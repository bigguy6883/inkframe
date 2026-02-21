"""WiFi AP/client mode switching using NetworkManager"""

import subprocess
import time
import os
import tempfile

AP_SSID = "inkframe-setup"
AP_PASSWORD = "photoframe"
AP_IP = "192.168.4.1"


def run_cmd(cmd, check=True):
    """Run a command (as arg list) and return output"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {cmd}")
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
        parts = line.split(':', maxsplit=2)
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


def start_ap_mode():
    """Start WiFi access point mode"""
    print("Starting AP mode...")

    # Stop any existing hotspot
    run_cmd(["nmcli", "con", "down", "Hotspot"], check=False)
    run_cmd(["nmcli", "con", "delete", "Hotspot"], check=False)

    # Create hotspot
    result = run_cmd(["nmcli", "dev", "wifi", "hotspot", "ifname", "wlan0",
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


def disconnect_wifi():
    """Disconnect from current WiFi"""
    ssid = get_current_ssid()
    if ssid:
        run_cmd(["nmcli", "con", "down", ssid], check=False)


def forget_wifi(ssid):
    """Forget a saved WiFi network"""
    run_cmd(["nmcli", "con", "delete", ssid], check=False)


def get_ip_address():
    """Get current IP address"""
    output = run_cmd(["hostname", "-I"], check=False)
    if output:
        return output.split()[0]
    return None


def setup_captive_portal():
    """
    Set up dnsmasq for captive portal DNS redirection.
    This makes all DNS queries resolve to the AP IP.
    """
    dnsmasq_conf = f"""
# Captive portal configuration
interface=wlan0
bind-interfaces
dhcp-range=192.168.4.2,192.168.4.20,255.255.255.0,24h
address=/#/{AP_IP}
"""

    # Write dnsmasq config
    try:
        with open('/tmp/dnsmasq-captive.conf', 'w') as f:
            f.write(dnsmasq_conf)

        # Stop system dnsmasq if running
        run_cmd(["sudo", "systemctl", "stop", "dnsmasq"], check=False)

        # Start dnsmasq with our config
        run_cmd(["sudo", "dnsmasq", "-C", "/tmp/dnsmasq-captive.conf"], check=False)
        return True
    except Exception as e:
        print(f"Failed to set up captive portal: {e}")
        return False


def stop_captive_portal():
    """Stop the captive portal DNS redirection"""
    run_cmd(["sudo", "pkill", "-f", "dnsmasq -C /tmp/dnsmasq-captive.conf"], check=False)
    run_cmd(["sudo", "systemctl", "start", "dnsmasq"], check=False)


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


def ensure_wifi_connected(timeout=15):
    """
    Try to connect to a saved WiFi network.
    Returns True if connected, False if should start AP mode.
    """
    # Check if already connected
    if is_wifi_connected():
        return True

    # Get saved networks and try to connect
    saved = get_saved_networks()
    if not saved:
        print("No saved WiFi networks")
        return False

    # NetworkManager usually auto-connects, just wait
    start = time.time()
    while time.time() - start < timeout:
        if is_wifi_connected():
            return True
        time.sleep(1)

    print(f"WiFi connection timeout after {timeout}s")
    return False
