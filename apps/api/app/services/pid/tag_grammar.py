"""ISA-5.1 tag grammar (README §4.5 step 2).

A P&ID's text layer is mostly tags, and a tag is not free text: ISA-5.1 gives
instrument bubbles a `[function letters][loop number]` structure, and
equipment/line tags follow plant conventions of the same shape. Parsing that
structure is what separates "the model saw some text" from "we identified a
pressure indicator on loop 101".

Parsing rather than pattern-matching buys three things:
  * a *type* that does not depend on the vision model guessing it,
  * a confidence signal (a well-formed tag is more trustworthy than a blob),
  * rejection of OCR noise that merely looks tag-shaped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ── ISA-5.1 §4.2 identification letters ───────────────────────
# First letter = measured / initiating variable.
FIRST_LETTER = {
    "A": "analysis",
    "B": "burner/combustion",
    "C": "conductivity",
    "D": "density",
    "E": "voltage",
    "F": "flow",
    "G": "gauging",
    "H": "hand",
    "I": "current",
    "J": "power",
    "K": "time/schedule",
    "L": "level",
    "M": "moisture",
    "N": "user-defined",
    "O": "user-defined",
    "P": "pressure",
    "Q": "quantity",
    "R": "radiation",
    "S": "speed/frequency",
    "T": "temperature",
    "U": "multivariable",
    "V": "vibration",
    "W": "weight/force",
    "X": "unclassified",
    "Y": "event/state",
    "Z": "position",
}

# Succeeding letters = readout / passive / output function.
SUCCEEDING_LETTER = {
    "A": "alarm",
    "B": "user-defined",
    "C": "control",
    "E": "primary element",
    "G": "glass",
    "I": "indicate",
    "K": "control station",
    "L": "light",
    "N": "user-defined",
    "O": "orifice",
    "P": "test point",
    "Q": "totalise",
    "R": "record",
    "S": "switch",
    "T": "transmit",
    "U": "multifunction",
    "V": "valve",
    "W": "well",
    "X": "accessory",
    "Y": "relay/compute",
    "Z": "driver/actuator",
}

# Equipment prefixes seen on refinery P&IDs.
EQUIPMENT_PREFIX = {
    "AC": ("equipment", "air cooler"),
    "AG": ("equipment", "agitator"),
    "B": ("equipment", "boiler"),
    "C": ("equipment", "compressor/column"),
    "CD": ("equipment", "condenser"),
    "CL": ("equipment", "cooler"),
    "D": ("equipment", "drum"),
    "DR": ("equipment", "drum"),
    "E": ("equipment", "heat exchanger"),
    "F": ("equipment", "filter/fan"),
    "FD": ("equipment", "feed drum"),
    "FL": ("equipment", "flare"),
    "H": ("equipment", "heater"),
    "HX": ("equipment", "heat exchanger"),
    "K": ("equipment", "compressor"),
    "MX": ("equipment", "mixer"),
    "P": ("equipment", "pump"),
    "R": ("equipment", "reactor"),
    "RB": ("equipment", "reboiler"),
    "S": ("equipment", "separator"),
    "SC": ("equipment", "scrubber"),
    "T": ("equipment", "tank/tower"),
    "TK": ("equipment", "tank"),
    "V": ("equipment", "vessel"),
}

# Valve prefixes that are NOT instrument loops.
VALVE_PREFIX = {
    "PSV": "pressure safety valve",
    "PRV": "pressure relief valve",
    "TSV": "thermal safety valve",
    "RV": "relief valve",
    "XV": "on/off valve",
    "HV": "hand valve",
    "FV": "flow control valve",
    "LV": "level control valve",
    "PV": "pressure control valve",
    "TV": "temperature control valve",
    "CV": "control valve",
    "BV": "ball valve",
    "GV": "gate valve",
    "NRV": "non-return valve",
    "MOV": "motor-operated valve",
}

LINE_PREFIX = {"L", "PL", "SL", "WL", "HL", "GL"}

# A tag: letters, optional separator, digits, optional suffix.
_TAG_RE = re.compile(
    r"^(?P<letters>[A-Z]{1,5})[\s\-_/]?(?P<number>\d{1,5})(?P<suffix>[A-Z]{0,2}\d{0,2})$"
)

# Line tags often carry a size-spec-service form: 6"-P-1501-A1A / 150-PL-2201
_LINE_SPEC_RE = re.compile(
    r"^(?P<size>\d{1,4})\s*(?:\"|IN|MM)?\s*[-–]\s*"
    r"(?P<service>[A-Z]{1,4})\s*[-–]\s*(?P<number>\d{2,5})"
    r"(?:\s*[-–]\s*(?P<spec>[A-Z0-9]{1,6}))?$"
)


@dataclass
class ParsedTag:
    """One parsed tag. `valid` means it matched the grammar, not that it is real."""

    raw: str
    canonical: str
    entity_type: str = "tag"
    valid: bool = False
    letters: str = ""
    loop_number: str = ""
    suffix: str = ""
    measured_variable: str = ""
    functions: list[str] = field(default_factory=list)
    description: str = ""
    line_size_mm: Optional[float] = None
    service: str = ""
    grammar_confidence: float = 0.0

    def as_label(self) -> str:
        if self.description:
            return self.description
        if self.measured_variable and self.functions:
            return f"{self.measured_variable} {'/'.join(self.functions)}".strip()
        return self.canonical


def _canonical(letters: str, number: str, suffix: str) -> str:
    return f"{letters}-{number}{suffix}"


def parse_tag(raw: str) -> ParsedTag:
    """Parse one candidate tag string into a typed, canonical tag."""
    text = (raw or "").strip().upper()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ParsedTag(raw=raw or "", canonical="", grammar_confidence=0.0)

    # ── line tags carrying a size-service-number form ──
    line = _LINE_SPEC_RE.match(text)
    if line:
        size = float(line.group("size"))
        # Bare numbers under 100 on a line tag are inches by convention.
        size_mm = size * 25.4 if size < 100 else size
        service = line.group("service")
        return ParsedTag(
            raw=raw,
            canonical=_canonical(service, line.group("number"), ""),
            entity_type="process_line",
            valid=True,
            letters=service,
            loop_number=line.group("number"),
            line_size_mm=round(size_mm, 1),
            service=service,
            description=f"{size:g} line, service {service}",
            grammar_confidence=0.95,
        )

    m = _TAG_RE.match(text)
    if not m:
        return ParsedTag(
            raw=raw,
            canonical=re.sub(r"\s+", "-", text),
            entity_type="tag",
            valid=False,
            grammar_confidence=0.2,
        )

    letters = m.group("letters")
    number = m.group("number")
    suffix = m.group("suffix") or ""
    canonical = _canonical(letters, number, suffix)

    # ── valves first: PSV/XV/FV are valves, not instrument loops ──
    if letters in VALVE_PREFIX:
        return ParsedTag(
            raw=raw,
            canonical=canonical,
            entity_type="valve",
            valid=True,
            letters=letters,
            loop_number=number,
            suffix=suffix,
            description=VALVE_PREFIX[letters],
            measured_variable=FIRST_LETTER.get(letters[0], ""),
            grammar_confidence=0.95,
        )

    # ── instrument loops: 2+ letters that decode under ISA-5.1 ──
    if len(letters) >= 2 and letters[0] in FIRST_LETTER:
        succeeding = [SUCCEEDING_LETTER.get(c) for c in letters[1:]]
        if all(succeeding):
            return ParsedTag(
                raw=raw,
                canonical=canonical,
                entity_type="instrument",
                valid=True,
                letters=letters,
                loop_number=number,
                suffix=suffix,
                measured_variable=FIRST_LETTER[letters[0]],
                functions=[s for s in succeeding if s],
                description=(
                    f"{FIRST_LETTER[letters[0]]} "
                    f"{'/'.join(s for s in succeeding if s)}"
                ),
                grammar_confidence=0.95,
            )

    # ── line prefixes ──
    if letters in LINE_PREFIX and letters not in EQUIPMENT_PREFIX:
        return ParsedTag(
            raw=raw,
            canonical=canonical,
            entity_type="process_line",
            valid=True,
            letters=letters,
            loop_number=number,
            suffix=suffix,
            description="process line",
            grammar_confidence=0.8,
        )

    # ── known equipment prefixes ──
    if letters in EQUIPMENT_PREFIX:
        etype, desc = EQUIPMENT_PREFIX[letters]
        return ParsedTag(
            raw=raw,
            canonical=canonical,
            entity_type=etype,
            valid=True,
            letters=letters,
            loop_number=number,
            suffix=suffix,
            description=desc,
            grammar_confidence=0.85,
        )

    # Well-formed but unknown prefix: keep it, flag it as a plain tag.
    return ParsedTag(
        raw=raw,
        canonical=canonical,
        entity_type="tag",
        valid=True,
        letters=letters,
        loop_number=number,
        suffix=suffix,
        grammar_confidence=0.5,
    )


def looks_like_tag(text: str) -> bool:
    """Cheap pre-filter before the full parse — used to sift a text layer."""
    t = re.sub(r"\s+", " ", (text or "").strip().upper())
    if len(t) < 2 or len(t) > 32:
        return False
    if not any(c.isdigit() for c in t) or not any(c.isalpha() for c in t):
        return False
    return bool(_TAG_RE.match(t) or _LINE_SPEC_RE.match(t))


def same_loop(a: str, b: str) -> bool:
    """True when two tags belong to the same instrument loop (PT-101 / PIC-101)."""
    pa, pb = parse_tag(a), parse_tag(b)
    if not (pa.valid and pb.valid):
        return False
    if not (pa.loop_number and pa.loop_number == pb.loop_number):
        return False
    if not (pa.letters and pb.letters):
        return False
    return pa.letters[0] == pb.letters[0]
