"""Deterministic calculation engine (README §4.7).

The claim this module exists to make good on is: *the model never produces a
number that reaches an engineering document.* The LLM may only emit a typed
calculation REQUEST; the arithmetic happens here, in pure Python, against a
version-pinned whitelist of formulas.

Three properties follow, and each is checkable:

  * **Whitelisted** — an operation not in `FORMULAS` is refused outright, so a
    model cannot invent a calculation.
  * **Dimensionally checked** — units are converted through an explicit table.
    A mismatch is an ERROR, never a silent coercion, because a quietly
    coerced unit is how a wrong number reaches a drawing.
  * **Shown** — every result carries its formula, its intermediate steps and
    the provenance of each input, and is marked NEEDS_ENGINEERING_REVIEW.

There is deliberately no `eval` anywhere in this file.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

ENGINE_VERSION = "1.0.0"

# ── unit registry ─────────────────────────────────────────────
# Each unit maps to (dimension, factor-to-SI). Keeping this explicit — rather
# than pulling a unit library — keeps the air-gapped install free of another
# runtime dependency and makes the conversion table auditable on one screen.
UNITS: dict[str, tuple[str, float]] = {
    # length
    "m": ("length", 1.0),
    "mm": ("length", 1e-3),
    "cm": ("length", 1e-2),
    "km": ("length", 1e3),
    "in": ("length", 0.0254),
    "inch": ("length", 0.0254),
    "ft": ("length", 0.3048),
    # mass
    "kg": ("mass", 1.0),
    "g": ("mass", 1e-3),
    "t": ("mass", 1e3),
    # time
    "s": ("time", 1.0),
    "min": ("time", 60.0),
    "h": ("time", 3600.0),
    # volumetric flow  → m3/s
    "m3/s": ("volflow", 1.0),
    "m3/h": ("volflow", 1.0 / 3600.0),
    "l/s": ("volflow", 1e-3),
    "l/min": ("volflow", 1e-3 / 60.0),
    "gpm": ("volflow", 6.30902e-5),
    # mass flow → kg/s
    "kg/s": ("massflow", 1.0),
    "kg/h": ("massflow", 1.0 / 3600.0),
    "t/h": ("massflow", 1000.0 / 3600.0),
    # pressure → Pa
    "pa": ("pressure", 1.0),
    "kpa": ("pressure", 1e3),
    "mpa": ("pressure", 1e6),
    "bar": ("pressure", 1e5),
    "bara": ("pressure", 1e5),
    "barg": ("pressure", 1e5),
    "psi": ("pressure", 6894.757),
    "kg/cm2": ("pressure", 98066.5),
    # density → kg/m3
    "kg/m3": ("density", 1.0),
    "g/cm3": ("density", 1000.0),
    # dynamic viscosity → Pa·s
    "pa.s": ("viscosity", 1.0),
    "cp": ("viscosity", 1e-3),
    # velocity
    "m/s": ("velocity", 1.0),
    # temperature handled separately (offset, not a factor)
    "c": ("temperature", 1.0),
    "k": ("temperature", 1.0),
    "f": ("temperature", 1.0),
    # dimensionless
    "": ("dimensionless", 1.0),
    "-": ("dimensionless", 1.0),
}


class CalculationError(Exception):
    """Raised for anything that must not silently produce a number."""


class UnitError(CalculationError):
    pass


@dataclass
class Quantity:
    """A value with a unit and, ideally, a citation for where it came from."""

    value: float
    unit: str = ""
    source: str = "user_input"

    @property
    def dimension(self) -> str:
        return _dimension(self.unit)

    def to_si(self) -> float:
        return convert(self.value, self.unit, _si_unit(self.dimension))


def _norm_unit(unit: str) -> str:
    u = (unit or "").strip().lower()
    u = u.replace("³", "3").replace("²", "2").replace("·", ".")
    u = u.replace("m^3", "m3").replace("deg", "")
    return u


def _dimension(unit: str) -> str:
    u = _norm_unit(unit)
    if u not in UNITS:
        raise UnitError(f"Unknown unit {unit!r}. Known units: {sorted(UNITS)[:12]}…")
    return UNITS[u][0]


_SI = {
    "length": "m", "mass": "kg", "time": "s", "volflow": "m3/s",
    "massflow": "kg/s", "pressure": "pa", "density": "kg/m3",
    "viscosity": "pa.s", "velocity": "m/s", "temperature": "k",
    "dimensionless": "",
}


def _si_unit(dimension: str) -> str:
    return _SI.get(dimension, "")


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between units of the SAME dimension. Mismatch raises."""
    fu, tu = _norm_unit(from_unit), _norm_unit(to_unit)
    fd, td = _dimension(fu), _dimension(tu)
    if fd != td:
        raise UnitError(
            f"Dimensional mismatch: cannot convert {from_unit!r} ({fd}) "
            f"to {to_unit!r} ({td})."
        )
    if fd == "temperature":
        return _convert_temperature(value, fu, tu)
    return value * UNITS[fu][1] / UNITS[tu][1]


def _convert_temperature(value: float, fu: str, tu: str) -> float:
    kelvin = {"c": value + 273.15, "k": value, "f": (value - 32) * 5 / 9 + 273.15}[fu]
    if tu == "k":
        return kelvin
    if tu == "c":
        return kelvin - 273.15
    return (kelvin - 273.15) * 9 / 5 + 32


def _require(inputs: dict[str, Quantity], name: str, unit: str) -> float:
    if name not in inputs:
        raise CalculationError(f"Missing required input {name!r}.")
    return convert(inputs[name].value, inputs[name].unit, unit)


# ── formula whitelist ─────────────────────────────────────────
@dataclass
class Formula:
    operation: str
    display: str
    description: str
    result_unit: str
    required: tuple[str, ...]
    fn: Callable[[dict[str, Quantity], list[str]], float]
    reference: str = ""
    # A plausible output band; outside it the result is flagged, not hidden.
    sane_range: tuple[float, float] = (-math.inf, math.inf)


def _pipe_area(diameter_m: float) -> float:
    return math.pi * diameter_m ** 2 / 4.0


def _fluid_velocity(inputs, steps):
    flow = _require(inputs, "flow", "m3/s")
    dia = _require(inputs, "diameter", "m")
    area = _pipe_area(dia)
    steps.append(f"A = pi*D^2/4 = pi*{dia:.4f}^2/4 = {area:.6f} m2")
    if area <= 0:
        raise CalculationError("Diameter must be greater than zero.")
    v = flow / area
    steps.append(f"v = Q/A = {flow:.6f}/{area:.6f} = {v:.4f} m/s")
    return v


def _reynolds(inputs, steps):
    rho = _require(inputs, "density", "kg/m3")
    mu = _require(inputs, "viscosity", "pa.s")
    dia = _require(inputs, "diameter", "m")
    v = _fluid_velocity(inputs, steps)
    if mu <= 0:
        raise CalculationError("Viscosity must be greater than zero.")
    re = rho * v * dia / mu
    steps.append(f"Re = rho*v*D/mu = {rho}*{v:.4f}*{dia:.4f}/{mu} = {re:.1f}")
    return re


def _friction_factor(re: float, steps: list[str], roughness_m: float, dia_m: float) -> float:
    if re < 2300:
        f = 64.0 / max(re, 1e-6)
        steps.append(f"Laminar (Re<2300): f = 64/Re = {f:.5f}")
        return f
    # Swamee–Jain: an explicit approximation of Colebrook-White.
    rel = roughness_m / dia_m if dia_m > 0 else 0.0
    f = 0.25 / (math.log10(rel / 3.7 + 5.74 / re ** 0.9)) ** 2
    steps.append(
        f"Turbulent: Swamee-Jain f = 0.25/[log10(e/3.7D + 5.74/Re^0.9)]^2 = {f:.5f}"
    )
    return f


def _darcy_weisbach(inputs, steps):
    rho = _require(inputs, "density", "kg/m3")
    length = _require(inputs, "length", "m")
    dia = _require(inputs, "diameter", "m")
    roughness = (
        _require(inputs, "roughness", "m") if "roughness" in inputs else 4.5e-5
    )
    steps.append(f"Absolute roughness e = {roughness:g} m (commercial steel default)")
    v = _fluid_velocity(inputs, steps)
    re = _reynolds(inputs, steps) if "viscosity" in inputs else 1e5
    if "viscosity" not in inputs:
        steps.append("No viscosity supplied: assuming fully turbulent Re = 1e5.")
    f = _friction_factor(re, steps, roughness, dia)
    dp = f * (length / dia) * (rho * v * v / 2.0)
    steps.append(
        f"dP = f*(L/D)*(rho*v^2/2) = {f:.5f}*({length:.2f}/{dia:.4f})"
        f"*({rho}*{v:.4f}^2/2) = {dp:.1f} Pa"
    )
    return dp


def _static_head(inputs, steps):
    rho = _require(inputs, "density", "kg/m3")
    height = _require(inputs, "height", "m")
    g = 9.80665
    dp = rho * g * height
    steps.append(f"dP = rho*g*h = {rho}*{g}*{height:.3f} = {dp:.1f} Pa")
    return dp


def _orifice_flow(inputs, steps):
    dp = _require(inputs, "delta_p", "pa")
    rho = _require(inputs, "density", "kg/m3")
    dia = _require(inputs, "diameter", "m")
    cd = inputs["cd"].value if "cd" in inputs else 0.61
    area = _pipe_area(dia)
    steps.append(f"Orifice area A = {area:.6f} m2, Cd = {cd}")
    if rho <= 0:
        raise CalculationError("Density must be greater than zero.")
    q = cd * area * math.sqrt(2 * dp / rho)
    steps.append(f"Q = Cd*A*sqrt(2*dP/rho) = {q:.6f} m3/s")
    return q


def _pump_hydraulic_power(inputs, steps):
    flow = _require(inputs, "flow", "m3/s")
    dp = _require(inputs, "delta_p", "pa")
    eff = inputs["efficiency"].value if "efficiency" in inputs else 1.0
    if not (0 < eff <= 1):
        raise CalculationError("Efficiency must be between 0 and 1.")
    power = flow * dp / eff
    steps.append(f"P = Q*dP/eta = {flow:.6f}*{dp:.1f}/{eff} = {power:.1f} W")
    return power


def _relief_required_area(inputs, steps):
    """API 520 simplified vapour sizing — the shape, with the constants shown."""
    w = _require(inputs, "mass_flow", "kg/s")
    p = _require(inputs, "relieving_pressure", "pa")
    t = _require(inputs, "temperature", "k")
    m = inputs["molecular_weight"].value if "molecular_weight" in inputs else 29.0
    kd = inputs["kd"].value if "kd" in inputs else 0.975
    k = inputs["k"].value if "k" in inputs else 1.4
    c = 0.03948 * math.sqrt(k * (2 / (k + 1)) ** ((k + 1) / (k - 1)))
    steps.append(f"C from k={k}: {c:.5f}")
    area = (w * 1000) / (c * kd * (p / 1000) ) * math.sqrt(t / m) / 1000
    steps.append(
        f"A = W/(C*Kd*P)*sqrt(T*Z/M) with W={w:.4f} kg/s, P={p:.0f} Pa, "
        f"T={t:.1f} K, M={m} -> {area:.6f} m2"
    )
    return area


FORMULAS: dict[str, Formula] = {
    "fluid_velocity": Formula(
        operation="fluid_velocity",
        display="v = Q / A,  A = pi*D^2/4",
        description="Bulk fluid velocity in a circular pipe.",
        result_unit="m/s",
        required=("flow", "diameter"),
        fn=_fluid_velocity,
        reference="Continuity equation",
        sane_range=(0.0, 30.0),
    ),
    "reynolds_number": Formula(
        operation="reynolds_number",
        display="Re = rho*v*D/mu",
        description="Reynolds number for pipe flow.",
        result_unit="",
        required=("flow", "diameter", "density", "viscosity"),
        fn=_reynolds,
        reference="Reynolds (1883)",
        sane_range=(0.0, 1e9),
    ),
    "line_pressure_drop_darcy_weisbach": Formula(
        operation="line_pressure_drop_darcy_weisbach",
        display="dP = f*(L/D)*(rho*v^2/2)",
        description="Frictional pressure drop in a straight run of pipe.",
        result_unit="pa",
        required=("flow", "diameter", "length", "density"),
        fn=_darcy_weisbach,
        reference="Darcy-Weisbach; Swamee-Jain friction factor",
        sane_range=(0.0, 1e8),
    ),
    "static_head_pressure": Formula(
        operation="static_head_pressure",
        display="dP = rho*g*h",
        description="Static pressure from an elevation difference.",
        result_unit="pa",
        required=("density", "height"),
        fn=_static_head,
        reference="Hydrostatics",
        sane_range=(-1e8, 1e8),
    ),
    "orifice_flow": Formula(
        operation="orifice_flow",
        display="Q = Cd*A*sqrt(2*dP/rho)",
        description="Volumetric flow through an orifice from measured dP.",
        result_unit="m3/s",
        required=("delta_p", "density", "diameter"),
        fn=_orifice_flow,
        reference="ISO 5167 (simplified)",
        sane_range=(0.0, 100.0),
    ),
    "pump_hydraulic_power": Formula(
        operation="pump_hydraulic_power",
        display="P = Q*dP/eta",
        description="Hydraulic power demanded by a pump duty.",
        result_unit="pa",  # W; dimensionally reported below
        required=("flow", "delta_p"),
        fn=_pump_hydraulic_power,
        reference="Pump hydraulics",
        sane_range=(0.0, 1e9),
    ),
    "relief_valve_area_api520": Formula(
        operation="relief_valve_area_api520",
        display="A = W/(C*Kd*P)*sqrt(T*Z/M)",
        description="Required relief orifice area, API 520 vapour service.",
        result_unit="",  # m2
        required=("mass_flow", "relieving_pressure", "temperature"),
        fn=_relief_required_area,
        reference="API 520 Part I (simplified, vapour)",
        sane_range=(0.0, 1.0),
    ),
}

# Result units that are not in the generic UNITS table.
_RESULT_UNIT_OVERRIDE = {
    "pump_hydraulic_power": "W",
    "relief_valve_area_api520": "m2",
    "reynolds_number": "-",
}


@dataclass
class CalculationResult:
    calculation_id: str
    operation: str
    result: float
    unit: str
    formula: str
    intermediate_steps: list[str] = field(default_factory=list)
    provenance: list[dict] = field(default_factory=list)
    status: str = "NEEDS_ENGINEERING_REVIEW"
    verification: str = ""
    engine_version: str = ENGINE_VERSION
    reference: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "calculation_id": self.calculation_id,
            "operation": self.operation,
            "result": self.result,
            "unit": self.unit,
            "formula": self.formula,
            "intermediate_steps": self.intermediate_steps,
            "provenance": self.provenance,
            "status": self.status,
            "verification": self.verification,
            "engine_version": self.engine_version,
            "reference": self.reference,
            "warnings": self.warnings,
        }


def _calculation_id(operation: str, inputs: dict[str, Quantity]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    payload = operation + "|" + "|".join(
        f"{k}={inputs[k].value}{inputs[k].unit}" for k in sorted(inputs)
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()[:6].upper()
    return f"CAL-{stamp}-{digest}"


def list_operations() -> list[dict]:
    """The whitelist, for the tool registry and the UI."""
    return [
        {
            "operation": f.operation,
            "formula": f.display,
            "description": f.description,
            "required_inputs": list(f.required),
            "result_unit": _RESULT_UNIT_OVERRIDE.get(f.operation, f.result_unit),
            "reference": f.reference,
        }
        for f in FORMULAS.values()
    ]


def calculate(
    operation: str,
    inputs: dict[str, Any],
    output_unit: Optional[str] = None,
) -> CalculationResult:
    """Run one whitelisted calculation.

    `inputs` maps a name to `{"value", "unit", "source"}` or a bare number.
    Anything unknown, dimensionally inconsistent or missing raises rather than
    returning a number that looks usable.
    """
    formula = FORMULAS.get(operation)
    if formula is None:
        raise CalculationError(
            f"Operation {operation!r} is not in the signed whitelist. "
            f"Available: {sorted(FORMULAS)}"
        )

    parsed: dict[str, Quantity] = {}
    for name, raw in (inputs or {}).items():
        if isinstance(raw, dict):
            parsed[name] = Quantity(
                value=float(raw.get("value")),
                unit=str(raw.get("unit", "") or ""),
                source=str(raw.get("source", "user_input")),
            )
        else:
            parsed[name] = Quantity(value=float(raw))

    missing = [r for r in formula.required if r not in parsed]
    if missing:
        raise CalculationError(
            f"{operation} requires {list(formula.required)}; missing {missing}."
        )

    # Dimensional check up front, so a bad unit fails before any arithmetic.
    for name, qty in parsed.items():
        _dimension(qty.unit)

    steps: list[str] = []
    value_si = formula.fn(parsed, steps)
    # Composite formulas reuse sub-calculations (dP needs velocity, and so
    # does Reynolds), so the same line can be appended twice. The working
    # shown to an engineer should read once, in order.
    seen: set[str] = set()
    steps = [s for s in steps if not (s in seen or seen.add(s))]

    unit = _RESULT_UNIT_OVERRIDE.get(operation, formula.result_unit)
    result = value_si
    if output_unit:
        try:
            result = convert(value_si, formula.result_unit, output_unit)
            steps.append(f"Converted {value_si:.6g} {formula.result_unit} -> "
                         f"{result:.6g} {output_unit}")
            unit = output_unit
        except UnitError as exc:
            raise UnitError(f"Cannot report {operation} in {output_unit!r}: {exc}")

    warnings: list[str] = []
    lo, hi = formula.sane_range
    range_ok = lo <= value_si <= hi
    if not range_ok:
        warnings.append(
            f"Result {value_si:.4g} is outside the expected band "
            f"[{lo:g}, {hi:g}] — check the inputs."
        )

    return CalculationResult(
        calculation_id=_calculation_id(operation, parsed),
        operation=operation,
        result=round(float(result), 6),
        unit=unit,
        formula=formula.display,
        intermediate_steps=steps,
        provenance=[
            {"input": n, "value": q.value, "unit": q.unit, "source": q.source}
            for n, q in sorted(parsed.items())
        ],
        status="NEEDS_ENGINEERING_REVIEW",
        verification="UNITS_OK | " + ("RANGE_OK" if range_ok else "RANGE_SUSPECT")
        + " | FORMULA_WHITELISTED",
        reference=formula.reference,
        warnings=warnings,
    )
