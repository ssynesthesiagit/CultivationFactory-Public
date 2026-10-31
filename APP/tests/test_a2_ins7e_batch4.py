"""Red Execution Discipline: actual service commits, choices and cold replay."""
import pytest

from combat.ext import red_execution as plug
from combat.typed_executor import mark_condition_id
from tests.auto_worker1_support import LEFT, RIGHT, act, action_sender, fight, reload, resolve, turn, cell_send


def fresh(c, mid):
    session = c._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return reload(c, mid)


def fixture(tmp_path, *, owns=True, source='TAL_AXES_HEADSMAN_S_MANDATE', attached=False, real=False,
            empowered=False, focus_drain=False, fixed_primary=False):
    def sheet(doc, aid):
        if aid == LEFT:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = [plug.FEATURE] if owns else []
            if empowered:
                doc['spheres_and_talents']['cultivation_insight_record_ids'].append('insight.legacy-empowered-technique')
    def bundle(b):
        if b['actor_id'] == RIGHT and focus_drain:
            import copy
            drain = copy.deepcopy(next(a for a in b['action_catalog'] if a['display_name'] == 'Cause'))
            drain.update(source_definition_id='action:test.focus_drain', display_name='Focus Drain')
            drain['parameters']['typed']['effects'] = [{'type': 'spend_resource', 'resource_id': plug.FOCUS,
                                                       'flat': 1, 'applies_to': 'target'}]
            b['action_catalog'].append(drain)
            b['actor_template']['action_ids'].append(drain['source_definition_id'])
        if b['actor_id'] == LEFT:
            for action in b['action_catalog']:
                if real:
                    (action['parameters'].get('typed') or {}).setdefault('numbers', {})['attack_bonus'] = 100
                    if (action['parameters'].get('typed') or {}).get('weapon'):
                        action['parameters']['typed']['weapon']['attack_bonus'] = 100
                if action['display_name'] == 'Strike':
                    action['parameters']['typed']['source'] = source
                    action['parameters']['typed']['numbers']['attack_bonus'] = 100
                    if empowered:
                        action['parameters']['typed']['sphere'] = 'tianxia.sphere.axes'
                    if fixed_primary:
                        action['parameters']['typed']['weapon'] = {
                            'damage': {'count': 1, 'sides': 6, 'modifier': 0},
                            'fixed_damage': 1, 'damage_type': 'SLASHING', 'attack_bonus': 100}
    damage = {'type': 'damage', 'dice': {'count': 2, 'sides': 6},
              'damage_types': ['slashing'], 'applies_to': 'target'}
    on_hit = [damage]
    if attached:
        on_hit = [{'type': 'damage', 'flat': 1, 'damage_types': ['slashing']},
                  {**damage, 'type': 'extra_damage', 'source_modifier': 'TAL_AXES_RENDING_HEW'}]
        if fixed_primary:
            on_hit[0] = {'type': 'damage', 'weapon_damage': True, 'damage_types': ['slashing']}
    return fight(tmp_path, sheet_edit=sheet, bundle_edit=bundle, reaction_ask=True,
        talents=['TAL_AXES_HEADSMAN_S_MANDATE', 'TAL_AXES_HEWING_STRIKE', 'TAL_AXES_RENDING_HEW'] if real else (),
        left_kit={'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]} if real else None,
        right_talents=['TAL_SPACE_FOLD_STEP'],
        prepare_target='ANY_CREATURE', prepare=[
            {'type': 'mark', 'mark': 'Execution Mark', 'applies_to': 'target',
             'duration': {'kind': 'until_start_of_your_next_turn'}},
            # The established Execution Mark source records its printed
            # "counts as Bite" permission as a separate co-expiring Bite row.
            *([{'type': 'mark', 'mark': 'Bite', 'applies_to': 'target',
                 'duration': {'kind': 'until_start_of_your_next_turn'}}] if real else []),
            {'type': 'spend_resource', 'resource_id': plug.FOCUS, 'flat': 1, 'applies_to': 'self'}],
        cause_target='ANY_CREATURE', cause=[{'type': 'condition', 'condition': 'invisible',
            'applies_to': 'target', 'duration': {'kind': 'until_removed'}}],
        extra_actions=[
            ('Strike', {'target_kind': 'HOSTILE_ENTITY', 'effects': [{'type': 'attack',
                'attack_kind': 'cultivation_melee', 'on_hit': on_hit}]}),
            ('Drop', {'target_kind': 'ANY_CREATURE', 'effects': [{'type': 'damage', 'flat': 9999,
                'damage_types': ['force'], 'applies_to': 'target'}]}),
            ('Focus Spend', {'effects': [{'type': 'spend_resource', 'resource_id': plug.FOCUS,
                'flat': 1, 'applies_to': 'self'}]}),
            ('Session', {'effects': [{'type': 'cultivation_session_completed', 'completed': 1}]}),
            ('Incomplete Session', {'effects': [{'type': 'cultivation_session_completed', 'completed': 0}]}),
            ('Teleport', {'target_kind': 'SELF', 'effects': [{'type': 'teleport', 'distance_ft': 5,
                'applies_to': 'self'}]})])


def mark(c, t, mid, owner=True):
    resolve(lambda a: act(t, mid, 'Prepare', a, target_id=RIGHT if owner else LEFT))
    assert any(c.condition_id == mark_condition_id('Execution Mark', LEFT)
               for c in fresh(c, mid).state.actors[RIGHT if owner else LEFT].conditions.values())


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('trigger', ['zero', 'invisible'])
def test_mark_triggers_free_optional_focus_offturn_and_reload(tmp_path, ai, trigger):
    c, t, mid = fixture(tmp_path)
    mark(c, t, mid)
    before = fresh(c, mid).state.actors[LEFT]
    assert before.resources[plug.FOCUS] == 0
    if trigger == 'zero':
        _, prompts = resolve(action_sender(c, t, mid, 'Drop', target_id=RIGHT, ai=ai))
    else:
        turn(t, mid, RIGHT)
        if ai:
            c.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
        _, prompts = resolve(lambda a: act(t, mid, 'Cause', a, target_id=RIGHT))
    actor = fresh(c, mid).state.actors[LEFT]
    assert actor.resources[plug.FOCUS] == 1
    assert actor.reaction_available == before.reaction_available
    assert bool(prompts) != ai
    if prompts:
        assert 'Red Execution Discipline' in str(prompts) and 'Visitor' in str(prompts)


@pytest.mark.parametrize('owns,correct_mark,decline', [(False, True, False), (True, False, False), (True, True, True)])
def test_focus_gates_and_decline(tmp_path, owns, correct_mark, decline):
    c, t, mid = fixture(tmp_path, owns=owns)
    mark(c, t, mid, correct_mark)
    turn(t, mid, RIGHT)
    _, prompts = resolve(lambda a: act(t, mid, 'Cause', a, target_id=RIGHT),
                         {plug.RECOVER: []} if decline else None)
    assert fresh(c, mid).state.actors[LEFT].resources[plug.FOCUS] == 0
    assert bool(prompts) == decline


@pytest.mark.parametrize('attached,result,ai', [(False, 'original', False), (False, 'new', False),
    (True, 'original', False), (True, 'new', False), (True, 'new', True)])
def test_every_die_and_both_results_single_use_cold_reload(tmp_path, attached, result, ai):
    c, t, mid = fixture(tmp_path, attached=attached,
        source='TAL_AXES_HEWING_STRIKE' if attached else 'TAL_AXES_HEADSMAN_S_MANDATE')
    mark(c, t, mid)
    _, prompts = resolve(action_sender(c, t, mid, 'Strike', target_id=RIGHT, ai=ai),
        {plug.DIE: ['1'], plug.RESULT: [result]})
    e = fresh(c, mid)
    receipts = [ev for ev in e.events if ev.source_definition_id == plug.FEATURE
                and 'damage_adjustment' in ev.payload]
    assert len(receipts) == 1
    if not ai:
        die_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == plug.DIE)
        assert {o['id'] for o in die_prompt['choice']['options']} == {'0', '1'}
        result_prompt = next(p for p in prompts if p['context']['reaction_source_id'] == plug.RESULT)
        assert {o['id'] for o in result_prompt['choice']['options']} == {'original', 'new'}
        receipt = receipts[0].payload
        original = next(r for r in e.rolls if r.roll_id == receipt['original_roll_id'])
        replacement = next(r for r in e.rolls if r.reason == 'DAMAGE_REROLL:' + plug.FEATURE)
        assert receipt['damage_adjustment'] == (replacement.total - original.dice[1] if result == 'new' else 0)
    else:
        assert not prompts
    assert any(c.condition_id == plug.USED for c in e.state.actors[LEFT].conditions.values())
    if ai:
        # The helper selects its candidate from a MANUAL menu before switching
        # to LOCAL_AUTO; put the already-tested owner back into that menu first.
        c.set_controller_mode(mid, actor_id=LEFT, controller_mode='MANUAL')
    _, later = resolve(action_sender(c, t, mid, 'Strike', target_id=RIGHT, ai=ai))
    assert not later
    assert len([ev for ev in fresh(c, mid).events if ev.source_definition_id == plug.FEATURE
                and 'damage_adjustment' in ev.payload]) == 1


@pytest.mark.parametrize('owns,source', [(False, 'TAL_AXES_HEADSMAN_S_MANDATE'), (True, 'TAL_AXES_HEWING_STRIKE')])
def test_unowned_or_other_hit_does_not_reroll(tmp_path, owns, source):
    c, t, mid = fixture(tmp_path, owns=owns, source=source)
    mark(c, t, mid)
    _, prompts = resolve(lambda a: act(t, mid, 'Strike', a, target_id=RIGHT))
    assert not prompts
    assert not any(c.condition_id == plug.USED for c in fresh(c, mid).state.actors[LEFT].conditions.values())


def test_decline_preserves_use_and_only_completed_session_refreshes(tmp_path):
    c, t, mid = fixture(tmp_path)
    mark(c, t, mid)
    resolve(lambda a: act(t, mid, 'Strike', a, target_id=RIGHT), {plug.DIE: []})
    assert not any(c.condition_id == plug.USED for c in fresh(c, mid).state.actors[LEFT].conditions.values())
    resolve(lambda a: act(t, mid, 'Strike', a, target_id=RIGHT))
    resolve(lambda a: act(t, mid, 'Incomplete Session', a))
    assert any(c.condition_id == plug.USED for c in fresh(c, mid).state.actors[LEFT].conditions.values())
    resolve(lambda a: act(t, mid, 'action:test.worker1.extra.Session', a))
    assert not any(c.condition_id == plug.USED for c in fresh(c, mid).state.actors[LEFT].conditions.values())
    resolve(lambda a: act(t, mid, 'Strike', a, target_id=RIGHT))
    assert len([ev for ev in fresh(c, mid).events if ev.source_definition_id == plug.FEATURE
                and 'damage_adjustment' in ev.payload]) == 2


def test_focus_at_max_and_invisibility_refresh_are_inert(tmp_path):
    c, t, mid = fixture(tmp_path, focus_drain=True)
    mark(c, t, mid)
    turn(t, mid, RIGHT)
    resolve(lambda a: act(t, mid, 'Cause', a, target_id=RIGHT))
    _, prompts = resolve(lambda a: act(t, mid, 'Cause', a, target_id=RIGHT))
    assert not prompts and fresh(c, mid).state.actors[LEFT].resources[plug.FOCUS] == 1
    # Spend while the same Execution Mark and Invisible instances remain.
    # The full-resource gate must not mask the becoming-Invisible boundary.
    resolve(lambda a: act(t, mid, 'Focus Drain', a, target_id=LEFT))
    e = fresh(c, mid)
    assert e.state.actors[LEFT].resources[plug.FOCUS] == 0
    assert any(row.condition_id == mark_condition_id('Execution Mark', LEFT)
               for row in e.state.actors[RIGHT].conditions.values())
    assert any(row.condition_id in {'condition:typed.invisible', 'condition:core.invisible'}
               for row in e.state.actors[RIGHT].conditions.values())
    recovery_count = sum(ev.source_definition_id == plug.FEATURE and
                         ev.event_type == 'RESOURCE_GAINED' for ev in e.events)
    assert recovery_count == 1
    _, prompts = resolve(lambda a: act(t, mid, 'Cause', a, target_id=RIGHT))
    after = fresh(c, mid)
    assert not prompts and after.state.actors[LEFT].resources[plug.FOCUS] == 0
    assert sum(ev.source_definition_id == plug.FEATURE and
               ev.event_type == 'RESOURCE_GAINED' for ev in after.events) == recovery_count


def test_teleport_without_target_ids_recovers_owners_focus(tmp_path):
    c, t, mid = fixture(tmp_path)
    mark(c, t, mid)
    turn(t, mid, RIGHT)
    resolve(cell_send(t, mid, 'Fold Step', (5, 6)))
    e = fresh(c, mid)
    assert e.state.actors[LEFT].resources[plug.FOCUS] == 1
    assert any(ev.event_type == 'MOVEMENT_COMMITTED' and ev.actor_id == RIGHT
               and ev.payload.get('teleport') for ev in e.events)


def test_real_compiled_headsmans_mandate_uses_single_bonus_and_cold_replay(tmp_path):
    c, t, mid = fixture(tmp_path, real=True)
    mark(c, t, mid)
    e = fresh(c, mid)
    actions = [a for a in e.action_catalog.values() if a.owner_id == LEFT
               and (a.parameters.get('typed') or {}).get('source') == 'TAL_AXES_HEADSMAN_S_MANDATE']
    assert actions
    source = actions[0].source_definition_id
    _, prompts = resolve(lambda a: act(t, mid, source, a, target_id=RIGHT))
    assert any(p['context']['reaction_source_id'] == plug.DIE for p in prompts)
    assert len([ev for ev in fresh(c, mid).events if ev.source_definition_id == plug.FEATURE
                and 'damage_adjustment' in ev.payload]) == 1


def test_real_rending_hew_variant_keeps_primary_weapon_die_reachable(tmp_path):
    c, t, mid = fixture(tmp_path, real=True)
    mark(c, t, mid)
    e = fresh(c, mid)
    action = next(a for a in e.action_catalog.values() if a.owner_id == LEFT
                  and ((a.parameters.get('typed') or {}).get('modifier') or {}).get('id') == 'TAL_AXES_RENDING_HEW'
                  and 'Focus' not in a.display_name)
    _, prompts = resolve(lambda a: act(t, mid, action.source_definition_id, a, target_id=RIGHT))
    receipt = next(ev.payload for ev in fresh(c, mid).events if ev.source_definition_id == plug.FEATURE
                   and 'original_roll_id' in ev.payload and 'damage_adjustment' in ev.payload)
    e = fresh(c, mid)
    original = next(r for r in e.rolls if r.roll_id == receipt['original_roll_id'])
    # The first eligible roll is the actual Fu weapon's damage, before the rider.
    assert original.reason.startswith('DAMAGE:' + action.source_definition_id)
    assert any(p['context']['reaction_source_id'] == plug.DIE for p in prompts)


@pytest.mark.parametrize('correct_owner', [False, True])
def test_rending_mark_requirement_preserves_owner_and_does_not_grant_insight(tmp_path, correct_owner):
    c, t, mid = fixture(tmp_path, real=True, owns=False)
    mark(c, t, mid, correct_owner)
    e = fresh(c, mid)
    sources = {a.source_definition_id for a in e.action_catalog.values() if a.owner_id == LEFT
               and ((a.parameters.get('typed') or {}).get('modifier') or {}).get('id') == 'TAL_AXES_RENDING_HEW'
               and 'Focus' not in a.display_name}
    legal = [a for a in e.legal_candidates() if a.source_definition_id in sources and RIGHT in a.target_ids]
    assert bool(legal) == correct_owner
    if correct_owner:
        _, prompts = resolve(lambda a: act(t, mid, legal[0].source_definition_id, a, target_id=RIGHT))
        assert not any(p['context']['reaction_source_id'] == plug.DIE for p in prompts)
        assert not any(c.condition_id == plug.USED for c in fresh(c, mid).state.actors[LEFT].conditions.values())
