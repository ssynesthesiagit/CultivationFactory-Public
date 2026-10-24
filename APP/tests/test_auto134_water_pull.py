"""Pull of the River: the chosen 10-foot pull replaces Water Lash's 5-foot move.

Table-level: every case is a real committed fight through the table service, then a
reload from what the table saved.
"""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, turn, reload
from tests.test_carry import KIT

PULL = 'TAL_WATER_PULL_OF_THE_RIVER'
CHOICE = 'choice:needle.water_pull_of_river'
PULL_PROMPT = 'Pull of the River:'
FOE_START = {'x': 6, 'y': 2}


def prepare(bundles, save=-100, size=None):
    """A Soaked mark the owner can apply for free, plus a certain Water Lash."""
    for b in bundles:
        if b['actor_id'] == FOE:
            b['actor_template']['saving_throws']['STR'] = save
            if size:
                b['actor_template']['size_category'] = size
        for a in b['action_catalog']:
            typed = (a.get('parameters') or {}).get('typed', {})
            if typed.get('source') == 'WATER_BASE_WATER_LASH':
                typed['numbers']['attack_bonus'] = 100
            if b['actor_id'] == FOE and a.get('weapon'):
                typed['numbers']['attack_bonus'] = 100
                for eff in typed.get('effects') or []:
                    for hit in eff.get('on_hit') or []:
                        if hit.get('type') == 'damage':
                            hit.pop('weapon_damage', None)
                            hit.update(dice=None, flat=1, formula='none', damage_types=['piercing'])
        if b['actor_id'] == OWNER:
            soak = deepcopy(next(a for a in b['action_catalog'] if a.get('parameters', {}).get('typed', {}).get('source') == 'WATER_BASE_WATER_LASH'))
            soak.update(source_definition_id='action:test.water_soak', display_name='Fixture soak',
                        economy='NONE', target_kind='ANY_CREATURE', range_ft=60)
            soak['parameters'] = {'free_primary': True, 'typed': {
                'source': 'test_water_soak',
                'effects': [{'type': 'mark', 'mark': 'Soaked', 'applies_to': 'target',
                             'duration': {'kind': 'until_end_of_your_next_turn'}}],
                'numbers': deepcopy(soak['parameters']['typed']['numbers']),
                'duration': {'kind': 'instant'}, 'riders': []}, 'expected_damage': 0}
            b['action_catalog'].append(soak)
            b['actor_template']['action_ids'].append(soak['source_definition_id'])
        b.pop('bundle_sha256', None)
        b['bundle_sha256'] = canonical_sha256(b)


def soak_then(table, combat, mid):
    """Mark the foe Soaked without spending the owner's Action."""
    settle(table, mid, candidate(combat, mid, 'Fixture soak', target=FOE).candidate_id)


def pull_prompt(prompts):
    return next(p for p in prompts if p['context']['reaction_source_id'] == CHOICE)


def rows(items):
    for row in items or ():
        yield row
        for key in ('on_hit', 'effects', 'on_fail', 'on_success'):
            yield from rows(row.get(key))


def typed_of(action):
    return (action.parameters or {}).get('typed') or {}


def plain_lash(engine):
    """The untalented Water Lash: its own row, with the ordinary post-hit move."""
    return next(a for a in engine.action_catalog.values()
                if typed_of(a).get('source') == 'WATER_BASE_WATER_LASH'
                and not (typed_of(a).get('modifier') or {}).get('id'))


def test_pull_of_river_pulls_a_soaked_target_toward_you(tmp_path):
    """The printed effect: a Soaked target hit by Water Lash is pulled 10 feet closer."""
    combat, table, mid = fixture(tmp_path, [PULL], foe_position=FOE_START, foe_kit={'starting_kit': {'items': [KIT['items'][-1]]}},
                                 bundle_transform=prepare)
    soak_then(table, combat, mid)
    prompts = settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id,
                       {CHOICE: 'cell:4,3'})
    asked = pull_prompt(prompts)
    assert PULL_PROMPT in asked['moment']
    assert 'Strength saving throw' in asked['moment']
    e = reload(tmp_path, mid)
    # The chosen square is two 5-foot cells from the start: the printed 10 feet.
    assert (e.state.actors[FOE].position.x, e.state.actors[FOE].position.y) == (4, 3)
    assert (e.state.actors[FOE].position.x, e.state.actors[FOE].position.y) != (FOE_START['x'], FOE_START['y'])
    # No Basin or Current exists, so the printed save never comes up.
    assert not [v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE]


def test_pull_of_river_replaces_the_base_five_foot_move(tmp_path):
    """'instead of moving it 5 feet': the ordinary move never also happens."""
    combat, table, mid = fixture(tmp_path, [PULL], foe_position=FOE_START, bundle_transform=prepare)
    e = reload(tmp_path, mid)
    lash = next(a for a in e.action_catalog.values() if a.display_name == 'Water Lash + Pull of the River')
    kinds = [r.get('type') for r in rows(typed_of(lash)['effects'])]
    assert 'water_pull_of_river' in kinds
    assert 'if_marked' not in kinds, 'the base 5-foot move must be replaced, not added to'


def test_pull_of_river_is_declined_leaving_the_target_where_it_was(tmp_path):
    combat, table, mid = fixture(tmp_path, [PULL], foe_position=FOE_START, bundle_transform=prepare)
    soak_then(table, combat, mid)
    before = reload(tmp_path, mid).state.actors[FOE].position
    settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id,
           {CHOICE: None})
    after = reload(tmp_path, mid).state.actors[FOE].position
    assert (after.x, after.y) == (before.x, before.y)


def test_pull_of_river_ignores_a_target_that_is_not_already_soaked(tmp_path):
    """The printed trigger is 'hits a Soaked target': a dry one is never offered the pull."""
    combat, table, mid = fixture(tmp_path, [PULL], foe_position=FOE_START, bundle_transform=prepare)
    before = reload(tmp_path, mid).state.actors[FOE].position
    prompts = settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id)
    assert not [p for p in prompts if p['context']['reaction_source_id'] == CHOICE]
    after = reload(tmp_path, mid).state.actors[FOE].position
    assert (after.x, after.y) == (before.x, before.y)


@pytest.mark.parametrize('save,prone', [(-100, True), (100, False)])
def test_pull_of_river_strength_save_only_beside_your_own_water(tmp_path, save, prone):
    """Large or smaller, ending beside a Basin you created: Strength save or fall Prone."""
    combat, table, mid = fixture(tmp_path, [PULL], foe_position=FOE_START, bundle_transform=lambda b: prepare(b, save=save))
    # A Basin of the caster's own, on the square the pull ends on.
    settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=(4, 3)).candidate_id)
    soak_then(table, combat, mid)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id,
           {CHOICE: 'cell:4,3'})
    e = reload(tmp_path, mid)
    assert (e.state.actors[FOE].position.x, e.state.actors[FOE].position.y) == (4, 3)
    assert len([v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE]) == 1
    assert any(c.condition_id == 'condition:typed.prone' for c in e.state.actors[FOE].conditions.values()) is prone


def test_pull_of_river_leaves_a_huge_target_without_the_save(tmp_path):
    """"Large or smaller": a Huge target is pulled and never rolls the Strength save."""
    combat, table, mid = fixture(tmp_path, [PULL], foe_position=FOE_START,
                                 bundle_transform=lambda b: prepare(b, size='Huge'))
    settle(table, mid, candidate(combat, mid, 'Shape Current: Mist Basin', at=(4, 3)).candidate_id)
    soak_then(table, combat, mid)
    turn(table, mid, FOE)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, 'Water Lash + Pull of the River', target=FOE).candidate_id,
           {CHOICE: 'cell:4,3'})
    e = reload(tmp_path, mid)
    assert (e.state.actors[FOE].position.x, e.state.actors[FOE].position.y) == (4, 3)
    assert not [v for v in e.events if v.event_type == 'SAVE_ROLLED' and v.actor_id == FOE]


def test_pull_of_river_is_inert_without_the_talent(tmp_path):
    """A Water character who does not own the row keeps Water Lash's ordinary 5-foot move."""
    combat, table, mid = fixture(tmp_path, ['TAL_WATER_WATER_SHIELD'], foe_position=FOE_START,
                                 bundle_transform=prepare)
    e = reload(tmp_path, mid)
    assert not [a for a in e.action_catalog.values() if 'Pull of the River' in a.display_name]
    assert 'if_marked' in [r.get('type') for r in rows(typed_of(plain_lash(e))['effects'])]
