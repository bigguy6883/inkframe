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
        img = _make_image(1200, 448)
        result = resize_for_display(img, fit_mode="cover", crop_mode="smart")
        assert result.size == (600, 448)
        mock_find.assert_called_once()
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
