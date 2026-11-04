"""Numeric answers with units (spec 006). Pure, no DB."""

from typing import Any

import pytest
import sympy

from app.content.units import UnitError
from app.grading import grade
from app.grading.units import convert_factor, normalise, parse_student_unit, quantity_name

R = sympy.Rational


def num(spec: dict[str, Any], response: str, unit: str | None) -> Any:
    return grade("numeric", {"spec": spec}, {}, response, unit=unit)


@pytest.mark.parametrize(
    ("typed", "same_as"),
    [
        ("kmph", "km/h"),
        ("kph", "km/h"),
        ("km/hr", "km/h"),
        ("km h^-1", "km/h"),
        ("km h⁻¹", "km/h"),
        ("mps", "m/s"),
        ("m s^-1", "m/s"),
        ("m·s^-1", "m/s"),
        ("sec", "s"),
        ("secs", "s"),
        ("hrs", "h"),
        ("kgs", "kg"),
        ("m/s²", "m/s^2"),
        ("m³", "m^3"),
        ("Ω", "ohm"),
        ("N m", "J"),
    ],
)
def test_aliases_and_forms(typed: str, same_as: str) -> None:
    assert convert_factor(typed, same_as) == 1


def test_matching_is_case_sensitive() -> None:
    assert convert_factor("ms", "s") == R(1, 1000)  # milliseconds, not metres per second
    with pytest.raises(UnitError):
        parse_student_unit("n")
    with pytest.raises(UnitError):
        parse_student_unit("x" * 41)


def test_normalise() -> None:
    assert normalise(" km  h^-1 ") == "km*h^-1"
    assert normalise("x/kmph") == "x/(km/h)"


def test_factor_and_dimension() -> None:
    assert convert_factor("m/s", "km/h") == R(18, 5)
    assert convert_factor("km", "m") == 1000
    assert convert_factor("s", "km/h") is None


def test_quantity_names() -> None:
    assert quantity_name("km/h") == "speed"
    assert quantity_name("m") == "length"
    assert quantity_name("m/s^2") == "acceleration"
    assert quantity_name("N") == "force"
    assert quantity_name("ohm") == "resistance"
    assert quantity_name("m^4") == "that quantity"


SPEED = {"value": "80/3", "mode": "sigfig", "sigfigs": 3, "unit": "km/h"}


def test_sigfig_in_the_students_unit() -> None:
    assert num(SPEED, "26.7", "km/h").correct
    assert num(SPEED, "7.41", "m/s").correct
    assert not num(SPEED, "7.40", "m/s").correct
    short = num(SPEED, "7.4", "m/s")
    assert not short.correct and short.note == "Give 3 significant figures"
    assert num(SPEED, "7.41", "m/s").display_answer == "26.7 km/h"


def test_exact_in_another_unit() -> None:
    metres = {"value": "500", "mode": "exact", "unit": "m"}
    assert num(metres, "500", "m").correct
    assert num(metres, "0.5", "km").correct
    assert num(metres, "50000", "cm").correct
    assert not num(metres, "0.6", "km").correct
    eight = {"value": "8", "mode": "exact", "unit": "m/s"}
    assert num(eight, "28.8", "km/h").correct
    ten = {"value": "10", "mode": "exact", "unit": "km/h"}
    off = num(ten, "2.78", "m/s")
    assert not off.correct and off.note == "Give it in km/h"


def test_tolerance_in_another_unit() -> None:
    spec = {"value": "1500", "mode": "tolerance", "rel_tol": 0.01, "unit": "m"}
    assert num(spec, "1.51", "km").correct
    assert not num(spec, "1.6", "km").correct


def test_unit_notes() -> None:
    metres = {"value": "500", "mode": "exact", "unit": "m"}
    wrong_dim = num(metres, "5", "s")
    assert not wrong_dim.correct and wrong_dim.note == "That unit doesn't measure length"
    missing = num(metres, "500", "")
    assert not missing.correct and missing.note == "Add a unit, e.g. m"
    assert num(metres, "500", None).note == "Add a unit, e.g. m"
    unreadable = num(metres, "500", "metres")
    assert not unreadable.correct and unreadable.note == "Couldn't read that unit"
    speed = num(SPEED, "5", "ms")
    assert speed.note == "That unit doesn't measure speed"
    assert num(metres, "abc", "m").note == "Enter a number, e.g. 12.5 or 3.0e8"


def test_unitless_answer_ignores_the_box() -> None:
    assert num({"value": "3", "mode": "exact"}, "3", None).correct


@pytest.mark.parametrize(
    "unit", ["((km^999)^999)^999", "((km/mm)^999)^999*m", "km^7", "s^-9", "(m^3)^3"]
)
def test_huge_powers_are_refused_quickly(unit: str) -> None:
    """Security: nested powers merge into one huge exponent; never convert it (DoS)."""
    import time

    start = time.monotonic()
    result = num({"value": "500", "mode": "exact", "unit": "m"}, "1", unit)
    assert not result.correct and result.note == "Couldn't read that unit"
    assert time.monotonic() - start < 1


def test_ordinary_powers_still_work() -> None:
    assert convert_factor("m^3", "L") == 1000
    assert convert_factor("m s^-2", "m/s^2") == 1
