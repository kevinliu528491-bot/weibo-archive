import sqlite3
import json
import os
import sys
from datetime import datetime
from collections import defaultdict
from ebooklib import epub

DB_PATH = "weibo_data.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def create_epub():
    print("Fetching posts from DB...", file=sys.stderr)
    conn = get_db_connection()
    # Fetch posts sorted by time (descending)
    posts = conn.execute('SELECT * FROM posts ORDER BY created_at_ts DESC').fetchall()
    conn.close()

    if not posts:
        print("No posts found to export.", file=sys.stderr)
        return

    # Group posts by Month
    posts_by_month = defaultdict(list)
    for post in posts:
        ts = post['created_at_ts']
        if not ts:
            # Fallback if no timestamp
            date_str = post['created_at'] 
            # Try to parse or just put in "Unknown"
            month_key = "Unknown Date"
        else:
            dt = datetime.fromtimestamp(ts)
            month_key = dt.strftime("%Y-%m")
        
        posts_by_month[month_key].append(post)

    # Sort months descending
    sorted_months = sorted(posts_by_month.keys(), reverse=True)

    # Create EPUB
    book = epub.EpubBook()
    book.set_identifier('weibo-archive')
    book.set_title('Weibo Archive')
    book.set_language('zh-cn')
    book.add_author('Weibo Scraper')

    # Create chapters
    chapters = []
    
    # Add CSS
    style = 'body { font-family: sans-serif; } .post { border-bottom: 1px solid #ccc; padding: 10px 0; } .date { color: #666; font-size: 0.8em; } img { max-width: 100%; }'
    css = epub.EpubItem(uid="style_nav", file_name="style/nav.css", media_type="text/css", content=style)
    book.add_item(css)

    for month in sorted_months:
        month_posts = posts_by_month[month]
        
        # Create chapter file
        chapter_title = f"{month}"
        chapter_filename = f"chapter_{month}.xhtml"
        
        c = epub.EpubHtml(title=chapter_title, file_name=chapter_filename, lang='zh-cn')
        c.add_item(css)
        
        # Build Content
        content = [f"<h1>{month}</h1>"]
        
        for post in month_posts:
            # Post Date
            created_at = post['created_at']
            text = post['text'] or ""
            
            # Images
            images_html = ""
            try:
                images_list = json.loads(post['images']) if post['images'] else []
                for img_url in images_list:
                    # Using remote URL for now as requested for creating an epub (not scraping all assets)
                    images_html += f'<div class="image"><img src="{img_url}" alt="image" /><br/><a href="{img_url}">[View Image]</a></div>'
            except:
                pass
            
            # Comments (Optional, but let's stick to posts first as requested)
            
            post_html = f"""
            <div class="post">
                <p class="date">{created_at}</p>
                <div class="content">{text}</div>
                {images_html}
            </div>
            <hr/>
            """
            content.append(post_html)
        
        c.content = "".join(content)
        book.add_item(c)
        chapters.append(c)

    # Define Table of Contents
    book.toc = tuple(chapters)

    # Add default NCX and Nav file
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Define Spine
    book.spine = ['nav'] + chapters

    # Write EPUB
    output_file = "weibo_posts.epub"
    epub.write_epub(output_file, book, {})
    print(f"EPUB generated: {output_file}", file=sys.stderr)

if __name__ == "__main__":
    create_epub()
