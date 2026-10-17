"""Explicit effective-CL and element suppression shared by cultivation consumers.

Only active condition rules carry caps/suppression. Their authorizing effects own
saves, source contests and durations; a numeric advantage never invents a seal.
"""
from .typed_executor import condition_rules


def effective_cl(engine, actor, compiled_cl):
    from .ext.activation_requirements import effective_cl as available_cl
    return available_cl(actor,compiled_cl,engine=engine)


def alignment_available(engine, actor, element):
    return not any(r.get("suppressed_element") == element for r in condition_rules(actor, engine=engine))
