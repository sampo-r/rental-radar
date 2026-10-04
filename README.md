# Rental Radar (Taka-Töölö Rental Market Intelligence)

A self-hosted, containerized agent that scrapes **Oikotie** and **Vuokraovi** daily, tracks rental listings over time, saves photos locally, records market velocity (Days on Market / time-to-rent), tracks price drops, and provides a web dashboard.

---

## Quick Start on Your Linux Server

### 1. Clone or copy files
Copy the `rental-radar` directory to your server (e.g. `~/rental-radar`).

### 2. Run with Docker Compose
```bash
cd rental-radar
docker compose up -d --build
```

That's it! The container will:
1. Run an initial scrape immediately.
2. Initialize SQLite at `./data/rentals.db`.
3. Download photos into `./data/photos/{listing_id}/`.
4. Start a web dashboard on port `8080`.
5. Schedule a daily scrape at 07:00 (Europe/Helsinki time).

---

## Accessing the Dashboard

Open in your browser:
```
http://<your-server-ip>:8080
```
From here you can:
* View active listings vs. rented/delisted listings.
* See price drops and Days on Market (DOM).
* Browse high-res photos saved on disk.
* Trigger a manual scrape at any time.

---

## Customizing Filters (`config.yaml`)

Edit `config.yaml` to adjust search criteria:
```yaml
search:
  location_name: "Taka-Töölö, Helsinki"
  city: "helsinki"
  district: "taka-toolo"
  price_max: 1050
  price_min: 700
  size_min: 27
  size_max: 38
  room_counts: [1, 2] # 1 or 2 rooms

scraper:
  download_images: true
  max_images_per_listing: 12
```

Restart to apply changes:
```bash
docker compose restart
```

---

## Instant Notifications (Telegram / Discord)

Add environment variables in `docker-compose.yml`:

```yaml
environment:
  - TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
  - TELEGRAM_CHAT_ID=-100123456789
  # or
  - DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```
You'll receive alerts whenever:
* A new listing is posted with its rent, size, and photos.
* A landlord cuts their asking price.

---

## Data & Backups

All state is stored inside the local `./data` folder on your server:
* `data/rentals.db`: SQLite database with all historical listings and price changes.
* `data/photos/`: Folder hierarchy of downloaded listing photos.
