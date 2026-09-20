"""P&ID document parsing — PDF page rendering + image normalization.

- Accepts PDF and common image formats.
- Renders every PDF page to a PNG via PyMuPDF.
- Normalizes images (RGB, capped size) for the vision path.
"""
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

from PIL import Image
from pymupdf import Document as PdfDocument  # PyMuPDF (>=1.24 exposes pymupdf)


MAX_EDGE = 2400  # cap rendering resolution


class PDFParseError(Exception):
    pass


def normalize_mime(filename: str, content: bytes | None = None) -> str:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return "application/pdf"
    if content is None or len(content) < 12:
        return "application/octet-stream"
    try:
        head = content[:12]
        if head.startswith(b"\x89PNG"):
            return "image/png"
        if head.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if head.startswith(b"GIF8"):
            return "image/gif"
        if head.startswith(b"BM"):
            return "image/bmp"
        if head.startswith(b"II*\x00") or head.startswith(b"MM\x00*"):
            return "image/tiff"
    except Exception:
        pass
    return "application/octet-stream"


def is_image_mime(mime: str) -> bool:
    return mime.startswith("image/")


def open_pdf(content: bytes):
    """Open a PDF for vector-layer reading, or None when it will not parse."""
    try:
        return PdfDocument(stream=content, filetype="pdf")
    except Exception:
        return None


def render_pdf_pages(content: bytes, max_edge: int = MAX_EDGE) -> list[Image.Image]:
    """Render every page of a PDF to a PIL image."""
    try:
        pdf = PdfDocument(stream=content, filetype="pdf")
    except Exception as exc:
        raise PDFParseError(f"Could not open PDF: {exc}") from exc
    images: list[Image.Image] = []
    try:
        for page in pdf:
            pix = page.get_pixmap(matrix=None, dpi=150)
            # pix.n is 1 (gray), 3 (RGB) or 4 (RGBA/CMYK) depending on the
            # source PDF — assuming RGB corrupts or crashes on the others.
            mode = {1: "L", 3: "RGB", 4: "RGBA"}.get(pix.n)
            if mode is None:
                pix = page.get_pixmap(matrix=None, dpi=150, colorspace="rgb")
                mode = "RGB"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img = _cap_size(img, max_edge)
            images.append(img)
    finally:
        pdf.close()
    return images


def load_image(content: bytes, max_edge: int = MAX_EDGE) -> Image.Image:
    img = Image.open(io.BytesIO(content))
    img.load()
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    return _cap_size(img, max_edge)


def _cap_size(img: Image.Image, max_edge: int) -> Image.Image:
    w, h = img.size
    longest = max(w, h)
    if longest > max_edge:
        scale = max_edge / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    return img


def encode_image_b64(img: Image.Image) -> str:
    import base64

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def hash_bytes(content: bytes) -> str:
    import hashlib

    return hashlib.sha256(content).hexdigest()


def detect_lines_from_text(text: str) -> list[str]:
    """Very light heuristic that surfaces line numbers from page text."""
    return re.findall(r"\b([LPL]\s*-?\s*\d{2,4})\b", text)


def safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return cleaned or "unnamed"