#!/usr/bin/env python3
"""
Instagram Feed Auto-Update for がおー Website
Fetches latest posts from @nakano.gaoo_event using instaloader,
downloads images, updates index.html, and uploads via FTP to Lolipop.
"""

import os
import sys
import json
import ftplib
import hashlib
from pathlib import Path
from datetime import datetime

# Try importing instaloader
try:
    import instaloader
except ImportError:
    print("Installing instaloader...")
    os.system("pip install instaloader")
    import instaloader

# ===== CONFIGURATION =====
IG_USERNAME = os.environ.get("IG_USERNAME", "nakano.gaoo_event")
FTP_HOST = os.environ.get("FTP_HOST", "ftp.lolipop.jp")
FTP_USER = os.environ.get("FTP_USER", "")
FTP_PASS = os.environ.get("FTP_PASS", "")
FTP_DIR = os.environ.get("FTP_DIR", "gaoo")
MAX_POSTS = 6
CACHE_FILE = Path(__file__).parent.parent / "cache" / "ig_cache.json"
TEMP_DIR = Path("/tmp/ig_downloads")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def fetch_instagram_posts(username, max_posts):
    """Fetch latest posts using instaloader"""
    L = instaloader.Instaloader(
        download_pictures=True,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
    )
    
    try:
        profile = instaloader.Profile.from_username(L.context, username)
        log(f"Found profile: {profile.full_name} ({profile.mediacount} posts)")
    except Exception as e:
        log(f"ERROR: Could not fetch profile: {e}")
        return []
    
    posts = []
    for i, post in enumerate(profile.get_posts()):
        if i >= max_posts:
            break
        
        posts.append({
            "shortcode": post.shortcode,
            "url": post.url,  # Direct image URL
            "timestamp": post.date_utc.isoformat(),
            "caption": (post.caption or "")[:100],
            "is_video": post.is_video,
        })
        log(f"  Post {i+1}: {post.shortcode} ({post.date_utc.strftime('%Y-%m-%d')})")
    
    return posts

def download_images(posts, temp_dir):
    """Download post images to temp directory"""
    import urllib.request
    
    temp_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    
    for i, post in enumerate(posts):
        if post["is_video"]:
            log(f"  Skipping video post: {post['shortcode']}")
            continue
        
        filename = f"ig_post_{i+1}.jpg"
        filepath = temp_dir / filename
        
        try:
            req = urllib.request.Request(
                post["url"],
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                filepath.write_bytes(data)
                downloaded.append(filename)
                log(f"  Downloaded: {filename} ({len(data)//1024}KB)")
        except Exception as e:
            log(f"  Failed to download {post['shortcode']}: {e}")
    
    return downloaded

def update_html_on_server(ftp, downloaded_files, ig_username):
    """Download index.html from FTP, update the IG section, re-upload"""
    import io
    import re
    
    # Download current index.html
    buf = io.BytesIO()
    ftp.retrbinary("RETR index.html", buf.write)
    html = buf.getvalue().decode("utf-8")
    log("Downloaded index.html from server")
    
    # Build new grid items
    ig_items = ""
    for filename in downloaded_files:
        ig_items += f'''            <a href="https://www.instagram.com/{ig_username}/" target="_blank" class="ig-post" style="display:block;aspect-ratio:1;overflow:hidden;border:1px solid var(--line);transition:transform .2s;">
              <img src="images/ig_posts/{filename}" alt="Instagram Post" style="width:100%;height:100%;object-fit:cover;">
            </a>
'''
    
    cols = min(len(downloaded_files), 3)
    max_width = cols * 220
    
    new_content = f'''<div class="ig-embed-wrap fade-in" id="ig-feed" style="background:transparent;border:none;min-height:auto;padding:0;display:block;">
          <div class="ig-grid" style="display:grid;grid-template-columns:repeat({cols},1fr);gap:24px;width:100%;max-width:{max_width}px;margin:0 auto;">
{ig_items}          </div>'''
    
    # Replace the ig-feed section
    pattern = r'<div class="ig-embed-wrap fade-in" id="ig-feed"[^>]*>.*?<div class="ig-grid"[^>]*>.*?</div>'
    new_html = re.sub(pattern, new_content, html, count=1, flags=re.DOTALL)
    
    if new_html != html:
        # Upload updated index.html
        buf = io.BytesIO(new_html.encode("utf-8"))
        ftp.storbinary("STOR index.html", buf)
        log("Updated and uploaded index.html")
        return True
    else:
        log("WARNING: Could not find ig-feed pattern in HTML")
        return False

def upload_to_ftp(downloaded_files, temp_dir):
    """Upload images and updated HTML to Lolipop via FTP"""
    if not FTP_USER or not FTP_PASS:
        log("ERROR: FTP credentials not set")
        return False
    
    try:
        ftp = ftplib.FTP_TLS()
        ftp.connect(FTP_HOST, 21)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.prot_p()
        ftp.cwd(FTP_DIR)
        log(f"Connected to FTP: {FTP_HOST}/{FTP_DIR}")
    except Exception as e:
        log(f"FTP connection failed: {e}")
        return False
    
    # Ensure ig_posts directory exists
    try:
        ftp.cwd("images/ig_posts")
    except:
        try:
            ftp.cwd("images")
            ftp.mkd("ig_posts")
            ftp.cwd("ig_posts")
        except Exception as e:
            log(f"Could not create ig_posts dir: {e}")
            ftp.quit()
            return False
    
    # Upload images
    for filename in downloaded_files:
        filepath = temp_dir / filename
        if filepath.exists():
            with open(filepath, "rb") as f:
                ftp.storbinary(f"STOR {filename}", f)
            log(f"  Uploaded: {filename}")
    
    # Go back to root to update HTML
    ftp.cwd(f"/{FTP_DIR}")
    update_html_on_server(ftp, downloaded_files, IG_USERNAME)
    
    ftp.quit()
    log("FTP upload complete")
    return True

def load_cache():
    """Load cache of previously fetched post IDs"""
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {"post_ids": []}

def save_cache(post_ids):
    """Save cache of fetched post IDs"""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps({
        "post_ids": post_ids,
        "updated_at": datetime.now().isoformat(),
    }, indent=2))

def main():
    log(f"=== Instagram Feed Update for @{IG_USERNAME} ===")
    
    # Fetch posts
    posts = fetch_instagram_posts(IG_USERNAME, MAX_POSTS)
    if not posts:
        log("No posts found. Exiting.")
        return
    
    # Check cache
    cache = load_cache()
    current_ids = [p["shortcode"] for p in posts]
    
    if current_ids == cache.get("post_ids"):
        log("No new posts since last check. Exiting.")
        return
    
    log(f"Found {len(posts)} posts (new or changed)")
    
    # Download images
    downloaded = download_images(posts, TEMP_DIR)
    if not downloaded:
        log("No images downloaded. Exiting.")
        return
    
    log(f"Downloaded {len(downloaded)} images")
    
    # Upload to FTP
    success = upload_to_ftp(downloaded, TEMP_DIR)
    
    if success:
        save_cache(current_ids)
        log("=== Update complete! ===")
    else:
        log("=== Update failed ===")
        sys.exit(1)

if __name__ == "__main__":
    main()
