"""Sol findings 1–7: real choices, exact object state and cold table continuation."""
import pytest
from combat import carry, summons, typed_executor
from combat.ext import hand_occupancy, scoundrel_riders, sword_sphere
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate4_context import build_decision_context
from tests import auto11_service_support as S
from tests.cw2_service_support import add_action, seal
from tests.test_sonnet1_talents_batch1 import _solo_engine
from tests.test_summons import OWNER, _engine, _turn_of, _use
from combat.gate2_runtime_models import ActionIntent, Position

STASH = 'TAL_DARK_SHADOW_STASH'
SWORD = 'TAL_SWORD_FLYING_SWORD_TECHNIQUE'
DAGGER = {'items': [{'item_id': 'tianxia.mortal.weapon.bi_shou', 'name': 'Dagger', 'quantity': 1}]}


def cold(combat, mid):
    fresh = CombatService(combat.source_root, combat.userdata_root)
    assert fresh.replay(mid)['status'] == 'PASS'
    engine = S.engine(fresh, mid)
    assert engine.state.model_dump(mode='json') == S.engine(combat, mid).state.model_dump(mode='json')
    return fresh, TabletopService(fresh, combat.userdata_root), engine


def choose_store(prompt):
    if prompt['context']['reaction_source_id'].endswith('shadow_stash_store'):
        return prompt['choice']['options'][0]['id']
    return None


def test_stored_nonweapon_is_unusable_undroppable_unstealable_after_reload(tmp_path):
    combat, table, mid = S.fight(tmp_path, [STASH])
    engine = S.engine(combat, mid)
    before = carry.weight(engine, engine.state.actors[S.THIEF])
    result, prompts = S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=choose_store)
    assert result['status'] == 'COMMITTED'
    assert any('Shadow Stash' in str(p) for p in prompts)
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert not carry.holds(engine, actor, S.PACK_KEY)
    assert not scoundrel_riders.possessions(engine, actor)
    assert not scoundrel_riders.possessions(engine, actor, viewer=engine.state.actors[S.VICTIM])
    assert len(scoundrel_riders.possessions(engine, actor, viewer=actor)) == 1
    assert carry.weight(engine, actor) == 0 < before
    assert not any((engine.action_catalog.get(c.source_definition_id).parameters.get('item_action') == 'drop')
                   for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog)
    # Availability/passive consumers share the lost-location contract too.
    assert carry.lost_to_another_hand(actor, S.PACK_KEY)
    result, _ = S.play(table, mid, S.candidate(table, mid, 'no action on your turn'), answer=lambda p:
        p['choice']['options'][0]['id'] if p['context']['reaction_source_id'].endswith('shadow_stash_retrieve') else None)
    assert result['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert carry.holds(engine, actor, S.PACK_KEY) and carry.weight(engine, actor) == before
    assert carry.dropped(actor, S.PACK_KEY) is None
    assert S.play(table, mid, S.candidate(table, mid, 'Drop Explorer'))[0]['status'] == 'COMMITTED'
    _, _, engine = cold(combat, mid)
    assert carry.weight(engine, engine.state.actors[S.THIEF]) == 0
    assert not any(r.data.get('stashed_by') for a in engine.state.actors.values() for r in a.conditions.values())


def test_received_same_key_stores_exact_copy_and_restores_carried_weight(tmp_path, monkeypatch):
    compile_original = S.compile_character
    def compile_setup(doc, **kw):
        bundle = compile_original(doc, **kw)
        if kw['actor_id'] == S.THIEF:
            add_action(bundle, 'Receive pack', [{'type': 'transfer_object', 'item': S.PACK_KEY,
                       'object': f'{S.VICTIM}|{S.PACK_KEY}', 'as': 'take'}])
        return bundle
    monkeypatch.setattr(S, 'compile_character', compile_setup)
    combat, table, mid = S.fight(tmp_path, [STASH])
    assert S.play(table, mid, S.candidate(table, mid, 'Receive pack', target=S.VICTIM))[0]['status'] == 'COMMITTED'
    engine = S.engine(combat, mid)
    actor = engine.state.actors[S.THIEF]
    identities = {r['object'] for r in scoundrel_riders.possessions(engine, actor)}
    assert identities == {f'{S.THIEF}|{S.PACK_KEY}', f'{S.VICTIM}|{S.PACK_KEY}'}
    before = carry.weight(engine, actor)
    def answer(prompt):
        if prompt['context']['reaction_source_id'].endswith('shadow_stash_store'):
            assert {r['id'] for r in prompt['choice']['options']} == identities
            return f'{S.VICTIM}|{S.PACK_KEY}'
        return None
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=answer)[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert carry.weight(engine, actor) == before / 2
    assert {r['object'] for r in scoundrel_riders.possessions(engine, actor)} == {f'{S.THIEF}|{S.PACK_KEY}'}
    assert not any('object:' in occupant for occupants in hand_occupancy.occupancy(engine, actor).values() for occupant in occupants)
    assert S.play(table, mid, S.candidate(table, mid, 'no action on your turn'), answer=lambda p:
        f'{S.VICTIM}|{S.PACK_KEY}' if p['context']['reaction_source_id'].endswith('shadow_stash_retrieve') else None)[0]['status'] == 'COMMITTED'
    _, _, engine = cold(combat, mid)
    assert carry.weight(engine, engine.state.actors[S.THIEF]) == before
    assert {r['object'] for r in scoundrel_riders.possessions(engine, engine.state.actors[S.THIEF])} == identities
    records = [r for r in engine.state.actors[S.VICTIM].conditions.values() if r.data.get('item_key') == S.PACK_KEY]
    assert len(records) == 1 and records[0].data['held_by'] == S.THIEF
    assert not records[0].data.get('dropped_at')


@pytest.mark.parametrize('full', [False, True])
def test_store_not_offered_when_overweight_or_full(tmp_path, monkeypatch, full):
    compile_original = S.compile_character
    def compile_weights(doc, **kw):
        bundle = compile_original(doc, **kw)
        if kw['actor_id'] == S.THIEF:
            items = bundle['carrying']['items']
            for item in items:
                item['weight_lb'] = '60' if full and item['key'] == S.PACK_KEY else '61' if not full else '1'
            bundle['carrying']['weight_lb'] = str(sum(int(i['weight_lb']) for i in items))
            seal(bundle)
        return bundle
    monkeypatch.setattr(S, 'compile_character', compile_weights)
    kit = {'items': [*S.PACK['items'], *DAGGER['items']]} if full else S.PACK
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=kit)
    if full:
        S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=choose_store)
        # The paid/free retrieve action does not depend on bonus-action availability;
        # candidate predicate itself must refuse a full stash even after a fresh turn.
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
        while table.state(mid)['menu']['actor_id'] != S.THIEF:
            S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert not any('Store an object' in group['label'] for group in table.state(mid)['menu']['actions'])


@pytest.mark.parametrize('paid_reaction', [False, True])
def test_paid_retrieval_charges_actual_pool_and_correct_economy(tmp_path, paid_reaction):
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=DAGGER)
    before_engine = S.engine(combat, mid)
    weapon = carry.item_of(carry.carrying_of(before_engine, S.THIEF), key='tianxia.mortal.weapon.bi_shou')['weapon_action']
    assert any(c.source_definition_id == weapon for c in before_engine.legal_candidates())
    assert S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=choose_store)[0]['status'] == 'COMMITTED'
    engine = S.engine(combat, mid)
    assert not any(c.source_definition_id == weapon for c in engine.legal_candidates())
    actor = engine.state.actors[S.THIEF]
    pool = 'resource:core.qi'
    before = actor.resources[pool]
    before_bonus = actor.bonus_action_available
    if paid_reaction:
        # Decline on own End Turn, then retrieve during the other actor's End Turn.
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
        assert table.state(mid)['menu']['actor_id'] != S.THIEF
        candidate = table.state(mid)['menu']['end_turn']
    else:
        candidate = S.candidate(table, mid, 'no action on your turn')
    result, prompts = S.play(table, mid, candidate, answer=lambda p:
        p['choice']['options'][0]['id'] if p['context']['reaction_source_id'].endswith('shadow_stash_retrieve') else None)
    assert result['status'] == 'COMMITTED'
    assert any('Shadow Stash' in str(p) for p in prompts)
    _, _, engine = cold(combat, mid)
    actor = engine.state.actors[S.THIEF]
    assert actor.resources[pool] == before - 1
    assert carry.holds(engine, actor, 'tianxia.mortal.weapon.bi_shou')
    if paid_reaction:
        assert any(e.event_type == 'REACTION_WINDOW_OPENED' and e.source_definition_id == STASH for e in engine.events)
    else:
        assert actor.reaction_available
        assert actor.bonus_action_available == before_bonus
        assert any(c.source_definition_id == weapon for c in engine.legal_candidates())


def test_stash_actions_reach_builtin_ai_context(tmp_path):
    combat, table, mid = S.fight(tmp_path, [STASH], thief_kit=DAGGER)
    session = combat._load_session(mid)
    def sources():
        # The table's own policy and the ordinary (not item-enabled) built-in AI view.
        policy, _ = combat.policies.for_actor(S.THIEF)
        context = build_decision_context(session.engine, policy, for_ai=True)
        return {c.source_definition_id for c in context.legal_candidates}
    assert any(s.endswith('.shadow_stash.store') for s in sources())
    S.play(table, mid, S.candidate(table, mid, 'Store an object'), answer=choose_store)
    session = combat._load_session(mid)
    assert any(s.endswith('.shadow_stash.retrieve_paid') for s in sources())


def test_sword_command_mark_enables_owner_guard_and_expires_on_owner_start():
    engine = _engine([SWORD, 'TAL_SWORD_SWORD_GUARD'])
    _turn_of(engine, OWNER)
    _use(engine, OWNER, '.' + SWORD)
    sword = summons.owned_by(engine, OWNER, 'flying_sword')[0]
    _turn_of(engine, OWNER)
    _use(engine, OWNER, '.command.flying_sword')
    _turn_of(engine, sword.entity_id)
    foe = engine.state.actors[next(a for a in engine.state.actors if a not in (OWNER, sword.entity_id))]
    foe.position = Position(x=sword.position.x + 1, y=sword.position.y, z=sword.position.z)
    foe.armor_class = 1
    _use(engine, sword.entity_id, '.attack0')
    owner = engine.state.actors[OWNER]
    assert typed_executor.bears_mark(foe, OWNER, 'Sword Intent')
    assert sword_sphere.sword_guard_bonus(engine, owner, owner, foe, {'feature_id': sword_sphere.GUARD}) == owner.proficiency_bonus
    _turn_of(engine, sword.entity_id)
    typed_executor.expire_marks(engine)
    assert typed_executor.bears_mark(foe, OWNER, 'Sword Intent')
    _turn_of(engine, OWNER)
    typed_executor.expire_marks(engine)
    assert not typed_executor.bears_mark(foe, OWNER, 'Sword Intent')


def test_sword_mark_survives_table_reload_then_expires_on_owner_turn(tmp_path, monkeypatch):
    original = S._doc
    def documents(*args, **kw):
        doc = original(*args, **kw)
        if kw['name'] == 'Victim':
            doc['ability_scores_and_statistics']['armor_class']['base_value'] = 1
        return doc
    monkeypatch.setattr(S, '_doc', documents)
    combat, table, mid = S.fight(tmp_path, [SWORD, 'TAL_SWORD_SWORD_GUARD'], thief_kit=S.SWORD,
                                seed='SUMMONS')
    result, _ = S.play(table, mid, S.candidate(table, mid, 'Flying Sword Technique'), answer=lambda p:
        'cell:3,5' if any(o['id'] == 'cell:3,5' for o in p.get('choice', {}).get('options', [])) else None)
    assert result['status'] == 'COMMITTED'
    S.play(table, mid, table.state(mid)['menu']['end_turn'])
    for _ in range(6):
        if table.state(mid)['menu']['actor_id'] == S.THIEF:
            break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert S.play(table, mid, S.candidate(table, mid, 'Command Flying Sword'))[0]['status'] == 'COMMITTED'
    S.play(table, mid, table.state(mid)['menu']['end_turn'])
    assert S.play(table, mid, S.candidate(table, mid, 'Flying Sword Strike', target=S.VICTIM))[0]['status'] == 'COMMITTED'
    combat, table, engine = cold(combat, mid)
    owner, foe = engine.state.actors[S.THIEF], engine.state.actors[S.VICTIM]
    assert typed_executor.bears_mark(foe, S.THIEF, 'Sword Intent')
    assert sword_sphere.sword_guard_bonus(engine, owner, owner, foe, {'feature_id': sword_sphere.GUARD}) == owner.proficiency_bonus
    for _ in range(6):
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
        if table.state(mid)['menu']['actor_id'] == S.THIEF:
            break
    _, _, engine = cold(combat, mid)
    assert not typed_executor.bears_mark(engine.state.actors[S.VICTIM], S.THIEF, 'Sword Intent')


@pytest.mark.parametrize('move_owner', [False, True])
def test_control_range_dismisses_after_either_participant_moves(move_owner):
    engine = _engine([SWORD])
    _turn_of(engine, OWNER)
    _use(engine, OWNER, '.' + SWORD)
    sword = summons.owned_by(engine, OWNER, 'flying_sword')[0]
    owner = engine.state.actors[OWNER]
    _turn_of(engine, OWNER)
    _use(engine, OWNER, '.command.flying_sword')
    # Start at the range boundary, then commit a real legal movement intent.
    owner.position = Position(x=1, y=1)
    sword.position = Position(x=13, y=1)
    mover = owner if move_owner else sword
    _turn_of(engine, mover.entity_id)
    stationary = sword if move_owner else owner
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'MOVE' and c.destination is not None
                     and engine.grid.distance_ft(c.destination, stationary.position) > 60)
    engine.execute_intent(ActionIntent(intent_id='leave-control-range', decision_id=candidate.decision_id,
        candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=mover.entity_id,
        target_ids=candidate.target_ids, destination=candidate.destination))
    assert not sword.active and sword.summon['status'] == 'dismissed'
    assert not summons.commandable(engine, owner, 'flying_sword')
