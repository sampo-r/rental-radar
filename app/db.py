import sqlite3
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

DB_PATH = os.environ.get("DB_PATH", "/app/data/rentals.db")

def get_db_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Listings table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS listings (
        id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        external_id TEXT NOT NULL,
        url TEXT NOT NULL,
        title TEXT,
        address TEXT,
        district TEXT,
        price REAL,
        initial_price REAL,
        size REAL,
        rooms INTEGER,
        room_structure TEXT,
        floor INTEGER,
        total_floors INTEGER,
        build_year INTEGER,
        description TEXT,
        landlord_type TEXT,
        thumbnail_url TEXT,
        image_count INTEGER DEFAULT 0,
        first_seen_at TIMESTAMP NOT NULL,
        last_seen_at TIMESTAMP NOT NULL,
        delisted_at TIMESTAMP,
        days_on_market REAL,
        status TEXT DEFAULT 'active'
    )
    ''')
    
    # Price history table (tracks price drops)
    cur.execute('''
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id TEXT NOT NULL,
        price REAL NOT NULL,
        recorded_at TIMESTAMP NOT NULL,
        FOREIGN KEY (listing_id) REFERENCES listings (id)
    )
    ''')
    
    # Images table
    cur.execute('''
    CREATE TABLE IF NOT EXISTS images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        listing_id TEXT NOT NULL,
        original_url TEXT NOT NULL,
        local_path TEXT NOT NULL,
        downloaded_at TIMESTAMP NOT NULL,
        ai_tags TEXT,
        FOREIGN KEY (listing_id) REFERENCES listings (id)
    )
    ''')
    
    conn.commit()
    conn.close()

def upsert_listing(data: Dict[str, Any]) -> tuple[bool, bool]:
    """
    Returns (is_new, price_changed)
    """
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    
    cur.execute("SELECT id, price, status, first_seen_at FROM listings WHERE id = ?", (data['id'],))
    row = cur.fetchone()
    
    is_new = False
    price_changed = False
    
    if row is None:
        is_new = True
        cur.execute('''
        INSERT INTO listings (
            id, source, external_id, url, title, address, district,
            price, initial_price, size, rooms, room_structure, floor,
            total_floors, build_year, description, landlord_type,
            thumbnail_url, image_count, first_seen_at, last_seen_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
        ''', (
            data['id'], data['source'], data['external_id'], data['url'],
            data.get('title'), data.get('address'), data.get('district'),
            data.get('price'), data.get('price'), data.get('size'),
            data.get('rooms'), data.get('room_structure'), data.get('floor'),
            data.get('total_floors'), data.get('build_year'), data.get('description'),
            data.get('landlord_type', 'private'), data.get('thumbnail_url'),
            data.get('image_count', 0), now, now
        ))
        
        # Insert initial price history
        if data.get('price'):
            cur.execute(
                "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?, ?, ?)",
                (data['id'], data['price'], now)
            )
    else:
        old_price = row['price']
        new_price = data.get('price')
        if new_price and new_price != old_price:
            price_changed = True
            cur.execute(
                "INSERT INTO price_history (listing_id, price, recorded_at) VALUES (?, ?, ?)",
                (data['id'], new_price, now)
            )
            
        cur.execute('''
        UPDATE listings SET
            last_seen_at = ?,
            price = ?,
            status = 'active',
            delisted_at = NULL,
            thumbnail_url = COALESCE(?, thumbnail_url)
        WHERE id = ?
        ''', (now, new_price or old_price, data.get('thumbnail_url'), data['id']))
        
    conn.commit()
    conn.close()
    return is_new, price_changed

def mark_delisted_missing(current_active_ids: set[str], source: str):
    """Marks listings not seen in the latest run as delisted/rented and calculates DOM."""
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now()
    now_str = now.isoformat()
    
    cur.execute("SELECT id, first_seen_at FROM listings WHERE source = ? AND status = 'active'", (source,))
    rows = cur.fetchall()
    
    for r in rows:
        lid = r['id']
        if lid not in current_active_ids:
            first_seen = datetime.fromisoformat(r['first_seen_at'])
            dom_days = round((now - first_seen).total_seconds() / 86400, 1)
            cur.execute('''
            UPDATE listings SET
                status = 'rented',
                delisted_at = ?,
                days_on_market = ?
            WHERE id = ?
            ''', (now_str, dom_days, lid))
            
    conn.commit()
    conn.close()
