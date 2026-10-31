"""Shared harmful-condition vocabulary for Karma imprint and consequence plug-ins.

Record the Deed (karma_imprints) and Trial/Ten Thousand Debts (karma_riders)
recognize the same observable combat causes. Narrative causes are not inferred.
"""

HARMFUL_CONDITIONS = frozenset({
    "blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated",
    "paralyzed", "petrified", "poisoned", "prone", "restrained", "stunned",
    "pinned", "sickened", "silenced", "burning", "bleeding",
})


def harmful_condition(condition_id: str, data: dict | None = None) -> bool:
    """Mechanical harm for Karma consequences and Record the Deed.

    Read negative mechanics and explicit harmful declarations from the same
    owner-editable condition rules as combat. Presentation-only pill colours
    and enemy provenance do not make an unknown condition harmful. Benefits,
    defenses and structural records are excluded; callers exclude self-costs.
    The legacy vocabulary retains conditions implemented entirely by plug-ins.
    """
    from ..condition_tone import hurts
    from ..typed_executor import rules

    declared = rules().get('conditions', {})
    own_rule = (data or {}).get('rule') or {}

    def classified(name: str, seen: frozenset[str], extra: dict | None = None) -> bool:
        rule = {**(declared.get(name) or {}), **(extra or {})}
        rule.pop('pill_tone', None)  # presentation metadata is not combat evidence
        kind = rule.get('effect_kind')
        if kind in {'benefit', 'defense', 'structural'}:
            return False
        if name in HARMFUL_CONDITIONS or kind == 'harmful' or hurts(rule):
            return True
        return any(classified(str(other), seen | {str(other)})
                   for other in rule.get('companions', []) if str(other) not in seen)

    name = str(condition_id or '').rsplit('.', 1)[-1]
    return classified(name, frozenset({name}), own_rule if isinstance(own_rule, dict) else None)


def inflicted_harm(engine, payload: dict, target_id: str) -> bool:
    """Classify the actual landed instance for both Karma event consumers."""
    target = engine.state.actors.get(target_id)
    instance = target.conditions.get(str(payload.get('instance_id') or '')) if target is not None else None
    return harmful_condition(str(payload.get('condition_id') or ''), instance.data if instance is not None else None)
