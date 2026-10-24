"""Sol seam review round 10 (Ten Thousand Sword Array Cultivator) blocking-finding regressions.

Finding 1: Call the Seed Sword is available at the beginning of an Attack action, before its attacks, as a free checkpoint.
Finding 2: Off-turn field movement and Return to the Hand are offered to the owner during another creature's turn, once per turn.
"""
from types import SimpleNamespace

from combat.ext import ten_thousand_swords as swords
from combat.ext import hand_occupancy
from combat.ext.ten_thousand_swords import SEED, RETURN, ATTACK_WINDOW
from combat.gate2_runtime_models import EconomyKind

A = 'actor:sword-owner'
STARTER = 'actor:other-creature'


def _sword(location='floating', form='real', **extra):
    return {'slot': 0, 'form': form, 'location': location, 'mode': 'assault', 'damage_type': 'force',
            'item_uid': 'item:sword', 'weapon_action': 'action:sword', 'x': 2, 'y': 3, 'z': 0, **extra}


def _actor(turn_flags=None):
    return SimpleNamespace(entity_id=A, active=True, position=SimpleNamespace(x=2, y=2, z=0),
                           turn_flags=dict(turn_flags or {}), conditions={})


def _patch(monkeypatch, sword_list, cl=18, free=True, owned_rows=(SEED, RETURN)):
    monkeypatch.setattr(swords, 'owned', lambda engine, actor, source=SEED: source in owned_rows and actor.entity_id == A)
    monkeypatch.setattr(swords, 'numbers', lambda engine, actor: {'cl': cl})
    monkeypatch.setattr(swords, 'state', lambda actor: {'swords': sword_list, 'origin_used': False})
    monkeypatch.setattr(swords, 'incapacitated', lambda actor: False)
    monkeypatch.setattr(swords, 'checkpoint_id', lambda *a, **k: 'checkpoint:test')
    monkeypatch.setattr(hand_occupancy, 'free_hands', lambda engine, actor: ['hand:left'] if free else [])


def _attack_action(economy=EconomyKind.ACTION):
    return SimpleNamespace(source_definition_id='action:attack', economy=economy,
                           parameters={'typed': {'attack_action': True}})


def _recording_ask(monkeypatch, answer):
    asked = []

    def fake_ask(engine, intent, checkpoint, chooser, choice_id, options, **kw):
        asked.append({'chooser': chooser.entity_id, 'options': list(options), 'kw': kw})
        return [o for o in answer if o in options]
    monkeypatch.setattr(swords, 'ask', fake_ask)
    return asked


def _recording_command(monkeypatch, seen):
    def fake_command(ctx, eff):
        seen.append({'command': eff['command'], 'window': ctx.actor.turn_flags.get(ATTACK_WINDOW),
                     'actor': ctx.actor.entity_id})
    monkeypatch.setattr(swords, 'command', fake_command)


def _fight_engine(current, round_number=2):
    return SimpleNamespace(state=SimpleNamespace(round_number=round_number, current_actor_id=current, actors={}),
                           _active_intent=object(), action_catalog={})


# Finding 1: beginning-of-Attack Call checkpoint.
def test_beginning_of_attack_offers_call_and_runs_the_free_call(monkeypatch):
    actor = _actor()
    _patch(monkeypatch, [_sword('floating')], cl=3)
    asked = _recording_ask(monkeypatch, answer=['0'])
    seen = []
    _recording_command(monkeypatch, seen)
    swords.attack_start_call(_fight_engine(A), actor, _attack_action())
    assert asked and asked[0]['options'] == ['0']
    assert seen == [{'command': 'attack_call:0', 'window': f'2:{A}', 'actor': A}]
    assert ATTACK_WINDOW not in actor.turn_flags


def test_beginning_of_attack_declined_or_unavailable_does_not_call(monkeypatch):
    actor = _actor()
    _patch(monkeypatch, [_sword('floating')], cl=3)
    _recording_ask(monkeypatch, answer=[])
    seen = []
    _recording_command(monkeypatch, seen)
    swords.attack_start_call(_fight_engine(A), actor, _attack_action())
    assert seen == []
    asked = _recording_ask(monkeypatch, answer=['0'])
    prefight = _fight_engine(A)
    prefight._active_intent = None
    swords.attack_start_call(prefight, actor, _attack_action())
    swords.attack_start_call(_fight_engine(A), actor, _attack_action(economy=EconomyKind.BONUS_ACTION))
    assert asked == [] and seen == []


def test_beginning_call_needs_a_floating_real_sword_and_free_hand(monkeypatch):
    actor = _actor()
    _patch(monkeypatch, [_sword('wielded')], cl=3)
    asked = _recording_ask(monkeypatch, answer=['0'])
    swords.attack_start_call(_fight_engine(A), actor, _attack_action())
    _patch(monkeypatch, [_sword('floating')], cl=3, free=False)
    swords.attack_start_call(_fight_engine(A), actor, _attack_action())
    assert asked == []


# Finding 2: off-turn owner checkpoint at another creature's turn start.
def _off_turn_setup(monkeypatch, sword_list, cl=18, answer=(), turn_flags=None):
    _patch(monkeypatch, sword_list, cl=cl)
    owner = _actor(turn_flags)
    starter = SimpleNamespace(entity_id=STARTER, active=True, turn_flags={}, conditions={})
    engine = _fight_engine(STARTER)
    engine.state.actors = {A: owner, STARTER: starter}
    monkeypatch.setattr(swords, 'fields', lambda engine, actor: ['zone:field'])
    monkeypatch.setattr(swords, 'inside', lambda engine, zone, p: True)
    monkeypatch.setattr(swords, 'point', lambda sword: sword)
    monkeypatch.setattr(swords, 'destinations',
                        lambda engine, actor, sword, **kw: [actor.position] if kw.get('call') else ['p'])
    monkeypatch.setattr(swords, 'perfected', lambda engine, actor: True)
    asked = _recording_ask(monkeypatch, answer=list(answer))
    seen = []
    _recording_command(monkeypatch, seen)
    return engine, starter, owner, asked, seen


def test_owner_gets_off_turn_field_move_and_return_during_another_turn(monkeypatch):
    engine, starter, owner, asked, seen = _off_turn_setup(monkeypatch, [_sword('floating')], answer=['move:0'])
    swords.off_turn_sword_controls(engine, starter)
    assert asked[0]['chooser'] == A and asked[0]['options'] == ['move:0', 'return:0']
    assert asked[0]['kw']['automatic_options'] == []
    assert seen == [{'command': 'move:0', 'window': None, 'actor': A}]
    assert owner.turn_flags.get(f'sword_offturn:move:0:2:{STARTER}') is True
    assert 'sword_move:0' not in owner.turn_flags


def test_off_turn_move_is_once_per_turn_and_return_restores_own_turn_flag(monkeypatch):
    flags = {f'sword_offturn:move:0:2:{STARTER}': True}
    engine, starter, owner, asked, seen = _off_turn_setup(monkeypatch, [_sword('floating')], answer=[], turn_flags=flags)
    swords.off_turn_sword_controls(engine, starter)
    assert asked[0]['options'] == ['return:0']
    engine, starter, owner, asked, seen = _off_turn_setup(monkeypatch, [_sword('floating')], answer=['return:0'])
    owner.turn_flags['sword_return'] = False
    swords.off_turn_sword_controls(engine, starter)
    assert seen == [{'command': 'return:0', 'window': None, 'actor': A}]
    assert owner.turn_flags['sword_return'] is False


def test_off_turn_controls_need_field_return_level_and_not_owner_turn(monkeypatch):
    engine, starter, owner, asked, seen = _off_turn_setup(monkeypatch, [_sword('floating')], answer=['move:0'])
    swords.off_turn_sword_controls(engine, owner)
    assert asked == []
    engine, starter, owner, asked, seen = _off_turn_setup(monkeypatch, [_sword('floating')], cl=10, answer=[])
    swords.off_turn_sword_controls(engine, starter)
    assert asked[0]['options'] == ['move:0']
    monkeypatch.setattr(swords, 'inside', lambda engine, zone, p: False)
    asked.clear()
    swords.off_turn_sword_controls(engine, starter)
    assert asked == []
