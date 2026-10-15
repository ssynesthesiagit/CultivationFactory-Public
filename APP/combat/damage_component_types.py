"""Post-roll type decisions shared by native and typed damage components.

The source owner may replace exactly one positive component's damage type using
an existing accepted intent. No provider means no choice, event, payment or type
change. Dice, hit outcomes, targets and damage amounts are never replaced here.
Living Mercury Body and Express Pattern are distinct printed consumers.
"""
from . import ext


def resolve(engine,actor,target_ids,source,amount,kind,*,ctx=None,spec=None,intent=None,attack_index=0):
    if amount<=0:return kind
    if ctx is None and spec is not None:ctx=spec.get("typed_context")
    answers=ext.run_strict('damage_component_type',engine,actor,tuple(target_ids),source,int(amount),str(kind),
        ctx=ctx,spec=spec,intent=intent,attack_index=attack_index)
    if not answers:return kind
    if len(answers)!=1 or type(answers[0]) is not str or not answers[0].strip():
        raise ValueError('Exactly one source may replace a resolved damage component type.')
    return answers[0].upper()
