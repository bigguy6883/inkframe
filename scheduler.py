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
_current_index = 0
_photo_list = []

INTERVAL_OPTIONS = [5, 15, 30, 60, 180, 360, 720, 1440]


def get_scheduler():
    """Get or create the background scheduler"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    return _scheduler


def _refresh_photo_list():
    """Reload photo list from database"""
    global _photo_list
    settings = models.load_settings()
    order = settings.get("slideshow", {}).get("order", "random")
    _photo_list = models.get_display_photos(order)


def show_next_photo():
    """Display the next photo"""
    global _current_index

    _refresh_photo_list()
    if not _photo_list:
        print("No photos available")
        return False

    settings = models.load_settings()
    order = settings.get("slideshow", {}).get("order", "random")
    saturation = settings.get("display", {}).get("saturation", 0.5)

    if order == "random":
        if len(_photo_list) == 1:
            path = _photo_list[0]
        else:
            available = [p for i, p in enumerate(_photo_list) if i != _current_index]
            path = random.choice(available)
            _current_index = _photo_list.index(path)
    else:
        _current_index = (_current_index + 1) % len(_photo_list)
        path = _photo_list[_current_index]

    display.show_photo(path, saturation)
    return True


def show_previous_photo():
    """Display the previous photo"""
    global _current_index

    _refresh_photo_list()
    if not _photo_list:
        return False

    settings = models.load_settings()
    order = settings.get("slideshow", {}).get("order", "random")
    saturation = settings.get("display", {}).get("saturation", 0.5)

    if order == "random":
        if len(_photo_list) > 1:
            available = [p for i, p in enumerate(_photo_list) if i != _current_index]
            path = random.choice(available)
            _current_index = _photo_list.index(path)
        else:
            path = _photo_list[0]
    else:
        _current_index = (_current_index - 1) % len(_photo_list)
        path = _photo_list[_current_index]

    display.show_photo(path, saturation)
    return True


def show_specific_photo(photo_id):
    """Display a specific photo by ID"""
    photo = models.get_photo(photo_id)
    if not photo:
        return False

    settings = models.load_settings()
    saturation = settings.get("display", {}).get("saturation", 0.5)
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
