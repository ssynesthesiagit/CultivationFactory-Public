"""Batch sweep fixtures retain the runtime's real concentration and hook contracts."""
import pytest

from combat.gate2_runtime_models import ActionIntent
from combat.gate5_service import CombatService
from tests import test_auto89r1f1_disease as disease_table


@pytest.mark.parametrize("ai", [False, True])
def test_field_repair_spends_reaction_at_table_and_ai_cannot_invent_object_damage(tmp_path, ai):
    from combat.gate4_context import build_decision_context
    from combat.tabletop_service import TabletopService
    from combat.typed_executor import mark_condition_id
    from tests import test_auto17_blacksmith as smith
    from tests.h1_support import ROOT

    owner, foe = smith.ME, disease_table.FOE
    bundles = [smith._bundle([smith.FIELD_REPAIR]),
               disease_table._bundle([], foe, "Sparring partner", no_base=True)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [owner, foe], {owner: "team:smith", foe: "team:opponents"},
        {owner: {"x": 3, "y": 6}, foe: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [owner], [foe],
        control_modes={owner: "MANUAL", foe: "MANUAL"}, match_seed="SOL138R2-REPAIR",
        display_name="Field Repair regression", maximum_rounds=4)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != owner:
        state = table.state(mid)
        menu = state["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                         state["last_sequence"], [])['status'] == 'COMMITTED'
    session = combat._load_session(mid)
    engine = session.engine
    if ai:
        policy, _ = combat.policies.for_actor(owner)
        context = build_decision_context(engine, policy, for_ai=True)
        assert not any(c.display_name.startswith("Field Repair") for c in context.legal_candidates)
        return
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name == "Field Repair" and foe in c.target_ids)
    state = table.state(mid)
    menu = state["menu"]
    before = dict(engine.state.actors[owner].resources)
    assert table.act(mid, candidate.candidate_id, menu["decision_id"], menu["state_version"],
                     state["last_sequence"], [])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[owner]
    assert actor.reaction_available is False
    assert actor.resources == before
    mark = next(c for c in loaded.engine.state.actors[foe].conditions.values()
                if c.condition_id == mark_condition_id("Forge Mark", owner))
    assert mark.data['count'] == 1
    assert not any(c.display_name.startswith("Field Repair") for c in loaded.engine.legal_candidates())
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["canonical_state_sha256"] == loaded.verify()["canonical_state_sha256"]


def test_ai_court_failed_concentration_ends_aura_without_overwriting_allies(tmp_path):
    """The ordinary maker loses the Court to damage, not to a repeated ally choice."""
    t = disease_table
    combat, table, mid = t._fight(tmp_path, control_modes=t.AI_MODES)
    assert t._step_until_actor(combat, mid, t.WARDEN)
    session = combat._load_session(mid)
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == "Court of the Crawling Fever" and c.actor_id == t.WARDEN)
    session.submit_intent(ActionIntent(intent_id="sol138r2-court", decision_id=candidate.decision_id,
                                      candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                      actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                                      destination=candidate.destination),
                          primary_decision_record=None, reaction_provider=None)
    engine = t._engine(combat, mid)
    stored = t._allies_of(engine, t._court_zone(engine))
    assert stored
    for _ in range(12):
        assert table.auto_step(mid, table.state(mid)["last_sequence"], [])['status'] == 'COMMITTED'
        engine = t._engine(combat, mid)
        zones = list(t.disease._zones_of(engine, t.CRAWLING_KEY))
        if not zones:
            break
        assert t._allies_of(engine, t._court_zone(engine)) == stored
        assert len(t._start_triggers(engine, t.WARDEN)) == 1
    assert not zones, "this ordinary maker must actually fail a damage concentration check"
    assert any(e.event_type == "CONCENTRATION_ENDED" and e.actor_id == t.WARDEN
               and e.payload.get("reason") == "FAILED_DAMAGE_CHECK" for e in engine.events)
    assert set(t._answers_on_the_aura(engine)) == {tuple(stored)}
    reloaded = CombatService(combat.source_root, combat.userdata_root)._load_session(mid)
    assert list(t.disease._zones_of(reloaded.engine, t.CRAWLING_KEY)) == []
    assert reloaded.engine.state.model_dump(mode="json") == engine.state.model_dump(mode="json")
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["canonical_state_sha256"] == reloaded.verify()["canonical_state_sha256"]
