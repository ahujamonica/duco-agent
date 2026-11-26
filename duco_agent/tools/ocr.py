"""OCR tool with several preprocessing strategies.

Scanned documents rarely read the same way twice. The tool exposes named
preprocessing ``variants``; the intake agent scores each attempt on evidence
(money tokens recovered, mean word confidence) and keeps the best one, so a bad
scan can trigger a retry with a different strategy instead of failing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image, ImageFilter, ImageOps

# Attempt order matters: the first pass lets tesseract find the layout itself,
# the retries take control of segmentation and scale the page up.
VARIANTS = ("auto-layout", "block", "binarised")


@dataclass
class OCRResult:
    text: str
    mean_confidence: float
    words: list[dict]
    variant: str
    width: int
    height: int

    @property
    def line_count(self) -> int:
        return len([line for line in self.text.splitlines() if line.strip()])


def _load(path: str | Path) -> Image.Image:
    return Image.open(path).convert("L")


PAGE_SEGMENTATION = {"auto-layout": "--psm 3", "block": "--psm 6", "binarised": "--psm 6"}


def _prepare(image: Image.Image, variant: str) -> Image.Image:
    if variant == "auto-layout":
        return ImageOps.autocontrast(image)
    if variant == "block":
        image = ImageOps.autocontrast(image)
        image = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
        return image.filter(ImageFilter.MedianFilter(3))
    if variant == "binarised":
        image = ImageOps.autocontrast(image)
        image = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
        image = image.filter(ImageFilter.MedianFilter(3))
        return image.point(lambda value: 0 if value < 175 else 255)
    raise ValueError(f"unknown OCR variant: {variant}")


def run_ocr(path: str | Path, variant: str = "clean") -> OCRResult:
    """Run tesseract on one image with the requested preprocessing variant."""
    source = _load(path)
    prepared = _prepare(source, variant)
    config = PAGE_SEGMENTATION.get(variant, "--psm 6")
    text = pytesseract.image_to_string(prepared, config=config)
    data = pytesseract.image_to_data(prepared, config=config, output_type=pytesseract.Output.DICT)
    confidences = [int(c) for c in data.get("conf", []) if str(c).lstrip("-").isdigit() and int(c) >= 0]
    words = [
        {"text": data["text"][i], "conf": int(data["conf"][i])}
        for i in range(len(data.get("text", [])))
        if data["text"][i].strip() and str(data["conf"][i]).lstrip("-").isdigit() and int(data["conf"][i]) > 0
    ]
    mean_confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
    return OCRResult(text=text, mean_confidence=mean_confidence, words=words, variant=variant,
                     width=prepared.width, height=prepared.height)
