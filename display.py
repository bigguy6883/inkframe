"""E-ink display abstraction with MockDisplay for headless development"""

import os
import time
import threading
import socket
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

try:
    from inky.auto import auto
    INKY_AVAILABLE = True
except ImportError:
    INKY_AVAILABLE = False

try:
    import qrcode
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False

DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480
DATA_DIR = Path(__file__).parent / "data"
MOCK_DISPLAY_PATH = DATA_DIR / "mock_display.png"

# Display state
_display = None
_busy = False
_busy_lock = threading.Lock()


class MockDisplay:
    """Saves output to PNG instead of driving e-ink hardware"""

    def __init__(self):
        self.width = DISPLAY_WIDTH
        self.height = DISPLAY_HEIGHT
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        print(f"MockDisplay initialized ({self.width}x{self.height})")

    def set_image(self, img, saturation=0.5):
        self._img = img

    def show(self):
        if hasattr(self, '_img') and self._img:
            self._img.save(str(MOCK_DISPLAY_PATH))
            print(f"MockDisplay: saved to {MOCK_DISPLAY_PATH}")


def get_display():
    """Get or initialize display (real Inky or MockDisplay)"""
    global _display

    if _display is not None:
        return _display

    if INKY_AVAILABLE:
        try:
            _display = auto()
            _display.set_border(_display.BLACK)
            print(f"Inky display initialized: {_display.width}x{_display.height}")
            return _display
        except Exception as e:
            print(f"Failed to init Inky display: {e}")

    _display = MockDisplay()
    return _display


def is_busy():
    """Check if display is currently refreshing"""
    with _busy_lock:
        return _busy


def _show_on_display(img, saturation=0.5):
    """Internal: send image to display with busy guard"""
    global _busy

    with _busy_lock:
        if _busy:
            print("Display busy, skipping update")
            return False
        _busy = True

    try:
        display = get_display()
        if isinstance(display, MockDisplay):
            display.set_image(img, saturation)
            display.show()
        else:
            display.set_image(img, saturation=saturation)
            display.show()
        return True
    except Exception as e:
        print(f"Display error: {e}")
        return False
    finally:
        with _busy_lock:
            _busy = False


def show_photo(image_path, saturation=0.5):
    """
    Display a pre-rendered display image on the e-ink screen.
    The image should already be 800x480 (from image_processor).
    Runs in a background thread to avoid blocking.
    """
    def _do_show():
        try:
            img = Image.open(image_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            _show_on_display(img, saturation)
            print(f"Displayed: {image_path}")
        except Exception as e:
            print(f"Error showing photo: {e}")

    threading.Thread(target=_do_show, daemon=True).start()
    return True


def show_image_object(img, saturation=0.5):
    """Display a PIL Image object (for info screens, messages)"""
    def _do_show():
        _show_on_display(img, saturation)

    threading.Thread(target=_do_show, daemon=True).start()
    return True


# --- Info screen and message helpers ---

def _load_fonts():
    """Load system fonts, returns (large, medium, small)"""
    bold_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    regular_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    font_large = font_medium = font_small = None

    for path in bold_paths:
        if os.path.exists(path):
            try:
                font_large = ImageFont.truetype(path, 48)
                font_medium = ImageFont.truetype(path, 32)
                break
            except Exception:
                pass

    for path in regular_paths:
        if os.path.exists(path):
            try:
                font_small = ImageFont.truetype(path, 24)
                break
            except Exception:
                pass

    if font_large is None:
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large

    return font_large, font_medium, font_small


def get_system_ip():
    """Get the system's IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def generate_info_screen(photo_count=0, wifi_status="Unknown", ap_mode=False):
    """Generate an info screen with QR code and system information"""
    width, height = DISPLAY_WIDTH, DISPLAY_HEIGHT
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    ip = get_system_ip()
    hostname = socket.gethostname()

    # QR code
    if ap_mode:
        qr_data = "WIFI:T:WPA;S:photos-setup;P:photoframe;;"
    else:
        qr_data = f"http://{hostname}.local/"

    qr_size = min(width, height) // 2
    if QRCODE_AVAILABLE:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L,
                           box_size=10, border=2)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
        img.paste(qr_img, (20, 20))

    font_large, font_medium, font_small = _load_fonts()
    text_x = qr_size + 40
    text_y = 20

    if ap_mode:
        draw.text((text_x, text_y), "Setup Mode", font=font_large, fill=(0, 0, 0))
        text_y += 55
        draw.text((text_x, text_y), "1. Connect to WiFi:", font=font_small, fill=(0, 0, 0))
        text_y += 30
        draw.text((text_x + 20, text_y), "photos-setup", font=font_medium, fill=(0, 100, 200))
        text_y += 38
        draw.text((text_x + 20, text_y), "Password: photoframe", font=font_small, fill=(100, 100, 100))
        text_y += 35
        draw.text((text_x, text_y), "2. Open browser:", font=font_small, fill=(0, 0, 0))
        text_y += 30
        draw.text((text_x + 20, text_y), "http://192.168.4.1", font=font_small, fill=(0, 100, 200))
        text_y += 35
        draw.text((text_x, text_y), "Or scan QR to connect", font=font_small, fill=(100, 100, 100))
    else:
        draw.text((text_x, text_y), "photos.local", font=font_large, fill=(0, 0, 0))
        text_y += 70
        draw.text((text_x, text_y), f"IP: {ip}", font=font_medium, fill=(0, 0, 0))
        text_y += 45
        draw.text((text_x, text_y), f"http://{hostname}.local/", font=font_small, fill=(100, 100, 100))
        text_y += 40
        wifi_color = (0, 128, 0) if wifi_status and wifi_status != "Unknown" else (200, 0, 0)
        draw.text((text_x, text_y), f"WiFi: {wifi_status}", font=font_small, fill=wifi_color)
        text_y += 35
        draw.text((text_x, text_y), f"Photos: {photo_count}", font=font_small, fill=(0, 0, 0))
        text_y += 35
        draw.text((text_x, text_y), "Upload photos at the URL above", font=font_small, fill=(100, 100, 100))

    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(0, 0, 0), width=3)
    return img


def show_info_screen(photo_count=0, wifi_status="Unknown", ap_mode=False):
    """Generate and display the info screen"""
    img = generate_info_screen(photo_count, wifi_status, ap_mode)
    return show_image_object(img)


def show_message(title, message, submessage=None):
    """Display a simple centered message on the e-ink screen"""
    width, height = DISPLAY_WIDTH, DISPLAY_HEIGHT
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_large, font_medium, font_small = _load_fonts()

    title_bbox = draw.textbbox((0, 0), title, font=font_large)
    title_w = title_bbox[2] - title_bbox[0]
    title_x = (width - title_w) // 2
    title_y = height // 3
    draw.text((title_x, title_y), title, font=font_large, fill=(0, 0, 0))

    if message:
        msg_bbox = draw.textbbox((0, 0), message, font=font_medium)
        msg_w = msg_bbox[2] - msg_bbox[0]
        draw.text(((width - msg_w) // 2, title_y + 70), message, font=font_medium, fill=(100, 100, 100))

    if submessage:
        sub_bbox = draw.textbbox((0, 0), submessage, font=font_small)
        sub_w = sub_bbox[2] - sub_bbox[0]
        draw.text(((width - sub_w) // 2, title_y + 120), submessage, font=font_small, fill=(150, 150, 150))

    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=(0, 0, 0), width=3)
    return show_image_object(img)
