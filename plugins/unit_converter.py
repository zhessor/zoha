"""Example plugin: convert common units by voice ("convert 5 kilometres to miles", "70 kilos in pounds")."""

from zoha.tools import tool

# unit -> (group, size in the group's base unit)
UNITS = {
    "mm": ("length", 0.001), "cm": ("length", 0.01), "m": ("length", 1.0), "km": ("length", 1000.0),
    "inch": ("length", 0.0254), "foot": ("length", 0.3048), "yard": ("length", 0.9144), "mile": ("length", 1609.344),
    "g": ("mass", 0.001), "kg": ("mass", 1.0), "pound": ("mass", 0.45359237), "ounce": ("mass", 0.028349523125),
    "ml": ("volume", 0.001), "l": ("volume", 1.0), "gallon": ("volume", 3.785411784), "cup": ("volume", 0.2365882365),
}
ALIASES = {
    "millimetre": "mm", "millimeter": "mm", "centimetre": "cm", "centimeter": "cm", "metre": "m", "meter": "m",
    "kilometre": "km", "kilometer": "km", "kms": "km", "inches": "inch", "feet": "foot", "ft": "foot", "yards": "yard",
    "miles": "mile", "gram": "g", "grams": "g", "kilo": "kg", "kilos": "kg", "kilogram": "kg", "kilograms": "kg",
    "pounds": "pound", "lb": "pound", "lbs": "pound", "ounces": "ounce", "oz": "ounce", "millilitre": "ml",
    "milliliter": "ml", "litre": "l", "liter": "l", "litres": "l", "liters": "l", "gallons": "gallon", "cups": "cup",
}


def _unit(name: str) -> str:
    n = name.strip().lower().rstrip(".")
    n = ALIASES.get(n, n)
    if n not in UNITS and n.endswith("s"):
        n = n[:-1]
    if n not in UNITS:
        raise ValueError(name)
    return n


def convert(value: float, src: str, dst: str) -> float:
    """Temperatures are handled separately because they are not a simple ratio."""
    s, d = src.strip().lower(), dst.strip().lower()
    temps = {"c": "c", "celsius": "c", "centigrade": "c", "f": "f", "fahrenheit": "f", "k": "k", "kelvin": "k"}
    if s in temps and d in temps:
        c = value if temps[s] == "c" else (value - 32) * 5 / 9 if temps[s] == "f" else value - 273.15
        return c if temps[d] == "c" else c * 9 / 5 + 32 if temps[d] == "f" else c + 273.15
    a, b = _unit(src), _unit(dst)
    if UNITS[a][0] != UNITS[b][0]:
        raise ValueError(f"{src} and {dst} measure different things")
    return value * UNITS[a][1] / UNITS[b][1]


@tool("convert_units", "Convert a number between units: length, weight, volume or temperature ('5 km to miles', '70 kg in pounds', '98.6 F to C').",
      "Converting", "📏", value=("number", "The number to convert", True), from_unit=("string", "Unit it is in", True),
      to_unit=("string", "Unit to convert to", True))
def convert_units(value: float, from_unit: str, to_unit: str) -> str:
    try:
        out = convert(float(value), from_unit, to_unit)
    except ValueError as e:
        return f"Error: I can't convert that ({e})."
    return f"{value:g} {from_unit} is {out:,.4g} {to_unit}."
