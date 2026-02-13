import argparse
import mimetypes
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.environ.get("DB_PATH", str(BASE_DIR / "database.db"))
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "cctp-images")

IMAGE_FOLDERS = {
    "integrations": "si",
    "modules": "modules",
    "onduleurs": "onduleurs",
}


def sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }


def sb_insert(table, rows):
    if not rows:
        return
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = sb_headers()
    headers["Prefer"] = "return=representation"
    chunk_size = 200
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        resp = requests.post(url, headers=headers, json=chunk, timeout=30)
        resp.raise_for_status()


def sb_delete_all(table):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    resp = requests.delete(url, headers=sb_headers(), params={"id": "gt.0"}, timeout=30)
    resp.raise_for_status()


def upload_file(local_path, folder):
    ext = local_path.suffix.lower()
    name = f"{uuid.uuid4().hex}{ext}"
    remote_path = f"{folder}/{name}"
    encoded = quote(remote_path, safe="/")
    url = f"{SUPABASE_URL}/storage/v1/object/{SUPABASE_BUCKET}/{encoded}"
    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    headers = sb_headers()
    headers["Content-Type"] = content_type
    headers["x-upsert"] = "true"
    with local_path.open("rb") as f:
        resp = requests.post(url, headers=headers, data=f.read(), timeout=60)
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{encoded}"


def sqlite_rows(table):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table} ORDER BY id ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def normalize_keys(row):
    return {str(k).lower(): v for k, v in row.items()}


def migrate_images(rows, folder):
    cache = {}
    for row in rows:
        image = row.get("image") or ""
        if not image:
            continue
        if str(image).startswith("http://") or str(image).startswith("https://"):
            continue
        key = (folder, image)
        if key in cache:
            row["image"] = cache[key]
            continue
        local_path = BASE_DIR / "static" / folder / str(image)
        if not local_path.exists():
            continue
        url = upload_file(local_path, folder)
        cache[key] = url
        row["image"] = url


def migrate_table(table, clear=False):
    rows = [normalize_keys(r) for r in sqlite_rows(table)]
    folder = IMAGE_FOLDERS.get(table)
    if folder:
        migrate_images(rows, folder)
    if clear:
        sb_delete_all(table)
    sb_insert(table, rows)
    print(f"{table}: {len(rows)} rows migrated")


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment.")
    if not Path(DB_PATH).exists():
        raise SystemExit(f"SQLite database not found: {DB_PATH}")

    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true", help="delete existing Supabase data before insert")
    args = parser.parse_args()

    migrate_table("modules", clear=args.clear)
    migrate_table("onduleurs", clear=args.clear)
    migrate_table("integrations", clear=args.clear)
    migrate_table("integrations_caracteristiques", clear=args.clear)

    print("\nRun this in Supabase SQL Editor to fix sequences:")
    print("select setval(pg_get_serial_sequence('modules','id'), (select coalesce(max(id),0) from modules));")
    print("select setval(pg_get_serial_sequence('onduleurs','id'), (select coalesce(max(id),0) from onduleurs));")
    print("select setval(pg_get_serial_sequence('integrations','id'), (select coalesce(max(id),0) from integrations));")
    print("select setval(pg_get_serial_sequence('integrations_caracteristiques','id'), (select coalesce(max(id),0) from integrations_caracteristiques));")


if __name__ == "__main__":
    main()
