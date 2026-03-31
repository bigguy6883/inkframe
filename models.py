"""SQLite database models and JSON settings for InkFrame"""

import sqlite3
import json
import threading
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "config" / "photos.db"
SETTINGS_PATH = Path(__file__).parent / "config" / "settings.json"

DEFAULT_SETTINGS = {
    "wifi": {
        "ssid": "",
        "configured": False
    },
    "display": {
        "orientation": "horizontal",
        "fit_mode": "contain",
        "saturation": 0.5,
        "crop_mode": "center"
    },
    "slideshow": {
        "order": "random",
        "interval_minutes": 60,
        "enabled": True,
        "auto_start": True,
        "current_index": 0
    },
    "upload": {
        "max_file_size_mb": 20
    }
}

_db_local = threading.local()


def get_db():
    """Get per-thread database connection with row factory. Reuses connection within a thread."""
    conn = getattr(_db_local, 'conn', None)
    if conn is None:
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _db_local.conn = conn
    return conn


def close_db():
    """Close the per-thread database connection. Called at end of request/job."""
    conn = getattr(_db_local, 'conn', None)
    if conn is not None:
        conn.close()
        _db_local.conn = None


def init_db():
    """Initialize database tables"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL UNIQUE,
            original_path TEXT NOT NULL,
            display_path TEXT NOT NULL,
            thumbnail_path TEXT NOT NULL,
            width INTEGER,
            height INTEGER,
            file_size INTEGER,
            mime_type TEXT,
            date_taken TEXT,
            uploaded_at TEXT NOT NULL,
            display_order INTEGER DEFAULT 0,
            is_favorite INTEGER DEFAULT 0
        )
    ''')

    conn.commit()


def load_settings():
    """Load settings from JSON file"""
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS.copy()

    try:
        with open(SETTINGS_PATH, 'r') as f:
            settings = json.load(f)
        # Merge with defaults to handle missing keys
        merged = {}
        for key in DEFAULT_SETTINGS:
            if key in settings:
                if isinstance(DEFAULT_SETTINGS[key], dict):
                    merged[key] = {**DEFAULT_SETTINGS[key], **settings.get(key, {})}
                else:
                    merged[key] = settings[key]
            else:
                merged[key] = DEFAULT_SETTINGS[key] if not isinstance(DEFAULT_SETTINGS[key], dict) else DEFAULT_SETTINGS[key].copy()
        # Migrate smart_recenter -> crop_mode (one-time)
        raw_display = settings.get('display', {})
        if 'smart_recenter' in raw_display:
            if 'crop_mode' not in raw_display:
                merged['display']['crop_mode'] = 'smart' if raw_display['smart_recenter'] else 'center'
            if 'smart_recenter' in merged['display']:
                del merged['display']['smart_recenter']
            save_settings(merged)

        return merged
    except (json.JSONDecodeError, IOError):
        return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """Save settings to JSON file"""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f, indent=2)


def update_settings(updates):
    """Update specific settings keys (deep merge for dicts)"""
    settings = load_settings()
    for key, value in updates.items():
        if isinstance(value, dict) and key in settings and isinstance(settings[key], dict):
            settings[key].update(value)
        else:
            settings[key] = value
    save_settings(settings)
    return settings


# Photo CRUD operations

def add_photo(filename, original_path, display_path, thumbnail_path,
              width=None, height=None, file_size=None, mime_type=None, date_taken=None):
    """Add a photo record"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO photos (filename, original_path, display_path, thumbnail_path,
                           width, height, file_size, mime_type, date_taken, uploaded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (filename, original_path, display_path, thumbnail_path,
          width, height, file_size, mime_type, date_taken, datetime.now().isoformat()))

    conn.commit()
    photo_id = cursor.lastrowid
    return photo_id


def get_photo(photo_id):
    """Get a photo by ID"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM photos WHERE id = ?', (photo_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def get_all_photos(limit=None, offset=0):
    """Get all photos, optionally paginated"""
    conn = get_db()
    cursor = conn.cursor()
    if limit:
        cursor.execute('SELECT * FROM photos ORDER BY uploaded_at DESC LIMIT ? OFFSET ?', (limit, offset))
    else:
        cursor.execute('SELECT * FROM photos ORDER BY uploaded_at DESC')
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_photo_count():
    """Get total photo count"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM photos')
    count = cursor.fetchone()[0]
    return count


def get_display_photos():
    """Get photos for display cycling, returns list of display_path strings.
    Always returns stable ASC order; shuffling is handled by the caller (scheduler).
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT display_path FROM photos ORDER BY uploaded_at ASC')
    rows = cursor.fetchall()
    return [row['display_path'] for row in rows]


def delete_photo(photo_id):
    """Delete a photo record, returns the photo dict for file cleanup"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM photos WHERE id = ?', (photo_id,))
    row = cursor.fetchone()
    photo = dict(row) if row else None
    if photo:
        cursor.execute('DELETE FROM photos WHERE id = ?', (photo_id,))
        conn.commit()
    return photo


def delete_photos_bulk(photo_ids):
    """Delete multiple photos, returns list of photo dicts for file cleanup"""
    if not photo_ids:
        return []
    conn = get_db()
    cursor = conn.cursor()
    photos = []
    for pid in photo_ids:
        cursor.execute('SELECT * FROM photos WHERE id = ?', (pid,))
        row = cursor.fetchone()
        if row:
            photos.append(dict(row))
    if photos:
        found_ids = [p['id'] for p in photos]
        placeholders = ','.join('?' * len(found_ids))
        cursor.execute(f'DELETE FROM photos WHERE id IN ({placeholders})', found_ids)
        conn.commit()
    return photos


def toggle_favorite(photo_id):
    """Toggle favorite status, returns new value"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE photos SET is_favorite = NOT is_favorite WHERE id = ?', (photo_id,))
    conn.commit()
    cursor.execute('SELECT is_favorite FROM photos WHERE id = ?', (photo_id,))
    row = cursor.fetchone()
    return bool(row['is_favorite']) if row else None
