import requests
import json
import os
import time
import threading
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler

PORT = 11984
CDX_URL = "https://web.archive.org/cdx/search/cdx"
DOWNLOAD_DELAY = 30
UPDATE_INTERVAL = 3600
DOWNLOAD_DIR = "downloads"
JSON_FILE = "images.json"
LAST_UPDATE_FILE = "last_update.txt"
LOCK = threading.Lock()

def load_images():
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, "r", encoding="utf8") as f:
            return json.load(f)
    return []

def save_images(images):
    with open(JSON_FILE, "w", encoding="utf8") as f:
        json.dump(images, f, ensure_ascii=False, indent=2)
    with open(LAST_UPDATE_FILE, "w", encoding="utf8") as f:
        f.write(datetime.now().strftime("%d.%m.%Y %H:%M:%S"))

def fetch_new_from_cdx():
    print("🔄 Запрашиваю CDX...")
    params = {
        "url": "i.oneme.ru/i*",
        "output": "json",
        "fl": "timestamp,original",
        "filter": "statuscode:200",
        "collapse": "urlkey"
    }
    try:
        r = requests.get(CDX_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"❌ Ошибка запроса CDX: {e}")
        return []

    new_entries = []
    for row in data[1:]:
        timestamp, original = row
        archive = f"https://web.archive.org/web/{timestamp}if_/{original}"
        dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
        formatted = dt.strftime("%d.%m.%Y - %H:%M")
        new_entries.append({
            "image": archive,
            "source": original,
            "date": formatted,
            "local": None,
            "failed": False
        })
    print(f"📦 Получено записей из CDX: {len(new_entries)}")
    return new_entries

def merge_new_images(existing, new_entries):
    existing_sources = {img["source"] for img in existing}
    added = 0
    for entry in new_entries:
        if entry["source"] not in existing_sources:
            existing.append(entry)
            existing_sources.add(entry["source"])
            added += 1
    if added:
        print(f"➕ Добавлено новых записей: {added}")
        save_images(existing)
    else:
        print("⏺ Нет новых записей.")

def update_loop():
    while True:
        with LOCK:
            current = load_images()
            new = fetch_new_from_cdx()
            merge_new_images(current, new)
        time.sleep(UPDATE_INTERVAL)

def get_image_extension(content_type):
    if content_type == "image/jpeg":
        return ".jpg"
    elif content_type == "image/png":
        return ".png"
    elif content_type == "image/gif":
        return ".gif"
    elif content_type == "image/webp":
        return ".webp"
    else:
        return ".jpg"

def extract_r_from_url(url):
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    r_list = qs.get("r", [])
    return r_list[0] if r_list else None

def download_image(entry):
    source = entry["source"]
    archive_url = entry["image"]
    r_param = extract_r_from_url(source)
    if not r_param:
        print(f"⚠️ Не найден параметр r в URL: {source}")
        entry["failed"] = True
        return False

    try:
        resp = requests.get(archive_url, stream=True, timeout=30)
        if resp.status_code != 200:
            print(f"❌ HTTP {resp.status_code} для {archive_url}")
            entry["failed"] = True
            return False

        content_type = resp.headers.get("Content-Type", "")
        ext = get_image_extension(content_type)
        filename = f"{r_param}{ext}"
        filepath = os.path.join(DOWNLOAD_DIR, filename)

        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(1024):
                f.write(chunk)

        print(f"✅ Скачано: {filename}")
        entry["local"] = f"{DOWNLOAD_DIR}/{filename}"
        entry["failed"] = False
        return True

    except Exception as e:
        print(f"❌ Ошибка скачивания {archive_url}: {e}")
        entry["failed"] = True
        return False

def parse_date_from_str(date_str):
    return datetime.strptime(date_str, "%d.%m.%Y - %H:%M")

def download_loop():
    while True:
        with LOCK:
            images = load_images()

        candidates = [img for img in images if img.get("local") is None and not img.get("failed", False)]
        if candidates:
            candidates.sort(key=lambda x: parse_date_from_str(x["date"]), reverse=True)
            entry = candidates[0]
            success = download_image(entry)
            with LOCK:
                save_images(images)
        else:
            print("⏳ Нет новых изображений для скачивания.")

        time.sleep(DOWNLOAD_DELAY)

if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    with LOCK:
        existing = load_images()
        new = fetch_new_from_cdx()
        merge_new_images(existing, new)

    t_updater = threading.Thread(target=update_loop, daemon=True)
    t_downloader = threading.Thread(target=download_loop, daemon=True)
    t_updater.start()
    t_downloader.start()

    print(f"\n🌐 Сервер запущен на http://localhost:{PORT}")
    HTTPServer(("localhost", PORT), SimpleHTTPRequestHandler).serve_forever()