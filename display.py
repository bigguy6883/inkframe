"""E-ink display abstraction for Pimoroni Inky Impression"""

import os
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

# Display lock for thread safety
display_lock = threading.Lock()

# Global display instance
_display = None

CACHE_DIR = Path(__file__).parent / "cache"
INFO_IMAGE_PATH = CACHE_DIR / "info_screen.png"


def get_display():
    """Get or initialize the Inky display"""
    global _display

    if _display is not None:
        return _display

    if not INKY_AVAILABLE:
        print("Inky library not available - running in headless mode")
        return None

    try:
        _display = auto()
        _display.set_border(_display.BLACK)
        print(f"Initialized Inky display: {_display.width}x{_display.height}")
        return _display
    except Exception as e:
        print(f"Failed to initialize Inky display: {e}")
        return None


def get_display_size():
    """Get display dimensions, returns (width, height)"""
    display = get_display()
    if display:
        return display.width, display.height
    # Default to 7.3" Inky Impression size
    return 800, 480


def process_image(image_path, fit_mode="contain", orientation="horizontal"):
    """
    Process an image for display on the e-ink screen.

    Args:
        image_path: Path to the source image
        fit_mode: "contain" (fit with bars), "cover" (fill with crop), "stretch"
        orientation: "horizontal" or "vertical"

    Returns:
        PIL Image ready for display
    """
    width, height = get_display_size()

    # Swap dimensions for vertical orientation
    if orientation == "vertical":
        width, height = height, width

    # Open and convert image
    img = Image.open(image_path)

    # Handle EXIF rotation
    try:
        from PIL import ExifTags
        for orientation_tag in ExifTags.TAGS.keys():
            if ExifTags.TAGS[orientation_tag] == 'Orientation':
                break
        exif = img._getexif()
        if exif:
            exif_orientation = exif.get(orientation_tag)
            if exif_orientation == 3:
                img = img.rotate(180, expand=True)
            elif exif_orientation == 6:
                img = img.rotate(270, expand=True)
            elif exif_orientation == 8:
                img = img.rotate(90, expand=True)
    except (AttributeError, KeyError, IndexError):
        pass

    # Convert to RGB if needed
    if img.mode != 'RGB':
        img = img.convert('RGB')

    img_width, img_height = img.size
    target_ratio = width / height
    img_ratio = img_width / img_height

    if fit_mode == "stretch":
        # Stretch to fill (may distort)
        img = img.resize((width, height), Image.LANCZOS)

    elif fit_mode == "cover":
        # Fill display completely, crop edges if needed
        if img_ratio > target_ratio:
            # Image is wider - crop sides
            new_width = int(img_height * target_ratio)
            left = (img_width - new_width) // 2
            img = img.crop((left, 0, left + new_width, img_height))
        else:
            # Image is taller - crop top/bottom
            new_height = int(img_width / target_ratio)
            top = (img_height - new_height) // 2
            img = img.crop((0, top, img_width, top + new_height))
        img = img.resize((width, height), Image.LANCZOS)

    else:  # contain (default)
        # Fit entire image, add black bars if needed
        if img_ratio > target_ratio:
            # Image is wider - fit to width
            new_width = width
            new_height = int(width / img_ratio)
        else:
            # Image is taller - fit to height
            new_height = height
            new_width = int(height * img_ratio)

        img = img.resize((new_width, new_height), Image.LANCZOS)

        # Create black background and paste centered image
        background = Image.new('RGB', (width, height), (0, 0, 0))
        x = (width - new_width) // 2
        y = (height - new_height) // 2
        background.paste(img, (x, y))
        img = background

    # Rotate for vertical orientation
    if orientation == "vertical":
        img = img.rotate(90, expand=True)

    return img


def show_image(image_path, fit_mode="contain", orientation="horizontal"):
    """Display an image on the e-ink screen (thread-safe)"""
    display = get_display()

    if display is None:
        print(f"Would display: {image_path}")
        return False

    try:
        img = process_image(image_path, fit_mode, orientation)

        with display_lock:
            display.set_image(img)
            display.show()

        print(f"Displayed: {image_path}")
        return True
    except Exception as e:
        print(f"Error displaying image: {e}")
        return False


def show_image_object(img):
    """Display a PIL Image object on the e-ink screen (thread-safe)"""
    display = get_display()

    if display is None:
        print("Would display image object")
        return False

    try:
        with display_lock:
            display.set_image(img)
            display.show()
        return True
    except Exception as e:
        print(f"Error displaying image: {e}")
        return False


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


def generate_info_screen(photo_count=0, wifi_status="Unknown", google_status=False, ap_mode=False):
    """
    Generate an info screen with QR code and system information.

    Args:
        photo_count: Number of cached photos
        wifi_status: WiFi connection status or SSID
        google_status: Whether Google Photos is authenticated
        ap_mode: Whether in AP mode
    """
    width, height = get_display_size()

    # Create image
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Get system info
    ip = get_system_ip()
    hostname = socket.gethostname()

    # QR code: WiFi connect in AP mode, web URL in normal mode
    if ap_mode:
        # WIFI: T = security type; S = SSID; P = password
        qr_data = "WIFI:T:WPA;S:photos-setup;P:photoframe;;"
    else:
        qr_data = f"http://{hostname}.local/"

    # Generate QR code
    qr_size = min(width, height) // 2
    if QRCODE_AVAILABLE:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
        img.paste(qr_img, (20, 20))

    # Try to load fonts
    font_large = None
    font_medium = None
    font_small = None
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    font_paths_regular = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]

    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                font_large = ImageFont.truetype(font_path, 48)
                font_medium = ImageFont.truetype(font_path, 32)
                break
            except Exception:
                pass

    for font_path in font_paths_regular:
        if os.path.exists(font_path):
            try:
                font_small = ImageFont.truetype(font_path, 24)
                break
            except Exception:
                pass

    if font_large is None:
        font_large = ImageFont.load_default()
        font_medium = font_large
        font_small = font_large

    # Draw text info
    text_x = qr_size + 60
    text_y = 30

    # Title
    if ap_mode:
        draw.text((text_x, text_y), "Setup Mode", font=font_large, fill=(0, 0, 0))
        text_y += 60
        draw.text((text_x, text_y), "Connect to WiFi:", font=font_medium, fill=(0, 0, 0))
        text_y += 40
        draw.text((text_x, text_y), "photos-setup", font=font_large, fill=(0, 100, 200))
        text_y += 55
        draw.text((text_x, text_y), "Password: photoframe", font=font_small, fill=(100, 100, 100))
        text_y += 40
        draw.text((text_x, text_y), "Then visit:", font=font_medium, fill=(0, 0, 0))
        text_y += 40
        draw.text((text_x, text_y), "http://192.168.4.1/", font=font_medium, fill=(0, 100, 200))
        text_y += 45
        draw.text((text_x, text_y), "Or scan QR code", font=font_small, fill=(100, 100, 100))
    else:
        draw.text((text_x, text_y), "photos.local", font=font_large, fill=(0, 0, 0))
        text_y += 70

        # IP Address
        draw.text((text_x, text_y), f"IP: {ip}", font=font_medium, fill=(0, 0, 0))
        text_y += 45

        # URL
        draw.text((text_x, text_y), f"URL: http://{hostname}.local/", font=font_small, fill=(100, 100, 100))
        text_y += 40

        # WiFi Status
        wifi_color = (0, 128, 0) if wifi_status and wifi_status != "Unknown" else (200, 0, 0)
        draw.text((text_x, text_y), f"WiFi: {wifi_status}", font=font_small, fill=wifi_color)
        text_y += 35

        # Google Status
        google_color = (0, 128, 0) if google_status else (200, 0, 0)
        google_text = "Connected" if google_status else "Not connected"
        draw.text((text_x, text_y), f"Google Photos: {google_text}", font=font_small, fill=google_color)
        text_y += 35

        # Photo count
        draw.text((text_x, text_y), f"Cached photos: {photo_count}", font=font_small, fill=(0, 0, 0))

    # Draw border
    draw.rectangle([(0, 0), (width-1, height-1)], outline=(0, 0, 0), width=3)

    # Save info screen
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    img.save(str(INFO_IMAGE_PATH))

    return img


def show_info_screen(photo_count=0, wifi_status="Unknown", google_status=False, ap_mode=False):
    """Generate and display the info screen"""
    img = generate_info_screen(photo_count, wifi_status, google_status, ap_mode)
    return show_image_object(img)


def show_message(title, message, submessage=None):
    """Display a simple message on the e-ink screen"""
    width, height = get_display_size()

    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Try to load fonts
    font_large = None
    font_medium = None
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]

    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                font_large = ImageFont.truetype(font_path, 48)
                font_medium = ImageFont.truetype(font_path, 28)
                break
            except Exception:
                pass

    if font_large is None:
        font_large = ImageFont.load_default()
        font_medium = font_large

    # Center text
    title_bbox = draw.textbbox((0, 0), title, font=font_large)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    title_y = height // 3

    draw.text((title_x, title_y), title, font=font_large, fill=(0, 0, 0))

    if message:
        msg_bbox = draw.textbbox((0, 0), message, font=font_medium)
        msg_width = msg_bbox[2] - msg_bbox[0]
        msg_x = (width - msg_width) // 2
        msg_y = title_y + 70
        draw.text((msg_x, msg_y), message, font=font_medium, fill=(100, 100, 100))

    if submessage:
        sub_bbox = draw.textbbox((0, 0), submessage, font=font_medium)
        sub_width = sub_bbox[2] - sub_bbox[0]
        sub_x = (width - sub_width) // 2
        sub_y = title_y + 120
        draw.text((sub_x, sub_y), submessage, font=font_medium, fill=(150, 150, 150))

    # Draw border
    draw.rectangle([(0, 0), (width-1, height-1)], outline=(0, 0, 0), width=3)

    return show_image_object(img)
