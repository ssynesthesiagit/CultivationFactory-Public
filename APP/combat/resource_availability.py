"""Pure represented-resource availability shared by admission and payment plans.

Consumers: native affordability and alternative payment quotes. Providers return
None/True/False through resource_quote_allowed(engine, actor, resource, amount,
source). No provider means unchanged affordability. Actual payment still invokes
the strict resource_spend_allowed checkpoint and may resolve an optional save.
"""
from . import ext


def permits(engine,actor,source,costs):
    for resource,amount in costs:
        answers=ext.run_strict('resource_quote_allowed',engine,actor,resource,amount,source)
        if any(type(value) is not bool for value in answers):
            raise ValueError('Resource availability quotes require bool or None')
        if False in answers:return False
    return True
