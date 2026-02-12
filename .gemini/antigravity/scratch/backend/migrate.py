import sqlite3
import sys
import os
from scraper import parse_weibo_date

DB_PATH = "weibo_data.db"

def migrate():
    print("Starting migration...", file=sys.stderr)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Add column if not exists
    try:
        c.execute("ALTER TABLE posts ADD COLUMN created_at_ts REAL")
        print("Added created_at_ts column.", file=sys.stderr)
    except sqlite3.OperationalError:
        print("Column created_at_ts already exists.", file=sys.stderr)

    # 2. Update existing records
    posts = c.execute("SELECT id, created_at FROM posts").fetchall()
    print(f"Updating {len(posts)} posts...", file=sys.stderr)
    
    for pid, created_at in posts:
        try:
            dt = parse_weibo_date(created_at)
            ts = dt.timestamp()
            c.execute("UPDATE posts SET created_at_ts = ? WHERE id = ?", (ts, pid))
        except Exception as e:
            print(f"Failed to parse date for post {pid}: {created_at} ({e})", file=sys.stderr)
            
    conn.commit()
    conn.close()
    print("Migration complete.", file=sys.stderr)

if __name__ == "__main__":
    migrate()
