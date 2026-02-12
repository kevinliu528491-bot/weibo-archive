from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
import sys
from pydantic import BaseModel
from typing import List, Optional

from fastapi.staticfiles import StaticFiles

app = FastAPI(title="Weibo Scraper API")

# Mount static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Serve index.html at root
from fastapi.responses import FileResponse
@app.get("/")
async def read_index():
    return FileResponse(os.path.join(STATIC_DIR, 'index.html'))

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
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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
            p['images'] = json.loads(p['images']) if p['images'] else []
        except:
            p['images'] = []
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
from scraper import run_scraper

# Scheduler configuration
def run_schedule():
    uid = os.getenv("WEIBO_UID")
    cookie = os.getenv("WEIBO_COOKIE")
    if not uid or not cookie:
        print("Scheduler: Missing UID or COOKIE, skipping.", file=sys.stderr)
        return

    # Run once on startup
    print("Scheduler: Running initial scrape...", file=sys.stderr)
    try:
        run_scraper(uid, cookie)
    except Exception as e:
        print(f"Scheduler: Initial scrape failed: {e}", file=sys.stderr)

    # Schedule daily run (e.g., at 10:00 AM or just every 24h)
    schedule.every().day.at("12:00").do(run_scraper, uid=uid, cookie=cookie, days_back=3)
    schedule.every().day.at("22:00").do(run_scraper, uid=uid, cookie=cookie, days_back=3)
    
    print("Scheduler: Started. Running daily at 12:00 and 22:00.", file=sys.stderr)
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            print(f"Scheduler: Error during run_pending: {e}", file=sys.stderr)
        time.sleep(60)

@app.on_event("startup")
def start_scheduler():
    t = threading.Thread(target=run_schedule, daemon=True)
    t.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
