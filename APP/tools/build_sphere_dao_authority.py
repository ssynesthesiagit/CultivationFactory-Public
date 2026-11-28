"""Build the Aspect Dao master list from its markdown sources.

Sources (``authority/sphere_dao/``):
- the owner's Aspect Dao Marker Catalogue and Aspect-Trigram Profile Catalogue
  (First Pass, 70 Aspects of an earlier list), copied verbatim from Google Docs;
- the R1 drafts for the current Aspects those catalogues do not cover.

Output: ``authority/Tianxia_Sphere_Dao_Authority_R1.json``, one profile per
current Aspect (canonical id), plus the eight trigrams and the 64 hexagrams.
Re-run after any source changes and update the pin in
``factory_authoring/sphere_dao.py``.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from catalog_authority.sphere_identity import resolve_sphere_id, sphere_heading_label
from tools.aspect_terms import TERMS

SOURCE_DIR = APP / "authority/sphere_dao"
MARKERS = SOURCE_DIR / "Tianxia_Sphere_Dao_Marker_Catalogue_First_Pass.md"
TRIGRAM_PROFILES = SOURCE_DIR / "Tianxia_Sphere_Trigram_Profile_Catalogue_Draft_v1.md"
DRAFTS = SOURCE_DIR / "Tianxia_Sphere_Dao_Drafts_R1.md"
MATRIX = APP / "catalog_authority/cat3/generated/matrices/talent_prerequisite_matrix.json"
OUTPUT = APP / "authority/Tianxia_Sphere_Dao_Authority_R1.json"

# Owner ruling 2026-09-24: these First Pass names are today's Aspects.
RENAMES = {
    "Alchemy & Pill Forging": "Alchemy",
    "Beast Taming": "Beastmastery",
    "Cold": "Ice",
    "Darkness": "Dark",
    "Wood": "Verdant Growth",
    "War": "Warleader",
    "Reeling Immortal": "Drunken Style",
    "Demonic Cultivation": "Daemonic Cultivation",
}

# Order: Fu Xi (Earlier Heaven).  Lines bottom to top, 1 = yang.
TRIGRAMS = {
    "qian": {"name": "Qian", "image": "Heaven", "symbol": "☰", "lines": [1, 1, 1],
             "meaning": "force, mandate, initiative, command, creative pressure"},
    "dui": {"name": "Dui", "image": "Lake-Marsh", "symbol": "☱", "lines": [1, 1, 0],
            "meaning": "joy, exchange, speech, openness, temptation, community"},
    "li": {"name": "Li", "image": "Fire", "symbol": "☲", "lines": [1, 0, 1],
           "meaning": "clarity, visibility, attachment, illumination, exposure, what clings"},
    "zhen": {"name": "Zhen", "image": "Thunder", "symbol": "☳", "lines": [1, 0, 0],
             "meaning": "shock, awakening, first movement, crisis, disruption"},
    "xun": {"name": "Xun", "image": "Wind-Wood", "symbol": "☴", "lines": [0, 1, 1],
            "meaning": "subtle entry, gradual influence, persuasion, growth, penetration"},
    "kan": {"name": "Kan", "image": "Water", "symbol": "☵", "lines": [0, 1, 0],
            "meaning": "peril, abyss, hidden danger, fear, depth, uncertainty"},
    "gen": {"name": "Gen", "image": "Mountain", "symbol": "☶", "lines": [0, 0, 1],
            "meaning": "stopping, boundary, stillness, restraint, gate, refusal"},
    "kun": {"name": "Kun", "image": "Earth", "symbol": "☷", "lines": [0, 0, 0],
            "meaning": "receptivity, support, service, bearing, nourishment, humility"},
}

# King Wen number by (upper, lower) trigram, with the Wilhelm name.
_KING_WEN = {
    "qian": {"qian": 1, "zhen": 25, "kan": 6, "gen": 33, "kun": 12, "xun": 44, "li": 13, "dui": 10},
    "zhen": {"qian": 34, "zhen": 51, "kan": 40, "gen": 62, "kun": 16, "xun": 32, "li": 55, "dui": 54},
    "kan": {"qian": 5, "zhen": 3, "kan": 29, "gen": 39, "kun": 8, "xun": 48, "li": 63, "dui": 60},
    "gen": {"qian": 26, "zhen": 27, "kan": 4, "gen": 52, "kun": 23, "xun": 18, "li": 22, "dui": 41},
    "kun": {"qian": 11, "zhen": 24, "kan": 7, "gen": 15, "kun": 2, "xun": 46, "li": 36, "dui": 19},
    "xun": {"qian": 9, "zhen": 42, "kan": 59, "gen": 53, "kun": 20, "xun": 57, "li": 37, "dui": 61},
    "li": {"qian": 14, "zhen": 21, "kan": 64, "gen": 56, "kun": 35, "xun": 50, "li": 30, "dui": 38},
    "dui": {"qian": 43, "zhen": 17, "kan": 47, "gen": 31, "kun": 45, "xun": 28, "li": 49, "dui": 58},
}
_HEXAGRAM_NAMES = [
    "", "Qian — The Creative", "Kun — The Receptive", "Zhun — Difficulty at the Beginning", "Meng — Youthful Folly",
    "Xu — Waiting", "Song — Conflict", "Shi — The Army", "Bi — Holding Together",
    "Xiao Chu — The Taming Power of the Small", "Lü — Treading", "Tai — Peace", "Pi — Standstill",
    "Tong Ren — Fellowship with Men", "Da You — Possession in Great Measure", "Qian — Modesty", "Yu — Enthusiasm",
    "Sui — Following", "Gu — Work on What Has Been Spoiled", "Lin — Approach", "Guan — Contemplation",
    "Shi He — Biting Through", "Bi — Grace", "Bo — Splitting Apart", "Fu — Return",
    "Wu Wang — Innocence", "Da Chu — The Taming Power of the Great", "Yi — The Corners of the Mouth",
    "Da Guo — Preponderance of the Great", "Kan — The Abysmal", "Li — The Clinging", "Xian — Influence",
    "Heng — Duration", "Dun — Retreat", "Da Zhuang — The Power of the Great", "Jin — Progress",
    "Ming Yi — Darkening of the Light", "Jia Ren — The Family", "Kui — Opposition", "Jian — Obstruction",
    "Xie — Deliverance", "Sun — Decrease", "Yi — Increase", "Guai — Breakthrough", "Gou — Coming to Meet",
    "Cui — Gathering Together", "Sheng — Pushing Upward", "Kun — Oppression", "Jing — The Well",
    "Ge — Revolution", "Ding — The Cauldron", "Zhen — The Arousing", "Gen — Keeping Still",
    "Jian — Development", "Gui Mei — The Marrying Maiden", "Feng — Abundance", "Lü — The Wanderer",
    "Xun — The Gentle", "Dui — The Joyous", "Huan — Dispersion", "Jie — Limitation", "Zhong Fu — Inner Truth",
    "Xiao Guo — Preponderance of the Small", "Ji Ji — After Completion", "Wei Ji — Before Completion",
]

_FIELD_KEYS = {
    "Reality Principle": "reality_principle", "Dao Trail": "dao_trail", "Trial Signs": "trial_signs",
    "Shadow": "shadow", "Keep Distinct From": "keep_distinct_from", "Path Pull": "path_pull",
    "Natural Trigrams": "natural_trigrams", "Testing Trigrams": "testing_trigrams",
    "Shadow Trigrams": "shadow_trigrams", "Dao Verbs": "dao_verbs", "GM Read": "gm_read", "Basis": "basis",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _entries(text: str, heading: str) -> dict[str, tuple[str, dict[str, str]]]:
    """Split entries by heading; numbered catalogues retain the entry number."""
    headings = list(re.finditer(heading, text, flags=re.M))
    entries = {}
    for index, match in enumerate(headings):
        name = match["name"].strip()
        key = match.groupdict().get("number", name)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        fields = {}
        for line in text[match.end():end].splitlines():
            field = re.match(r"^([A-Z][A-Za-z ]+):\s*(.+)$", line.strip())
            if field and field[1] in _FIELD_KEYS:
                fields[_FIELD_KEYS[field[1]]] = field[2].strip()
        if fields:
            if key in entries:
                raise SystemExit(f"Duplicate Dao profile entry: {key!r}")
            entries[key] = (name, fields)
    return entries


def _trigrams(value: str) -> list[dict[str, object]]:
    rows = []
    for part in value.rstrip(".").split(","):
        match = re.match(r"^\s*(Qian|Kun|Zhen|Xun|Kan|Li|Gen|Dui)\b(?:\s*/\s*[\w-]+)?(?:\s+Line\s+(\d))?\s*$", part.strip())
        if not match:
            raise SystemExit(f"Unreadable trigram entry: {part!r}")
        rows.append({"trigram": match.group(1).lower(), "line": int(match.group(2)) if match.group(2) else None})
    return rows


def _profile(fields: dict[str, str], *, status: str, sources: dict[str, str]) -> dict[str, object]:
    missing = [key for key in _FIELD_KEYS.values() if key != "basis" and key not in fields]
    if missing:
        raise SystemExit(f"Profile is missing {missing}: {sources}")
    profile: dict[str, object] = {"status": status, "source_names": sources}
    for key in ("reality_principle", "dao_trail", "trial_signs", "shadow", "keep_distinct_from", "path_pull", "gm_read"):
        profile[key] = fields[key]
    for key in ("natural_trigrams", "testing_trigrams", "shadow_trigrams"):
        profile[key] = _trigrams(fields[key])
    profile["dao_verbs"] = [verb.strip() for verb in fields["dao_verbs"].rstrip(".").split(",") if verb.strip()]
    if "basis" in fields:
        profile["basis"] = fields["basis"]
    return profile


def build() -> dict[str, object]:
    names = {}
    for row in json.loads(MATRIX.read_text(encoding="utf-8")):
        for predicate in row.get("typed_prerequisites") or []:
            if predicate.get("kind") == "owning_sphere" and predicate.get("target_id"):
                names[predicate["target_id"]] = predicate["display_name"]

    numbered = r"^(?P<number>\d+)\.[ \t]+(?P<name>.+)$"
    markers = _entries(MARKERS.read_text(encoding="utf-8"), numbered)
    trigram_profiles = _entries(TRIGRAM_PROFILES.read_text(encoding="utf-8"), numbered)
    drafts = _entries(DRAFTS.read_text(encoding="utf-8"), r"^##[ \t]+(?P<name>.+)$")
    if len(markers) != 70 or markers.keys() != trigram_profiles.keys():
        raise SystemExit(f"Expected the same 70 numbered owner profiles, found {len(markers)} markers"
                         f" and {len(trigram_profiles)} trigram profiles")

    # The catalogue's retired entries are not equivalent to modern Aspects,
    # even if CAT1 has an old alias with the same spelling (e.g. Fencing).
    current_labels = {*TERMS["names"], *TERMS["names"].values(), *TERMS["short_lists"],
                      *TERMS["short_lists"].values()}
    spheres: dict[str, dict[str, object]] = {}
    retired: dict[str, dict[str, object]] = {}
    for number, (heading, marker) in markers.items():
        trigram_name, trigram = trigram_profiles[number]
        # The first-pass catalogues share entry numbers, even for entries
        # retired from the canonical registry. Their title spellings may differ.
        marker_name = sphere_heading_label(heading) or trigram_name
        profile = _profile({**marker, **trigram}, status="owner",
                           sources={"marker_catalogue": marker_name, "trigram_catalogue": trigram_name})
        current = RENAMES.get(trigram_name, trigram_name)
        aspect_id = resolve_sphere_id(current) if current in current_labels else None
        if aspect_id in names:
            if aspect_id in spheres:
                raise SystemExit(f"Duplicate owner profile for {aspect_id}")
            spheres[aspect_id] = {"name": names[aspect_id], **profile}
        else:
            # Preserve old keys for retired profiles, which have no registry ID.
            retired[trigram_name] = {"name": trigram_name, **profile}
    for name, fields in drafts.values():
        aspect_id = resolve_sphere_id(name)
        if aspect_id not in names:
            raise SystemExit(f"Draft for an unknown Aspect: {name}")
        if aspect_id in spheres:
            raise SystemExit(f"Draft duplicates an owner profile: {name}")
        spheres[aspect_id] = {"name": names[aspect_id], **_profile(fields, status="draft", sources={"drafts_r1": name})}
    missing = sorted(set(names) - spheres.keys())
    if missing:
        raise SystemExit(f"Aspects without a profile: {missing}")

    hexagrams = {
        f"{upper}/{lower}": {"number": number, "name": _HEXAGRAM_NAMES[number], "upper": upper, "lower": lower}
        for upper, row in _KING_WEN.items() for lower, number in row.items()
    }
    if sorted(item["number"] for item in hexagrams.values()) != list(range(1, 65)):
        raise SystemExit("The hexagram table is not a permutation of 1-64")
    return {
        "schema": "TianxiaFoundry.SphereDaoAuthority.v1",
        "release": "R1",
        "doctrine": {
            "sphere": "What truth of reality is this cultivator becoming sensitive to?",
            "yijing": "What configuration of change is placing that truth under pressure right now?",
            "dao": "The pattern that appears over time.",
        },
        "weighting": {
            "formula": "sqrt(talents_in_sphere + 1)",
            "owner_ruling": "2026-09-24: investment, softened; knowing a Sphere is its first mark.",
            "mark_scale": {"1": "hint", "2": "tendency", "3": "trail", "5": "strong resonance"},
        },
        "sources": [
            {"file": MARKERS.name, "sha256": _sha(MARKERS), "owner_doc_id": "1vI2Ury0FL2Xf5RygvYyEMo5BGrAJHv7RUL1BY6pj4ko", "status": "owner"},
            {"file": TRIGRAM_PROFILES.name, "sha256": _sha(TRIGRAM_PROFILES), "owner_doc_id": "1WHGyGvWzd0MY02FKjwkzN77r21lc8SxrcN7Bp0yGbXo", "status": "owner"},
            {"file": DRAFTS.name, "sha256": _sha(DRAFTS), "owner_doc_id": None, "status": "draft"},
        ],
        "framework_doc_id": "1f1dSDdJe96j8sAMa74z06jOSKebZtTE_Tq6tzg4wfug",
        "renames": RENAMES,
        "trigrams": TRIGRAMS,
        "hexagrams": dict(sorted(hexagrams.items())),
        "spheres": dict(sorted(spheres.items())),
        "retired_owner_profiles": dict(sorted(retired.items())),
    }


def main() -> int:
    data = build()
    payload = (json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n").encode("utf-8")
    OUTPUT.write_bytes(payload)
    counts = {"owner": 0, "draft": 0}
    for row in data["spheres"].values():
        counts[row["status"]] += 1
    print(f"{OUTPUT.relative_to(APP)} sha256={hashlib.sha256(payload).hexdigest()} spheres={len(data['spheres'])} {counts} retired={len(data['retired_owner_profiles'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
