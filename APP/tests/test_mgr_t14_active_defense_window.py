"""A real acquired Shield keeps its after-roll choice even on a natural miss."""
import pytest

from combat.tabletop_service import TabletopService
from tests.test_journey_activities_native import A, B, catalog, game
from tests.test_lock_choices import install
from tests.test_shield_fix_r2 import advance, finish


@pytest.mark.parametrize("payment", ["reaction", "focus"])
@pytest.mark.parametrize("automatic_attacker", [False, True])
def test_acquired_shield_can_answer_a_rolled_miss(
        tmp_path, monkeypatch, catalog, payment, automatic_attacker):
    # A natural 1 still triggers Active Defense: it is not a hit-only response.
    # This also makes the after-roll boundary independent of equipment AC.
    install(monkeypatch, "d20_result", lambda *args: {
        "source_id": "test:shield_rolled_miss", "operation": "replace",
        "natural_result": 1})
    cold, jid, _, _ = game(tmp_path, monkeypatch, catalog, sphere="shield")
    journey = cold().journey_state(jid)
    owner_sheet = cold()._factory_owner_sheet(A.removeprefix("actor:factory."))
    assert "SHIELD_BASE_ACTIVE_DEFENSE" in owner_sheet["spheres_and_talents"][
        "automatic_sphere_component_record_ids"], owner_sheet["spheres_and_talents"]
    bundle = journey["actors"][A]["bundle"]
    assert any(r.get("feature_id") == "SHIELD_BASE_ACTIVE_DEFENSE"
               for r in bundle["typed_reactions"]), (
        f"Shield reaction absent: skipped={bundle.get('skipped')}; "
        f"diagnostics={bundle.get('diagnostics')}; "
        f"passives={[(r.get('feature_id'), r.get('block')) for r in bundle['typed_passives']]}")
    mid = cold().journey_start_combat(
        jid, journey["revision"], {A: "team:a", B: "team:b"},
        maximum_rounds=2)["match_id"]
    table = TabletopService(cold(), tmp_path)
    advance(table, mid, B)
    engine = cold()._load_session(mid).engine
    before = engine.state.actors[A]
    hp, ac = before.current_hp, before.armor_class + engine._ac_modifier(before)
    if automatic_attacker:
        from tests.r1i_service_support import force_ai_candidate
        attack = next(c for c in engine.legal_candidates() if c.target_ids == (A,)
                      and engine.action_catalog.get(c.source_definition_id)
                      and engine.action_catalog[c.source_definition_id].display_name
                      == "Bi Shou (Dagger) attack")
        force_ai_candidate(table.combat, mid, B, attack.candidate_id)

    def choose(prompt):
        source = prompt["context"]["reaction_source_id"]
        if "fact_admission.shield_readiness" in source:
            return ["ready"]
        if ("active_defense_payment" in source
                or source == "reaction:typed.SHIELD_BASE_ACTIVE_DEFENSE"):
            return [payment]
        return None

    prompts = finish(table, mid, "Bi Shou (Dagger) attack", choose,
           auto=automatic_attacker, target=None if automatic_attacker else A)
    engine = cold()._load_session(mid).engine
    rolled = next(e for e in reversed(engine.events)
                  if e.event_type == "ATTACK_ROLLED" and e.actor_id == B)
    windows = [e for e in engine.events if e.event_type == "REACTION_WINDOW_OPENED"
               and e.source_definition_id == "SHIELD_BASE_ACTIVE_DEFENSE"]
    assert rolled.payload["natural_result"] == 1
    assert len(windows) == 1, {"prompts": prompts, "riders": [
        e.payload for e in engine.events if e.event_type == "GM_RIDER"]}
    assert windows[0].sequence > rolled.sequence
    assert windows[0].payload["checkpoint"] == "ATTACK_ROLLED_BEFORE_DAMAGE"
    defender = engine.state.actors[A]
    assert defender.current_hp == hp
    assert defender.armor_class + engine._ac_modifier(defender) == ac
    assert defender.reaction_available == (payment != "reaction")
    assert defender.resources["resource:core.martial_focus"] == (payment != "focus")
    assert cold().verify(mid)["status"] == "PASS"
    assert cold().replay(mid)["status"] == "PASS"
