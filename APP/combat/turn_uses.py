"""Typed per-turn usage clocks shared by native turns and typed consumers.

Only explicitly per-turn namespaces participate. Ordinary owner-turn flags,
round counters and untyped historical modifier gates retain their clocks.
"""

PER_TURN_PREFIXES = ("typed_once_turn:", "once_per_turn:", "creature_kind_once:")


def current_turn_key(engine):
    """Stable scalar identity for the currently active creature turn."""
    state = engine.state
    return f"{state.round_number}:{state.current_slot_index}:{state.current_actor_id}"


def modifier_period(mechanic, modifier):
    """Preserve the printed owner-turn qualification, independent of ability ID."""
    import re
    if modifier.get('limit') != 'once_per_turn':
        return None  # old round/unspecified modifier records keep their existing gate
    trigger = str((mechanic.get('activation') or {}).get('trigger') or '').lower()
    return 'owner_turn' if re.search(r'\b(?:each of your turns|your turn|your own turn)\b', trigger) else 'turn'


def usage_explanations(typed, names=None, action_name='This action'):
    """Shared player-facing refresh wording for Table and sheet action descriptions."""
    rows = set()
    names = names or {}
    def visit(node, nested=False):
        if isinstance(node, list):
            for child in node:visit(child, nested)
        elif isinstance(node, dict):
            label = node.get('source_modifier_name') or names.get(node.get('source_modifier')) or node.get('name')
            if not label:
                kinds = node.get('damage_types') or []
                label = ' and '.join(str(k).replace('_',' ').title() for k in kinds) + ' damage' if kinds else 'This effect'
            label = label + ' bonus' if nested else action_name
            period = 'turn' if node.get('once_per_turn') else node.get('modifier_once_period') or node.get('once')
            if period in ('turn','owner_turn','round'):rows.add((label,period,nested))
            for key in ('effects','on_hit','on_miss','on_fail','on_success'):visit(node.get(key), True)
    visit(typed)
    wording = {'turn': "Once per turn: available again at the start of the next creature's turn.",
               'owner_turn': "Once on your turn only: available again at the start of your next turn.",
               'round': "Once per round: available again at the start of the next round."}
    text = ' '.join(f'{label}: {wording[period]}' for label,period,_ in sorted(rows))
    if rows and all(nested for _,_,nested in rows):
        text += ' The underlying action keeps its normal action and reaction rules.'
    return text


def reset_at_turn_start(engine):
    """Reset all creatures' typed per-turn uses, recording each changed key set.

Called before start-of-turn expiry/triggers, including skipped creature turns.
No matching flags means no event and no change. Keys are sorted for replay.
The historical once_per_turn:_round_ namespace belongs to the round clock;
retain it for old saves as well as current Initiative checkpoints.
"""
    for actor_id, actor in sorted(engine.state.actors.items()):
        keys = sorted(key for key in actor.turn_flags if key.startswith(PER_TURN_PREFIXES)
                      and not key.startswith('once_per_turn:_round_'))
        if not keys:
            continue
        for key in keys:
            del actor.turn_flags[key]
        engine._append_event("PER_TURN_USES_RESET", "system:combat.turn", actor_id=actor_id,
                             payload={"keys": keys, "turn_actor_id": engine.state.current_actor_id})
