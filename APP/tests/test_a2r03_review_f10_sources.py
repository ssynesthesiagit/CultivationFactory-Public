"""F10: compatible shipped and forged techniques through table commits/reloads."""
import pytest

from combat.ext import beast_echo_marrow as marrow
from combat.gate5_service import CombatService
from combat.typed_executor import Context
from tests import test_a2r11_foundations as f
from tests.test_a2r03_fix_round import _play_picked, _prepare_pressure
from tests.test_a2r03_review_round5 import _owner_action, _take_owner_turn, _step

HUNGER = 'HUNGER_BASE_DIGESTIVE_MANTLE'
SATIETY = 'resource:named.satiety'


@pytest.mark.parametrize('kind,qualifies', [('hunger', True), ('forged', True), ('unrelated', False)])
@pytest.mark.parametrize('mover', [f.FIGHTER, f.SERVICE_ALLY])
def test_compatible_paid_technique_offers_both_state_movers_after_reload(
        tmp_path, monkeypatch, kind, qualifies, mover):
    original_doc = f._doc

    def doc(mids, name, **kwargs):
        if kwargs.get('foundation') and kind == 'hunger':
            mids = [*mids, HUNGER]
        return original_doc(mids, name, **kwargs)

    monkeypatch.setattr(f, '_doc', doc)

    def prepare(bundles):
        _prepare_pressure('WIS', 30, 'frightened', held=2)(bundles)
        owner = next(b for b in bundles if b['actor_id'] == f.FIGHTER)
        if kind == 'hunger':
            assert any((a['parameters'].get('typed') or {}).get('source') == HUNGER
                       for a in owner['action_catalog'])
            pool = next(p for p in owner['actor_template']['resources'] if p['resource_id'] == SATIETY)
            pool.update(initial=3, maximum=max(3, pool['maximum']))
        else:
            row = _owner_action(bundles, 'Blood Hunger Beast in title only', [])
            row['parameters']['typed'].update(
                source='forged:719a8bc2', typing_status='forged', base_form='Strike',
                forged_from=('TAL_BRUTE_MOUNTAIN_MOVING_PALM' if qualifies else 'TAL_DESTRUCTION_BLAST'))

    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow(), f.MARROW_BARE,
        ally=True, foe_creature_types=('Humanoid',), prepare=prepare)
    _take_owner_turn(table, mid)
    f._play(table, mid, f._candidate(table, mid, 'Beast-Echo Marrow State'), answer=f.SERVICE_ALLY)
    # Digestive Mantle is a shipped bonus action: use the following owner turn.
    f._play(table, mid, table.state(mid)['menu']['end_turn'])
    _take_owner_turn(table, mid)
    before = f._engine(CombatService(f.ROOT, tmp_path), mid)
    position = before.state.actors[mover].position
    qi = before.state.actors[f.FIGHTER].resources['resource:core.qi']
    satiety = before.state.actors[f.FIGHTER].resources.get(SATIETY, 0)

    def pick(prompt):
        if prompt['reaction'] != 'Beast-Echo Marrow State':
            return 'DECLINE'
        ids = [o['id'] for o in prompt.get('choice', {}).get('options', [])]
        if f.FIGHTER in ids:
            assert set(ids) == {f.FIGHTER, f.SERVICE_ALLY}
            return mover
        return _step(prompt)

    label = 'Digestive Mantle: Thick Hide' if kind == 'hunger' else 'Blood Hunger Beast in title only'
    _, prompts = _play_picked(table, mid, f._candidate(table, mid, label), pick)
    cold = f._engine(CombatService(f.ROOT, tmp_path), mid)
    owner = cold.state.actors[f.FIGHTER]
    assert owner.resources['resource:core.qi'] == qi - 1
    if kind == 'hunger':
        assert owner.resources[SATIETY] == satiety - 1
    assert any(p['reaction'] == 'Beast-Echo Marrow State' for p in prompts) is qualifies
    assert (cold.state.actors[mover].position != position) is qualifies
    assert bool(owner.turn_flags.get('once_per_turn:beast_echo_state_move')) is qualifies
    moves = [e for e in cold.events if e.event_type == 'MOVEMENT_COMMITTED'
             and e.actor_id == mover and e.payload.get('granted_cost_ft')]
    assert sum(e.payload['granted_cost_ft'] for e in moves) == (5 if qualifies else 0)


@pytest.mark.parametrize('key,lineage,qualifies', [
    ('source', 'BLOOD_BASE_BLOOD_THREAD', True),
    ('source', HUNGER, True),
    ('forged_from', 'TAL_BRUTE_MOUNTAIN_MOVING_PALM', True),
    ('option_of', 'TAL_SPIRIT_COMPANIONS_BINDING_SEAL', True),
    ('forged_from', 'TAL_DESTRUCTION_BLAST', False),
])
def test_hit_consumers_share_bound_compatible_provenance(key, lineage, qualifies):
    engine = f._duel([marrow.GENERATE, marrow.STRIKE], f._marrow(), ally_mids=[])
    actor, target = (engine.state.actors[i] for i in (f.ME, f.FOE))
    target.creature_types = ('Humanoid',)
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Unarmed Strike')
    typed = {'source': 'forged:719a8bc2', key: lineage}
    ctx = Context(engine, actor, action, None, typed, [target], target, {})
    actor.resources[f.ECHO] = 0
    marrow.pack_echo_generation(ctx, target, 'hit')
    assert actor.resources[f.ECHO] == int(qualifies)
    actor.resources[f.ECHO] = 1
    ctx.hit_snapshots = {'beast_echo_strike': {f.ME: 1}}
    hp = target.current_hp
    marrow.pack_marrow_strike(ctx, target, 'hit')
    assert target.current_hp == hp - actor.proficiency_bonus * int(qualifies)
    assert actor.resources[f.ECHO] == 1 - int(qualifies)
