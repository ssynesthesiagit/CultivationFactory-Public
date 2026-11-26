"""Needle Flick adds its printed Metal modifier once, including critical hits."""

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.test_lock2_persistence import act

PLAYER, FOE = 'actor:factory.needle-player', 'actor:factory.needle-foe'


@pytest.mark.parametrize('cl,count', [(1, 1), (5, 2), (15, 4)])
@pytest.mark.parametrize('score,modifier', [(8, -1), (18, 4)])
@pytest.mark.parametrize('critical', [False, True])
def test_needle_modifier_once_after_table_commit_reload(tmp_path, monkeypatch, cl, count, score, modifier, critical):
    original = Gate4ControllerEngine._resolve_attack_spec

    def hit(engine, *args, **kwargs):
        script(engine, [20 if critical else 19, *([1] * 40)])
        return original(engine, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, '_resolve_attack_spec', hit)
    attacker = sheet(['TAL_METAL_NEEDLE_FLICK'], cl=cl, key='WIS', score=score)
    # A different Path key proves that this is the compiled key modifier,
    # rather than a fixed +2 or a second contribution from another ability.
    for ability in attacker['ability_scores_and_statistics']['abilities']:
        if ability['ability'] != 'WIS':
            ability.update(score=12, modifier=1)
    bundles = [compile_character(attacker, actor_id=PLAYER),
               compile_character(sheet([]), actor_id=FOE)]
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [PLAYER, FOE], {PLAYER: 'team:factory', FOE: 'team:opponents'},
        {PLAYER: {'x': 3, 'y': 6}, FOE: {'x': 6, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [PLAYER], [FOE],
        control_modes={PLAYER: 'MANUAL', FOE: 'MANUAL'}, match_seed='R22-Needle',
        display_name='Needle modifier regression', maximum_rounds=20)['match_id']
    while table.state(mid)['menu']['actor_id'] != PLAYER:
        assert act(table, mid, 'end')['status'] == 'COMMITTED'
    state = table.state(mid)
    session = combat._load_session(mid)
    hp = session.engine.state.actors[FOE].current_hp
    candidate = next(c for c in session.engine.legal_candidates()
                     if c.display_name == 'Needle Flick' and c.target_ids == (FOE,))
    assert table.act(mid, candidate.candidate_id, state['menu']['decision_id'], state['menu']['state_version'],
                     state['last_sequence'], [])['status'] == 'COMMITTED'
    fresh = CombatService(ROOT, tmp_path)
    boundary = fresh.history(mid)['boundaries'][-1]
    rolls = [e['payload'] for e in boundary['events'] if e['event_type'] == 'DAMAGE_ROLLED']
    dice_count = count * (2 if critical else 1)
    assert [roll['expression'] for roll in rolls] == [f'{dice_count}d8{modifier:+d}']
    reloaded = fresh._load_session(mid).engine.state
    # Owning Metal also grants Sharpen: one separate PB damage packet. Keep it
    # in the HP assertion so fixing Needle's modifier cannot erase that rider.
    pb = attacker['identity']['proficiency_bonus']
    assert reloaded.actors[FOE].current_hp == hp - dice_count - modifier - pb
