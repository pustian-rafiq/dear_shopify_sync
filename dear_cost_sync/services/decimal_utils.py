"""Money/decimal helpers — never use float for money."""

from __future__ import annotations

from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
)

from dear_cost_sync.services.exceptions import ValidationError

_ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_UP": ROUND_UP,
}


def resolve_rounding_mode(name: str):
    try:
        return _ROUNDING_MODES[name]
    except KeyError as exc:
        raise ValidationError(
            f"Unsupported rounding_mode {name!r}; "
            f"expected one of {sorted(_ROUNDING_MODES)}"
        ) from exc


def to_decimal(value) -> Decimal:
    if value is None:
        raise ValidationError("cost value is null")
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, bool):
        raise ValidationError("cost value is boolean")
    elif isinstance(value, int):
        candidate = Decimal(value)
    elif isinstance(value, float):
        candidate = Decimal(str(value))
    elif isinstance(value, str):
        text = value.strip()
        if text == "":
            raise ValidationError("cost value is empty string")
        try:
            candidate = Decimal(text)
        except InvalidOperation as exc:
            raise ValidationError(f"cost value {value!r} is not numeric") from exc
    else:
        raise ValidationError(f"cost value has unsupported type {type(value).__name__}")

    if not candidate.is_finite():
        raise ValidationError(f"cost value {value!r} is not finite")
    if candidate < 0:
        raise ValidationError(f"cost value {value!r} is negative")
    return candidate


def normalise_cost(
    value, decimal_places: int = 2, rounding_mode: str = "ROUND_HALF_UP"
) -> Decimal:
    if decimal_places < 0:
        raise ValidationError("decimal_places must be >= 0")
    dec = to_decimal(value)
    quant = Decimal(1).scaleb(-decimal_places)
    return dec.quantize(quant, rounding=resolve_rounding_mode(rounding_mode))


def decimal_to_cost_string(value: Decimal, decimal_places: int = 2) -> str:
    if not isinstance(value, Decimal):
        value = to_decimal(value)
    quant = Decimal(1).scaleb(-decimal_places)
    return str(value.quantize(quant, rounding=ROUND_HALF_UP))


def costs_differ(new_cost: Decimal, previous_cost, tolerance: str = "0.00") -> bool:
    if previous_cost is None:
        return True
    prev = previous_cost if isinstance(previous_cost, Decimal) else to_decimal(previous_cost)
    tol = Decimal(tolerance)
    return abs(new_cost - prev) > tol
