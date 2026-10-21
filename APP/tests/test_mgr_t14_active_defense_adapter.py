"""The portable native attack caller shares Active Defense's rolled boundary."""
import pytest

from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
from combat.gate2_runtime_models import ActionIntent
from tests.active_defense_authority_support import DEFENSE, install
from tests.h1_support import ME, FOE, duel, script

SHIELD = {'item_id': 'tianxia.mortal.armor.shield', 'name': 'Shield', 'quantity': 1}


def attack(engine, *, attack_bonus, natural):
    """Resolve one portable attack from the built-in sparring foe against ME."""
    attacker, target = engine.state.actors[FOE], engine.state.actors[ME]
    script(engine, [natural])
    intent = ActionIntent(intent_id='shield-portable', decision_id='test', candidate_id='test',
        state_version=engine.state.state_version, actor_id=FOE, target_ids=(ME,))
    start = len(engine.events)
    hit = CharacterCombatRuntimeEngine._resolve_character_attack(engine, attacker, target,
        source_id='test:portable-shield', attack_bonus=attack_bonus, damage=None, fixed_damage=2,
        damage_type='BLUDGEONING', intent=intent, ranged=False)
    return hit, engine.events[start:]


def test_portable_attack_offers_owned_defense_after_actual_roll(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch)
    engine = duel([DEFENSE], kit={'starting_kit': {'items': [SHIELD]}})
    target = engine.state.actors[ME]
    assert any(r.get('feature_id') == DEFENSE and r.get('after_attack_roll')
               for r in engine.typed_reaction_rows[ME])
    baseline_ac = target.armor_class + engine._ac_modifier(target)
    hit, events = attack(engine, attack_bonus=100, natural=1)
    assert not hit
    rolled = next(e for e in events if e.event_type == 'ATTACK_ROLLED')
    windows = [e for e in events if e.event_type == 'REACTION_WINDOW_OPENED'
               and e.source_definition_id == DEFENSE]
    assert len(windows) == 1
    assert windows[0].sequence > rolled.sequence
    assert windows[0].payload['checkpoint'] == 'ATTACK_ROLLED_BEFORE_DAMAGE'
    assert target.armor_class + engine._ac_modifier(target) == baseline_ac


@pytest.mark.parametrize('natural, expected_hit', [(10, False), (20, True)])
def test_portable_attack_recomputes_hit_with_attack_only_ac(tmp_path, monkeypatch, natural, expected_hit):
    install(tmp_path, monkeypatch)
    engine = duel([DEFENSE], kit={'starting_kit': {'items': [SHIELD]}})
    target = engine.state.actors[ME]
    if natural == 20:
        # Below the corrected AC, so only the printed natural-twenty rule keeps
        # this attack landing after the Shield's +2 arrives.
        target.armor_class = 30
    baseline_ac = target.armor_class + engine._ac_modifier(target)
    # A natural 10 total equal to the printed AC is a hit; Active Defense's +2
    # then makes it miss. A natural 20 still hits against the raised AC.
    hit, events = attack(engine, attack_bonus=baseline_ac - natural, natural=natural)
    assert hit is expected_hit
    assert any(e.event_type == 'REACTION_WINDOW_OPENED' and e.source_definition_id == DEFENSE
               for e in events)
    assert target.armor_class + engine._ac_modifier(target) == baseline_ac


def test_portable_attack_without_owned_defense_keeps_its_result_and_state():
    engine = duel([])
    target = engine.state.actors[ME]
    assert not any(r.get('feature_id') == DEFENSE for r in engine.typed_reaction_rows.get(ME, ()))
    baseline_ac = target.armor_class + engine._ac_modifier(target)
    before_hp = target.current_hp
    hit, events = attack(engine, attack_bonus=100, natural=19)
    assert hit is True
    assert not [e for e in events if e.event_type == 'REACTION_WINDOW_OPENED'
                and e.payload.get('checkpoint') == 'ATTACK_ROLLED_BEFORE_DAMAGE']
    assert target.current_hp == before_hp - 2
    assert target.armor_class + engine._ac_modifier(target) == baseline_ac
