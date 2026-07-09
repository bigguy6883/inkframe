"""Setup mode must exit after WiFi is successfully configured.

Bug: _in_setup_mode was set on Button D / boot-without-WiFi but never cleared,
so the captive-portal routes kept redirecting to /setup/wifi until restart.
"""

import pytest


@pytest.fixture
def client(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module.wifi_manager, "scan_networks", lambda: [])
    monkeypatch.setattr(app_module.wifi_manager, "connect_to_wifi", lambda s, p: True)
    monkeypatch.setattr(app_module.wifi_manager, "is_ap_mode", lambda: False)
    monkeypatch.setattr(app_module.models, "update_settings", lambda u: {})

    app_module.app.config['TESTING'] = True
    with app_module._setup_mode_lock:
        app_module._in_setup_mode = True
    yield app_module.app.test_client(), app_module
    with app_module._setup_mode_lock:
        app_module._in_setup_mode = False


def test_successful_wifi_config_exits_setup_mode(client):
    test_client, app_module = client
    resp = test_client.post('/setup/wifi', data={'ssid': 'HomeNet', 'password': 'pw'})
    assert resp.status_code == 302  # redirect to index on success
    assert app_module._in_setup_mode is False


def test_failed_wifi_config_stays_in_setup_mode(client, monkeypatch):
    test_client, app_module = client
    monkeypatch.setattr(app_module.wifi_manager, "connect_to_wifi", lambda s, p: False)
    resp = test_client.post('/setup/wifi', data={'ssid': 'HomeNet', 'password': 'bad'})
    assert resp.status_code == 200  # re-renders setup page with error
    assert app_module._in_setup_mode is True


def test_captive_portal_stops_redirecting_after_setup(client):
    test_client, app_module = client
    test_client.post('/setup/wifi', data={'ssid': 'HomeNet', 'password': 'pw'})
    resp = test_client.get('/generate_204')
    assert resp.status_code == 204
