"""Motion purchase monotonicity and teleport composition at the persisted table.

All actors and controllers are deterministic; no model or browser is contacted.
"""
import pytest

from combat.ext import athletics
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.test_mgr_t16_athletics import (
    game, commit, move_at, ROOT, OWNER, MULTIPLE, AFTERIMAGE, MOVING,
    MOBILITY, FOCUS, reload_identical,
)

FLASH = athletics.FLASH_STEP


def composition_prompts(prompts):
    return [p for p in prompts if p['context']['reaction_source_id'] in {
        'choice:needle.athletics.motion_count', 'choice:needle.athletics.multiple_motions'}]


def flash_landing(prompt):
    if prompt['context']['reaction_source_id'] == 'choice:needle.teleport_destination':
        assert 'cell:8,6' in {o['id'] for o in prompt['choice']['options']}
        return ['cell:8,6']
    return None


def test_landing_driver_distinguishes_cells_from_motion_choices():
    landing = {'context': {'reaction_source_id': 'choice:needle.teleport_destination'},
               'choice': {'options': [{'id': 'cell:8,6'}]}}
    motion = {'context': {'reaction_source_id': 'choice:needle.athletics.multiple_motions'},
              'choice': {'options': [{'id': MOVING}]}}
    assert flash_landing(landing) == ['cell:8,6']
    assert flash_landing(motion) is None
    assert composition_prompts([landing, motion]) == [motion]


def cold(tmp_path, mid):
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    return engine, engine.state.actors[OWNER]


def last_move(engine):
    return next(e for e in reversed(engine.events)
                if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == OWNER)


@pytest.mark.parametrize('selected', [AFTERIMAGE, MOVING, MOBILITY])
def test_purchase_keeps_every_free_motion_on_same_loadout(tmp_path, selected):
    outcomes = []
    for upgrade in (False, True):
        folder = tmp_path / str(upgrade)
        service, table, mid = game(folder, [AFTERIMAGE, MOVING, MOBILITY]
                                   + ([MULTIPLE] if upgrade else []))
        offered = []
        def choose(prompt):
            if 'motion_count' in prompt['context']['reaction_source_id']:
                return ['one']
            offered.extend(o['id'] for o in prompt['choice']['options'])
            return [selected]
        prompts = commit(table, mid, move_at(table, mid, 8), choose)
        assert len(prompts) == (2 if upgrade else 1)
        assert set(offered) == {AFTERIMAGE, MOVING, MOBILITY}
        engine, owner = cold(folder, mid)
        assert last_move(engine).payload['movement_selections']['motion'] == [selected]
        result = (owner.resources[FOCUS],
                  any(c.condition_id == athletics.AFTERIMAGE_CONDITION for c in owner.conditions.values()),
                  athletics._moving_target(engine, owner))
        assert result == (1, selected == AFTERIMAGE, 2 if selected == MOVING else 0)
        outcomes.append(result)
        reload_identical(service, mid, folder)
    assert outcomes[0] == outcomes[1]


def flash_candidate(service, mid):
    return next(c for c in service._load_session(mid).engine.legal_candidates()
                if c.display_name.startswith('Flash Step to ')
                and (c.destination.x, c.destination.y, c.destination.z) == (8, 6, 0))


def focus_capacity(bundles):
    # A sealed fixture with room for the two independently payable costs.
    owner = next(b for b in bundles if b['actor_id'] == OWNER)
    next(r for r in owner['actor_template']['resources']
         if r['resource_id'] == FOCUS)['maximum'] = 2


@pytest.mark.parametrize('focus,combine,cover,prompts_count', [
    (1, False, 0, 0), (2, False, 0, 1), (2, True, 2, 2),
])
def test_flash_step_binds_its_own_motion_pays_each_cost_and_reloads(
        tmp_path, focus, combine, cover, prompts_count):
    service, table, mid = game(tmp_path, [MULTIPLE, FLASH, MOVING, MOBILITY, AFTERIMAGE],
                               focus=focus, prepare=focus_capacity)
    choices = []
    def choose(prompt):
        landing = flash_landing(prompt)
        if landing is not None:
            return landing
        assert 'Flash Step' in str(prompt) and 'Swimmer' in str(prompt)
        assert 'Martial Focus' in str(prompt)
        if 'motion_count' in prompt['context']['reaction_source_id']:
            return ['two' if combine else 'one']
        choices.extend(o['id'] for o in prompt['choice']['options'])
        return [MOVING]
    prompts = commit(table, mid, {'candidate_id': flash_candidate(service, mid).candidate_id}, choose)
    assert len(composition_prompts(prompts)) == prompts_count
    assert all(set(answer) <= {o['id'] for o in prompt['choice']['options']}
               for prompt in prompts if (answer := flash_landing(prompt)) is not None)
    if combine:
        assert set(choices) == {MOVING, MOBILITY, AFTERIMAGE}
    engine, owner = cold(tmp_path, mid)
    assert (owner.position.x, owner.position.y) == (8, 6)
    assert not owner.action_available
    assert owner.resources[FOCUS] == focus - 1 - int(combine)
    assert athletics._moving_target(engine, owner) == cover
    assert not any(c.condition_id == athletics.AFTERIMAGE_CONDITION for c in owner.conditions.values())
    event = last_move(engine)
    assert event.payload['teleport'] is True
    assert event.payload['movement_selections']['motion'] == [FLASH] + ([MOVING] if combine else [])
    spent = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
             and e.actor_id == OWNER and e.payload.get('resource_id') == FOCUS]
    assert len(spent) == 1 + int(combine)
    assert not getattr(engine, '_movement_sequence', None)
    reload_identical(service, mid, tmp_path)
    # Start the next native route after cold reload: teleport's binding is gone.
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    commit(table, mid, move_at(table, mid, 9), lambda p:
           ['one'] if 'motion_count' in p['context']['reaction_source_id'] else [MOBILITY])
    engine, owner = cold(tmp_path, mid)
    assert last_move(engine).payload['movement_selections']['motion'] == [MOBILITY]
    assert athletics._moving_target(engine, owner) == cover
    reload_identical(service, mid, tmp_path)


def test_flash_step_automatic_seat_chooses_pair_without_player_prompt(tmp_path):
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate4_context import build_reaction_context
    service, _, mid = game(tmp_path, [MULTIPLE, FLASH, MOVING], mode='LOCAL_AUTO',
                            focus=2, prepare=focus_capacity)
    session = service._load_session(mid)
    candidate = flash_candidate(service, mid)
    decisions = []
    def policy(request):
        actor_policy, _ = session.persistence.policy_library.for_actor(request['reactor_id'])
        context = build_reaction_context(session.engine, actor_policy, request)
        chosen = session.persistence.local_controller.choose_reaction(context)
        decisions.append(chosen.decision)
        return chosen.decision, chosen.record.model_dump(mode='json', by_alias=True)
    intent = ActionIntent(intent_id='athletics-flash-composition', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version,
        actor_id=OWNER, target_ids=candidate.target_ids, destination=candidate.destination,
        option_ids=candidate.option_ids)
    session.submit_intent(intent, primary_decision_record=None, reaction_provider=policy)
    engine, owner = cold(tmp_path, mid)
    assert len(decisions) == 1  # The only additional Motion is already determined.
    assert last_move(engine).payload['movement_selections']['motion'] == [FLASH, MOVING]
    assert owner.resources[FOCUS] == 0 and athletics._moving_target(engine, owner) == 2
    reload_identical(service, mid, tmp_path)


def test_flash_step_without_multiple_motions_cannot_earn_an_extra_motion(tmp_path):
    service, table, mid = game(tmp_path, [FLASH, MOVING], focus=2, prepare=focus_capacity)
    prompts = commit(table, mid, {'candidate_id': flash_candidate(service, mid).candidate_id}, flash_landing)
    assert not composition_prompts(prompts)  # The landing choice is independent of Motion composition.
    engine, owner = cold(tmp_path, mid)
    assert (owner.position.x, owner.position.y) == (8, 6)
    assert owner.resources[FOCUS] == 1 and athletics._moving_target(engine, owner) == 0
    assert last_move(engine).payload['movement_selections']['motion'] == [FLASH]
    reload_identical(service, mid, tmp_path)
