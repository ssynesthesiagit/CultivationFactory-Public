"""R2 findings: physical equipment, death spills, worn gear and independent owners."""
import pytest
from combat import carry
from combat.ext import hand_occupancy, life_state, treasure_armor
from combat.gate4_context import build_decision_context
from tests import auto11_service_support as S
from tests.cw2_service_support import add_action
from tests.test_sonnet1_talents_f1 import STASH, DAGGER, cold, choose_store


def stash_answer(identity):
    return lambda p: identity if p['context']['reaction_source_id'].endswith('shadow_stash_store') else None


def test_stored_drawn_weapon_frees_exact_grip_and_two_handed_option_after_reload(tmp_path):
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit={'items': [*S.SWORD['items'], *DAGGER['items']]})
    engine = S.engine(combat, mid)
    actor = engine.state.actors[S.THIEF]
    dagger = next(i for i in carry.carrying_of(engine, S.THIEF)['items'] if 'bi_shou' in i['key'])
    spear = next(a.source_definition_id for a in engine.action_catalog.values()
                 if a.owner_id == S.THIEF and a.source_definition_id.endswith('.weapon.qiang'))
    occupant = 'weapon:' + dagger['weapon_action']
    assert occupant in {v for slots in hand_occupancy.occupancy(engine, actor).values() for v in slots}
    assert not hand_occupancy.free_hands(engine, actor)
    assert not any(c.source_definition_id == spear for c in engine.legal_candidates())
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'),
                  answer=stash_answer(f"{S.THIEF}|{dagger['key']}"))[0]['status'] == 'COMMITTED'
    _, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert occupant not in {v for slots in hand_occupancy.occupancy(engine, actor).values() for v in slots}
    assert len(hand_occupancy.free_hands(engine, actor)) == 1
    assert any(c.source_definition_id == spear for c in engine.legal_candidates())
    assert any(g['source_definition_id'] == spear for g in table.state(mid)['menu']['actions'])


@pytest.mark.parametrize('lingering', [False, True])
def test_death_spills_received_exact_object_and_original_owner_recovers_after_reload(tmp_path, monkeypatch, lingering):
    original = S.compile_character
    def compile_setup(doc, **kw):
        bundle = original(doc, **kw)
        if kw['actor_id'] == S.THIEF:
            add_action(bundle, 'Receive pack', [{'type': 'transfer_object', 'item': S.PACK_KEY,
                'object': f'{S.VICTIM}|{S.PACK_KEY}', 'as': 'take'}])
        if kw['actor_id'] == S.VICTIM:
            for name, flat in [('Wound', 60), ('Fatal wound', 150)]:
                add_action(bundle, name, [{'type': 'damage', 'flat': flat, 'damage_type': 'FORCE'}])
        return bundle
    monkeypatch.setattr(S, 'compile_character', compile_setup)
    talents = [STASH, *(['tianxia.talent.life.soul_lamp_continuity'] if lingering else [])]
    combat, table, mid = S.fight(tmp_path, talents, ally=True)
    identity = f'{S.VICTIM}|{S.PACK_KEY}'
    S.play(table, mid, S.candidate(table, mid, 'Receive pack', target=S.VICTIM))
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=stash_answer(identity))[0]['status'] == 'COMMITTED'
    while table.state(mid)['menu']['actor_id'] != S.VICTIM:
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert S.play(table, mid, S.candidate(table, mid, 'Wound', target=S.THIEF))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    assert not life_state.is_deceased(engine.state.actors[S.THIEF])
    assert any(r.data.get('object_id') == identity and r.data.get('stashed_by') == S.THIEF
               for r in engine.state.actors[S.VICTIM].conditions.values())
    def accept_lamp(prompt):
        return 'keep_soul' if prompt['context']['reaction_source_id'].startswith('choice:life.lamp:') else None
    assert S.play(table, mid, S.candidate(table, mid, 'Fatal wound', target=S.THIEF),
                  answer=accept_lamp)[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    assert life_state.is_deceased(engine.state.actors[S.THIEF])
    assert life_state.is_dead(engine.state.actors[S.THIEF]) == lingering
    rows = [r for r in engine.state.actors[S.VICTIM].conditions.values() if r.data.get('object_id') == identity]
    assert len(rows) == 1 and rows[0].condition_id == carry.DROPPED
    assert not rows[0].data.get('stashed_by') and not rows[0].data.get('held_by')
    spot = rows[0].data['dropped_at']
    assert (spot['x'], spot['y']) == (2, 5)  # deterministic nearest open cell, excluding the body
    from combat.gate2_runtime_models import Position
    ground = Position(**spot)
    actor = engine.state.actors[S.VICTIM]
    move = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination is not None
                and engine.grid.distance_ft(c.destination, ground) <= 5)
    assert S.play(table, mid, move.candidate_id)[0]['status'] == 'COMMITTED'
    assert S.play(table, mid, S.candidate(table, mid, 'Pick up Explorer'))[0]['status'] == 'COMMITTED'
    _, _, engine = cold(combat, mid)
    assert carry.holds(engine, engine.state.actors[S.VICTIM], S.PACK_KEY)
    assert carry.holds(engine, engine.state.actors[S.THIEF], S.PACK_KEY)  # untouched identical copy
    assert not any(r.data.get('stashed_by') for a in engine.state.actors.values() for r in a.conditions.values())


def test_worn_armor_store_is_legal_for_human_and_ai_and_stops_bonuses_after_reload(tmp_path):
    from tests.test_a2_treasure_armor_enhancements import kit, AUTH
    armor_kit = kit('fire_shedding_lining')
    armor_kit['resolved_treasure_armor']['chassis'] = next(r for r in AUTH['chassis']
                                                       if r['name'] == 'Full Lamellar Battle Dress')
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=armor_kit)
    engine = S.engine(combat, mid)
    actor = engine.state.actors[S.THIEF]
    [item] = carry.carrying_of(engine, S.THIEF)['items']
    assert item['worn']
    assert treasure_armor.rows(engine, actor, 'fire_shedding_lining')
    before = actor.armor_class + engine._ac_modifier(actor)
    policy, _ = combat.policies.for_actor(S.THIEF)
    assert any(c.source_definition_id.endswith('.shadow_stash.store')
               for c in build_decision_context(engine, policy, for_ai=True).legal_candidates)
    result, prompts = S.play(table, mid, S.candidate(table, mid, 'Store an object'),
                            answer=stash_answer(f"{S.THIEF}|{item['key']}"))
    assert result['status'] == 'COMMITTED'
    assert any('Test treasure armor' in str(p) for p in prompts)
    _, _, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert not treasure_armor.rows(engine, actor, 'fire_shedding_lining')
    assert actor.armor_class + engine._ac_modifier(actor) < before
    assert carry.weight(engine, actor) == 0


@pytest.mark.parametrize('trigger', ['Store an object', 'no action on your turn'])
def test_other_owner_can_pay_retrieval_reaction_during_stash_actions(tmp_path, monkeypatch, trigger):
    original_doc, original_compile = S._doc, S.compile_character
    def document(talents, **kw):
        return original_doc([STASH] if kw['name'] == 'Victim' else talents, **kw)
    def compile_setup(doc, **kw):
        return original_compile(doc, **{**kw, 'reaction_plan': {'ask': True}})
    monkeypatch.setattr(S, '_doc', document)
    monkeypatch.setattr(S, 'compile_character', compile_setup)
    combat, table, mid = S.fight(tmp_path, [STASH])
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=choose_store)[0]['status'] == 'COMMITTED'
    S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert table.state(mid)['menu']['actor_id'] == S.VICTIM
    if trigger != 'Store an object':
        assert S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=choose_store)[0]['status'] == 'COMMITTED'
    engine = S.engine(combat, mid)
    before = engine.state.actors[S.THIEF].resources['resource:core.qi']
    def answer(prompt):
        source = prompt['context']['reaction_source_id']
        return prompt['choice']['options'][0]['id'] if source.endswith(('shadow_stash_store', 'shadow_stash_retrieve')) else None
    result, prompts = S.play(table, mid, S.candidate(table, mid, trigger), answer=answer)
    assert result['status'] == 'COMMITTED'
    assert any(p['context']['reactor_id'] == S.THIEF and 'Shadow Stash' in str(p) for p in prompts)
    _, _, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert actor.resources['resource:core.qi'] == before - 1
    assert not actor.reaction_available
    assert carry.holds(engine, actor, S.PACK_KEY)
