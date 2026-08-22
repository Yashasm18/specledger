"""Regenerate the sample datasheets used to demonstrate document linking.

These are **fixtures, not manufacturer publications**, and they say so on
their own first line. Every specification in them is traceable to the
catalogue row it accompanies — the descriptions in the shipped datasets
already state the size, pressure, voltage and amperage below — so the
demonstration connects two things that were both already true rather than
introducing an invented value to make the feature look good.

Each file names a part that exists in a catalogue this repository ships,
so the datasheet-to-row link can be reproduced from a clean checkout:

  sample_datasheet_apollo_70-104-01.pdf   -> data/samples/01_industrial_distributor.csv
  sample_datasheet_leviton_R02D215P1RW.pdf-> data/samples/01_industrial_distributor.csv
  sample_datasheet_prime_TNOCD002.pdf     -> the official 1,000-row challenge dataset

Run: python scripts/build_sample_datasheets.py
"""

from pathlib import Path

import pymupdf

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "samples"

DISCLAIMER = (
    "SPECLEDGER SAMPLE DATASHEET - synthetic fixture, not a manufacturer publication."
)

SHEETS: list[tuple[str, list[str]]] = [
    (
        "sample_datasheet_apollo_70-104-01.pdf",
        [
            DISCLAIMER,
            "Values below match the catalogue description of this part.",
            "",
            "BRONZE BALL VALVE - 70-100 SERIES",
            "",
            "Part Number: 70-104-01",
            "Size: 1/2 in",
            "Pressure Rating: 600 WOG",
            "Body Material: Bronze ASTM B584",
            "Connection Type: NPT Threaded",
            "",
            "Matches row 70-104-01 of data/samples/01_industrial_distributor.csv",
        ],
    ),
    (
        "sample_datasheet_leviton_R02D215P1RW.pdf",
        [
            DISCLAIMER,
            "Values below match the catalogue description of this part.",
            "",
            "COMMERCIAL DUPLEX RECEPTACLE",
            "",
            "Catalog Number: R02D215P1RW",
            "Amperage Rating: 15 A",
            "Voltage Rating: 125 V",
            "",
            "Matches row R02D215P1RW of data/samples/01_industrial_distributor.csv",
        ],
    ),
    (
        "sample_datasheet_prime_TNOCD002.pdf",
        [
            DISCLAIMER,
            "The voltage below is the one the challenge dataset itself states",
            "for this part. Nothing here was invented to fill a field.",
            "",
            "OUTDOOR TIMER",
            "",
            "Part Number: TNOCD002",
            "Voltage Rating: 125 V",
            "",
            "Matches row TNOCD002 of the official 1,000-row challenge dataset,",
            "so this one demonstrates the link inside Unilog CX1 Master.",
        ],
    ),
]


def build() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, lines in SHEETS:
        document = pymupdf.open()
        page = document.new_page()
        y = 60
        for line in lines:
            if line:
                page.insert_text((56, y), line, fontsize=10.5)
            y += 17
        path = OUTPUT_DIR / filename
        document.save(path)
        document.close()
        print(f"wrote {path.relative_to(OUTPUT_DIR.parent.parent)} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
