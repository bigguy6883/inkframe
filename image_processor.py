"""Image processing for photo uploads: resize, thumbnail, EXIF handling"""

import uuid
from pathlib import Path
from PIL import Image, ImageOps
from datetime import datetime

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
ORIGINALS_DIR = DATA_DIR / "originals"
DISPLAY_DIR = DATA_DIR / "display"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"

DISPLAY_SIZE = (800, 480)
THUMBNAIL_SIZE = (300, 200)

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/webp', 'image/tiff'}


def ensure_dirs():
    """Create data directories if they don't exist"""
    for d in [ORIGINALS_DIR, DISPLAY_DIR, THUMBNAILS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def is_allowed_file(filename):
    """Check if file extension is allowed"""
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


def sanitize_filename(original_name):
    """Generate a safe unique filename preserving original extension"""
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = '.jpg'
    return f"{uuid.uuid4().hex[:12]}{ext}"


def get_exif_date(img):
    """Extract date taken from EXIF data"""
    try:
        exif = img.getexif()
        # DateTimeOriginal (36867) or DateTime (306)
        for tag in [36867, 306]:
            if tag in exif:
                return exif[tag]
    except Exception:
        pass
    return None


def resize_for_display(img, fit_mode="contain"):
    """
    Resize image to display dimensions (800x480).

    fit_mode:
        "contain" - fit entire image, black bars if needed
        "cover" - fill display completely, crop edges
        "stretch" - stretch to fill (may distort)
    """
    width, height = DISPLAY_SIZE

    if fit_mode == "stretch":
        return img.resize((width, height), Image.LANCZOS)

    img_w, img_h = img.size
    target_ratio = width / height
    img_ratio = img_w / img_h

    if fit_mode == "cover":
        if img_ratio > target_ratio:
            new_w = int(img_h * target_ratio)
            left = (img_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, img_h))
        else:
            new_h = int(img_w / target_ratio)
            top = (img_h - new_h) // 2
            img = img.crop((0, top, img_w, top + new_h))
        return img.resize((width, height), Image.LANCZOS)

    # contain (default)
    if img_ratio > target_ratio:
        new_w = width
        new_h = int(width / img_ratio)
    else:
        new_h = height
        new_w = int(height * img_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    background = Image.new('RGB', (width, height), (0, 0, 0))
    x = (width - new_w) // 2
    y = (height - new_h) // 2
    background.paste(img, (x, y))
    return background


def process_upload(file_storage, fit_mode="contain"):
    """
    Process an uploaded file: save original, create display version, create thumbnail.

    Args:
        file_storage: werkzeug FileStorage object
        fit_mode: how to fit image to display

    Returns:
        dict with keys: filename, original_path, display_path, thumbnail_path,
                       width, height, file_size, mime_type, date_taken
        or None on error
    """
    ensure_dirs()

    original_name = file_storage.filename or "unknown.jpg"
    if not is_allowed_file(original_name):
        return None

    filename = sanitize_filename(original_name)
    original_path = ORIGINALS_DIR / filename

    # Save original
    file_storage.save(str(original_path))
    file_size = original_path.stat().st_size

    try:
        img = Image.open(str(original_path))

        # Apply EXIF orientation transpose
        img = ImageOps.exif_transpose(img)

        # Get metadata before conversion
        date_taken = get_exif_date(img)
        orig_width, orig_height = img.size
        mime_type = Image.MIME.get(img.format, 'image/jpeg')

        # Convert to RGB for processing
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Create display version (800x480 PNG)
        display_img = resize_for_display(img, fit_mode)
        display_filename = Path(filename).stem + ".png"
        display_path = DISPLAY_DIR / display_filename
        display_img.save(str(display_path), "PNG")

        # Create thumbnail (300x200 JPEG)
        thumb = img.copy()
        thumb.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
        thumb_filename = Path(filename).stem + ".jpg"
        thumb_path = THUMBNAILS_DIR / thumb_filename
        thumb.save(str(thumb_path), "JPEG", quality=85)

        return {
            'filename': filename,
            'original_path': str(original_path),
            'display_path': str(display_path),
            'thumbnail_path': str(thumb_path),
            'width': orig_width,
            'height': orig_height,
            'file_size': file_size,
            'mime_type': mime_type,
            'date_taken': date_taken,
        }

    except Exception as e:
        # Clean up on error
        original_path.unlink(missing_ok=True)
        print(f"Error processing upload {original_name}: {e}")
        return None


def delete_photo_files(photo_dict):
    """Delete all files associated with a photo record"""
    for key in ['original_path', 'display_path', 'thumbnail_path']:
        path = photo_dict.get(key)
        if path:
            Path(path).unlink(missing_ok=True)


def reprocess_display_images(fit_mode="contain"):
    """
    Reprocess all display images from originals (e.g. after fit_mode change).
    Returns count of reprocessed images.
    """
    ensure_dirs()
    count = 0
    for original in ORIGINALS_DIR.iterdir():
        if original.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        try:
            img = Image.open(str(original))
            img = ImageOps.exif_transpose(img)
            if img.mode != 'RGB':
                img = img.convert('RGB')

            display_img = resize_for_display(img, fit_mode)
            display_filename = original.stem + ".png"
            display_path = DISPLAY_DIR / display_filename
            display_img.save(str(display_path), "PNG")
            count += 1
        except Exception as e:
            print(f"Error reprocessing {original.name}: {e}")
    return count
