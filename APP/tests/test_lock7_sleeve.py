"""Owned Puppetry talent at the table: ordinary Opportunity Attacks, choices and replay."""
import pytest

from combat.gate2_runtime_content import AN, BAI
from combat.gate3_reducer import canonical_state_sha256
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import Context, bears_mark, run_effects
from tests.h1_support import ROOT, ME, bundle
from tests.test_hidden_targeting import turn
from tests.test_lock2_persistence import act
from tests.test_lock_choices import install
from tests.r10_fixup_support import cast_sender, commit, answer

REBUKE = 'tianxia.talent.puppetry.sleeve_pulling_rebuke'
OA = 'system:combat.opportunity_attack'
TAKE_OA = {'checkpoint': 'LEAVE_REACH', 'reactor_id': AN, 'reaction_source_id': OA, 'selection': 'USE'}


def fight(tmp_path, monkeypatch, *, owned=True, marked=True, raised=True, succeeds=False):
    def dice(engine, roll, intent):
        context = engine.d20_context(roll) or {}
        return {'source_id': 'test:scripted-die', 'operation': 'replace',
                'natural_result': 20 if context.get('kind') != 'save' or succeeds else 1}
    install(monkeypatch, 'd20_result', dice)
    # Fixture only: apply an actual mark effect when the owner holds position.
    # Raising the vessel and provoking the ordinary OA are real table actions.
    def mark(engine, kind, kwargs):
        if marked and kind == 'HOLD_POSITION_COMMITTED' and kwargs['actor_id'] == ME:
            action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.parameters.get('vessel_kit'))
            ctx = Context(engine, engine.state.actors[ME], action, engine._active_intent,
                          action.parameters['typed'], [engine.state.actors[AN]], engine.state.actors[AN])
            run_effects(ctx, [{'type': 'mark', 'mark': 'Tension Mark', 'applies_to': 'target'}])
    install(monkeypatch, 'event', mark)
    service = CombatService(ROOT, tmp_path)
    puppeteer = bundle([REBUKE if owned else 'tianxia.talent.puppetry.two_body_control'])
    mid = service.persistence.create_match(match_seed='LOCK7-SLEEVE', typed_bundles=(puppeteer,),
        roster_setup={'primary_actor_ids': [ME, AN, BAI],
            'team_by_actor': {ME: 'team:a', BAI: 'team:a', AN: 'team:b'},
            'starting_positions': {ME: {'x': 3, 'y': 6}, BAI: {'x': 4, 'y': 6}, AN: {'x': 5, 'y': 6}}}).match_id
    for aid in (ME, AN, BAI):
        service.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    table = TabletopService(service, tmp_path)
    turn(table, mid, ME)
    if raised:
        commit(cast_sender(service, table, mid, 'Raise the Vessel (1 CP)', at=(3, 7)))
    assert act(table, mid, 'system:combat.hold_position')['status'] == 'COMMITTED'
    turn(table, mid, BAI)
    return service, table, mid


def movement(service, table, mid):
    state = table.state(mid)
    candidate = next(c for c in service._load_session(mid).engine.legal_candidates()
                     if c.destination and (c.destination.x, c.destination.y) == (4, 4) and c.kind == 'MOVE')
    return lambda answers=(): table.act(mid, candidate.candidate_id, candidate.decision_id,
                                       candidate.state_version, state['last_sequence'], [TAKE_OA, *answers]), candidate


@pytest.mark.parametrize('selection,succeeds', [('USE', False), ('DECLINE', False), ('USE', True)])
def test_native_opportunity_rebuke_choice_reload_and_natural20(monkeypatch, tmp_path, selection, succeeds):
    service, table, mid = fight(tmp_path, monkeypatch, succeeds=succeeds)
    before = service._load_session(mid).engine
    assert BAI not in before.typed_actor_ids and AN not in before.typed_actor_ids
    hp, armor, reaction = before.state.actors[BAI].current_hp, before.state.actors[BAI].armor_class, before.state.actors[ME].reaction_available
    send, _ = movement(service, table, mid)
    pending = send()
    assert pending['status'] == 'REACTION_REQUIRED'
    assert 'Sleeve-Pulling Rebuke' in pending['reaction']['moment']
    assert before.state.actors[BAI].display_name in pending['reaction']['moment']
    assert canonical_state_sha256(service._load_session(mid).engine.state) == canonical_state_sha256(before.state)
    # Resume the same pending table intent using a new service instance.
    reopened = CombatService(ROOT, tmp_path)
    send, _ = movement(reopened, TabletopService(reopened, tmp_path), mid)
    responses = [answer(pending['reaction'], 'SPEND', selection == 'USE')]
    for _ in range(8):
        result = send(responses)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        responses.append(answer(result['reaction'], use=False))
    assert result['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    forced = [e for e in engine.events if e.event_type == 'ATTACK_FORCED_MISS' and e.source_definition_id == REBUKE]
    roll = next(e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.source_definition_id == OA)
    assert roll.payload['natural_result'] == 20
    assert bool(forced) == (selection == 'USE' and not succeeds)
    assert bears_mark(engine.state.actors[AN], ME, 'Tension Mark') == (selection == 'DECLINE')
    assert engine.state.actors[ME].reaction_available == reaction  # costs the mark, not a Reaction
    assert engine.state.actors[BAI].armor_class == armor
    if forced:
        assert engine.state.actors[BAI].current_hp == hp
        assert len(forced) == 1
        assert not any(e.event_type == 'DAMAGE_ROLLED' and e.source_definition_id == OA for e in engine.events)
    if succeeds:
        assert roll.payload['mode'] == 'DISADVANTAGE'
    assert loaded.verify()['status'] == loaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('missing', ['owned', 'marked', 'raised'])
def test_rebuke_is_inert_without_ownership_mark_or_thread(monkeypatch, tmp_path, missing):
    service, table, mid = fight(tmp_path, monkeypatch, **{missing: False})
    send, _ = movement(service, table, mid)
    prompts = commit(send)
    assert not any('Sleeve-Pulling Rebuke' in p['moment'] for p in prompts)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert not any(e.source_definition_id == REBUKE for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'


def test_player_rebuke_on_api_driven_ally_move(monkeypatch, tmp_path):
    service, table, mid = fight(tmp_path, monkeypatch)
    service.set_controller_mode(mid, actor_id=BAI, controller_mode='API_AUTO')
    _, c = movement(service, table, mid)
    payload = {key: getattr(c, key) for key in ('candidate_id', 'actor_id', 'target_ids', 'option_ids')}
    payload.update(destination=c.destination.model_dump(mode='json'), decision_id=c.decision_id, state_version=c.state_version)
    token = service.ai_validate(mid, payload)['validation_token']
    pending = service.ai_execute(mid, payload, token, reactions=[TAKE_OA])
    assert pending['status'] == 'AWAITING_REACTION'
    context = pending['reaction_context']
    assert context['reactor_id'] == ME and 'Sleeve-Pulling Rebuke' in context['choice_trigger']['prompt']
    result = CombatService(ROOT, tmp_path).ai_execute(mid, payload, token,
        reactions=[TAKE_OA, {**{k: context[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')},
                             'selection': 'USE', 'option_ids': ['SPEND']}])
    assert result['status'] == 'COMMITTED'
    assert CombatService(ROOT, tmp_path)._load_session(mid).verify()['status'] == 'PASS'


def test_ai_puppeteer_spends_automatically(monkeypatch, tmp_path):
    service, table, mid = fight(tmp_path, monkeypatch)
    service.set_controller_mode(mid, actor_id=ME, controller_mode='LOCAL_AUTO')
    send, _ = movement(service, table, mid)
    assert send()['status'] == 'COMMITTED'
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert any(e.event_type == 'ATTACK_FORCED_MISS' and e.source_definition_id == REBUKE for e in loaded.engine.events)
    assert loaded.verify()['status'] == 'PASS'
