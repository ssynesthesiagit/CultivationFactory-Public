"""Radiance sphere's Dawnmark loop (owner 2026-09-28: "make sure all the talents and class abilities and
foundations and methods and everything is applied"; w4-radiance, Wen Xue).

Radiance Strike, Judgment Ray and Dawn-Cleansing Wave place a real "Dawnmark" (combat/typed_executor.py's
block_mark/bears_mark, condition id "condition:typed.mark.dawnmark.<owner>") on their target when the printed
text says "apply your Dawnmark"/"become Dawnmarked" (see authority/typed_mechanics/reviewed_final.d/wenxue.json).
Everything else in the sphere that reads the mark needs no plug-in code at all:
  - Dawnlit Rebuke's reaction trigger ("When a creature bearing your Dawnmark damages one of your allies...") is
    parsed straight from the printed trigger text by combat/reaction_triggers.py's _requires_mark, so the generic
    reaction machinery only offers it when the damaging creature currently bears the mark.
  - Daybreak Seal's modifier wraps its save in an if_marked("Dawnmark") gate (typed_executor.block_if_marked) so
    paying the 2 CP only does anything against a marked target.
  - Mirror of Clean Dawn (an unrelated existing "checked" record) is left alone.
This module also supplies complete plain Daybreak Seal text for the shared
paid_hit.effect_text presentation helper, including its nested save outcomes.

Dawnmark Scripture (CL5+, Realm Evolution) is the one feature that changes how the mark itself behaves rather
than reading it once, so it needs real hook code:
  - "Your Dawnmark lasts until the end of your next turn" (replacing the "momentary gleam" of a bare Dawnmark,
    which expires at the START of the marker's next turn): after any of this character's own typed actions
    finishes running its effects (technique_used -- by then Radiance Strike/Judgment Ray/Dawn-Cleansing Wave's own
    on_hit/on_fail/on_success "mark" effect has already placed it), re-apply any of her own Dawnmarks still
    sitting at the shorter expiry with the longer one, rather than special-casing each of the three abilities.
  - "When a creature bearing your Dawnmark starts its turn, you may choose to make the mark flare; if you do, the
    creature cannot take Reactions until the start of its next turn": a transactional turn_start_choice asks
    the mark's manual owner; AI owners prefer flaring. The expiry names the bearer's next turn exactly.
Not automated here (left as a GM-only rider on Dawnmark Scripture's own reviewed_final entry): shedding Bright/Dim
light (no combat mechanic). The target_sight_bypass hook permits Mark talents
against the owner's Dawnmark within 60 feet, with known direction and an open
route; it changes neither ordinary sight nor other actions' targeting.
"Once per turn when you damage an Unclean creature bearing your Dawnmark, add 1d8 Radiant damage" is implemented
once in radiance_unclean.py, on the actual committed damage event. That covers native and typed damage, including
weapon attacks and save-based techniques, with no second potency application or critical doubling of the bonus die.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .radiance_unclean import SCRIPTURE_TURN_FLAG
from ..typed_executor import CONDITION_PREFIX, mark_condition_id


@hook("effect_player_text")
def seal_player_text(row: dict[str, Any]) -> str | None:
    """Describe Dawnmark's healing seal subtree without its implementation note."""
    children = row.get("effects") or []
    if (row.get("type") != "if_marked" or row.get("mark") != "Dawnmark"
            or len(children) != 1 or children[0].get("type") != "save"
            or children[0].get("ability") != "con"
            or tuple(str(kind).casefold() for kind in children[0].get("disadvantage_if_kind") or []) != ("unclean",)
            or {e.get("type") for e in children[0].get("on_fail") or []}
               != {"deny_temp_hp", "healing_reduction"}
            or {e.get("type") for e in children[0].get("on_success") or []} != {"deny_temp_hp"}):
        return None
    return ("When you damage a creature bearing your Dawnmark (your Radiance mark on that creature), "
            "you may pay 2 CP. The target makes a Constitution saving throw. "
            "Failed save: until the start of your next turn, the target cannot regain hit points "
            "or gain Temporary HP. Successful save: the target cannot gain Temporary HP until "
            "the start of your next turn. An Unclean target has Disadvantage on this saving throw; "
            "Unclean includes undead, demons, fiends, corrupted spirits, possession entities, "
            "and creatures the GM classifies as unclean.")

SCRIPTURE_BLOCK = "radiance_dawnmark_scripture"
MARK_NAME = "Dawnmark"
# "once per turn" needs the *current* turn's identity, not a flag cleared at the owner's turn start: the printed
# bonus is available on any turn the owner damages the target, including another creature's turn. gate2_engine's
# turn start keeps "_round_" keys and drops the rest, and this flag's value is the "round:whose turn" stamp
# (the same shape bloodless_devouring uses), so a new turn -- whosever's -- reads as unspent while a second hit in
# the same turn still finds its own stamp. A string, so it survives a table commit and reload.


def _has_scripture(engine: Any, actor_id: str) -> bool:
    from ..typed_reactions import _rows

    return bool(_rows(engine, actor_id, SCRIPTURE_BLOCK))


@hook('target_sight_bypass')
def scripture_target_sight(engine: Any, actor: Any, target: Any, action: Any) -> bool | None:
    """Only owned Mark talents, own Dawnmark, known direction and an open route."""
    from .ability_source import mechanic_of
    from ..factory_compiler import _talent_tags
    from ..typed_executor import bears_mark
    from ..target_knowledge import located

    if not _has_scripture(engine, actor.entity_id):
        return None
    if 'Mark' not in _talent_tags(mechanic_of(action)):
        return None
    if not bears_mark(target, actor.entity_id, MARK_NAME):
        return None
    if engine._distance_actor_to_actor(actor, target) > 60:
        return None
    observed = engine.state.observations.get(actor.team_id, {}).get(target.entity_id)
    if not (located(engine, actor, target) or observed == target.position):
        return None
    # A stale square is not current direction knowledge. Do not follow a hidden
    # creature's later movement merely because it still bears the mark.
    # Ordinary map admission still enforces range and the legal route. Do not
    # advertise this exception if that route is blocked by cover or a barrier.
    return True if engine.grid.line_of_sight_between_cell_sets(
        engine._actor_cells(actor), engine._actor_cells(target), obscured_cells=set()) else None


@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block == SCRIPTURE_BLOCK:
        # No keeps_compiling: every mechanical benefit of this talent is handled by the hooks in this module
        # (the mark's duration, the flare and the 1d8 Unclean bonus), so the feature is filed as automated and the
        # record itself carries only the two GM riders. 'choice_owner': the flare is a choice of this character.
        return [{**row, 'choice_owner': True}]  # expose this owner's choice on manual and AI turn transitions
    return None


@hook("technique_used")
def _extend_dawnmark(ctx: Any) -> None:
    owner = ctx.actor.entity_id
    if not _has_scripture(ctx.engine, owner):
        return
    condition_id = mark_condition_id(MARK_NAME, owner)
    for actor in ctx.engine.state.actors.values():
        condition = next((c for c in actor.conditions.values() if c.condition_id == condition_id), None)
        if condition is None or condition.expires_on != "START_OF_MARKER_NEXT_TURN":
            continue  # not this character's Dawnmark, or already at the longer Scripture duration
        data = dict(condition.data or {})
        ctx.engine._remove_condition(actor, condition_id, ctx.source)
        ctx.engine._apply_condition(actor, condition_id, ctx.source, owner, expires_on="END_OF_MARKER_NEXT_TURN", data=data)


@hook("mark_duration")
def scripture_mark_duration(ctx: Any, name: str, duration_kind: str) -> str | None:
    """Choose Scripture's printed deadline when its owner places a Dawnmark."""
    if name == MARK_NAME and _has_scripture(ctx.engine, ctx.actor.entity_id):
        return "until_end_of_your_next_turn"
    return None


@hook("turn_start_choice")
def _flare(engine: Any, actor: Any) -> None:
    from .needle import ask, checkpoint_id
    from .effect_durations import token

    for condition in list(actor.conditions.values()):
        if not condition.condition_id.startswith(CONDITION_PREFIX + "mark.dawnmark."):
            continue
        owner_id = condition.source_actor_id
        if owner_id == actor.entity_id or not _has_scripture(engine, owner_id):
            continue
        owner = engine.state.actors.get(owner_id)
        if owner is None or not owner.active:
            continue
        picked = ask(engine, None, checkpoint_id(engine, 'dawnmark_flare', condition.instance_id), owner,
                     'choice:needle.dawnmark_flare', ['flare'], allow_decline=True,
                     name='Dawnmark Scripture', feature_id='tianxia.talent.radiance.dawnmark_scripture',
                     target_id=actor.entity_id, labels={'flare': f'Flare: {actor.display_name} cannot take Reactions until its next turn starts (no cost)'},
                     prompt=f'Dawnmark Scripture: {actor.display_name} starts its turn bearing your Dawnmark. Flare it at no cost to prevent its Reactions until the start of its next turn?')
        if not picked:
            continue
        engine._apply_condition(actor, CONDITION_PREFIX + "reaction_denied", f"talent:{SCRIPTURE_BLOCK}", owner_id,
                                expires_on=token('start', actor.entity_id, actor.turns_started + 1),
                                data={'label': 'Dawnmark Scripture: no Reactions until your next turn starts'})
