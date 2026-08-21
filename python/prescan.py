"""Pre-scan quality gate: cheap, deterministic image-quality checks that run
on a rendered page BEFORE layout detection/OCR, so the user gets an honest
signal about likely OCR quality before waiting 60-90s for a bad result.

A page that fails this gate is still processed in full — this never blocks
extraction, it only annotates the result with a warning. Thresholds below
are heuristic and uncalibrated (same honesty standard as rules.py's
confidence bands): they were picked to catch obviously-bad scans (heavy
blur, near-blank or near-black pages, washed-out contrast), not tuned
against a labeled dataset.
"""

import cv2
import numpy as np

# Pages are rendered at RENDER_ZOOM=4.0 (~288 DPI) by layout.py — reported
# here as a constant rather than recomputed, since prescan doesn't have
# access to the original page's physical size, only the rendered pixels.
RENDER_DPI = 288

# Laplacian variance: a standard, cheap blur-detection metric — a sharp,
# high-detail image has high-frequency content (edges) that survives the
# Laplacian; a blurred one doesn't. Threshold picked well below what a
# normal in-focus printed-text scan produces.
SHARPNESS_FAIL_THRESHOLD = 15.0
SHARPNESS_WARN_THRESHOLD = 60.0

# Standard deviation of pixel intensity: low contrast means text and
# background are too close in brightness to reliably separate.
CONTRAST_FAIL_THRESHOLD = 15.0
CONTRAST_WARN_THRESHOLD = 30.0

# Mean pixel intensity: a page that's nearly all-white (overexposed/blank)
# or all-black (underexposed) has effectively no readable content.
BRIGHTNESS_FAIL_LOW = 20.0
BRIGHTNESS_FAIL_HIGH = 245.0
BRIGHTNESS_WARN_LOW = 60.0
BRIGHTNESS_WARN_HIGH = 220.0


def run_prescan(page_image_path: str, page_number: int) -> dict:
    """Compute sharpness/contrast/brightness for one rendered page image and
    return {page, dpi, sharpness, contrast, brightness, status, reasons}.

    status is "fail" (>=1 metric in the fail range), "warn" (>=1 metric in
    the warn-but-not-fail range), or "pass" (all metrics comfortably within
    range). A "fail" is a warning to the user, never a reason to skip
    processing that page.
    """
    image = cv2.imread(page_image_path)
    if image is None:
        raise FileNotFoundError(f"Could not read rendered page image: {page_image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast = float(np.std(gray))
    brightness = float(np.mean(gray))

    reasons: list[str] = []
    status = "pass"

    if sharpness < SHARPNESS_FAIL_THRESHOLD:
        status = "fail"
        reasons.append(f"very low sharpness ({sharpness:.1f}) — page may be too blurred to OCR reliably")
    elif sharpness < SHARPNESS_WARN_THRESHOLD:
        status = "warn" if status == "pass" else status
        reasons.append(f"low sharpness ({sharpness:.1f}) — some OCR errors are likely")

    if contrast < CONTRAST_FAIL_THRESHOLD:
        status = "fail"
        reasons.append(f"very low contrast ({contrast:.1f}) — text may not be distinguishable from background")
    elif contrast < CONTRAST_WARN_THRESHOLD:
        status = "warn" if status == "pass" else status
        reasons.append(f"low contrast ({contrast:.1f}) — faint text may be missed")

    if brightness < BRIGHTNESS_FAIL_LOW or brightness > BRIGHTNESS_FAIL_HIGH:
        status = "fail"
        reasons.append(f"extreme brightness ({brightness:.1f}) — page may be blank, over-, or under-exposed")
    elif brightness < BRIGHTNESS_WARN_LOW or brightness > BRIGHTNESS_WARN_HIGH:
        status = "warn" if status == "pass" else status
        reasons.append(f"unusual brightness ({brightness:.1f})")

    return {
        "page": page_number,
        "dpi": RENDER_DPI,
        "sharpness": round(sharpness, 2),
        "contrast": round(contrast, 2),
        "brightness": round(brightness, 2),
        "status": status,
        "reasons": reasons,
    }
