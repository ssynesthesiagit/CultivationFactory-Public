"""Active Defense's +2 is bounded to the triggering attack (SHIELD_BASE_ACTIVE_DEFENSE).

The reviewed row lives in ``reviewed_final.d/ironroot.json`` and reaches the
engine only through the generated authority. A source edit that is never
rebuilt silently restores the old until-next-turn modifier, so the first test
pins the generated data and the others play the printed clauses on the engine.
"""
import json

import pytest

from tests.h1_support import ROOT
from tests.test_auto55_shield import ME, THEM, _fight, _stab
from tests.test_auto_lane4 import _script

GENERATED = ROOT / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json'
REVIEWED = ROOT / 'authority/typed_mechanics/reviewed_final.d/ironroot.json'
ROW = 'SHIELD_BASE_ACTIVE_DEFENSE'


@pytest.fixture(scope='module', autouse=True)
def printed_active_defense_trigger(tmp_path_factory):
    """Compile the row from its actual printed trigger on every checkout.

    The public test export redacts printed prose, including ``activation.trigger``,
    and the compiler parses that trigger to decide a reaction is runnable. Restore
    the row's printed trigger so these tests exercise the engine, not the export's
    redaction. On a normal checkout this writes the same text it already has.
    """
    from combat import factory_compiler

    original = factory_compiler.TYPED_AUTHORITY
    authority = json.loads(GENERATED.read_text())
    authority['mechanics'][ROW]['activation']['trigger'] = (
        'A creature you are aware of makes an attack roll against you')
    path = tmp_path_factory.mktemp('printed-authority') / 'authority.json'
    path.write_text(json.dumps(authority))
    factory_compiler.TYPED_AUTHORITY = path
    try:
        yield
    finally:
        factory_compiler.TYPED_AUTHORITY = original


def test_generated_authority_bounds_active_defense_to_the_triggering_attack():
    """Editing the reviewed row must reach the generated authority the compiler reads."""
    reviewed = json.loads(REVIEWED.read_text())['mechanics'][ROW]
    generated = json.loads(GENERATED.read_text())['mechanics'][ROW]
    for row in (reviewed, generated):
        ac = [e for e in row['effects'] if e.get('type') == 'ac_bonus']
        assert ac and all(e.get('duration') == 'triggering_attack' for e in ac), row['effects']


def _attack_roll(engine):
    return next(e for e in reversed(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id != ME)


def test_after_roll_bonus_turns_a_hit_into_a_miss_and_leaves_no_modifier():
    """A total that exactly meets AC hits; the +2 then applies only to that attack."""
    probe = _fight([])
    me = probe.state.actors[ME]
    me.armor_class = 60  # a miss on its own; the bonus is still offered (printed "after the roll")
    _script(probe, [5])
    _stab(probe)
    rolled = _attack_roll(probe)
    total = int(rolled.payload['modified_total'])
    natural = int(rolled.payload['natural_result'])
    assert natural == 5

    engine = _fight([])
    me = engine.state.actors[ME]
    me.armor_class = total - engine._ac_modifier(me)  # total == effective AC: a hit by exactly 0
    assert me.armor_class + engine._ac_modifier(me) == total
    hp = me.current_hp
    _script(engine, [natural])
    _stab(engine)
    rolled = _attack_roll(engine)
    assert int(rolled.payload['target_ac']) == total and rolled.payload['provisional_hit'] is True
    recheck = next(e for e in engine.events if e.event_type == 'REACTION_RESOLVED'
                   and e.payload.get('checkpoint') == 'AFTER_ATTACK_ROLL_DEFENSES')
    assert recheck.payload['ac_bonus'] == 2
    assert recheck.payload['new_ac'] == total + 2
    assert recheck.payload['hit_after_recheck'] is False
    assert me.current_hp == hp  # the attack really missed
    assert not any(m.source_definition_id == ROW for m in me.modifiers.values())
    assert me.armor_class + engine._ac_modifier(me) == total  # no modifier outlived the attack


@pytest.mark.parametrize('natural,hit', [(1, False), (20, True)])
def test_natural_one_and_natural_twenty_keep_their_printed_outcome(natural, hit):
    """Natural 1 always misses and natural 20 always hits, with or without the +2."""
    engine = _fight([])
    me = engine.state.actors[ME]
    me.armor_class = 60  # out of reach for an ordinary total
    hp = me.current_hp
    _script(engine, [natural])
    _stab(engine)
    rolled = _attack_roll(engine)
    assert int(rolled.payload['natural_result']) == natural
    assert (me.current_hp < hp) is hit


@pytest.mark.parametrize('natural,expected_hit', [(10, False), (20, True)])
def test_portable_declaration_rechecks_the_hit_after_the_bonus(natural, expected_hit):
    """The portable adapter runs the same after-roll seam as the native engine.

    A total that exactly meets the ordinary AC is a provisional hit; the +2 then
    rechecks that same attack. A natural 20 keeps its printed outcome.
    """
    from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
    from combat.gate2_runtime_models import ActionIntent

    engine = _fight([])
    me, them = engine.state.actors[ME], engine.state.actors[THEM]
    runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
    runtime.__dict__.update(engine.__dict__)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.display_name == 'Bi Shou (Dagger) attack' and a.owner_id == THEM)
    candidate = next(c for c in engine.legal_candidates() if c.kind == 'END_TURN')
    intent = ActionIntent(intent_id='journey:portable-shield', decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=ME)
    assert me.armor_class + engine._ac_modifier(me) == 18
    hp = me.current_hp
    _script(engine, [natural])
    hit = CharacterCombatRuntimeEngine._resolve_character_attack(
        runtime, them, me, source_id=source, attack_bonus=8, damage=None, damage_type='PIERCING',
        intent=intent, fixed_damage=5, ranged=False)
    rolled = next(e for e in runtime.events if e.event_type == 'ATTACK_ROLLED')
    assert int(rolled.payload['target_ac']) == 18 and rolled.payload['provisional_hit'] is True
    rechecks = [e for e in runtime.events if e.event_type == 'REACTION_RESOLVED'
                and e.payload.get('checkpoint') == 'AFTER_ATTACK_ROLL_DEFENSES']
    assert hit is expected_hit
    if natural == 20:
        assert me.current_hp == hp - 5 and rechecks[0].payload['hit_after_recheck'] is True
    else:
        assert me.current_hp == hp
        assert rechecks[0].payload['ac_bonus'] == 2 and rechecks[0].payload['new_ac'] == 20
        assert rechecks[0].payload['hit_after_recheck'] is False
    assert not [m for m in me.modifiers.values() if m.source_definition_id == ROW]


def test_journey_started_fight_keeps_the_tables_ask_reaction_plan(tmp_path, monkeypatch):
    """Manual/Ask me ownership belongs to fights started from a journey too."""
    from canonical_catalog.service import CanonicalCatalogAuthorityService
    from tests.test_journey_activities_native import A, B, game

    cold, jid, _act, _world = game(tmp_path, monkeypatch, CanonicalCatalogAuthorityService(ROOT), sphere='shield')
    state = cold().journey_state(jid)
    mid = cold().journey_start_combat(jid, state['revision'], {A: 'team:a', B: 'team:b'}, maximum_rounds=1)['match_id']
    engine = cold()._load_session(mid).engine
    assert A in engine.typed_ask_reactors
