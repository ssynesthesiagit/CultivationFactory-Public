"""Native turn/payment controls for the Perfected parent, without model servers."""
from combat.gate4_adapters import ManualControllerAdapter
from tests.worker2_support import OWNER, FOE, candidate, settle, reload, turn
from tests.test_a2_foundations4 import setup, S, POOLS, move, own_attack
from tests.test_bone_perfected_parent import PREFIX, receipts, cut
from combat.ext.foundation_conversion_bonus import CLOCK, conversion_bonus, settle_conversion_bonus


def fixed_controller(combat, cid):
    actual = combat.controller
    class FixedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(actual, name)
    combat.controller = FixedController()


def test_ai_turn_waits_for_manual_perfected_guard_then_pays_once(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode='LOCAL_AUTO')
    turn(table, mid, FOE)
    cid = candidate(combat, mid, 'Hostile hit', target=OWNER).candidate_id
    fixed_controller(combat, cid)
    result = table.auto_step(mid, 0)
    assert result['status'] == 'REACTION_REQUIRED'
    prompt = result['reaction']
    assert prompt['context']['reactor_id'] == OWNER
    assert prompt['context']['reaction_source_id'] == 'reaction:typed.' + PREFIX + 'sheath_bone_guard'
    assert 'Hostile hit' in prompt['summary'] and 'Sheath Bone Guard' in prompt['summary']
    assert 'up to 10' in prompt['table_note'] and 'Reaction' in prompt['table_note']
    assert 'Bone-Deep Severance' in prompt['table_note']
    assert 'shared once-per-round benefit' in prompt['table_note']
    assert all(name in prompt['table_note'] for name in ('Sword-Bone Cut', 'Sheath-Bone Guard', 'Severing Clarity'))
    assert 'until the next round' in prompt['table_note']
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 1
    assert CLOCK not in engine.state.actors[OWNER].turn_flags
    result = table.auto_step(mid, 0, [{**prompt['context'], 'selection': 'USE'}])
    assert result['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert len(receipts(engine)) == 1
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 0
    assert not engine.state.actors[OWNER].reaction_available


def test_ai_cut_is_automatic_with_one_increased_damage_value(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True)
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    cid = candidate(combat, mid, 'Owner hit', target=FOE).candidate_id
    fixed_controller(combat, cid)
    result = table.auto_step(mid, 0)
    assert result['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert len(receipts(engine)) == 1
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert len(damage) == 2 and damage[-1].payload['hp_damage'] == 8
    assert engine.state.actors[OWNER].reaction_available


def test_actual_new_round_and_prior_hit_fund_second_perfected_spend(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True)
    move(combat, table, mid, 5)
    settle(table, mid, own_attack(combat, mid).candidate_id,
        choices={'reaction:typed.' + PREFIX + 'sword_bone_cut': 'USE'})
    first = reload(tmp_path, mid)
    assert len(receipts(first)) == 1
    assert first.state.actors[OWNER].resources[POOLS[S]] == 1
    first_round = first.state.round_number
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)
    before = reload(tmp_path, mid)
    assert before.state.round_number > first_round
    assert before.state.actors[OWNER].resources[POOLS[S]] == 1
    cut(combat, table, mid)
    engine = reload(tmp_path, mid)
    used = receipts(engine)
    assert len(used) == 2 and used[0].payload['round'] < used[1].payload['round']
    assert used[0].payload['payment_sequence'] != used[1].payload['payment_sequence']
    assert used[1].payload['bonus'] == 4
    damage = [e for e in engine.events if e.event_type == 'DAMAGE_COMMITTED' and e.actor_id == OWNER]
    assert damage[-1].payload['hp_damage'] == 8
    actor = engine.state.actors[OWNER]
    receipt = actor.turn_flags[CLOCK]['receipt']
    assert conversion_bonus(engine, actor, 'sheath', receipt_id=receipt['receipt_id']) == 0
    assert settle_conversion_bonus(engine, actor, 'sheath', 'different-receipt', PREFIX + 'sword_bone_cut') == 0
    assert len(receipts(engine)) == 2


def test_perfected_does_not_make_unscoped_roll_a_legal_conversion(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True, prepare=True)
    turn(table, mid, FOE)
    prompts = settle(table, mid, candidate(combat, mid, 'Cold pressure', target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not prompts and not receipts(engine)
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 1


def test_perfected_guard_cannot_replace_missing_reaction_permission(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=1, ask=True, prepare=True)
    settle(table, mid, candidate(combat, mid, 'Lose reactions').candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, 'Hostile hit', target=OWNER).candidate_id,
           choices={'reaction:typed.' + PREFIX + 'sheath_bone_guard': 'USE'})
    engine = reload(tmp_path, mid)
    assert not receipts(engine)
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 1


def test_perfected_cannot_boost_the_weapon_hit_that_first_generates_edge(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Perfected', held=0, ask=True)
    move(combat, table, mid, 5)
    prompts = settle(table, mid, own_attack(combat, mid).candidate_id,
        choices={'reaction:typed.' + PREFIX + 'sword_bone_cut': 'USE'})
    engine = reload(tmp_path, mid)
    assert not prompts and not receipts(engine)
    assert engine.state.actors[OWNER].resources[POOLS[S]] == 1
    assert CLOCK not in engine.state.actors[OWNER].turn_flags
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.payload.get('resource_id') == POOLS[S]]
