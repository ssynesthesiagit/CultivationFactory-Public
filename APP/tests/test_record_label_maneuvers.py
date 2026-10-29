"""Public synthetic contracts for named modifiers delivered by weapon maneuvers."""
from copy import deepcopy

import pytest

from combat import factory_compiler
from combat.candidate_knowledge import query
from combat.ext import docket_maneuvers
from factory_authoring.record_links import bind_records
from tests import hunt36_support as support

CASES = [(spec["key"], spec["name"]) for spec in docket_maneuvers.MANEUVERS]
BOOST = "TEST_MANEUVER_RIDER"
OTHER = "TEST_UNRELATED_RECORD"
QI = "resource:core.qi"


def _row(rid, name, sphere, modifier=None):
    return {"mechanic_id": rid, "name": name, "sphere_id": sphere, "kind": "talent",
            "activation": {"economy": "passive"}, "effects": [], "riders": [],
            "range": {"kind": "feet", "feet": 5}, "area": None, "duration": {"kind": "instant"},
            "cost": [], **({"modifier": modifier} if modifier else {})}


@pytest.mark.parametrize("key,name", CASES)
def test_source_binding_keeps_native_record_and_explicit_weapon_delivery_ids(key, name):
    records = {"NATIVE": _row("NATIVE", name, "test:sphere"),
               BOOST: _row(BOOST, "Rider", "test:sphere", {
                   "targets": [name], "scope": "named", "when": "hit",
                   "effects": [{"type": "extra_damage", "flat": 2, "damage_types": ["force"]}]})}
    original = deepcopy(records)
    linked = bind_records(records)
    assert linked[BOOST]["modifier"]["target_links"] == [
        {"ids": ["NATIVE", f"maneuver:{key}"], "fallback_ids": ["NATIVE"]}]
    assert records == original
    # An explicit sealed relationship, including an empty one, is authoritative.
    for ids in ([], ["NATIVE"]):
        records[BOOST]["modifier"]["target_links"] = [{"ids": ids, "fallback_ids": []}]
        assert bind_records(records)[BOOST]["modifier"] == records[BOOST]["modifier"]


@pytest.mark.parametrize("key,name", CASES)
def test_weapon_maneuver_variants_survive_renaming_in_human_and_observed_model_menus(
        tmp_path, monkeypatch, key, name):
    spec = next(spec for spec in docket_maneuvers.MANEUVERS if spec["key"] == key)
    training = next(iter(spec["records"]), "TEST_BARRAGE_TRAINING")
    records = {
        training: _row(training, name if spec.get("source_record") else "Training", spec["sphere"]),
        OTHER: _row(OTHER, "Unrelated", spec["sphere"]),
        BOOST: _row(BOOST, "Practice rider", spec["sphere"], {
            "targets": [name], "scope": "named", "when": "hit", "optional": True, "extra_cp": 1,
            "effects": [{"type": "extra_damage", "flat": 2, "damage_types": ["force"]}]})}
    sealed = bind_records(records)
    compile_character = support.compile_character
    original_specs = docket_maneuvers.MANEUVERS
    before_actions = None
    for renamed in (False, True):
        authority = deepcopy(sealed)
        maneuver_label, rider_label = name, "Practice rider"
        if renamed:
            maneuver_label, rider_label = "Renamed maneuver", "Renamed rider"
            authority[training]["name"] = "Renamed training"
            authority[BOOST]["name"] = rider_label
            authority[OTHER]["name"] = name  # a duplicate label must not become a target
        authority_before = deepcopy(authority)
        monkeypatch.setattr(docket_maneuvers, "MANEUVERS", tuple(
            {**row, "name": maneuver_label} if row["key"] == key else row for row in original_specs))

        def compiled(document, *, actor_id, **kwargs):
            document = deepcopy(document)
            document["spheres_and_talents"] = {
                "sphere_record_ids": [spec["sphere"]] if actor_id == support.LEFT else [],
                "learned_talent_record_ids": list(authority) if actor_id == support.LEFT else []}
            return compile_character(document, actor_id=actor_id, typed_authority={"mechanics": authority}, **kwargs)

        monkeypatch.setattr(support, "compile_character", compiled)
        combat, table, mid = support.fight(
            tmp_path / str(renamed), kit={"starting_kit": {"items": [
                {"item_id": "tianxia.mortal.weapon.gong_jian" if key in ("snipe", "barrage")
                 else "tianxia.mortal.weapon.dao"}]}})
        support.turn(combat, table, mid)
        engine = support.reload(combat, mid)
        variants = {aid: action for aid, action in engine.action_catalog.items()
                    if action.owner_id == support.LEFT
                    and (action.parameters.get("typed", {}).get("modifier") or {}).get("id") == BOOST
                    and action.parameters["typed"].get("maneuver") == key}
        assert variants, "the weapon adapter must publish the owned modifier's legal variants"
        assert not any(action.owner_id == support.RIGHT and action.parameters.get("typed", {}).get("maneuver") == key
                       for action in engine.action_catalog.values()), "nonowners must not gain the maneuver"
        assert all(action.display_name.startswith(maneuver_label + ": ")
                   and action.display_name.endswith(" + " + rider_label) for action in variants.values())
        # Compare every variant field, not just names or damage. Only the two
        # declared presentation strings may differ; IDs, costs and effects stay.
        actions = {aid: action.model_dump(mode="json") for aid, action in variants.items()}
        if not renamed:
            before_actions = actions
        else:
            expected = deepcopy(before_actions)
            for action in expected.values():
                action["display_name"] = action["display_name"].replace(name + ": ", maneuver_label + ": ", 1).replace(
                    " + Practice rider", " + " + rider_label)
                typed = action["parameters"]["typed"]
                typed["modifier"]["name"] = rider_label
                hits = [hit for effect in typed["effects"] for hit in effect.get("on_hit", [])
                        if hit.get("source_modifier") == BOOST]
                assert len(hits) == 1 and hits[0]["damage_label"] == "Practice rider"
                hits[0]["damage_label"] = rider_label
            assert actions == expected

        # Additive hit riders on a published plain maneuver use the existing
        # persistent player loadout. Turn the rider on through its real menu,
        # rather than bypassing that decision or assuming it starts enabled.
        families = {action.parameters["typed"].get("attack_modifier_variant") for action in variants.values()}
        controls = [action.source_definition_id for action in engine.action_catalog.values()
                    if (setting := action.parameters.get("attack_modifier_setting"))
                    and setting["family"] in families and setting["modifier"] == BOOST and setting["field"] == "on"]
        for source in controls:
            setting = next(c for c in engine.legal_candidates() if c.source_definition_id == source)
            support.send(combat, table, mid, setting.candidate_id)
            engine = support.reload(combat, mid)
        human = [c for c in engine.legal_candidates() if c.source_definition_id in variants
                 and tuple(c.target_ids) == (support.RIGHT,)]
        assert human, "the variant must be reachable in the human's native menu"
        with query(engine):
            observed = [c for c in engine.legal_candidates() if c.source_definition_id in variants
                        and tuple(c.target_ids) == (support.RIGHT,)]
        assert {c.source_definition_id for c in observed} == {c.source_definition_id for c in human}
        # Submit the model seat's observed native choice without a live model,
        # hidden roster, or Local Auto's separate tactical candidate generation.
        if renamed:
            combat.set_controller_mode(mid, actor_id=support.LEFT, controller_mode="MANUAL_AI_BRIDGE")
        qi_before = engine.state.actors[support.LEFT].resources[QI]
        support.send(combat, table, mid, observed[0].candidate_id)
        loaded = support.reload(combat, mid)
        assert loaded.state.actors[support.LEFT].resources[QI] == qi_before - 1
        assert any(event.event_type == "ATTACK_ROLLED" for event in loaded.events)
        assert authority == authority_before
