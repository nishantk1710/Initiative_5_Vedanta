"""Pre-scan quality gate — real, measured metrics on synthetic images, not
fabricated scores. A crisp high-contrast image must pass; a heavily blurred
or washed-out one must fail/warn."""

import cv2
import numpy as np
import pytest

from prescan import SHARPNESS_WARN_THRESHOLD, run_prescan


def _write(path, image):
    cv2.imwrite(str(path), image)
    return str(path)


def _sharp_text_like_image(size=400):
    """High-frequency content (checkerboard-ish stripes) simulates a crisp
    printed page — real text produces plenty of edge content too."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    for y in range(0, size, 6):
        cv2.line(img, (0, y), (size, y), (0, 0, 0), 1)
    for x in range(0, size, 6):
        cv2.line(img, (x, 0), (x, size), (0, 0, 0), 1)
    return img


def _text_line_block_image(size=400):
    """Sparse thick black blocks on white, simulating text lines with wide
    gaps — unlike the fine grid above, mild blur softens edges here without
    collapsing overall contrast, since large flat black/white regions
    survive a small blur radius."""
    img = np.full((size, size, 3), 255, dtype=np.uint8)
    for y in range(20, size - 20, 40):
        cv2.rectangle(img, (20, y), (size - 20, y + 18), (0, 0, 0), -1)
    return img


def test_sharp_high_contrast_page_passes(tmp_path):
    image = _sharp_text_like_image()
    path = _write(tmp_path / "sharp.png", image)
    result = run_prescan(path, page_number=1)
    assert result["status"] == "pass"
    assert result["reasons"] == []
    assert result["page"] == 1
    assert result["dpi"] == 288


def test_blurred_page_is_flagged(tmp_path):
    """Heavy Gaussian blur washes out a sharp page's edges and contrast
    together — whichever metric actually crosses its threshold, the page
    must be flagged, not silently passed."""
    sharp = _sharp_text_like_image()
    blurred = cv2.GaussianBlur(sharp, (31, 31), 15)
    path = _write(tmp_path / "blurred.png", blurred)
    result = run_prescan(path, page_number=2)
    assert result["status"] in ("warn", "fail")
    assert result["reasons"]


def test_sharpness_reason_is_reported_when_sharpness_itself_is_low(tmp_path):
    """A mild blur that drops sharpness without collapsing contrast must be
    attributed to sharpness specifically, not just some flag."""
    block_image = _text_line_block_image()
    mildly_blurred = cv2.GaussianBlur(block_image, (9, 9), 4)
    path = _write(tmp_path / "mild_blur.png", mildly_blurred)
    result = run_prescan(path, page_number=2)
    assert result["sharpness"] < SHARPNESS_WARN_THRESHOLD
    assert any("sharpness" in r for r in result["reasons"])


def test_blank_white_page_fails_on_contrast_and_brightness(tmp_path):
    blank = np.full((400, 400, 3), 255, dtype=np.uint8)
    path = _write(tmp_path / "blank.png", blank)
    result = run_prescan(path, page_number=3)
    assert result["status"] == "fail"
    assert len(result["reasons"]) >= 1


def test_nearly_black_page_fails(tmp_path):
    dark = np.full((400, 400, 3), 5, dtype=np.uint8)
    path = _write(tmp_path / "dark.png", dark)
    result = run_prescan(path, page_number=4)
    assert result["status"] == "fail"


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_prescan(str(tmp_path / "does_not_exist.png"), page_number=1)


def test_fail_never_escalates_below_warn_metrics():
    """A page failing on one metric while others merely warn must still
    report status 'fail' overall (worst-case across metrics), and still
    list every triggered reason, not just the first one found."""
    img = np.full((400, 400, 3), 255, dtype=np.uint8)  # blank: fails contrast+brightness
    import tempfile
    import os
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        cv2.imwrite(path, img)
        result = run_prescan(path, page_number=1)
        assert result["status"] == "fail"
        assert len(result["reasons"]) >= 2
    finally:
        os.remove(path)
