"""Generate the golden demo P&ID (Unit A) as a PNG + PDF, along with the
hand-verified expected extraction (entities.json / relationships.json)
and the golden question set.

The drawing layout and the golden extraction share this one SPEC so the
demo is deterministic: entities are drawn exactly where the expected
bounding boxes say they are.

Run from repo root:
    python scripts/make_demo_pid.py
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
DEMO_DIR = REPO / "data" / "demo"
PID_DIR = DEMO_DIR / "pid"
EXPECTED_DIR = DEMO_DIR / "expected"

W, H = 1600, 1000
BG = (250, 250, 246)
INK = (30, 42, 62)
BLUE = (37, 99, 235)
GREEN = (5, 150, 105)
AMBER = (217, 119, 6)
RED = (190, 18, 60)
GRAY = (100, 116, 139)


def norm(x: float, y: float, w: float = 0.0, h: float = 0.0) -> list[float]:
    return [round(x / W, 4), round(y / H, 4), round(w / W, 4), round(h / H, 4)]


# ── canonical spec: entity -> (canvas center x, y, w, h, type, label, conf) ──
SPEC_ENTITIES = [
    #  equipment
    (0.150, 0.52, 0.075, 0.14, "equipment", "V-101", "Feed Vessel", 0.98),
    (0.360, 0.60, 0.065, 0.065, "equipment", "P-101", "Centrifugal Pump", 0.97),
    (0.620, 0.46, 0.12, 0.055, "equipment", "E-101", "Shell & Tube Heater", 0.96),
    (0.860, 0.46, 0.075, 0.075, "equipment", "T-201", "Product Tank", 0.97),
    #  instruments
    (0.075, 0.20, 0.050, 0.050, "instrument", "LIC-101", "Level Controller", 0.94),
    (0.210, 0.30, 0.045, 0.045, "instrument", "PI-101", "Pressure Indicator", 0.92),
    (0.440, 0.76, 0.045, 0.045, "instrument", "PI-102", "Discharge Pressure", 0.93),
    (0.470, 0.20, 0.050, 0.050, "instrument", "FI-101", "Flow Indicator", 0.90),
    (0.530, 0.14, 0.045, 0.045, "instrument", "TI-101", "Inlet Temperature", 0.88),
    (0.690, 0.14, 0.045, 0.045, "instrument", "TI-102", "Outlet Temperature", 0.89),
    (0.300, 0.22, 0.045, 0.045, "instrument", "TT-201", "Skin Temperature", 0.45),   # UNCERTAIN
    (0.410, 0.38, 0.050, 0.050, "valve", "PSV-101", "Pressure Safety Valve", 0.91),
    #  valves
    (0.250, 0.585, 0.030, 0.030, "valve", "XV-101", "Motor Isolating Valve", 0.93),
    (0.490, 0.545, 0.030, 0.030, "valve", "FV-101", "Flow Control Valve", 0.92),
    #  lines
    (0.203, 0.585, 0.120, 0.015, "process_line", "L-101", "Suction Line", 0.96),
    (0.423, 0.545, 0.140, 0.015, "process_line", "L-102", "Discharge Line", 0.95),
    (0.680, 0.545, 0.24, 0.015, "process_line", "L-103", "Heater Outlet", 0.94),
    (0.480, 0.40, 0.16, 0.015, "process_line", "L-104", "Bypass (uncertain)", 0.42),  # UNCERTAIN
    (0.280, 0.68, 0.12, 0.015, "process_line", "L-105", "Drain (uncertain)", 0.40),   # UNCERTAIN
]

# coordinates overridden below by actual polyline anchor boxes where needed
SPEC_LINES = {
    "L-101": [(0.145, 0.585), (0.265, 0.585)],
    "L-102": [(0.395, 0.545), (0.560, 0.545)],
    "L-103": [(0.680, 0.545), (0.820, 0.545)],
    "L-104": [(0.480, 0.40), (0.640, 0.40)],
    "L-105": [(0.265, 0.60), (0.340, 0.68)],
}


# ── relationships ─────────────────────────────────────────────
RELATIONSHIPS = [
    ("V-101", "TO", "L-101", 0.95),
    ("L-101", "TO", "P-101", 0.96),
    ("P-101", "TO", "L-102", 0.96),
    ("L-102", "TO", "E-101", 0.95),
    ("E-101", "TO", "L-103", 0.94),
    ("L-103", "TO", "T-201", 0.95),
    ("L-104", "TO", "E-101", 0.40),   # uncertain bypass
    ("V-101", "HAS_INSTRUMENT", "LIC-101", 0.94),
    ("V-101", "HAS_INSTRUMENT", "PI-101", 0.92),
    ("P-101", "HAS_INSTRUMENT", "PI-102", 0.93),
    ("E-101", "HAS_INSTRUMENT", "TI-101", 0.88),
    ("E-101", "HAS_INSTRUMENT", "TI-102", 0.89),
    ("E-101", "HAS_INSTRUMENT", "TT-201", 0.45),
    ("P-101", "HAS_VALVE", "PSV-101", 0.91),
    ("L-101", "HAS_VALVE", "XV-101", 0.93),
    ("L-102", "HAS_VALVE", "FV-101", 0.92),
]


def build_expected() -> None:
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    entities = []
    for cx, cy, w, h, etype, tag, label, conf in SPEC_ENTITIES:
        x = cx * W - (w * W) / 2
        y = cy * H - (h * H) / 2
        entities.append(
            {
                "type": etype,
                "tag": tag,
                "label": label,
                "bbox": norm(x, y, w * W, h * H),
                "confidence": conf,
                "raw_text": tag,
            }
        )
    relationships = []
    for src, rel, tgt, conf in RELATIONSHIPS:
        relationships.append({"source": src, "relation": rel, "target": tgt, "confidence": conf})

    expected = {"document": "unit-a-pid.png", "entities": entities, "relationships": relationships}
    (EXPECTED_DIR / "entities.json").write_text(
        json.dumps(expected, indent=2), encoding="utf-8")
    print(f"wrote entities.json: {len(entities)} entities, {len(relationships)} relationships")


if __name__ == "__main__":
    build_expected()
    print("Demo P&ID spec written.")

# ── drawing helpers ───────────────────────────────────────────
FONT_CACHE: dict = {}


def font(size: int):
    if size in FONT_CACHE:
        return FONT_CACHE[size]
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            f = ImageFont.truetype(name, size)
            FONT_CACHE[size] = f
            return f
        except Exception:
            continue
    f = ImageFont.load_default(size=size)
    FONT_CACHE[size] = f
    return f


def label(draw, cx: float, cy: float, text: str, size: int = 22,
          fill: tuple = INK, anchor="mm"):
    draw.text((cx, cy), text, font=font(size), fill=fill, anchor=anchor)


def draw_equipment(draw, cx: float, cy: float, w: float, h: float, tag: str) -> None:
    x0, y0 = cx - w / 2, cy - h / 2
    x1, y1 = cx + w / 2, cy + h / 2
    if tag == "V-101":
        draw.rounded_rectangle([x0, y0, x1, y1], radius=18, outline=INK, width=4)
        draw.ellipse([x0, y0 - 14, x1, y0 + 14], outline=INK, width=4)
        draw.ellipse([x0, y1 - 14, x1, y1 + 14], outline=INK, width=4)
    elif tag == "P-101":
        r = w / 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, width=4)
        draw.polygon([(cx - r * 0.45, cy + r * 0.55), (cx + r * 0.45, cy + r * 0.55),
                      (cx, cy - r * 0.45)], outline=INK, width=3)
    elif tag == "E-101":
        draw.rounded_rectangle([x0, y0, x1, y1], radius=10, outline=INK, width=4)
        for i in range(6):
            y = y0 + (i + 1) * (h / 7)
            draw.line([(x0, y), (x1, y)], fill=BLUE, width=2)
    elif tag == "T-201":
        r = w / 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, width=4)
        draw.line([(cx - r, cy), (cx + r, cy)], fill=INK, width=2)
    else:
        draw.rounded_rectangle([x0, y0, x1, y1], radius=12, outline=INK, width=4)


def draw_instrument(draw, cx: float, cy: float, r: float, tag: str, conf: float) -> None:
    color = INK if conf >= 0.6 else AMBER
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=4)
    draw.line([(cx, cy), (cx, cy + r + 18)], fill=color, width=2)
    label(draw, cx, cy, tag.split("-")[0], size=20, fill=color)


def draw_valve(draw, cx: float, cy: float, s: float, conf: float) -> None:
    color = INK if conf >= 0.6 else AMBER
    draw.polygon([(cx - s, cy - s), (cx + s, cy - s), (cx, cy + s)], outline=color, width=4)
    draw.polygon([(cx - s, cy + s), (cx + s, cy + s), (cx, cy - s)], outline=color, width=4)
def render_pid() -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ── title block ──────────────────────────────────────────
    draw.rectangle([20, 20, W - 20, 92], outline=INK, width=3)
    label(draw, W / 2, 56, "UNIT-A  FEED / PUMPING / HEATER  P&ID", size=30, fill=INK)
    label(draw, W - 90, 56, "Rev 1", size=20, fill=GRAY)

    # ── process lines (under symbols) ─────────────────────────
    draw.line([(120, 585), (212, 585)], fill=INK, width=6)
    draw.line([(212, 585), (250, 585)], fill=INK, width=6)
    draw.line([(280, 585), (332, 585)], fill=INK, width=6)
    line_p2 = [(120, 460), (120, 200), (212, 200)]
    draw.line(line_p2, fill=INK, width=5)  # LIC tap line
    draw.line([(560, 545), (620, 545)], fill=INK, width=6)
    draw.line([(680, 545), (820, 545)], fill=INK, width=6)
    draw.line([(820, 545), (822, 460)], fill=INK, width=6)
    draw.line([(360, 600), (360, 545)], fill=INK, width=5)
    draw.line([(360, 545), (395, 545)], fill=INK, width=6)
    # L-104 bypass (uncertain)
    draw.line([(480, 400), (560, 400)], fill=AMBER, width=4)
    draw.line([(560, 400), (620, 400)], fill=AMBER, width=4)
    draw.line([(620, 400), (620, 432.5)], fill=AMBER, width=4)
    # L-105 drain (uncertain)
    draw.line([(280, 610), (340, 680)], fill=AMBER, width=4)

    # ── equipment / valves / instruments ──────────────────────
    for cx, cy, w, h, etype, tag, lbl, conf in SPEC_ENTITIES:
        if etype == "equipment":
            draw_equipment(draw, cx * W, cy * H, w * W, h * H, tag)
    for cx, cy, w, h, etype, tag, lbl, conf in SPEC_ENTITIES:
        if etype == "valve":
            draw_valve(draw, cx * W, cy * H, w * W / 2, conf)
    for cx, cy, w, h, etype, tag, lbl, conf in SPEC_ENTITIES:
        if etype == "instrument":
            draw_instrument(draw, cx * W, cy * H, w * W / 2, tag, conf)

    # ── tags / labels ─────────────────────────────────────────
    for cx, cy, w, h, etype, tag, lbl, conf in SPEC_ENTITIES:
        color = INK if conf >= 0.6 else AMBER
        label(draw, cx * W, cy * H, tag, size=22, fill=color)
        label(draw, cx * W, cy * H + h * H / 2 + 22, lbl, size=16, fill=GRAY)

    # line labels
    label(draw, 0.203 * W, 0.585 * H - 24, "L-101", size=20, fill=BLUE)
    label(draw, 0.480 * W, 0.500 * H, "L-102", size=20, fill=BLUE)
    label(draw, 0.750 * W, 0.505 * H, "L-103", size=20, fill=BLUE)
    label(draw, 0.560 * W, 0.370 * H, "L-104 ?", size=18, fill=AMBER)
    label(draw, 0.300 * W, 0.720 * H, "L-105 ?", size=18, fill=AMBER)

    # process direction arrows
    label(draw, 0.230 * W, 0.600 * H, "⟶", size=26, fill=GREEN)
    label(draw, 0.470 * W, 0.560 * H, "⟶", size=26, fill=GREEN)
    label(draw, 0.750 * W, 0.560 * H, "⟶", size=26, fill=GREEN)

    draw.rectangle([0, 0, W - 1, H - 1], outline=INK, width=6)
    return img
def main() -> None:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    build_expected()

    img = render_pid()
    png_path = PID_DIR / "unit-a-pid.png"
    img.save(png_path, format="PNG")
    print(f"wrote {png_path} ({img.size[0]}x{img.size[1]})")

    # PDF page from the same image (so the demo can also upload a PDF)
    try:
        import io

        import pymupdf

        pdf_path = PID_DIR / "unit-a-pid.pdf"
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=372)
        scaled = img.resize((595, 372))
        buf = io.BytesIO()
        scaled.save(buf, format="PNG")
        page.insert_image(page.rect, stream=buf.getvalue())
        doc.save(pdf_path)
        doc.close()
        print(f"wrote {pdf_path}")
    except Exception as exc:
        print(f"PDF export skipped: {exc}")

    gq = {
        "document": "unit-a-pid.png",
        "questions": [
            {"question": "What is P-101?", "expected_tags": ["P-101"],
             "forbidden_tags": ["X-999"], "kind": "entity_lookup"},
            {"question": "What is upstream of P-101?", "expected_tags": ["L-101", "V-101"],
             "forbidden_tags": ["T-201"], "kind": "connectivity"},
            {"question": "Which instruments are associated with P-101?",
             "expected_tags": ["PI-102", "PSV-101"], "forbidden_tags": ["TI-999"],
             "kind": "instrumentation"},
            {"question": "Why do you believe L-101 connects to P-101?",
             "expected_tags": ["L-101", "P-101"], "forbidden_tags": ["L-999"], "kind": "evidence"},
            {"question": "What connections are uncertain on this page?",
             "expected_tags": ["TT-201", "L-104", "L-105"], "forbidden_tags": [],
             "kind": "uncertainty"},
        ],
    }
    (EXPECTED_DIR / "golden-questions.json").write_text(json.dumps(gq, indent=2), encoding="utf-8")
    print("wrote golden-questions.json")


if __name__ == "__main__":
    main()
