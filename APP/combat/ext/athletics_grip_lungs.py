"""Scoped Sure Grip and Strong Lungs benefits; no inferred environmental hazards.

Catching a falling creature needs a table-defined catch/check difficulty and
reachable support, neither printed by Sure Grip. Breath clocks remain travel
text. Actual climb/fall checks and categorized combat saves receive their
printed Advantage; Sure Grip's physical holds survive Incapacitated.
"""
from . import hook
BLOCK = 'athletics_grip_lungs'
GRIP = 'TAL_ATHLETICS_SURE_GRIP'
LUNGS = 'TAL_ATHLETICS_STRONG_LUNGS'


@hook('compile_block')
def compile_benefits(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, 'block': BLOCK, 'kind': spec['kind']}]


def owns(engine, actor, kind):
    return any(r.get('block') == BLOCK and r.get('kind') == kind
               for r in engine.typed_passive_rows.get(actor.entity_id, ()))


@hook('maintain_grapples_incapacitated')
def maintain_grip(engine, actor):
    return True if owns(engine, actor, 'sure_grip') else None


@hook('climbing')
def sure_grip_climbing(engine, actor):
    """The same owned Sure Grip row supplies native roof-climbing Advantage.

    Kept here with its physical-hold and ordinary climb-check benefits so a
    later feature file cannot replace one half of the talent with the other.
    """
    return {'climb_check_modes': ['ADVANTAGE']} if owns(engine, actor, 'sure_grip') else None


@hook('ability_check_hazards')
def climb_and_fall(engine, actor, ability, skill, hazards):
    if (owns(engine, actor, 'sure_grip') and str(skill).lower() == 'athletics'
            and set(hazards) & {'climb', 'prevent_falling'}):
        return 'ADVANTAGE'


@hook('save')
def lungs_saves(ctx, subject, ability, named):
    if not owns(ctx.engine, subject, 'strong_lungs'):
        return
    categories = set(named or ())
    if 'smoke_nonbreather_advantage' in ctx.typed or categories & {'category:inhalation', 'category:suffocation'} or (
            str(ability).upper() == 'CON' and 'category:forced_march_exhaustion' in categories):
        return {'bonus': 0, 'modes': ['ADVANTAGE']}
