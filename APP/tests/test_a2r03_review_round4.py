"""A2R03R3: consent, shipped scope IDs, and refined companion range."""
import copy
from types import SimpleNamespace

import pytest

from combat.ext import beast_echo_marrow as marrow
from combat.typed_executor import Context, clock_expiry
from tests.test_a2r03_fix_round import _add_companion, _prepare_pressure, COMPANION
from tests.test_a2r11_foundations import (
    FIGHTER, SERVICE_FOE, MARROW_BARE, ECHO, ME, FOE, ALLY,
    _marrow, _service_fight, _until, _candidate, _play, _engine, _duel,
)


@pytest.mark.parametrize('accept', [False, True])
def test_guard_pair_budget_settles_only_after_consent_and_table_reload(tmp_path, monkeypatch, accept):
    def prepare(bundles):
        _prepare_pressure('WIS', 22, 'frightened', held=2)(bundles)
        _add_companion(bundles)
    combat, table, mid = _service_fight(tmp_path, monkeypatch, _marrow(), MARROW_BARE,
        ally=True, foe_creature_types=('Beast',), prepare=prepare,
        positions={FIGHTER: {'x': 4, 'y': 7}})
    _until(table, mid, FIGHTER, answer='DECLINE')
    _play(table, mid, _candidate(table, mid, 'Beast-Echo Marrow State'), answer=COMPANION)
    _play(table, mid, table.state(mid)['menu']['end_turn'])
    _until(table, mid, SERVICE_FOE, answer='DECLINE')
    before = _engine(combat, mid)
    position = copy.deepcopy(before.state.actors[COMPANION].position)
    held = before.state.actors[FIGHTER].resources[ECHO]
    assert held > 0 and before.state.actors[FIGHTER].reaction_available
    assert before.state.actors[FIGHTER].turn_flags.get(marrow.PAIR_BUDGET) != before.state.round_number
    _, prompts = _play(table, mid, _candidate(table, mid, 'Unarmed Strike', COMPANION),
                       answer='move' if accept else 'DECLINE')
    cold = _engine(combat, mid)
    owner, companion = cold.state.actors[FIGHTER], cold.state.actors[COMPANION]
    assert any(p['reaction'] == 'Marrow Pack Guard' for p in prompts)
    assert owner.resources[ECHO] == held - int(accept)
    assert owner.reaction_available is (not accept)
    assert (owner.turn_flags.get(marrow.PAIR_BUDGET) == cold.state.round_number) is accept
    assert (companion.position != position) is accept
    assert not companion.turn_flags.get('beast_echo_guard_move')
    assert any(e.event_type == 'DAMAGE_COMMITTED' and COMPANION in e.target_ids for e in cold.events)
    moves = [p for p in prompts if p['reaction'] == 'Marrow Pack Guard'
             and ('Move 5 feet' in p['moment'] or 'choose where' in p['moment'])]
    assert bool(moves) is accept


@pytest.mark.parametrize('mechanic_id', [
    'TAL_BRUTE_MOUNTAIN_MOVING_PALM', 'TAL_BERSERKER_BATTER',
    'TAL_BEASTMASTERY_ACCOMPLICE', 'TAL_SPIRIT_COMPANIONS_BINDING_SEAL',
])
def test_shipped_scope_sources_feed_generation_strike_witness_guard_and_state(monkeypatch, mechanic_id):
    engine = _duel([mechanic_id, marrow.GENERATE, marrow.STRIKE, marrow.WITNESS, marrow.STATE],
                   _marrow(), ally_mids=[])
    actor, target, ally = (engine.state.actors[i] for i in (ME, FOE, ALLY))
    target.creature_types = ('Humanoid',)
    action = next(a for a in engine.action_catalog.values()
                  if (a.parameters.get('typed') or {}).get('source') == mechanic_id)
    assert not marrow.beast_kinded(target)
    assert marrow.in_scope(mechanic_id)
    ctx = Context(engine, actor, action, None, action.parameters['typed'], [target], target, {})
    engine._active_action_source_id = action.source_definition_id
    assert marrow._scope_source(engine, target)
    monkeypatch.setattr(engine, 'd20_context', lambda *args: {'source_id': mechanic_id})
    assert marrow._witness_scope(engine, SimpleNamespace(named=()))
    actor.resources[ECHO] = 0
    marrow.pack_echo_generation(ctx, target, 'hit')
    assert actor.resources[ECHO] == 1
    # This is a later qualifying hit: only its prior-Echo receipt can pay Strike.
    ctx.hit_snapshots = {'beast_echo_strike': {ME: 1}}
    prompts = []
    monkeypatch.setattr(marrow.needle, 'ask', lambda *args, **kw: prompts.append(kw) or ['strike'])
    hp = target.current_hp
    marrow.pack_marrow_strike(ctx, target, 'hit')
    assert target.current_hp == hp - actor.proficiency_bonus
    assert actor.resources[ECHO] == 0
    # A compatible paid technique preserves the whole State movement decision.
    engine._apply_condition(actor, marrow.STATE_CONDITION, 'test:state', ME,
        expires_on=clock_expiry(engine, 'minutes', 1),
        data={'holder': ME, 'member': ALLY, 'cl': 10})
    ctx.action = action.model_copy(update={'costs': (('resource:core.qi', 1),)})
    steps = []
    from combat.ext import granted_moves
    monkeypatch.setattr(granted_moves, 'choose', lambda *args, **kw: steps.append((args, kw)) or 5)
    monkeypatch.setattr(marrow.needle, 'ask', lambda *args, **kw: [ALLY])
    marrow.state_technique_move(ctx)
    assert steps and steps[0][0][1] is ally


@pytest.mark.parametrize('distance_ft, expected', [(30, 8), (35, 4)])
def test_refined_pack_marrow_companion_range_matches_quote_and_damage(monkeypatch, distance_ft, expected):
    engine = _duel([marrow.STRIKE, marrow.MARROW], _marrow(), ally_mids=[])
    owner, target, companion = (engine.state.actors[i] for i in (ME, FOE, ALLY))
    companion.summon = {'owner': ME, 'group': 'test:bond', 'source': 'test:bond', 'status': 'present'}
    companion.position = owner.position.model_copy(update={'x': owner.position.x + distance_ft // 5})
    assert companion in marrow.companions(engine, owner)
    assert engine._distance_actor_to_actor(owner, companion) == distance_ft
    owner.resources[ECHO] = 1
    target.creature_types = ('Humanoid',)
    engine._append_event('DAMAGE_COMMITTED', 'test:prior', actor_id=ME, target_ids=(FOE,), payload={})
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Unarmed Strike')
    ctx = Context(engine, companion, action, None, {'source': 'action:unarmed_strike'}, [target], target, {})
    ctx.hit_snapshots = {'beast_echo_strike': {ME: 1}}
    prompts = []
    monkeypatch.setattr(marrow.needle, 'ask', lambda *args, **kw: prompts.append(kw['prompt']) or ['strike'])
    hp = target.current_hp
    marrow.pack_marrow_strike(ctx, target, 'hit')
    assert prompts and f'add {expected} damage' in prompts[0]
    assert target.current_hp == hp - expected
    assert owner.resources[ECHO] == 0  # Distant companions retain the base Strike option.
