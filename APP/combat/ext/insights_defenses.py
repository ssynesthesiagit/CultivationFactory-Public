"""Printed defensive Insights, sealed by reviewed path_passive ownership.

Queries consume only retained rows. Bell-Skin listens to the real Stamina Guard
receipt; unrelated zero-damage reactions cannot grant its AC or resource reward.
Body Like Water reuses the common escape resolvers and their check/DC semantics.
"""
from . import effect, hook

SKIN = "insight.bell-skin-discipline"
WATER = "insight.body-like-water"
BELL = "insight.bell-bone-adept"  # Implemented by Sound's existing typed modifier.
GUARD = "tianxia.path.body_refining.feature.stamina_guard"
AC = "condition:typed.bell_skin_discipline"
STAMINA = "resource:core.stamina"
FOCUS = "resource:core.martial_focus"


def owned(engine, actor, feature):
    return next((r for r in engine.typed_passive_rows.get(actor.entity_id, ())
                 if r.get("block") == "path_rider" and r.get("kind") == "insight_defense"
                 and r.get("feature_id") == feature), None)


@hook("event")
def guard_reward(engine, event_type, kwargs):
    if event_type != "REACTION_RESOLVED" or kwargs.get("source_definition_id") != GUARD:
        return
    payload = kwargs.get("payload") or {}
    if payload.get("pending_after") != 0 or int(payload.get("pending_before") or 0) <= 0 or not payload.get("spend"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id"))
    if actor is None or not owned(engine, actor, SKIN):
        return
    engine._remove_condition(actor, AC, SKIN)
    engine._apply_condition(actor, AC, SKIN, actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": "Bell-Skin Discipline: +1 AC until the start of your next turn"})
    flag = "insights_bell_skin_round_used"
    if actor.turn_flags.get(flag) != engine.state.round_number:
        actor.turn_flags[flag] = engine.state.round_number
        if STAMINA in actor.resources:
            engine._gain_resource(actor, STAMINA, 1, SKIN)


@hook("ac")
def skin_ac(engine, actor):
    return 1 if any(c.condition_id == AC for c in actor.conditions.values()) else None


@hook("compile_actions")
def water_action(info):
    if WATER not in info["owned_ids"]:
        return []
    mech = info["mechanics"].get(WATER) or {}
    if not any(r.get("type") == "path_passive" and r.get("kind") == "insight_defense" for r in mech.get("effects", [])):
        return []
    from ..gate2_runtime_models import ActionDefinition
    stats = info["owner_sheet"].get("ability_scores_and_statistics") or {}
    skills = {r.get("skill"): int(r.get("bonus") or 0) for r in stats.get("skills", []) if isinstance(r, dict)}
    bonus = max(skills.get("Athletics", info["mods"].get("STR", 0)), skills.get("Acrobatics", info["mods"].get("DEX", 0)))
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.body_like_water",
        display_name="Body Like Water: escape", owner_id=info["actor_id"], economy="BONUS_ACTION",
        resolution_kind="TYPED", target_kind="SELF", parameters={"insight_water_escape": True,
        "description": "Use a Bonus Action to attempt to escape a Grapple or Restraint. On success, regain Martial Focus if absent.",
        "typed": {"source": WATER, "effects": [{"type": "insight_water_escape"}],
                  "numbers": {**info["numbers"], "escape_bonus": bonus}, "riders": [], "duration": {"kind": "instant"}}})]


def holds(actor):
    return [c for c in actor.conditions.values() if c.condition_id in
            ("condition:typed.grappled", "condition:core.grappled", "condition:typed.pinned",
             "condition:core.pinned", "condition:typed.restrained", "condition:core.restrained")]


_ABILITY_NAME = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution",
                "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}


@hook("candidate_allowed")
def water_allowed(engine, actor, candidate, action):
    if (getattr(action, "parameters", None) or {}).get("insight_water_escape"):
        return bool(holds(actor))
    return None


@effect("insight_water_escape")
def water_escape(ctx, row):
    from . import escape_options as eo
    from .needle import ask, checkpoint_id
    from .escape_checks import resolve_escape_check, resolve_escape_save
    from .condition_ownership import remove_instance
    from .hold_escapes import escaped
    available = holds(ctx.actor)
    if not available:
        return
    from .hold_escapes import escape_stage
    stage = escape_stage([(c.instance_id, c) for c in available])
    options = {iid: condition for iid, condition in stage}
    escape_records = {}
    for record_key, record_condition in eo.options(ctx.actor):
        for guarded in (record_condition.data or {}).get("guards") or []:
            escape_records[guarded] = (record_key, record_condition)
    labels = {}
    procedures = {}
    for key, condition in options.items():
        data = condition.data or {}
        source_action = ctx.engine.action_catalog.get(condition.source_definition_id)
        source_name = (getattr(source_action, "display_name", "") or
                       str(condition.source_definition_id or "Unknown source").rsplit(".", 1)[-1].replace("_", " ").replace("-", " ").title())
        source_actor = ctx.engine.state.actors.get(condition.source_actor_id)
        source_creature = source_actor.display_name if source_actor else "an unknown creature"
        escape_record = escape_records.get(key)
        rule = data.get("action_escape") or {}
        if escape_record:
            record_data = escape_record[1].data or {}
            dc = int(record_data.get("dc") or 10)
            procedure = eo.attempt_description(record_data, "Bonus Action")
        else:
            dc = int(rule.get("dc") or data.get("escape_dc") or data.get("save_dc") or 10)
            if rule:
                ability = str(rule.get("ability") or "STR").upper()
                procedure = f"a {_ABILITY_NAME.get(ability, ability)} ability check against DC {dc}"
            elif data.get("escape_save"):
                ability = str(data["escape_save"]).upper()
                procedure = f"a {_ABILITY_NAME.get(ability, ability)} saving throw against DC {dc}"
            else:
                procedure = f"a Strength (Athletics) or Dexterity (Acrobatics) check against DC {dc}"
        if rule:
            ability = str(rule.get("ability") or "STR").upper()
        elif data.get("escape_save") and not escape_record:
            ability = str(data["escape_save"]).upper()
        condition_name = data.get("label") or condition.condition_id.rsplit(".", 1)[-1].replace("_", " ").title()
        labels[key] = f"{condition_name} from {source_name}, used by {source_creature} — {procedure}"
        procedures[key] = (rule, dc)
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "body_like_water", ctx.actor.entity_id),
                 ctx.actor, "choice:needle.body_like_water", list(options), allow_decline=False,
                 labels=labels,
                 name="Body Like Water", feature_id=WATER,
                 prompt=f"Body Like Water: {ctx.actor.display_name}, choose which current hold to escape with your Bonus Action. Each choice names its source and escape roll. Success restores missing Martial Focus.")
    held = options[picked[0]]
    record = escape_records.get(held.instance_id)
    if record:
        eo.attempt(ctx, ctx.actor, ctx.actor, *record)
    else:
        data = held.data or {}
        rule, dc = procedures[held.instance_id]
        if rule:
            from .restraint_riders import resolve_action_escape
            success = resolve_action_escape(ctx, held.instance_id, held)
        elif data.get("escape_save"):
            ability = str(held.data["escape_save"]).upper()
            success = resolve_escape_save(ctx.engine, ctx.actor, ability, dc, ctx.source, [held])
        else:
            success = resolve_escape_check(ctx, row, dc, [held], (held.condition_id.rsplit(".", 1)[-1],))
        if success and not rule:
            remove_instance(ctx.engine, ctx.actor, held.instance_id, ctx.source)
            from .hold_escapes import how_for
            escaped(ctx.engine, ctx.actor, [held], how_for(ability if (rule or data.get("escape_save")) else "STR", ctx.actor),
                    by=ctx.actor, source=ctx.source,
                    way="save" if data.get("escape_save") and not rule else "check")
    if held.instance_id not in ctx.actor.conditions and FOCUS in ctx.actor.resources and ctx.actor.resources.get(FOCUS, 0) < 1:
        ctx.engine._gain_resource(ctx.actor, FOCUS, 1, WATER)
