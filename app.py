#!/usr/bin/env python3
"""
photos.local - Google Photos E-Ink Frame
Main Flask application with display controller
"""

import os
import sys
import json
import time
import threading
import signal
import secrets
from pathlib import Path
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, session, flash
)

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

import models
import display
import wifi_manager
import photo_sync
import scheduler

# Try to import GPIO for button handling
try:
    from gpiozero import Button
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("gpiozero not available - button handling disabled")

# Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

# Button GPIO pins
BUTTON_A = 5   # Info screen
BUTTON_B = 6   # Previous photo
BUTTON_C = 16  # Next photo
BUTTON_D = 24  # Setup mode / Long press: reboot

# Global state
_buttons_initialized = False
_in_setup_mode = False


def needs_setup():
    """Check if initial setup is required"""
    settings = models.load_settings()
    wifi_configured = settings.get("wifi", {}).get("configured", False)
    rclone_configured = photo_sync.is_configured()
    has_photos = len(photo_sync.get_cached_photos()) > 0
    return not wifi_configured or not rclone_configured or not has_photos


def setup_buttons():
    """Initialize GPIO button handlers"""
    global _buttons_initialized

    if not GPIO_AVAILABLE or _buttons_initialized:
        return

    try:
        btn_a = Button(BUTTON_A, pull_up=True, hold_time=0.1)
        btn_b = Button(BUTTON_B, pull_up=True, hold_time=0.1)
        btn_c = Button(BUTTON_C, pull_up=True, hold_time=0.1)
        btn_d = Button(BUTTON_D, pull_up=True, hold_time=2.0)  # Long press for reboot

        btn_a.when_pressed = button_a_handler
        btn_b.when_pressed = button_b_handler
        btn_c.when_pressed = button_c_handler
        btn_d.when_pressed = button_d_handler
        btn_d.when_held = button_d_held_handler

        _buttons_initialized = True
        print("Button handlers initialized")
    except Exception as e:
        print(f"Failed to initialize buttons: {e}")


def button_a_handler():
    """Button A: Show info screen"""
    def do_show_info():
        wifi_status = wifi_manager.get_wifi_status() or "Not connected"
        rclone_status = photo_sync.is_configured()
        photos = photo_sync.get_cached_photos()

        display.show_info_screen(
            photo_count=len(photos),
            wifi_status=wifi_status,
            google_status=rclone_status,
            ap_mode=_in_setup_mode
        )

    threading.Thread(target=do_show_info).start()


def button_b_handler():
    """Button B: Previous photo"""
    def do_prev():
        scheduler.show_previous_photo()

    threading.Thread(target=do_prev).start()


def button_c_handler():
    """Button C: Next photo"""
    def do_next():
        scheduler.show_next_photo()

    threading.Thread(target=do_next).start()


def button_d_handler():
    """Button D: Enter setup mode (short press)"""
    global _in_setup_mode

    if not _in_setup_mode:
        def do_setup():
            global _in_setup_mode
            _in_setup_mode = True
            wifi_manager.start_ap_mode()
            display.show_info_screen(ap_mode=True)
            print("Entered setup mode")

        threading.Thread(target=do_setup).start()


def button_d_held_handler():
    """Button D held: Reboot"""
    print("Rebooting...")
    display.show_message("Rebooting...", "Please wait")
    os.system("sudo reboot")


# Flask routes

@app.route('/')
def index():
    """Main page - shows setup wizard or slideshow settings"""
    if needs_setup():
        return redirect(url_for('setup'))

    settings = models.load_settings()
    status = scheduler.get_slideshow_status()
    cache_stats = photo_sync.get_cache_stats()

    return render_template('slideshow.html',
        settings=settings,
        status=status,
        cache_stats=cache_stats,
        interval_options=scheduler.INTERVAL_OPTIONS
    )


@app.route('/setup')
def setup():
    """Setup wizard start page"""
    settings = models.load_settings()
    wifi_configured = settings.get("wifi", {}).get("configured", False)
    google_authenticated = settings.get("google", {}).get("authenticated", False)

    # Determine which step to show
    if not wifi_configured:
        return redirect(url_for('setup_wifi'))
    elif not google_authenticated:
        return redirect(url_for('setup_google'))
    else:
        return redirect(url_for('setup_album'))


@app.route('/setup/wifi', methods=['GET', 'POST'])
def setup_wifi():
    """WiFi configuration page"""
    if request.method == 'POST':
        ssid = request.form.get('ssid', '').strip()
        password = request.form.get('password', '')

        if not ssid:
            flash('Please select or enter a WiFi network', 'error')
            return redirect(url_for('setup_wifi'))

        # Try to connect
        if wifi_manager.connect_to_wifi(ssid, password):
            # Update settings
            models.update_settings({
                "wifi": {"ssid": ssid, "configured": True}
            })
            flash(f'Connected to {ssid}', 'success')
            return redirect(url_for('setup_google'))
        else:
            flash(f'Failed to connect to {ssid}. Please check the password.', 'error')
            return redirect(url_for('setup_wifi'))

    # GET - show WiFi selection
    networks = wifi_manager.scan_networks()
    return render_template('setup_wifi.html', networks=networks)


@app.route('/setup/google')
def setup_google():
    """rclone setup page for Google Photos"""
    # Check if already configured
    if photo_sync.is_configured():
        return redirect(url_for('setup_album'))

    rclone_installed = photo_sync.is_rclone_installed()
    remotes = photo_sync.get_rclone_remotes() if rclone_installed else []
    gphotos_remote = photo_sync.get_google_photos_remote()

    return render_template('setup_rclone.html',
        rclone_installed=rclone_installed,
        remotes=remotes,
        gphotos_remote=gphotos_remote
    )


@app.route('/setup/check-rclone')
def check_rclone():
    """Check rclone configuration status"""
    return jsonify({
        'installed': photo_sync.is_rclone_installed(),
        'configured': photo_sync.is_configured(),
        'remote': photo_sync.get_google_photos_remote(),
        'remotes': photo_sync.get_rclone_remotes()
    })


@app.route('/setup/album', methods=['GET', 'POST'])
def setup_album():
    """Album selection and sync page"""
    if not photo_sync.is_configured():
        return redirect(url_for('setup_google'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'sync':
            album = request.form.get('album', '').strip()
            if not album:
                flash('Please select an album', 'error')
                return redirect(url_for('setup_album'))

            success, message, count = photo_sync.sync_album(album)

            if success:
                # Save selected album
                models.update_settings({
                    "google": {"authenticated": True, "album": album}
                })
                flash(f'Synced {count} photos from "{album}"', 'success')

                # Start slideshow if we have photos
                if count > 0:
                    scheduler.start_slideshow()
                    return redirect(url_for('index'))
            else:
                flash(f'Sync failed: {message}', 'error')

            return redirect(url_for('setup_album'))

    # GET - show album selection page
    albums = photo_sync.list_albums()
    cache_stats = photo_sync.get_cache_stats()
    settings = models.load_settings()
    current_album = settings.get("google", {}).get("album", "")

    return render_template('setup_album.html',
        albums=albums,
        cache_stats=cache_stats,
        current_album=current_album
    )


@app.route('/settings', methods=['POST'])
def update_settings():
    """Update display and slideshow settings"""
    data = request.get_json() or request.form.to_dict()

    updates = {}

    # Display settings
    if 'orientation' in data or 'fit_mode' in data:
        display_updates = {}
        if 'orientation' in data:
            display_updates['orientation'] = data['orientation']
        if 'fit_mode' in data:
            display_updates['fit_mode'] = data['fit_mode']
        updates['display'] = display_updates

    # Slideshow settings
    if 'order' in data or 'interval_minutes' in data or 'enabled' in data:
        slideshow_updates = {}
        if 'order' in data:
            slideshow_updates['order'] = data['order']
        if 'interval_minutes' in data:
            slideshow_updates['interval_minutes'] = int(data['interval_minutes'])
        if 'enabled' in data:
            slideshow_updates['enabled'] = data['enabled'] in ['true', True, '1', 1]
        updates['slideshow'] = slideshow_updates

    if updates:
        models.update_settings(updates)

        # Restart slideshow if interval changed
        if 'slideshow' in updates and 'interval_minutes' in updates['slideshow']:
            if scheduler.is_slideshow_running():
                scheduler.start_slideshow()

        # Refresh current photo if display settings changed
        if 'display' in updates:
            scheduler.show_current_photo()

    if request.is_json:
        return jsonify({'success': True, 'settings': models.load_settings()})
    else:
        flash('Settings updated', 'success')
        return redirect(url_for('index'))


@app.route('/next', methods=['POST'])
def next_photo():
    """Show next photo"""
    scheduler.show_next_photo()
    if request.is_json:
        return jsonify({'success': True})
    return redirect(url_for('index'))


@app.route('/prev', methods=['POST'])
def prev_photo():
    """Show previous photo"""
    scheduler.show_previous_photo()
    if request.is_json:
        return jsonify({'success': True})
    return redirect(url_for('index'))


@app.route('/sync', methods=['POST'])
def sync_photos():
    """Trigger manual photo sync"""
    settings = models.load_settings()
    album = settings.get("google", {}).get("album")

    if not album:
        return jsonify({'success': False, 'error': 'No album configured'})

    success, message, count = photo_sync.sync_album(album)
    if success:
        return jsonify({'success': True, 'downloaded': count, 'message': message})
    else:
        return jsonify({'success': False, 'error': message})


@app.route('/info')
def show_info():
    """Show info screen on display"""
    wifi_status = wifi_manager.get_wifi_status() or "Not connected"
    rclone_status = photo_sync.is_configured()
    photos = photo_sync.get_cached_photos()

    display.show_info_screen(
        photo_count=len(photos),
        wifi_status=wifi_status,
        google_status=rclone_status,
        ap_mode=_in_setup_mode
    )

    if request.is_json:
        return jsonify({'success': True})
    return redirect(url_for('index'))


@app.route('/clear-cache', methods=['POST'])
def clear_cache():
    """Clear photo cache"""
    count = photo_sync.clear_cache()
    models.clear_all_photos()

    if request.is_json:
        return jsonify({'success': True, 'cleared': count})

    flash(f'Cleared {count} cached photos', 'success')
    return redirect(url_for('index'))


@app.route('/disconnect-google', methods=['POST'])
def disconnect_google():
    """Clear settings (rclone config remains)"""
    photo_sync.clear_cache()
    models.update_settings({
        "google": {"authenticated": False, "album": ""}
    })

    if request.is_json:
        return jsonify({'success': True})

    flash('Cleared photo settings', 'success')
    return redirect(url_for('setup'))


@app.route('/slideshow/start', methods=['POST'])
def start_slideshow():
    """Start slideshow"""
    scheduler.start_slideshow()
    models.update_settings({"slideshow": {"enabled": True}})

    if request.is_json:
        return jsonify({'success': True})
    return redirect(url_for('index'))


@app.route('/slideshow/stop', methods=['POST'])
def stop_slideshow():
    """Stop slideshow"""
    scheduler.stop_slideshow()
    models.update_settings({"slideshow": {"enabled": False}})

    if request.is_json:
        return jsonify({'success': True})
    return redirect(url_for('index'))


@app.route('/api/status')
def api_status():
    """API endpoint for current status"""
    settings = models.load_settings()
    status = scheduler.get_slideshow_status()
    cache_stats = photo_sync.get_cache_stats()
    wifi_status = wifi_manager.get_wifi_status()

    return jsonify({
        'wifi': {
            'connected': wifi_manager.is_wifi_connected(),
            'ssid': wifi_status,
            'ap_mode': wifi_manager.is_ap_mode()
        },
        'google': {
            'configured': photo_sync.is_configured(),
            'album': settings.get("google", {}).get("album", "")
        },
        'slideshow': status,
        'cache': cache_stats,
        'display': settings.get('display', {})
    })


@app.route('/hotspot-detect')
@app.route('/generate_204')
@app.route('/ncsi.txt')
def captive_portal_detect():
    """Handle captive portal detection requests"""
    if _in_setup_mode or wifi_manager.is_ap_mode():
        return redirect(url_for('setup'))
    return '', 204


def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print("Shutting down...")
    scheduler.shutdown()
    sys.exit(0)


def main():
    """Main entry point"""
    models.init_db()
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    setup_buttons()

    global _in_setup_mode

    # Smart WiFi check: verify ACTUAL connectivity, not just config flag
    print("Checking WiFi connectivity...")

    # Give NetworkManager time to auto-connect on boot
    time.sleep(3)

    if wifi_manager.is_wifi_connected():
        # Connected to WiFi - show web UI QR code
        print(f"Connected to WiFi: {wifi_manager.get_current_ssid()}")
        _in_setup_mode = False

        settings = models.load_settings()
        if needs_setup():
            # WiFi works but Google not configured - show info screen with web URL
            display.show_info_screen(
                wifi_status=wifi_manager.get_current_ssid(),
                google_status=False,
                ap_mode=False
            )
        else:
            # Fully configured - start slideshow
            if settings.get("slideshow", {}).get("enabled", True):
                photos = photo_sync.get_cached_photos()
                if photos:
                    scheduler.start_slideshow()
                else:
                    display.show_message("No Photos", "Sync photos from settings")
            else:
                scheduler.show_current_photo()
    else:
        # Not connected - start AP mode for setup
        print("No WiFi connection - starting AP mode")
        _in_setup_mode = True
        wifi_manager.start_ap_mode()
        display.show_info_screen(ap_mode=True)

    print("Starting photos.local web server...")
    app.run(host='0.0.0.0', port=80, threaded=True)


if __name__ == '__main__':
    main()
