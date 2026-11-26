"""DEFDISC1 finding 1: a Defensive Discipline recorded on the sheet governs the real failed save.

The pick is stored on the character sheet (a build choice), the fight is compiled from that sheet, the fight is
cold reloaded from disk, and a real failed save is rolled. The chosen ability is rescued; the other is not.
Nothing is asked in the fight.
"""
import pytest

from character_creation.feature_choices import resolve
from combat.gate5_service import CombatService
from tests.h1_support import script
from tests.h48_table_support import OWNER, fixture

TEMPERED = "tianxia.path.body_refining.feature.tempered_response"
STAMINA = "resource:core.stamina"


@pytest.mark.parametrize("ability,other", [("DEX", "CON"), ("CON", "DEX")])
def test_a_recorded_pick_rescues_its_save_after_a_cold_reload(tmp_path, ability, other):
    picks = resolve([{"canonical_id": TEMPERED, "display_name": "Tempered Response"}],
                    {TEMPERED: ability.lower()}, required=False)
    combat, _table, match_id, _send, _commit = fixture(
        tmp_path, [], seed=f"DEFDISC1-RT-{ability}", path_features=[TEMPERED], feature_build_choices=picks)
    engine = CombatService(combat.source_root, tmp_path)._load_session(match_id).engine
    me = engine.state.actors[OWNER]
    row = next(r for r in engine.typed_reaction_rows[OWNER] if r.get("feature_id") == TEMPERED)
    assert row["abilities"] == [ability]

    me.resources[STAMINA] = 10
    me.turn_flags.clear()
    engine.typed_ask_reactors = frozenset()  # automatic engine saves: nothing is asked in the fight
    script(engine, [8] * 20)
    original_total = 8 + me.saving_throws[ability]
    rescued = engine._roll_save(me, ability, original_total + 1, TEMPERED)
    assert rescued.total == original_total + row["bonus"]

    # The other ability's failed save is never answered while this discipline is recorded.
    me.turn_flags.clear()
    script(engine, [8] * 20)
    untouched = engine._roll_save(me, other, 8 + me.saving_throws[other] + 1, TEMPERED)
    assert untouched.total == 8 + me.saving_throws[other]


@pytest.mark.parametrize("proficient", [False, True])
def test_two_recorded_disciplines_respect_save_proficiency_after_reload(tmp_path, proficient):
    from combat.canonical import canonical_sha256

    indomitable = "tianxia.path.body_refining.feature.indomitable_body"
    features = [{"canonical_id": key, "display_name": key} for key in (TEMPERED, indomitable)]
    picks = resolve(features, {TEMPERED: "dex", indomitable: "con"})

    def configure(bundles):
        bundle = bundles[0]
        bundle["save_proficiencies"] = ["DEX"] if proficient else []
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, _, match_id, _, _ = fixture(
        tmp_path, [], seed=f"BODYRIDERS-{proficient}", path_features=[TEMPERED, indomitable],
        feature_build_choices=picks, bundle_transform=configure)
    engine = CombatService(combat.source_root, tmp_path)._load_session(match_id).engine
    me = engine.state.actors[OWNER]
    row = next(r for r in engine.typed_reaction_rows[OWNER] if r.get("feature_id") == TEMPERED)
    assert set(row["abilities"]) == {"DEX", "CON"}
    me.resources[STAMINA] = 10
    engine.typed_ask_reactors = frozenset()
    for ability, applies in (("DEX", not proficient), ("CON", True), ("STR", False)):
        me.turn_flags.clear()
        script(engine, [8] * 20)
        original = 8 + me.saving_throws[ability]
        result = engine._roll_save(me, ability, original + 1, TEMPERED)
        assert result.total == original + (row["bonus"] if applies else 0)
