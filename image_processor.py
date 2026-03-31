"""Image processing for photo uploads: resize, thumbnail, EXIF handling"""

import gc
import io
import threading
import json
import uuid
import logging
from pathlib import Path
from PIL import Image, ImageOps
from datetime import datetime

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
ORIGINALS_DIR = DATA_DIR / "originals"
DISPLAY_DIR = DATA_DIR / "display"
THUMBNAILS_DIR = DATA_DIR / "thumbnails"

THUMBNAIL_SIZE = (300, 200)
DISPLAY_STATE_FILE = DATA_DIR / ".display_state.json"

_reprocess_lock = threading.Lock()


def get_display_size():
    """Get display size from display module, fallback to 800x480"""
    try:
        import display as disp_mod
        return disp_mod.get_display_size()
    except Exception:
        return (600, 448)

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


YUNET_MODEL = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"


def _cluster_faces(faces, scale, crop_size):
    """
    Given detected faces and crop window size, return the center of the
    best face group. Uses 2D Euclidean clustering.

    Args:
        faces: numpy array of YuNet detections (each row: x, y, w, h, ...)
        scale: detection downscale factor
        crop_size: (width, height) of crop window in original image coordinates

    Returns:
        (cx, cy) in original image coordinates
    """
    import math

    # Convert faces to original coordinates: list of (cx, cy, w, h)
    orig_faces = []
    for f in faces:
        cx = (f[0] + f[2] / 2) / scale
        cy = (f[1] + f[3] / 2) / scale
        w = f[2] / scale
        h = f[3] / scale
        orig_faces.append((cx, cy, w, h))

    # Check if all faces fit in crop window
    bbox_left = min(f[0] - f[2] / 2 for f in orig_faces)
    bbox_right = max(f[0] + f[2] / 2 for f in orig_faces)
    bbox_top = min(f[1] - f[3] / 2 for f in orig_faces)
    bbox_bottom = max(f[1] + f[3] / 2 for f in orig_faces)
    bbox_w = bbox_right - bbox_left
    bbox_h = bbox_bottom - bbox_top

    crop_w, crop_h = crop_size
    if bbox_w <= crop_w and bbox_h <= crop_h:
        # All faces fit — return bounding box center
        return (int((bbox_left + bbox_right) / 2), int((bbox_top + bbox_bottom) / 2))

    # Cluster by 2D Euclidean distance
    ws = [f[2] for f in orig_faces]
    avg_face_w = sum(ws) / len(ws)
    threshold = avg_face_w * 2

    # Greedy clustering: assign each face to nearest cluster within threshold
    clusters = []  # list of lists of face indices
    for i, face in enumerate(orig_faces):
        merged = False
        for cluster in clusters:
            for j in cluster:
                other = orig_faces[j]
                dist = math.sqrt((face[0] - other[0]) ** 2 + (face[1] - other[1]) ** 2)
                if dist <= threshold:
                    cluster.append(i)
                    merged = True
                    break
            if merged:
                break
        if not merged:
            clusters.append([i])

    # Pick cluster with most faces, tie-break by total face area
    best = max(clusters, key=lambda c: (len(c), sum(orig_faces[i][2] * orig_faces[i][3] for i in c)))

    # Return center of best cluster's bounding box
    cl_left = min(orig_faces[i][0] - orig_faces[i][2] / 2 for i in best)
    cl_right = max(orig_faces[i][0] + orig_faces[i][2] / 2 for i in best)
    cl_top = min(orig_faces[i][1] - orig_faces[i][3] / 2 for i in best)
    cl_bottom = max(orig_faces[i][1] + orig_faces[i][3] / 2 for i in best)
    return (int((cl_left + cl_right) / 2), int((cl_top + cl_bottom) / 2))


def find_crop_center(img, crop_size):
    """
    Detect faces in the image and return the best center point for cropping.

    Args:
        img: PIL Image (original, EXIF-transposed)
        crop_size: (width, height) of the crop window in original image pixel
                   coordinates (pre-resize, same coordinate space as img.size)

    Returns:
        (cx, cy) in original image pixel coordinates, or None if no faces found.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    orig_w, orig_h = img.size

    # Downscale for detection (saves RAM)
    MAX_DET = 640
    scale = min(MAX_DET / orig_w, MAX_DET / orig_h, 1.0)
    dw, dh = int(orig_w * scale), int(orig_h * scale)
    det_img = img.resize((dw, dh), Image.BILINEAR)
    cv_img = np.array(det_img)
    cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
    del det_img

    if not YUNET_MODEL.exists():
        del cv_img
        return None

    try:
        detector = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (dw, dh), 0.5)
        _, faces = detector.detect(cv_img)
        del detector, cv_img
        if faces is None or len(faces) == 0:
            return None

        if len(faces) == 1:
            f = faces[0]
            cx = int((f[0] + f[2] / 2) / scale)
            cy = int((f[1] + f[3] / 2) / scale)
            return (cx, cy)

        return _cluster_faces(faces, scale, crop_size)
    except Exception:
        return None


def resize_for_display(img, fit_mode="contain", crop_mode="center"):
    """
    Resize image to display dimensions (600x448).

    fit_mode:
        "contain" - fit entire image, black bars if needed
        "cover" - fill display completely, crop edges
        "stretch" - stretch to fill (may distort)
    crop_mode:
        "center" - always crop from geometric center
        "smart" - use face detection to find best crop center
    """
    width, height = get_display_size()

    if fit_mode == "stretch":
        return img.resize((width, height), Image.LANCZOS)

    img_w, img_h = img.size
    target_ratio = width / height
    img_ratio = img_w / img_h

    if fit_mode == "cover":
        # Compute crop window size in original image coordinates
        if img_ratio > target_ratio:
            crop_w = int(img_h * target_ratio)
            crop_h = img_h
        else:
            crop_w = img_w
            crop_h = int(img_w / target_ratio)

        # Find subject center if smart mode
        center = None
        if crop_mode == "smart":
            center = find_crop_center(img, (crop_w, crop_h))

        if img_ratio > target_ratio:
            new_w = crop_w
            if center:
                left = center[0] - new_w // 2
                left = max(0, min(left, img_w - new_w))
            else:
                left = (img_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, img_h))
        else:
            new_h = crop_h
            if center:
                top = center[1] - new_h // 2
                top = max(0, min(top, img_h - new_h))
            else:
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


def process_upload(file_storage, fit_mode="contain", crop_mode="center"):
    """
    Process an uploaded file: save original, create display version, create thumbnail.

    Args:
        file_storage: werkzeug FileStorage object
        fit_mode: how to fit image to display
        crop_mode: "center" or "smart" for cover crop positioning

    Returns:
        dict with keys: filename, original_path, display_path, thumbnail_path,
                       width, height, file_size, mime_type, date_taken
        or None on error
    """
    ensure_dirs()

    original_name = file_storage.filename or "unknown.jpg"
    if not is_allowed_file(original_name):
        return None

    # Validate image in memory before touching disk
    try:
        file_data = file_storage.read()
        img = Image.open(io.BytesIO(file_data))
        img.verify()  # Raises if the file is corrupt or not a valid image
        # Re-open after verify() (verify exhausts the internal stream)
        img = Image.open(io.BytesIO(file_data))
    except Exception as e:
        print(f"Invalid image {original_name}: {e}")
        return None

    filename = sanitize_filename(original_name)
    original_path = ORIGINALS_DIR / filename

    # Save validated original
    original_path.write_bytes(file_data)
    file_size = len(file_data)
    del file_data  # Free memory

    display_path = None
    thumb_path = None
    try:
        # Capture format before exif_transpose (which returns a new Image without .format)
        img_format = img.format
        mime_type = Image.MIME.get(img_format, 'image/jpeg')

        # Apply EXIF orientation transpose
        img = ImageOps.exif_transpose(img)

        # Get remaining metadata
        date_taken = get_exif_date(img)
        orig_width, orig_height = img.size

        # Convert to RGB for processing
        if img.mode != 'RGB':
            img = img.convert('RGB')

        # Create display version (600x448 PNG)
        display_img = resize_for_display(img, fit_mode, crop_mode=crop_mode)
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
        # Clean up all files created so far
        original_path.unlink(missing_ok=True)
        if display_path:
            display_path.unlink(missing_ok=True)
        if thumb_path:
            thumb_path.unlink(missing_ok=True)
        print(f"Error processing upload {original_name}: {e}")
        return None


def delete_photo_files(photo_dict):
    """Delete all files associated with a photo record"""
    for key in ['original_path', 'display_path', 'thumbnail_path']:
        path = photo_dict.get(key)
        if path:
            Path(path).unlink(missing_ok=True)


def _save_display_state(fit_mode, crop_mode):
    """Save the current display processing state to a marker file."""
    try:
        DISPLAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DISPLAY_STATE_FILE, 'w') as f:
            json.dump({'fit_mode': fit_mode, 'crop_mode': crop_mode}, f)
    except Exception as e:
        log.warning("Failed to save display state: %s", e)


def get_display_state():
    """Read the last-processed display state. Returns dict or None."""
    try:
        with open(DISPLAY_STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def reprocess_display_images(fit_mode="contain", crop_mode="center"):
    """
    Reprocess all display images from originals (e.g. after fit_mode change).
    Returns count of reprocessed images. No-ops if already running.
    """
    if not _reprocess_lock.acquire(blocking=False):
        log.info("Reprocess already in progress, skipping")
        return 0
    try:
        log.info("Reprocessing display images: fit_mode=%s, crop_mode=%s", fit_mode, crop_mode)
        ensure_dirs()
        count = 0
        errors = 0
        for original in ORIGINALS_DIR.iterdir():
            if original.suffix.lower() not in ALLOWED_EXTENSIONS:
                continue
            try:
                img = Image.open(str(original))
                img = ImageOps.exif_transpose(img)
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                display_img = resize_for_display(img, fit_mode, crop_mode=crop_mode)
                display_filename = original.stem + ".png"
                display_path = DISPLAY_DIR / display_filename
                display_img.save(str(display_path), "PNG")
                count += 1
            except Exception as e:
                errors += 1
                log.error("Error reprocessing %s: %s", original.name, e)
            finally:
                gc.collect()

        _save_display_state(fit_mode, crop_mode)
        log.info("Reprocess complete: %d ok, %d errors", count, errors)
        return count
    finally:
        _reprocess_lock.release()
