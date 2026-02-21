"""Photo cycling scheduler using APScheduler"""

import random
import threading
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import models
import display

_scheduler = None
_scheduler_lock = threading.Lock()
_current_path = None  # Track by path, not index
_shuffle_bag = []     # Shuffle-bag for random mode: ensures all photos shown before repeats
_history = []         # History stack for "previous" button
_initialized = False  # Whether we've loaded persisted state from disk

INTERVAL_OPTIONS = [5, 15, 30, 60, 180, 360, 720, 1440]


def get_scheduler():
    """Get or create the background scheduler"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    return _scheduler


def _load_persisted_state():
    """Load saved current photo path and shuffle bag from settings on startup"""
    global _current_path, _shuffle_bag, _initialized
    if _initialized:
        return
    _initialized = True
    settings = models.load_settings()
    slideshow = settings.get("slideshow", {})
    saved_path = slideshow.get("current_photo_path")
    saved_bag = slideshow.get("shuffle_bag", [])
    if saved_path:
        from pathlib import Path as _Path
        if _Path(saved_path).exists():
            _current_path = saved_path
            print(f"Restored current photo: {saved_path}")
        else:
            print(f"Restored photo no longer exists, resetting: {saved_path}")
    if saved_bag:
        _shuffle_bag = saved_bag
        print(f"Restored shuffle bag: {len(saved_bag)} photos remaining")


def _persist_state():
    """Save current photo path and shuffle bag to settings for restart persistence"""
    models.update_settings({"slideshow": {
        "current_photo_path": _current_path,
        "shuffle_bag": _shuffle_bag,
    }})


def _get_sequential_list():
    """Get stable sequential photo list"""
    return models.get_display_photos("sequential")


def _next_from_shuffle_bag(all_photos):
    """Pick next photo from shuffle bag, refilling when empty.
    Guarantees every photo is shown exactly once per cycle."""
    global _shuffle_bag, _current_path

    # Remove any photos from bag that no longer exist
    valid_photos = set(all_photos)
    _shuffle_bag = [p for p in _shuffle_bag if p in valid_photos]

    # Refill bag when empty
    if not _shuffle_bag:
        _shuffle_bag = list(all_photos)
        random.shuffle(_shuffle_bag)
        # If possible, avoid repeating the last shown photo at start of new cycle
        # Guard: len > 1 check prevents randint(1, 0) crash when only 1 photo exists
        if len(_shuffle_bag) > 1 and _shuffle_bag[0] == _current_path:
            # Swap first with a random other position
            swap_idx = random.randint(1, len(_shuffle_bag) - 1)
            _shuffle_bag[0], _shuffle_bag[swap_idx] = _shuffle_bag[swap_idx], _shuffle_bag[0]

    return _shuffle_bag.pop(0)


def show_next_photo():
    """Display the next photo"""
    global _current_path

    _load_persisted_state()
    all_photos = _get_sequential_list()
    if not all_photos:
        print("No photos available")
        return False

    settings = models.load_settings()
    order = settings.get("slideshow", {}).get("order", "random")
    saturation = settings.get("display", {}).get("saturation", 0.5)

    if order == "random":
        path = _next_from_shuffle_bag(all_photos)
    else:
        # Sequential: find current photo's position and advance
        if _current_path in all_photos:
            photo_index = {p: i for i, p in enumerate(all_photos)}
            idx = photo_index[_current_path]
            path = all_photos[(idx + 1) % len(all_photos)]
        else:
            path = all_photos[0]

    # Save to history before changing
    if _current_path:
        _history.append(_current_path)
        # Keep history bounded
        if len(_history) > 100:
            _history.pop(0)

    _current_path = path
    _persist_state()
    display.show_photo(path, saturation)
    print(f"Showing photo: {path} ({len(all_photos)} total)")
    return True


def show_previous_photo():
    """Display the previous photo"""
    global _current_path

    _load_persisted_state()
    all_photos = _get_sequential_list()
    if not all_photos:
        return False

    settings = models.load_settings()
    order = settings.get("slideshow", {}).get("order", "random")
    saturation = settings.get("display", {}).get("saturation", 0.5)

    if order == "random":
        # Go back in history if available
        if _history:
            path = _history.pop()
            # Make sure it still exists
            while _history and path not in all_photos:
                path = _history.pop()
            if path not in all_photos:
                path = _next_from_shuffle_bag(all_photos)
        else:
            path = _next_from_shuffle_bag(all_photos)
    else:
        # Sequential: find current photo's position and go back
        if _current_path in all_photos:
            idx = all_photos.index(_current_path)
            path = all_photos[(idx - 1) % len(all_photos)]
        else:
            path = all_photos[-1]

    _current_path = path
    display.show_photo(path, saturation)
    return True


def show_specific_photo(photo_id):
    """Display a specific photo by ID"""
    global _current_path

    photo = models.get_photo(photo_id)
    if not photo:
        return False

    settings = models.load_settings()
    saturation = settings.get("display", {}).get("saturation", 0.5)

    if _current_path:
        _history.append(_current_path)
        if len(_history) > 100:
            _history.pop(0)

    _current_path = photo['display_path']
    display.show_photo(photo['display_path'], saturation)
    return True


def _cycle_photo_job():
    """Job function called by scheduler"""
    print(f"[{datetime.now().isoformat()}] Cycling to next photo...")
    show_next_photo()


def start_slideshow():
    """Start automatic photo cycling"""
    settings = models.load_settings()
    slideshow = settings.get("slideshow", {})
    interval_minutes = slideshow.get("interval_minutes", 60)

    if interval_minutes not in INTERVAL_OPTIONS:
        interval_minutes = 60

    scheduler = get_scheduler()

    with _scheduler_lock:
        try:
            scheduler.remove_job("photo_cycle")
        except Exception:
            pass

        scheduler.add_job(
            _cycle_photo_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="photo_cycle",
            replace_existing=True
        )

    print(f"Started slideshow with {interval_minutes}min interval")
    show_next_photo()
    return True


def stop_slideshow():
    """Stop automatic photo cycling"""
    scheduler = get_scheduler()
    with _scheduler_lock:
        try:
            scheduler.remove_job("photo_cycle")
            print("Stopped slideshow")
            return True
        except Exception:
            return False


def is_slideshow_running():
    """Check if slideshow is currently running"""
    scheduler = get_scheduler()
    try:
        return scheduler.get_job("photo_cycle") is not None
    except Exception:
        return False


def get_slideshow_status():
    """Get current slideshow status"""
    settings = models.load_settings()
    slideshow = settings.get("slideshow", {})

    running = False
    next_run = None
    try:
        scheduler = get_scheduler()
        job = scheduler.get_job("photo_cycle")
        if job:
            running = True
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
    except Exception:
        pass

    return {
        "running": running,
        "enabled": slideshow.get("enabled", True),
        "interval_minutes": slideshow.get("interval_minutes", 60),
        "order": slideshow.get("order", "random"),
        "photo_count": models.get_photo_count(),
        "next_run": next_run
    }


def shutdown():
    """Shutdown the scheduler"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
