import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[1] / "report" / "latex" / "chapters-tex"
text = "\n".join(p.read_text(encoding="utf-8") for p in sorted(root.glob("*.tex")))

brit_words = [
    "summarise",
    "summarises",
    "summarised",
    "behaviour",
    "behavioural",
    "organisation",
    "organisational",
    "organise",
    "organised",
    "colour",
    "colours",
    "centre",
    "centres",
    "centred",
    "modelling",
    "modelled",
    "favour",
    "favourable",
    "recognise",
    "recognised",
    "analyse",
    "analysed",
    "generalise",
    "operationalise",
    "operationalised",
    "defence",
    "catalogue",
    "catalogues",
    "travelled",
    "grey",
    "programme",
]
amer_words = [
    "summarize",
    "summarizes",
    "summarized",
    "behavior",
    "behavioral",
    "organization",
    "organizational",
    "organize",
    "organized",
    "color",
    "colors",
    "center",
    "centers",
    "centered",
    "modeling",
    "modeled",
    "favor",
    "favorable",
    "recognize",
    "recognized",
    "analyze",
    "analyzed",
    "generalize",
    "operationalize",
    "operationalized",
    "defense",
    "catalog",
    "catalogs",
    "traveled",
    "gray",
    "program",
]


def count_word(w: str) -> int:
    return len(re.findall(r"(?i)\b" + re.escape(w) + r"\b", text))


br_total = 0
am_total = 0
print("British forms:")
for w in brit_words:
    n = count_word(w)
    if n:
        print(f"  {w}: {n}")
        br_total += n
print("American forms:")
for w in amer_words:
    n = count_word(w)
    if n:
        print(f"  {w}: {n}")
        am_total += n
print()
print("TOTAL British:", br_total)
print("TOTAL American:", am_total)
