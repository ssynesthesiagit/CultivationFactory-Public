"""Explicit effective-CL and element suppression shared by cultivation consumers.

Only active condition rules carry caps/suppression. Their authorizing effects own
saves, source contests and durations; a numeric advantage never invents a seal.
"""
from .typed_executor import condition_rules


def effective_cl(engine, actor, compiled_cl):
    caps = [r["cultivation_cl_cap"] for r in condition_rules(actor, engine=engine)
            if type(r.get("cultivation_cl_cap")) is int]
    return min([int(compiled_cl), *caps])


def alignment_available(engine, actor, element):
    return not any(r.get("suppressed_element") == element for r in condition_rules(actor, engine=engine))
