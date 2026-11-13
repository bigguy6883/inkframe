"""A power blip must not strand the frame in setup mode.

Bug (2026-11-04): the frame gave WiFi 15 s at startup, tore down a connection
that was mid-DHCP to start the setup hotspot, then never retried the saved
network — the setup screen stayed up for four days.
"""

import pytest

import wifi_manager


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(wifi_manager.time, "time", fake.time)
    monkeypatch.setattr(wifi_manager.time, "sleep", fake.sleep)
    return fake


def test_startup_waits_past_15s_for_slow_wifi(clock, monkeypatch):
    monkeypatch.setattr(wifi_manager, "get_saved_networks", lambda: ["home"])
    monkeypatch.setattr(wifi_manager, "is_wifi_connecting", lambda: False)
    monkeypatch.setattr(wifi_manager, "get_current_ssid", lambda: "HomeNet")
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: clock.now >= 40)
    assert wifi_manager.ensure_wifi_connected() is True


def test_startup_does_not_give_up_mid_connection(clock, monkeypatch):
    timeout = wifi_manager.STARTUP_WIFI_TIMEOUT
    monkeypatch.setattr(wifi_manager, "get_saved_networks", lambda: ["home"])
    monkeypatch.setattr(wifi_manager, "is_wifi_connecting", lambda: True)
    monkeypatch.setattr(wifi_manager, "get_current_ssid", lambda: "HomeNet")
    monkeypatch.setattr(wifi_manager, "is_wifi_connected",
                        lambda: clock.now >= timeout + 10)
    assert wifi_manager.ensure_wifi_connected() is True


def test_startup_gives_up_eventually_even_if_always_connecting(clock, monkeypatch):
    monkeypatch.setattr(wifi_manager, "get_saved_networks", lambda: ["home"])
    monkeypatch.setattr(wifi_manager, "is_wifi_connecting", lambda: True)
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: False)
    assert wifi_manager.ensure_wifi_connected() is False
    limit = wifi_manager.STARTUP_WIFI_TIMEOUT + wifi_manager.CONNECTING_GRACE
    assert clock.now <= limit + 1


def test_is_wifi_connecting_reads_device_state(monkeypatch):
    monkeypatch.setattr(wifi_manager, "run_cmd", lambda cmd, check=True:
                        "lo:loopback:connected (externally)\n"
                        "wlan0:wifi:connecting (getting IP configuration)")
    assert wifi_manager.is_wifi_connecting() is True
    monkeypatch.setattr(wifi_manager, "run_cmd", lambda cmd, check=True:
                        "wlan0:wifi:connected\nlo:loopback:connected (externally)")
    assert wifi_manager.is_wifi_connecting() is False


@pytest.fixture
def recovery(monkeypatch):
    """Frame in AP mode with one saved connection 'home' for SSID 'HomeNet'."""
    calls = []
    monkeypatch.setattr(wifi_manager, "get_saved_ssids", lambda: {"home": "HomeNet"})
    monkeypatch.setattr(wifi_manager, "stop_ap_mode", lambda: calls.append("stop_ap"))
    monkeypatch.setattr(wifi_manager, "start_ap_mode", lambda: calls.append("start_ap"))
    monkeypatch.setattr(wifi_manager, "run_cmd",
                        lambda cmd, check=True: calls.append(cmd) or "")
    return calls


def test_reconnect_skipped_when_saved_network_not_visible(recovery, monkeypatch):
    monkeypatch.setattr(wifi_manager, "scan_networks", lambda: [{"ssid": "Neighbour"}])
    assert wifi_manager.try_reconnect_saved() is False
    assert recovery == []  # hotspot left alone


def test_reconnect_joins_visible_saved_network(recovery, monkeypatch):
    monkeypatch.setattr(wifi_manager, "scan_networks", lambda: [{"ssid": "HomeNet"}])
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: True)
    assert wifi_manager.try_reconnect_saved() is True
    assert recovery[0] == "stop_ap"
    assert recovery[1][-3:] == ["con", "up", "home"]
    assert "start_ap" not in recovery


def test_failed_reconnect_restores_hotspot(recovery, monkeypatch):
    monkeypatch.setattr(wifi_manager, "scan_networks", lambda: [{"ssid": "HomeNet"}])
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: False)
    assert wifi_manager.try_reconnect_saved() is False
    assert recovery[-1] == "start_ap"


@pytest.fixture
def app_in_setup(monkeypatch):
    import app as app_module

    started = []
    monkeypatch.setattr(app_module, "_after_wifi_connected", lambda: started.append(True))
    with app_module._setup_mode_lock:
        app_module._in_setup_mode = True
    yield app_module, started
    with app_module._setup_mode_lock:
        app_module._in_setup_mode = False


def test_recovery_check_exits_setup_mode_when_wifi_returns(app_in_setup, monkeypatch):
    app_module, started = app_in_setup
    monkeypatch.setattr(app_module, "_last_portal_activity", None)
    monkeypatch.setattr(app_module.wifi_manager, "try_reconnect_saved", lambda: True)
    assert app_module._setup_recovery_check() is True
    assert app_module._in_setup_mode is False
    assert started == [True]


def test_recovery_check_keeps_setup_mode_when_wifi_still_gone(app_in_setup, monkeypatch):
    app_module, started = app_in_setup
    monkeypatch.setattr(app_module, "_last_portal_activity", None)
    monkeypatch.setattr(app_module.wifi_manager, "try_reconnect_saved", lambda: False)
    assert app_module._setup_recovery_check() is False
    assert app_module._in_setup_mode is True


def test_recovery_check_leaves_hotspot_alone_while_portal_in_use(app_in_setup, monkeypatch):
    app_module, started = app_in_setup
    tried = []
    monkeypatch.setattr(app_module.wifi_manager, "try_reconnect_saved",
                        lambda: tried.append(True) or True)
    app_module.app.config['TESTING'] = True
    monkeypatch.setattr(app_module.wifi_manager, "scan_networks", lambda: [])
    app_module.app.test_client().get('/setup/wifi')  # someone is on the portal
    assert app_module._setup_recovery_check() is False
    assert tried == []
    assert app_module._in_setup_mode is True


def test_recovery_check_stops_once_setup_mode_has_ended(app_in_setup, monkeypatch):
    app_module, started = app_in_setup
    tried = []
    monkeypatch.setattr(app_module.wifi_manager, "try_reconnect_saved",
                        lambda: tried.append(True) or True)
    with app_module._setup_mode_lock:
        app_module._in_setup_mode = False
    assert app_module._setup_recovery_check() is True  # nothing left to do
    assert tried == [] and started == []


# --- WiFi lost while running (2026-11-11: a failed roam left the frame offline 33 h) ---

@pytest.fixture
def dropped(monkeypatch):
    """Frame running normally with one saved connection 'home', WiFi down."""
    calls = []
    monkeypatch.setattr(wifi_manager, "get_saved_networks", lambda: ["home"])
    monkeypatch.setattr(wifi_manager, "is_wifi_connecting", lambda: False)
    monkeypatch.setattr(wifi_manager, "is_ap_mode", lambda: False)
    monkeypatch.setattr(wifi_manager, "run_cmd",
                        lambda cmd, check=True: calls.append(cmd) or "")
    return calls


def test_dropped_wifi_is_reactivated(dropped, monkeypatch):
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: bool(dropped))
    assert wifi_manager.reconnect_if_dropped() is True
    assert dropped[0][-3:] == ["con", "up", "home"]


def test_nothing_done_while_wifi_is_up(dropped, monkeypatch):
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: True)
    assert wifi_manager.reconnect_if_dropped() is False
    assert dropped == []


def test_join_in_progress_is_not_interrupted(dropped, monkeypatch):
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: False)
    monkeypatch.setattr(wifi_manager, "is_wifi_connecting", lambda: True)
    assert wifi_manager.reconnect_if_dropped() is False
    assert dropped == []


def test_hotspot_is_not_torn_down_by_the_watchdog(dropped, monkeypatch):
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: False)
    monkeypatch.setattr(wifi_manager, "is_ap_mode", lambda: True)
    assert wifi_manager.reconnect_if_dropped() is False
    assert dropped == []


def test_failed_reactivation_reports_false(dropped, monkeypatch):
    monkeypatch.setattr(wifi_manager, "is_wifi_connected", lambda: False)
    assert wifi_manager.reconnect_if_dropped() is False
    assert dropped[0][-3:] == ["con", "up", "home"]


def test_watchdog_check_skips_setup_mode(app_in_setup, monkeypatch):
    app_module, _ = app_in_setup
    tried = []
    monkeypatch.setattr(app_module.wifi_manager, "reconnect_if_dropped",
                        lambda: tried.append(True) or True)
    app_module._wifi_watchdog_check()
    assert tried == []


def test_watchdog_check_runs_outside_setup_mode(app_in_setup, monkeypatch):
    app_module, _ = app_in_setup
    tried = []
    monkeypatch.setattr(app_module.wifi_manager, "reconnect_if_dropped",
                        lambda: tried.append(True) or True)
    with app_module._setup_mode_lock:
        app_module._in_setup_mode = False
    app_module._wifi_watchdog_check()
    assert tried == [True]


# --- Setup hotspot must be WPA2-only ---

def test_hotspot_is_created_without_wpa3(monkeypatch):
    """By default NetworkManager also offers WPA3 (SAE) on the hotspot, which
    the frame's WiFi chip cannot serve; turning PMF off leaves WPA2 only."""
    calls = []
    monkeypatch.setattr(wifi_manager.time, "sleep", lambda s: None)
    monkeypatch.setattr(wifi_manager, "get_wifi_interface", lambda: "wlan0")
    monkeypatch.setattr(wifi_manager, "is_ap_mode", lambda: True)
    monkeypatch.setattr(wifi_manager, "run_cmd",
                        lambda cmd, check=True: calls.append(cmd) or "")
    assert wifi_manager.start_ap_mode() is True
    add = next(c for c in calls if c[1:3] == ["con", "add"])
    assert add[add.index("wifi-sec.pmf") + 1] == "disable"
    assert add[add.index("wifi-sec.key-mgmt") + 1] == "wpa-psk"
    assert add[add.index("ssid") + 1] == wifi_manager.AP_SSID
    assert calls.index(add) < calls.index(["nmcli", "con", "up", "Hotspot"])
    assert not any("hotspot" in c for c in calls)
