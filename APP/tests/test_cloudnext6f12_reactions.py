"""Regression coverage for paid reaction reservations and conscious-at-zero reactions."""
from types import SimpleNamespace

import pytest

from tests.test_tripwires import _echoed, _thunder
from tests.test_oareact_reaction_economy import _engine, _walk_away, THREAD_ID
from tests.test_a2_shadow import marked_fight, ambush_events
from tests.auto_worker1_support import LEFT, RIGHT, reload
from tests.test_a2_treasure_armor_enhancements import kit, AUTH
from tests.worker2_support import fixture, OWNER, ALLY, FOE, sealed_native_attack
from combat.ext.drum_body import ECHO_DETONATION, ECHOING, PREFIX


def echo(engine, target, source):
    engine._apply_condition(target, ECHOING, PREFIX + 'internal_echo', source.entity_id,
        expires_on='END_OF_CURRENT_TURN', data={'trips_on': ['reaction', 'cp_spend'],
        'on_trip': ECHO_DETONATION, 'pb': 4, 'cl': 15, 'save_dc': 15})


@pytest.mark.parametrize('with_echo', [False, True])
def test_ambush_resolves_after_one_reaction_payment(tmp_path, with_echo):
    from combat.ext.shadow import _ambush
    c, t, mid = marked_fight(tmp_path, ai=True)
    engine = reload(c, mid)
    owner, subject = engine.state.actors[LEFT], engine.state.actors[RIGHT]
    if with_echo:
        echo(engine, owner, subject)
    before = owner.current_hp
    _ambush(engine, subject, 'ends its turn')
    assert len(ambush_events(engine)) == 1
    assert not owner.reaction_available
    assert owner.resources['resource:core.qi'] == 98
    assert subject.current_hp < 1000
    assert (owner.current_hp < before) == with_echo


@pytest.mark.parametrize('with_echo', [False, True])
def test_deflecting_shield_resolves_after_one_reaction_payment(tmp_path, monkeypatch, with_echo):
    from combat.ext import treasure_armor
    from combat.ext.cp_pools import of
    def transform(bundles):
        sealed_native_attack(bundles[2], 'Heavy Strike', count=1, sides=2, modifier=35, attack_bonus=100)
    treasure = kit('deflecting_shield_face')
    treasure['resolved_treasure_armor']['chassis'] = next(r for r in AUTH['chassis'] if r['armor_category'] == 'shield')
    c, t, mid = fixture(tmp_path, [], owner_kit={'starting_kit': treasure}, owner_pb=5,
        bundle_transform=transform, ally_position={'x':4,'y':6}, foe_position={'x':4,'y':7})
    engine = reload(c, mid)
    owner, target, foe = (engine.state.actors[k] for k in (OWNER, ALLY, FOE))
    if with_echo:
        echo(engine, owner, foe)
    hp, cp = owner.current_hp, owner.resources[of(owner)]
    monkeypatch.setattr(engine, 'damage_context', lambda: SimpleNamespace(target_id=ALLY, roll_id='test-roll'))
    monkeypatch.setattr(treasure_armor, 'ask', lambda *a, **k: ['use'])
    result = treasure_armor.deflecting_shield(engine, target, 35, 'FIRE', 'test:attack', FOE, object())
    assert result and result['reduction'] > 0
    assert owner.resources[of(owner)] == cp - 1
    assert not owner.reaction_available
    assert (owner.current_hp < hp) == with_echo
    assert any(r.reason == 'TREASURE_SHIELD_REDUCTION' for r in engine.rolls)


def test_conscious_at_zero_opportunity_attack_still_resolves():
    engine = _engine()
    actor = engine.state.actors[THREAD_ID]
    actor.current_hp = 0
    actor.life_state = 'CONSCIOUS'
    assert actor.active
    events = _walk_away(engine)
    assert any(e.event_type == 'REACTION_RESOLVED' for e in events)
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == THREAD_ID for e in events)
    assert not actor.reaction_available
