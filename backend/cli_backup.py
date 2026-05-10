import os
import sys
from datetime import datetime
import shutil

from scraper import run_scraper
from git_sync import sync_content
from export_static import export_stats, export_posts
from auto_cookie import refresh_cookie_file


def get_cookie():
    """
    获取 Cookie 的优先级：
      1. 先尝试从 Edge 浏览器自动提取最新 Cookie
      2. 如果提取失败，降级使用 cookie.txt 中的旧 Cookie
    """
    # 第一优先：从 Edge 自动提取
    print("Attempting to extract fresh cookies from Edge...")
    fresh_cookie = refresh_cookie_file()
    if fresh_cookie:
        print(f"✅ Got fresh cookies from Edge ({len(fresh_cookie)} chars)")
        return fresh_cookie

    # 降级：读取 cookie.txt
    print("⚠️ Edge extraction failed, falling back to cookie.txt...")
    try:
        with open("cookie.txt", "r") as f:
            cookie = f.read().strip()
        if cookie:
            print(f"Using existing cookie.txt ({len(cookie)} chars)")
            return cookie
    except Exception:
        pass

    return ""


def main():
    print(f"[{datetime.now()}] Weibo cron backup starting...")

    # Target blogger UID
    uid = os.getenv("WEIBO_UID", "1644724561")

    # 1. 获取 Cookie（自动从 Edge 提取，或降级使用 cookie.txt）
    cookie = get_cookie()
    if not cookie:
        print("❌ Error: No cookie available (Edge extraction failed + no cookie.txt)")
        sys.exit(1)

    # 2. 抓取最近 3 天的帖子
    print(f"Running scraper for uid={uid}...")
    result = run_scraper(uid=uid, cookie=cookie, days_back=3)

    if result == "cookie_expired":
        # Cookie 过期了，尝试重新从 Edge 提取一次
        print("⚠️ Cookie expired! Trying to refresh from Edge...")
        fresh_cookie = refresh_cookie_file()
        if fresh_cookie:
            print("🔄 Got fresh cookie, retrying scrape...")
            result = run_scraper(uid=uid, cookie=fresh_cookie, days_back=3)
            if result == "cookie_expired":
                print("❌ Fresh cookie also expired. Please re-login in Edge browser.")
                sys.exit(1)
        else:
            print("❌ Cannot refresh cookie. Please login to m.weibo.cn in Edge.")
            sys.exit(1)

    # 3. 导出静态文件
    print("Exporting static files...")
    export_stats()
    export_posts()

    # 4. 同步到 GitHub
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

