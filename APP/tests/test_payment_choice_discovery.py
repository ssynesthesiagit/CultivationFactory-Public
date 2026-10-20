"""Cancellation choices stop discovery; other optional reactions keep grouping."""
from types import SimpleNamespace
import pytest
from combat.gate4_models import ExtensionChoice
from combat.reaction_menu import ReactionMenuProbe,MenuBoundary


def context(spec):
    return SimpleNamespace(checkpoint='PAYMENT',reactor_id='actor:payer',reaction_source_id='choice:payment',extension_choice=spec)


def test_canceling_payment_preserves_the_original_choice_boundary():
    spec=ExtensionChoice(option_ids=('ordinary','alternative'),decline_cancels_activation=True)
    first=context(spec)
    probe=ReactionMenuProbe(first)
    with pytest.raises(MenuBoundary):probe.answer(first)
    assert probe.contexts==[] and probe.first is first
    assert ExtensionChoice.model_validate(spec.model_dump()).decline_cancels_activation


def test_default_optional_reaction_keeps_legacy_decline_and_discovery():
    spec=ExtensionChoice(option_ids=('benefit',))
    assert 'decline_cancels_activation' not in spec.model_dump()
    first=context(spec);probe=ReactionMenuProbe(first)
    decision=probe.answer(first)
    assert decision.selection=='DECLINE' and probe.contexts==[first]


def test_mandatory_choice_remains_a_boundary_without_new_metadata():
    first=context(ExtensionChoice(option_ids=('required',),allow_decline=False))
    with pytest.raises(MenuBoundary):ReactionMenuProbe(first).answer(first)


def test_zero_coverage_is_explicit_owned_and_requires_a_real_price(monkeypatch):
    from combat import ext
    from combat.alternative_payments import PaymentAlternative,options
    from dataclasses import replace
    source='test:minimum_cost_choice';qi='resource:core.qi';price='resource:named.price'
    actor=SimpleNamespace(entity_id='owner',active=True,current_hp=20,resources={qi:1,price:0},
        passive_ids=(source,),augment_ids=(),action_ids=(),reaction_ids=())
    engine=SimpleNamespace(action_catalog={},typed_passive_rows={},typed_reaction_rows={})
    plan=PaymentAlternative(source,'Pay the minimum and the real price',((qi,0),),resolution_gains=((price,1),))
    monkeypatch.setattr(ext,'run_strict',lambda kind,*args: [plan] if kind=='payment_substitution' else [])
    with pytest.raises(ValueError,match='actual costs'):options(engine,actor,'actual:activation',((qi,1),))
    plan=replace(plan,allow_zero_coverage=True)
    assert options(engine,actor,'actual:activation',((qi,1),))==(plan,)
    actor.passive_ids=()
    assert options(engine,actor,'actual:activation',((qi,1),))==()
    actor.passive_ids=(source,)
    plan=replace(plan,resolution_gains=())
    with pytest.raises(ValueError,match='real cost'):options(engine,actor,'actual:activation',((qi,1),))
