"""Table regressions for hidden-square targeting and nonstacking mode narration.

The targeting cases exercise the saved-fight lock round's
remembered-square candidate seam. They exercise real casts, moves and commits.
"""
import json
import zipfile

import pytest

from combat import senses, stealth
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate4_context import build_decision_context
from combat.gate4_policy import PolicyLibrary
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import cast_sender, commit, fixed_dice
from tests.test_lock2_persistence import act

LEFT = 'actor:factory.left'
RIGHT = 'actor:factory.right'
STRIKE = 'Stone-Skipping Strike'


def table_fight(tmp_path, *, left_at=(7, 11), right_at=(15, 11), left_abilities=(),
                left_weapons=('jian', 'gun', 'gong_jian'), left_primary='Qi'):
    talents = {
        'left': ['TAL_MONKEY_STYLE_STONE_SKIPPING_STRIKE', *left_abilities],
        'right': ['TAL_DARK_PURE_DARKNESS', 'TAL_DARK_GREATER_DARKNESS', 'TAL_DARK_PERSISTENT_DARKNESS'],
    }
    for pid, owned in talents.items():
        kit = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.' + name, 'quantity': 1}
                                         for name in left_weapons]}}
        document = sheet(owned, kit=kit if pid == 'left' else None,
                         primary=left_primary if pid == 'left' else 'Qi')
        document['identity']['display_name'] = pid.title()
        folder = tmp_path / 'portable_characters' / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({'display_name': 'Hidden yard', 'width_squares': 25, 'height_squares': 25,
        'walls': [], 'starts': {'team1': [list(left_at)], 'team2': [list(right_at)]}})
    mid = combat.create_factory_match(project_ids=['left'], opponent_actor_ids=[RIGHT],
        control_modes={LEFT: 'MANUAL', RIGHT: 'MANUAL'}, arena_id='battlefield:map.hidden-yard',
        match_seed='HIDE1-TABLE')['match_id']
    return combat, TabletopService(combat, tmp_path), mid


def turn(table, mid, actor_id):
    while table.state(mid)['menu']['actor_id'] != actor_id:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'


def move_to(table, mid, at):
    state = table.state(mid)
    menu = state['menu']
    c = next(c for c in menu['moves'] if c['destination'] == {'x': at[0], 'y': at[1]})
    assert table.act(mid, c['candidate_id'], menu['decision_id'], menu['state_version'],
                     state['last_sequence'])['status'] == 'COMMITTED'


def hidden_fight(tmp_path, monkeypatch, *, move=False, right_at=(15, 11), greater_darkness=True, **setup):
    combat, table, mid = table_fight(tmp_path, right_at=right_at, **setup)
    turn(table, mid, RIGHT)
    augments = ['Augment Darkness: Persistent Darkness', 'Shape Darkness: Pure Darkness']
    if greater_darkness:
        augments.insert(0, 'Augment Darkness: Greater Darkness')
    for name in augments:
        commit(cast_sender(combat, table, mid, name))
    name = 'Darkness + Greater Darkness + Persistent Darkness' if greater_darkness else 'Darkness + Persistent Darkness'
    commit(cast_sender(combat, table, mid, name, at=right_at))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, RIGHT)
    # Preserve natural 20s, and pass the owner's new pre-attack percentile check.
    fixed_dice(monkeypatch, [100] * 60)
    commit(cast_sender(combat, table, mid, 'Hide'))
    if move:
        move_to(table, mid, (right_at[0] + 1, right_at[1]))
    assert act(table, mid, 'end')['status'] == 'COMMITTED'
    turn(table, mid, LEFT)
    e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    actor, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    assert stealth.hidden(target)
    assert not stealth.sees(e, actor, target)
    assert not senses.sees_hidden(e, actor, target) and not senses.pinpoints(e, actor, target)
    return combat, table, mid


@pytest.mark.parametrize('for_ai', [False, True])
def test_in_range_remembered_square_is_offered_when_hidden_creature_moves_out_of_range(
        tmp_path, monkeypatch, for_ai):
    # Stone-Skipping Strike reaches 90 feet. Hidden movement puts Right 95 feet
    # away; the last observed square remains at 90 feet and must stay attackable.
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True,
                                     left_at=(0, 11), right_at=(18, 11))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    if for_ai:
        e = combat._load_session(mid).engine
        policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
        options = [c.model_dump(mode='json') for c in build_decision_context(e, policy, for_ai=True).legal_candidates
                   if c.display_name == STRIKE]
    else:
        options = [o for g in table.state(mid)['menu']['actions'] if g['label'] == STRIKE for o in g['options']]
    assert options, 'Hidden movement must not remove an in-range remembered-square attack'
    assert any(o['destination'] == {'x': 18, 'y': 11} for o in options)


def test_ai_context_remembers_position_instead_of_exposing_hidden_movement(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True)
    e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    context = build_decision_context(e, policy, for_ai=True)
    target = next(a for a in context.actors if a.entity_id == RIGHT)
    assert e.state.actors[RIGHT].position.model_dump() == {'x': 16, 'y': 11}
    assert target.position.model_dump() == {'x': 15, 'y': 11}, \
        'AI must receive the observed square rather than the hidden creature position'


def test_ai_recent_events_do_not_disclose_hidden_movement_after_reload(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True)
    e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    context = build_decision_context(e, policy, for_ai=True)
    # The authoritative journal keeps the movement for replay. A controller
    # must receive an observation-safe projection, without its destination/path.
    movement = [v for v in e.events if v.actor_id == RIGHT and v.event_type == 'MOVEMENT_COMMITTED']
    assert movement and movement[-1].payload['destination'] == {'x': 16, 'y': 11}
    assert not [v for v in context.recent_events
                if v.get('actor_id') == RIGHT and v.get('event_type') == 'MOVEMENT_COMMITTED'
                and any(v.get('payload', {}).get(k) for k in ('destination', 'path'))], \
        'AI recent events must not reveal an unobserved destination or movement path'


def test_ai_movement_adjacency_uses_last_observed_square_after_reload(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_at=(10, 11))
    e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    context = build_decision_context(e, policy, for_ai=True)
    # This reachable cell is adjacent to the observed (15, 11), but not the
    # hidden current (16, 11). Its tactical score must not track the secret move.
    option = next(c for c in context.legal_candidates if c.destination
                  and c.destination.x == 14 and c.destination.y == 10 and c.kind.value == 'MOVE')
    assert option.metadata['adjacent_hostiles'] == 1, \
        'Movement scoring must use the last observed hostile square'


def test_menu_and_ai_context_reads_preserve_hidden_table_journal(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    session = combat._load_session(mid)
    before = session.engine.state.model_dump(mode='json')
    journals = {name: (session.store.match_dir / name).read_bytes()
                for name in ('Journal.ndjson', 'ControllerJournal.ndjson')}
    policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
    for _ in range(2):
        table.state(mid)
        build_decision_context(combat._load_session(mid).engine, policy, for_ai=True)
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.engine.state.model_dump(mode='json') == before
    for name, content in journals.items():
        assert (reloaded.store.match_dir / name).read_bytes() == content
    assert reloaded.mechanical.replay()['status'] == 'PASS'


def test_unseen_contact_commits_and_reloads_without_repeated_blocked_moves(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_at=(13, 11))
    move_to(table, mid, (16, 11))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    session = combat._load_session(mid)
    actor = session.engine.state.actors[LEFT]
    assert actor.position.model_dump() == {'x': 15, 'y': 11}
    assert actor.turn_flags['unseen_blockers'][RIGHT] == {'x': 16, 'y': 11}
    assert session.engine.state.observations[actor.team_id][RIGHT].model_dump() == {'x': 16, 'y': 11}
    assert not any(c['destination'] == {'x': 16, 'y': 11} for c in table.state(mid)['menu']['moves'])
    assert session.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('sense, ability, sees', [
    ('blindsight', 'Sight Beyond Sight: Blindsight (expend Martial Focus)', True),
    ('tremorsense', 'Sight Beyond Sight: Tremorsense', False),
])
def test_sense_activation_still_targets_moved_hidden_creature_after_table_reload(
        tmp_path, monkeypatch, sense, ability, sees):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_at=(13, 11),
                                     left_abilities=('TAL_THE_HIDDEN_EYE_SIGHT_BEYOND_SIGHT',))
    # The defender hid before this sense was activated. Pure Darkness halves
    # its 30-foot range to 15 feet, exactly the distance to the moved defender.
    commit(cast_sender(combat, table, mid, ability))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    e = combat._load_session(mid).engine
    viewer, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    assert stealth.hidden(target)
    assert senses.reach(e, viewer, sense, target) == 15
    assert senses.sees_hidden(e, viewer, target) is sees
    assert senses.pinpoints(e, viewer, target) is (not sees)
    assert e._attack_mode(viewer, target) == ('NORMAL' if sees else 'DISADVANTAGE')
    options = [o for g in table.state(mid)['menu']['actions'] if g['label'] == STRIKE for o in g['options']]
    assert any(RIGHT in o['target_ids'] and o['destination'] is None for o in options)
    before = target.current_hp
    sequence = table.state(mid)['last_sequence']
    commit(cast_sender(combat, table, mid, STRIKE, target=RIGHT))
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.engine.state.actors[RIGHT].current_hp < before
    attacks = [v for v in reloaded.engine.events if v.sequence > sequence and v.event_type == 'ATTACK_ROLLED']
    # Blindsight sees the defender, while the defender cannot see the attacker
    # inside Darkness: the actual roll gains Advantage. Tremorsense only
    # pinpoints, so Hidden still supplies Disadvantage.
    assert len(attacks) == 1 and attacks[0].payload['mode'] == ('ADVANTAGE' if sees else 'DISADVANTAGE')
    assert reloaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('feature, sense, left_at, right_at, approach, reach', [
    ('tianxia.path.spirit_awakening.feature.spiritual_sense', 'spiritual_sense',
     (10, 11), (15, 11), (15, 11), 5),
    ('TAL_THE_HIDDEN_EYE_TRUE_SIGHT', 'truesight', (0, 11), (13, 11), (6, 11), 60),
])
def test_passive_sense_locates_hidden_creature_when_attacker_moves_into_range(
        tmp_path, monkeypatch, feature, sense, left_at, right_at, approach, reach):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_at=left_at,
                                     right_at=right_at, left_abilities=(feature,))
    move_to(table, mid, approach)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    e = combat._load_session(mid).engine
    viewer, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    assert stealth.hidden(target)
    assert senses.reach(e, viewer, sense, target) == reach
    assert senses.sees_hidden(e, viewer, target)
    options = [o for g in table.state(mid)['menu']['actions'] if g['label'] == STRIKE for o in g['options']]
    assert any(RIGHT in o['target_ids'] and o['destination'] is None for o in options)
    before = target.current_hp
    commit(cast_sender(combat, table, mid, STRIKE, target=RIGHT))
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.engine.state.actors[RIGHT].current_hp < before
    assert reloaded.mechanical.replay()['status'] == 'PASS'


@pytest.mark.parametrize('for_ai', [False, True])
@pytest.mark.parametrize('sense, activation, can_see', [
    pytest.param('none', None, False),
    pytest.param('tremorsense', 'Sight Beyond Sight: Tremorsense', False),
    ('blindsight', 'Sight Beyond Sight: Blindsight (expend Martial Focus)', True),
])
def test_seen_target_attack_allows_known_square_under_owner_targeting_ruling(
        tmp_path, monkeypatch, for_ai, sense, activation, can_see):
    # SOL132 owner ruling overrides seen-only printed targeting for attack rolls.
    # Tremorsense pinpoints the creature; without it an attack uses the last square.
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True, left_at=(13, 11),
        left_abilities=('INK_BASE_INK_LASH', 'TAL_THE_HIDDEN_EYE_SIGHT_BEYOND_SIGHT'))
    if activation:
        commit(cast_sender(combat, table, mid, activation))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    session = combat._load_session(mid)
    e = session.engine
    viewer, target = e.state.actors[LEFT], e.state.actors[RIGHT]
    assert stealth.hidden(target)
    assert senses.sees_hidden(e, viewer, target) is can_see
    assert senses.pinpoints(e, viewer, target) is (sense == 'tremorsense')
    # Confirm that the compiled attack exists; an unowned/missing ability must
    # not make the exclusion assertion pass vacuously.
    assert any(a.owner_id == LEFT and a.display_name == 'Ink Lash'
               for a in e.action_catalog.values())
    if for_ai:
        policy, _ = PolicyLibrary(ROOT).for_actor(LEFT)
        options = [c.model_dump(mode='json')
                   for c in build_decision_context(e, policy, for_ai=True).legal_candidates
                   if c.display_name == 'Ink Lash' and RIGHT in c.target_ids]
    else:
        options = [o for g in table.state(mid)['menu']['actions'] if g['label'] == 'Ink Lash'
                   for o in g['options'] if RIGHT in o['target_ids']]
    assert options, 'Attack rolls may aim at a known square under the 2026-10-06 ruling'
    if not can_see and sense != 'tremorsense':
        assert all(o['destination'] == {'x': 15, 'y': 11} for o in options)
    if can_see:
        assert all(o['destination'] is None for o in options)
        hp = target.current_hp
        commit(cast_sender(combat, table, mid, 'Ink Lash', target=RIGHT))
        reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert reloaded.engine.state.actors[RIGHT].current_hp < hp
        assert reloaded.mechanical.replay()['status'] == 'PASS'


def test_manual_menu_offers_last_seen_square_after_hide_move_reload(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True)
    # A new service verifies this is the saved table state, not an in-memory menu.
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    option = next(g['options'][0] for g in table.state(mid)['menu']['actions'] if g['label'] == STRIKE)
    assert option['destination'] == {'x': 15, 'y': 11}
    assert 'last saw Right' in option['label']


@pytest.mark.parametrize('auto', [False, True])
def test_hidden_move_attack_misses_through_table_commit_reload(tmp_path, monkeypatch, auto):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch, move=True)
    prior = combat._load_session(mid).engine
    before = prior.state.actors[RIGHT].current_hp
    resources = dict(prior.state.actors[LEFT].resources)
    sequence, rolls = prior.state.event_sequence, prior.roller.counter
    state = table.state(mid)
    menu = state['menu']
    c = next(c for c in combat._load_session(mid).engine.legal_candidates()
             if c.display_name == STRIKE and RIGHT in c.target_ids)
    if auto:
        combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
        original = combat.controller

        class StrikeController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(original, name)

        combat.controller = StrikeController()
        send = lambda answers=(): table.auto_step(mid, 0, list(answers))
    else:
        send = lambda answers=(): table.act(mid, c.candidate_id, menu['decision_id'], menu['state_version'],
                                           state['last_sequence'], list(answers))
    commit(send)
    e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert e.state.actors[RIGHT].position.model_dump() == {'x': 16, 'y': 11}
    assert e.state.actors[RIGHT].current_hp == before
    assert not e.state.actors[LEFT].action_available
    action = e.action_catalog[c.source_definition_id]
    for resource, amount in prior.effective_costs(prior.state.actors[LEFT], action.source_definition_id, action.costs):
        assert e.state.actors[LEFT].resources[resource] == resources[resource] - amount
    added = [event for event in e.events if event.sequence > sequence]
    assert any(event.event_type == 'ATTACK_LOCATION_MISSED' for event in added)
    assert not any(event.event_type in ('ATTACK_ROLLED', 'DAMAGE_COMMITTED', 'REACTION_RESOLVED') for event in added)
    assert e.roller.counter == rolls
    assert CombatService(ROOT, tmp_path)._load_session(mid).verify()['status'] == 'PASS'


def test_redundant_strike_disadvantage_is_narrated_once_after_table_reload(tmp_path, monkeypatch):
    combat, table, mid = hidden_fight(tmp_path, monkeypatch)
    hp = combat._load_session(mid).engine.state.actors[RIGHT].current_hp
    before = table.state(mid)['last_sequence']
    commit(cast_sender(combat, table, mid, STRIKE, target=RIGHT))
    e = CombatService(ROOT, tmp_path)._load_session(mid).engine
    # A hidden creature that remains in its last-seen square can still be hit.
    assert e.state.actors[RIGHT].current_hp < hp
    applied = [v for v in e.events if v.sequence > before and v.event_type == 'MODIFIER_APPLIED'
               and v.payload.get('target_field') == 'attack_mode' and v.payload.get('value') == 'DISADVANTAGE']
    # Long range and unseen target are separate mechanical causes of the same mode.
    assert len(applied) == 2
    attacks = [v for v in e.events if v.sequence > before and v.event_type == 'ATTACK_ROLLED']
    assert len(attacks) == 1 and attacks[0].payload['mode'] == 'DISADVANTAGE'
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    feed = table.events(mid, before)['events']
    lines = [v['summary'] for v in feed]
    # The printed Strike rule makes a ranged weapon attack, not a penalty on
    # its user. Long range and the unseen target affect this attack's roll;
    # MMX75 names the attack rather than blaming the ability for the penalty.
    assert sum("Left's Stone-Skipping Strike is made with Disadvantage on the attack roll"
               in s for s in lines) == 1, lines
    assert not any('disadvantage on attack rolls from Stone-Skipping Strike' in s for s in lines)
    assert sum('The effect of Stone-Skipping Strike ended for Left' in s for s in lines) == 1
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()['status'] == 'PASS'
