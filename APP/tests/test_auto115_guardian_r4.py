"""Calamity protects native Concentration saves and uses the strongest allied aura.

All fight setup is sealed in synthetic bundles; damage and aura expiry are real
table transactions checked after commit and a fresh service replay/reload.
"""
import copy
import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT
from tests.hunt15_support import act, reload
from tests.auto_worker1_support import settle
from tests.test_auto115_guardian import CALAMITY, PRACTICE, LABEL, STATE, submit_move

WEAK = 'actor:factory.a-guardian'
STRONG = 'actor:factory.z-guardian'
ALLY = 'actor:factory.friend'
FOE = 'actor:factory.foe'


def fight(root, *, owned=True, outside=False, reverse=False, overlap=False, disadvantage=False,
          opposing_pair=False, next_mode=None):
    weak, strong = (STRONG, WEAK) if reverse else (WEAK, STRONG)
    roster = [(weak, 4, [PRACTICE, CALAMITY] if owned else []),
              *([(strong, 6, [PRACTICE, CALAMITY])] if overlap else []),
              (ALLY, 4, []), (FOE, 4, [])]
    bundles = []
    for aid, pb, talents in roster:
        doc = sheet(talents, cl=15, score=50, kit={'starting_kit': KIT})
        doc['identity'].update(proficiency_bonus=pb, display_name=aid.rsplit('.', 1)[-1].title())
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
        folder = root / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={'ask': False})
        template = next(a for a in bundle['action_catalog'] if a['resolution_kind'] == 'TYPED')
        maintain = [{'type': 'ac_bonus', 'flat': 1, 'applies_to': 'self'}]
        if disadvantage or opposing_pair:
            maintain.append({'type': 'disadvantage', 'on': 'the next Concentration saving throw'
                             if next_mode == 'DISADVANTAGE' else 'Concentration saving throws',
                             'applies_to': 'self', 'duration': 'one_minute'})
        for label, target, effects, duration in [
            ('Maintain', 'SELF', maintain, {'kind': 'one_minute', 'concentration': True}),
            *([('Concentration Advantage', 'SELF', [{'type': 'advantage',
                'on': 'the next Concentration saving throw' if next_mode == 'ADVANTAGE'
                else 'Concentration saving throws', 'applies_to': 'self', 'duration': 'one_minute'}],
                {'kind': 'instant'})] if opposing_pair else []),
            ('Hit', 'ANY_CREATURE', [{'type': 'damage', 'flat': 10, 'damage_types': ['fire'],
                                     'applies_to': 'target'}], {'kind': 'instant'}),
        ]:
            action = copy.deepcopy(template)
            action.update(source_definition_id=f'action:test.r4.{aid}.{label}', display_name=label,
                          economy='ACTION', target_kind=target, costs=[], range_ft=120)
            action['parameters'] = {'typed': {'effects': effects, 'duration': duration,
                                              'numbers': {'cl': 15, 'pb': pb, 'save_dc': 100}, 'riders': []}}
            bundle['action_catalog'].append(action)
            bundle['actor_template']['action_ids'].append(action['source_definition_id'])
        bundle.pop('bundle_sha256', None)
        bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    ids = [aid for aid, _, _ in roster]
    positions = {weak: {'x': 3, 'y': 6}, strong: {'x': 3, 'y': 4},
                 ALLY: {'x': 19 if outside else 3, 'y': 5},
                 FOE: {'x': 18 if outside else 4, 'y': 5 if outside else 6}}
    c = CombatService(ROOT, root)
    m = c._finish_factory_match(bundles, ids, {aid: 'team:foe' if aid == FOE else 'team:ally' for aid in ids},
        {aid: positions[aid] for aid in ids}, c.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'],
        [aid for aid in ids if aid != FOE], [FOE], control_modes={aid: 'MANUAL' for aid in ids},
        match_seed='SOLFAUTO115r4', display_name='Calamity regression', maximum_rounds=10)['match_id']
    return c, TabletopService(c, root), m, weak, strong


def turn(t, m, aid):
    """Advance a three- or four-creature table without assuming the roster size."""
    for _ in range(len(t.combat._load_session(m).engine.state.actors) + 1):
        if t.state(m)['menu']['actor_id'] == aid:
            return
        assert act(t, m, 'end')['status'] == 'COMMITTED'
    raise AssertionError('turn did not advance')


def plant(t, m, aid):
    turn(t, m, aid)
    settle(lambda answers: act(t, m, LABEL, answers))


def hit(c, t, m):
    turn(t, m, FOE)
    before = reload(c, m)
    first, hp = len(before.events), before.state.actors[ALLY].current_hp
    settle(lambda answers: act(t, m, 'Hit', answers, target_id=ALLY))
    after = reload(c, m)
    return hp - after.state.actors[ALLY].current_hp, after.events[first:]


@pytest.mark.parametrize('case,mode', [('inside', 'ADVANTAGE'), ('unowned', 'NORMAL'),
                                      ('outside', 'NORMAL'), ('opposed', 'NORMAL')])
def test_native_ally_concentration_after_table_commit_and_reload(tmp_path, case, mode):
    c, t, m, weak, _ = fight(tmp_path, owned=case != 'unowned', outside=case == 'outside',
                              disadvantage=case == 'opposed')
    if case != 'unowned':
        plant(t, m, weak)
    turn(t, m, ALLY)
    settle(lambda answers: act(t, m, 'Maintain', answers))
    assert reload(c, m).state.actors[ALLY].concentration is not None
    lost, events = hit(c, t, m)
    saves = [e for e in events if e.event_type == 'SAVE_ROLLED'
             and e.source_definition_id == 'system:combat.concentration' and e.actor_id == ALLY]
    assert len(saves) == 1
    assert saves[0].payload['mode'] == mode
    assert lost == (6 if case in {'inside', 'opposed'} else 10)
    assert reload(c, m).state.actors[ALLY].concentration is not None


@pytest.mark.parametrize('reverse', [False, True], ids=['weaker-id-first', 'stronger-id-first'])
def test_overlapping_allied_auras_use_highest_pb_then_fall_back_after_expiry(tmp_path, reverse):
    c, t, m, weak, strong = fight(tmp_path, overlap=True, reverse=reverse)
    plant(t, m, weak)
    plant(t, m, strong)
    assert reload(c, m).state.actors[weak].proficiency_bonus == 4
    assert reload(c, m).state.actors[strong].proficiency_bonus == 6
    lost, _ = hit(c, t, m)
    assert lost == 4, 'same aura does not stack; strongest PB 6 reduces the 10 damage'
    turn(t, m, strong)
    destination = next((r['destination']['x'], r['destination']['y']) for r in t.state(m)['menu']['moves'])
    submit_move(t, m, destination)
    state = reload(c, m).state
    assert not any(row.condition_id == STATE for row in state.actors[strong].conditions.values())
    assert any(row.condition_id == STATE for row in state.actors[weak].conditions.values())
    lost, _ = hit(c, t, m)
    assert lost == 6, 'after the stronger aura ends the remaining PB 4 applies'


def test_concentration_suppression_does_not_remove_advantage_from_other_saves(tmp_path, monkeypatch):
    from combat.ext import guardian_calamity as calamity
    c, t, m, weak, _ = fight(tmp_path)
    plant(t, m, weak)
    e = reload(c, m)
    # Isolate the existing suppression seam without modifying the engine or its
    # save roller. The field consumer itself is covered by test_riders_c14.
    monkeypatch.setattr(calamity, 'run', lambda point, engine, subject: [{'ADVANTAGE'}])
    ally = e.state.actors[ALLY]
    assert calamity.calamity_saves(e, ally, 'CON', 10, 'system:combat.concentration', {}) is None
    assert calamity.calamity_saves(e, ally, 'CON', 10, 'action:test.save', {}) == 'ADVANTAGE'


@pytest.mark.parametrize('outside', [False, True], ids=['inside-aura', 'outside-aura'])
@pytest.mark.parametrize('next_mode', [None, 'ADVANTAGE', 'DISADVANTAGE'],
                         ids=['persistent-pair', 'next-advantage', 'next-disadvantage'])
def test_opposing_concentration_sources_cancel_after_all_contributions_and_reload(tmp_path, outside, next_mode):
    from combat.concentration import MODE

    c, t, m, weak, _ = fight(tmp_path, outside=outside, opposing_pair=True, next_mode=next_mode)
    plant(t, m, weak)
    turn(t, m, ALLY)
    settle(lambda answers: act(t, m, 'Concentration Advantage', answers))
    assert act(t, m, 'end')['status'] == 'COMMITTED'
    turn(t, m, ALLY)
    settle(lambda answers: act(t, m, 'Maintain', answers))
    before = reload(c, m).state.actors[ALLY]
    rows = [row for row in before.conditions.values() if row.condition_id == MODE]
    assert {row.data['rule']['concentration_mode'] for row in rows} == {'ADVANTAGE', 'DISADVANTAGE'}
    assert len({row.source_definition_id for row in rows}) == 2
    assert sum(bool(row.data['rule']['next']) for row in rows) == int(next_mode is not None)
    subsequent = ('ADVANTAGE' if next_mode == 'DISADVANTAGE' else
                  'DISADVANTAGE' if next_mode == 'ADVANTAGE' and outside else 'NORMAL')
    for check_index, expected in enumerate(['NORMAL', subsequent]):
        lost, events = hit(c, t, m)
        saves = [event for event in events if event.event_type == 'SAVE_ROLLED'
                 and event.source_definition_id == 'system:combat.concentration' and event.actor_id == ALLY]
        assert len(saves) == 1 and saves[0].payload['mode'] == expected
        assert lost == (10 if outside else 6)
        after = reload(c, m).state.actors[ALLY]
        assert after.concentration is not None
        remaining = [row for row in after.conditions.values() if row.condition_id == MODE]
        assert len(remaining) == (1 if next_mode else 2)
        assert not any(row.data['rule']['next'] for row in remaining)
        consumed = [event for event in events if event.event_type == 'CONDITION_REMOVED'
                    and event.payload.get('reason') == 'CONSUMED' and ALLY in event.target_ids]
        assert len(consumed) == int(check_index == 0 and next_mode is not None)
        if check_index == 0:
            assert act(t, m, 'end')['status'] == 'COMMITTED'
