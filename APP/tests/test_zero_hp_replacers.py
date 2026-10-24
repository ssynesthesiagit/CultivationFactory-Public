"""Zero-Hit-Point replacers: one resolves per lethal hit, each limited per scene, after earlier reduction."""
from combat import typed_reactions
from combat.factory_compiler import compile_character
from tests.test_auto_bodya import AN, BODY_REFINING_SHEET, ME, _engine

PATH = "tianxia.path.body_refining.feature."
STAMINA = "resource:core.stamina"


def _owner(*features):
    sheet = {**BODY_REFINING_SHEET, "path_and_subpath": {"path_feature_record_ids": [PATH + "iron_fist", *features]}}
    engine = _engine(compile_character(sheet, actor_id=ME))
    me = engine.state.actors[ME]
    me.resources[STAMINA], me.current_hp = 10, 20
    return engine, me


def _lethal(engine, me):
    pending = typed_reactions.on_damage(engine, me, 999, 0, source_actor_id=AN)
    engine._commit_damage(me, pending, "FORCE", "reaction:test.lethal", AN, None, reaction_depth=0)


def test_blood_pump_works_once_per_scene():
    engine, me = _owner(PATH + "blood_pump")
    _lethal(engine, me)
    assert me.current_hp == 1 and me.resources[STAMINA] == 4
    me.current_hp, me.resources[STAMINA] = 20, 10
    _lethal(engine, me)
    assert me.current_hp <= 0 and me.resources[STAMINA] == 10


def test_only_one_replacer_resolves_for_a_lethal_hit():
    engine, me = _owner(PATH + "blood_pump", "tianxia.subpath.body.iron_shirt.feature.invincible_iron")
    rows = typed_reactions._generic_rows(engine, ME, "drop_to_zero")
    assert len(rows) == 2
    _lethal(engine, me)
    resolved = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and (e.payload or {}).get("kind") == "drop_to_zero"]
    assert me.current_hp == 1 and len(resolved) == 1


def test_blood_pump_keeps_the_printed_choose_one_rider_for_several_replacers():
    # Regression (SYS2 review finding 2): the printed "If several are available, choose one" rider was deleted, so the first
    # replacer in catalog order fired with no choice and no GM adjudication. The printed rider is restored; it is text, and
    # it stays on the typed authority record the engine reads.
    import json
    from pathlib import Path
    authority = json.loads((Path(__file__).resolve().parents[1] / "authority" / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    riders = authority["mechanics"][PATH + "blood_pump"]["riders"]
    assert any("choose one" in rider and "GM-adjudicated" in rider for rider in riders)
