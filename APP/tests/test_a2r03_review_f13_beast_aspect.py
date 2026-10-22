"""The Beast-Echo Marrow State saves against beast-aspected sources, not only
against creatures of a beast kind.

The printed clause reads "...from beasts, monstrosities, spirit beasts, demon
beasts, or beast-aspected cultivators". A beast-aspected cultivator is an
ordinary humanoid that took beast aspects, so its creature types never say
"beast": recognising only the creature kind left those saves unadvantaged.
"""
import pytest

from combat.gate5_service import CombatService
from tests.test_a2r03_fix_round import _prepare_pressure
from tests.test_a2r03_review_round5 import _take_owner_turn
from tests import test_a2r11_foundations as f

ASPECT_ROW = {"block": "path_rider", "kind": "beast_aspects", "role": "initiate"}


@pytest.mark.parametrize('aspected', [True, False],
                         ids=['beast-aspect-humanoid', 'plain-humanoid'])
def test_state_save_advantage_covers_a_beast_aspect_humanoid_source_at_table(
        tmp_path, monkeypatch, aspected):
    """A fear save against a Humanoid pressure source rolls with Advantage only
    when that source is beast-aspected. The State is paid at the table, the save
    commits, and the roll is read back cold from a fresh service."""
    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=1)(bundles)
        if aspected:
            foe = next(b for b in bundles if b['actor_id'] == f.SERVICE_FOE)
            foe['typed_passives'] = [*(foe.get('typed_passives') or []), ASPECT_ROW]

    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow(), f.MARROW_BARE, ally=True,
        foe_creature_types=('Humanoid',), prepare=prepare)

    # The pressure source is a Humanoid: never a beast kind.
    before = f._engine(CombatService(f.ROOT, tmp_path), mid)
    assert before.state.actors[f.SERVICE_FOE].creature_types == ('Humanoid',)

    _take_owner_turn(table, mid)
    f._play(table, mid, f._candidate(table, mid, 'Beast-Echo Marrow State'), answer=f.SERVICE_ALLY)
    paired = f._engine(CombatService(f.ROOT, tmp_path), mid)
    assert any(c.condition_id == 'condition:typed.beast_echo_marrow_state'
               for c in paired.state.actors[f.SERVICE_ALLY].conditions.values())

    # The foe acts first each round; hand the round back so it can press.
    for _ in range(6):
        menu = table.state(mid)['menu']
        if menu['actor_id'] == f.SERVICE_FOE:
            break
        f._play(table, mid, menu['end_turn'])
    assert table.state(mid)['menu']['actor_id'] == f.SERVICE_FOE
    f._play(table, mid, f._candidate(table, mid, 'Body pressure', f.FIGHTER), answer='USE')

    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    save = next((r for r in reversed(cold.rolls)
                 if r.actor_id == f.FIGHTER and str(r.reason).startswith('SAVE:')), None)
    assert save is not None, 'the fear save was never rolled'
    # The printed clause names the beast-aspected cultivator, so an ordinary
    # humanoid source is advantaged by provenance and nothing else is.
    assert save.mode == ('ADVANTAGE' if aspected else 'NORMAL')