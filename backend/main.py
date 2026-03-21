from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
import sys
from pydantic import BaseModel
from typing import List, Optional

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Weibo Scraper API")

# Mount static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# API routes must act first
# ... (API routes are defined below, but we must ensure static mount doesn't shadow them if we mount at root)

# Instead of specific file routes, let's mount /images explicitly
app.mount("/images", StaticFiles(directory=os.path.join(STATIC_DIR, "images")), name="images")

# Serve specific files for the SPA/Frontend
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))

@app.get("/app.js")
async def read_js():
    return FileResponse(os.path.join(STATIC_DIR, 'app.js'))

@app.get("/style.css")
async def read_css():
    return FileResponse(os.path.join(STATIC_DIR, 'style.css'))

@app.get("/stats.json")
async def read_stats_json():
    return FileResponse(os.path.join(STATIC_DIR, 'stats.json'))

@app.get("/posts.json")
async def read_posts_json():
    return FileResponse(os.path.join(STATIC_DIR, 'posts.json'))

# Fallback/Root mount for other static assets if needed, but the above covers most.
# Removing the generic /static mount to avoid confusion or keep it at /static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Enable CORS for development (optional if serving from same origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "weibo_data.db"

class Post(BaseModel):
    id: str
    text: str
    created_at: str
    created_at_ts: float = 0.0
    reposts_count: int
    comments_count: int
    attitudes_count: int
    images: List[str] = []
    # raw_json is internal, maybe don't expose it or expose parsed fields

class Comment(BaseModel):
    id: str
    post_id: str
    user_name: str
    text: str
    created_at: str
    reply_text: Optional[str] = None
    reply_created_at: Optional[str] = None

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.row_factory = sqlite3.Row
    return conn

import hashlib

def get_image_filename(url):
    """Generate a unique filename for the image based on its URL.
    
    Uses only the base URL (without query params) for hashing, so the same
    image served with different signed URLs maps to the same local file.
    """
    if not url:
        return None
    base_url = url.split('?')[0]  # Strip query params (Expires, ssig, etc.)
    try:
        ext = os.path.splitext(base_url)[1]
        if not ext:
            ext = ".jpg" # Default
    except:
        ext = ".jpg"
        
    hash_obj = hashlib.md5(base_url.encode())
    return f"{hash_obj.hexdigest()}{ext}"

@app.get("/api/posts", response_model=List[Post])
def get_posts():
    conn = get_db_connection()
    posts = conn.execute('SELECT * FROM posts ORDER BY created_at_ts DESC').fetchall()
    conn.close()
    
    results = []
    for post in posts:
        p = dict(post)
        # Parse images JSON
        try:
            images = json.loads(p['images']) if p['images'] else []
        except:
            images = []
        
        # Transform to local paths
        local_images = []
        for url in images:
            filename = get_image_filename(url)
            # Check if file exists? Optimistically return local path
            # The client will try to load it. If it doesn't exist, it 404s.
            # But effectively we are simulating what export_static does.
            local_images.append(f"images/{filename}")
            
        p['images'] = local_images
        results.append(p)
        
    return results

@app.get("/api/posts/{post_id}/comments", response_model=List[Comment])
def get_post_comments(post_id: str):
    conn = get_db_connection()
    comments = conn.execute('SELECT * FROM comments WHERE post_id = ? ORDER BY created_at DESC', (post_id,)).fetchall()
    conn.close()
    return [dict(comment) for comment in comments]

@app.get("/api/stats")
def get_stats():
    conn = get_db_connection()
    post_count = conn.execute('SELECT COUNT(*) FROM posts').fetchone()[0]
    comment_count = conn.execute('SELECT COUNT(*) FROM comments').fetchone()[0]
    conn.close()
    return {"posts": post_count, "comments": comment_count}

import threading
import schedule
import time
import shutil
from datetime import datetime as _dt
from scraper import run_scraper
from git_sync import sync_content
from export_static import export_stats, export_posts

# Scheduler configuration
def _log(msg):
    """Log with timestamp for scheduler messages."""
    ts = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Scheduler: {msg}", file=sys.stderr, flush=True)

def run_schedule():
    uid = os.getenv("WEIBO_UID")
    cookie = os.getenv("WEIBO_COOKIE")
    if not uid or not cookie:
        _log("Missing UID or COOKIE, skipping.")
        return

    # Run once on startup
    _log("Running initial scrape...")
    try:
        run_scraper(uid, cookie)
        _log("Exporting static files...")
        export_stats()
        export_posts()
        sync_content()  # Sync after initial scrape
        _log("Initial scrape completed successfully.")
    except Exception as e:
        import traceback
        _log(f"Initial scrape failed: {e}")
        traceback.print_exc(file=sys.stderr)

    # Schedule daily run
    def run_wrapper():
        _log("=== Scheduled run starting ===")
        try:
            # Check disk space before running
            disk = shutil.disk_usage("/")
            free_gb = disk.free / (1024**3)
            _log(f"Disk free: {free_gb:.1f} GiB")
            if free_gb < 1.0:
                _log("WARNING: Less than 1 GiB free. Skipping git sync but still scraping.")

            run_scraper(uid=uid, cookie=cookie, days_back=3)
            _log("Exporting static files...")
            export_stats()
            export_posts()

            if free_gb >= 1.0:
                sync_content()
            else:
                _log("Skipped git sync due to low disk space.")

            _log("=== Scheduled run completed successfully ===")
        except Exception as e:
            import traceback
            _log(f"Failed during scheduled run: {e}")
            traceback.print_exc(file=sys.stderr)

    schedule.every().day.at("08:00").do(run_wrapper)
    schedule.every().day.at("12:00").do(run_wrapper)
    schedule.every().day.at("22:00").do(run_wrapper)
    
    _log("Started. Running daily at 08:00, 12:00 and 22:00 with GitHub sync.")
    heartbeat_counter = 0
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            import traceback
            _log(f"Error during run_pending: {e}")
            traceback.print_exc(file=sys.stderr)
        time.sleep(60)
        heartbeat_counter += 1
        if heartbeat_counter >= 30:  # Log heartbeat every 30 minutes
            next_run = schedule.next_run()
            _log(f"Heartbeat: alive. Next scheduled run: {next_run}")
            heartbeat_counter = 0

@app.on_event("startup")
def start_scheduler():
    t = threading.Thread(target=run_schedule, daemon=True)
    t.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
