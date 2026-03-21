import sqlite3
import json
import os
import sys
import requests
import hashlib
import re
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# Configuration
DB_PATH = "weibo_data.db"
IMAGE_DIR = "images"
OUTPUT_PDF = "weibo_archive.pdf"

# Register Chinese Font
# STSong-Light is a standard CID font available in reportlab
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def download_image(url):
    """Download image and return local path. Return None if failed."""
    if not url:
        return None
        
    if not os.path.exists(IMAGE_DIR):
        os.makedirs(IMAGE_DIR)
        
    # Create filename from hash of URL
    hash_name = hashlib.md5(url.encode('utf-8')).hexdigest()
    # Guess extension or default to jpg
    ext = "jpg"
    if ".png" in url.lower(): ext = "png"
    elif ".gif" in url.lower(): ext = "gif"
    
    filename = f"{hash_name}.{ext}"
    local_path = os.path.join(IMAGE_DIR, filename)
    
    if os.path.exists(local_path):
        return local_path
        
    # Download
    print(f"Downloading {url}...", file=sys.stderr)
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            with open(local_path, "wb") as f:
                f.write(resp.content)
            return local_path
    except Exception as e:
        print(f"Failed to download {url}: {e}", file=sys.stderr)
        
    return None

import concurrent.futures

def download_images_parallel(posts):
    """Pre-download all images in parallel."""
    print("Collecting image URLs...", file=sys.stderr)
    urls = set()
    for post in posts:
        try:
            imgs = json.loads(post['images']) if post['images'] else []
            for url in imgs:
                urls.add(url)
        except:
            pass
            
    print(f"Found {len(urls)} unique images. Downloading in parallel...", file=sys.stderr)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(download_image, url): url for url in urls}
        
        done_count = 0
        total = len(urls)
        
        for future in concurrent.futures.as_completed(futures):
            done_count += 1
            if done_count % 100 == 0:
                print(f"Downloaded {done_count}/{total} images...", file=sys.stderr)

def create_pdf():
    print("Fetching posts...", file=sys.stderr)
    conn = get_db_connection()
    posts = conn.execute('SELECT * FROM posts ORDER BY created_at_ts DESC').fetchall()
    conn.close()
    
    if not posts:
        print("No posts found.", file=sys.stderr)
        return

    # Pre-download images
    download_images_parallel(posts)

    doc = SimpleDocTemplate(OUTPUT_PDF, pagesize=A4, topMargin=50, bottomMargin=50)
    story = []
    
    styles = getSampleStyleSheet()
    # Define Chinese styles
    title_style = ParagraphStyle(
        'ChineseTitle',
        parent=styles['Heading1'],
        fontName='STSong-Light',
        fontSize=24,
        leading=30,
        alignment=1, # Center
        spaceAfter=20
    )
    
    date_style = ParagraphStyle(
        'ChineseDate',
        parent=styles['Normal'],
        fontName='STSong-Light',
        fontSize=10,
        textColor=colors.gray,
        spaceAfter=5
    )
    
    body_style = ParagraphStyle(
        'ChineseBody',
        parent=styles['Normal'],
        fontName='STSong-Light',
        fontSize=12,
        leading=16,
        spaceAfter=10
    )
    
    # Title Page
    story.append(Paragraph("Weibo Archive", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d')}", date_style))
    story.append(PageBreak())
    
    # Posts
    processed_count = 0
    for post in posts:
        processed_count += 1
        if processed_count % 100 == 0:
            print(f"Processing PDF content: {processed_count}/{len(posts)} posts...", file=sys.stderr)
            
        created_at = post['created_at']
        text = post['text'] or ""
        
        # Add Date
        story.append(Paragraph(created_at, date_style))
        
        # Add Text (replace newlines with <br/>)
        formatted_text = text.replace('\n', '<br/>')
        # Clean unsupported attributes (data-hide, class, target, rel, style, alt) from HTML tags for ReportLab
        formatted_text = re.sub(r' (data-[a-z-]+|class|target|rel|style|alt)=("[^"]*"|\'[^\']*\')', '', formatted_text)
        
        try:
            story.append(Paragraph(formatted_text, body_style))
        except Exception as e:
            print(f"Error parsing paragraph for post {post['id']}: {e}", file=sys.stderr)
            # Fallback to plain text if parsing fails
            clean_text = re.sub(r'<[^>]+>', '', formatted_text) # Strip tags
            story.append(Paragraph(clean_text, body_style))
        
        # Handle Images
        try:
            images = json.loads(post['images']) if post['images'] else []
        except:
            images = []
            
        for img_url in images:
            # Check local cache (hash)
            hash_name = hashlib.md5(img_url.encode('utf-8')).hexdigest()
            ext = "jpg"
            if ".png" in img_url.lower(): ext = "png"
            elif ".gif" in img_url.lower(): ext = "gif"
            local_path = os.path.join(IMAGE_DIR, f"{hash_name}.{ext}")
            
            if os.path.exists(local_path):
                try:
                    # Resize image if too big for A4
                    # A4 width is ~595 points. Margins are 72+72=144. Usable ~450.
                    # ReportLab Image takes width/height.
                    # We create an Image instance
                    im = RLImage(local_path)
                    
                    # Simple scaling logic
                    avail_width = 450
                    max_height = 650 # Keep some buffer
                    
                    img_width = im.drawWidth
                    img_height = im.drawHeight
                    
                    # Scale width first
                    if img_width > avail_width:
                        factor = avail_width / img_width
                        img_width = avail_width
                        img_height = img_height * factor
                    
                    # Then check height
                    if img_height > max_height:
                        factor = max_height / img_height
                        img_height = max_height
                        img_width = img_width * factor
                        
                    im.drawWidth = img_width
                    im.drawHeight = img_height
                    
                    story.append(im)
                    story.append(Spacer(1, 10))
                except Exception as e:
                    print(f"Error adding image {local_path} to PDF: {e}", file=sys.stderr)
        
        story.append(Spacer(1, 20))
        story.append(Paragraph("_" * 50, body_style)) # Separator
        story.append(Spacer(1, 20))
        
    print("Building PDF...", file=sys.stderr)
    doc.build(story)
    print(f"PDF saved to {OUTPUT_PDF}", file=sys.stderr)

if __name__ == "__main__":
    create_pdf()
