import os
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.db import get_db_connection

app = FastAPI(title="Rental Radar API & Dashboard")

PHOTO_DIR = os.environ.get("PHOTO_DIR", "/app/data/photos")

# Serve static images if folder exists
if os.path.exists(PHOTO_DIR):
    app.mount("/photos", StaticFiles(directory=PHOTO_DIR), name="photos")

@app.get("/api/listings")
def get_listings():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
    SELECT l.*, 
           (SELECT COUNT(*) FROM images i WHERE i.listing_id = l.id) as local_image_count,
           (SELECT COUNT(*) FROM price_history ph WHERE ph.listing_id = l.id) as price_change_count
    FROM listings l
    ORDER BY l.status ASC, l.last_seen_at DESC
    ''')
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"listings": rows}

@app.get("/api/stats")
def get_stats():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM listings WHERE status = 'active'")
    active_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM listings WHERE status = 'rented'")
    rented_count = cur.fetchone()[0]
    
    cur.execute("SELECT AVG(price), AVG(price/size) FROM listings WHERE status = 'active' AND price IS NOT NULL AND size IS NOT NULL")
    r_avg = cur.fetchone()
    avg_price = round(r_avg[0], 1) if r_avg[0] else 0
    avg_sqm = round(r_avg[1], 1) if r_avg[1] else 0

    cur.execute("SELECT AVG(days_on_market) FROM listings WHERE status = 'rented' AND days_on_market IS NOT NULL")
    r_dom = cur.fetchone()
    avg_dom = round(r_dom[0], 1) if r_dom[0] else 0
    
    conn.close()
    return {
        "active_count": active_count,
        "rented_count": rented_count,
        "avg_price": avg_price,
        "avg_sqm_price": avg_sqm,
        "avg_days_on_market": avg_dom
    }

@app.get("/", response_class=HTMLResponse)
def index_page():
    return """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>Rental Radar • Taka-Töölö Dashboard</title>
      <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-slate-900 text-slate-100 min-h-screen p-4 sm:p-6 antialiased">
      <div class="max-w-6xl mx-auto space-y-6">
        
        <!-- Header -->
        <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-800 pb-5">
          <div>
            <div class="flex items-center gap-2">
              <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
              <span class="text-xs uppercase tracking-wider text-slate-400 font-semibold">Live Market Intelligence</span>
            </div>
            <h1 class="text-2xl font-bold mt-1">Rental Radar • Taka-Töölö</h1>
            <p class="text-sm text-slate-400 mt-0.5">Tracking Oikotie & Vuokraovi listings and photos</p>
          </div>
          <button onclick="triggerManualScrape()" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 rounded-lg text-sm font-semibold transition">
            🔄 Run Scraper Now
          </button>
        </div>

        <!-- Metrics -->
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4" id="stats-container">
          <div class="p-4 bg-slate-800/80 border border-slate-700/60 rounded-xl">
            <div class="text-xs text-slate-400 uppercase font-medium">Active Listings</div>
            <div class="text-2xl font-bold mt-1 text-emerald-400" id="stat-active">-</div>
          </div>
          <div class="p-4 bg-slate-800/80 border border-slate-700/60 rounded-xl">
            <div class="text-xs text-slate-400 uppercase font-medium">Avg Rent</div>
            <div class="text-2xl font-bold mt-1 text-sky-400" id="stat-price">-</div>
          </div>
          <div class="p-4 bg-slate-800/80 border border-slate-700/60 rounded-xl">
            <div class="text-xs text-slate-400 uppercase font-medium">Avg €/m²</div>
            <div class="text-2xl font-bold mt-1 text-slate-100" id="stat-sqm">-</div>
          </div>
          <div class="p-4 bg-slate-800/80 border border-slate-700/60 rounded-xl">
            <div class="text-xs text-slate-400 uppercase font-medium">Avg Days to Rent</div>
            <div class="text-2xl font-bold mt-1 text-amber-400" id="stat-dom">-</div>
          </div>
        </div>

        <!-- Filter bar -->
        <div class="flex items-center gap-2 text-sm">
          <button onclick="filterListings('all')" id="btn-all" class="px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200">All</button>
          <button onclick="filterListings('active')" id="btn-active" class="px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200">Active</button>
          <button onclick="filterListings('rented')" id="btn-rented" class="px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200">Rented (Delisted)</button>
        </div>

        <!-- Cards Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4" id="listings-grid">
          <div class="p-8 text-center text-slate-400 col-span-2">Loading listings...</div>
        </div>

      </div>

      <script>
        let allListings = [];
        let currentFilter = 'all';

        async function loadData() {
          const statsRes = await fetch('/api/stats');
          const stats = await statsRes.json();
          document.getElementById('stat-active').textContent = stats.active_count;
          document.getElementById('stat-price').textContent = stats.avg_price + ' €';
          document.getElementById('stat-sqm').textContent = stats.avg_sqm_price + ' €/m²';
          document.getElementById('stat-dom').textContent = stats.avg_days_on_market + ' days';

          const listRes = await fetch('/api/listings');
          const data = await listRes.json();
          allListings = data.listings;
          renderListings();
        }

        function filterListings(f) {
          currentFilter = f;
          ['all', 'active', 'rented'].forEach(id => {
            const btn = document.getElementById('btn-' + id);
            if (id === f) {
              btn.className = 'px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 text-slate-200 font-semibold';
            } else {
              btn.className = 'px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200';
            }
          });
          renderListings();
        }

        function renderListings() {
          const container = document.getElementById('listings-grid');
          const filtered = allListings.filter(l => currentFilter === 'all' || l.status === currentFilter);

          if (filtered.length === 0) {
            container.innerHTML = '<div class="p-8 text-center text-slate-400 col-span-2">No listings found in this category.</div>';
            return;
          }

          container.innerHTML = filtered.map(l => {
            const isRented = l.status === 'rented';
            const statusBadge = isRented 
              ? `<span class="px-2 py-0.5 rounded text-xs bg-rose-500/20 text-rose-300 border border-rose-500/30">Rented in ${l.days_on_market || '?'} d</span>`
              : `<span class="px-2 py-0.5 rounded text-xs bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">Active</span>`;
            
            const priceCut = (l.initial_price && l.price && l.price < l.initial_price)
              ? `<span class="line-through text-slate-500 text-xs mr-2 font-mono">${l.initial_price}€</span>` : '';

            const sourceBadge = l.source === 'oikotie' ? 'Oikotie' : 'Vuokraovi';
            const img = l.thumbnail_url 
              ? `<img src="${l.thumbnail_url}" class="w-24 h-24 rounded-lg object-cover bg-slate-800 shrink-0">`
              : `<div class="w-24 h-24 rounded-lg bg-slate-800 border border-slate-700 flex items-center justify-center text-2xl shrink-0">🏢</div>`;

            return `
              <div class="p-4 bg-slate-800/80 border border-slate-700/60 rounded-xl flex flex-col justify-between hover:border-slate-500 transition">
                <div>
                  <div class="flex items-center justify-between gap-2 mb-2">
                    <div class="flex items-center gap-1.5">
                      ${statusBadge}
                      <span class="px-2 py-0.5 rounded text-xs bg-slate-700 text-slate-300">${sourceBadge}</span>
                    </div>
                    <span class="text-xs text-slate-400 font-mono">${l.address || l.district}</span>
                  </div>
                  <div class="flex gap-3 mt-3">
                    ${img}
                    <div class="flex-1 min-w-0">
                      <div class="flex items-baseline justify-between">
                        <div class="flex items-baseline">
                          ${priceCut}
                          <span class="text-xl font-bold text-slate-100">${l.price || '-'} €</span>
                          <span class="text-xs text-slate-400 ml-1">/mo</span>
                        </div>
                        <span class="text-xs font-mono text-slate-400">${l.size ? (l.price / l.size).toFixed(1) + ' €/m²' : ''}</span>
                      </div>
                      <div class="text-xs font-medium text-slate-300 mt-1">${l.size || '-'} m² • ${l.room_structure || (l.rooms ? l.rooms + 'h' : '')}</div>
                      <div class="text-[11px] text-slate-400 mt-2 truncate">${l.title || ''}</div>
                    </div>
                  </div>
                </div>
                <div class="mt-4 pt-3 border-t border-slate-700/60 flex items-center justify-between text-xs text-slate-400">
                  <span>📸 ${l.local_image_count || l.image_count || 0} saved photos</span>
                  <a href="${l.url}" target="_blank" class="text-sky-400 hover:underline">View Ad ↗</a>
                </div>
              </div>
            `;
          }).join('');
        }

        async function triggerManualScrape() {
          alert('Triggering manual scrape in background...');
          await fetch('/api/run', { method: 'POST' });
          setTimeout(loadData, 3000);
        }

        loadData();
      </script>
    </body>
    </html>
    """
