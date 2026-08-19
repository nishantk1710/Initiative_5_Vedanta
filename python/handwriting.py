import os
import shutil

import cv2
import numpy as np
import pytesseract

from paths import document_dir

_DEFAULT_WINDOWS_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if shutil.which("tesseract") is None and os.path.isfile(_DEFAULT_WINDOWS_TESSERACT):
    pytesseract.pytesseract.tesseract_cmd = _DEFAULT_WINDOWS_TESSERACT


def _preprocess(crop: np.ndarray) -> np.ndarray:
    """crop -> grayscale -> upscale -> denoise -> adaptive threshold."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    upscaled = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    denoised = cv2.fastNlMeansDenoising(upscaled, h=10)

    thresholded = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31,
        C=11,
    )

    return thresholded


def extract_handwriting(layout: dict, image_path: str, document_id: str) -> list[dict]:
    """Crop each kept handwriting region, preprocess it, run Tesseract, and
    return one ExtractedValue-shaped dict per detected text element. Crops
    are saved under results/<document_id>/handwriting/ for provenance."""
    page_number = layout["page"]
    regions = [r for r in layout["regions"] if r.get("category") == "handwriting"]
    if not regions:
        return []

    handwriting_dir = os.path.join(document_dir(document_id), "handwriting")
    os.makedirs(handwriting_dir, exist_ok=True)

    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"Could not read rendered page image: {image_path}")

    values: list[dict] = []

    for region_index, region in enumerate(regions):
        x0, y0, x1, y1 = [int(round(v)) for v in region["bbox"]]
        crop = image[max(y0, 0) : y1, max(x0, 0) : x1]
        if crop.size == 0:
            continue

        crop_path = os.path.join(handwriting_dir, f"hand_{region_index}.png")
        cv2.imwrite(crop_path, crop)

        preprocessed = _preprocess(crop)

        data = pytesseract.image_to_data(
            preprocessed, output_type=pytesseract.Output.DICT
        )

        # upscale factor applied in _preprocess — divide word boxes back down
        # to crop-local coordinates before translating to page coordinates
        scale = 0.5

        for i, text in enumerate(data["text"]):
            if not text or not text.strip():
                continue

            raw_conf = float(data["conf"][i])
            if raw_conf < 0:  # Tesseract uses -1 for non-text/structural entries
                continue

            wx = data["left"][i] * scale
            wy = data["top"][i] * scale
            ww = data["width"][i] * scale
            wh = data["height"][i] * scale

            page_bbox = [
                float(x0 + wx),
                float(y0 + wy),
                float(x0 + wx + ww),
                float(y0 + wy + wh),
            ]

            values.append(
                {
                    "value": text.strip(),
                    "source": "tesseract",
                    "confidence": raw_conf / 100.0,  # normalize 0-100 -> 0-1
                    "page": page_number,
                    "bbox": page_bbox,
                }
            )

    return values
