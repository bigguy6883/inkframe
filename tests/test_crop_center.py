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
        assert cx < 1000  # should be in left half

    @patch('image_processor.YUNET_MODEL')
    def test_no_yunet_model_returns_none(self, mock_model):
        """No YuNet model file -> None."""
        mock_model.exists.return_value = False
        img = _make_image(1000, 800)
        from image_processor import find_crop_center
        result = find_crop_center(img, (600, 800))
        assert result is None
