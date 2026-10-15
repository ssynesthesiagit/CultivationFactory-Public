"""Thread weaving riders (rider lane C11, 2026-09-30): Spool and Strand's Qi Thread, Qi Thread Scripture, Hundred-Line Weaving and
Loom of the Narrow Gate's Persistent Lines.

Source (owner text, authority/typed_mechanics/rules_text.json):
  Spool and Strand: "Cost: None for mundane thread; 1 CP to create or reinforce Qi Thread for combat use. ... If you spend 1 CP, you
    can create Qi Thread ... for 1 minute."  Draw the Line (its own lines): "Range: Mundane 20 feet, Qi Thread 30 feet. Cost: ... 1 CP
    for Qi Thread."
  Qi Thread Scripture: "When you spend 1 CP to create Qi Thread, it lasts for 10 minutes instead of 1 minute. While active, your Thread
    Lines may be Qi Threads by default instead of requiring separate CP for each line. Extra Lines: Your Thread Line limit increases by
    1."
  Hundred-Line Weaving: "Your Thread Line limit increases by 2. When you use Draw the Line, you may spend 1 additional CP to target one
    additional creature or object within range. Make a separate Thread Attack for each target. Tension Mastery: Once per round when a
    Thread Line you maintain would end at the end of your turn, you may maintain it until the end of your next turn without spending
    an action."

How it runs (feature block ``thread_weaving``, combat/rules/feature_blocks.d/riders_c11.json; Spool and Strand is every Thread user's
base ability, so its row is on every Thread fighter):
  * Qi Thread: each Draw the Line option has a "(Qi Thread)" twin -- 30 feet, +1 CP -- offered only against a creature beyond the mundane
    20 feet. With Qi Thread Scripture the first one also starts "Qi Thread" on the user for 10 minutes (100 rounds); while
    it lasts a free "(Qi Thread)" twin replaces the paid one ("Qi Threads by default").
  * Thread Line limit: +1 (Qi Thread Scripture) and +2 (Hundred-Line Weaving) through the documented ``mark_cap`` hook.
  * Two targets: each Draw the Line option has a "(two targets)" twin, +1 CP, whose Thread Attack runs once for each of up to two
    creatures the user picks within range (extra_targets). An object as the extra target is the GM's.
  * Loom of the Narrow Gate (typed: a 30-foot line of six squares within 90 feet, 1 minute, Difficult Terrain for hostile
    creatures): each of the user's active looms takes two Thread Lines off the limit ("Persistent Lines").
  * Tension Mastery: at the start of the user's turn (``turn_start_choice``), the user is asked whether to keep one Thread Line that
    will end at the end of this turn until the end of the next (a player is asked; the AI keeps the one on a hostile creature). The
    line is re-laid with the same data and a new turn stamp. Reading: the printed moment is the end of the turn; the table asks at
    its start because only turn-start choices can pause for a player (a line spent meanwhile makes the answer moot).
Default-inert for fighters without the rows. Martial Use (the ability for Thread Attacks with Qi Thread, chosen when the talent is
learned) is not on the sheet: the table's Thread Attacks use the technique attack bonus (GM).
"""

from __future__ import annotations

import json
from typing import Any

from . import effect, hook, note

BLOCK = "thread_weaving"
DRAW = "THREAD_BASE_DRAW_THE_LINE"
QI_THREAD = "condition:typed.qi_thread"
QI_SUFFIX, FREE_SUFFIX, TWO_SUFFIX = ".qi_thread", ".qi_thread_active", ".two_targets"
MUNDANE_FT, QI_FT = 20, 30
LINE = "Thread Line"
LOOM = "tianxia.talent.thread.loom_of_the_narrow_gate"


@hook("compile_block")
def compile_row(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "kind": spec.get("kind"), **({"lines": int(spec["lines"])} if spec.get("lines") else {})}]


def _kinds(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    from .. import typed_reactions

    return {str(row.get("kind")): row for row in typed_reactions._rows(engine, actor.entity_id, BLOCK)}


def _is_draw_option(action: Any) -> bool:
    typed = (action.parameters or {}).get("typed") or {}
    return typed.get("option_of") == DRAW and not typed.get("variant_of") and not (action.parameters or {}).get("thread_twin")


@hook("compile_actions")
def twins(info: dict[str, Any]) -> list[Any] | None:
    owned = set(info["owned_ids"])
    if "THREAD_BASE_SPOOL_AND_STRAND" not in owned:
        return None
    from ..factory_compiler import RESOURCE_IDS

    primary = RESOURCE_IDS.get(str(info.get("primary") or ""))  # the Path pool "CP" is paid from (qi, stamina, resonance)
    scripture = "tianxia.talent.thread.qi_thread_scripture" in owned
    hundred = "tianxia.talent.thread.hundred_line_weaving" in owned
    made = []
    for action in info["actions"]:
        if not _is_draw_option(action):
            continue
        base = json.loads(json.dumps(action.parameters))
        paid = [*action.costs, (primary, 1)] if primary else list(action.costs)

        def twin(suffix: str, name: str, costs: list[Any], extra: dict[str, Any], range_ft: int, effects: list[Any] | None = None) -> Any:
            parameters = json.loads(json.dumps(base))
            typed = parameters["typed"]
            typed["range_ft"] = range_ft
            if effects is not None:
                typed["effects"] = effects
            parameters["thread_twin"] = extra
            return action.model_copy(update={"source_definition_id": action.source_definition_id + suffix,
                                              "display_name": f"{action.display_name} ({name})", "range_ft": range_ft,
                                              "costs": tuple(costs), "parameters": parameters})

        made.append(twin(QI_SUFFIX, "Qi Thread", paid, {"qi": "paid", "scripture": scripture}, QI_FT))
        if scripture:
            made.append(twin(FREE_SUFFIX, "Qi Thread", list(action.costs), {"qi": "active"}, QI_FT))
        if hundred:
            wrapped = [{"type": "extra_targets", "count": 2, "sight": False, "requires_perception": True,
                        "automatic_recipients": "enemies", "prefer": "all_hostile",
                        "evidence": "you may spend 1 additional CP to target one additional creature or object within range. Make a separate "
                                    "Thread Attack for each target.",
                        "effects": base["typed"]["effects"]}]
            made.append(twin(TWO_SUFFIX, "two targets", paid, {"two": True}, int(action.range_ft or MUNDANE_FT), wrapped))
    return made or None


def _qi_active(actor: Any) -> bool:
    return any(c.condition_id == QI_THREAD for c in actor.conditions.values())


@hook("candidate_allowed")
def offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    extra = (getattr(action, "parameters", None) or {}).get("thread_twin")
    if not extra:
        return None
    if extra.get("two"):
        return None
    targets = [engine.state.actors.get(target_id) for target_id in getattr(candidate, "target_ids", None) or ()]
    beyond = bool(targets) and all(target is not None and engine._distance_actor_to_actor(actor, target) > MUNDANE_FT for target in targets)
    active = _qi_active(actor)
    return active if extra.get("qi") == "active" else not (active and extra.get("scripture"))


@hook("technique_used")
def start_qi_thread(ctx: Any) -> None:
    extra = (ctx.action.parameters or {}).get("thread_twin") or {}
    if extra.get("qi") != "paid":
        return
    create_strand(ctx, scripture=bool(extra.get('scripture')))


@hook("mark_cap")
def more_lines(ctx: Any, name: str) -> dict[str, int] | None:
    if str(name).lower() != LINE.lower():
        return None
    add = sum(int(row.get("lines") or 0) for row in _kinds(ctx.engine, ctx.actor).values())
    from .. import zones

    # Loom of the Narrow Gate: "Persistent Lines: The loom counts as two active Thread Lines for your limit."
    add -= 2 * sum(1 for zone in zones.typed_zones(ctx.engine) if zone.owner_id == ctx.actor.entity_id and LOOM in str(zone.source_definition_id))
    return {"add": add} if add else None


@hook("turn_start_choice")
def tension_mastery(engine: Any, actor: Any) -> None:
    if "hundred_line_weaving" not in _kinds(engine, actor):
        return
    from ..typed_executor import mark_condition_id

    cid = mark_condition_id(LINE, actor.entity_id)
    ending = [(holder, key, condition) for holder in engine.state.actors.values() if holder.active
              for key, condition in holder.conditions.items()
              if condition.condition_id == cid and condition.expires_on == "END_OF_MARKER_NEXT_TURN"
              and int((condition.data or {}).get("marker_turn") or -1) == int(actor.turns_started) - 1]
    if not ending:
        return
    from .needle import CHOICE, ask, checkpoint_id

    labels = {key: f"Keep the line on {holder.display_name}" for holder, key, _condition in ending}
    hostile = [key for holder, key, _condition in ending if holder.team_id != actor.team_id]
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "tension_mastery", actor.entity_id), actor,
                 CHOICE + "tension_mastery", list(labels), labels=labels, allow_decline=True, name="Tension Mastery",
                 preferred=(hostile or list(labels))[:1],
                 prompt="Tension Mastery (Hundred-Line Weaving): a Thread Line of yours ends at the end of this turn. Keep one until "
                        "the end of your next turn (no action; once per round)?")
    if not picked:
        return
    holder, key, condition = next(row for row in ending if row[1] == picked[0])
    from .condition_ownership import remove_instance

    data = {**(condition.data or {}), "marker_turn": int(actor.turns_started)}
    remove_instance(engine, holder, key, "tianxia.talent.thread.hundred_line_weaving")
    engine._apply_condition(holder, cid, str(condition.source_definition_id), actor.entity_id, expires_on="END_OF_MARKER_NEXT_TURN", data=data)
    note(engine, "tianxia.talent.thread.hundred_line_weaving", actor,
         f"Tension Mastery: {actor.display_name} keeps the Thread Line on {holder.display_name} until the end of their next turn.", (holder,))

# Base strand creation is a Special Trigger with no separate Action. A Thread
# talent can also pay its own printed Qi-thread price through the existing twins.
ORIGINS = ('fingertips', 'breath', 'weapon', 'sleeve', 'hair', 'blood', 'dantian pressure')


@hook('compile_actions')
def base_strands(info):
    if 'THREAD_BASE_SPOOL_AND_STRAND' not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from ..factory_compiler import RESOURCE_IDS
    pool = RESOURCE_IDS.get(str(info.get('primary') or ''))
    if not pool:
        return None
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.spool.qi.{index}",
        owner_id=info['actor_id'], display_name=f'Spool and Strand: Qi Thread from {origin}',
        economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF', costs=((pool, 1),),
        parameters={'expected_damage': 0, 'typed': {'source': 'THREAD_BASE_SPOOL_AND_STRAND',
            'numbers': dict(info['numbers']), 'effects': [{'type': 'thread_create_strand', 'origin': origin,
                'scripture': int('tianxia.talent.thread.qi_thread_scripture' in info['owned_ids'])}], 'riders': []},
            'description': f'Create or reinforce Qi Thread from your {origin} for one minute, spending 1 Cultivation Point as part of handling Thread. This creates a strand; it does not restrain, damage or lay a trap.'})
        for index, origin in enumerate(ORIGINS)]


def create_strand(ctx, *, scripture=False, origin='Thread technique'):
    from .effect_durations import round_token
    from .condition_ownership import refresh_owned
    refresh_owned(ctx.engine, ctx.actor, QI_THREAD, ctx.actor.entity_id, ctx.source)
    rounds = 100 if scripture else 10
    ctx.engine._apply_condition(ctx.actor, QI_THREAD, ctx.source, ctx.actor.entity_id,
        expires_on=round_token(ctx.engine, rounds), data={'label': 'Qi Thread', 'origin': origin,
        'reading': f'Qi Thread lasts {10 if scripture else 1} minute(s); it enables your Thread talents. No restraint, damage or trap is created.'})
    note(ctx.engine, ctx.source, ctx.actor, f'{ctx.actor.display_name} creates or reinforces Qi Thread from {origin} for {10 if scripture else 1} minute(s).')


@effect('thread_create_strand', harmful=False)
def base_strand_effect(ctx, row):
    if row.get('origin') not in ORIGINS:
        raise ValueError('Choose a printed Qi Thread origin.')
    create_strand(ctx, scripture=bool(row.get('scripture')), origin=row['origin'])
