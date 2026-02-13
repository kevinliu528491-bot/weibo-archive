import sqlite3
import json
import os
import datetime
import requests
import hashlib
import time

DB_PATH = "weibo_data.db"
STATIC_DIR = "static"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def export_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM posts")
    posts_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM comments")
    comments_count = cursor.fetchone()[0]
    
    stats = {
        "posts": posts_count,
        "comments": comments_count,
        "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open(os.path.join(STATIC_DIR, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    
    print(f"Exported stats: {stats}")
    conn.close()

def get_image_filename(url):
    """Generate a unique filename for the image based on its URL."""
    if not url:
        return None
    try:
        ext = os.path.splitext(url)[1].split('?')[0] # Get extension
        if not ext:
            ext = ".jpg" # Default
    except:
        ext = ".jpg"
        
    hash_obj = hashlib.md5(url.encode())
    return f"{hash_obj.hexdigest()}{ext}"

def download_image(url):
    """Download image to static/images and return local path."""
    if not url:
        return None
        
    filename = get_image_filename(url)
    images_dir = os.path.join(STATIC_DIR, "images")
    if not os.path.exists(images_dir):
        os.makedirs(images_dir)
        
    local_path = os.path.join(images_dir, filename)
    relative_path = f"images/{filename}"
    
    if os.path.exists(local_path):
        return relative_path # Already downloaded
        
    try:
        # Use headers to mimic browser
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Referer": "https://weibo.com/"
        }
        print(f"Downloading {url}...", end="\r")
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(response.content)
            return relative_path
        else:
            print(f"\nFailed to download {url}: Status {response.status_code}")
    except Exception as e:
        print(f"\nError downloading {url}: {e}")
        
    return url # Return original URL if download fails

def export_posts():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all posts ordered by date descending
    cursor.execute("SELECT * FROM posts ORDER BY created_at_ts DESC")
    posts = [dict(row) for row in cursor.fetchall()]
    
    # For each post, parse images JSON and fetch comments
    # Prepare list of all image URLs to download first
    all_image_jobs = []
    
    print("Preparing image download jobs...", end="\r")
    for post in posts:
        # Parse images
        if isinstance(post.get("images"), str):
            try:
                img_list = json.loads(post["images"])
            except:
                img_list = []
        else:
            img_list = post.get("images", [])
        
        post["_image_urls"] = img_list # Temp storage
        if img_list:
            for url in img_list:
                all_image_jobs.append(url)
                
    # Download images in parallel
    print(f"\nDownloading {len(all_image_jobs)} images with 10 threads...")
    from concurrent.futures import ThreadPoolExecutor
    
    url_map = {} # url -> local_path
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all jobs
        future_to_url = {executor.submit(download_image, url): url for url in set(all_image_jobs)}
        
        # Process results
        total = len(future_to_url)
        done = 0
        for future in  list(future_to_url.keys()): # Iterate over futures
            try:
                # We want to process as they complete, but basic iteration is fine for progress
                pass
            except:
                pass
        
        # Better: use as_completed
        from concurrent.futures import as_completed
        for future in as_completed(future_to_url):
            done += 1
            url = future_to_url[future]
            try:
                local_path = future.result()
                if local_path:
                    url_map[url] = local_path
            except Exception as e:
                print(f"Error downloading {url}: {e}")
            print(f"Progress: {done}/{total}", end="\r")
            
    print("\nImage download complete. Updating posts...")

    # Update posts with local paths
    for i, post in enumerate(posts):
        img_list = post.pop("_image_urls", []) # Retrieve and remove temp
        if img_list is None:
            img_list = []
            
        local_images = []
        for url in img_list:
             if url in url_map:
                 local_images.append(url_map[url])
             else:
                 local_images.append(url) 
        post["images"] = local_images
        
        # Fetch comments for this post
        cursor.execute("SELECT * FROM comments WHERE post_id = ? ORDER BY id ASC", (post["id"],))
        comments = [dict(row) for row in cursor.fetchall()]
        post["comments"] = comments
    
    print() # Newline after progress loop
    with open(os.path.join(STATIC_DIR, "posts.json"), "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)
        
    print(f"Exported {len(posts)} posts with comments and images to {os.path.join(STATIC_DIR, 'posts.json')}")
    conn.close()

if __name__ == "__main__":
    print("Starting static export...")
    if not os.path.exists(STATIC_DIR):
        os.makedirs(STATIC_DIR)
        
    export_stats()
    export_posts()
    print("Export complete.")
