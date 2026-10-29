"""Focus review regressions through accepted table intents and cold replay."""
import pytest

from combat.canonical import canonical_sha256
from combat.target_knowledge import knowledge
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture, candidate
from tests.test_auto2_fire import FOCUS, WARD, cold, damage, ward
from tests.test_auto77f1_fire_service import _run, _candidate

FURNACE = 'tianxia.talent.fire.furnace_heart'


def concealed_fixture(tmp_path, talents):
    def prepare(bundles):
        for b in bundles:
            if b['actor_id'] in (FOE, SECOND):
                # Keep the concealment setup through concentration checks.
                b['actor_template']['saving_throws']['CON'] = 100
                for a in b['action_catalog']:
                    if a['display_name'].startswith('Blazing Armor'):
                        a['parameters']['typed']['effects'].append({'type': 'condition', 'condition': 'invisible',
                            'applies_to': 'self', 'duration': 'one_minute'})
                b.pop('bundle_sha256', None)
                b['bundle_sha256'] = canonical_sha256(b)
    result = fixture(tmp_path, talents, foe_talents=[WARD], second_talents=[WARD],
        bundle_transform=prepare, seed='A2FIREr1-HIDDEN',
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 7, 'y': 6}, SECOND: {'x': 8, 'y': 6}})
    combat, table, mid, send, commit = result
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != OWNER:
        ward(table, mid, commit, table.state(mid)['menu']['actor_id'])
    engine = cold(combat, mid, tmp_path)
    assert all(knowledge(engine, engine.state.actors[OWNER], engine.state.actors[who]).mode == 'LAST_OBSERVED'
               for who in (FOE, SECOND))
    return result


def test_all_unperceived_area_recipients_get_no_targeted_focus_save_benefit(tmp_path):
    combat, table, mid, send, commit = concealed_fixture(tmp_path, [FOCUS, 'FIRE_TAL_FIREBALL_ART'])
    commit(candidate(table, mid, 'saving throw against your next Fire talent'))
    cold(combat, mid, tmp_path)
    choices = []
    def answer(prompt, choice, ids):
        choices.append(choice)
        return ids[:1]
    _run(table, mid, _candidate(combat, table, mid, 'Fireball', FOE), answer)
    engine = cold(combat, mid, tmp_path)
    assert not choices, 'No hidden area occupant is disclosed in a Focus picker'
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id in (FOE, SECOND)]
    assert {e.actor_id for e in saves} == {FOE, SECOND}
    assert all(e.payload['mode'] == 'NORMAL' for e in saves)
    assert all(damage(engine, who) for who in (FOE, SECOND))
    assert damage(engine, OWNER)[-1]['reduced_to'] == 4
    assert not any('white_hot_focus' in c.condition_id for c in engine.state.actors[OWNER].conditions.values())


def test_focus_advantage_cancels_unseen_disadvantage_on_one_accepted_attack(tmp_path):
    combat, table, mid, send, commit = concealed_fixture(tmp_path, [FOCUS, 'FIRE_TAL_SCORCHING_RAY_ART'])
    commit(candidate(table, mid, 'Advantage on one attack roll'))
    cold(combat, mid, tmp_path)
    choices = []
    def answer(prompt, choice, ids):
        choices.append(choice)
        return [FOE] if FOE in ids else ids[:1]
    cid = next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
               if g['label'].startswith('Scorching Ray Art') and 'Overheat' not in g['label']
               for o in g['options'] if FOE in o.get('target_ids', []))
    _run(table, mid, cid, answer)
    engine = cold(combat, mid, tmp_path)
    rolls = [e.payload for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert len(rolls) >= 2
    assert rolls[0]['mode'] == 'NORMAL'
    assert all(r['mode'] == 'DISADVANTAGE' for r in rolls[1:])
    assert len(choices) == 1
    assert {o['id'] for o in choices[0]['options']} == {FOE}, 'Only the accepted attack target is offered'
    assert not any(e.event_type == 'ATTACK_LOCATION_MISSED' for e in engine.events)
    assert damage(engine, OWNER)[-1]['reduced_to'] == 4
    assert not any('white_hot_focus' in c.condition_id for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize('overheat', [False, True])
@pytest.mark.parametrize('countered', [False, True])
@pytest.mark.parametrize('legacy', [False, True])
def test_focus_backlash_keeps_own_identity_with_furnace_and_resistance(tmp_path, overheat, countered, legacy):
    def prepare(bundles):
        for b in bundles:
            if b['actor_id'] == OWNER:
                # Overheat must not break the resistance setup before Focus settles.
                b['actor_template']['saving_throws']['CON'] = 100
            if b['actor_id'] == FOE:
                for row in b['typed_reactions']:
                    if row.get('feature_id') == 'TAL_QIWEAVING_COUNTERWEAVE':
                        row['ask'] = True
            if legacy and b['actor_id'] == OWNER:
                for a in b['action_catalog']:
                    typed = a['parameters'].get('typed') or {}
                    if str(typed.get('source') or '').split('#', 1)[0] == FOCUS:
                        for row in typed.get('effects') or []:
                            if row.get('type') == 'fire_focus_state':
                                row['type'] = 'state'
                        typed['effects'].append({'type': 'damage', 'applies_to': 'self', 'flat': 4,
                                                'damage_types': ['fire']})
            b.pop('bundle_sha256', None)
            b['bundle_sha256'] = canonical_sha256(b)
    combat, table, mid, send, commit = fixture(tmp_path, [FOCUS, FURNACE, WARD],
        foe_talents=['TAL_QIWEAVING_COUNTERWEAVE'], bundle_transform=prepare, seed='A2FIREr1-BACKLASH',
        positions={OWNER: {'x': 3, 'y': 6}, FOE: {'x': 7, 'y': 6}, SECOND: {'x': 8, 'y': 6}})
    commit(candidate(table, mid, 'Furnace Heart'))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    commit(candidate(table, mid, 'Blazing Armor'))
    commit(table.state(mid)['menu']['end_turn'])
    while table.state(mid)['menu']['actor_id'] != OWNER:
        commit(table.state(mid)['menu']['end_turn'])
    commit(candidate(table, mid, 'Advantage on one attack roll'))
    engine = cold(combat, mid, tmp_path)
    assert len(damage(engine, OWNER)) == int(legacy)
    cid = next(o['candidate_id'] for g in table.state(mid)['menu']['actions']
               if g['label'].startswith('Ignite: Push Target') and ('Overheat' in g['label']) == overheat
               for o in g['options'] if FOE in o.get('target_ids', []))
    answers = []
    for _ in range(24):
        result = send(cid, answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        reply = {**prompt['context'], 'selection': 'DECLINE'}
        if countered and 'COUNTERWEAVE' in prompt['context']['reaction_source_id'].upper():
            reply['selection'] = 'USE'
        if prompt.get('choice'):
            ids = [o['id'] for o in prompt['choice']['options']]
            reply.update(selection='USE', option_ids=[FOE] if FOE in ids else ids[:1])
        answers.append(reply)
    else:
        raise AssertionError('too many pauses')
    engine = cold(combat, mid, tmp_path)
    packets = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids
               and 'white_hot_focus' in str(e.source_definition_id)]
    assert len(packets) == 1, [(e.source_definition_id, e.payload) for e in engine.events
                             if e.event_type == 'DAMAGE_COMMITTED' and OWNER in e.target_ids]
    assert packets[0].payload['rolled_or_pending_damage'] == 4
    assert packets[0].payload['reduced_to'] == 2, 'Resistance halves Focus; Furnace never halves Focus'
    attacks = [e for e in engine.events if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OWNER]
    assert bool(attacks) == (not countered)
    if not legacy:
        assert not any('white_hot_focus' in c.condition_id for c in engine.state.actors[OWNER].conditions.values())
