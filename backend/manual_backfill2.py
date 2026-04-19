import sys
import os

from main import _get_cookie
from scraper import run_scraper
from export_static import export_stats, export_posts
from git_sync import sync_content

uid = "1644724561"
cookie = _get_cookie()

if not cookie:
    print("Cannot find cookie")
    sys.exit(1)

print("Starting backfill for the last 20 days...")
try:
    result = run_scraper(uid=uid, cookie=cookie, days_back=20)
    print("Scraper result:", result)
    print("Exporting static files...")
    export_stats()
    export_posts()
    print("Syncing to GitHub...")
    sync_content()
    print("Done!")
except Exception as e:
    print(f"Error: {e}")
