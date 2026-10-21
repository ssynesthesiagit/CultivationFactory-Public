"""Bell-Mark's darkness exemption belongs to its actual observer, not their team."""
import pytest

from combat import senses, zones
from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
from tests.bell_support import fixture, turn
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, reload, settle


@pytest.mark.parametrize('other_bell_owner', [False, True])
def test_committed_darkness_keeps_bell_mark_private(tmp_path, other_bell_owner):
    combat, table, mid = fixture(
        tmp_path, [], owner_features=[bell.WATCH],
        ally_talents=[bell.WATCH] if other_bell_owner else [],
        foe_sheet=sheet(['DARK_BASE_DARKNESS'], cl=18, name='Mara'),
        cl=18, owner_dc=100, named=True, seed='BELL-DARK-0')
    settle(table, mid, candidate(combat, mid, 'Watch Bell').candidate_id, picks={
        'choice:needle.bell_warning_tone': 'revealing',
        'choice:needle.bell_reveal_target': FOE})
    engine = reload(tmp_path, mid)
    assert bell.held(engine.state.actors[FOE], 'marked')[0].expires_on == bell.UNTIL
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Darkness', at=(6, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    owner, ally, foe = (engine.state.actors[aid] for aid in (OWNER, ALLY, FOE))
    darkness = [z for z in zones.typed_zones(engine)
                if (z.trigger_profile.get('visual') or {}).get('darkness')]
    assert darkness, [z.model_dump(mode='json') for z in engine.state.zones.values()]
    assert any(zones.actor_inside_zone(engine, foe, z) for z in darkness)
    assert bell.held(foe, 'marked', owner)
    assert not bell.held(foe, 'marked', ally)
    assert senses.perceives(engine, owner, foe)
    assert not senses.perceives(engine, ally, foe), {
        'zones': [z.model_dump(mode='json') for z in darkness],
        'ally_senses': senses.of(engine, ally),
        'ally': ally.model_dump(mode='json'),
    }
