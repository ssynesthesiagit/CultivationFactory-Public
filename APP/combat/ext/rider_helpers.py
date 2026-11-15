"""Public rider helpers shared by alchemy_riders, rider_step and second_attack.

Shared effect traversal, printed-source identity and cell choice transport.
Alchemy riders use printed_source for generated zone triggers; rider_step uses
the existing cell:x,y transport. Neither needs another plug-in's private state.
"""
from typing import Any


def printed_source(ctx: Any) -> str:
    """Resolve a generated trigger through its originating action's typed data.

    Zone trigger IDs append a suffix to the compiled action ID. Preserve explicit
    printed sources (including contextual replacements), and normalize variants
    only after following that provenance, without parsing an ability name.
    """
    source = str(ctx.typed.get('option_of') or ctx.typed.get('source') or ctx.source)
    if source.startswith(ctx.action.source_definition_id + ':'):
        typed = (ctx.action.parameters or {}).get('typed') or {}
        source = str(typed.get('option_of') or typed.get('source') or ctx.action.source_definition_id)
    return source.split('#', 1)[0]


def effect_rows(rows: Any):
    """Yield original row objects through attack, save and nested effect branches."""
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        yield row
        for branch in ('on_hit', 'on_miss', 'on_fail', 'on_success', 'effects'):
            yield from effect_rows(row.get(branch))


def cell_choice_id(position: Any) -> str:
    """Encode an existing legal candidate's cell for bounded choice transport."""
    return f'cell:{position.x},{position.y}'
