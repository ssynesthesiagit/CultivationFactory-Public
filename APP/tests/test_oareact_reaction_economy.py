"""OAREACT (HUNT152, confirmed 1): a Reaction is only offered through its own
trigger window, never as a primary turn intent.

A Thread-sphere fighter made 77-207 Opportunity Attacks in ONE turn and the
turn never ended. The compiled "Opportunity Attack + Threaded Strike" actions
(factory_compiler._opportunity_attack, fanned out into per-mode variants by
_core_modifier_pass) carry economy REACTION and sat in the actor's action_ids,
so Gate2Engine._generate_legal_candidates offered them as primary candidates on
the actor's OWN turn. Executing one never cleared reaction_available
(_consume_economy had no REACTION branch), so the candidate regenerated forever.

The fix is general and lives in the engine:

- _action_candidates_impl denies REACTION-economy actions as primary
  candidates (for AI and human seats alike). Reactions are only offered
  through their trigger window (a creature leaving reach, damage
  application, ...), which resolves the attack directly through
  combat/typed_reactions.py and pays with typed_reactions.spend_reaction.
- _consume_economy consumes reaction_available for REACTION and raises when the
  Reaction is already spent, so no path that resolves a REACTION-economy
  action through the action pipeline can loop.
- reaction_available is still refreshed at the creature's turn start
  (_system_start_turn), as the rules say.
"""

from pathlib import Path
from copy import deepcopy
import json

import pytest

from combat.factory_compiler import compile_character
from combat.diagnostics import CombatGate1Error
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionDefinition, ActionIntent, CandidateKind, EconomyKind, Position
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]
THREAD_ID = "actor:factory.oareact_thread"

# A minimal Thread-sphere fighter: a melee weapon (the dao) plus Threaded
# Strike. The compiler pairs the opportunity attack with the linked modifier,
# producing the four "Opportunity Attack + Threaded Strike: <mode>" actions
# with economy REACTION in the fighter's action_ids -- exactly the shapes that
# looped in HUNT152.
THREAD_SHEET = {
    "identity": {"display_name": "Thread Probe", "proficiency_bonus": 2,
                 "cultivation_level": 5, "path": "Qi Cultivation", "size": "Medium"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2}
                      for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Qi", "maximum": 20},
        "armor_class": {"base_value": 13}, "hit_points": {"maximum": 40},
        "speed": {"walking_ft": 30},
        "technique_save_dc": 12, "technique_attack_bonus": 4,
    },
    "spheres_and_talents": {"learned_talent_record_ids": ["THREAD_BASE_THREADED_STRIKE"]},
    "equipment": [{"content_type": "item", "name": "Starting kit", "starting_kit": {
        "background_id": "tianxia.background.imperial_scholar", "choices": [], "coin_cc": 100,
        "items": [{"item_id": "tianxia.mortal.weapon.dao", "name": "Dao", "printed": "a dao",
                   "quantity": 1, "source": "starting_kit", "unit_price_cc": 100, "value_cc": 100}]}}],
}


def _engine() -> Gate2Engine:
    bundle = compile_character(THREAD_SHEET, actor_id=THREAD_ID)
    return Gate2Engine(ROOT, match_seed="OAREACT", typed_bundles=(bundle,),
                       roster_setup={"primary_actor_ids": [THREAD_ID, AN],
                                     "team_by_actor": {THREAD_ID: "team:a", AN: "team:b"},
                                     "starting_positions": {THREAD_ID: {"x": 5, "y": 5},
                                                            AN: {"x": 5, "y": 6}}})


def _reaction_action(engine: Gate2Engine):
    """A compiled REACTION-economy action from the Thread fighter's own ids."""
    for source_id in engine.state.actors[THREAD_ID].action_ids:
        if "opportunity_attack" in source_id:
            return engine.action_catalog[source_id]
    raise AssertionError("the Thread fighter compiled no opportunity-attack variant")


def test_thread_fighter_compiles_reaction_economy_variants():
    engine = _engine()
    variants = [a for a in engine.state.actors[THREAD_ID].action_ids if "opportunity_attack" in a]
    assert len(variants) == 4, "expected the four Threaded Strike modes on the opportunity attack"
    for source_id in variants:
        assert engine.action_catalog[source_id].economy == EconomyKind.REACTION


def test_reaction_economy_actions_are_never_primary_intents():
    """On the fighter's OWN turn, with a foe in reach, no Reaction is offered."""
    engine = _engine()
    assert engine.state.current_actor_id == THREAD_ID  # the Thread fighter leads initiative
    assert engine.state.actors[THREAD_ID].reaction_available
    candidates = engine.legal_candidates()
    offered = [c for c in candidates if "opportunity_attack" in c.source_definition_id]
    assert not offered, "a Reaction-economy action must never be a primary turn intent"
    for candidate in candidates:
        definition = engine.action_catalog.get(candidate.source_definition_id)
        if definition is not None:
            assert definition.economy != EconomyKind.REACTION


def test_a_reaction_is_consumed_when_resolved_through_the_action_pipeline():
    engine = _engine()
    actor = engine.state.actors[THREAD_ID]
    action = _reaction_action(engine)
    assert actor.reaction_available
    engine._consume_economy(actor, action)
    assert not actor.reaction_available
    with pytest.raises(ValueError, match="reaction unavailable"):
        engine._consume_economy(actor, action)


def _walk_away(engine: Gate2Engine) -> list:
    mover = engine.state.actors[AN]
    before = len(engine.events)
    engine._resolve_leave_reach(mover, mover.position,
                                Position(x=mover.position.x, y=mover.position.y + 1), None)
    return engine.events[before:]


def test_opportunity_attack_still_fires_when_a_foe_leaves_reach():
    """The real Reaction window is untouched: leaving reach provokes one OA."""
    engine = _engine()
    events = _walk_away(engine)
    assert any(e.event_type == "REACTION_WINDOW_OPENED" for e in events)
    assert any(e.event_type == "REACTION_RESOLVED" for e in events)
    assert not engine.state.actors[THREAD_ID].reaction_available


def test_opportunity_attack_fires_once_per_round():
    engine = _engine()
    assert any(e.event_type == "REACTION_WINDOW_OPENED" for e in _walk_away(engine))
    assert not engine.state.actors[THREAD_ID].reaction_available
    # The Reaction is spent: the second leave-reach in the same round is declined,
    # not silently re-offered.
    events = _walk_away(engine)
    assert not any(e.event_type == "REACTION_WINDOW_OPENED" for e in events)
    assert any(e.event_type == "REACTION_DECLINED" for e in events)


def test_reaction_is_refreshed_at_the_creatures_turn_start():
    engine = _engine()
    assert any(e.event_type == "REACTION_WINDOW_OPENED" for e in _walk_away(engine))
    assert not engine.state.actors[THREAD_ID].reaction_available
    engine.end_turn()  # the foe's turn
    assert not engine.state.actors[THREAD_ID].reaction_available
    while engine.state.current_actor_id != THREAD_ID:
        engine.end_turn()
    assert engine.state.actors[THREAD_ID].reaction_available  # refreshed at turn start
    assert any(e.event_type == "REACTION_RESOLVED" for e in _walk_away(engine))


def test_a_forged_primary_reaction_intent_is_rejected_without_spending():
    engine = _engine()
    actor = engine.state.actors[THREAD_ID]
    action = _reaction_action(engine)
    forged = engine._candidate(CandidateKind.ACTION, actor, action.source_definition_id,
                               action.display_name, target_ids=(AN,))
    intent = ActionIntent(intent_id="test:forged-reaction", actor_id=THREAD_ID, candidate_id=forged.candidate_id,
                          decision_id=forged.decision_id, state_version=forged.state_version,
                          target_ids=(AN,))
    before = engine.state.model_dump(mode="json")
    count = len(engine.events)
    with pytest.raises(CombatGate1Error) as rejected:
        engine.execute_intent(intent)
    assert rejected.value.diagnostic.code == "GATE2_STALE_OR_ILLEGAL_CANDIDATE"
    assert engine.state.model_dump(mode="json") == before
    assert len(engine.events) == count


def test_compiled_reaction_catalog_inventory_uses_the_same_primary_gate(tmp_path):
    """Every REACTION-economy catalog action in the census is trigger-only.

    Include all authority Reaction abilities in one census bundle, an unarmed
    bundle, the reported Thread bundle, and Flexible Cover (an Action ability
    whose plug-in declares a voluntary paid Reaction to turn its face). Unsupported triggers remain
    compiler diagnostics, rather than being invented as turn actions.
    """
    authority = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    reaction_ids = [key for key, row in authority["mechanics"].items()
                    if row.get("activation", {}).get("economy") == "reaction"]
    assert reaction_ids
    census = deepcopy(THREAD_SHEET)
    census["spheres_and_talents"]["learned_talent_record_ids"] = reaction_ids
    unarmed = deepcopy(THREAD_SHEET)
    unarmed["spheres_and_talents"]["learned_talent_record_ids"] = []
    unarmed["equipment"] = []
    shield = deepcopy(unarmed)
    shield["spheres_and_talents"]["learned_talent_record_ids"] = ["TAL_SHIELD_FLEXIBLE_COVER"]
    engine = _engine()
    checked = set()
    inventory = []
    declarations = []
    for sheet in (THREAD_SHEET, unarmed, census, shield):
        bundle = compile_character(sheet, actor_id=THREAD_ID)
        for row in bundle["action_catalog"]:
            # A multi-part ability can also supply ordinary actions. Inspect
            # each compiled action's economy, rather than its ability's header.
            if ".field_repair" in row["source_definition_id"]:
                assert row["economy"] == "NONE"
                assert row["display_name"].startswith("Confirm damaged equipment:")
                declarations.append({"id": row["source_definition_id"], "name": row["display_name"]})
            if row['source_definition_id'].endswith('.flexible_cover.turn'):
                assert row['economy'] == 'NONE' and row['parameters']['free_primary']
                declarations.append({'id': row['source_definition_id'], 'name': row['display_name']})
            if row["economy"] != "REACTION":
                continue
            action = ActionDefinition.model_validate(row)
            checked.add(action.display_name)
            inventory.append({"id": action.source_definition_id, "name": action.display_name})
            assert engine._action_candidates(engine.state.actors[THREAD_ID], action) == []
    (tmp_path / "reaction_inventory.json").write_text(json.dumps({
        "printed_reaction_owners": len(reaction_ids), "catalog_actions": inventory,
        "manual_trigger_declarations": declarations}, indent=2) + "\n")
    assert any(d['name'] == 'Turn FLEXIBLE COVER face (Reaction)' for d in declarations)
    assert {"Opportunity Attack", *{
        "Opportunity Attack + Threaded Strike: " + mode
        for mode in ("Follow the Sleeve", "Tighten the Wrist", "Draw the Guard", "Weighted Knot")}} <= checked


@pytest.mark.parametrize("mode", ["MANUAL", "LOCAL_AUTO"])
def test_thread_table_primary_actions_finish_turn_and_reload(tmp_path, mode):
    """The reported loop is absent from both player and production AI service menus."""
    service, table, mid = _table_fight(tmp_path, mode, THREAD_SHEET)
    for _ in range(16):
        engine = service._load_session(mid).engine
        if engine.state.current_actor_id != THREAD_ID or engine.state.terminal_result:
            break
        candidates = engine.legal_candidates()
        assert not any(engine.action_catalog[c.source_definition_id].economy == EconomyKind.REACTION
                       for c in candidates if c.source_definition_id in engine.action_catalog)
        state = table.state(mid)
        if mode == "LOCAL_AUTO":
            result = table.auto_step(mid, state["last_sequence"])
        else:
            attacks = [c for c in candidates if c.kind == CandidateKind.ACTION and AN in c.target_ids
                       and c.source_definition_id.startswith("action:typed.")]
            c = next(iter(attacks), None) or next(c for c in candidates if c.kind == CandidateKind.END_TURN)
            result = table.act(mid, c.candidate_id, c.decision_id, c.state_version, state["last_sequence"])
        assert result["status"] == "COMMITTED", result
    else:
        pytest.fail("Thread fighter's primary turn did not finish within 16 commits")
    engine = service._load_session(mid).engine
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == engine.state
    assert loaded.verify()["status"] == "PASS"
    assert not any(e.event_type == "ATTACK_ROLLED" and "opportunity_attack" in e.source_definition_id
                   and e.actor_id == THREAD_ID for e in engine.events)


def _table_fight(tmp_path, mode, sheet, *, reaction_responder=False):
    bundle = compile_character(sheet, actor_id=THREAD_ID)
    bundles = [bundle]
    if reaction_responder:
        observer = compile_character(THREAD_SHEET, actor_id=AN)
        observer['typed_reactions'] = [{
            'block': 'generic', 'feature_id': 'TEST_REPAIR_RESPONSE',
            'name': 'Repair response', 'kind': 'reaction_used', 'range_ft': 30,
            'ask': True, 'costs': [['resource:core.qi', 1]], 'numbers': {'pb': 2},
            'effects': [{'type': 'temp_hp', 'flat': 3, 'applies_to': 'self'}],
        }]
        bundles.append(observer)
    service = CombatService(ROOT, tmp_path)
    mid = service.persistence.create_match(match_seed="OAREACT", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [THREAD_ID, AN],
                      "team_by_actor": {THREAD_ID: "team:a", AN: "team:b"},
                      "starting_positions": {THREAD_ID: {"x": 5, "y": 5}, AN: {"x": 5, "y": 6}}}).match_id
    service.set_controller_mode(mid, actor_id=THREAD_ID, controller_mode=mode)
    service.set_controller_mode(mid, actor_id=AN, controller_mode="MANUAL")
    table = TabletopService(service, tmp_path)
    assert service._load_session(mid).engine.state.current_actor_id == THREAD_ID
    return service, table, mid


def test_field_repair_publishes_ask_me_response_once_and_reloads(tmp_path):
    from tests.test_auto17_blacksmith import FIELD_REPAIR, _sheet
    from combat.ext.blacksmith_forge import mark_count

    service, table, mid = _table_fight(tmp_path, 'MANUAL', _sheet([FIELD_REPAIR]),
                                     reaction_responder=True)
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id.endswith('.field_repair.close_crack')
                     and c.target_ids == (AN,))
    before = engine.state.model_dump(mode='json')
    sequence = table.state(mid)['last_sequence']

    def send(answers):
        return table.act(mid, candidate.candidate_id, candidate.decision_id,
                         candidate.state_version, sequence, answers)

    result = send([])
    assert result['status'] == 'REACTION_REQUIRED', result
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == AN
    assert 'Field Repair' in prompt['moment']
    assert send([])['reaction'] == prompt
    assert service._load_session(mid).engine.state.model_dump(mode='json') == before
    assert send([{**prompt['context'], 'selection': 'USE'}])['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    for actor_id in (THREAD_ID, AN):
        actor = engine.state.actors[actor_id]
        assert not actor.reaction_available
        assert actor.resources['resource:core.qi'] == before['actors'][actor_id]['resources']['resource:core.qi'] - 1
    assert engine.state.actors[AN].temporary_hp == 3
    assert mark_count(engine.state.actors[AN], THREAD_ID) == 1
    for source in (FIELD_REPAIR, 'TEST_REPAIR_RESPONSE'):
        assert len([e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                    and e.source_definition_id == source]) == 1
    assert not any('.field_repair' in c.source_definition_id for c in engine.legal_candidates())
    assert loaded.verify()['status'] == 'PASS'


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO'])
def test_voluntary_paid_shield_rotation_preserves_all_edges_and_reloads(tmp_path, mode):
    from tests.test_shield_fix_r2 import match, finish
    from tests.test_auto55_shield import ME, ALLY
    from combat import ext
    from combat.ext.shield_faces import FACE
    from combat.gate4_adapters import ManualControllerAdapter

    service, table, mid = match(tmp_path, ['TAL_SHIELD_FLEXIBLE_COVER'], ally=True)
    finish(table, mid, 'FLEXIBLE COVER', lambda p: ['E'])
    engine = service._load_session(mid).engine
    # No attack is happening: rotate north to protect the ally, not the bearer.
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id.endswith('.flexible_cover.turn'))
    actor = engine.state.actors[ME]
    definition = engine.action_catalog[candidate.source_definition_id]
    assert not ext.any_false('ai_candidate_allowed', engine, actor, candidate, definition)
    before = engine.state.model_dump(mode='json')
    held = next(c for c in actor.conditions.values() if c.condition_id == FACE)
    expiry = held.expires_on
    if mode == 'LOCAL_AUTO':
        original = service.controller

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(original, name)

        service.controller = Controller()
        service.set_controller_mode(mid, actor_id=ME, controller_mode=mode)
    prompts = finish(table, mid, definition.display_name, lambda p: ['N'], auto=mode == 'LOCAL_AUTO')
    if mode == 'MANUAL':
        assert prompts
        assert {o['id'] for o in prompts[0]['choice']['options']} == {'N', 'S', 'W'}
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[ME]
    face = next(c for c in actor.conditions.values() if c.condition_id == FACE)
    assert face.data['edge'] == 'N' and face.expires_on == expiry
    assert not actor.reaction_available
    assert actor.action_available == before['actors'][ME]['action_available']
    assert actor.bonus_action_available == before['actors'][ME]['bonus_action_available']
    assert actor.resources == before['actors'][ME]['resources']
    assert loaded.engine.state.actors[ALLY].conditions == engine.state.actors[ALLY].conditions
    assert not any(c.source_definition_id.endswith('.flexible_cover.turn')
                   for c in loaded.engine.legal_candidates())
    assert loaded.verify()['status'] == 'PASS'


def test_shield_edge_preference_does_not_reveal_concealed_enemy():
    from tests.test_auto55_shield import _fight, ME, THEM
    from combat.ext.shield_faces import _nearest_hostile
    from combat import senses

    engine = _fight(['TAL_SHIELD_FLEXIBLE_COVER'])
    actor, enemy = engine.state.actors[ME], engine.state.actors[THEM]
    assert _nearest_hostile(engine, actor) is enemy
    engine._apply_condition(enemy, 'condition:typed.invisible', 'test:concealed',
                            THEM, expires_on='UNTIL_REMOVED', data={})
    assert not senses.perceives(engine, actor, enemy)
    assert _nearest_hostile(engine, actor) is None


def test_paid_shield_rotation_publishes_ask_me_response_once(tmp_path):
    from tests.test_auto55_shield import _sheet
    from tests.test_shield_fix_r2 import finish
    from combat.ext.shield_faces import FACE

    service, table, mid = _table_fight(tmp_path, 'MANUAL', _sheet(['TAL_SHIELD_FLEXIBLE_COVER']),
                                     reaction_responder=True)
    finish(table, mid, 'FLEXIBLE COVER', lambda p: ['E'])
    engine = service._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.source_definition_id.endswith('.flexible_cover.turn'))
    before = engine.state.model_dump(mode='json')
    sequence = table.state(mid)['last_sequence']
    answers = []
    seen = []
    for _ in range(3):
        result = table.act(mid, candidate.candidate_id, candidate.decision_id,
                           candidate.state_version, sequence, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        assert service._load_session(mid).engine.state.model_dump(mode='json') == before
        prompt = result['reaction']
        seen.append(prompt)
        answers.append({**prompt['context'], 'selection': 'USE',
                        **({'option_ids': ['N']} if prompt.get('choice') else {})})
    else:
        pytest.fail('rotation did not resume after edge and responder answers')
    assert any(p['context']['reactor_id'] == AN and 'Flexible Cover' in p['moment'] for p in seen)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor, observer = loaded.engine.state.actors[THREAD_ID], loaded.engine.state.actors[AN]
    assert not actor.reaction_available and not observer.reaction_available
    assert actor.resources == before['actors'][THREAD_ID]['resources']
    assert observer.resources['resource:core.qi'] == before['actors'][AN]['resources']['resource:core.qi'] - 1
    assert observer.temporary_hp == 3
    assert len([c for c in actor.conditions.values() if c.condition_id == FACE]) == 1
    assert next(c for c in actor.conditions.values() if c.condition_id == FACE).data['edge'] == 'N'
    assert len([e for e in loaded.engine.events if e.event_type == 'REACTION_RESOLVED'
                and e.source_definition_id == 'TEST_REPAIR_RESPONSE']) == 1
    assert loaded.verify()['status'] == 'PASS'


@pytest.mark.parametrize("close_crack", [False, True])
def test_manual_equipment_damage_declaration_opens_one_paid_reaction_and_reloads(tmp_path, close_crack):
    from tests.test_auto17_blacksmith import FIELD_REPAIR, _sheet
    from combat.typed_executor import mark_condition_id

    service, table, mid = _table_fight(tmp_path, "MANUAL", _sheet([FIELD_REPAIR]))
    engine = service._load_session(mid).engine
    qi = engine.state.actors[THREAD_ID].resources["resource:core.qi"]
    candidates = [c for c in engine.legal_candidates() if ".field_repair" in c.source_definition_id]
    chosen = next(c for c in candidates if c.target_ids == (AN,)
                  and c.source_definition_id.endswith(".close_crack") == close_crack)
    assert engine.action_catalog[chosen.source_definition_id].economy == EconomyKind.NONE
    state = table.state(mid)
    assert table.act(mid, chosen.candidate_id, chosen.decision_id, chosen.state_version,
                     state["last_sequence"])["status"] == "COMMITTED"
    engine = service._load_session(mid).engine
    smith = engine.state.actors[THREAD_ID]
    assert smith.action_available and not smith.reaction_available
    assert smith.resources["resource:core.qi"] == qi - int(close_crack)
    assert any(c.condition_id == mark_condition_id("Forge Mark", THREAD_ID)
               for c in engine.state.actors[AN].conditions.values())
    assert not any(".field_repair" in c.source_definition_id for c in engine.legal_candidates())
    for kind in ("REACTION_WINDOW_OPENED", "REACTION_RESOLVED"):
        events = [e for e in engine.events if e.event_type == kind and e.source_definition_id == FIELD_REPAIR]
        assert len(events) == 1 and events[0].target_ids == (AN,)
        assert events[0].payload["checkpoint"] == "MANUAL_DAMAGED_EQUIPMENT"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state == engine.state
    assert loaded.verify()["status"] == "PASS"


def test_ai_does_not_invent_equipment_damage_to_use_field_repair(tmp_path):
    from tests.test_auto17_blacksmith import FIELD_REPAIR, _sheet
    from combat import ext

    service, table, mid = _table_fight(tmp_path, "LOCAL_AUTO", _sheet([FIELD_REPAIR]))
    engine = service._load_session(mid).engine
    smith = engine.state.actors[THREAD_ID]
    declarations = [c for c in engine.legal_candidates() if ".field_repair" in c.source_definition_id]
    assert declarations
    assert all(ext.any_false("ai_candidate_allowed", engine, smith, c,
                             engine.action_catalog[c.source_definition_id]) for c in declarations)
    state = table.state(mid)
    assert table.auto_step(mid, state["last_sequence"])["status"] == "COMMITTED"
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == FIELD_REPAIR
                   for e in service._load_session(mid).engine.events)
