"""Cinder Touch through the real compiled character and fight engine.

Printed text (LocalSources/03_paths/Qi/Tianxia_Qi_Cultivation_Subpath_Compendium_R19.md, CL3):

    Gain Resistance to Fire damage.
    Once per turn, when one of your Qi-powered techniques deals damage, one creature damaged by
    the activation takes additional Fire damage equal to your Proficiency Bonus.

Both clauses are mandatory: the printed record offers no choice to decline the extra damage, so a
compiled character applies it automatically. The control case for the branch review's "declined
trigger" is therefore a character that does not own Cinder Touch: the same Qi-powered hit must gain
no extra Fire damage and no Fire Resistance.
"""
from __future__ import annotations

import json

from combat.gate2_runtime_models import ActionIntent, DiceSpec
from tests import h1_support as h

CINDER = "tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch"
QI_TECHNIQUES = ["FIRE_TAL_FLAME_LASH", "FIRE_BASE_IGNITE"]


def _flame_lash_hit(mids, *, seed):
    engine = h.duel(mids, seed=seed)
    before = engine.state.actors[h.FOE].current_hp
    h.script(engine, [20, 4, 4])
    events = h.use(engine, "Flame Lash", target=h.FOE)
    return engine, before - engine.state.actors[h.FOE].current_hp, events


def _cinder_events(events):
    return [event for event in events if CINDER in json.dumps(event.payload)]


def test_cinder_touch_adds_proficiency_bonus_fire_damage_once_per_turn():
    engine, _loss, events = _flame_lash_hit(QI_TECHNIQUES + [CINDER], seed="cinder-trigger")

    cinder = [
        event for event in _cinder_events(events)
        if event.event_type == "DAMAGE_COMMITTED"
    ]
    assert len(cinder) == 1
    extra = cinder[0].payload
    assert extra["display_source_id"] == f"passive:{CINDER}"
    assert extra["damage_type"] == "FIRE"
    assert extra["hp_damage"] == engine.state.actors[h.ME].proficiency_bonus

    engine.state.actors[h.ME].action_available = True
    h.script(engine, [20, 4, 4])
    second = h.use(engine, "Flame Lash", target=h.FOE)
    assert not [event for event in _cinder_events(second) if event.event_type == "DAMAGE_COMMITTED"]


def test_without_cinder_touch_the_same_hit_gets_no_extra_fire_damage():
    engine, control_loss, control_events = _flame_lash_hit(QI_TECHNIQUES, seed="cinder-trigger")
    _, cinder_loss, _ = _flame_lash_hit(QI_TECHNIQUES + [CINDER], seed="cinder-trigger")

    assert not _cinder_events(control_events)
    assert cinder_loss - control_loss == engine.state.actors[h.ME].proficiency_bonus


def _fire_hit_loss(mids):
    engine = h.duel(mids, seed="cinder-resistance")
    attacker, target = engine.state.actors[h.FOE], engine.state.actors[h.ME]
    spec = {
        "attack_bonus": 100,
        "damage": DiceSpec(count=2, sides=4, modifier=6),
        "damage_type": "FIRE",
        "reach_ft": 5,
    }
    intent = ActionIntent(
        intent_id="i-fire", decision_id="d-fire", candidate_id="c-fire",
        state_version=engine.state.state_version, actor_id=h.FOE, target_ids=(h.ME,),
    )
    before = target.current_hp
    h.script(engine, [4, 4, 4])
    engine._resolve_attack_spec(attacker, target, spec, intent, source_definition_id="test:fire", attack_index=1)
    return before - target.current_hp


def test_cinder_touch_grants_fire_resistance():
    control_loss = _fire_hit_loss(QI_TECHNIQUES)
    cinder_loss = _fire_hit_loss(QI_TECHNIQUES + [CINDER])

    assert control_loss == 14
    assert cinder_loss == control_loss // 2
