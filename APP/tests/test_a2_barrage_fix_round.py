"""Review regressions: compiled weapon branches, unforced AI, and visible expiry.

Every action travels through the table, CombatService/session execute_intent,
then a fresh service verifies and mechanically replays the persisted fight.
The miss case uses the documented owner-editable weapon-specials input to
exercise a compiled Graze branch; it does not change the shipped bow rules.
"""
from copy import deepcopy
import pytest
from combat import factory_compiler
from combat.ext.hand_occupancy import weapon_grips
from tests import test_a2_barrage_transactions as transactions
from tests.test_a2_barrage import finish, option, ready, reload, COVER, SUPPRESS, PROTECTED
from tests.test_tabletop_hunt6 import table_fight, LEFT, ALLY, RIGHT

QUICK = 'TAL_BARRAGE_QUICK_DRAW_ARSENAL'
THROWN_KIT = {'starting_kit': {'items': [
    {'item_id': 'tianxia.mortal.weapon.fei_biao', 'quantity': 1}]}}
ENCHANTED_BOW = {'starting_kit': {
    'items': [{'item_id': 'tianxia.mortal.gear.arrows_20', 'quantity': 1}],
    'resolved_treasure_weapon': {
        'chassis': {'item_id': 'tianxia.mortal.weapon.gong_jian', 'name': 'Inscribed bow',
                    'damage': '1d8 Piercing', 'properties': 'Ammunition, Range 80/320, Two-Handed',
                    'weapon_class': 'Martial Ranged'},
        'refinement_bonus': 1,
        'enchantments': [{'name': 'Mountain-Weight Inscription',
                         'text': 'Whenever you hit with the weapon, the target takes an additional 1d4 force damage.'}]}}}


@pytest.mark.parametrize('hit', [True, False])
def test_ignore_retains_compiled_hit_and_miss_branches(tmp_path, monkeypatch, hit):
    real = transactions.compile_character
    def compile_owner(doc, *, actor_id, **kwargs):
        if actor_id == LEFT:
            doc = deepcopy(doc)
            doc['equipment'] = [ENCHANTED_BOW]
            kwargs['granted_spheres'] = ['tianxia.sphere.weapons']
        bundle = real(doc, actor_id=actor_id, **kwargs)
        if actor_id == LEFT:
            for action in bundle['action_catalog']:
                typed = action['parameters'].get('typed') or {}
                if typed.get('weapon'):
                    typed['numbers']['attack_bonus'] = 1000 if hit else -1000
        return bundle
    monkeypatch.setattr(transactions, 'compile_character', compile_owner)
    if not hit:
        specials = deepcopy(factory_compiler.weapon_specials())
        specials['tianxia.mortal.weapon.gong_jian']['mastery'] = 'Graze'
        monkeypatch.setattr(factory_compiler, 'weapon_specials', lambda: specials)
    combat, table, mid, enemy = transactions.battle(tmp_path, [SUPPRESS], hit=hit)
    draw = next((g for g in table.state(mid)['menu']['actions'] if g['label'].startswith('Draw Inscribed bow')), None)
    if draw:
        finish(table, mid, draw['options'][0]['candidate_id'])
    finish(table, mid, option(table, mid, 'Barrage: Inscribed bow + Suppressing Fire', enemy), lambda p: False)
    engine = reload(tmp_path, mid)
    before = len(engine.events)
    cid = option(table, mid, 'Suppressing Fire: Inscribed bow', enemy)
    source = next(c.source_definition_id for c in engine.legal_candidates() if c.candidate_id == cid)
    base = next(a for a in engine.action_catalog.values() if a.owner_id == LEFT and a.display_name == 'Inscribed bow attack')
    compiled = base.parameters['typed']['effects'][0]
    assert ('on_hit' if hit else 'on_miss') in compiled
    finish(table, mid, cid, lambda p: 'ignore' if p['context']['reaction_source_id'] == 'choice:needle.suppressing_fire' else False)
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events[before:] if e.source_definition_id == source]
    rolls = [e for e in events if e.event_type == 'ATTACK_ROLLED']
    assert len(rolls) == 2 and all(e.payload['mode'] == 'DISADVANTAGE' for e in rolls)
    damage = [e for e in events if e.event_type == 'DAMAGE_COMMITTED']
    if hit:
        assert len(damage) == 4  # weapon and inscription for each shot
        assert sum(e.event_type == 'DAMAGE_ROLLED' and e.payload['expression'] == '1d4+0' for e in events) == 2
        assert any(e.event_type == 'MODIFIER_APPLIED' and e.payload.get('target_field') == 'speed_ft' for e in events)
    else:
        assert len(damage) == 2  # each miss retains the compiled Graze damage
        assert all(e.payload['rolled_or_pending_damage'] == 2 for e in damage)


def test_quick_draw_unforced_auto_step_readies_stowed_thrown_weapon(tmp_path):
    combat, table, mid = table_fight(tmp_path, [QUICK], cl=5, kit=THROWN_KIT, ask=True)
    finish(table, mid, option(table, mid, 'Stow Fei Biao'))
    engine = reload(tmp_path, mid)
    assert not weapon_grips(engine, engine.state.actors[LEFT])
    before = len(engine.events)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, table.state(mid)['last_sequence'], [])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[LEFT]
    assert owner.turn_flags.get('barrage_quick_draw_used') is True
    assert any('fei_biao' in weapon for weapon in weapon_grips(engine, owner))
    assert owner.action_available and owner.bonus_action_available
    assert any(e.source_definition_id == QUICK for e in engine.events[before:])
    assert not any('Quick-Draw Arsenal: draw' in c.display_name for c in engine.legal_candidates())


def test_covering_prompt_and_cold_condition_name_source_deadline(tmp_path):
    from tests.test_auto58_barrage_projectiles import ARROW_KIT
    combat, table, mid = table_fight(tmp_path, [COVER], cl=5, kit=ARROW_KIT, ask=True)
    ready(table, mid)
    prompts = finish(table, mid, option(table, mid, 'Barrage: Gong Jian (Bow and Arrow) + Covering Volley', RIGHT), lambda p: ALLY)
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.covering_volley')
    engine = reload(tmp_path, mid)
    grant = next(c for c in engine.state.actors[ALLY].conditions.values() if c.condition_id == PROTECTED)
    expected = "start of Left's next turn"
    assert expected in prompt['moment']
    assert expected in grant.data['label']
    assert grant.expires_on == 'START_OF_SOURCE_NEXT_TURN'
    finish(table, mid, table.state(mid)['menu']['end_turn'])
    transactions.reach_turn(table, mid, LEFT)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == PROTECTED for c in engine.state.actors[ALLY].conditions.values())


def test_quick_draw_manual_decline_preserves_choice_and_use(tmp_path):
    combat, table, mid = table_fight(tmp_path, [QUICK], cl=5, kit=THROWN_KIT, ask=True)
    finish(table, mid, option(table, mid, 'Stow Fei Biao'))
    prompts = finish(table, mid, option(table, mid, 'Quick-Draw Arsenal: draw'), lambda p: False)
    assert len(prompts) == 1 and prompts[0]['context']['reactor_id'] == LEFT
    assert prompts[0]['choice']['allow_decline']
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[LEFT]
    assert not owner.turn_flags.get('barrage_quick_draw_used')
    assert not weapon_grips(engine, owner)
    finish(table, mid, option(table, mid, 'Quick-Draw Arsenal: draw'))
    engine = reload(tmp_path, mid)
    assert engine.state.actors[LEFT].turn_flags.get('barrage_quick_draw_used') is True
    assert weapon_grips(engine, engine.state.actors[LEFT])


def test_quick_draw_auto_preserves_ready_physical_thrown_copy(tmp_path):
    kit = deepcopy(THROWN_KIT)
    kit['starting_kit']['items'][0]['quantity'] = 2
    combat, table, mid = table_fight(tmp_path, [QUICK], cl=5, kit=kit, ask=True)
    finish(table, mid, option(table, mid, 'Stow Fei Biao'))
    engine = reload(tmp_path, mid)
    assert weapon_grips(engine, engine.state.actors[LEFT])  # the second physical copy
    assert any('Quick-Draw Arsenal: draw' in g['label'] for g in table.state(mid)['menu']['actions'])
    before = len(engine.events)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, table.state(mid)['last_sequence'], [])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[LEFT].turn_flags.get('barrage_quick_draw_used')
    assert not any(e.source_definition_id == QUICK for e in engine.events[before:])


def test_general_free_preparation_sequences_ordinary_draw_without_talent(tmp_path, monkeypatch):
    """A second provider uses the seam, with no Barrage/Quick-Draw owner or ID."""
    real = transactions.compile_character
    def compile_owner(doc, *, actor_id, **kwargs):
        if actor_id == LEFT:
            doc = deepcopy(doc)
            doc['equipment'] = [THROWN_KIT]
        bundle = real(doc, actor_id=actor_id, **kwargs)
        if actor_id == LEFT:
            for action in bundle['action_catalog']:
                grip = action['parameters'].get('equipment_grip') or {}
                if grip.get('held'):
                    action['parameters']['ai_free_preparation'] = True
        return bundle
    monkeypatch.setattr(transactions, 'compile_character', compile_owner)
    combat, table, mid, enemy = transactions.battle(tmp_path, [])
    finish(table, mid, option(table, mid, 'Stow Fei Biao'))
    engine = reload(tmp_path, mid)
    assert not weapon_grips(engine, engine.state.actors[LEFT])
    assert not any((a.parameters.get('typed') or {}).get('source') == QUICK
                   for a in engine.action_catalog.values() if a.owner_id == LEFT)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode='LOCAL_AUTO')
    assert table.auto_step(mid, table.state(mid)['last_sequence'], [])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[LEFT]
    assert weapon_grips(engine, owner)
    assert owner.action_available and owner.bonus_action_available
