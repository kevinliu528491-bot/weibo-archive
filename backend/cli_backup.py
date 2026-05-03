import os
import sys
from datetime import datetime
import shutil

from scraper import run_scraper
from git_sync import sync_content
from export_static import export_stats, export_posts

def main():
    print(f"[{datetime.now()}] Weibo cron backup starting...")
    
    # Try to get UID from env, fallback to default
    uid = os.getenv("WEIBO_UID", "5187664653")
    
    # Get cookie
    cookie = ""
    try:
        with open("cookie.txt", "r") as f:
            cookie = f.read().strip()
    except Exception:
        pass
        
    if not cookie:
        print("Error: No cookie found in cookie.txt")
        sys.exit(1)
        
    # 1. Scrape last 3 days
    print(f"Running scraper for uid={uid}...")
    result = run_scraper(uid=uid, cookie=cookie, days_back=3)
    if result == "cookie_expired":
        print("Cookie expired! Update via the web interface.")
        sys.exit(1)
        
    # 2. Export static JSON
    print("Exporting static files...")
    export_stats()
    export_posts()
    
    # 3. Sync to github if disk space allows
    disk = shutil.disk_usage("/")
    free_gb = disk.free / (1024**3)
    print(f"Disk free: {free_gb:.1f} GiB")
    if free_gb >= 1.0:
        sync_content()
    else:
        print("Skipped git sync due to low disk space.")
        
    print(f"[{datetime.now()}] Weibo cron backup finished.")

if __name__ == "__main__":
    main()
