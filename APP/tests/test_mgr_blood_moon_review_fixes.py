"""Regressions for the Blood-Moon review findings; all fixtures are synthetic."""
from types import SimpleNamespace as NS

import pytest

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


def test_execution_threshold_recognizes_other_suppressed_major_system(monkeypatch):
    target = NS(current_hp=100, maximum_hp=100, resources={}, conditions={
        "seal": NS(condition_id="condition:other.seal",
                   source_actor_id="other", data={"suppressed": True, "major_system": True})
    })
    ctx = NS(target=target, actor=NS(entity_id="executioner"),
             engine=NS(), numbers={"cl": 18})
    # The threshold needs three Blood-Moon marks on the target; the suppressed other system is the condition under test.
    monkeypatch.setattr(blood, "marks", lambda *_: [1, 2, 3])
    assert blood.threshold(ctx)


def test_execution_wound_options_explain_effect_and_duration():
    import inspect
    source = inspect.getsource(blood.execution)
    assert "no Cultivation Point recovery until repaired" in source
    assert "cannot regain Hit Points for 1 minute" in source
    assert "no weapon-delivered cultivation techniques" in source


@pytest.mark.parametrize('witnessed', [False, True])
def test_mark_reading_uses_only_records_the_actor_witnessed(monkeypatch, witnessed):
    # A regeneration record the acting player never witnessed must not change the
    # Blood-Moon Mark reading; a witnessed one must still be reported.
    from combat.table_facts import TableFact, FactAnswer, RelationshipFact
    relation = RelationshipFact(key='regen', kind='regeneration', name='Regeneration',
                                source_reference='campaign:synthetic-regeneration')
    fact = TableFact(record_id='r1', subject_id='foe', subject_name='Foe', subject_kind='creature',
                     position={'x': 1, 'y': 1}, source_reference='campaign:synthetic-scene',
                     witness_ids=('hero',) if witnessed else ('bystander',), valid_through_round=5,
                     answers={'regen': FactAnswer(fact='Foe regenerates.', category='regeneration',
                                                  visible_sign='Wounds close.', source_cl=5,
                                                  relationship=relation)})
    actor = NS(entity_id='hero', resources={blood.QI: 3}, turn_flags={}, conditions={},
               current_hp=10, maximum_hp=10)
    target = NS(entity_id='foe', display_name='Foe', current_hp=10, maximum_hp=10, conditions={})
    engine = NS(events=[NS(event_type='TABLE_FACT_RECORDED', payload={'fact': fact.model_dump(mode='json')})],
                state=NS(round_number=1, actors={}), action_catalog={},
                _spend_resource=lambda *a, **k: None, _apply_condition=lambda *a, **k: None)
    ctx = NS(engine=engine, actor=actor, target=target, numbers={'cl': 18, 'pb': 2},
             action=NS(display_name='Test strike'), source=None, intent=None)
    published = {}
    monkeypatch.setattr(blood, 'saber_context', lambda c, t: c)
    monkeypatch.setattr(blood, 'used', lambda *a: False)
    monkeypatch.setattr(blood, 'spend', lambda *a: None)
    monkeypatch.setattr(blood, 'pick', lambda *a, **k: ['Apply Blood-Moon Mark'])
    monkeypatch.setattr(blood, 'publish', lambda c, details: published.update(details))
    blood.mark_on_confirmed_hit(ctx, target, ())
    assert published['regeneration'] == (1 if witnessed else 'unknown')
