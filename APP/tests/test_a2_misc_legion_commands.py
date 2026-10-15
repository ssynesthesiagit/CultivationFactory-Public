"""Actual Legion commands, cover/check consumption and recipient-side regression."""
import pytest

from combat.ext.ancestral_channeler import ADVICE, INTERPOSE
from combat.ext import spirit_assets
from tests.test_a2_group_misc_subpaths_1 import Fight, setup_action, place
from tests.test_riders_c8 import ME, ALLY, FOE, AC_ALL


def test_legion_advice_consumed_by_actual_ally_check_reload(tmp_path):
    def setup(mine, ally, enemy):
        setup_action(ally, 'Test contest', [{'type': 'contest_against', 'applies_to': 'target',
            'actor_check': {'kind': 'ability', 'ability': 'STR', 'skill': 'Athletics'},
            'target_check': {'kind': 'ability', 'ability': 'STR', 'skill': 'Athletics'},
            'on_success': [], 'on_fail': []}])
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    f.act('Legion: Advise (Bonus Action)', ALLY, remote=True)
    f.reload()
    assert any(c.condition_id == ADVICE for c in f.e.state.actors[ALLY].conditions.values())
    f.act('End turn'); f.advance(ALLY)
    events, _ = f.act('Test contest', FOE)
    check = next(e for e in events if e.event_type == 'CHECK_ROLLED')
    assert check.payload['actor']['mode'] == 'ADVANTAGE'
    assert not any(c.condition_id == ADVICE for c in f.e.state.actors[ALLY].conditions.values())
    f.reload()


@pytest.mark.parametrize('attack_kind', ['cultivation_ranged', 'melee'])
def test_legion_interpose_cover_is_directional_and_consumed_reload(tmp_path, attack_kind):
    def setup(mine, ally, enemy):
        setup_action(enemy, 'Test attack', [{'type': 'attack', 'attack_kind': attack_kind, 'count': 1,
            'on_hit': [{'type': 'damage', 'flat': 1, 'damage_types': ['force'], 'applies_to': 'target'}], 'on_miss': []}])
        enemy['action_catalog'][-1]['parameters']['typed']['range_ft'] = 90 if attack_kind == 'cultivation_ranged' else None
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    f.act('Legion: Interpose (Bonus Action)', ALLY, remote=True)
    f.reload()
    from combat.ext.ancestral_channeler import legion_cover
    assert legion_cover(f.e, f.e.state.actors[FOE], f.e.state.actors[ALLY]) == 2
    assert legion_cover(f.e, f.e.state.actors[ME], f.e.state.actors[ALLY]) == 0
    f.act('End turn'); f.advance(FOE)
    events, _ = f.act('Test attack', ALLY)
    attack = next(e for e in events if e.event_type == 'ATTACK_ROLLED')
    assert attack.payload['cover_bonus'] == 2
    assert attack.payload['target_ac'] == f.e.state.actors[ALLY].armor_class + 2
    assert not any(c.condition_id == INTERPOSE for c in f.e.state.actors[ALLY].conditions.values())
    f.reload()


def test_legion_strike_requires_hostile_mark_and_favor_payment_reload(tmp_path):
    def setup(mine, ally, enemy):
        setup_action(mine, 'Test mark enemy', [{'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}])
        setup_action(mine, 'Test mark friend', [{'type': 'mark', 'mark': 'Resonance', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}], target='ALLY_OR_SELF')
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    assert not f.candidates('Legion: Ancestral Strike (Favor)', FOE, True)
    f.act('Test mark enemy', FOE); f.act('Test mark friend', ALLY)
    assert not f.candidates('Legion: Ancestral Strike (Favor)', ALLY, True)
    before = f.e.state.actors[ME].resources['resource:named.favor']
    events, _ = f.act('Legion: Ancestral Strike (Favor)', FOE, remote=True)
    assert any(e.event_type == 'ATTACK_ROLLED' and FOE in e.target_ids for e in events)
    assert f.e.state.actors[ME].resources['resource:named.favor'] == before - 1
    assert not f.candidates('Legion: Interpose (Bonus Action)', ALLY, True)
    f.reload()


def test_unscoped_harmful_area_spares_own_legion(tmp_path):
    def setup(mine, ally, enemy):
        setup_action(mine, 'Test own area', [{'type': 'damage', 'flat': 20, 'damage_types': ['psychic'], 'applies_to': 'enemies_in_area'}],
                     target='CELL', area={'shape': 'sphere', 'size_ft': 60})
    f = Fight(tmp_path, AC_ALL, setup=setup)
    f.act('Ancestral Legion', choose=place('cell:5,6,0', 'cell:5,7,0', 'cell:5,5,0'))
    events, _ = f.act('Test own area', at=(6, 6))
    assert not any(e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage') for e in events)
    assert {o.current_hp for o in spirit_assets.assets(f.e, f.e.state.actors[ME], 'Ancestral Legion')} == {60}
    f.reload()
