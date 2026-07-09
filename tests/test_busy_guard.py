"""Manual photo changes during an active e-ink refresh must be rejected
BEFORE any state mutation.

Bug: the Inky Impression refresh takes ~30s; display._show_on_display drops
updates while busy, but scheduler.show_next_photo had already advanced
_current_path and persisted it — the app then believed a photo was showing
that never reached the glass.
"""

import pytest


@pytest.fixture
def sched(monkeypatch, tmp_path):
    """Fresh scheduler module state + stubs (same pattern as timer tests)."""
    import importlib
    import models
    import scheduler

    monkeypatch.setattr(models, "SETTINGS_PATH", tmp_path / "settings.json")

    if scheduler._scheduler is not None:
        try:
            scheduler._scheduler.shutdown(wait=False)
        except Exception:
            pass
    scheduler._scheduler = None
    scheduler._current_path = "/fake/p1.png"
    scheduler._shuffle_bag = []
    scheduler._history = []
    scheduler._initialized = True

    monkeypatch.setattr(scheduler.display, "show_photo", lambda *a, **kw: None)

    fake_photos = ["/fake/p1.png", "/fake/p2.png", "/fake/p3.png"]
    monkeypatch.setattr(scheduler.models, "get_display_photos", lambda: fake_photos)
    monkeypatch.setattr(
        scheduler.models,
        "get_photo",
        lambda pid: {"id": pid, "display_path": f"/fake/p{pid}.png"},
    )
    monkeypatch.setattr(scheduler.models, "get_photo_count", lambda: len(fake_photos))

    models.save_settings({
        "slideshow": {
            "order": "sequential",
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


def test_next_refused_while_display_busy(sched, monkeypatch):
    monkeypatch.setattr(sched.display, "is_busy", lambda: True)
    assert sched.show_next_photo() is False
    assert sched._current_path == "/fake/p1.png"
    assert sched._history == []


def test_prev_refused_while_display_busy(sched, monkeypatch):
    monkeypatch.setattr(sched.display, "is_busy", lambda: True)
    assert sched.show_previous_photo() is False
    assert sched._current_path == "/fake/p1.png"


def test_specific_refused_while_display_busy(sched, monkeypatch):
    monkeypatch.setattr(sched.display, "is_busy", lambda: True)
    assert sched.show_specific_photo(2) is False
    assert sched._current_path == "/fake/p1.png"
    assert sched._history == []


def test_next_proceeds_when_display_idle(sched, monkeypatch):
    monkeypatch.setattr(sched.display, "is_busy", lambda: False)
    assert sched.show_next_photo() is True
    assert sched._current_path == "/fake/p2.png"
