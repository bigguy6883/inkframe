"""Photo cycling scheduler"""

import random
import threading
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import models
import display
import photo_sync

# Scheduler instance
_scheduler = None
_scheduler_lock = threading.Lock()

# Valid interval options in minutes
INTERVAL_OPTIONS = [5, 15, 30, 60, 180, 360, 720, 1440]


def get_scheduler():
    """Get or create the background scheduler"""
    global _scheduler

    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()

    return _scheduler


def get_next_photo_path(order="random"):
    """
    Get the path to the next photo to display.

    Args:
        order: "random" or "sequential"

    Returns:
        Path to next photo, or None if no photos available
    """
    photos = photo_sync.get_cached_photos()

    if not photos:
        return None

    settings = models.load_settings()
    current_index = settings.get("slideshow", {}).get("current_index", 0)

    if order == "random":
        # Random selection (but avoid repeating the same photo)
        if len(photos) == 1:
            next_photo = photos[0]
        else:
            available = [p for i, p in enumerate(photos) if i != current_index]
            next_photo = random.choice(available) if available else photos[0]
            next_index = photos.index(next_photo)
    else:
        # Sequential order
        next_index = (current_index + 1) % len(photos)
        next_photo = photos[next_index]

    # Save current index
    models.update_settings({
        "slideshow": {**settings.get("slideshow", {}), "current_index": next_index}
    })

    return next_photo


def get_previous_photo_path(order="random"):
    """
    Get the path to the previous photo.

    Args:
        order: "random" or "sequential"

    Returns:
        Path to previous photo, or None if no photos available
    """
    photos = photo_sync.get_cached_photos()

    if not photos:
        return None

    settings = models.load_settings()
    current_index = settings.get("slideshow", {}).get("current_index", 0)

    if order == "random":
        # For random mode, just pick another random photo
        if len(photos) == 1:
            prev_photo = photos[0]
        else:
            available = [p for i, p in enumerate(photos) if i != current_index]
            prev_photo = random.choice(available) if available else photos[0]
            prev_index = photos.index(prev_photo)
    else:
        # Sequential order - go backwards
        prev_index = (current_index - 1) % len(photos)
        prev_photo = photos[prev_index]

    # Save current index
    models.update_settings({
        "slideshow": {**settings.get("slideshow", {}), "current_index": prev_index}
    })

    return prev_photo


def show_next_photo():
    """Display the next photo"""
    settings = models.load_settings()
    slideshow = settings.get("slideshow", {})
    display_settings = settings.get("display", {})

    order = slideshow.get("order", "random")
    fit_mode = display_settings.get("fit_mode", "contain")
    orientation = display_settings.get("orientation", "horizontal")

    photo_path = get_next_photo_path(order)

    if photo_path:
        display.show_image(str(photo_path), fit_mode, orientation)
        return True
    else:
        print("No photos available to display")
        return False


def show_previous_photo():
    """Display the previous photo"""
    settings = models.load_settings()
    slideshow = settings.get("slideshow", {})
    display_settings = settings.get("display", {})

    order = slideshow.get("order", "random")
    fit_mode = display_settings.get("fit_mode", "contain")
    orientation = display_settings.get("orientation", "horizontal")

    photo_path = get_previous_photo_path(order)

    if photo_path:
        display.show_image(str(photo_path), fit_mode, orientation)
        return True
    else:
        print("No photos available to display")
        return False


def show_current_photo():
    """Re-display the current photo (useful after settings change)"""
    photos = photo_sync.get_cached_photos()

    if not photos:
        return False

    settings = models.load_settings()
    current_index = settings.get("slideshow", {}).get("current_index", 0)
    display_settings = settings.get("display", {})

    fit_mode = display_settings.get("fit_mode", "contain")
    orientation = display_settings.get("orientation", "horizontal")

    # Clamp index to valid range
    if current_index >= len(photos):
        current_index = 0

    photo_path = photos[current_index]
    display.show_image(str(photo_path), fit_mode, orientation)
    return True


def _cycle_photo_job():
    """Job function called by scheduler to cycle photos"""
    print(f"[{datetime.now().isoformat()}] Cycling to next photo...")
    show_next_photo()


def start_slideshow():
    """Start the automatic photo cycling"""
    settings = models.load_settings()
    slideshow = settings.get("slideshow", {})

    if not slideshow.get("enabled", True):
        print("Slideshow is disabled")
        return False

    interval_minutes = slideshow.get("interval_minutes", 60)

    # Validate interval
    if interval_minutes not in INTERVAL_OPTIONS:
        interval_minutes = 60

    scheduler = get_scheduler()

    with _scheduler_lock:
        # Remove existing job if any
        try:
            scheduler.remove_job("photo_cycle")
        except Exception:
            pass

        # Add new job
        scheduler.add_job(
            _cycle_photo_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="photo_cycle",
            replace_existing=True
        )

    print(f"Started slideshow with {interval_minutes} minute interval")

    # Show first photo immediately
    show_next_photo()

    return True


def stop_slideshow():
    """Stop the automatic photo cycling"""
    scheduler = get_scheduler()

    with _scheduler_lock:
        try:
            scheduler.remove_job("photo_cycle")
            print("Stopped slideshow")
            return True
        except Exception:
            return False


def update_interval(interval_minutes):
    """Update the slideshow interval"""
    if interval_minutes not in INTERVAL_OPTIONS:
        return False

    settings = models.load_settings()
    settings["slideshow"]["interval_minutes"] = interval_minutes
    models.save_settings(settings)

    # Restart slideshow if running
    scheduler = get_scheduler()
    try:
        job = scheduler.get_job("photo_cycle")
        if job:
            start_slideshow()
    except Exception:
        pass

    return True


def is_slideshow_running():
    """Check if slideshow is currently running"""
    scheduler = get_scheduler()
    try:
        job = scheduler.get_job("photo_cycle")
        return job is not None
    except Exception:
        return False


def get_slideshow_status():
    """Get current slideshow status"""
    settings = models.load_settings()
    slideshow = settings.get("slideshow", {})
    photos = photo_sync.get_cached_photos()

    scheduler = get_scheduler()
    running = False
    next_run = None

    try:
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
        "current_index": slideshow.get("current_index", 0),
        "photo_count": len(photos),
        "next_run": next_run
    }


def shutdown():
    """Shutdown the scheduler"""
    global _scheduler

    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
