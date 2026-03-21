import sqlite3
import json
import os
import sys
import time
from scraper import save_post

DB_PATH = "weibo_data.db"

def refresh_data():
    cookie = os.getenv("WEIBO_COOKIE")
    if not cookie:
        print("Error: WEIBO_COOKIE is not set.", file=sys.stderr)
        return

    print("Starting data refresh...", file=sys.stderr)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Fetch all posts
    cursor = conn.execute("SELECT id, raw_json FROM posts")
    posts = cursor.fetchall()
    conn.close()
    
    print(f"Found {len(posts)} posts. Updating...", file=sys.stderr)
    
    count = 0
    for row in posts:
        try:
            if not row['raw_json']:
                continue
                
            mblog = json.loads(row['raw_json'])
            # Construct a wrapper like the 'card' object expected by save_post
            card = {'mblog': mblog}
            
            # save_post will:
            # 1. Extract images from mblog['pics']
            # 2. Fetch full text if mblog['isLongText'] is true (using the cookie)
            # 3. Update the DB record
            save_post(card, cookie)
            
            count += 1
            if count % 100 == 0:
                print(f"Processed {count} posts...", file=sys.stderr)
                
            # Sleep slightly to avoid rate limits if we are making API calls for long text
            if mblog.get('isLongText'):
                time.sleep(0.5)
                
        except Exception as e:
            print(f"Error processing post {row['id']}: {e}", file=sys.stderr)

    print("Refresh complete.", file=sys.stderr)

if __name__ == "__main__":
    refresh_data()
