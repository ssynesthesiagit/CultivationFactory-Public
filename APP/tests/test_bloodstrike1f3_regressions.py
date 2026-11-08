"""BLOODSTRIKE1F3 regressions: Bloodline Strike gates, one affinity, and the Source Rule exception.

Pure unit tests on the compiled hook helpers; no live model, service or running server is touched.
"""
from types import SimpleNamespace

from combat.ext import ancestral_bloodline as lineage
from combat.typed_executor import Context

GIFT = lineage.GIFT
AFFINITY = lineage.AFFINITY
PERMIT = lineage.REPEAT_PERMISSION


def cond(condition_id, **data):
    return SimpleNamespace(condition_id=condition_id, data=data)


def actor(*conditions):
    return SimpleNamespace(conditions={i: c for i, c in enumerate(conditions)}, turn_flags={}, active=True)


def action(source="", costs=(), typed_extra=None):
    typed = {"source": source, **(typed_extra or {})}
    return SimpleNamespace(costs=tuple(costs), parameters={"typed": typed}, source_definition_id="action:x")


# Finding 1: the Crimson Court zone path is gated by the creating action's own printed basis, not by a guess.
def test_crimson_court_aura_is_not_a_qi_powered_activation():
    court = action("tianxia.talent.blood.crimson_court", costs=[("resource:named.cp", 7)])
    assert lineage._source_qi_powered(court) is False


def test_qi_costed_zone_creator_is_qi_powered():
    zone = action("tianxia.subpath.qi.synthetic.field", costs=[("resource:named.qi", 2)])
    assert lineage._source_qi_powered(zone) is True


def test_missing_creating_action_never_offers_the_strike():
    assert lineage._source_qi_powered(None) is False


def test_qi_zone_qualification_survives_trigger_context(monkeypatch):
    calls = []
    monkeypatch.setattr(lineage, "bloodline_strike",
                        lambda ctx, **kwargs: calls.append((ctx.technique_event_start, kwargs)))
    owner = SimpleNamespace(entity_id="owner")
    engine = SimpleNamespace(events=[object(), object()])
    ctx = Context(
        engine=engine, actor=owner, intent=None, targets=[],
        action=action("tianxia.subpath.qi.synthetic.field"),
        damage_cache={"bloodline_zone_start": 1}, typed={"source": "zone.trigger"},
        technique_event_start=None,
    )
    lineage.strike_zone_damage(ctx, SimpleNamespace(), 5)
    assert calls == [(1, {"qi_qualified": True})]
    assert ctx.technique_event_start is None  # Only the child context gets the trigger window.


# The independent Insight must not override the Subpath's permanent affinity.
def test_strike_affinity_is_the_subpath_recorded_affinity_not_the_insight_gift():
    # BLOODSTRIKE1F6RSC finding 1: a Cold Subpath affinity with a Fire Insight gift strikes Cold.
    owner = actor(cond(GIFT, gift="dragon", damage_type="FIRE"), cond(AFFINITY, damage_type="cold"))
    assert lineage.chosen_damage(owner) == "FIRE"
    assert lineage.strike_affinity(owner) == "cold"


def test_strike_affinity_falls_back_to_the_gift_type_only_without_a_recorded_affinity():
    owner = actor(cond(GIFT, gift="dragon", damage_type="FIRE"))
    assert lineage.strike_affinity(owner) == "fire"
    assert lineage.strike_affinity(actor(cond(GIFT, gift="fox", damage_type=""))) == ""


# Finding 3: the Source Rule exception to once across a multiattack.
def test_multiattack_shares_one_turn_flag_without_a_source_rule_permission():
    owner = actor(cond(GIFT, gift="dragon", damage_type="FIRE"))
    first = lineage.strike_flag(owner, SimpleNamespace(technique_event_start=3))
    second = lineage.strike_flag(owner, SimpleNamespace(technique_event_start=9))
    assert first == second == "typed_once_turn:bloodline_strike"


def test_source_rule_permission_gives_each_activation_its_own_strike():
    owner = actor(cond(GIFT, gift="dragon", damage_type="FIRE"), cond(PERMIT))
    first = lineage.strike_flag(owner, SimpleNamespace(technique_event_start=3))
    second = lineage.strike_flag(owner, SimpleNamespace(technique_event_start=9))
    assert first != second
