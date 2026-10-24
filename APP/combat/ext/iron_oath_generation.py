"""Shared helper module: combat/ext/foundation_combat.py uses conscious_for_guarding_iron.

Guarding Iron eligibility used by foundation_combat's existing damage producer.

Shared public helper: consumed by foundation_combat.py. Its exported functions are
the stable cross-plugin API; private helpers stay private.

Keep the existing resource clock and post-damage ordering in pressure. Positive
HP alone does not establish consciousness: Sleeping Curse, for example, leaves
its victim alive and active. These are native unconscious/sleep conditions, not
a guess from the more general no-actions rule (a stunned creature is conscious).
This helper does not adjudicate whether a declared duty is meaningful or being
defended; that missing scene authority must not be inferred from consciousness.
"""


def conscious_for_guarding_iron(engine, owner):
    """Read active native conditions; suppressed conditions confer no restriction."""
    from ..typed_executor import condition_rule_instances, rules

    table = rules()
    aliases = table.get('condition_aliases') or {}
    id_aliases = table.get('condition_id_aliases') or {}
    for condition, _rule in condition_rule_instances(owner, engine=engine):
        name = id_aliases.get(condition.condition_id,
                              condition.condition_id.removeprefix('condition:typed.'))
        name = aliases.get(name, name)
        if name in {'unconscious', 'dream_sleep', 'cursed_sleep', 'nightmare_sleep'}:
            return False
    return True
