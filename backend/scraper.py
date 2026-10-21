import sys
print("Script starting...", file=sys.stderr)
import requests
import sqlite3
import time
import json
import os
import random
from datetime import datetime, timedelta
import pandas as pd

# Configuration
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_BACKEND_DIR, "weibo_data.db")

# ── Anti-detection: realistic mobile User-Agent pool ──────────
_USER_AGENTS = [
    # Safari on various iPhones
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_7_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    # Chrome on Android
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.144 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6045.163 Mobile Safari/537.36",
    # Edge on iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/124.0.2478.50 Version/17.0 Mobile/15E148 Safari/604.1",
]

def _pick_ua():
    """Pick a random User-Agent for this session."""
    return random.choice(_USER_AGENTS)

def _build_headers(cookie, ua=None, referer="https://m.weibo.cn/"):
    """Build realistic browser headers that mimic a real mobile browser session."""
    if ua is None:
        ua = _pick_ua()
    return {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": referer,
        "X-Requested-With": "XMLHttpRequest",
        "MWeibo-Pwa": "1",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Cookie": cookie,
    }

def _jitter(base_seconds, variance=0.5):
    """Sleep for base_seconds ± variance (randomised to avoid mechanical timing)."""
    delay = base_seconds + random.uniform(-variance, variance)
    delay = max(0.3, delay)  # never sleep less than 0.3s
    time.sleep(delay)

# Legacy constant kept for backward compatibility in case external code references it
HEADERS = {
    "User-Agent": _USER_AGENTS[0],
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
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL;')
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

def get_long_text(post_id, cookie, session=None, ua=None):
    """Fetch full text for long posts."""
    url = "https://m.weibo.cn/statuses/extend"
    params = {"id": post_id}
    headers = _build_headers(cookie, ua=ua, referer=f"https://m.weibo.cn/detail/{post_id}")
    
    _jitter(1.0, 0.5)  # small delay before fetching long text
    try:
        requester = session or requests
        response = requester.get(url, params=params, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            if data.get("ok") == 1:
                return data.get("data", {}).get("longTextContent", "")
    except Exception as e:
        print(f"Error fetching long text for {post_id}: {e}", file=sys.stderr)
    return None

def get_posts(uid, container_id, cookie, page=1, max_retries=5, session=None, ua=None):
    """Fetch posts for a user, supporting pagination.
    
    Retries up to max_retries times with exponential backoff + jitter when the
    API returns non-JSON responses (common Weibo anti-scraping behaviour).
    """
    url = "https://m.weibo.cn/api/container/getIndex"
    params = {
        "type": "uid",
        "value": uid,
        "containerid": container_id,
        "page": page
    }
    referer = f"https://m.weibo.cn/u/{uid}" if page == 1 else f"https://m.weibo.cn/u/{uid}?page={page}"
    headers = _build_headers(cookie, ua=ua, referer=referer)
    requester = session or requests
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Fetching page {page} (attempt {attempt}/{max_retries})...", file=sys.stderr)
            response = requester.get(url, params=params, headers=headers, timeout=30)
            response.raise_for_status()

            # ── Bot-detection check ──────────────────────────────────
            content_type = response.headers.get("Content-Type", "")
            if "text/html" in content_type:
                # Weibo served an HTML bot-challenge page instead of JSON
                wait = 10 * attempt + random.uniform(0, 5)
                print(f"Bot-detection HTML on page {page} attempt {attempt}. "
                      f"Waiting {wait:.0f}s...", file=sys.stderr)
                time.sleep(wait)
                continue

            data = response.json()
            
            if data.get("ok") == 1:
                cards = data.get("data", {}).get("cards", [])
                print(f"Success! Found {len(cards)} cards on page {page}.", file=sys.stderr)
                return cards
            else:
                msg = data.get("msg", "")
                print(f"Error fetching posts page {page}: {data}", file=sys.stderr)
                # Detect common auth-failure signals
                if "请先登录" in msg or "login" in msg.lower() or data.get("ok") == -100:
                    return "cookie_expired"
                return []
        except (ValueError, requests.exceptions.JSONDecodeError) as e:
            # Non-JSON response – likely anti-scraping throttle
            wait = 8 * attempt + random.uniform(0, 5)
            print(f"Non-JSON response on page {page} attempt {attempt}: {e}. "
                  f"Retrying in {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)
        except Exception as e:
            wait = 8 * attempt + random.uniform(0, 5)
            print(f"Exception fetching posts page {page} attempt {attempt}: {e}. "
                  f"Retrying in {wait:.0f}s...", file=sys.stderr)
            time.sleep(wait)

    print(f"All {max_retries} attempts failed for page {page}.", file=sys.stderr)
    return []

def get_comments(post_id, cookie, session=None, ua=None):
    """Fetch comments for a post."""
    url = "https://m.weibo.cn/comments/hotflow"
    params = {
        "id": post_id,
        "mid": post_id,
        "max_id_type": 0
    }
    headers = _build_headers(cookie, ua=ua, referer=f"https://m.weibo.cn/detail/{post_id}")
    requester = session or requests
    
    comments = []
    _jitter(0.8, 0.4)  # small randomised delay
    try:
        response = requester.get(url, params=params, headers=headers, timeout=30)
        # hotflow might return 404 or empty if no hot comments, try regular flow if needed?
        # For now, let's stick to hotflow or simple 'comments/hot'
        
        if response.status_code == 200:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" in content_type:
                print(f"Bot-detection HTML for comments on post {post_id}, skipping.", file=sys.stderr)
                return []
            data = response.json()
            if data.get("ok") == 1:
                comments = data["data"]["data"]
    except Exception as e:
        print(f"Exception fetching comments for {post_id}: {e}", file=sys.stderr)
    
    return comments

def save_post(post, cookie=None, **kwargs):
    """Save post to DB."""
    mblog = post.get("mblog", {})
    if not mblog:
        return None

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL;')
    c = conn.cursor()
    
    pid = mblog.get("id")
    text = mblog.get("text")
    
    # Handle Long Text
    session = kwargs.get("session")
    ua = kwargs.get("ua")
    if mblog.get("isLongText") and cookie:
        print(f"Fetching full text for {pid}...", file=sys.stderr)
        full_text = get_long_text(pid, cookie, session=session, ua=ua)
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
    # Preserve old images: merge with any existing images in DB
    # Compare by base URL (without query params) to avoid duplicates from re-signed URLs
    try:
        existing = c.execute('SELECT images FROM posts WHERE id = ?', (pid,)).fetchone()
        if existing and existing[0]:
            existing_images = json.loads(existing[0])
            # Build a set of base URLs from the new images (newer signatures take priority)
            new_base_set = set(url.split('?')[0] for url in images)
            for old_url in existing_images:
                old_base = old_url.split('?')[0]
                if old_base not in new_base_set:
                    images.append(old_url)
                    new_base_set.add(old_base)
    except Exception:
        pass

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
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute('PRAGMA journal_mode=WAL;')
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
    conn = sqlite3.connect(DB_PATH, timeout=30)
    
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

def _warmup_session(session, uid, cookie, ua):
    """Visit the user's mobile profile page first to establish a natural browsing
    pattern before hitting the API.  This helps avoid bot-detection on the
    very first API call."""
    try:
        warmup_headers = _build_headers(cookie, ua=ua, referer="https://m.weibo.cn/")
        # Override Accept to look like a normal page load
        warmup_headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        warmup_headers.pop("X-Requested-With", None)
        warmup_headers.pop("Sec-Fetch-Dest", None)
        warmup_headers.pop("Sec-Fetch-Mode", None)
        warmup_headers.pop("Sec-Fetch-Site", None)
        warmup_headers.pop("MWeibo-Pwa", None)

        print(f"Warming up session (visiting profile page)...", file=sys.stderr)
        resp = session.get(f"https://m.weibo.cn/u/{uid}", headers=warmup_headers, timeout=30)
        print(f"Warmup status: {resp.status_code}, length: {len(resp.text)}", file=sys.stderr)
        _jitter(3.0, 1.5)  # mimic a human reading the page
    except Exception as e:
        print(f"Warmup request failed (non-fatal): {e}", file=sys.stderr)


def run_scraper(uid, cookie, days_back=1):
    print(f"Starting scrape for user {uid} (Last {days_back} days)...", file=sys.stderr)
    init_db()

    # ── Create a persistent session & pick a UA for the whole run ────
    session = requests.Session()
    ua = _pick_ua()
    print(f"Using UA: {ua[:60]}...", file=sys.stderr)

    # Warm up: visit profile page first to look like a real user
    _warmup_session(session, uid, cookie, ua)
    
    container_id = f"107603{uid}"
    page = 1
    cutoff_date = datetime.now() - timedelta(days=days_back)
    keep_scraping = True
    consecutive_old_posts = 0
    
    while keep_scraping:
        cards = get_posts(uid, container_id, cookie, page, session=session, ua=ua)
        if cards == "cookie_expired":
            print("Cookie expired! Cannot scrape.", file=sys.stderr)
            return "cookie_expired"
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
                
                # Skip posts containing "波浪理论详解" (book promo)
                post_text = mblog.get("text", "")
                if "波浪理论详解" in post_text:
                    print(f"Skipping post with '波浪理论详解' ({created_at_str})", file=sys.stderr)
                    continue
                
                pid = save_post(card, cookie, session=session, ua=ua)
                if pid:
                    print(f"Processing post {pid} ({created_at_str})...", file=sys.stderr)
                    comments = get_comments(pid, cookie, session=session, ua=ua)
                    for comment in comments:
                        save_comment_with_reply(pid, comment, uid)
                    _jitter(1.5, 0.8)  # randomised delay between posts
        
        page += 1
        _jitter(3.0, 1.5)  # longer randomised delay between pages

    export_to_excel()
    session.close()
    return "ok"

if __name__ == "__main__":
    # Load config from env or args
    UID = os.getenv("WEIBO_UID")
    COOKIE = os.getenv("WEIBO_COOKIE")
    DAYS = int(os.getenv("WEIBO_DAYS", 3)) # Default to 3 days for safety
    
    if not UID or not COOKIE:
        print("Please set WEIBO_UID and WEIBO_COOKIE environment variables.", file=sys.stderr)
    else:
        run_scraper(UID, COOKIE, days_back=DAYS)
