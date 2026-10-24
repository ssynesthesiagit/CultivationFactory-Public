"""Sol seam review (Ten Thousand Sword Array Cultivator) blocking-finding regressions.

Finding 1: Twin owners get the printed once-per-turn free floating/wielded switch.
Finding 2: Sword-Qi Origin covers any qualifying sword-technique Qi action from the sword-path points.
Finding 3: A live one-hour manifestation leaves the fight snapshot, its clock is exported and ticks during travel.
Finding 4: Call the Seed Sword is also free in the window a completed Attack action opens.
"""
from fractions import Fraction
from types import SimpleNamespace

from combat.ext import ten_thousand_swords as swords
from combat.ext import hand_occupancy
from combat.ext.ten_thousand_swords import FAMILY, SEED, TWIN

A = 'actor:sword-owner'


def _sword(location='floating', form='real', x=2, y=3, z=0, **extra):
    return {'slot': 0, 'form': form, 'location': location, 'mode': 'assault', 'damage_type': 'force',
            'item_uid': 'item:sword', 'weapon_action': 'action:sword', 'x': x, 'y': y, 'z': z, **extra}


def _actor(conditions=()):
    return SimpleNamespace(entity_id=A, position=SimpleNamespace(x=2, y=2, z=0), turn_flags={},
                           conditions={c.condition_id: c for c in conditions})


def _patch_twin(monkeypatch, swords_list, cl=14, free=True):
    monkeypatch.setattr(swords, 'owned', lambda engine, actor, source=SEED: True)
    monkeypatch.setattr(swords, 'numbers', lambda engine, actor: {'cl': cl})
    monkeypatch.setattr(swords, 'state', lambda actor: {'swords': swords_list, 'origin_used': False})
    monkeypatch.setattr(swords, 'incapacitated', lambda actor: False)
    monkeypatch.setattr(hand_occupancy, 'free_hands', lambda engine, actor: ['hand:left'] if free else [])


# Finding 1: printed Twin free switch, once per turn, real sword needs a free hand.
def _switch_action(slot):
    return SimpleNamespace(parameters={'sword_array': 'switch:' + str(slot), 'typed': {'source': TWIN}})


def test_twin_owner_can_switch_floating_real_sword_to_wielded_once_per_turn(monkeypatch):
    actor = _actor()
    _patch_twin(monkeypatch, [_sword('floating')])
    allowed = swords.candidates(object(), actor, None, _switch_action(0))
    assert allowed is True
    actor.turn_flags['sword_switch:0'] = True
    assert swords.candidates(object(), actor, None, _switch_action(0)) is False


def test_switch_rejects_projected_sword_and_missing_free_hand(monkeypatch):
    actor = _actor()
    _patch_twin(monkeypatch, [_sword('floating', form='projected')])
    assert swords.candidates(object(), actor, None, _switch_action(0)) is False
    _patch_twin(monkeypatch, [_sword('floating')], free=False)
    assert swords.candidates(object(), actor, None, _switch_action(0)) is False


def test_switch_below_twin_level_is_unavailable(monkeypatch):
    _patch_twin(monkeypatch, [_sword('floating')], cl=13)
    assert swords.candidates(object(), _actor(), None, _switch_action(0)) is False


# Finding 2: Sword-Qi Origin for a qualifying sword-technique Qi action, not only this plug-in's strike.
def _technique_action(**typed):
    return SimpleNamespace(source_definition_id='action:other', parameters={'typed': typed})


def test_qi_sword_technique_originates_from_sword_path_point(monkeypatch):
    monkeypatch.setattr(swords, 'owned', lambda engine, actor, source=SEED: True)
    monkeypatch.setattr(swords, 'state', lambda actor: {'swords': [_sword('floating', x=7, y=4, z=2)]})
    from combat import activation_settlement
    monkeypatch.setattr(activation_settlement, 'profile', lambda engine, actor, action: {'qi_powered': True})
    origins = swords.committed_packet_origin(object(), _actor(), _technique_action(sword_technique=True))
    assert origins and origins[0]['position'] == {'x': 7, 'y': 4, 'z': 2}


def test_unrelated_non_sword_technique_gets_no_remote_origin(monkeypatch):
    monkeypatch.setattr(swords, 'owned', lambda engine, actor, source=SEED: True)
    monkeypatch.setattr(swords, 'state', lambda actor: {'swords': [_sword('floating')]})
    from combat import activation_settlement
    monkeypatch.setattr(activation_settlement, 'profile', lambda engine, actor, action: {'qi_powered': True})
    assert not swords.committed_packet_origin(object(), _actor(), _technique_action())


# Finding 3: a live one-hour manifestation is not part of the fight snapshot; its clock is exported and ticks.
def test_snapshot_adapter_drops_only_own_manifestation(monkeypatch):
    monkeypatch.setattr(swords, 'owned', lambda engine, actor, source=SEED: True)
    cond_manifest = SimpleNamespace(condition_id=swords.MANIFEST_PREFIX + '0')
    cond_other = SimpleNamespace(condition_id='condition:other')

    class Creature:
        conditions = {}

        def model_copy(self, deep=False):
            copied = Creature()
            copied.conditions = dict(self.conditions)
            return copied

    creature = Creature()
    creature.conditions = {cond_manifest.condition_id: cond_manifest, cond_other.condition_id: cond_other}
    snap = swords.snapshot_without_manifests(creature, None, A, object())
    assert set(snap.conditions) == {cond_other.condition_id}
    assert set(creature.conditions) == {cond_manifest.condition_id, cond_other.condition_id}


def test_travel_ticks_manifest_clock_and_expires_it(monkeypatch):
    session = SimpleNamespace(state={'actors': {A: {'source_states': {FAMILY: {
        'manifest_seconds': {'0': str(Fraction(600))},
        'swords': [_sword('floating')]}}}}})
    swords.travel_manifest_clock(session, A, Fraction(0), Fraction(120), ())
    data = session.state['actors'][A]['source_states'][FAMILY]
    assert data['manifest_seconds'] == {'0': str(Fraction(480))}
    swords.travel_manifest_clock(session, A, Fraction(120), Fraction(480), ())
    assert data['manifest_seconds'] == {}
    assert data['swords'][0]['location'] == 'carried'


def test_restore_uses_remaining_clock_after_travel(monkeypatch):
    calls = []

    class Engine:
        class state:
            round_number = 1
            current_slot_index = 0
        def _apply_condition(self, actor, cid, source, src_id, expires_on=None, data=None):
            calls.append((cid, expires_on))

    actor = SimpleNamespace(entity_id=A)
    monkeypatch.setattr(swords, 'state', lambda a: {'swords': [_sword('floating')]})
    monkeypatch.setattr(swords, 'save', lambda engine, a, s, source=None: None)
    swords.restore_manifests(Engine(), actor, {'manifest_seconds': {'0': str(Fraction(60))}})
    assert calls and calls[0][0] == swords.MANIFEST_PREFIX + '0'


# Finding 4 (blocking, review F11): Call the Seed Sword is also free during the Attack action (printed "at the beginning or
# end of your Attack action"), not only as a Bonus Action. A completed Attack action opens the window once.
from combat.gate2_runtime_models import EconomyKind


def _engine(source_id='action:attack', actor_id=A, action=None):
    catalog = {source_id: action} if action is not None else {}
    return SimpleNamespace(state=SimpleNamespace(round_number=1, current_actor_id=actor_id), action_catalog=catalog)


def _attack_action(**typed):
    return SimpleNamespace(parameters={'typed': {'attack_action': True, **typed}}, economy=EconomyKind.ACTION)


def _attack_call_action(slot=0):
    return SimpleNamespace(parameters={'sword_array': 'attack_call:' + str(slot), 'typed': {'source': SEED}})


def test_completed_attack_action_opens_free_call_window(monkeypatch):
    actor = _actor()
    _patch_twin(monkeypatch, [_sword('floating')], cl=3)
    monkeypatch.setattr(swords, 'owned', lambda engine, actor, source=SEED: True)
    engine = _engine(action=_attack_action())
    assert swords.candidates(engine, actor, None, _attack_call_action()) is False
    swords.attack_action_window(engine, actor, EconomyKind.ACTION, 'action:attack')
    assert swords.candidates(engine, actor, None, _attack_call_action()) is True


def test_bonus_action_or_non_attack_closes_window_and_call_is_spent(monkeypatch):
    actor = _actor()
    _patch_twin(monkeypatch, [_sword('floating')], cl=3)
    monkeypatch.setattr(swords, 'owned', lambda engine, actor, source=SEED: True)
    engine = _engine(action=_attack_action())
    swords.attack_action_window(engine, actor, EconomyKind.ACTION, 'action:attack')
    swords.attack_action_window(engine, actor, EconomyKind.BONUS_ACTION, 'action:bonus')
    assert swords.candidates(engine, actor, None, _attack_call_action()) is False
    swords.attack_action_window(engine, actor, EconomyKind.ACTION, 'action:attack')
    actor.turn_flags[swords.ATTACK_WINDOW] = None  # what the command does when the call is used
    assert swords.candidates(engine, actor, None, _attack_call_action()) is False


def test_reaction_attack_does_not_open_call_window(monkeypatch):
    actor = _actor()
    monkeypatch.setattr(swords, 'owned', lambda engine, actor, source=SEED: True)
    engine = _engine(action=_attack_action(reaction_attack=True))
    swords.attack_action_window(engine, actor, EconomyKind.ACTION, 'action:attack')
    assert not swords.attack_window_open(engine, actor)

