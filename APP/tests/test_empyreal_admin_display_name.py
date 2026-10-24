"""Owner ruling 2026-10-24: "it shouldnt be named cai clan".

The player-visible name of the Qi subpath is "Empyreal Administrator". Internal ids
(tianxia.subpath.qi.cai_clan_empyreal_administrator, pack id, combat/ext/cai_clan.py)
are unchanged and are not checked here.
"""
import json
from pathlib import Path

from non_sphere_authority.owner_subpaths import load_owner_subpaths

APP = Path(__file__).resolve().parents[1]
SUBPATH_ID = "tianxia.subpath.qi.cai_clan_empyreal_administrator"
PLAYER_FILES = [
    APP / "authority/typed_mechanics/player_text.json",
    APP / "authority/typed_mechanics/rules_text.json",
    APP / "authority/Tianxia_Typed_Mechanics_Authority_R1.json",
]


def _cai_clan_hits(text: str) -> bool:
    return "cai clan" in text.lower()


def test_empyreal_administrator_is_the_player_visible_name():
    rows, _ = load_owner_subpaths(APP)
    row = next(r for r in rows if r["canonical_id"] == SUBPATH_ID)
    assert row["display_name"] == "Empyreal Administrator"
    assert "Cai Clan" not in row["aliases"]
    assert "Cai Clan" not in json.dumps(row, ensure_ascii=False)


def test_no_player_visible_text_says_cai_clan():
    rows, _ = load_owner_subpaths(APP)
    row = next(r for r in rows if r["canonical_id"] == SUBPATH_ID)
    owner_texts = [row["display_name"], *row.get("aliases", [])]
    owner_texts += [f["display_name"] for f in row["feature_progression"]]
    owner_texts += [f["source_markdown"] for f in row["feature_progression"]]
    assert not any(_cai_clan_hits(t) for t in owner_texts)
    for path in PLAYER_FILES:
        assert not _cai_clan_hits(path.read_text(encoding="utf-8")), path.name
