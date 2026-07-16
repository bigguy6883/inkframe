"""Photo cycling scheduler using APScheduler"""

import random
import threading
from datetime import datetime
from pathlib import Path
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
RECENT_REPEAT_GUARD = 10  # keep this many recently shown photos out of the front of a fresh bag


def get_scheduler():
    """Get or create the background scheduler"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    return _scheduler


def _load_persisted_state():
    """Load saved current photo path and shuffle bag from settings on startup"""
    global _current_path, _shuffle_bag, _history, _initialized
    if _initialized:
        return
    _initialized = True
    try:
        settings = models.load_settings()
        slideshow = settings.get("slideshow", {})
        saved_path = slideshow.get("current_photo_path")
        saved_bag = slideshow.get("shuffle_bag", [])
        saved_history = slideshow.get("recent_history", [])
        if saved_history:
            _history = saved_history
        if saved_path:
            if Path(saved_path).exists():
                _current_path = saved_path
                print(f"Restored current photo: {saved_path}")
            else:
                print(f"Restored photo no longer exists, resetting: {saved_path}")
        if saved_bag:
            _shuffle_bag = saved_bag
            print(f"Restored shuffle bag: {len(saved_bag)} photos remaining")
    except Exception as e:
        print(f"Failed to load persisted slideshow state, starting fresh: {e}")


def _persist_state():
    """Save current photo path and shuffle bag to settings for restart persistence"""
    try:
        models.update_settings({"slideshow": {
            "current_photo_path": _current_path,
            "shuffle_bag": _shuffle_bag,
            "recent_history": _history[-RECENT_REPEAT_GUARD:],
        }})
    except Exception as e:
        print(f"Failed to persist slideshow state: {e}")


def _get_sequential_list():
    """Get stable sequential photo list"""
    return models.get_display_photos()


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
        _space_out_recent(valid_photos)

    return _shuffle_bag.pop(0)


def _space_out_recent(valid_photos):
    """Keep recently shown photos out of the front of a freshly refilled bag,
    so a photo shown at the end of one cycle can't reappear right at the
    start of the next (cycle-boundary adjacency).

    The window shrinks with small libraries (half the library at most, so at
    least half the photos remain eligible for the front) and is never larger
    than RECENT_REPEAT_GUARD."""
    global _shuffle_bag

    window = min(RECENT_REPEAT_GUARD, len(_shuffle_bag) // 2)
    shown = _history + ([_current_path] if _current_path else [])
    recent = set()
    for p in reversed(shown):
        if len(recent) >= window:
            break
        if p in valid_photos:
            recent.add(p)
    if not recent:
        return

    reordered = [p for p in _shuffle_bag if p not in recent]
    for p in (p for p in _shuffle_bag if p in recent):
        reordered.insert(random.randint(min(window, len(reordered)), len(reordered)), p)
    _shuffle_bag = reordered


def show_next_photo(_from_scheduler=False):
    """Display the next photo.

    When called manually (via REST/GPIO), re-anchors the cycle timer so the
    chosen photo sits for a full interval. When called by the scheduler's own
    tick (_from_scheduler=True), leaves the timer alone — APScheduler's
    IntervalTrigger already advances to the next fire time on its own.
    """
    global _current_path

    if display.is_busy():
        print("Display busy, ignoring photo change")
        return False

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
    if not _from_scheduler:
        _reset_cycle_timer()
    return True


def show_previous_photo():
    """Display the previous photo"""
    global _current_path

    if display.is_busy():
        print("Display busy, ignoring photo change")
        return False

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
            photo_index = {p: i for i, p in enumerate(all_photos)}
            idx = photo_index[_current_path]
            path = all_photos[(idx - 1) % len(all_photos)]
        else:
            path = all_photos[-1]

    _current_path = path
    display.show_photo(path, saturation)
    _reset_cycle_timer()
    return True


def show_specific_photo(photo_id):
    """Display a specific photo by ID"""
    global _current_path, _shuffle_bag

    if display.is_busy():
        print("Display busy, ignoring photo change")
        return False

    _load_persisted_state()
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
    # Pull the picked photo from the shuffle bag so it doesn't show a second
    # time in the same cycle
    if _current_path in _shuffle_bag:
        _shuffle_bag.remove(_current_path)
    _persist_state()
    display.show_photo(photo['display_path'], saturation)
    _reset_cycle_timer()
    return True


def _reset_cycle_timer():
    """Re-anchor the photo_cycle job to fire `interval_minutes` from now.

    Called after a manual photo change (select/next/prev) so that a user-chosen
    photo gets the full rotation interval before the next auto-cycle, instead
    of being replaced by whatever remained on the original schedule. No-op if
    the slideshow is stopped (no job registered).
    """
    scheduler = get_scheduler()
    with _scheduler_lock:
        try:
            if scheduler.get_job("photo_cycle") is None:
                return
        except Exception:
            return

        settings = models.load_settings()
        interval_minutes = settings.get("slideshow", {}).get("interval_minutes", 60)
        if interval_minutes not in INTERVAL_OPTIONS:
            interval_minutes = 60

        try:
            scheduler.reschedule_job(
                "photo_cycle",
                trigger=IntervalTrigger(minutes=interval_minutes),
            )
        except Exception as e:
            print(f"Failed to reset cycle timer: {e}")


def _cycle_photo_job():
    """Job function called by scheduler"""
    print(f"[{datetime.now().isoformat()}] Cycling to next photo...")
    show_next_photo(_from_scheduler=True)


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
