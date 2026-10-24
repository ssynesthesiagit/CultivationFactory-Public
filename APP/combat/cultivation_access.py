"""Cycle of Rebirth's public cultivation access facade, sharing cap admission.

Consumers use the published facade or activation_requirements.effective_cl;
both read the same explicit active restriction inputs. This creates no producer
or condition schema. The source-authorized producers own costs and durations.
"""


def effective_cl(engine, actor, compiled_cl):
    from .ext.activation_requirements import effective_cl as admitted_cl
    return admitted_cl(actor, compiled_cl, engine=engine)


def alignment_available(engine, actor, element):
    from .typed_executor import condition_rules
    return not any(row.get('suppressed_element') == element
                   for row in condition_rules(actor, engine=engine))
