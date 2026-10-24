"""Sol seam review round 11 (Ten Thousand Sword Array Cultivator) blocking-finding regressions.

Finding 1: a lent real sword is one physical item: the borrower wields its own held copy of the owner's weapon.
Finding 2: the printed once-during-each-turn controls are complete off-turn (each sword's move, switch, mode) and
           are not withheld from automatic owners.
Finding 3: Sword-Qi Origin classifies a qualifying sword technique from its native delivery and offers the field's
           visible sword-path points, while a technique that needs a real weapon hit gets only actual swords.
Finding 4: Call the Seed Sword is offered as part of activating a sword-delivered technique through the floating sword.

These are plug-in level checks. The same behaviours are also asserted through real CombatService/TabletopService
fights and a cold reload in tests/test_mgr_t14_sword_round11_table.py.
"""
from types import SimpleNamespace

from combat.ext import ten_thousand_swords as swords
from combat.ext import hand_occupancy
from combat.ext.ten_thousand_swords import ARRAY, RETURN, SEED, TWIN

A = 'actor:sword-owner'
B = 'actor:sword-lender'
OTHER = 'actor:other-creature'
LENT_ACTION = 'action:typed.lender.weapon.jian'
HELD_ACTION = 'action:typed.borrower.weapon.held.jian'


def _sword(location='floating', form='real', **extra):
    return {'slot': 0, 'form': form, 'location': location, 'mode': 'assault', 'damage_type': 'force',
            'item_uid': 'item:sword', 'weapon_action': LENT_ACTION, 'owner_id': B, 'x': 2, 'y': 3, 'z': 0, **extra}


def _actor(eid=A, turn_flags=None):
    return SimpleNamespace(entity_id=eid, display_name=eid, active=True, position=SimpleNamespace(x=2, y=2, z=0),
                           turn_flags=dict(turn_flags or {}), conditions={}, resources={})


def _catalog():
    return {
        LENT_ACTION: SimpleNamespace(source_definition_id=LENT_ACTION, owner_id=B, display_name='Lent Jian',
                                     parameters={'typed': {'weapon': {'damage': {'count': 1, 'sides': 6}}}}),
        HELD_ACTION: SimpleNamespace(source_definition_id=HELD_ACTION, owner_id=A, display_name='Lent Jian',
                                     parameters={'requires_held_weapon': LENT_ACTION,
                                                 'typed': {'weapon': {'damage': {'count': 1, 'sides': 6}}}}),
    }


def _engine(actors=(), catalog=None):
    return SimpleNamespace(state=SimpleNamespace(round_number=2, current_actor_id=A, event_sequence=0,
                                                 actors={row.entity_id: row for row in actors}, zones={}),
                           action_catalog=catalog if catalog is not None else _catalog(), events=[],
                           _append_event=lambda *a, **k: None)


def _patch(monkeypatch, sword_list, *, cl=18, free=True, owned_rows=(SEED, ARRAY, TWIN, RETURN), actor=A,
           destination=('p',)):
    monkeypatch.setattr(swords, 'owned', lambda engine, row, source=SEED: source in owned_rows and row.entity_id == actor)
    monkeypatch.setattr(swords, 'numbers', lambda engine, row: {'cl': cl})
    monkeypatch.setattr(swords, 'state', lambda row: {'swords': sword_list, 'origin_used': False})
    monkeypatch.setattr(swords, 'incapacitated', lambda row: False)
    monkeypatch.setattr(swords, 'checkpoint_id', lambda *a, **k: 'checkpoint:test')
    monkeypatch.setattr(hand_occupancy, 'free_hands', lambda engine, row: ['hand:left'] if free else [])
    monkeypatch.setattr(swords, 'destinations',
                        lambda engine, row, sword, **kw: [row.position] if kw.get('call') else list(destination))


def _recording_ask(monkeypatch, answer):
    asked = []

    def fake_ask(engine, intent, checkpoint, chooser, choice_id, options, **kw):
        asked.append({'chooser': chooser.entity_id, 'options': list(options), 'choice_id': choice_id, 'kw': kw})
        return [option for option in answer if option in options]
    monkeypatch.setattr(swords, 'ask', fake_ask)
    return asked


def _recording_command(monkeypatch, seen):
    def fake_command(ctx, eff):
        seen.append({'command': eff['command'], 'actor': ctx.actor.entity_id})
    monkeypatch.setattr(swords, 'command', fake_command)


# ---------------------------------------------------------------- Finding 1: one item, the borrower wields it
def test_borrower_reads_the_held_copy_of_the_lenders_weapon_not_the_lender_action():
    actor = _actor()
    engine = _engine([actor])
    borrowed = _sword()
    assert swords.bound_action(engine, actor, borrowed) == HELD_ACTION
    own = _sword(owner_id=A, weapon_action=HELD_ACTION)
    assert swords.bound_action(engine, actor, own) == HELD_ACTION
    assert swords.borrower(borrowed, actor) and not swords.borrower(own, actor)


def test_lender_loses_simultaneous_use_and_the_borrower_holds_the_one_item():
    borrower, lender = _actor(), _actor(B)
    engine = _engine([borrower, lender])
    applied = []
    engine._apply_condition = lambda target, cid, source, owner, expires_on=None, data=None: applied.append(
        (target.entity_id, cid, data))
    swords.custody(engine, borrower, {'swords': [_sword()]})
    assert [(who, cid, data['disables_action'], data['held_by']) for who, cid, data in applied] == [
        (B, swords.LENT, LENT_ACTION, A)]
    # An own sword never creates a custody record; a lent projected sword has no physical item to lend.
    applied.clear()
    swords.custody(engine, borrower, {'swords': [_sword(owner_id=A), _sword(form='projected')]})
    assert applied == []


def test_item_placement_updates_the_lenders_ledger_record(monkeypatch):
    from combat import acquisition_inventory
    borrower, lender = _actor(), _actor(B)
    engine = _engine([borrower, lender])
    ledgers = {borrower.entity_id: {}, lender.entity_id: {'item:sword': {'profile': {'flags': {}}}},
               OTHER: {}}
    monkeypatch.setattr(acquisition_inventory, 'read', lambda row: ledgers[row.entity_id])
    written = []
    monkeypatch.setattr(acquisition_inventory, 'write',
                        lambda eng, row, items, source: written.append((row.entity_id, dict(items))) or
                        ledgers.__setitem__(row.entity_id, items))
    monkeypatch.setattr(hand_occupancy, 'occupancy', lambda engine, row: {'hand:left': ('weapon:' + HELD_ACTION,)})
    swords.item_placement(engine, borrower, _sword(location='hand'), 'hand')
    assert written and written[0][0] == B
    recorded = written[0][1]['item:sword']
    assert recorded['holder'] == A and recorded['location'] == 'hand' and recorded['hand'] == 'hand:left'


# ---------------------------------------------------------------- Finding 2: complete off-turn controls
def _off_turn(monkeypatch, sword_list, *, cl=18, answer=(), turn_flags=None, free=True, owned_rows=(SEED, ARRAY, TWIN, RETURN)):
    _patch(monkeypatch, sword_list, cl=cl, free=free, owned_rows=owned_rows)
    owner = _actor(turn_flags=turn_flags)
    starter = _actor(OTHER)
    engine = _engine([owner, starter])
    monkeypatch.setattr(swords, 'fields', lambda engine, row: ['zone:field'])
    monkeypatch.setattr(swords, 'inside', lambda engine, zone, p: True)
    monkeypatch.setattr(swords, 'point', lambda sword: sword)
    monkeypatch.setattr(swords, 'perfected', lambda engine, row: True)
    asked = _recording_ask(monkeypatch, answer=list(answer))
    seen = []
    _recording_command(monkeypatch, seen)
    return engine, starter, owner, asked, seen


def test_two_twin_swords_without_a_field_each_get_their_own_move_and_are_not_hidden_from_ai(monkeypatch):
    first = _sword('floating')
    second = _sword('floating', slot=1, form='projected', item_uid='')
    engine, starter, owner, asked, seen = _off_turn(
        monkeypatch, [first, second], answer=['move:0', 'move:1'])
    monkeypatch.setattr(swords, 'inside', lambda engine, zone, p: False)  # no field at all
    swords.off_turn_sword_controls(engine, starter)
    assert asked[0]['options'][:2] == ['move:0', 'move:1']
    assert seen == [{'command': 'move:0', 'actor': A}, {'command': 'move:1', 'actor': A}]
    # Every legal option is offered to automatic owners too; the menu is no longer emptied for them.
    assert 'automatic_options' not in asked[0]['kw']
    assert asked[0]['kw']['maximum'] == len(asked[0]['options'])
    assert owner.turn_flags.get(f'sword_offturn:move:0:2:{OTHER}') and owner.turn_flags.get(f'sword_offturn:move:1:2:{OTHER}')
    assert 'sword_move:0' not in owner.turn_flags and 'sword_move:1' not in owner.turn_flags


def test_off_turn_offers_wielded_switch_mode_switch_and_one_return_per_turn(monkeypatch):
    twin = _sword('floating', form='projected', item_uid='')
    real = _sword('floating', slot=1)
    engine, starter, owner, asked, seen = _off_turn(
        monkeypatch, [twin, real], answer=['switch:1', 'guard:0', 'return:1'])
    swords.off_turn_sword_controls(engine, starter)
    options = asked[0]['options']
    assert {'move:0', 'move:1', 'switch:1', 'guard:0', 'guard:1', 'return:1'} <= set(options)
    # A projected sword can never be taken in hand.
    assert 'switch:0' not in options
    assert seen == [{'command': 'switch:1', 'actor': A}, {'command': 'guard:0', 'actor': A},
                    {'command': 'return:1', 'actor': A}]
    flags = {f'sword_offturn:switch:1:2:{OTHER}': True, f'sword_offturn:guard:0:2:{OTHER}': True,
             f'sword_offturn:return:2:{OTHER}': True}
    engine, starter, owner, asked, seen = _off_turn(monkeypatch, [twin, real], turn_flags=flags, answer=[])
    swords.off_turn_sword_controls(engine, starter)
    assert 'switch:1' not in asked[0]['options'] and 'guard:0' not in asked[0]['options']
    assert not [option for option in asked[0]['options'] if option.startswith('return:')]


def test_off_turn_moves_need_a_field_below_twin_level(monkeypatch):
    engine, starter, owner, asked, seen = _off_turn(
        monkeypatch, [_sword('floating', form='projected', item_uid='')], cl=10,
        owned_rows=(SEED, ARRAY), answer=[])
    monkeypatch.setattr(swords, 'inside', lambda engine, zone, p: False)
    swords.off_turn_sword_controls(engine, starter)
    assert asked == []


# ---------------------------------------------------------------- Finding 3: Sword-Qi Origin
def _technique_action(**typed):
    return SimpleNamespace(source_definition_id='action:typed.compendium.sword_technique',
                           parameters={'typed': typed}, owner_id=A)


def _origins(monkeypatch, action, *, sword_list=None, field_cells=(3, 4), dual=(7, 4), cl=18,
             weapon_hit=False, sword_family=True):
    _patch(monkeypatch, sword_list if sword_list is not None else [_sword('floating', x=dual[0], y=dual[1])], cl=cl)
    monkeypatch.setattr(swords, 'sword_technique', lambda engine, actor, act: sword_family)
    monkeypatch.setattr(swords, 'weapon_hit_technique', lambda act: weapon_hit)
    grid = SimpleNamespace(in_bounds=lambda cell: True, line_of_sight=lambda a, b: True)
    engine = _engine([_actor()])
    engine.state.zones = {}
    engine.grid = grid
    zone = SimpleNamespace(affected_cells=[SimpleNamespace(x=field_cells[0], y=field_cells[1])], center=SimpleNamespace(z=0))
    monkeypatch.setattr(swords, 'fields', lambda engine, actor: [zone])
    return swords._technique_origins(engine, _actor(), action)


def test_sword_qi_origin_offers_one_visible_field_point_distinct_from_both_swords(monkeypatch):
    origins = _origins(monkeypatch, _technique_action(), field_cells=(9, 9), dual=(7, 4))
    positions = {(row['position']['x'], row['position']['y']) for row in origins}
    assert (9, 9) in positions and (7, 4) in positions
    assert any(row['id'].startswith('sword:path:') for row in origins)


def test_weapon_hit_sword_technique_gets_only_actual_swords(monkeypatch):
    projected = _sword('floating', form='projected', item_uid='', x=2, y=3)
    origins = _origins(monkeypatch, _technique_action(delivered_by='action:typed.x.weapon.jian'),
                       sword_list=[projected], weapon_hit=True, field_cells=(9, 9))
    assert origins == []


def test_sword_qi_origin_is_inert_for_a_non_sword_technique(monkeypatch):
    assert _origins(monkeypatch, _technique_action(), field_cells=(9, 9), sword_family=False) is None


# ---------------------------------------------------------------- Finding 4: Call during a sword-delivered technique
def _delivered(action_source='action:typed.compendium.sword_technique', weapon=HELD_ACTION):
    return SimpleNamespace(source_definition_id=action_source, display_name='Compendium Sword Strike',
                           parameters={'typed': {'delivered_by': weapon}}, owner_id=A)


def test_sword_delivered_technique_offers_the_call_through_that_sword(monkeypatch):
    from combat import weapon_delivery
    _patch(monkeypatch, [_sword('floating', owner_id=A, weapon_action=HELD_ACTION)])
    monkeypatch.setattr(weapon_delivery, 'weapon_identity', lambda *a, **k: HELD_ACTION)
    engine = _engine([_actor()])
    ctx = SimpleNamespace(engine=engine, actor=_actor(), action=_delivered(), intent=object(), typed={})
    asked = _recording_ask(monkeypatch, answer=['0'])
    seen = []
    _recording_command(monkeypatch, seen)
    swords.technique_delivery_call(ctx)
    assert asked and asked[0]['choice_id'] == 'choice:needle.sword_array.technique-call'
    assert seen == [{'command': 'call:0', 'actor': A}]


def test_technique_call_needs_the_delivering_sword_and_a_free_hand(monkeypatch):
    from combat import weapon_delivery
    _patch(monkeypatch, [_sword('wielded', owner_id=A, weapon_action=HELD_ACTION)])
    monkeypatch.setattr(weapon_delivery, 'weapon_identity', lambda *a, **k: HELD_ACTION)
    engine = _engine([_actor()])

    def attempt():
        swords.technique_delivery_call(SimpleNamespace(engine=engine, actor=_actor(), action=_delivered(),
                                                       intent=object(), typed={}))
    asked = _recording_ask(monkeypatch, answer=['0'])
    attempt()
    _patch(monkeypatch, [_sword('floating', owner_id=A, weapon_action=HELD_ACTION)], free=False)
    attempt()
    monkeypatch.setattr(weapon_delivery, 'weapon_identity', lambda *a, **k: 'action:typed.other.weapon.spear')
    _patch(monkeypatch, [_sword('floating', owner_id=A, weapon_action=HELD_ACTION)])
    attempt()
    assert asked == []


def test_remote_sword_delivery_admits_only_a_floating_bound_sword(monkeypatch):
    _patch(monkeypatch, [_sword('floating', owner_id=A, weapon_action=HELD_ACTION)])
    engine = _engine([_actor()])
    assert swords.remote_sword_delivery(engine, _actor(), HELD_ACTION) is True
    assert swords.remote_sword_delivery(engine, _actor(), LENT_ACTION) is None
    _patch(monkeypatch, [_sword('wielded', owner_id=A, weapon_action=HELD_ACTION)])
    assert swords.remote_sword_delivery(engine, _actor(), HELD_ACTION) is None
    _patch(monkeypatch, [_sword('floating', owner_id=A, weapon_action=HELD_ACTION)], owned_rows=(SEED,))
    assert swords.remote_sword_delivery(engine, _actor(), HELD_ACTION) is None
