"""Seeded ancient-Chinese names by Dao type (owner 2026-09-27: "a random name generator with seeds by dao type with
variations and base it on ancient chinese names ... for character creation and other naming"; the local AI kept
naming everyone "Lingfeng").

The data -- surnames (single and compound), the given-name characters of each of the eight trigrams the Sphere Dao
system uses (factory_authoring/sphere_dao.py), themed characters for elements and arts, and Daoist epithets -- is the
owner-editable authority/names/Tianxia_Name_Generator_R1.json; each character carries its hanzi and meaning. The same
seed and options always give the same name. A name comes in one of several shapes: "Han Xiao" (classic), "Lin Zhaoyue"
(double), "Murong Lanxi" (compound surname), "Qingxu Zi" (a Daoist name), "Zhao Yun, courtesy Zilong" (courtesy).
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

DATA = Path(__file__).resolve().parents[1] / "authority" / "names" / "Tianxia_Name_Generator_R1.json"
TRIGRAMS = ("qian", "dui", "li", "zhen", "xun", "kan", "gen", "kun")
_IMAGES = {"heaven": "qian", "lake": "dui", "fire": "li", "thunder": "zhen", "wind": "xun", "water": "kan", "mountain": "gen", "earth": "kun"}


@lru_cache(maxsize=4)
def _load(mtime: float) -> dict[str, Any]:
    return json.loads(DATA.read_text(encoding="utf-8"))


def data() -> dict[str, Any]:
    return _load(DATA.stat().st_mtime)


def dao_key(value: Any) -> str | None:
    """A trigram key from a key ("kan"), an image ("Water") or a Dao record ({"natural": {"key": "kan"}, ...})."""
    if isinstance(value, dict):
        for key in ("natural", "trigram", "upper"):
            inner = value.get(key)
            found = dao_key(inner.get("key") if isinstance(inner, dict) else inner)
            if found:
                return found
        return None
    text = str(value or "").strip().lower()
    return text if text in TRIGRAMS else _IMAGES.get(text)


def themes_for(words: Iterable[str]) -> list[str]:
    """Themed pools for Sphere names ("Ash", "Lightning", "Beastmastery") or motifs."""
    table = data()["sphere_themes"]
    out: list[str] = []
    for word in words:
        for part in str(word or "").lower().replace("-", " ").split():
            theme = table.get(part)
            if theme and theme not in out:
                out.append(theme)
    return out


class _Dice:
    def __init__(self, seed: str, salt: str):
        self.seed, self.salt, self.count = str(seed), salt, 0

    def roll(self, sides: int) -> int:
        self.count += 1
        digest = hashlib.sha256(f"tianxia.names.v1|{self.seed}|{self.salt}|{self.count}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big") % max(1, sides)

    def pick(self, values: Sequence[Any]) -> Any:
        return values[self.roll(len(values))]


def _given_pools(dao: str | None, themes: Sequence[str], lean: str | None) -> tuple[list[list[str]], list[list[str]]]:
    """(the Dao's and themes' characters, everything including the virtues): a name's first given character always
    carries the Dao or theme; a second one may also be a virtue."""
    table = data()
    primary: list[list[str]] = []
    if dao:
        primary += table["trigrams"][dao]["chars"] * 2  # the Dao weighs most
    for theme in themes:
        primary += table["themes"].get(theme, [])
    if not primary:
        primary = [row for trigram in TRIGRAMS for row in table["trigrams"][trigram]["chars"]]
    full = primary + table["virtues"]
    if lean in ("f", "m"):
        primary = [row for row in primary if row[3] in ("", lean)] or primary
        full = [row for row in full if row[3] in ("", lean)] or full
    return primary, full


def generate(seed: Any, *, dao: Any = None, themes: Sequence[str] = (), style: str | None = None, lean: str | None = None,
             avoid: Iterable[str] = (), salt: str = "") -> dict[str, Any]:
    """One name for ``seed``: {"name", "hanzi", "meaning", "style", "dao", "seed"}. ``avoid`` names (the library's) are
    skipped by trying the next variation of the same seed."""
    taken = {str(name).strip().lower() for name in avoid if name}
    for attempt in range(40):
        row = _one(str(seed), dao_key(dao), list(themes), style, lean if lean in ("f", "m") else None, f"{salt}|{attempt}")
        if row["name"].lower() not in taken and row["name"].split(",")[0].lower() not in taken:
            return row
    return row


def _one(seed: str, dao: str | None, themes: list[str], style: str | None, lean: str | None, salt: str) -> dict[str, Any]:
    table = data()
    dice = _Dice(seed, salt)
    styles = table["styles"]
    if style not in styles:
        ticket = dice.roll(sum(styles.values()))
        for name, weight in styles.items():
            if ticket < weight:
                style = name
                break
            ticket -= weight
    primary, full = _given_pools(dao, themes, lean)
    surname_syllables: set[str] = set()

    def given(chars: int) -> tuple[str, str, list[str]]:
        picked: list[list[str]] = []
        for _ in range(200):
            if len(picked) >= chars:
                break
            row = dice.pick(primary if not picked else full)
            if all(row[0] != other[0] for other in picked) and row[0].lower() not in surname_syllables:
                picked.append(row)
        surname_syllables.update(row[0].lower() for row in picked)  # a courtesy name doesn't repeat the given name
        return "".join(row[0] for row in picked).capitalize(), "".join(row[1] for row in picked), [row[2] for row in picked]

    if style == "daoist":
        text, hanzi, meaning = given(2)
        suffix = dice.pick(table["daoist_suffixes"])
        return {"name": f"{text} {suffix[0]}", "hanzi": hanzi + suffix[1], "meaning": f"{' and '.join(meaning)}, {suffix[2]}",
                "style": style, "dao": dao, "seed": seed}
    if style == "compound":
        surname, surname_hanzi = dice.pick(table["compound_surnames"])
    else:
        surname = dice.pick(table["surnames"])
        surname_hanzi = table["surnames_hanzi"].get(surname, "")
    surname_syllables.add(surname.lower())
    text, hanzi, meaning = given(1 if style == "classic" or (style == "compound" and dice.roll(2)) else 2)
    row = {"name": f"{surname} {text}", "hanzi": surname_hanzi + hanzi, "meaning": " and ".join(meaning), "style": style, "dao": dao, "seed": seed}
    if style == "courtesy":
        courtesy, courtesy_hanzi, courtesy_meaning = given(1)
        row["name"] += f", courtesy Zi{courtesy.lower()}"
        row["hanzi"] += f"，字子{courtesy_hanzi}"
        row["meaning"] += f"; courtesy name: {courtesy_meaning[0]}"
    return row


def suggestions(seed: Any, count: int = 5, **options: Any) -> list[dict[str, Any]]:
    """``count`` different names from one seed (different shapes, no repeats)."""
    out: list[dict[str, Any]] = []
    avoid = set(options.pop("avoid", ()) or ())
    for index in range(count * 3):
        row = generate(seed, avoid=avoid, salt=f"s{index}", **options)
        if row["name"] not in avoid:
            out.append(row)
            avoid.add(row["name"])
        if len(out) >= count:
            break
    return out
