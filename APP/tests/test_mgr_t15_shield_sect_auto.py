"""Source-owned Shield/Sect table contracts, using real seat routing and cold mechanical replay.

The API provider is a fake transport. Local selection asserts against the actual standard AI context;
neither path changes control mode to submit an action, bypasses legality, or calls a live model.
"""
import json
import zipfile

import pytest

from combat import armour, carry
from combat.ext.hand_occupancy import occupancy
from combat.ext.sect_stewardship import MERIT, SECT_KEY
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import AI_RESPONSE_SCHEMA, CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

SHIELD = 'SHIELD_BASE_SHIELD_TRAINING'
SECT = 'SECT_STEWARDSHIP_BASE_SECT_CHECK'
ME, FOE = 'actor:factory.mgr15', 'actor:factory.mgr15-foe'
BARE, PAID = 'Sect Check', 'Sect Check (spend 1 Merit Die)'


def game(tmp_path, source, *, shields=False):
    kit = {'items': [
        {'item_id': 'tianxia.mortal.armor.shield', 'name': name, 'quantity': 1}
        for name in ('Oak Shield', 'Iron Shield')]} if shields else None
    docs = [sheet([source], cl=18, score=18, kit=kit, name='Trained owner'),
            sheet([], cl=18, score=18, kit=kit, name='Untrained carrier')]
    bundles = []
    for aid, doc in zip((ME, FOE), docs):
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={'ask': True}))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME: 'a', FOE: 'b'},
        {ME: {'x': 3, 'y': 6}, FOE: {'x': 12, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME], [FOE],
        control_modes={ME: 'MANUAL', FOE: 'MANUAL'}, match_seed='MGR15',
        display_name='Shield and Sect contracts', maximum_rounds=20)['match_id']
    while combat.decision(mid)['context']['active_actor_id'] != ME:
        step(combat, table, mid, 'MANUAL', kind='END_TURN')
    return combat, table, mid


def cold(combat, table, mid):
    fresh = CombatService(ROOT, combat.userdata_root)
    session = fresh._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    table.combat = fresh
    return fresh, session.engine


def step(combat, table, mid, mode, label=None, *, kind=None, accept=True, answers=()):
    context = combat.decision(mid)['context']
    selected = next(c for c in context['legal_candidates']
                    if (c['kind'] == kind if kind else c['display_name'] == label))
    if mode == 'MANUAL':
        return table.act(mid, selected['candidate_id'], context['decision_id'], context['state_version'],
                         table.state(mid)['last_sequence'], list(answers))
    real = combat.controller

    def primary(ctx):
        # This fails before the fix: the caller really receives the standard filtered AI context.
        assert selected['candidate_id'] in {c.candidate_id for c in ctx.legal_candidates}
        return selected['candidate_id'], ()

    def reaction(ctx):
        decision = real.choose_reaction(ctx).decision
        if not accept and ctx.reaction_source_id == 'choice:needle.sect_stewardship.add_merit_die':
            return decision.model_copy(update={'selection': 'DECLINE', 'option_ids': ()})
        return decision

    combat.controller = ManualControllerAdapter(primary, reaction_chooser=reaction)

    class Provider:
        def status(self):
            return {'ready': True}

        def complete_json(self, **kwargs):
            frame = json.loads(kwargs['prompt_text'].split('\n\n', 1)[1])
            assert selected['candidate_id'] in {c['candidate_id'] for c in frame['legal_candidates']}
            return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': {
                'decision_id': frame['decision_id'], 'state_version': frame['state_version'],
                **{key: selected[key] for key in ('candidate_id', 'actor_id', 'target_ids', 'destination')},
                'option_ids': []}}}

    combat.ai_provider = Provider()
    try:
        return table.auto_step(mid, table.state(mid)['last_sequence'], list(answers))
    finally:
        combat.controller = real


def next_turn(combat, table, mid, mode):
    assert step(combat, table, mid, mode, kind='END_TURN')['status'] == 'COMMITTED'
    for _ in range(5):
        if combat.decision(mid)['context']['active_actor_id'] == ME:
            return
        assert step(combat, table, mid, 'MANUAL', kind='END_TURN')['status'] == 'COMMITTED'
    pytest.fail('owner turn did not return')


def ac(engine, aid):
    actor = engine.state.actors[aid]
    return actor.armor_class + engine._ac_modifier(actor)


def shield_hands(engine, aid):
    return [who for values in occupancy(engine, engine.state.actors[aid]).values()
            for who in values if who.startswith('shield:')]


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO', 'API_AUTO'])
def test_two_owned_shields_carry_wield_swap_action_ac_and_cold_replay(tmp_path, mode):
    combat, table, mid = game(tmp_path, SHIELD, shields=True)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode=mode)
    combat, engine = cold(combat, table, mid)
    actor = engine.state.actors[ME]
    items = [item for item in carry.carrying_of(engine, ME)['items'] if item.get('shield')]
    assert len(items) == 2 and items[0]['key'] != items[1]['key']
    assert len(shield_hands(engine, ME)) == len(shield_hands(engine, FOE)) == 1
    assert carry.holds(engine, actor, items[1]['key'])
    assert carry.owned_item_location(actor, items[1]['key']) == 'carried'
    assert ac(engine, ME) == ac(engine, FOE) + 2
    weight = carry.weight(engine, actor)
    labels = {c['display_name'] for c in combat.decision(mid)['context']['legal_candidates']}
    assert 'Don Iron Shield 2 (Utilize Action)' not in labels
    assert step(combat, table, mid, mode, 'Doff Oak Shield 1 (Utilize Action)')['status'] == 'COMMITTED'
    combat, engine = cold(combat, table, mid)
    assert not engine.state.actors[ME].action_available
    assert not shield_hands(engine, ME)
    assert ac(engine, ME) == ac(engine, FOE)
    assert carry.weight(engine, engine.state.actors[ME]) == weight
    next_turn(combat, table, mid, mode)
    labels = {c['display_name'] for c in combat.decision(mid)['context']['legal_candidates']}
    assert {'Don Oak Shield 1 (Utilize Action)', 'Don Iron Shield 2 (Utilize Action)'} <= labels
    assert step(combat, table, mid, mode, 'Don Iron Shield 2 (Utilize Action)')['status'] == 'COMMITTED'
    combat, engine = cold(combat, table, mid)
    assert not engine.state.actors[ME].action_available
    assert shield_hands(engine, ME) == ['shield:' + items[1]['key']]
    assert armour.shield_item_key(engine, engine.state.actors[ME]) == items[1]['key']
    assert ac(engine, ME) == ac(engine, FOE) + 2
    next_turn(combat, table, mid, mode)
    labels = {c['display_name'] for c in combat.decision(mid)['context']['legal_candidates']}
    assert 'Don Oak Shield 1 (Utilize Action)' not in labels
    assert 'Doff Iron Shield 2 (Utilize Action)' in labels


@pytest.mark.parametrize('mode', ['MANUAL', 'LOCAL_AUTO', 'API_AUTO'])
@pytest.mark.parametrize('paid,accept', [(True, True), (False, True), (False, False)])
def test_source_owned_sect_before_after_accept_decline_one_die_and_cold_replay(tmp_path, mode, paid, accept):
    combat, table, mid = game(tmp_path, SECT)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode=mode)
    assert step(combat, table, mid, mode, 'Sect Stewardship: choose Intelligence')['status'] == 'COMMITTED'
    combat, engine = cold(combat, table, mid)
    assert engine.state.actors[ME].resources[SECT_KEY] == 1
    before = engine.state.actors[ME].resources[MERIT]
    result = step(combat, table, mid, mode, PAID if paid else BARE, accept=accept)
    if mode == 'MANUAL' and not paid:
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        assert prompt['context']['reactor_id'] == ME
        assert 'Sect Check' in prompt['moment'] and 'Spend 1 Merit Die' in prompt['moment']
        combat, engine = cold(combat, table, mid)
        assert not [event for event in engine.events if event.event_type == 'CHECK_ROLLED']
        answer = {**prompt['context'], 'selection': 'USE' if accept else 'DECLINE',
                  'option_ids': ['add'] if accept else []}
        result = step(combat, table, mid, mode, BARE, answers=[answer])
    assert result['status'] == 'COMMITTED', result
    combat, engine = cold(combat, table, mid)
    event = [event for event in engine.events if event.event_type == 'CHECK_ROLLED'][-1]
    dice = [roll for roll in engine.rolls if str(roll.reason).startswith('MERIT_DIE:')]
    spent = int(paid or accept)
    assert len(dice) == spent
    merit = int(dice[0].total) if spent else 0
    assert event.payload['merit_die'] == merit
    roll = event.payload['actor']
    assert roll['total'] == roll['natural_result'] + 4 + 4 + merit
    assert engine.state.actors[ME].resources[MERIT] == before - spent
    assert not engine.state.actors[ME].action_available
