"""Manuals are memorized (owner 2026-09-27: "lets assume the manual is all memorized for these characters and the ones i
make"), and the table may give a character a manual ("add cleaarsight to tabik damu, put it on a manual with a few other
things"). combat/table_advance.py memorized, manual_source."""

from combat import table_advance


def _sheet(cl=10) -> dict:
    return {"identity": {"cultivation_level": cl},
            "spheres_and_talents": {"learned_talent_record_ids": ["TAL_DARK_PURE_DARKNESS"], "automatic_sphere_component_record_ids": ["DARK_BASE_DARKNESS"]},
            "training_sources": [{"name": "Dark Gate School", "contents": {
                "manual_collection": {"content_record_bindings": [{"record_id": "TAL_DARK_CREEPING_LETHARGY"}, {"record_id": "TAL_DARK_PURE_DARKNESS"},
                                                                  {"record_id": "TAL_DARK_MIDNIGHT"}]},
                "recorded_art_details": [{"minimum_cl": 5}, {"minimum_cl": 1}, {"minimum_cl": 15}]}}]}


def test_a_manuals_talents_are_known_once_the_character_reaches_their_level():
    out = table_advance.memorized(_sheet(cl=10))
    learned = out["spheres_and_talents"]["learned_talent_record_ids"]
    assert learned == ["TAL_DARK_PURE_DARKNESS", "TAL_DARK_CREEPING_LETHARGY"]  # Midnight is CL 15; Pure Darkness already known
    assert out["memorized_from_manuals"] == ["TAL_DARK_CREEPING_LETHARGY"]
    assert table_advance.memorized(_sheet(cl=1))["spheres_and_talents"]["learned_talent_record_ids"] == ["TAL_DARK_PURE_DARKNESS"]


def test_a_manual_given_at_the_table_is_listed_and_memorized():
    advancement = {"manuals": [{"id": "table.manual.clearsight", "name": "Dark Gate School — Clearsight",
                                "talents": ["TAL_DARK_CLEARSIGHT", "TAL_DARK_LOOMING_DARKNESS"]}]}
    out = table_advance.memorized(table_advance.apply(_sheet(), advancement))
    assert [row["name"] for row in out["training_sources"]] == ["Dark Gate School", "Dark Gate School — Clearsight"]
    assert {"TAL_DARK_CLEARSIGHT", "TAL_DARK_LOOMING_DARKNESS"} <= set(out["spheres_and_talents"]["learned_talent_record_ids"])
