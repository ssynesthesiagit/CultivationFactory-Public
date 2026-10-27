"""Read-only table movement cards, using the engine's public diagnostics.

Used by TabletopService; candidate destinations remain the sole permission to
move. Cards are transient presentation data, never saved in a fight.
"""
from .gate2_runtime_models import Position
from .read_queries import pure


def reading(explanation, names):
    """Keep stable reason codes, but present names and ordinary player words."""
    reasons = []
    for reason in explanation['reasons']:
        message = reason['message']
        if reason['code'] == 'FRIGHTENED_CLOSER':
            name = names.get(reason.get('source_actor_id'), 'that creature')
            message = f"You are Frightened of {name}: you can't move closer to them while you can see them."
        elif reason['code'] == 'DIFFICULT_TERRAIN':
            message = message.replace('Difficult terrain:', 'Difficult terrain slows you here:')
        # The board already has terrain geometry. Repeating every terrain cell
        # inside every destination card would make this response quadratic.
        reasons.append({**{k: v for k, v in reason.items() if k != 'cells'}, 'message': message})
    # Speed-zero conditions already explain why; avoid a second copy of the same fact.
    if any(r['code'] in {'GRAPPLED', 'RESTRAINED', 'SPEED_ZERO_EFFECT'} for r in reasons):
        reasons = [r for r in reasons if r['code'] != 'SPEED_ZERO']
    return {**explanation, 'reasons': reasons}


@pure
def for_menu(engine, menu, names):
    """Summary plus destination cards for the active manual fighter only.

    Query destination-dependent reasons only when the summary has any. Normal
    turns need one diagnostic query, not one per square. No state/cache survives
    this table answer; changes of turn, sight or terrain cannot leave stale cards.
    The existing pure-query frame shares unchanged zone and perception geometry
    across the board's destination diagnostics. It ends before any table commit
    and never caches destination-specific explanations or movement permission.
    """
    if engine is None or not menu or not menu.get('manual'):
        return None
    actor_id = menu['actor_id']
    summary = reading(engine.movement_explanation(actor_id), names)
    directional = any(r['code'] in {'FRIGHTENED_CLOSER', 'DIFFICULT_TERRAIN'} for r in summary['reasons'])
    legal = {(m['destination']['x'], m['destination']['y']) for m in menu['moves']}
    legal.update((row[0], row[1]) for row in menu.get('movement_grid', ()))
    cells = {}
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            allowed = (x, y) in legal
            explanation = engine.movement_explanation(actor_id, Position(x=x, y=y)) if directional else summary
            # A nonblocking fear restriction belongs on the token, not a square
            # moving away from the source. Terrain costs apply on legal squares too.
            reasons = [r for r in explanation['reasons']
                       if r['code'] != 'FRIGHTENED_CLOSER' or r['blocks_destination']]
            if allowed:
                reasons = [r for r in reasons if r['code'] in {'DIFFICULT_TERRAIN', 'CRAWLING'}]
            if not allowed or reasons:
                card = reading({**explanation, 'reasons': reasons}, names)
                cells[f'{x},{y}'] = {'reasons': card['reasons'],
                                    'explained_refusal': card['explained_refusal'], 'available': allowed}
    return {'summary': summary, 'destinations': cells}
