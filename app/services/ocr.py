"""
OCR for scanned/image-based bank statements.

Default engine: Tesseract (free, local).
"""

from typing import List

import pymupdf  # PyMuPDF
import pytesseract
from PIL import Image

from app.config import OCR_ENGINE
from app.services.parsers.base import NormalizedTransaction
from app.services.parsers.generic import GenericParser

_generic_parser = GenericParser()


def extract_transactions_from_scan(
    file_path: str,
) -> List[NormalizedTransaction]:

    if OCR_ENGINE == "google_vision":
        text = _extract_text_google_vision(file_path)
    else:
        text = _extract_text_tesseract(file_path)

    transactions = []

    for line in text.splitlines():
        txn = _generic_parser._row_to_transaction(line)

        if txn:
            transactions.append(txn)

    return transactions


def _extract_text_tesseract(file_path: str) -> str:
    """
    Extract embedded page images directly from the PDF and OCR them.

    This is faster than rendering the entire PDF through pdf2image,
    especially when the PDF is already a scanned/image-based document.
    """

    full_text = []

    pdf = pymupdf.open(file_path)

    try:
        for page_number, page in enumerate(pdf, start=1):

            images = page.get_images(full=True)

            if not images:
                # Fallback for pages without embedded images
                pix = page.get_pixmap(
                    matrix=pymupdf.Matrix(1.5, 1.5),
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )

                image = Image.frombytes(
                    "RGB",
                    [pix.width, pix.height],
                    pix.samples,
                )

                text = pytesseract.image_to_string(
                    image,
                    config="--psm 6",
                )

                full_text.append(text)
                continue

            # Usually the first large image is the scanned page
            image_info = max(
                images,
                key=lambda img: img[2] * img[3]
            )

            xref = image_info[0]

            pix = pymupdf.Pixmap(pdf, xref)

            if pix.alpha:
                pix = pymupdf.Pixmap(
                    pymupdf.csRGB,
                    pix
                )

            image = Image.frombytes(
                "RGB",
                [pix.width, pix.height],
                pix.samples,
            )

            text = pytesseract.image_to_string(
                image,
                config="--psm 6",
            )

            full_text.append(
                f"\n--- PAGE {page_number} ---\n{text}"
            )

            # Release memory
            pix = None
            image.close()

    finally:
        pdf.close()

    return "\n".join(full_text)


def _extract_text_google_vision(file_path: str) -> str:
    """
    Google Vision OCR is currently not implemented.
    """

    raise NotImplementedError(
        "Google Vision OCR not wired up yet. "
        "Set OCR_ENGINE=tesseract in .env."
    )