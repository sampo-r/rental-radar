import os
import yaml
import logging
import asyncio
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import uvicorn

from app.db import init_db, upsert_listing, mark_delisted_missing
from app.scrapers.oikotie import OikotieScraper
from app.scrapers.vuokraovi import VuokraoviScraper
from app.images import download_listing_images
from app.web import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("rental-radar")

CONFIG_PATH = os.environ.get("CONFIG_PATH", "config.yaml")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

config = load_config()

def send_alert(message: str):
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tg_token and tg_chat:
        try:
            requests.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                json={"chat_id": tg_chat, "text": message, "parse_mode": "Markdown"},
                timeout=10
            )
        except Exception as e:
            logger.warning("Telegram alert failed: %s", e)

    discord_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if discord_url:
        try:
            requests.post(discord_url, json={"content": message}, timeout=10)
        except Exception as e:
            logger.warning("Discord alert failed: %s", e)

def run_scrape_cycle():
    logger.info("=== Starting Daily Rental Radar Scrape Cycle ===")
    
    # 1. Scrape Oikotie
    oikotie = OikotieScraper(config)
    oikotie_listings = oikotie.fetch_listings()
    
    # 2. Scrape Vuokraovi
    vuokraovi = VuokraoviScraper(config)
    vuokraovi_listings = vuokraovi.fetch_listings()
    
    all_listings = oikotie_listings + vuokraovi_listings
    logger.info("Total listings fetched across all sources: %d", len(all_listings))
    
    new_count = 0
    price_change_count = 0
    active_ids_by_source = {"oikotie": set(), "vuokraovi": set()}
    download_images = config.get("scraper", {}).get("download_images", True)
    max_images = config.get("scraper", {}).get("max_images_per_listing", 12)

    for item in all_listings:
        src = item["source"]
        active_ids_by_source[src].add(item["id"])
        
        is_new, price_changed = upsert_listing(item)
        if is_new:
            new_count += 1
            logger.info("NEW LISTING: %s (%s €/mo, %s m²)", item.get('title'), item.get('price'), item.get('size'))
            send_alert(f"🚨 *New Rental in Taka-Töölö*: {item.get('title')}\nRent: {item.get('price')} €/mo ({item.get('size')} m²)\n[View Ad]({item.get('url')})")
            
            # Download images for new listings
            if download_images and item.get("image_urls"):
                download_listing_images(item["id"], item["image_urls"], max_images=max_images)
                
        elif price_changed:
            price_change_count += 1
            logger.info("PRICE CHANGED: %s -> %s €", item.get('id'), item.get('price'))
            send_alert(f"📉 *Price Cut in Taka-Töölö*: {item.get('title')} is now {item.get('price')} €/mo\n[View Ad]({item.get('url')})")

    # 3. Mark delisted / rented listings
    for src, active_ids in active_ids_by_source.items():
        mark_delisted_missing(active_ids, src)

    logger.info("Scrape finished. %d new listings, %d price changes recorded.", new_count, price_change_count)

@app.post("/api/run")
def trigger_manual_run():
    asyncio.get_event_loop().run_in_executor(None, run_scrape_cycle)
    return {"status": "started"}

def start_scheduler():
    scheduler = BackgroundScheduler()
    cron_hour = int(os.environ.get("CRON_HOUR", "7"))
    cron_minute = int(os.environ.get("CRON_MINUTE", "0"))
    
    scheduler.add_job(
        run_scrape_cycle,
        "cron",
        hour=cron_hour,
        minute=cron_minute,
        name="daily_rental_scrape"
    )
    scheduler.start()
    logger.info("Scheduler started. Daily run scheduled at %02d:%02d Europe/Helsinki", cron_hour, cron_minute)

if __name__ == "__main__":
    init_db()
    start_scheduler()
    
    # Run once on startup if enabled
    if os.environ.get("RUN_ON_STARTUP", "true").lower() == "true":
        logger.info("Triggering initial scrape on startup...")
        import threading
        threading.Thread(target=run_scrape_cycle, daemon=True).start()

    server_cfg = config.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = server_cfg.get("port", 8080)
    logger.info("Starting web server on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)
