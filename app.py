#!/usr/bin/env python3
"""
photos.local - E-Ink Photo Frame
Flask web app with drag-drop upload, gallery management, and e-ink display control
"""

import os
import sys
import time
import threading
import signal
import secrets
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, send_from_directory
)

sys.path.insert(0, str(Path(__file__).parent))

import models
import display
import image_processor
import wifi_manager
import scheduler

try:
    import lgpio
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("lgpio not available - button handling disabled")

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)

# Button GPIO pins (active LOW with pull-up)
BUTTON_A = 5   # Info screen
BUTTON_B = 6   # Previous photo
BUTTON_C = 16  # Next photo
BUTTON_D = 24  # Setup mode / Long press: reboot

_buttons_initialized = False
_in_setup_mode = False
_button_thread = None
_gpio_handle = None

POLL_INTERVAL = 0.05    # 50ms polling
DEBOUNCE_TIME = 0.3     # 300ms debounce
HOLD_TIME = 2.0         # 2s for long-press reboot
_BUTTON_PINS = [BUTTON_A, BUTTON_B, BUTTON_C, BUTTON_D]


# --- GPIO Button Handlers ---

def setup_buttons():
    global _buttons_initialized, _button_thread, _gpio_handle
    if not GPIO_AVAILABLE or _buttons_initialized:
        return

    try:
        _gpio_handle = lgpio.gpiochip_open(0)
        for pin in _BUTTON_PINS:
            lgpio.gpio_claim_input(_gpio_handle, pin, lgpio.SET_PULL_UP)

        _buttons_initialized = True
        _button_thread = threading.Thread(target=_button_poll_loop, daemon=True)
        _button_thread.start()
        print("Button handlers initialized (lgpio polling)")
    except Exception as e:
        print(f"Failed to initialize buttons: {e}")


def _button_poll_loop():
    """Poll buttons via lgpio in a background thread."""
    last_press = {pin: 0 for pin in _BUTTON_PINS}
    btn_d_down_since = None

    handlers = {
        BUTTON_A: lambda: threading.Thread(target=_btn_info, daemon=True).start(),
        BUTTON_B: lambda: threading.Thread(target=scheduler.show_previous_photo, daemon=True).start(),
        BUTTON_C: lambda: threading.Thread(target=scheduler.show_next_photo, daemon=True).start(),
    }

    while True:
        now = time.time()

        try:
            for pin, handler in handlers.items():
                if lgpio.gpio_read(_gpio_handle, pin) == 0 and now - last_press[pin] > DEBOUNCE_TIME:
                    last_press[pin] = now
                    print(f"Button GPIO {pin} pressed")
                    handler()

            # Button D: short press = setup, long hold = reboot
            if lgpio.gpio_read(_gpio_handle, BUTTON_D) == 0:
                if btn_d_down_since is None:
                    btn_d_down_since = now
                elif now - btn_d_down_since >= HOLD_TIME:
                    print("Button D held - rebooting")
                    _btn_reboot()
                    btn_d_down_since = None
            else:
                if btn_d_down_since is not None:
                    if now - btn_d_down_since < HOLD_TIME and now - last_press[BUTTON_D] > DEBOUNCE_TIME:
                        last_press[BUTTON_D] = now
                        print("Button D short press - setup mode")
                        threading.Thread(target=_btn_setup, daemon=True).start()
                    btn_d_down_since = None
        except Exception as e:
            print(f"Button poll error: {e}")

        time.sleep(POLL_INTERVAL)


def _btn_info():
    wifi_status = wifi_manager.get_wifi_status() or "Not connected"
    photo_count = models.get_photo_count()
    display.show_info_screen(photo_count=photo_count, wifi_status=wifi_status, ap_mode=_in_setup_mode)


def _btn_setup():
    global _in_setup_mode
    if not _in_setup_mode:
        _in_setup_mode = True
        wifi_manager.start_ap_mode()
        display.show_info_screen(ap_mode=True)
        print("Entered setup mode")


def _btn_reboot():
    print("Rebooting...")
    display.show_message("Rebooting...", "Please wait")
    os.system("sudo reboot")


# --- Page Routes ---

@app.route('/')
def index():
    """Main page - gallery with upload"""
    photos = models.get_all_photos()
    settings = models.load_settings()
    status = scheduler.get_slideshow_status()
    return render_template('index.html', photos=photos, settings=settings, status=status)


@app.route('/settings')
def settings_page():
    """Display and slideshow settings page"""
    settings = models.load_settings()
    status = scheduler.get_slideshow_status()
    return render_template('settings.html',
                           settings=settings, status=status,
                           interval_options=scheduler.INTERVAL_OPTIONS)


@app.route('/setup/wifi', methods=['GET', 'POST'])
def setup_wifi():
    """WiFi configuration page"""
    if request.method == 'POST':
        ssid = request.form.get('ssid', '').strip()
        password = request.form.get('password', '')

        if not ssid:
            return render_template('setup_wifi.html', networks=wifi_manager.scan_networks(),
                                   error="Please select a WiFi network")

        if wifi_manager.connect_to_wifi(ssid, password):
            models.update_settings({"wifi": {"ssid": ssid, "configured": True}})
            return redirect(url_for('index'))
        else:
            return render_template('setup_wifi.html', networks=wifi_manager.scan_networks(),
                                   error=f"Failed to connect to {ssid}")

    networks = wifi_manager.scan_networks()
    return render_template('setup_wifi.html', networks=networks)


# --- Photo API ---

@app.route('/api/photos/upload', methods=['POST'])
def upload_photo():
    """Upload a photo (multipart form data)"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    settings = models.load_settings()
    max_size = settings.get('upload', {}).get('max_file_size_mb', 20) * 1024 * 1024
    fit_mode = settings.get('display', {}).get('fit_mode', 'contain')

    # Check file size
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > max_size:
        return jsonify({'success': False, 'error': 'File too large'}), 413

    if not image_processor.is_allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'File type not allowed'}), 400

    result = image_processor.process_upload(file, fit_mode)
    if not result:
        return jsonify({'success': False, 'error': 'Failed to process image'}), 500

    photo_id = models.add_photo(
        filename=result['filename'],
        original_path=result['original_path'],
        display_path=result['display_path'],
        thumbnail_path=result['thumbnail_path'],
        width=result['width'],
        height=result['height'],
        file_size=result['file_size'],
        mime_type=result['mime_type'],
        date_taken=result['date_taken']
    )

    # Auto-start slideshow if first photo and auto_start enabled
    if models.get_photo_count() == 1:
        if settings.get('slideshow', {}).get('auto_start', True):
            scheduler.start_slideshow()

    return jsonify({
        'success': True,
        'photo': {
            'id': photo_id,
            'filename': result['filename'],
            'thumbnail_url': url_for('serve_thumbnail', filename=Path(result['thumbnail_path']).name)
        }
    })


@app.route('/api/photos', methods=['GET'])
def list_photos():
    """List all photos with pagination"""
    limit = request.args.get('limit', type=int)
    offset = request.args.get('offset', 0, type=int)

    photos = models.get_all_photos(limit=limit, offset=offset)
    total = models.get_photo_count()

    for p in photos:
        p['thumbnail_url'] = url_for('serve_thumbnail', filename=Path(p['thumbnail_path']).name)

    return jsonify({'photos': photos, 'total': total})


@app.route('/api/photos/<int:photo_id>', methods=['DELETE'])
def delete_photo(photo_id):
    """Delete a single photo"""
    photo = models.delete_photo(photo_id)
    if not photo:
        return jsonify({'success': False, 'error': 'Photo not found'}), 404

    image_processor.delete_photo_files(photo)
    return jsonify({'success': True})


@app.route('/api/photos/delete-bulk', methods=['POST'])
def delete_photos_bulk():
    """Delete multiple photos"""
    data = request.get_json()
    if not data or 'ids' not in data:
        return jsonify({'success': False, 'error': 'No photo IDs provided'}), 400

    photos = models.delete_photos_bulk(data['ids'])
    for photo in photos:
        image_processor.delete_photo_files(photo)

    return jsonify({'success': True, 'deleted': len(photos)})


@app.route('/thumbnails/<filename>')
def serve_thumbnail(filename):
    """Serve a thumbnail image"""
    return send_from_directory(str(image_processor.THUMBNAILS_DIR), filename)


# --- Display API ---

@app.route('/api/display/next', methods=['POST'])
def display_next():
    """Show next photo on display"""
    success = scheduler.show_next_photo()
    return jsonify({'success': success})


@app.route('/api/display/prev', methods=['POST'])
def display_prev():
    """Show previous photo on display"""
    success = scheduler.show_previous_photo()
    return jsonify({'success': success})


@app.route('/api/display/show/<int:photo_id>', methods=['POST'])
def display_show(photo_id):
    """Show a specific photo on display"""
    success = scheduler.show_specific_photo(photo_id)
    return jsonify({'success': success})


@app.route('/api/display/info', methods=['POST'])
def display_info():
    """Show info screen on display"""
    wifi_status = wifi_manager.get_wifi_status() or "Not connected"
    photo_count = models.get_photo_count()
    display.show_info_screen(photo_count=photo_count, wifi_status=wifi_status, ap_mode=_in_setup_mode)
    return jsonify({'success': True})


# --- Slideshow API ---

@app.route('/api/slideshow/start', methods=['POST'])
def start_slideshow():
    """Start slideshow"""
    scheduler.start_slideshow()
    models.update_settings({"slideshow": {"enabled": True}})
    return jsonify({'success': True})


@app.route('/api/slideshow/stop', methods=['POST'])
def stop_slideshow():
    """Stop slideshow"""
    scheduler.stop_slideshow()
    models.update_settings({"slideshow": {"enabled": False}})
    return jsonify({'success': True})


# --- Settings API ---

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """Get current settings"""
    return jsonify(models.load_settings())


@app.route('/api/settings', methods=['POST'])
def update_settings():
    """Update settings"""
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400

    updates = {}

    if 'display' in data:
        updates['display'] = {}
        for key in ['orientation', 'fit_mode', 'saturation']:
            if key in data['display']:
                val = data['display'][key]
                if key == 'saturation':
                    val = max(0.0, min(1.0, float(val)))
                updates['display'][key] = val

    if 'slideshow' in data:
        updates['slideshow'] = {}
        for key in ['order', 'interval_minutes', 'enabled']:
            if key in data['slideshow']:
                val = data['slideshow'][key]
                if key == 'interval_minutes':
                    val = int(val)
                elif key == 'enabled':
                    val = bool(val)
                updates['slideshow'][key] = val

    if updates:
        settings = models.update_settings(updates)

        # Restart slideshow if interval changed while running
        if 'slideshow' in updates and 'interval_minutes' in updates['slideshow']:
            if scheduler.is_slideshow_running():
                scheduler.start_slideshow()

    return jsonify({'success': True, 'settings': models.load_settings()})


# --- Status API ---

@app.route('/api/status')
def api_status():
    """Full system status"""
    settings = models.load_settings()
    status = scheduler.get_slideshow_status()

    return jsonify({
        'wifi': {
            'connected': wifi_manager.is_wifi_connected(),
            'ssid': wifi_manager.get_wifi_status(),
            'ap_mode': wifi_manager.is_ap_mode()
        },
        'slideshow': status,
        'photos': {
            'count': models.get_photo_count()
        },
        'display': settings.get('display', {}),
        'display_busy': display.is_busy()
    })


# --- Captive Portal ---

@app.route('/hotspot-detect')
@app.route('/generate_204')
@app.route('/ncsi.txt')
def captive_portal_detect():
    if _in_setup_mode or wifi_manager.is_ap_mode():
        return redirect(url_for('setup_wifi'))
    return '', 204


# --- Startup ---

def signal_handler(signum, frame):
    print("Shutting down...")
    scheduler.shutdown()
    sys.exit(0)


def main():
    models.init_db()
    image_processor.ensure_dirs()
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    setup_buttons()

    global _in_setup_mode

    print("Checking WiFi connectivity...")
    time.sleep(3)

    if wifi_manager.is_wifi_connected():
        print(f"Connected to WiFi: {wifi_manager.get_current_ssid()}")
        _in_setup_mode = False

        photo_count = models.get_photo_count()
        settings = models.load_settings()

        if photo_count > 0 and settings.get("slideshow", {}).get("enabled", True):
            scheduler.start_slideshow()
        else:
            wifi_status = wifi_manager.get_wifi_status() or "Connected"
            display.show_info_screen(photo_count=photo_count, wifi_status=wifi_status)
    else:
        print("No WiFi connection - starting AP mode")
        _in_setup_mode = True
        wifi_manager.start_ap_mode()
        display.show_info_screen(ap_mode=True)

    print("Starting photos.local web server...")
    app.run(host='0.0.0.0', port=80, threaded=True)


if __name__ == '__main__':
    main()
