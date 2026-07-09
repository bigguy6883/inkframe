"""Tests for vertical orientation support in resize_for_display.

Vertical orientation = frame physically mounted portrait. Images are composed
for a portrait canvas (448x600) and then rotated 90° so the physical 600x448
panel shows them upright.
"""

import json
from unittest.mock import patch
from PIL import Image


def _make_image(w, h, color=(128, 128, 128)):
    return Image.new('RGB', (w, h), color)


class TestResizeOrientation:

    @patch('image_processor.get_display_size', return_value=(600, 448))
    def test_vertical_output_is_physical_landscape_size(self, mock_size):
        from image_processor import resize_for_display
        img = _make_image(800, 400)
        result = resize_for_display(img, fit_mode="contain", orientation="vertical")
        assert result.size == (600, 448)

    @patch('image_processor.get_display_size', return_value=(600, 448))
    def test_vertical_stretch_equals_portrait_resize_rotated(self, mock_size):
        from image_processor import resize_for_display
        # Non-uniform image so a wrong rotation/compose produces different bytes
        img = _make_image(800, 400)
        for x in range(400):
            img.putpixel((x, 100), (255, 0, 0))
        result = resize_for_display(img, fit_mode="stretch", orientation="vertical")
        expected = img.resize((448, 600), Image.LANCZOS).rotate(90, expand=True)
        assert result.size == (600, 448)
        assert result.tobytes() == expected.tobytes()

    @patch('image_processor.get_display_size', return_value=(600, 448))
    def test_vertical_contain_bars_land_left_right(self, mock_size):
        """Wide 2:1 image on a portrait canvas gets top/bottom bars, which
        become left/right bars after rotation to the physical panel."""
        from image_processor import resize_for_display
        img = _make_image(800, 400)
        result = resize_for_display(img, fit_mode="contain", orientation="vertical")
        assert result.size == (600, 448)
        assert result.getpixel((5, 224)) == (0, 0, 0)        # bar
        assert result.getpixel((300, 5)) == (128, 128, 128)  # content

    @patch('image_processor.get_display_size', return_value=(600, 448))
    def test_horizontal_contain_bars_land_top_bottom(self, mock_size):
        """Same wide image, default horizontal: bars top/bottom (regression guard)."""
        from image_processor import resize_for_display
        img = _make_image(800, 400)
        result = resize_for_display(img, fit_mode="contain", orientation="horizontal")
        assert result.size == (600, 448)
        assert result.getpixel((300, 5)) == (0, 0, 0)          # bar
        assert result.getpixel((300, 224)) == (128, 128, 128)  # content

    @patch('image_processor.get_display_size', return_value=(600, 448))
    @patch('image_processor.find_crop_center', return_value=(400, 200))
    def test_vertical_cover_smart_uses_portrait_crop_window(self, mock_find, mock_size):
        from image_processor import resize_for_display
        img = _make_image(800, 400)
        result = resize_for_display(img, fit_mode="cover", crop_mode="smart",
                                    orientation="vertical")
        assert result.size == (600, 448)
        args, kwargs = mock_find.call_args
        # Portrait target ratio 448/600: crop window is int(400 * 448/600) wide
        assert args[1] == (298, 400)


class TestDisplayStateOrientation:

    def test_state_includes_orientation(self, tmp_path):
        import image_processor
        original = image_processor.DISPLAY_STATE_FILE
        image_processor.DISPLAY_STATE_FILE = tmp_path / ".display_state.json"
        try:
            image_processor._save_display_state("cover", "smart", "vertical")
            data = json.loads(image_processor.DISPLAY_STATE_FILE.read_text())
            assert data == {'fit_mode': 'cover', 'crop_mode': 'smart',
                            'orientation': 'vertical'}
        finally:
            image_processor.DISPLAY_STATE_FILE = original


class TestReprocessNeeded:
    """reprocess_needed(last, fit_mode, crop_mode, orientation) decides whether
    display images must be regenerated. crop_mode only matters in cover mode."""

    def _call(self, last, fit="contain", crop="center", orient="horizontal"):
        from image_processor import reprocess_needed
        return reprocess_needed(last, fit, crop, orient)

    def test_no_state_needs_reprocess(self):
        assert self._call(None) is True

    def test_fit_mode_change_needs_reprocess(self):
        last = {'fit_mode': 'cover', 'crop_mode': 'center', 'orientation': 'horizontal'}
        assert self._call(last, fit="contain") is True

    def test_orientation_change_needs_reprocess(self):
        last = {'fit_mode': 'contain', 'crop_mode': 'center', 'orientation': 'horizontal'}
        assert self._call(last, orient="vertical") is True

    def test_crop_change_in_cover_needs_reprocess(self):
        last = {'fit_mode': 'cover', 'crop_mode': 'center', 'orientation': 'horizontal'}
        assert self._call(last, fit="cover", crop="smart") is True

    def test_crop_change_in_contain_skips_reprocess(self):
        last = {'fit_mode': 'contain', 'crop_mode': 'center', 'orientation': 'horizontal'}
        assert self._call(last, fit="contain", crop="smart") is False

    def test_unchanged_skips_reprocess(self):
        last = {'fit_mode': 'cover', 'crop_mode': 'smart', 'orientation': 'vertical'}
        assert self._call(last, fit="cover", crop="smart", orient="vertical") is False

    def test_old_state_without_orientation_defaults_horizontal(self):
        # State files written before this feature lack the orientation key
        last = {'fit_mode': 'contain', 'crop_mode': 'center'}
        assert self._call(last) is False
