"""F4 review: retrieval cannot overfill hands; storage moves one stack unit."""
import pytest

from combat import carry
from combat.ext import hand_occupancy, scoundrel_riders
from combat.gate4_context import build_decision_context
from tests import auto11_service_support as S
from tests.cw2_service_support import add_action
from tests.test_sonnet1_talents_f1 import STASH, DAGGER, cold


def answer_object(kind, identity):
    def answer(prompt):
        if prompt['context']['reaction_source_id'].endswith('shadow_stash_' + kind):
            assert identity in {o['id'] for o in prompt['choice']['options']}
            return identity
        return None
    return answer


def grip_candidate(engine, weapon, held):
    return next(c.candidate_id for c in engine.legal_candidates()
                if c.source_definition_id in engine.action_catalog
                and (engine.action_catalog[c.source_definition_id].parameters.get('equipment_grip') or {})
                == {'weapon': weapon, 'held': held, 'hands': 1})


@pytest.mark.parametrize('reaction', [False, True])
def test_retrieved_weapon_preserves_replacement_grips_through_table_reload(tmp_path, reaction):
    kit = {'items': [{**DAGGER['items'][0], 'quantity': 3}]}
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=kit)
    engine = S.engine(combat, mid)
    actor = engine.state.actors[S.THIEF]
    items = carry.carrying_of(engine, S.THIEF)['items']
    first, second, spare = [i['weapon_action'] for i in items]
    identity = f"{S.THIEF}|{items[0]['key']}"
    assert set(hand_occupancy.weapon_grips(engine, actor)) == {first, second}
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'),
                  answer=answer_object('store', identity))[0]['status'] == 'COMMITTED'
    assert S.play(table, mid, grip_candidate(S.engine(combat, mid), spare, True))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    if reaction:
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
        candidate = table.state(mid)['menu']['end_turn']
    else:
        candidate = S.candidate(table, mid, 'no action on your turn')
    assert S.play(table, mid, candidate, answer=answer_object('retrieve', identity))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert set(hand_occupancy.weapon_grips(engine, actor)) == {second, spare}
    assert len(hand_occupancy.occupancy(engine, actor)) == 2
    assert not hand_occupancy.free_hands(engine, actor)
    assert carry.holds(engine, actor, items[0]['key'])
    assert carry.owned_item_location(actor, items[0]['key']) == 'carried'
    S.to_thief(table, mid)
    engine = S.engine(combat, mid)
    assert {second, spare} <= {c.source_definition_id for c in engine.legal_candidates()}
    assert first not in {c.source_definition_id for c in engine.legal_candidates()}
    assert S.play(table, mid, grip_candidate(engine, spare, False))[0]['status'] == 'COMMITTED'
    assert S.play(table, mid, grip_candidate(S.engine(combat, mid), first, True))[0]['status'] == 'COMMITTED'
    _, _, engine = cold(combat, mid)
    assert set(hand_occupancy.weapon_grips(engine, engine.state.actors[S.THIEF])) == {first, second}


@pytest.mark.parametrize('quantity', [2, 3])
def test_store_one_unit_from_over_capacity_stack_and_retrieve_drop_pickup_after_reload(tmp_path, monkeypatch, quantity):
    # A printed 3-pound gear item, two copies: each fits CL1's 5 lb, the row does not.
    original = S._doc
    def cl_one(*args, **kw):
        doc = original(*args, **kw)
        doc['identity']['cultivation_level'] = 1
        return doc
    monkeypatch.setattr(S, '_doc', cl_one)
    kit = {'items': [{'item_id': 'tianxia.mortal.gear.blanket', 'name': 'Blanket', 'quantity': quantity}]}
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=kit)
    engine = S.engine(combat, mid)
    actor = engine.state.actors[S.THIEF]
    [item] = carry.carrying_of(engine, S.THIEF)['items']
    assert item['quantity'] == quantity and float(item['weight_lb']) == 3 * quantity
    store = next(a for a in engine.action_catalog.values() if a.owner_id == S.THIEF
                 and a.source_definition_id.endswith('.shadow_stash.store'))
    assert store.parameters['typed']['numbers']['cl'] == 1
    policy, _ = combat.policies.for_actor(S.THIEF)
    assert store.source_definition_id in {c.source_definition_id for c in
        build_decision_context(engine, policy, for_ai=True).legal_candidates}
    selected = []
    def store_one(prompt):
        if prompt['context']['reaction_source_id'].endswith('shadow_stash_store'):
            options = prompt['choice']['options']
            assert len(options) == quantity and len({o['id'] for o in options}) == quantity
            selected.append(options[0]['id'])
            return options[0]['id']
        return None
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=store_one)[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    rows = [r for r in actor.conditions.values() if r.data.get('stashed_by')]
    assert len(rows) == 1 and rows[0].data['weight_lb'] == '3'
    assert carry.weight(engine, actor) == 3 * (quantity - 1) and carry.holds(engine, actor, item['key'])
    remaining = scoundrel_riders.possessions(engine, actor)
    assert len(remaining) == quantity - 1 and all(r['quantity'] == 1 for r in remaining)
    assert all(r['object'] != selected[0] and float(r['weight_lb']) == 3 for r in remaining)
    assert S.play(table, mid, S.candidate(table, mid, 'Drop Blanket'))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert carry.weight(engine, actor) == 0 and not carry.holds(engine, actor, item['key'])
    assert len([r for r in actor.conditions.values() if r.condition_id == carry.DROPPED]) == quantity - 1
    assert S.play(table, mid, S.candidate(table, mid, 'no action on your turn'),
                  answer=answer_object('retrieve', selected[0]))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert carry.weight(engine, actor) == 3 and carry.holds(engine, actor, item['key'])
    assert [r['object'] for r in scoundrel_riders.possessions(engine, actor)] == [selected[0]]
    assert not any(r.data.get('stashed_by') for r in actor.conditions.values())
    for _ in range(quantity - 1):
        assert S.play(table, mid, S.candidate(table, mid, 'Pick up Blanket'))[0]['status'] == 'COMMITTED'
    _, _, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert carry.weight(engine, actor) == 3 * quantity
    assert len(scoundrel_riders.possessions(engine, actor)) == quantity


def test_each_bonus_action_moves_one_unit_even_when_the_whole_stack_fits(tmp_path):
    kit = {'items': [{'item_id': 'tianxia.mortal.gear.blanket', 'name': 'Blanket', 'quantity': 2}]}
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=kit)
    selected = []
    def store_one(prompt):
        if prompt['context']['reaction_source_id'].endswith('shadow_stash_store'):
            selected.append(prompt['choice']['options'][0]['id'])
            return selected[-1]
        return None
    for number in (1, 2):
        assert S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=store_one)[0]['status'] == 'COMMITTED'
        combat, table, engine = cold(combat, mid)
        actor = engine.state.actors[S.THIEF]
        assert len([r for r in actor.conditions.values() if r.data.get('stashed_by')]) == number
        assert carry.weight(engine, actor) == 3 * (2 - number)
        assert not actor.bonus_action_available
        S.to_thief(table, mid, end_thief=True)
    assert len(set(selected)) == 2
    assert S.play(table, mid, S.candidate(table, mid, 'Retrieve an object (Bonus Action)'),
                  answer=answer_object('retrieve', selected[0]))[0]['status'] == 'COMMITTED'
    _, _, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert carry.weight(engine, actor) == 3 and not actor.bonus_action_available
    assert [r['object'] for r in scoundrel_riders.possessions(engine, actor)] == [selected[0]]
    assert [r.data['object_id'] for r in actor.conditions.values() if r.data.get('stashed_by')] == [selected[1]]


def test_splitting_a_received_stack_keeps_the_other_unit_on_its_current_holder(tmp_path, monkeypatch):
    key = 'tianxia.mortal.gear.blanket'
    original = S.compile_character
    def compile_setup(doc, **kw):
        bundle = original(doc, **kw)
        if kw['actor_id'] == S.THIEF:
            add_action(bundle, 'Receive blankets', [{'type': 'transfer_object', 'item': key,
                'object': f'{S.VICTIM}|{key}', 'as': 'take'}])
        return bundle
    monkeypatch.setattr(S, 'compile_character', compile_setup)
    kit = {'items': [{'item_id': key, 'name': 'Blanket', 'quantity': 2}]}
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit={'items': []}, victim_kit=kit)
    assert S.play(table, mid, S.candidate(table, mid, 'Receive blankets', S.VICTIM))[0]['status'] == 'COMMITTED'
    selected = []
    def store_one(prompt):
        if prompt['context']['reaction_source_id'].endswith('shadow_stash_store'):
            assert len(prompt['choice']['options']) == 2
            selected.append(prompt['choice']['options'][0]['id'])
            return selected[-1]
        return None
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=store_one)[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    thief, owner = engine.state.actors[S.THIEF], engine.state.actors[S.VICTIM]
    assert carry.weight(engine, thief) == 3 and carry.weight(engine, owner) == 0
    assert not scoundrel_riders.possessions(engine, owner)
    [remaining] = scoundrel_riders.possessions(engine, thief)
    assert remaining['object'] != selected[0] and remaining['quantity'] == 1
    assert float(remaining['weight_lb']) == 3
    assert S.play(table, mid, S.candidate(table, mid, 'no action on your turn'),
                  answer=answer_object('retrieve', selected[0]))[0]['status'] == 'COMMITTED'
    _, _, engine = cold(combat, mid)
    assert carry.weight(engine, engine.state.actors[S.THIEF]) == 6
    assert carry.weight(engine, engine.state.actors[S.VICTIM]) == 0
    assert len(scoundrel_riders.possessions(engine, engine.state.actors[S.THIEF])) == 2
