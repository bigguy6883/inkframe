# Smart Crop Mode Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the binary smart_recenter toggle with a crop_mode dropdown that auto-detects per-photo centering (single face, all faces with clustering, or center crop fallback).

**Architecture:** The change touches 4 files across 3 layers: data model/settings migration (models.py), image processing pipeline (image_processor.py), API/startup glue (app.py), and UI (settings.html). Each task is independent after the settings migration lands.

**Tech Stack:** Python 3.13, Flask, PIL/Pillow, OpenCV (YuNet face detection), SQLite, Jinja2

**Spec:** `docs/superpowers/specs/2026-03-31-smart-crop-mode-design.md`

---

## Chunk 1: Settings Migration and Face Detection Pipeline

### Task 1: Settings migration in models.py

**Files:**
- Modify: `models.py:12-33` (DEFAULT_SETTINGS)
- Modify: `models.py:84-105` (load_settings)
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test for migration**

```python
# tests/test_models.py
import json
import pytest
from pathlib import Path


@pytest.fixture
def settings_dir(tmp_path):
    """Patch models to use temp directory for settings."""
    import models
    original_path = models.SETTINGS_PATH
    models.SETTINGS_PATH = tmp_path / "settings.json"
    yield tmp_path
    models.SETTINGS_PATH = original_path


def test_migrate_smart_recenter_true(settings_dir):
    """smart_recenter: true should migrate to crop_mode: smart"""
    import models
    models.SETTINGS_PATH.write_text(json.dumps({
        "display": {
            "orientation": "horizontal",
            "fit_mode": "cover",
            "saturation": 0.5,
            "smart_recenter": True
        },
        "slideshow": {"order": "random", "interval_minutes": 60, "enabled": True, "auto_start": True, "current_index": 0},
        "upload": {"max_file_size_mb": 20},
        "wifi": {"ssid": "", "configured": False}
    }))
    settings = models.load_settings()
    assert settings['display']['crop_mode'] == 'smart'
    assert 'smart_recenter' not in settings['display']
    # Verify it was persisted
    saved = json.loads(models.SETTINGS_PATH.read_text())
    assert saved['display']['crop_mode'] == 'smart'
    assert 'smart_recenter' not in saved['display']


def test_migrate_smart_recenter_false(settings_dir):
    """smart_recenter: false should migrate to crop_mode: center"""
    import models
    models.SETTINGS_PATH.write_text(json.dumps({
        "display": {
            "orientation": "horizontal",
            "fit_mode": "contain",
            "saturation": 0.5,
            "smart_recenter": False
        },
        "slideshow": {"order": "random", "interval_minutes": 60, "enabled": True, "auto_start": True, "current_index": 0},
        "upload": {"max_file_size_mb": 20},
        "wifi": {"ssid": "", "configured": False}
    }))
    settings = models.load_settings()
    assert settings['display']['crop_mode'] == 'center'
    assert 'smart_recenter' not in settings['display']


def test_fresh_install_defaults(settings_dir):
    """Fresh install should get crop_mode: center, no smart_recenter"""
    import models
    settings = models.load_settings()
    assert settings['display']['crop_mode'] == 'center'
    assert 'smart_recenter' not in settings['display']


def test_already_migrated_is_idempotent(settings_dir):
    """Settings with crop_mode already set should not change"""
    import models
    models.SETTINGS_PATH.write_text(json.dumps({
        "display": {
            "orientation": "horizontal",
            "fit_mode": "cover",
            "saturation": 0.5,
            "crop_mode": "smart"
        },
        "slideshow": {"order": "random", "interval_minutes": 60, "enabled": True, "auto_start": True, "current_index": 0},
        "upload": {"max_file_size_mb": 20},
        "wifi": {"ssid": "", "configured": False}
    }))
    settings = models.load_settings()
    assert settings['display']['crop_mode'] == 'smart'
    assert 'smart_recenter' not in settings['display']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pi/photos && source venv/bin/activate && python -m pytest tests/test_models.py -v`
Expected: FAIL — `crop_mode` not in settings, `smart_recenter` still present

- [ ] **Step 3: Implement migration**

In `models.py`, change `DEFAULT_SETTINGS` and add migration to `load_settings()`:

```python
# models.py line 12-33: Replace smart_recenter with crop_mode in DEFAULT_SETTINGS
DEFAULT_SETTINGS = {
    "wifi": {
        "ssid": "",
        "configured": False
    },
    "display": {
        "orientation": "horizontal",
        "fit_mode": "contain",
        "saturation": 0.5,
        "crop_mode": "center"
    },
    "slideshow": {
        "order": "random",
        "interval_minutes": 60,
        "enabled": True,
        "auto_start": True,
        "current_index": 0
    },
    "upload": {
        "max_file_size_mb": 20
    }
}
```

In `load_settings()`, before the `return merged` at line 103, add migration. Important: use the raw `settings` dict (pre-merge) to read the old value, since `merged` already has `crop_mode` from DEFAULT_SETTINGS:

```python
    # Migrate smart_recenter -> crop_mode (one-time)
    raw_display = settings.get('display', {})
    if 'smart_recenter' in raw_display:
        if 'crop_mode' not in raw_display:
            merged['display']['crop_mode'] = 'smart' if raw_display['smart_recenter'] else 'center'
        if 'smart_recenter' in merged['display']:
            del merged['display']['smart_recenter']
        save_settings(merged)

    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pi/photos && source venv/bin/activate && python -m pytest tests/test_models.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: migrate smart_recenter to crop_mode setting"
```

---

### Task 2: Replace find_smart_center with find_crop_center

**Files:**
- Modify: `image_processor.py:74-132` (replace find_smart_center)
- Create: `tests/test_crop_center.py`

- [ ] **Step 1: Write failing tests for find_crop_center**

```python
# tests/test_crop_center.py
import pytest
from unittest.mock import patch, MagicMock
from PIL import Image
import numpy as np


def _make_image(w, h):
    """Create a solid-color test image."""
    return Image.new('RGB', (w, h), (128, 128, 128))


def _mock_faces(face_list):
    """Create a mock faces array from list of (x, y, w, h) tuples.
    Each face is a numpy array matching YuNet output format.
    """
    if not face_list:
        return None
    # YuNet returns rows of [x, y, w, h, ...] — we only use first 4 cols
    return np.array([[x, y, w, h, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0] for x, y, w, h in face_list], dtype=np.float32)


class TestFindCropCenter:
    """Tests for find_crop_center function."""

    @patch('image_processor.YUNET_MODEL')
    def test_no_faces_returns_none(self, mock_model):
        """No faces detected -> None (caller uses center crop)."""
        mock_model.exists.return_value = True
        img = _make_image(1000, 800)
        with patch('cv2.FaceDetectorYN') as mock_yn:
            detector = MagicMock()
            detector.detect.return_value = (None, None)
            mock_yn.create.return_value = detector
            from image_processor import find_crop_center
            result = find_crop_center(img, (600, 800))
        assert result is None

    @patch('image_processor.YUNET_MODEL')
    def test_single_face_returns_face_center(self, mock_model):
        """Single face -> return center of that face."""
        mock_model.exists.return_value = True
        img = _make_image(1000, 800)
        # Face at (200, 300) size 100x100 in detection coords
        # scale = 640/1000 = 0.64, so orig center = (250/0.64, 350/0.64) = (390, 546)
        # Actually let's use scale=1.0 for simplicity: 640x512 detection image
        # Face at x=200, y=300, w=100, h=100 -> center (250, 350) in det coords
        # scale = min(640/1000, 640/800, 1.0) = 0.64
        # orig center = (250/0.64, 350/0.64) = (390, 546)
        faces = _mock_faces([(200, 300, 100, 100)])
        with patch('cv2.FaceDetectorYN') as mock_yn:
            detector = MagicMock()
            detector.detect.return_value = (None, faces)
            mock_yn.create.return_value = detector
            from image_processor import find_crop_center
            result = find_crop_center(img, (600, 800))
        assert result is not None
        cx, cy = result
        assert isinstance(cx, int)
        assert isinstance(cy, int)

    @patch('image_processor.YUNET_MODEL')
    def test_multiple_faces_all_fit(self, mock_model):
        """Multiple faces that fit in crop window -> bounding box center."""
        mock_model.exists.return_value = True
        img = _make_image(1000, 800)
        # Two faces close together (will fit in a 600px wide crop)
        # scale = 0.64
        faces = _mock_faces([
            (100, 200, 80, 80),  # face 1
            (250, 200, 80, 80),  # face 2, nearby
        ])
        with patch('cv2.FaceDetectorYN') as mock_yn:
            detector = MagicMock()
            detector.detect.return_value = (None, faces)
            mock_yn.create.return_value = detector
            from image_processor import find_crop_center
            result = find_crop_center(img, (600, 800))
        assert result is not None

    @patch('image_processor.YUNET_MODEL')
    def test_multiple_faces_too_spread_returns_largest_cluster(self, mock_model):
        """Faces too spread to all fit -> center of largest cluster."""
        mock_model.exists.return_value = True
        img = _make_image(2000, 800)
        # scale = min(640/2000, 640/800, 1.0) = 0.32
        # Group of 3 faces on left, 1 face far right
        faces = _mock_faces([
            (10, 100, 50, 50),   # cluster left
            (80, 100, 50, 50),   # cluster left
            (150, 100, 50, 50),  # cluster left
            (580, 100, 50, 50),  # far right, alone
        ])
        with patch('cv2.FaceDetectorYN') as mock_yn:
            detector = MagicMock()
            detector.detect.return_value = (None, faces)
            mock_yn.create.return_value = detector
            from image_processor import find_crop_center
            # crop_size smaller than full image so faces won't all fit
            result = find_crop_center(img, (400, 800))
        assert result is not None
        # Should center on the left cluster (3 faces), not the right one (1 face)
        cx, cy = result
        # Left cluster in orig coords: faces at x 10-200 in det, /0.32 = 31-625 orig
        # Right face at x 580 in det, /0.32 = 1812 orig
        # cx should be much closer to left side
        assert cx < 1000  # should be in left half

    @patch('image_processor.YUNET_MODEL')
    def test_no_yunet_model_returns_none(self, mock_model):
        """No YuNet model file -> None."""
        mock_model.exists.return_value = False
        img = _make_image(1000, 800)
        from image_processor import find_crop_center
        result = find_crop_center(img, (600, 800))
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pi/photos && source venv/bin/activate && python -m pytest tests/test_crop_center.py -v`
Expected: FAIL — `find_crop_center` not defined

- [ ] **Step 3: Implement find_crop_center**

Replace `find_smart_center()` (lines 74-132) in `image_processor.py` with:

```python
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
    xs = [f[0] for f in orig_faces]
    ys = [f[1] for f in orig_faces]
    ws = [f[2] for f in orig_faces]
    hs = [f[3] for f in orig_faces]
    # Bounding box of all face centers + half-widths
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/pi/photos && source venv/bin/activate && python -m pytest tests/test_crop_center.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add image_processor.py tests/test_crop_center.py
git commit -m "feat: replace find_smart_center with find_crop_center

Adds multi-face support with clustering. Removes saliency fallback.
Single face centers on that face, multiple faces centers on all or
largest cluster, no faces returns None for center crop."
```

---

### Task 3: Update resize_for_display and downstream functions

**Files:**
- Modify: `image_processor.py:135-191` (resize_for_display)
- Modify: `image_processor.py:193-283` (process_upload)
- Modify: `image_processor.py:294-350` (display state + reprocess)
- Create: `tests/test_resize.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_resize.py
import json
import pytest
from unittest.mock import patch
from PIL import Image


def _make_image(w, h):
    return Image.new('RGB', (w, h), (128, 128, 128))


class TestResizeForDisplay:
    """Tests for resize_for_display with crop_mode parameter."""

    @patch('image_processor.get_display_size', return_value=(600, 448))
    def test_cover_center_mode_uses_geometric_center(self, mock_size):
        from image_processor import resize_for_display
        img = _make_image(1200, 448)  # wider than display
        result = resize_for_display(img, fit_mode="cover", crop_mode="center")
        assert result.size == (600, 448)

    @patch('image_processor.get_display_size', return_value=(600, 448))
    @patch('image_processor.find_crop_center', return_value=(300, 224))
    def test_cover_smart_mode_calls_find_crop_center(self, mock_find, mock_size):
        from image_processor import resize_for_display
        # Wide image: crop_size should be (new_w, img_h) = (int(448 * 600/448), 448) = (600, 448)
        img = _make_image(1200, 448)
        result = resize_for_display(img, fit_mode="cover", crop_mode="smart")
        assert result.size == (600, 448)
        mock_find.assert_called_once()
        # Verify crop_size argument: for 1200x448 image with 600:448 target
        # img_ratio=2.678 > target_ratio=1.339 -> crop_w = int(448 * 1.339) = 600
        args, kwargs = mock_find.call_args
        assert args[1] == (600, 448)  # crop_size

    @patch('image_processor.get_display_size', return_value=(600, 448))
    @patch('image_processor.find_crop_center', return_value=(300, 400))
    def test_cover_smart_mode_tall_image_crop_size(self, mock_find, mock_size):
        """Tall image: crop_size should be (img_w, new_h)."""
        from image_processor import resize_for_display
        img = _make_image(600, 1200)
        result = resize_for_display(img, fit_mode="cover", crop_mode="smart")
        assert result.size == (600, 448)
        args, kwargs = mock_find.call_args
        # img_ratio=0.5 < target_ratio=1.339 -> crop_h = int(600 / 1.339) = 448
        assert args[1] == (600, 448)  # crop_size

    @patch('image_processor.get_display_size', return_value=(600, 448))
    def test_cover_smart_mode_no_faces_falls_back_to_center(self, mock_size):
        from image_processor import resize_for_display
        with patch('image_processor.find_crop_center', return_value=None):
            img = _make_image(1200, 448)
            result = resize_for_display(img, fit_mode="cover", crop_mode="smart")
            assert result.size == (600, 448)

    @patch('image_processor.get_display_size', return_value=(600, 448))
    @patch('image_processor.find_crop_center')
    def test_contain_mode_does_not_call_find_crop_center(self, mock_find, mock_size):
        from image_processor import resize_for_display
        img = _make_image(1200, 448)
        result = resize_for_display(img, fit_mode="contain", crop_mode="smart")
        assert result.size == (600, 448)
        mock_find.assert_not_called()


class TestSaveDisplayState:
    """Tests for _save_display_state using crop_mode."""

    def test_saves_crop_mode(self, tmp_path):
        import image_processor
        original = image_processor.DISPLAY_STATE_FILE
        image_processor.DISPLAY_STATE_FILE = tmp_path / ".display_state.json"
        try:
            image_processor._save_display_state("cover", "smart")
            data = json.loads(image_processor.DISPLAY_STATE_FILE.read_text())
            assert data == {'fit_mode': 'cover', 'crop_mode': 'smart'}
            assert 'smart_recenter' not in data
        finally:
            image_processor.DISPLAY_STATE_FILE = original
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/pi/photos && source venv/bin/activate && python -m pytest tests/test_resize.py -v`
Expected: FAIL — `crop_mode` parameter not accepted

- [ ] **Step 3: Implement changes**

Update `resize_for_display()` signature and body in `image_processor.py`:

```python
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
```

Update `process_upload()` — change parameter name and pass-through:

```python
def process_upload(file_storage, fit_mode="contain", crop_mode="center"):
```
And line 251: `resize_for_display(img, fit_mode, crop_mode=crop_mode)`

Update `_save_display_state()`:

```python
def _save_display_state(fit_mode, crop_mode):
    """Save the current display processing state to a marker file."""
    try:
        DISPLAY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(DISPLAY_STATE_FILE, 'w') as f:
            json.dump({'fit_mode': fit_mode, 'crop_mode': crop_mode}, f)
    except Exception as e:
        log.warning("Failed to save display state: %s", e)
```

Update `reprocess_display_images()`:

```python
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
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/pi/photos && source venv/bin/activate && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add image_processor.py tests/test_resize.py
git commit -m "feat: update resize pipeline to use crop_mode parameter

Replace smart_recenter with crop_mode in resize_for_display,
process_upload, reprocess_display_images, and _save_display_state."
```

---

## Chunk 2: App Layer and Settings UI

### Task 4: Update app.py settings API, upload, and startup

**Files:**
- Modify: `app.py:228` (upload_photo)
- Modify: `app.py:240` (upload_photo call)
- Modify: `app.py:377-428` (update_settings)
- Modify: `app.py:496-510` (main startup)

- [ ] **Step 1: Update settings API whitelist and validation**

In `app.py` line 388, replace the whitelist and remove the `bool()` branch:

```python
        for key in ['orientation', 'fit_mode', 'saturation', 'crop_mode']:
            if key in data['display']:
                val = data['display'][key]
                if key == 'saturation':
                    val = max(0.0, min(1.0, float(val)))
                elif key == 'crop_mode':
                    if val not in ('center', 'smart'):
                        continue
                updates['display'][key] = val
```

- [ ] **Step 2: Update reprocessing trigger**

In `app.py` line 417, change the condition and kwargs:

```python
        # Reprocess display images if fit_mode or crop_mode changed
        if 'display' in updates and ('fit_mode' in updates['display'] or 'crop_mode' in updates['display']):
            display_settings = settings.get('display', {})
            threading.Thread(
                target=image_processor.reprocess_display_images,
                kwargs={
                    'fit_mode': display_settings.get('fit_mode', 'contain'),
                    'crop_mode': display_settings.get('crop_mode', 'center'),
                },
                daemon=True
            ).start()
```

- [ ] **Step 3: Update upload handler**

In `app.py` line 228, change:
```python
    crop_mode = settings.get('display', {}).get('crop_mode', 'center')
```
And line 240:
```python
    result = image_processor.process_upload(file, fit_mode, crop_mode=crop_mode)
```

- [ ] **Step 4: Update main() startup comparison**

In `app.py` lines 499-510, change:

```python
            current_crop = display_settings.get('crop_mode', 'center')
            last_state = image_processor.get_display_state()
            if (last_state is None
                    or last_state.get('fit_mode') != current_fit
                    or last_state.get('crop_mode') != current_crop):
                print(f"Display images stale, reprocessing with fit_mode={current_fit}")
                threading.Thread(
                    target=image_processor.reprocess_display_images,
                    kwargs={'fit_mode': current_fit, 'crop_mode': current_crop},
                    daemon=True
                ).start()
```

- [ ] **Step 5: Run all tests**

Run: `cd /home/pi/photos && source venv/bin/activate && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: update app.py to use crop_mode throughout

Replace smart_recenter with crop_mode in settings API whitelist,
upload handler, reprocessing trigger, and startup state comparison."
```

---

### Task 5: Update settings UI

**Files:**
- Modify: `templates/settings.html:46-57`

- [ ] **Step 1: Replace the Smart Recenter toggle with Crop Mode dropdown**

Replace the smart recenter setting-row block (lines 46-57) with:

```html
    <div class="setting-row">
        <div class="setting-label">
            Crop Mode
            <small>How cover crop positions the frame</small>
        </div>
        <select id="cropMode" onchange="saveSetting('display', 'crop_mode', this.value)">
            <option value="center" {% if settings.display.crop_mode == 'center' %}selected{% endif %}>Center</option>
            <option value="smart" {% if settings.display.crop_mode == 'smart' %}selected{% endif %}>Smart (face detect)</option>
        </select>
    </div>
```

- [ ] **Step 2: Verify manually**

Run dev server (on homelab): `cd /home/pi/photos && source venv/bin/activate && python3 -c "from app import app; app.run(host='0.0.0.0', port=8080)"`
Open `http://192.168.0.221:8080/settings` and confirm:
- Dropdown shows "Center" and "Smart (face detect)"
- Changing the dropdown saves without error (check terminal for 200 response)

- [ ] **Step 3: Commit**

```bash
git add templates/settings.html
git commit -m "feat: replace smart recenter toggle with crop mode dropdown"
```

---

### Task 6: Deploy and verify on target Pi

- [ ] **Step 1: Push to remote**

```bash
cd /home/pi/photos && git push origin main
```

- [ ] **Step 2: Pull on photos.local and restart**

```bash
ssh pi@photos.local "cd ~/photos && git pull origin main && sudo systemctl restart inkframe"
```

- [ ] **Step 3: Verify service is running**

```bash
ssh pi@photos.local "sudo systemctl status inkframe --no-pager"
```
Expected: `active (running)`

- [ ] **Step 4: Verify settings migration**

```bash
ssh pi@photos.local "cat ~/photos/config/settings.json | python3 -m json.tool | grep -A2 crop_mode"
```
Expected: `"crop_mode": "center"` (or `"smart"` if it was previously enabled), no `smart_recenter`

- [ ] **Step 5: Verify settings UI**

Open `http://photos.local/settings` and confirm the Crop Mode dropdown appears and works.
