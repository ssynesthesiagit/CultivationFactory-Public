"""Qi Armor through table persistence and the sealed portable runtime.

Synthetic saves live only in pytest's disk-backed task directory. Historical
bundles retain their stored +3; new bundles read the owner's current +5 rule.
"""
import json

import pytest

from combat.canonical import canonical_sha256
from combat.character_adapter_service import CharacterCombatAdapter
from combat.character_runtime_adapter import (
    CharacterCombatRuntimeAdapter, CharacterCombatRuntimeEngine,
    CharacterRuntimeBundle, RuntimeResourceInitialization, SOURCE_ACTOR_ID,
    dummy_actor_template,
)
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, Position, ReactionDecision
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.test_lock2_persistence import act

QI_ARMOR = "tianxia.path.qi_cultivation.feature.qi_armor"
QI = "resource:core.qi"
ATTACKER, DEFENDER = "actor:factory.qa5f-attacker", "actor:factory.qa5f-defender"
REACTION = "reaction:qi.qi_armor"


@pytest.mark.parametrize("cl,cost", [(5, 2), (10, 1)])
@pytest.mark.parametrize("bonus", [5, 3], ids=["current", "stored-before-edit"])
def test_qi_armor_table_commit_reload_and_next_turn_expiry(tmp_path, monkeypatch, cl, cost, bonus):
    original = Gate4ControllerEngine._resolve_attack_spec

    def ordinary_hit(engine, attacker, target, spec, *args, **kwargs):
        # The Factory offers AC reactions only when they can prevent the hit.
        # +4 over base AC requires current +5; +2 lets historical +3 activate.
        natural = target.armor_class + bonus - 1 - spec["attack_bonus"]
        assert 1 < natural < 20
        script(engine, [natural, *([1] * 40)])
        return original(engine, attacker, target, spec, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", ordinary_hit)
    bundles = [compile_character(sheet(["INK_BASE_INK_LASH"], cl=5), actor_id=ATTACKER),
               compile_character(sheet([QI_ARMOR], cl=cl), actor_id=DEFENDER)]
    row = next(row for row in bundles[1]["typed_reactions"] if row["feature_id"] == QI_ARMOR)
    assert row["ac"] == 5 and row["cost"] == cost
    if bonus == 3:
        row["ac"] = 3  # Public synthetic historical bundle, never a private save.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ATTACKER, DEFENDER], {ATTACKER: "team:a", DEFENDER: "team:b"},
        {ATTACKER: {"x": 2, "y": 6}, DEFENDER: {"x": 8, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ATTACKER], [DEFENDER],
        control_modes={ATTACKER: "MANUAL", DEFENDER: "MANUAL"},
        match_seed="QA5F-PERSISTENCE", display_name="Qi Armor regression", maximum_rounds=20,
    )["match_id"]
    for _ in range(2):
        if table.state(mid)["menu"]["actor_id"] == ATTACKER:
            break
        assert act(table, mid, "end")["status"] == "COMMITTED"
    state = table.state(mid)
    engine = combat._load_session(mid).engine
    before = engine.state.actors[DEFENDER]
    hp, qi = before.current_hp, before.resources[QI]
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.startswith("Ink Lash") and c.target_ids == (DEFENDER,))

    def submit(reactions):
        return table.act(mid, candidate.candidate_id, state["menu"]["decision_id"],
                         state["menu"]["state_version"], state["last_sequence"], reactions)

    result = submit([])
    if result["status"] == "REACTION_REQUIRED":
        assert result["reaction"]["reaction"] == "Qi Armor"
        result = submit([{**result["reaction"]["context"], "selection": "USE"}])
    assert result["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    loaded = fresh._load_session(mid)
    defender = loaded.engine.state.actors[DEFENDER]
    [modifier] = [m for m in defender.modifiers.values() if m.source_definition_id == QI_ARMOR]
    assert modifier.value == bonus and isinstance(modifier.value, int)
    assert modifier.expires_on == "START_OF_SELF_NEXT_TURN"
    assert loaded.engine._ac_modifier(defender) == bonus
    assert defender.resources[QI] == qi - cost and not defender.reaction_available
    boundary = fresh.history(mid)["boundaries"][-1]
    [reaction] = [e["payload"] for e in boundary["events"]
                  if e["event_type"] == "REACTION_RESOLVED" and e["source_definition_id"] == QI_ARMOR]
    [attack] = [e["payload"] for e in boundary["events"] if e["event_type"] == "ATTACK_ROLLED"]
    assert attack["provisional_hit"] and attack["total"] - attack["target_ac"] == bonus - 1
    assert {key: reaction[key] for key in ("ac_bonus", "new_ac", "hit_after_recheck")} == {
        "ac_bonus": bonus, "new_ac": attack["target_ac"] + bonus, "hit_after_recheck": False}
    assert defender.current_hp == hp
    assert not any(e["event_type"] == "DAMAGE_COMMITTED" and DEFENDER in e["target_ids"]
                   for e in boundary["events"])

    # End the attacker turn through the table, then reload the committed expiry.
    fresh_table = TabletopService(fresh, tmp_path)
    assert fresh_table.state(mid)["menu"]["actor_id"] == ATTACKER
    assert act(fresh_table, mid, "end")["status"] == "COMMITTED"
    expired = CombatService(ROOT, tmp_path)._load_session(mid)
    assert expired.engine.state.current_actor_id == DEFENDER
    defender = expired.engine.state.actors[DEFENDER]
    assert not [m for m in defender.modifiers.values() if m.source_definition_id == QI_ARMOR]
    assert expired.engine._ac_modifier(defender) == 0 and defender.reaction_available
    assert defender.resources[QI] == qi - cost
    assert expired.mechanical.replay()["status"] == "PASS"


@pytest.fixture(scope="module")
def portable_bundle(tmp_path_factory):
    root = tmp_path_factory.mktemp("qa5f-portable")
    package = root / "sealed.zip"
    CharacterCombatAdapter().compile(
        ROOT / "fixtures/c3a/C1A_Clean_Fire_Qi_Proof_Character.zip",
        output_dir=root / "artifacts", output_package=package,
    )
    return CharacterCombatRuntimeAdapter(package).build_bundle(RuntimeResourceInitialization(
        qi_current=15, martial_focus_current=1,
        provenance_kind="TEST_FIXTURE", provenance_id="pytest:qa5f",
    ))


@pytest.mark.parametrize("bonus", [5, 3], ids=["new-sealed-bundle", "historical-stored-bundle"])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_portable_qi_armor_handler_uses_reloaded_bundle_parameters(tmp_path, portable_bundle, bonus, selection):
    raw = portable_bundle.model_dump(mode="json", by_alias=True)
    assert raw["reaction_parameters"][REACTION]["ac_bonus"] == 5
    assert raw["reaction_parameters"][REACTION]["cost"] == 2
    if bonus == 3:
        raw["reaction_parameters"][REACTION]["ac_bonus"] = 3
    raw.pop("bundle_sha256")
    raw["bundle_sha256"] = canonical_sha256(raw)
    saved = tmp_path / "stored-runtime-bundle.json"
    saved.write_text(json.dumps(raw), encoding="utf-8")
    bundle = CharacterRuntimeBundle.model_validate_json(saved.read_bytes())
    engine = CharacterCombatRuntimeEngine(
        ROOT, bundle, match_seed="QA5F-PORTABLE",
        additional_actors=(dummy_actor_template("dummy:attacker", team_id="team:dummy"),),
        positions={SOURCE_ACTOR_ID: Position(x=2, y=2), "dummy:attacker": Position(x=3, y=2)},
    )
    defender, attacker = engine.state.actors[SOURCE_ACTOR_ID], engine.state.actors["dummy:attacker"]
    hp = defender.current_hp
    intent = ActionIntent(
        intent_id="qa5f:ranged", decision_id="qa5f:decision", candidate_id="qa5f:candidate",
        state_version=engine.state.state_version, actor_id=attacker.entity_id,
        reaction_decisions=(ReactionDecision(checkpoint="ATTACK_HIT_BEFORE_DAMAGE",
            reactor_id=defender.entity_id, reaction_source_id=REACTION, selection=selection),),
    )
    script(engine, [10])
    with engine._transaction("qa5f:ranged", intent.intent_id, attacker.entity_id):
        hit = engine._resolve_character_attack(
            attacker, defender, source_id="qa5f:ranged", attack_bonus=defender.armor_class - 6,
            damage=None, damage_type="BLUDGEONING", intent=intent, fixed_damage=10, ranged=True,
        )
    used = selection == "USE"
    assert hit == (not used or bonus == 3)
    assert defender.current_hp == hp - (10 if hit else 0)
    assert defender.resources[QI] == 15 - (2 if used else 0)
    assert defender.reaction_available == (not used)
    assert engine._ac_modifier(defender) == (bonus if used else 0)
    resolved = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == REACTION]
    assert len(resolved) == int(used)
    if used:
        payload = dict(resolved[0].payload)
        if "observations_after" in payload:
            assert payload.pop("observations_after") == engine.state.model_dump(mode="json")["observations"]
        assert payload == {"ac_bonus": bonus, "new_ac": defender.armor_class + bonus,
                           "hit_after_recheck": bonus == 3}
        [modifier] = list(defender.modifiers.values())
        assert modifier.value == bonus and modifier.expires_on == "START_OF_SELF_NEXT_TURN"
        # This portable harness has no turn controller: exercise its expiry
        # checkpoint directly. Full turn advancement is covered by the table test.
        engine._expire_for_checkpoint("START_OF_TURN", attacker.entity_id)
        assert engine._ac_modifier(defender) == bonus
        engine._expire_for_checkpoint("START_OF_TURN", defender.entity_id)
        assert engine._ac_modifier(defender) == 0 and not defender.modifiers
        assert defender.resources[QI] == 13
