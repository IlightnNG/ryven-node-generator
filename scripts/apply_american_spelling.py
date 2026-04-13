"""Apply American spelling across report/latex/chapters-tex/*.tex (one-off normalisation)."""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1] / "report" / "latex" / "chapters-tex"

# Order: longer phrases first, then longer words before shorter shared stems.
REPLACEMENTS: list[tuple[str, str]] = [
    ("Thesis organisation", "Thesis organization"),
    ("Catalogue", "Catalog"),
    ("Colour", "Color"),
    ("operationalised", "operationalized"),
    ("operationalise", "operationalize"),
    ("organisational", "organizational"),
    ("organisation", "organization"),
    ("behavioural", "behavioral"),
    ("behaviour", "behavior"),
    ("summarised", "summarized"),
    ("summarises", "summarizes"),
    ("summarise", "summarize"),
    ("organised", "organized"),
    ("organise", "organize"),
    ("catalogue", "catalog"),
    ("catalogues", "catalogs"),
    ("colours", "colors"),
    ("colour", "color"),
    ("centres", "centers"),
    ("centred", "centered"),
    ("centre", "center"),
    ("modelled", "modeled"),
    ("modelling", "modeling"),
    ("favourable", "favorable"),
    ("favour", "favor"),
    ("recognised", "recognized"),
    ("recognise", "recognize"),
    ("analysed", "analyzed"),
    ("analyse", "analyze"),
    ("generalise", "generalize"),
    ("travelled", "traveled"),
    ("artefacts", "artifacts"),
    ("artefact", "artifact"),
    ("Optimisers", "Optimizers"),
    ("optimisers", "optimizers"),
]


def main() -> None:
    for path in sorted(ROOT.glob("*.tex")):
        text = path.read_text(encoding="utf-8")
        orig = text
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        if text != orig:
            path.write_text(text, encoding="utf-8", newline="\n")
            print("updated", path.name)


if __name__ == "__main__":
    main()
