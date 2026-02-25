#!/usr/bin/env python3
"""
Instagram Feed Auto-Update for がおー Website
Uses a single API request to fetch posts from @nakano.gaoo_event,
then downloads images and uploads to Lolipop via FTP.
"""

import os
import sys
import json
import ftplib
import re
import io
import urllib.request
from pathlib import Path
from datetime import datetime

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

def fetch_posts_via_html(username):
    """Fetch posts by parsing Instagram profile HTML page"""
    url = f"https://www.instagram.com/{username}/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            log(f"Profile page fetched: {len(html)} bytes")
    except Exception as e:
        log(f"Failed to fetch profile page: {e}")
        return []
    
    posts = []
    
    # Look for image URLs in various patterns
    # Pattern: high-resolution image URLs from Instagram CDN
    img_pattern = r'https://(?:scontent[^"\'\s]+|instagram[^"\'\s]+)\.(?:cdninstagram|fbcdn)\.net/[^"\'\s]+\.jpg[^"\'\s]*'
    found_urls = list(set(re.findall(img_pattern, html)))
    
    # Filter to likely post images (high res, not tiny thumbnails)
    for img_url in found_urls[:MAX_POSTS]:
        clean_url = img_url.split("\\u0026")[0].replace("\\u0026", "&").replace("\\", "")
        posts.append({
            "id": clean_url.split("/")[-1][:20],
            "image_url": clean_url,
        })
    
    # Also try extracting from JSON embedded in the page
    if not posts:
        # Try window.__additionalDataLoaded or similar patterns
        json_patterns = [
            r'"display_url"\s*:\s*"([^"]+)"',
            r'"thumbnail_src"\s*:\s*"([^"]+)"',
            r'"src"\s*:\s*"(https://[^"]*cdninstagram[^"]*)"',
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, html)
            for match in matches[:MAX_POSTS]:
                clean_url = match.replace("\\u0026", "&").replace("\\", "")
                posts.append({
                    "id": clean_url.split("/")[-1][:20],
                    "image_url": clean_url,
                })
            if posts:
                break
    
    log(f"Found {len(posts)} potential post images")
    return posts

def fetch_posts_via_api(username):
    """Try Instagram's web API endpoint"""
    url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
    
    headers = {
        "User-Agent": "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2340; Google/google; Pixel 7; panther; panther; en_US; 458229258)",
        "X-IG-App-ID": "936619743392459",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        log(f"API returned HTTP {e.code}")
        return []
    except Exception as e:
        log(f"API request failed: {e}")
        return []
    
    try:
        edges = data["data"]["user"]["edge_owner_to_timeline_media"]["edges"]
    except (KeyError, TypeError):
        log("Could not parse API response")
        return []
    
    posts = []
    for edge in edges[:MAX_POSTS]:
        node = edge.get("node", {})
        posts.append({
            "id": node.get("shortcode", ""),
            "image_url": node.get("display_url", "") or node.get("thumbnail_src", ""),
        })
    
    log(f"API returned {len(posts)} posts")
    return posts

def download_image(url, filepath):
    """Download a single image"""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            if len(data) > 5000:  # Minimum size check
                filepath.write_bytes(data)
                return True
            else:
                log(f"  Image too small ({len(data)} bytes), skipping")
                return False
    except Exception as e:
        log(f"  Download failed: {e}")
        return False

def update_html_on_server(ftp, filenames, ig_username):
    """Download index.html, update IG section, re-upload"""
    buf = io.BytesIO()
    ftp.retrbinary("RETR index.html", buf.write)
    html = buf.getvalue().decode("utf-8")
    log("Downloaded index.html")
    
    # Build grid items
    ig_items = ""
    for fn in filenames:
        ig_items += (
            f'            <a href="https://www.instagram.com/{ig_username}/" '
            f'target="_blank" class="ig-post" style="display:block;aspect-ratio:1;'
            f'overflow:hidden;border:1px solid var(--line);transition:transform .2s;">\n'
            f'              <img src="images/ig_posts/{fn}" alt="Instagram Post" '
            f'style="width:100%;height:100%;object-fit:cover;">\n'
            f'            </a>\n'
        )
    
    cols = min(len(filenames), 3)
    new_block = (
        f'<div class="ig-embed-wrap fade-in" id="ig-feed" '
        f'style="background:transparent;border:none;min-height:auto;padding:0;display:block;">\n'
        f'          <div class="ig-grid" style="display:grid;grid-template-columns:repeat({cols},1fr);'
        f'gap:24px;width:100%;max-width:{cols*220}px;margin:0 auto;">\n'
        f'{ig_items}          </div>'
    )
    
    pattern = r'<div class="ig-embed-wrap fade-in" id="ig-feed"[^>]*>.*?<div class="ig-grid"[^>]*>.*?</div>'
    new_html = re.sub(pattern, new_block, html, count=1, flags=re.DOTALL)
    
    if new_html != html:
        buf2 = io.BytesIO(new_html.encode("utf-8"))
        ftp.storbinary("STOR index.html", buf2)
        log("HTML updated and uploaded")
        return True
    
    log("HTML pattern not found, no update")
    return False

def upload_to_ftp(filenames, temp_dir):
    """Upload images and update HTML via FTP"""
    if not FTP_USER or not FTP_PASS:
        log("ERROR: FTP credentials not configured")
        return False
    
    ftp = ftplib.FTP_TLS()
    ftp.connect(FTP_HOST, 21)
    ftp.login(FTP_USER, FTP_PASS)
    ftp.prot_p()
    ftp.cwd(FTP_DIR)
    log(f"Connected to FTP: {FTP_HOST}/{FTP_DIR}")
    
    # Navigate to ig_posts
    ftp.cwd("images")
    try:
        ftp.mkd("ig_posts")
    except ftplib.error_perm:
        pass
    ftp.cwd("ig_posts")
    
    # Set directory permissions
    ftp.cwd(f"/{FTP_DIR}/images")
    ftp.sendcmd("SITE CHMOD 755 ig_posts")
    ftp.cwd("ig_posts")
    
    # Upload images
    for fn in filenames:
        fp = temp_dir / fn
        if fp.exists():
            with open(fp, "rb") as f:
                ftp.storbinary(f"STOR {fn}", f)
            ftp.sendcmd(f"SITE CHMOD 644 {fn}")
            log(f"  Uploaded: {fn}")
    
    # Update HTML
    ftp.cwd(f"/{FTP_DIR}")
    update_html_on_server(ftp, filenames, IG_USERNAME)
    
    ftp.quit()
    return True

def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}

def save_cache(post_ids):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps({
        "post_ids": post_ids,
        "updated_at": datetime.now().isoformat(),
    }, indent=2))

def main():
    log(f"=== Instagram Feed Update: @{IG_USERNAME} ===")
    
    # Try API first, then HTML parsing
    posts = fetch_posts_via_api(IG_USERNAME)
    
    if not posts:
        log("API failed, trying HTML parsing...")
        posts = fetch_posts_via_html(IG_USERNAME)
    
    if not posts:
        log("All methods failed. Exiting.")
        sys.exit(0)  # Don't fail the workflow
    
    # Check cache
    cache = load_cache()
    current_ids = [p["id"] for p in posts if p.get("id")]
    if current_ids and current_ids == cache.get("post_ids"):
        log("No new posts. Exiting.")
        return
    
    # Download images
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    downloaded = []
    
    for i, post in enumerate(posts[:MAX_POSTS]):
        if not post.get("image_url"):
            continue
        fn = f"ig_post_{i+1}.jpg"
        fp = TEMP_DIR / fn
        log(f"  Downloading post {i+1}...")
        if download_image(post["image_url"], fp):
            downloaded.append(fn)
    
    if not downloaded:
        log("No images downloaded. Exiting.")
        return
    
    log(f"Downloaded {len(downloaded)} images")
    
    # Upload
    if upload_to_ftp(downloaded, TEMP_DIR):
        save_cache(current_ids)
        log("=== Success! ===")
    else:
        log("=== Upload failed ===")
        sys.exit(1)

if __name__ == "__main__":
    main()
