"""Photo sync using rclone for Google Photos"""

import os
import subprocess
import json
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "cache"
CONFIG_DIR = Path(__file__).parent / "config"
SETTINGS_PATH = CONFIG_DIR / "settings.json"


def is_rclone_installed():
    """Check if rclone is installed"""
    try:
        result = subprocess.run(["rclone", "version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_rclone_remotes():
    """Get list of configured rclone remotes"""
    try:
        result = subprocess.run(
            ["rclone", "listremotes"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            remotes = [r.strip().rstrip(':') for r in result.stdout.strip().split('\n') if r.strip()]
            return remotes
        return []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def get_google_photos_remote():
    """Find a Google Photos remote, or return None"""
    remotes = get_rclone_remotes()

    # Check each remote's type
    for remote in remotes:
        try:
            result = subprocess.run(
                ["rclone", "config", "show", remote],
                capture_output=True,
                text=True,
                timeout=10
            )
            if "type = google photos" in result.stdout.lower():
                return remote
        except:
            pass

    # Fall back to common names
    for name in ['gphotos', 'googlephotos', 'google-photos', 'photos']:
        if name in remotes:
            return name

    return None


def list_albums(remote=None):
    """List albums from Google Photos via rclone"""
    if remote is None:
        remote = get_google_photos_remote()

    if not remote:
        return []

    try:
        result = subprocess.run(
            ["rclone", "lsf", f"{remote}:album", "--dirs-only"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            albums = [a.strip().rstrip('/') for a in result.stdout.strip().split('\n') if a.strip()]
            return sorted(albums)
        return []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def sync_album(album_name, remote=None, progress_callback=None):
    """
    Sync an album from Google Photos to local cache.

    Returns:
        tuple: (success: bool, message: str, count: int)
    """
    if remote is None:
        remote = get_google_photos_remote()

    if not remote:
        return False, "No Google Photos remote configured", 0

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    source = f"{remote}:album/{album_name}"

    try:
        # Run rclone copy
        result = subprocess.run(
            [
                "rclone", "copy",
                source,
                str(CACHE_DIR),
                "--progress",
                "-v"
            ],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )

        if result.returncode == 0:
            photos = get_cached_photos()
            return True, f"Synced {len(photos)} photos", len(photos)
        else:
            return False, f"Sync failed: {result.stderr}", 0

    except subprocess.TimeoutExpired:
        return False, "Sync timed out", 0
    except Exception as e:
        return False, f"Sync error: {e}", 0


def sync_all_albums(album_names, remote=None):
    """Sync multiple albums"""
    total = 0
    for album in album_names:
        success, msg, count = sync_album(album, remote)
        if success:
            total += count
    return total


def get_cached_photos():
    """Get list of cached photo files"""
    if not CACHE_DIR.exists():
        return []

    extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic'}
    photos = []

    for f in CACHE_DIR.iterdir():
        if f.is_file() and f.suffix.lower() in extensions:
            photos.append(f)

    return sorted(photos, key=lambda x: x.stat().st_mtime, reverse=True)


def clear_cache():
    """Delete all cached photos"""
    photos = get_cached_photos()
    for photo in photos:
        try:
            photo.unlink()
        except Exception as e:
            print(f"Failed to delete {photo}: {e}")
    return len(photos)


def get_cache_stats():
    """Get cache statistics"""
    photos = get_cached_photos()
    total_size = sum(p.stat().st_size for p in photos)

    return {
        "count": len(photos),
        "size_bytes": total_size,
        "size_mb": round(total_size / (1024 * 1024), 2)
    }


def is_configured():
    """Check if rclone is set up with a Google Photos remote"""
    return is_rclone_installed() and get_google_photos_remote() is not None
