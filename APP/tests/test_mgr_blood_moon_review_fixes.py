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


def test_severance_wounds_require_identified_anatomy(monkeypatch):
    ctx = NS()
    monkeypatch.setattr(blood, "identified_relations", lambda *_args, **_kwargs: [])
    assert "Severed Limb" not in blood.execution_wound_options(ctx)
    assert "Ruined Organ" not in blood.execution_wound_options(ctx)
    anatomy = [("arm", NS(), NS(ordinary_vital=False))]
    monkeypatch.setattr(blood, "identified_relations", lambda *_args, **_kwargs: anatomy)
    options = blood.execution_wound_options(ctx)
    assert "Severed Limb" in options
    assert "Ruined Organ" not in options
    anatomy.append(("heart", NS(), NS(ordinary_vital=True)))
    assert "Ruined Organ" in blood.execution_wound_options(ctx)


def test_equal_or_higher_named_survival_authority_protects_execution(monkeypatch):
    ctx = NS(numbers={"cl": 18})
    rows = [("authority", NS(source_cl=18),
             NS(survives=("bodily_execution",)))]
    monkeypatch.setattr(blood, "identified_relations", lambda *_args, **_kwargs: rows)
    assert blood.has_survival_authority(ctx)



def test_lower_cl_death_inside_threshold_skips_save(monkeypatch):
    ctx = NS(numbers={"cl": 18}, engine=NS(), target=NS())
    monkeypatch.setattr(blood, "target_cl", lambda *_: 12)
    monkeypatch.setattr(blood, "has_survival_authority", lambda *_: False)
    assert not blood.death_save_required(ctx, True)
    assert blood.death_save_required(ctx, False)


def test_equal_or_higher_survival_authority_restores_death_save(monkeypatch):
    ctx = NS(numbers={"cl": 18}, engine=NS(), target=NS())
    monkeypatch.setattr(blood, "target_cl", lambda *_: 12)
    monkeypatch.setattr(blood, "has_survival_authority", lambda *_: True)
    assert blood.death_save_required(ctx, True)


def test_execution_threshold_recognizes_other_suppressed_major_system():
    target = NS(current_hp=100, maximum_hp=100, resources={}, conditions={
        "seal": NS(condition_id="condition:other.seal",
                   source_actor_id="other", data={"suppressed": True, "major_system": True})
    })
    ctx = NS(target=target, actor=NS(entity_id="executioner"),
             engine=NS(), numbers={"cl": 18})
    # Only this plug-in's own sentence state is absent.
    assert blood.threshold(ctx)


def test_execution_wound_options_explain_effect_and_duration():
    import inspect
    source = inspect.getsource(blood.execution)
    assert "no Cultivation Point recovery until repaired" in source
    assert "cannot regain Hit Points for 1 minute" in source
    assert "no weapon-delivered cultivation techniques" in source
