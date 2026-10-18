"""Regressions for the Blood-Moon review findings; all fixtures are synthetic."""
from types import SimpleNamespace as NS

import combat.ext.mgr_reserve_blood_moon_execution_saber_cultivator_write_the_first_sentence as blood


def test_cut_breath_does_not_charge_non_qi_activation(monkeypatch):
    actor = NS(resources={"resource:core.qi": 10}, conditions={
        "surcharge": NS(condition_id=blood.STATE, data={
            "kind": "surcharge", "resource": blood.QI, "amount": 2
        })
    })
    action = NS()
    engine = NS(action_catalog={"action:cp": action})
    monkeypatch.setattr("combat.activation_settlement.profile",
        lambda *_: {"qi_powered": False})
    assert blood.surcharge(engine, actor, "action:cp", ["resource:core.cp"]) is None


def test_cut_breath_surcharge_applies_only_to_qi_feature(monkeypatch):
    actor = NS(resources={"resource:core.qi": 10}, conditions={
        "surcharge": NS(condition_id=blood.STATE, data={
            "kind": "surcharge", "resource": blood.QI, "amount": 2
        })
    })
    engine = NS(action_catalog={"action:qi": NS()})
    monkeypatch.setattr("combat.activation_settlement.profile",
        lambda *_: {"qi_powered": True})
    assert blood.surcharge(engine, actor, "action:qi", []) == {blood.QI: 2}


def test_lower_or_unrelated_survival_record_does_not_override_execution():
    ctx = NS(numbers={"cl": 18})
    rows = [
        ("low", NS(source_cl=12), NS(survives=("bodily_execution",))),
        ("unrelated", NS(source_cl=20), NS(survives=())),
    ]
    from unittest.mock import patch
    with patch.object(blood, "identified_relations", return_value=rows):
        assert not blood.has_survival_authority(ctx)


def test_equal_or_higher_named_survival_authority_protects_execution(monkeypatch):
    ctx = NS(numbers={"cl": 18})
    rows = [("authority", NS(source_cl=18),
             NS(survives=("bodily_execution",)))]
    monkeypatch.setattr(blood, "identified_relations", lambda *_args, **_kwargs: rows)
    assert blood.has_survival_authority(ctx)
