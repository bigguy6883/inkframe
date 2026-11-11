"""WiFi AP/client mode switching using NetworkManager"""

import subprocess
import time
import os
import tempfile

AP_SSID = "inkframe-setup"
AP_PASSWORD = "photoframe"

STARTUP_WIFI_TIMEOUT = 90   # seconds to wait for a saved network at startup
CONNECTING_GRACE = 60       # extra seconds allowed while a connection is mid-flight
RECONNECT_WAIT = 30         # seconds nmcli may spend on one recovery attempt


def run_cmd(cmd, check=True):
    """Run a command (as arg list) and return output"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check
        )
        if result.returncode != 0:
            cmd_str = ' '.join(str(c) for c in cmd)
            print(f"Command exited {result.returncode}: {cmd_str}")
            if result.stderr.strip():
                print(f"  stderr: {result.stderr.strip()}")
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {' '.join(str(c) for c in cmd)}")
        print(f"Error: {e.stderr}")
        return None


def get_current_ssid():
    """Get currently connected WiFi SSID"""
    output = run_cmd(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"], check=False)
    if not output:
        return None
    for line in output.split('\n'):
        if line.startswith('yes:'):
            ssid = line.split(':', 1)[1]
            if ssid:
                return ssid
    return None


def get_wifi_status():
    """Get WiFi connection status"""
    ssid = get_current_ssid()
    if ssid:
        return ssid

    # Check if in AP mode
    output = run_cmd(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show", "--active"], check=False)
    if output and "wifi" in output.lower():
        if AP_SSID in output:
            return "AP Mode"
    return None


def is_wifi_connected():
    """Check if connected to a WiFi network (not AP mode)"""
    ssid = get_current_ssid()
    return ssid is not None and ssid != AP_SSID


def is_wifi_connecting():
    """Check if NetworkManager is partway through joining a WiFi network"""
    output = run_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "dev"], check=False)
    if not output:
        return False
    for line in output.split('\n'):
        parts = line.split(':', 2)
        if len(parts) == 3 and parts[1] == 'wifi' and parts[2].startswith('connecting'):
            return True
    return False


def is_ap_mode():
    """Check if currently in AP mode"""
    output = run_cmd(["nmcli", "-t", "-f", "NAME", "con", "show", "--active"], check=False)
    if output:
        return "Hotspot" in output or AP_SSID in output
    return False


def scan_networks():
    """Scan for available WiFi networks"""
    # Trigger a fresh scan
    run_cmd(["nmcli", "dev", "wifi", "rescan"], check=False)
    time.sleep(2)

    output = run_cmd(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"], check=False)
    if not output:
        return []

    networks = []
    seen = set()

    for line in output.split('\n'):
        # maxsplit=2 so SSIDs containing colons are preserved in parts[0]
        parts = line.rsplit(':', maxsplit=2)
        if len(parts) >= 3:
            ssid = parts[0].strip()
            if ssid and ssid not in seen and ssid != AP_SSID:
                seen.add(ssid)
                networks.append({
                    'ssid': ssid,
                    'signal': int(parts[1]) if parts[1].isdigit() else 0,
                    'security': parts[2].strip() if len(parts) > 2 else 'Open'
                })

    # Sort by signal strength
    networks.sort(key=lambda x: x['signal'], reverse=True)
    return networks


def get_wifi_interface():
    """Detect the first available WiFi interface name (falls back to wlan0)."""
    output = run_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE", "dev"], check=False)
    if output:
        for line in output.split('\n'):
            parts = line.rsplit(':', maxsplit=1)
            if len(parts) == 2 and parts[1].strip() == 'wifi':
                iface = parts[0].strip()
                if iface:
                    return iface
    return "wlan0"


def start_ap_mode():
    """Start WiFi access point mode"""
    print("Starting AP mode...")

    # Stop any existing hotspot
    run_cmd(["nmcli", "con", "down", "Hotspot"], check=False)
    run_cmd(["nmcli", "con", "delete", "Hotspot"], check=False)

    # Create hotspot
    iface = get_wifi_interface()
    result = run_cmd(["nmcli", "dev", "wifi", "hotspot", "ifname", iface,
                      "ssid", AP_SSID, "password", AP_PASSWORD], check=False)
    print(f"Hotspot command result: {result}")
    time.sleep(2)

    if not is_ap_mode():
        # Retry: bring up if connection was created but not activated
        run_cmd(["nmcli", "con", "up", "Hotspot"], check=False)
        time.sleep(2)

    active = is_ap_mode()
    print(f"AP mode active: {active}")
    return active


def stop_ap_mode():
    """Stop WiFi access point mode"""
    print("Stopping AP mode...")
    run_cmd(["nmcli", "con", "down", "Hotspot"], check=False)
    time.sleep(1)


def connect_to_wifi(ssid, password):
    """Connect to a WiFi network"""
    print(f"Connecting to WiFi: {ssid}")

    # Stop AP mode if active
    if is_ap_mode():
        stop_ap_mode()

    # Check if connection already exists
    output = run_cmd(["nmcli", "-t", "-f", "NAME", "con", "show"], check=False)
    existing = output and ssid in output.split('\n')

    if existing:
        # Update password using passwd-file to avoid exposing it in process listings
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pw', delete=False) as f:
            f.write(f"wifi-sec.psk:{password}\n")
            pw_file = f.name
        try:
            run_cmd(["nmcli", "--passwd-file", pw_file, "con", "modify", ssid,
                     "wifi-sec.key-mgmt", "wpa-psk"], check=False)
            result = run_cmd(["nmcli", "con", "up", ssid], check=False)
        finally:
            os.unlink(pw_file)
    else:
        # Create new connection using passwd-file to avoid exposing password in process listings
        with tempfile.NamedTemporaryFile(mode='w', suffix='.pw', delete=False) as f:
            f.write(f"wifi-sec.psk:{password}\n")
            pw_file = f.name
        try:
            result = run_cmd(["nmcli", "--passwd-file", pw_file,
                              "dev", "wifi", "connect", ssid], check=False)
        finally:
            os.unlink(pw_file)

    # Wait for connection
    time.sleep(5)

    if is_wifi_connected():
        print(f"Successfully connected to {ssid}")
        return True
    else:
        print(f"Failed to connect to {ssid}")
        return False


def get_saved_networks():
    """Get list of saved WiFi networks"""
    output = run_cmd(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"], check=False)
    if not output:
        return []

    networks = []
    for line in output.split('\n'):
        parts = line.split(':')
        if len(parts) >= 2 and parts[1] == '802-11-wireless':
            name = parts[0]
            if name != "Hotspot":
                networks.append(name)
    return networks


def get_saved_ssids():
    """Map each saved WiFi connection name to the SSID it joins"""
    ssids = {}
    for name in get_saved_networks():
        ssid = run_cmd(["nmcli", "-g", "802-11-wireless.ssid", "con", "show", name],
                       check=False)
        if ssid:
            ssids[name] = ssid
    return ssids


def try_reconnect_saved():
    """
    From AP mode, rejoin a saved network if one is in range.
    The hotspot is only dropped when a saved SSID shows up in a scan, and is
    restored if the join fails. Returns True once connected.
    """
    visible = {n['ssid'] for n in scan_networks()}
    name = next((name for name, ssid in get_saved_ssids().items() if ssid in visible), None)
    if name is None:
        return False

    print(f"Saved network {name} is back in range — leaving AP mode to rejoin it")
    stop_ap_mode()
    run_cmd(["nmcli", "--wait", str(RECONNECT_WAIT), "con", "up", name], check=False)
    if is_wifi_connected():
        print(f"Reconnected to {name}")
        return True

    print(f"Could not rejoin {name} — restoring AP mode")
    start_ap_mode()
    return False


def ensure_wifi_connected(timeout=STARTUP_WIFI_TIMEOUT):
    """
    Wait for NetworkManager to establish a saved WiFi connection.
    Waits up to CONNECTING_GRACE longer while a connection is in progress,
    so a slow join is never torn down to start the hotspot.
    Returns True if connected, False if should start AP mode.
    """
    if is_wifi_connected():
        return True

    saved = get_saved_networks()
    if not saved:
        print("No saved WiFi networks — will start AP mode")
        return False

    print(f"Waiting up to {timeout}s for WiFi ({len(saved)} saved network(s): {', '.join(saved[:3])})...")
    start = time.time()
    deadline = start + timeout
    hard_deadline = deadline + CONNECTING_GRACE
    while time.time() < deadline or (time.time() < hard_deadline and is_wifi_connecting()):
        if is_wifi_connected():
            ssid = get_current_ssid()
            print(f"WiFi connected: {ssid}")
            return True
        time.sleep(1)

    print(f"WiFi not connected after {int(time.time() - start)}s — will start AP mode")
    return False
