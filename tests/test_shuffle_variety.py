"""Tests for shuffle-bag variety guarantees.

Bug: "random" order felt repetitive for two reasons:
1. When the shuffle bag refills, a photo shown at the end of the previous
   cycle can land at the front of the new one — reappearing within a day
   while other photos wait weeks (cycle-boundary adjacency).
2. Picking a photo from the web gallery (show_specific_photo) displayed it
   but left it in the bag, so it showed a second time in the same cycle.

These tests assert: refills keep the recently shown photos out of the front
of the new bag, gallery picks are pulled from the bag, and the recent-history
window survives a service restart so the guard still applies afterwards.
"""

import json

import pytest


FAKE_PHOTOS = [f"/fake/p{i}.png" for i in range(30)]


@pytest.fixture
def sched(monkeypatch, tmp_path):
    """Fresh scheduler module state + stubs for display and photos."""
    import importlib
    import models
    import scheduler

    # Isolate settings file so tests don't touch real config.
    monkeypatch.setattr(models, "SETTINGS_PATH", tmp_path / "settings.json")

    # Reset module-level state between tests.
    if scheduler._scheduler is not None:
        try:
            scheduler._scheduler.shutdown(wait=False)
        except Exception:
            pass
    scheduler._scheduler = None
    scheduler._current_path = None
    scheduler._shuffle_bag = []
    scheduler._history = []
    scheduler._initialized = True  # skip disk load in tests

    monkeypatch.setattr(scheduler.display, "show_photo", lambda *a, **kw: None)

    monkeypatch.setattr(scheduler.models, "get_display_photos", lambda: list(FAKE_PHOTOS))
    monkeypatch.setattr(
        scheduler.models,
        "get_photo",
        lambda pid: {"id": pid, "display_path": f"/fake/p{pid}.png"},
    )
    monkeypatch.setattr(scheduler.models, "get_photo_count", lambda: len(FAKE_PHOTOS))

    models.save_settings({
        "slideshow": {
            "order": "random",
            "interval_minutes": 5,
            "enabled": True,
            "auto_start": False,
        },
        "display": {"saturation": 0.5},
    })

    yield scheduler

    if scheduler._scheduler is not None:
        try:
            scheduler._scheduler.shutdown(wait=False)
        except Exception:
            pass
    scheduler._scheduler = None
    importlib.reload(scheduler)


def test_refill_keeps_recent_photos_out_of_front(sched):
    """The 10 most recently shown photos must not occupy the first 10
    positions of a freshly refilled bag."""
    recent = FAKE_PHOTOS[:10]

    # Repeat to make a lucky pass astronomically unlikely (~0.6% per refill).
    for _ in range(40):
        sched._shuffle_bag = []
        sched._history = list(recent[:-1])
        sched._current_path = recent[-1]

        first = sched._next_from_shuffle_bag(list(FAKE_PHOTOS))
        front = [first] + sched._shuffle_bag[:9]

        overlap = set(front) & set(recent)
        assert not overlap, (
            f"Recently shown photos appeared in the first 10 positions "
            f"after refill: {sorted(overlap)}"
        )


def test_refill_bag_still_contains_every_photo_once(sched):
    """The spacing guard must not drop or duplicate photos."""
    sched._shuffle_bag = []
    sched._history = FAKE_PHOTOS[:9]
    sched._current_path = FAKE_PHOTOS[9]

    first = sched._next_from_shuffle_bag(list(FAKE_PHOTOS))
    full_cycle = [first] + sched._shuffle_bag

    assert sorted(full_cycle) == sorted(FAKE_PHOTOS)


def test_refill_with_tiny_library_still_works(sched):
    """When (almost) every photo is 'recent', refill must degrade gracefully:
    no crash, complete bag, and no immediate repeat of the current photo."""
    tiny = FAKE_PHOTOS[:3]
    sched._shuffle_bag = []
    sched._history = list(tiny)
    sched._current_path = tiny[2]

    first = sched._next_from_shuffle_bag(list(tiny))

    assert sorted([first] + sched._shuffle_bag) == sorted(tiny)
    assert first != tiny[2], "Refill repeated the currently shown photo"


def test_gallery_pick_is_removed_from_bag(sched):
    """Picking a photo from the gallery must pull it from the shuffle bag so
    it doesn't show a second time in the same cycle."""
    sched._shuffle_bag = list(FAKE_PHOTOS)

    assert sched.show_specific_photo(5) is True

    assert "/fake/p5.png" not in sched._shuffle_bag
    assert sched._current_path == "/fake/p5.png"


def test_gallery_pick_loads_saved_state_before_persisting(sched, tmp_path):
    """show_specific_photo on a fresh process must load the persisted bag
    before writing state back, not clobber it with an empty in-memory bag."""
    import models

    saved_bag = list(FAKE_PHOTOS[10:])
    models.update_settings({"slideshow": {"shuffle_bag": saved_bag,
                                          "current_photo_path": FAKE_PHOTOS[0]}})

    # Simulate a fresh process: nothing loaded yet.
    sched._initialized = False
    sched._shuffle_bag = []
    sched._current_path = None

    assert sched.show_specific_photo(12) is True

    with open(models.SETTINGS_PATH) as f:
        persisted = json.load(f)["slideshow"]["shuffle_bag"]
    expected = [p for p in saved_bag if p != "/fake/p12.png"]
    assert persisted == expected, (
        "Persisted bag should be the saved bag minus the picked photo, "
        "not an empty in-memory bag"
    )


def test_recent_history_survives_restart(sched):
    """The recent-history window must persist so the refill spacing guard
    still applies if the service restarts near a refill."""
    import models

    sched._history = FAKE_PHOTOS[:15]
    sched._current_path = FAKE_PHOTOS[15]
    sched._shuffle_bag = FAKE_PHOTOS[16:]
    sched._persist_state()

    # Simulate restart.
    sched._history = []
    sched._current_path = None
    sched._shuffle_bag = []
    sched._initialized = False
    sched._load_persisted_state()

    # The last 10 shown (tail of history) must be back for the guard to use.
    assert sched._history[-5:] == FAKE_PHOTOS[10:15]
    assert len(sched._history) >= 10
