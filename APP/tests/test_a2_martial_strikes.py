"""Strike-variant filter for Ancestral Channeler (include_variants=False) and Equal Measure.

F11 Finding 2 regression: martial_strikes.options() keys its include_variants=False skip on the
compiled MARK parameter (reach_bonus), not on a '#' in the action id. Generated '#' variants such as
'#integrated_con' always carry MARK, so live content is unchanged; the discriminating case is a base
strike whose id contains '#' but has no MARK. Pre-fix '#' logic drops it and fails; MARK logic keeps it.
"""
from types import SimpleNamespace

from combat.ext import martial_strikes, reach_bonus
from combat import attack_reach


class _Economy:
    value = "ACTION"


def _action(aid, parameters):
    return SimpleNamespace(action_id=aid, economy=_Economy(), range_ft=5, reach_ft=None, costs=(), parameters=parameters)


def _typed():
    return {"weapon": "qiang", "effects": [{"type": "attack", "attack_kind": "melee_weapon"}]}


def _engine(actions):
    return SimpleNamespace(
        action_catalog={a.action_id: a for a in actions},
        _effect_distance=lambda actor, target: 5,
        _has_condition=lambda actor, condition: True,
    )


def _patch(monkeypatch):
    monkeypatch.setattr(martial_strikes, "ready", lambda engine, actor, action: True)
    monkeypatch.setattr(attack_reach, "melee", lambda action: True)
    monkeypatch.setattr(reach_bonus, "current_reach", lambda engine, actor, action: 5)


def _run(monkeypatch, actions, **kwargs):
    _patch(monkeypatch)
    engine = _engine(actions)
    actor = SimpleNamespace(action_ids=[a.action_id for a in actions], entity_id="actor:test")
    target = SimpleNamespace(entity_id="target:test")
    return [row[0].action_id for row in martial_strikes.options(engine, actor, target, **kwargs)]


def test_channeler_keeps_base_strike_whose_id_has_hash_but_no_mark(monkeypatch):
    base = _action("strike.qiang#note", {"typed": _typed(), "expected_damage": 6})
    selected = _run(monkeypatch, [base], include_variants=False)
    assert selected == ["strike.qiang#note"]


def test_channeler_excludes_mark_variant(monkeypatch):
    base = _action("strike.qiang", {"typed": _typed(), "expected_damage": 6})
    variant = _action("strike.qiang.reach_10", {
        "typed": _typed(), "expected_damage": 6,
        reach_bonus.MARK: {"base": "strike.qiang", "menu_variant": True},
    })
    assert _run(monkeypatch, [base, variant], include_variants=False) == ["strike.qiang"]


def test_equal_measure_default_keeps_base_strike(monkeypatch):
    base = _action("strike.qiang#note", {"typed": _typed(), "expected_damage": 6})
    assert _run(monkeypatch, [base]) == ["strike.qiang#note"]
