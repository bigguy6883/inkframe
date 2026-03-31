# Smart Crop Mode Design

## Problem

The current smart recenter feature has two shortcomings:
1. **Group photos**: It centers on the largest face only, cropping out other people
2. **Landscapes**: The saliency fallback (Sobel edge detection) picks arbitrary edge details, often worse than a simple center crop

## Solution

Replace the binary `smart_recenter` toggle with a `crop_mode` dropdown offering two modes: **Center** (geometric center crop) and **Smart** (auto-detecting face-aware crop with center crop fallback).

## Settings & Data Model

Replace `display.smart_recenter` (boolean) with `display.crop_mode` (string).

| `crop_mode` | Behavior |
|---|---|
| `"center"` | Always geometric center crop, no face detection |
| `"smart"` | Auto-detect per photo: 1 face -> center on it, multiple faces -> fit all/cluster, no faces -> center crop |

Default: `"center"` (preserves current behavior where smart recenter is off by default).

### Migration

On startup, if `smart_recenter` exists in settings:
- `true` -> `crop_mode: "smart"`
- `false` -> `crop_mode: "center"`
- Delete `smart_recenter` key, save settings

One-time, idempotent. Important: removing `smart_recenter` from `DEFAULT_SETTINGS` and adding the migration must land in the same change, otherwise the settings merge logic will re-inject the old key.

## Face Detection Pipeline

Replace `find_smart_center()` with `find_crop_center(img, crop_size)`.

Parameters:
- `img`: PIL Image (original, EXIF-transposed)
- `crop_size`: `(width, height)` tuple of the crop window in original image pixel coordinates (pre-resize, same coordinate space as `img.size`)

Returns: `(cx, cy)` in original image pixel coordinates, or `None`.

### Logic

1. Run YuNet face detection (unchanged from current implementation)
2. **No faces** -> return `None` (caller uses geometric center)
3. **1 face** -> return center of that face
4. **Multiple faces** -> compute bounding box of all faces:
   - If bounding box fits within `crop_size` -> return bounding box center
   - If too spread out -> cluster and return center of largest cluster

### Clustering Algorithm

When all faces don't fit in the crop window:

1. Compute average face width across all detected faces
2. Use 2D Euclidean distance between face centers (handles both horizontal group shots and vertical arrangements)
3. Greedily merge faces within 2x average face width distance into clusters
4. Select the cluster with the most faces (tie-break: largest total face area)
5. Return center of that cluster's bounding box

No external dependencies -- arithmetic on YuNet face rectangles.

### Saliency Fallback Removed

The Sobel edge-based saliency code is deleted entirely. No faces = center crop.

## Crop Application

`resize_for_display()` changes:
- Accept `crop_mode` parameter instead of `smart_recenter`
- Compute crop window size before calling detection: `(new_w, img_h)` when image is wider than target ratio, `(img_w, new_h)` when taller (same calculation already exists for the crop)
- When `crop_mode == "smart"`: call `find_crop_center(img, crop_size)`, use result or fall back to geometric center
- When `crop_mode == "center"`: skip detection, use geometric center
- Crop clamping logic (already exists) unchanged

`process_upload()` and `reprocess_display_images()` signatures also change: `smart_recenter` parameter becomes `crop_mode`.

## Settings UI

In `settings.html`, replace the Smart Recenter toggle (checkbox) with a Crop Mode dropdown:

```html
<select id="cropMode" onchange="saveSetting('display', 'crop_mode', this.value)">
    <option value="center">Center</option>
    <option value="smart">Smart (face detect)</option>
</select>
```

Label: "Crop Mode" with subtitle "How cover crop positions the frame".

Only relevant when fit mode is "cover" (same visibility as current toggle).

## Reprocessing

Same existing mechanism:
- `app.py` compares current `crop_mode` against `.display_state.json`
- If changed, background thread reprocesses all display images
- Dropdown change triggers reprocessing via `/api/settings` endpoint

Specific changes in `app.py`:
- Settings API whitelist: replace `'smart_recenter'` with `'crop_mode'` in allowed display keys, validate value is one of `["center", "smart"]`. Remove the `bool()` coercion branch for `smart_recenter` entirely.
- Reprocessing trigger condition: change `'smart_recenter' in updates['display']` to `'crop_mode' in updates['display']`
- `main()` startup state comparison: use `crop_mode` key instead of `smart_recenter` when comparing current settings against `.display_state.json`

Specific changes in `image_processor.py`:
- `_save_display_state()`: save `crop_mode` key instead of `smart_recenter`

## Files Modified

| File | Changes |
|---|---|
| `image_processor.py` | Replace `find_smart_center()` with `find_crop_center()`, remove saliency code, update `resize_for_display()` / `process_upload()` / `reprocess_display_images()` / `_save_display_state()` signatures and internals |
| `models.py` | Change `DEFAULT_SETTINGS` (`smart_recenter` -> `crop_mode: "center"`), add migration in `load_settings()` |
| `app.py` | Update settings API whitelist and validation, reprocessing trigger condition, display state keys, pass `crop_mode` throughout |
| `templates/settings.html` | Replace toggle with dropdown |

## Not Changed

- Upload flow (already passes settings through)
- Thumbnail generation (own fixed crop)
- Display/scheduler code
- YuNet model or detection parameters
