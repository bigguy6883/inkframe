"""Info screen must keep its content clear of the picture-frame matte.

Bug: the QR code was pasted at a hardcoded (20, 20) and the text column
started at y=20, so a matte overlapping the panel edge hid the QR (and the
heading) entirely. Content now draws inside a MATTE_INSET safe area, with the
QR vertically centred so it is never near the top edge.
"""

import pytest
from PIL import Image, ImageChops


def _content_bbox(img, box=None):
    """Bounding box of every non-white pixel, optionally within a crop box."""
    region = img.crop(box) if box else img
    white = Image.new('RGB', region.size, (255, 255, 255))
    diff = ImageChops.difference(region, white).convert('L')
    bbox = diff.getbbox()
    if bbox is None:
        return None
    if box:
        return (bbox[0] + box[0], bbox[1] + box[1], bbox[2] + box[0], bbox[3] + box[1])
    return bbox


@pytest.mark.parametrize("ap_mode", [False, True])
def test_no_content_inside_matte_inset(ap_mode):
    import display

    img = display.generate_info_screen(photo_count=42, wifi_status="HomeNet",
                                       ap_mode=ap_mode)
    width, height = img.size
    inset = display.MATTE_INSET

    bbox = _content_bbox(img)
    assert bbox is not None, "info screen rendered blank"
    left, top, right, bottom = bbox

    assert left >= inset, f"content reaches x={left}, inside {inset}px left margin"
    assert top >= inset, f"content reaches y={top}, inside {inset}px top margin"
    assert right <= width - inset, f"content reaches x={right}, inside right margin"
    assert bottom <= height - inset, f"content reaches y={bottom}, inside bottom margin"


@pytest.mark.parametrize("ap_mode", [False, True])
def test_qr_is_vertically_centred(ap_mode):
    import display

    if not display.QRCODE_AVAILABLE:
        pytest.skip("qrcode not installed, so no QR is drawn to measure")

    img = display.generate_info_screen(ap_mode=ap_mode)
    width, height = img.size
    inner = display.MATTE_INSET + display.BORDER_WIDTH

    # Measure the QR column only: inside the border rule, and left of where the
    # text column starts.
    bbox = _content_bbox(img, box=(inner, inner,
                                   display.MATTE_INSET + display.QR_SIZE,
                                   height - inner))
    assert bbox is not None, "no QR code rendered in the QR column"

    qr_centre = (bbox[1] + bbox[3]) / 2
    assert abs(qr_centre - height / 2) <= 8, (
        f"QR vertical centre at {qr_centre}, expected ~{height / 2}"
    )
