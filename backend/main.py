from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
import sys
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime as _dt2

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Weibo Scraper API")

# Mount static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
COOKIE_FILE = os.path.join(BASE_DIR, "cookie.txt")

# ── Cookie state ──────────────────────────────────────────────
_cookie_state = {
    "cookie": "",
    "status": "unknown",       # "ok" | "expired" | "unknown"
    "last_updated": None,      # ISO timestamp of last cookie update
    "last_checked": None,      # ISO timestamp of last scraper run
}

def _load_cookie():
    """Load cookie from cookie.txt, falling back to env var."""
    if os.path.exists(COOKIE_FILE):
        with open(COOKIE_FILE, "r") as f:
            val = f.read().strip()
            if val:
                _cookie_state["cookie"] = val
                _cookie_state["last_updated"] = _dt2.fromtimestamp(os.path.getmtime(COOKIE_FILE)).isoformat()
                return
    env = os.getenv("WEIBO_COOKIE", "")
    if env:
        _cookie_state["cookie"] = env

def _save_cookie(cookie_value: str):
    """Persist cookie to cookie.txt and update runtime state."""
    with open(COOKIE_FILE, "w") as f:
        f.write(cookie_value)
    _cookie_state["cookie"] = cookie_value
    _cookie_state["status"] = "unknown"
    _cookie_state["last_updated"] = _dt2.now().isoformat()

_load_cookie()  # Load on import

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

DB_PATH = os.path.join(BASE_DIR, "weibo_data.db")

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

# ── Cookie management endpoints ──────────────────────────────
class CookieUpdate(BaseModel):
    cookie: str

@app.get("/api/cookie-status")
def get_cookie_status():
    return {
        "status": _cookie_state["status"],
        "last_updated": _cookie_state["last_updated"],
        "last_checked": _cookie_state["last_checked"],
        "has_cookie": bool(_cookie_state["cookie"]),
    }

@app.post("/api/cookie")
def update_cookie(body: CookieUpdate):
    val = body.cookie.strip()
    if not val:
        raise HTTPException(status_code=400, detail="Cookie cannot be empty")
    _save_cookie(val)
    # Also update env var so scheduler thread picks it up
    os.environ["WEIBO_COOKIE"] = val
    return {"ok": True, "message": "Cookie updated"}

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

def _get_cookie():
    """Get current cookie – prefer runtime state over env."""
    return _cookie_state["cookie"] or os.getenv("WEIBO_COOKIE", "")

def _do_scrape(uid, cookie, days_back=1):
    """Run a single scrape + export + sync cycle."""
    result = run_scraper(uid=uid, cookie=cookie, days_back=days_back)
    if result == "cookie_expired":
        _cookie_state["status"] = "expired"
        _cookie_state["last_checked"] = _dt2.now().isoformat()
        _log("Cookie appears expired!")
    else:
        _cookie_state["status"] = "ok"
        _cookie_state["last_checked"] = _dt2.now().isoformat()
    _log("Exporting static files...")
    export_stats()
    export_posts()

    disk = shutil.disk_usage("/")
    free_gb = disk.free / (1024**3)
    _log(f"Disk free: {free_gb:.1f} GiB")
    if free_gb >= 1.0:
        sync_content()
    else:
        _log("Skipped git sync due to low disk space.")
    return result

def run_schedule():
    """Main scheduler loop. Runs initial scrape, then schedules daily runs."""
    uid = os.getenv("WEIBO_UID")
    cookie = _get_cookie()
    if not uid or not cookie:
        _log("Missing UID or COOKIE, skipping.")
        return

    # Run once on startup
    _log("Running initial scrape...")
    try:
        _do_scrape(uid, cookie, days_back=1)
        _log("Initial scrape completed successfully.")
    except Exception as e:
        import traceback
        _log(f"Initial scrape failed: {e}")
        traceback.print_exc(file=sys.stderr)

    # Schedule daily run
    def run_wrapper():
        _log("=== Scheduled run starting ===")
        try:
            cookie = _get_cookie()  # re-read in case updated via UI
            _do_scrape(uid, cookie, days_back=3)
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
            try:
                next_run = schedule.next_run()
                _log(f"Heartbeat: alive. Next scheduled run: {next_run}")
            except Exception:
                _log("Heartbeat: alive. (could not determine next run)")
            heartbeat_counter = 0

# ── Scheduler supervisor ──────────────────────────────────────
# The supervisor thread monitors the scheduler thread and restarts
# it automatically if it crashes, with exponential backoff.

_scheduler_thread = None
_scheduler_lock = threading.Lock()

def _start_scheduler_thread():
    """Start (or restart) the scheduler thread."""
    global _scheduler_thread
    with _scheduler_lock:
        # Clear any existing schedule jobs to avoid duplicates on restart
        schedule.clear()
        _scheduler_thread = threading.Thread(
            target=run_schedule, daemon=True, name="scheduler"
        )
        _scheduler_thread.start()
        _log(f"Scheduler thread started (tid={_scheduler_thread.ident})")

def _supervisor():
    """Supervisor loop: watches the scheduler thread and restarts it if dead."""
    restart_count = 0
    max_backoff = 300  # 5 minutes max

    # Wait for initial startup
    time.sleep(5)

    while True:
        try:
            with _scheduler_lock:
                thread = _scheduler_thread

            if thread is None or not thread.is_alive():
                if thread is not None:
                    restart_count += 1
                    backoff = min(30 * restart_count, max_backoff)
                    _log(f"⚠️  Scheduler thread DIED! Restart #{restart_count}, "
                         f"waiting {backoff}s before restart...")
                    time.sleep(backoff)
                _log("Restarting scheduler thread...")
                _start_scheduler_thread()
            else:
                # Thread is alive, reset restart count (successful period)
                if restart_count > 0:
                    restart_count = 0
        except Exception as e:
            _log(f"Supervisor error: {e}")

        time.sleep(30)  # Check every 30 seconds

@app.on_event("startup")
def start_scheduler():
    _start_scheduler_thread()
    # Start the supervisor that watches the scheduler
    supervisor = threading.Thread(target=_supervisor, daemon=True, name="supervisor")
    supervisor.start()
    _log("Supervisor thread started.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
