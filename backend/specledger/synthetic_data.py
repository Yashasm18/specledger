"""Generate synthetic ground-truth data for evaluation.

Creates a 200-row synthetic ground-truth CSV file focused on industrial
valves (primary category) with some pumps and fittings. All data is
synthetic — no Unilog proprietary information is used.
"""

from __future__ import annotations

import csv
import random
from io import StringIO
from pathlib import Path


# -- Realistic synthetic data pools ----------------------------------------

MANUFACTURERS = [
    "Parker Hannifin", "Emerson Electric", "Honeywell", "Flowserve",
    "Crane Co.", "Watts Water Technologies", "Apollo Valves", "Nibco",
    "Milwaukee Valve", "Kitz Corporation", "Velan", "Pentair",
    "Bray International", "Swagelok", "Victaulic",
]

BRANDS = [
    "Apollo", "Sharpe", "Watts", "NIBCO", "Milwaukee", "Kitz",
    "Swagelok", "Fisher", "Victaulic", "Grundfos",
]

VALVE_TYPES = [
    "Ball Valve", "Gate Valve", "Globe Valve", "Check Valve",
    "Butterfly Valve", "Needle Valve",
]

MATERIALS = [
    "Brass", "Bronze", "Cast Iron", "Carbon Steel",
    "Stainless Steel 304", "Stainless Steel 316", "Ductile Iron", "PVC",
]

SIZES = [
    "1/4", "3/8", "1/2", "3/4", "1", "1-1/4", "1-1/2", "2",
    "2-1/2", "3", "4", "6",
]

SIZE_UOMS = ["in", "in", "in", "in", "mm"]  # mostly inches

PRESSURE_RATINGS = ["150", "200", "300", "400", "600", "800", "1000", "1500"]
PRESSURE_UOMS = ["psi", "psi", "psi", "WOG", "CWP"]

CONNECTION_TYPES = ["NPT", "FNPT", "BSP", "Flanged", "Solder", "Compression", "Threaded"]

TEMPERATURE_RANGES = [
    "-20°F to 350°F", "-40°F to 400°F", "0°F to 250°F",
    "-20°C to 180°C", "0°C to 200°C",
]

CERTIFICATIONS = [
    "NSF/ANSI 61", "NSF/ANSI 372", "UL Listed", "FM Approved",
    "ASME B16.34", "API 607", "MSS SP-110",
]

PUMP_TYPES = ["Centrifugal Pump", "Centrifugal Pump", "Centrifugal Pump"]
FITTING_TYPES = ["Elbow Fitting", "Tee Fitting", "Coupling", "Union", "Reducer", "Flange"]


def generate_ground_truth(num_rows: int = 200, seed: int = 42) -> list[dict]:
    """Generate synthetic ground-truth rows."""
    rng = random.Random(seed)
    rows: list[dict] = []

    for i in range(num_rows):
        row_number = i + 2  # row 1 is header
        manufacturer = rng.choice(MANUFACTURERS)
        brand = rng.choice(BRANDS)

        # 70% valves, 15% pumps, 15% fittings
        roll = rng.random()
        if roll < 0.70:
            category = rng.choice(VALVE_TYPES)
        elif roll < 0.85:
            category = rng.choice(PUMP_TYPES)
        else:
            category = rng.choice(FITTING_TYPES)

        material = rng.choice(MATERIALS)
        size = rng.choice(SIZES)
        size_uom = rng.choice(SIZE_UOMS)
        pressure = rng.choice(PRESSURE_RATINGS)
        pressure_uom = rng.choice(PRESSURE_UOMS)
        connection = rng.choice(CONNECTION_TYPES)
        temp_range = rng.choice(TEMPERATURE_RANGES)

        part_number = f"{manufacturer[:3].upper()}-{category[:2].upper()}-{size.replace('/', '')}-{i+1:04d}"
        description = f"{size} {size_uom} {material} {category}, {pressure} {pressure_uom}"

        # Some fields intentionally missing (5-10% per field)
        def maybe_missing(value: str) -> str | None:
            return None if rng.random() < 0.07 else value

        rows.append({
            "row_number": row_number,
            "manufacturer": maybe_missing(manufacturer),
            "brand": maybe_missing(brand),
            "category": category,
            "part_number": part_number,
            "description": description,
            "material": maybe_missing(material),
            "size": maybe_missing(size),
            "size_uom": maybe_missing(size_uom),
            "pressure_rating": maybe_missing(pressure),
            "pressure_uom": maybe_missing(pressure_uom),
            "connection_type": maybe_missing(connection),
            "temperature_range": maybe_missing(temp_range),
        })

    return rows


def write_ground_truth_csv(path: str | Path, rows: list[dict] | None = None) -> Path:
    """Write ground-truth data to CSV. Returns the path."""
    if rows is None:
        rows = generate_ground_truth()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with target.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (v if v is not None else "") for k, v in row.items()})
    return target


def generate_input_csv(ground_truth: list[dict], seed: int = 42) -> list[dict]:
    """Generate messy input data from ground truth.

    Simulates real-world catalogue data quality issues:
    - Manufacturer names with variations/typos
    - Extra whitespace
    - Different cases
    - Some additional placeholder values
    """
    rng = random.Random(seed)
    input_rows: list[dict] = []

    MFG_VARIATIONS = {
        "Parker Hannifin": ["Parker Hannifin Corp", "PARKER HANNIFIN", "Parker", "Parker-Hannifin"],
        "Emerson Electric": ["Emerson Electric Co.", "EMERSON", "Emerson", "Emerson Electric Co"],
        "Honeywell": ["Honeywell International", "HONEYWELL", "Honeywell Inc"],
        "Flowserve": ["Flowserve Corporation", "FLOWSERVE", "Flowserve Corp"],
        "Crane Co.": ["Crane", "CRANE", "Crane Company"],
        "Watts Water Technologies": ["Watts", "WATTS", "Watts Water"],
        "Apollo Valves": ["Apollo", "APOLLO", "Apollo Valve"],
        "Nibco": ["NIBCO", "NIBCO Inc", "Nibco"],
        "Milwaukee Valve": ["Milwaukee", "MILWAUKEE VALVE"],
        "Kitz Corporation": ["Kitz", "KITZ", "KITZ Corp"],
        "Velan": ["Velan Inc", "VELAN"],
        "Pentair": ["Pentair plc", "PENTAIR"],
        "Bray International": ["Bray", "BRAY"],
        "Swagelok": ["Swagelok Company", "SWAGELOK"],
        "Victaulic": ["Victaulic Company", "VICTAULIC"],
    }

    MATERIAL_VARIATIONS = {
        "Brass": ["brass", "BRASS", "Brass"],
        "Bronze": ["bronze", "BRONZE"],
        "Cast Iron": ["cast iron", "CI", "Cast Iron"],
        "Carbon Steel": ["carbon steel", "CS", "Carbon Steel"],
        "Stainless Steel 304": ["304 SS", "SS304", "304 Stainless Steel", "304 Stainless"],
        "Stainless Steel 316": ["316 SS", "SS316", "316 Stainless Steel", "316 Stainless"],
        "Ductile Iron": ["ductile iron", "DI", "Ductile Iron"],
        "PVC": ["pvc", "PVC"],
    }

    for gt_row in ground_truth:
        mfg = gt_row.get("manufacturer")
        if mfg and mfg in MFG_VARIATIONS:
            mfg = rng.choice(MFG_VARIATIONS[mfg])

        mat = gt_row.get("material")
        if mat and mat in MATERIAL_VARIATIONS:
            mat = rng.choice(MATERIAL_VARIATIONS[mat])

        # Simulate some placeholder values (about 3% of fields)
        def maybe_placeholder(value):
            if value is None:
                return rng.choice(["", "N/A", "--", "n/a", None])
            if rng.random() < 0.03:
                return rng.choice(["N/A", "--", "n/a"])
            return value

        input_rows.append({
            "Manufacturer": maybe_placeholder(mfg),
            "Brand": maybe_placeholder(gt_row.get("brand")),
            "Category": gt_row.get("category", ""),
            "Part Number": gt_row.get("part_number", ""),
            "Description": gt_row.get("description", ""),
            "Material": maybe_placeholder(mat),
            "Size": maybe_placeholder(gt_row.get("size")),
            "UOM": maybe_placeholder(gt_row.get("size_uom")),
            "Pressure Rating": maybe_placeholder(gt_row.get("pressure_rating")),
            "Pressure UOM": maybe_placeholder(gt_row.get("pressure_uom")),
            "Connection Type": maybe_placeholder(gt_row.get("connection_type")),
            "Temperature Range": maybe_placeholder(gt_row.get("temperature_range")),
        })

    return input_rows


if __name__ == "__main__":
    gt = generate_ground_truth(200)
    write_ground_truth_csv("data/ground_truth/synthetic_200_valves.csv", gt)
    print(f"Generated {len(gt)} ground-truth rows")

    input_data = generate_input_csv(gt)
    # Write input CSV
    from pathlib import Path
    input_path = Path("data/ground_truth/synthetic_200_input.csv")
    fieldnames = list(input_data[0].keys())
    with input_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in input_data:
            writer.writerow({k: (v if v is not None else "") for k, v in row.items()})
    print(f"Generated {len(input_data)} input rows")
