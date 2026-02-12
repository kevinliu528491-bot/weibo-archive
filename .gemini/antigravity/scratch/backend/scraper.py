import sys
print("Script starting...", file=sys.stderr)
import requests
import sqlite3
import time
import json
import os
from datetime import datetime, timedelta
import pandas as pd

# Configuration
DB_PATH = "weibo_data.db"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
    "MWeibo-Pwa": "1",
    "Referer": "https://m.weibo.cn/",
}

def parse_weibo_date(date_str):
    """Parse Weibo's date format into a datetime object."""
    now = datetime.now()
    if "Just now" in date_str or "mins ago" in date_str or "min ago" in date_str:
        return now
    if "hr ago" in date_str or "hrs ago" in date_str:
        return now # Approximate to today
    if "Yesterday" in date_str:
        return now - timedelta(days=1)
    
    # Chinese formats often seen: "刚刚", "x分钟前", "x小时前", "昨天", "MM-DD", "YYYY-MM-DD"
    # Full format: "Sun Nov 30 12:46:08 +0800 2025"
    
    try:
        # Try full format first
        dt = datetime.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        # Convert to local time and make naive to match datetime.now()
        return dt.astimezone(None).replace(tzinfo=None)
    except:
        pass

    try:
        if "-" in date_str:
            parts = date_str.split("-")
            if len(parts) == 2: # MM-DD
                return datetime(now.year, int(parts[0]), int(parts[1]))
            elif len(parts) == 3: # YYYY-MM-DD
                return datetime(int(parts[0]), int(parts[1]), int(parts[2]))
    except:
        pass
        
    # Fallback: try standard parsing or return now if unknown
    return now

def init_db():
    """Initialize the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Posts table
    c.execute('''CREATE TABLE IF NOT EXISTS posts (
                    id TEXT PRIMARY KEY,
                    text TEXT,
                    created_at TEXT,
                    created_at_ts REAL,
                    reposts_count INTEGER,
                    comments_count INTEGER,
                    attitudes_count INTEGER,
                    images TEXT,
                    raw_json TEXT
                )''')
    
    # Comments table (only storing comments where the blogger replied or interesting ones)
    c.execute('''CREATE TABLE IF NOT EXISTS comments (
                    id TEXT PRIMARY KEY,
                    post_id TEXT,
                    user_name TEXT,
                    text TEXT,
                    created_at TEXT,
                    reply_text TEXT,
                    reply_created_at TEXT,
                    FOREIGN KEY(post_id) REFERENCES posts(id)
                )''')
    
    conn.commit()
    conn.close()

def get_long_text(post_id, cookie):
    """Fetch full text for long posts."""
    url = "https://m.weibo.cn/statuses/extend"
    params = {"id": post_id}
    headers = HEADERS.copy()
    headers["Cookie"] = cookie
    
    try:
        response = requests.get(url, params=params, headers=headers)
        if response.status_code == 200:
            data = response.json()
            if data.get("ok") == 1:
                return data.get("data", {}).get("longTextContent", "")
    except Exception as e:
        print(f"Error fetching long text for {post_id}: {e}", file=sys.stderr)
    return None

def get_posts(uid, container_id, cookie, page=1):
    """Fetch posts for a user, supporting pagination."""
    url = "https://m.weibo.cn/api/container/getIndex"
    params = {
        "type": "uid",
        "value": uid,
        "containerid": container_id,
        "page": page
    }
    headers = HEADERS.copy()
    headers["Cookie"] = cookie
    
    try:
        print(f"Fetching page {page}...", file=sys.stderr)
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if data.get("ok") == 1:
            cards = data.get("data", {}).get("cards", [])
            print(f"Success! Found {len(cards)} cards on page {page}.", file=sys.stderr)
            return cards
        else:
            print(f"Error fetching posts page {page}: {data}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"Exception fetching posts: {e}", file=sys.stderr)
        return []

def get_comments(post_id, cookie):
    """Fetch comments for a post."""
    url = "https://m.weibo.cn/comments/hotflow"
    params = {
        "id": post_id,
        "mid": post_id,
        "max_id_type": 0
    }
    headers = HEADERS.copy()
    headers["Cookie"] = cookie
    
    comments = []
    try:
        response = requests.get(url, params=params, headers=headers)
        # hotflow might return 404 or empty if no hot comments, try regular flow if needed?
        # For now, let's stick to hotflow or simple 'comments/hot'
        
        if response.status_code == 200:
            data = response.json()
            if data.get("ok") == 1:
                comments = data["data"]["data"]
    except Exception as e:
        print(f"Exception fetching comments for {post_id}: {e}", file=sys.stderr)
    
    return comments

def save_post(post, cookie=None):
    """Save post to DB."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    mblog = post.get("mblog", {})
    if not mblog:
        return None

    pid = mblog.get("id")
    text = mblog.get("text")
    
    # Handle Long Text
    if mblog.get("isLongText") and cookie:
        print(f"Fetching full text for {pid}...", file=sys.stderr)
        full_text = get_long_text(pid, cookie)
        if full_text:
            text = full_text

    created_at = mblog.get("created_at")
    
    # Parse date to timestamp for sorting
    try:
        dt = parse_weibo_date(created_at)
        created_at_ts = dt.timestamp()
    except:
        created_at_ts = 0.0

    reposts = mblog.get("reposts_count")
    comments_c = mblog.get("comments_count")
    attitudes = mblog.get("attitudes_count")
    
    # Handle Images
    images = []
    pics = mblog.get("pics", [])
    if pics:
        for pic in pics:
            # Prefer large image
            url = pic.get("large", {}).get("url") or pic.get("url")
            if url:
                images.append(url)
    images_json = json.dumps(images)
    
    try:
        c.execute('''INSERT OR REPLACE INTO posts 
                     (id, text, created_at, created_at_ts, reposts_count, comments_count, attitudes_count, images, raw_json) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (pid, text, created_at, created_at_ts, reposts, comments_c, attitudes, images_json, json.dumps(mblog)))
    except sqlite3.OperationalError:
        # Column might not exist yet if migration hasn't run. 
        pass
    
    conn.commit()
    conn.close()
    return pid

def save_comment_with_reply(post_id, comment, blogger_uid):
    """Check if blogger replied to this comment and save if so."""
    # In m.weibo.cn API, comments often have a 'comments' field if there are sub-comments (replies).
    # Or sometimes the blogger replies directly in the comment list?
    # Usually, we look for sub-comments where user.id == blogger_uid.
    
    # NOTE: The structure of 'comment' object needs to be inspected.
    # Typically: comment['comments'] is a list of replies.
    
    replies = comment.get("comments", [])
    blogger_reply = None
    
    if replies:
        for reply in replies:
            if str(reply.get("user", {}).get("id")) == str(blogger_uid):
                blogger_reply = reply
                break
    
    # If we found a reply from the blogger
    if blogger_reply:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        cid = comment.get("id")
        user_name = comment.get("user", {}).get("screen_name")
        text = comment.get("text")
        created_at = comment.get("created_at")
        
        reply_text = blogger_reply.get("text")
        reply_created_at = blogger_reply.get("created_at")
        
        c.execute('''INSERT OR REPLACE INTO comments 
                     (id, post_id, user_name, text, created_at, reply_text, reply_created_at) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (cid, post_id, user_name, text, created_at, reply_text, reply_created_at))
        
        conn.commit()
        conn.close()
        print(f"Saved reply for comment {cid}", file=sys.stderr)

def export_to_excel():
    """Export DB content to Excel."""
    conn = sqlite3.connect(DB_PATH)
    
    # Export Posts
    posts_df = pd.read_sql_query("SELECT * FROM posts", conn)
    
    # Export Comments
    comments_df = pd.read_sql_query("SELECT * FROM comments", conn)
    
    conn.close()
    
    output_file = "weibo_history.xlsx"
    with pd.ExcelWriter(output_file) as writer:
        posts_df.to_excel(writer, sheet_name="Posts", index=False)
        comments_df.to_excel(writer, sheet_name="Comments", index=False)
    
    print(f"Exported data to {output_file}", file=sys.stderr)

def run_scraper(uid, cookie, days_back=1):
    print(f"Starting scrape for user {uid} (Last {days_back} days)...", file=sys.stderr)
    init_db()
    
    container_id = f"107603{uid}"
    page = 1
    cutoff_date = datetime.now() - timedelta(days=days_back)
    keep_scraping = True
    consecutive_old_posts = 0
    
    while keep_scraping:
        cards = get_posts(uid, container_id, cookie, page)
        if not cards:
            break
            
        for card in cards:
            if card.get("card_type") == 9:
                mblog = card.get("mblog", {})
                created_at_str = mblog.get("created_at", "")
                post_date = parse_weibo_date(created_at_str)
                
                # Check if pinned post (isTop)
                is_top = mblog.get("isTop", 0)
                
                if post_date < cutoff_date:
                    if is_top:
                        print(f"Found old pinned post ({created_at_str}). Ignoring for stop condition...", file=sys.stderr)
                    else:
                        consecutive_old_posts += 1
                        print(f"Found post older than {days_back} days ({created_at_str}). Consecutive count: {consecutive_old_posts}", file=sys.stderr)
                        if consecutive_old_posts >= 10:
                           print("Reached 10 consecutive old posts. Stopping.", file=sys.stderr)
                           keep_scraping = False
                           break
                        continue # Skip saving this old post but don't stop yet
                else:
                    consecutive_old_posts = 0 # Reset counter if we find a new post
                
                pid = save_post(card, cookie)
                if pid:
                    print(f"Processing post {pid} ({created_at_str})...", file=sys.stderr)
                    comments = get_comments(pid, cookie)
                    for comment in comments:
                        save_comment_with_reply(pid, comment, uid)
                    time.sleep(1) 
        
        page += 1
        time.sleep(2)

    export_to_excel()

if __name__ == "__main__":
    # Load config from env or args
    UID = os.getenv("WEIBO_UID")
    COOKIE = os.getenv("WEIBO_COOKIE")
    DAYS = int(os.getenv("WEIBO_DAYS", 3)) # Default to 3 days for safety
    
    if not UID or not COOKIE:
        print("Please set WEIBO_UID and WEIBO_COOKIE environment variables.", file=sys.stderr)
    else:
        run_scraper(UID, COOKIE, days_back=DAYS)
