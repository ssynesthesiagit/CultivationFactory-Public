"""Pursuit: source-compiled owners, native table movement, cold choices and replay.

Dynamic authority inputs are explicit for the safe CI export.
"""
import json
from hashlib import sha256
from pathlib import Path

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.sky_treading import PURSUIT, PREFIX, TREAD_HOLD
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, turn, OWNER, ALLY, FOE
from tests.cw2_service_support import add_action

INPUTS = (
    'authority/typed_mechanics/rules_text.json',
    'authority/typed_mechanics/reviewed_final.d/riders_c7.json',
    'authority/Tianxia_Typed_Mechanics_Authority_R1.json',
)


def test_exact_printed_authority():
    texts = json.loads((ROOT / INPUTS[0]).read_text())
    assert sha256(texts[PURSUIT].encode()).hexdigest() == '0dffb16135921d7b2e6fa1490f5962423394fee17b574a8a6c4c406e1424e52c'


def fight(tmp_path, *, features=None, prepare=None, foe_talents=(), team=None, owner_speed=30, foe_x=6,
          ally_team=None, blocked=()):
    def build(bundles):
        if prepare:
            prepare(bundles)
    foe = sheet(list(foe_talents), cl=14)
    def terrain(arena):
        if blocked:
            arena.setdefault('terrain_regions', []).append({'region_id': 'pursuit_block', 'terrain_type': 'BLOCKED',
                'movement_cost': 0, 'description': 'Stone obstruction',
                'cells': [{'x': x, 'y': y} for x, y in blocked]})
    return fixture(tmp_path, [], cl=14, owner_path='Body Refining', primary='Stamina',
                   owner_features=features if features is not None else [PURSUIT],
                   owner_speed=owner_speed, foe_sheet=foe, bundle_transform=build,
                   positions={OWNER: {'x': 2, 'y': 6}, ALLY: {'x': 1, 'y': 7}, FOE: {'x': foe_x, 'y': 6}},
                   team_overrides={**({FOE: team} if team else {}), **({ALLY: ally_team} if ally_team else {})},
                   battlefield_transform=terrain, named=True)


def cold(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    return combat, TabletopService(combat, tmp_path), combat._load_session(mid)


def commit(tmp_path, mid, cid, *, pick=None, pending=False, decline=False):
    """Recreate both services before every answer, including destination settlement."""
    combat, table, loaded = cold(tmp_path, mid)
    state = table.state(mid)
    menu = state['menu']
    answers, prompts = [], []
    for _ in range(20):
        combat, table, _ = cold(tmp_path, mid)
        result = table.act(mid, cid, menu['decision_id'], menu['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            _, _, loaded = cold(tmp_path, mid)
            assert loaded.verify()['status'] == 'PASS'
            assert loaded.mechanical.replay()['status'] == 'PASS'
            return loaded.engine, prompts
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']; prompts.append(prompt)
        if pending:
            # Pending response must be durable, not an in-memory continuation.
            assert cold(tmp_path, mid)[1].state(mid)
        answer = {**prompt['context'], 'selection': 'DECLINE' if decline else 'USE'}
        options = (prompt.get('choice') or {}).get('options') or []
        if options:
            preferred = (prompt.get('choice') or {}).get('preferred') or []
            choice = pick(prompt, options) if pick else (preferred[0] if preferred else options[0]['id'])
            if choice is None:
                answer['selection'] = 'DECLINE'
            else:
                answer['option_ids'] = [choice]
        answers.append(answer)
    raise AssertionError('Unsettled Pursuit choice')


def move(tmp_path, mid, x, y=6, z=0, **kw):
    _, _, loaded = cold(tmp_path, mid)
    c = next(c for c in loaded.engine.legal_candidates()
             if c.kind == 'MOVE' and (c.destination.x, c.destination.y, c.destination.z) == (x, y, z))
    return commit(tmp_path, mid, c.candidate_id, **kw)


def action(tmp_path, mid, name, *, target=None, **kw):
    _, _, loaded = cold(tmp_path, mid)
    c = next(c for c in loaded.engine.legal_candidates() if c.display_name.startswith(name)
             and (target is None or target in c.target_ids))
    return commit(tmp_path, mid, c.candidate_id, **kw)


def chase_events(engine):
    return [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == PURSUIT]


def at(options, x, y, z=0, *, jump=None):
    """The Pursuit option whose label names this destination (ids are opaque, not coordinates)."""
    where = f"to {x},{y}" + (f",{z}" if z else "") + " ("
    for option in options:
        text_ = str(option)
        if where in text_ and (jump is None or ('jump' in text_.lower()) == jump):
            return option['id']
    raise AssertionError(f"no Pursuit option to {x},{y},{z}: {options}")


def test_cumulative_native_moves_payment_strike_and_cold_destination(tmp_path):
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    engine, prompts = move(tmp_path, mid, 7)
    assert not chase_events(engine)
    stamina = engine.state.actors[OWNER].resources['resource:core.stamina']
    ordinary = engine.state.actors[OWNER].movement_remaining_ft
    engine, prompts = move(tmp_path, mid, 8, pending=True)
    assert len(chase_events(engine)) == 1
    owner = engine.state.actors[OWNER]
    assert owner.resources['resource:core.stamina'] == stamina - 2
    assert not owner.reaction_available and owner.movement_remaining_ft == ordinary
    assert owner.turn_flags[f'once_per_round:typed.{PURSUIT}'] == engine.state.round_number
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == PURSUIT]
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert moves and len(attacks) == 1 and moves[-1].sequence < attacks[0].sequence
    assert any(p.get('choice') for p in prompts)
    engine, _ = move(tmp_path, mid, 9)
    assert len(chase_events(engine)) == 1


@pytest.mark.parametrize('team,owned', [(None, False), ('team:factory', True), ('team:neutral', True)])
def test_nonowners_allies_and_neutral_creatures_do_not_trigger(tmp_path, team, owned):
    combat, table, mid = fight(tmp_path, team=team, features=[PURSUIT] if owned else [])
    turn(table, mid, FOE)
    engine, _ = move(tmp_path, mid, 8)
    assert not chase_events(engine)


@pytest.mark.parametrize('subject,relation,destination,y,qualifies', [
    (ALLY, 'ENEMY', 3, 7, True), (FOE, 'NEUTRAL', 8, 6, False),
])
def test_native_relation_commands_override_roster_teams(tmp_path, subject, relation, destination, y, qualifies):
    combat, table, mid = fight(tmp_path)
    loaded = combat._load_session(mid)
    combat.change_relations(mid, change={'kind': 'ACTOR_RELATION', 'subject': OWNER,
                            'other': subject, 'relation': relation},
                            expected_state_version=loaded.engine.state.state_version)
    combat, table, _ = cold(tmp_path, mid)
    turn(table, mid, subject)
    engine, _ = move(tmp_path, mid, destination, y=y)
    assert bool(chase_events(engine)) is qualifies


def test_real_owned_flash_step_completed_teleport(tmp_path):
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    receipts = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.payload.get('teleport')]
    assert receipts and len(chase_events(engine)) == 1
    assert receipts[-1].sequence < chase_events(engine)[0].sequence
    assert any(p.get('choice') for p in prompts)


def test_owned_reaction_teleport_has_native_row_provenance(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Trigger attack', [{'type': 'attack', 'attack_kind': 'ranged_cultivation',
                   'count': 1, 'on_hit': []}], typed={'numbers': {'cl': 14, 'pb': 5, 'attack_bonus': 100, 'save_dc': 16}})
    combat, table, mid = fight(tmp_path, prepare=prepare,
                               foe_talents=['tianxia.talent.space.blink_guard'])
    engine, prompts = action(tmp_path, mid, 'Trigger attack', target=FOE)
    teleports = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED'
                 and e.actor_id == FOE and e.payload.get('teleport')]
    assert teleports and len(chase_events(engine)) == 1
    assert any(p['context']['reaction_source_id'] == 'choice:needle.reaction_teleport' for p in prompts)


def test_declining_threshold_does_not_reoffer_each_later_segment(tmp_path):
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    move(tmp_path, mid, 7)
    engine, prompts = move(tmp_path, mid, 8, decline=True)
    assert prompts and not chase_events(engine)
    engine, prompts = move(tmp_path, mid, 9)
    assert not prompts and not chase_events(engine)
    assert engine.state.actors[OWNER].reaction_available


def test_automatic_owner_uses_same_native_chase_without_manual_question(tmp_path):
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    engine, prompts = move(tmp_path, mid, 8)
    assert not prompts and len(chase_events(engine)) == 1
    assert engine.state.actors[OWNER].position.x > 2


@pytest.mark.parametrize('destination,qualifies', [(14, True), (15, False)])
def test_sixty_foot_trigger_boundary_uses_completed_position(tmp_path, destination, qualifies):
    combat, table, mid = fight(tmp_path, foe_x=destination-2)
    turn(table, mid, FOE)
    engine, _ = move(tmp_path, mid, destination)
    assert bool(chase_events(engine)) is qualifies


def test_chase_avoids_every_creatures_opportunity_attacks(tmp_path):
    combat, table, mid = fight(tmp_path, ally_team='team:opponents')
    turn(table, mid, FOE)
    engine, _ = move(tmp_path, mid, 8)
    assert len(chase_events(engine)) == 1
    assert engine.state.actors[ALLY].reaction_available
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == ALLY for e in engine.events)


def test_closer_destination_outside_unarmed_reach_grants_no_strike(tmp_path):
    combat, table, mid = fight(tmp_path)
    turn(table, mid, FOE)
    def pick(prompt, options):
        return (at(options, 3, 6) if prompt['context']['reaction_source_id'] == 'choice:needle.pursuit_without_horizon'
                else ((prompt.get('choice') or {}).get('preferred') or [options[0]['id']])[0])
    engine, _ = move(tmp_path, mid, 8, pick=pick)
    assert len(chase_events(engine)) == 1
    assert engine.state.actors[OWNER].position.x == 3
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER for e in engine.events)


def test_blocked_destination_is_not_offered_and_native_route_goes_around_it(tmp_path):
    combat, table, mid = fight(tmp_path, blocked=[(3, 7)])
    turn(table, mid, FOE)
    def pick(prompt, options):
        if prompt['context']['reaction_source_id'] == 'choice:needle.pursuit_without_horizon':
            with pytest.raises(AssertionError):
                at(options, 3, 7)
            return at(options, 4, 7)
        return ((prompt.get('choice') or {}).get('preferred') or [options[0]['id']])[0]
    engine, _ = move(tmp_path, mid, 8, pick=pick)
    receipt = next(e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == PURSUIT)
    assert all((p['x'], p['y']) != (3, 7) for p in receipt.payload['path'])
    assert (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y) == (4, 7)


@pytest.mark.parametrize('control', ['blinded', 'poor', 'immobile'])
def test_visibility_resources_and_failed_closer_movement(tmp_path, control):
    def prepare(bundles):
        effect = ({'type': 'spend_resource', 'resource_id': 'resource:core.stamina', 'flat': 99, 'applies_to': 'self'}
                  if control == 'poor' else {'type': 'condition', 'condition': 'blinded', 'applies_to': 'self'})
        add_action(bundles[0], 'Prepare control', [effect], target='SELF')
    combat, table, mid = fight(tmp_path, prepare=prepare if control != 'immobile' else None,
                               owner_speed=0 if control == 'immobile' else 30)
    if control != 'immobile':
        action(tmp_path, mid, 'Prepare control')
    turn(table, mid, FOE)
    before = cold(tmp_path, mid)[2].engine.state.actors[OWNER]
    engine, _ = move(tmp_path, mid, 8)
    owner = engine.state.actors[OWNER]
    if control == 'immobile':
        assert len(chase_events(engine)) == 1
        assert owner.resources['resource:core.stamina'] == before.resources['resource:core.stamina'] - 2
        assert owner.position == before.position
        assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER for e in engine.events)
    else:
        assert not chase_events(engine)
        assert owner.resources['resource:core.stamina'] == before.resources['resource:core.stamina']


@pytest.mark.parametrize('teleport', [False, True])
def test_imposed_displacement_never_triggers(tmp_path, teleport):
    def prepare(bundles):
        effect = ({'type': 'teleport', 'applies_to': 'target', 'distance_ft': 10, 'unwilling': True,
                   'forced': True, 'choose_subject_destination': True} if teleport else
                  {'type': 'forced_movement', 'applies_to': 'target', 'distance_ft': 10, 'direction': 'away'})
        add_action(bundles[0], 'Impose displacement', [effect])
    combat, table, mid = fight(tmp_path, prepare=prepare)
    engine, _ = action(tmp_path, mid, 'Impose displacement', target=FOE)
    assert not chase_events(engine)
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == FOE and e.payload.get('forced')
               for e in engine.events)


def test_off_turn_free_tread_3d_chase_and_expiry(tmp_path):
    features = [PURSUIT, PREFIX + 'tread_the_empty_sky', PREFIX + 'thousand_mile_legs']
    combat, table, mid = fight(tmp_path, features=features)
    # Actual high jump, normal paid Tread, then the hostile's turn while suspended.
    engine, _ = move(tmp_path, mid, 2, z=1)
    assert engine.state.actors[OWNER].position.z == 1
    turn(table, mid, FOE)
    before = cold(tmp_path, mid)[2].engine.state.actors[OWNER].resources['resource:core.stamina']
    def pick(prompt, options):
        if prompt['context']['reaction_source_id'] == 'choice:needle.pursuit_without_horizon':
            return at(options, 7, 6, 1)
        return ((prompt.get('choice') or {}).get('preferred') or [options[0]['id']])[0]
    engine, prompts = move(tmp_path, mid, 8, pick=pick, pending=True)
    owner = engine.state.actors[OWNER]
    assert owner.position.z == 1 and owner.position.x == 7
    assert owner.resources['resource:core.stamina'] == before - 2
    assert any(p['context']['reaction_source_id'] == 'choice:needle.pursuit_tread' for p in prompts)
    assert any(c.condition_id == TREAD_HOLD for c in owner.conditions.values())
    # Decline renewal during the next owner turn, then its deadline settles falling.
    for _ in range(8):
        combat, table, loaded = cold(tmp_path, mid)
        if loaded.engine.state.current_actor_id == OWNER:
            break
        commit(tmp_path, mid, table.state(mid)['menu']['end_turn'], pick=lambda p, opts: None)
    combat, table, _ = cold(tmp_path, mid)
    engine, _ = commit(tmp_path, mid, table.state(mid)['menu']['end_turn'], pick=lambda p, opts: None)
    assert engine.state.actors[OWNER].position.z == 0
    assert not any(c.condition_id == TREAD_HOLD for c in engine.state.actors[OWNER].conditions.values())


def test_pursuit_never_offers_a_non_closer_jump_even_with_free_tread(tmp_path):
    features = [PURSUIT, PREFIX + 'tread_the_empty_sky', PREFIX + 'thousand_mile_legs']
    _, table, mid = fight(tmp_path, features=features)
    turn(table, mid, FOE)

    engine, prompts = move(tmp_path, mid, 8, pending=True)
    offered = next(p for p in prompts
                   if p['context']['reaction_source_id'] == 'choice:needle.pursuit_without_horizon')
    from combat.ext.sky_treading import _pursuit_gap
    from combat.ext.granted_movement import choices
    owner, hostile = engine.state.actors[OWNER], engine.state.actors[FOE]
    start_gap = _pursuit_gap(engine, owner, hostile, owner.position)
    options = offered['choice']['options']
    assert options
    assert all(_pursuit_gap(engine, owner, hostile, type(owner.position)(
        x=option['cell']['x'], y=option['cell']['y'], z=option['cell'].get('z', 0))) < start_gap
               for option in options)

    # Choice transport carries destination IDs, so correlate them with native movement metadata.
    candidates = choices(engine, owner, int(engine._effective_speed(owner)))
    jump_candidates = [candidate for candidate in candidates
                       if candidate.metadata.get('movement_mode') == 'jump']
    assert jump_candidates, "fixture must offer a native jump candidate"
    non_closing_jump_cells = {
        (candidate.destination.x, candidate.destination.y, candidate.destination.z)
        for candidate in jump_candidates
        if _pursuit_gap(engine, owner, hostile, candidate.destination) >= start_gap
    }
    assert non_closing_jump_cells, "fixture must include a non-closing jump leg"
    assert not any((option['cell']['x'], option['cell']['y'], option['cell'].get('z', 0))
                   in non_closing_jump_cells for option in options)
    assert len(chase_events(engine)) == 1


@pytest.mark.parametrize('continue_flight', [False, True])
def test_off_turn_native_jump_retains_free_tread_permission(tmp_path, continue_flight):
    combat, table, mid = fight(tmp_path, features=[PURSUIT, PREFIX + 'tread_the_empty_sky',
                                                 PREFIX + 'thousand_mile_legs'])
    turn(table, mid, FOE)
    before = cold(tmp_path, mid)[2].engine.state.actors[OWNER].resources['resource:core.stamina']
    def pick(prompt, options):
        if prompt['context']['reaction_source_id'] == 'choice:needle.pursuit_without_horizon':
            return at(options, 3, 6, 1, jump=True)
        if prompt['context']['reaction_source_id'] == 'choice:needle.pursuit_continue':
            return at(options, 7, 6, 1) if continue_flight else None
        return ((prompt.get('choice') or {}).get('preferred') or [options[0]['id']])[0]
    engine, prompts = move(tmp_path, mid, 8, pick=pick, pending=True)
    owner = engine.state.actors[OWNER]
    assert (owner.position.x, owner.position.y, owner.position.z) == (7 if continue_flight else 3, 6, 1)
    assert owner.resources['resource:core.stamina'] == before - 2
    assert any(p['context']['reaction_source_id'] == 'choice:needle.pursuit_tread' for p in prompts)
    assert any(e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == PURSUIT
               and e.payload.get('movement_mode') == 'jump' for e in engine.events)
    moves = [e for e in engine.events if e.event_type == 'MOVEMENT_COMMITTED' and e.source_definition_id == PURSUIT]
    assert sum(int(e.payload['granted_cost_ft']) for e in moves) <= engine._effective_speed(owner)
    strikes = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(strikes) == int(continue_flight)
    if strikes:
        assert moves[-1].sequence < strikes[0].sequence
