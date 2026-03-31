import json
import pytest
from pathlib import Path


@pytest.fixture
def settings_dir(tmp_path):
    """Patch models to use temp directory for settings."""
    import models
    original_path = models.SETTINGS_PATH
    models.SETTINGS_PATH = tmp_path / "settings.json"
    yield tmp_path
    models.SETTINGS_PATH = original_path


def test_migrate_smart_recenter_true(settings_dir):
    """smart_recenter: true should migrate to crop_mode: smart"""
    import models
    models.SETTINGS_PATH.write_text(json.dumps({
        "display": {
            "orientation": "horizontal",
            "fit_mode": "cover",
            "saturation": 0.5,
            "smart_recenter": True
        },
        "slideshow": {"order": "random", "interval_minutes": 60, "enabled": True, "auto_start": True, "current_index": 0},
        "upload": {"max_file_size_mb": 20},
        "wifi": {"ssid": "", "configured": False}
    }))
    settings = models.load_settings()
    assert settings['display']['crop_mode'] == 'smart'
    assert 'smart_recenter' not in settings['display']
    # Verify it was persisted
    saved = json.loads(models.SETTINGS_PATH.read_text())
    assert saved['display']['crop_mode'] == 'smart'
    assert 'smart_recenter' not in saved['display']


def test_migrate_smart_recenter_false(settings_dir):
    """smart_recenter: false should migrate to crop_mode: center"""
    import models
    models.SETTINGS_PATH.write_text(json.dumps({
        "display": {
            "orientation": "horizontal",
            "fit_mode": "contain",
            "saturation": 0.5,
            "smart_recenter": False
        },
        "slideshow": {"order": "random", "interval_minutes": 60, "enabled": True, "auto_start": True, "current_index": 0},
        "upload": {"max_file_size_mb": 20},
        "wifi": {"ssid": "", "configured": False}
    }))
    settings = models.load_settings()
    assert settings['display']['crop_mode'] == 'center'
    assert 'smart_recenter' not in settings['display']


def test_fresh_install_defaults(settings_dir):
    """Fresh install should get crop_mode: center, no smart_recenter"""
    import models
    settings = models.load_settings()
    assert settings['display']['crop_mode'] == 'center'
    assert 'smart_recenter' not in settings['display']


def test_already_migrated_is_idempotent(settings_dir):
    """Settings with crop_mode already set should not change"""
    import models
    models.SETTINGS_PATH.write_text(json.dumps({
        "display": {
            "orientation": "horizontal",
            "fit_mode": "cover",
            "saturation": 0.5,
            "crop_mode": "smart"
        },
        "slideshow": {"order": "random", "interval_minutes": 60, "enabled": True, "auto_start": True, "current_index": 0},
        "upload": {"max_file_size_mb": 20},
        "wifi": {"ssid": "", "configured": False}
    }))
    settings = models.load_settings()
    assert settings['display']['crop_mode'] == 'smart'
    assert 'smart_recenter' not in settings['display']
