"""Player-facing resource labels shared by engine notices and payment errors."""


def exhausted_uses_reason() -> str:
    """Compiled per-fight counter explanation for native and Table fallback errors."""
    return ("No uses of this ability remain in this fight; a new fight starts with fresh uses "
            "unless your character starts it with this ability already used up")


def resource_name(resource_id: str) -> str:
    known = {'resource:core.cp': 'Cultivation Points (CP)', 'resource:core.qi': 'Qi',
             'resource:core.stamina': 'Stamina', 'resource:core.resonance': 'Resonance',
             'resource:core.martial_focus': 'Martial Focus'}
    if resource_id in known:
        return known[resource_id]
    if resource_id.startswith('resource:uses.'):
        return 'uses of this ability'
    if resource_id.rsplit('.', 1)[-1] == 'cp':
        return 'Cultivation Points (CP)'
    label = resource_id.rsplit(':', 1)[-1].rsplit('.', 1)[-1]
    return label.replace('_', ' ').replace('-', ' ').strip().title() or 'this resource'
