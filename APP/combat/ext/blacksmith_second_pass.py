"""Blacksmith combat responses on the existing equipment-carrier chassis.

Quench requires an explicit factual declaration of the smith's marked equipment
family; it never guesses that an armor mark is a weapon mark. The declaration
ends with the last mark. Loose objects and independently marked allied items
remain outside this carrier implementation. AI never invents a declaration.

Steady Hammer reads explicit persisted Smith's Tools proficiency, never a total.
Incarnation's repeated benefits require its own timed activation condition.
"""
from . import effect, hook
from .blacksmith_forge import held_condition, mark_count, set_marks, FORGE_MARK, INCARNATION

K = "tianxia.talent.blacksmith."
QUENCH = K + "quench_against_the_grain"
STEADY = K + "steady_hammer_breathing"
BLOCK = "blacksmith_second_pass"
EQUIPMENT = "condition:typed.blacksmith_quench_equipment"
LIVING = "condition:typed.blacksmith_living_forge"
EXPERT_USED = "condition:typed.blacksmith_steady_expertise_used"
EXPERT_PENDING = "condition:typed.blacksmith_steady_expertise_pending"


@hook("compile_block")
def compile_block(block, spec, row, numbers):
    if block == BLOCK:
        return [{**row, "block": BLOCK, "kind": spec["kind"]}]
    return None


def owns(engine, actor, kind):
    from .passive_rows import row_of
    return row_of(engine, actor.entity_id, BLOCK, kind) is not None


@hook("compile_actions")
def actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    made = []
    if QUENCH in info["owned_ids"]:
        for kind, label in [("weapon", "weapon"), ("armor", "armor or shield"), ("tool", "tool"), ("none", "unspecified equipment")]:
            made.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.blacksmith.quench_equipment.{kind}",
                display_name="Quench Against the Grain: my marked workpiece is " + label,
                owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "player_only": True, "expected_damage": 0,
                            "setting_description": "Declare the equipment actually bearing your Forge Marks. This does not equip or mark an item. The declaration ends when the last mark is gone.",
                            "typed": {"numbers": info["numbers"], "effects": [{"type": "blacksmith_quench_equipment", "kind": kind}], "riders": []}}))
    if INCARNATION in info["owned_ids"]:
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.blacksmith.living_forge_mark",
            display_name="Living Forge: place a Forge Mark (once this turn)", owner_id=info["actor_id"],
            economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
            parameters={"expected_damage": 0, "typed": {"numbers": info["numbers"], "effects": [{"type": "blacksmith_living_mark"}], "riders": []}}))
    return made


@effect("blacksmith_quench_equipment")
def declare(ctx, row):
    ctx.engine._remove_condition(ctx.actor, EQUIPMENT, QUENCH)
    if row["kind"] != "none" and mark_count(ctx.actor, ctx.actor.entity_id):
        ctx.engine._apply_condition(ctx.actor, EQUIPMENT, QUENCH, ctx.actor.entity_id,
            expires_on="UNTIL_REMOVED", data={"kind": row["kind"], "label": "Quench Against the Grain: marked " + row["kind"]})


@hook("candidate_allowed")
def living_candidate(engine, actor, candidate, action):
    if action is None or not action.source_definition_id.endswith("blacksmith.living_forge_mark"):
        return None
    from .blacksmith_forge import limit, TWO_BEAT_LOCK
    return bool(held_condition(actor, LIVING) and not actor.turn_flags.get("blacksmith_living_mark")
                and mark_count(actor, actor.entity_id) < limit(engine, actor)
                and not held_condition(actor, TWO_BEAT_LOCK + actor.entity_id))


@effect("blacksmith_living_mark")
def living_mark(ctx, row):
    if held_condition(ctx.actor, LIVING) and not ctx.actor.turn_flags.get("blacksmith_living_mark"):
        if set_marks(ctx.engine, ctx.actor, ctx.actor, 1, INCARNATION) > 0:
            ctx.actor.turn_flags["blacksmith_living_mark"] = True


@effect("blacksmith_living_forge")
def living_forge(ctx, row):
    from ..typed_executor import clock_expiry
    ctx.engine._apply_condition(ctx.actor, LIVING, ctx.source, ctx.actor.entity_id,
        expires_on=clock_expiry(ctx.engine, "one_minute"), data={"label": "Incarnation of the Living Forge"})


@hook("mark_spent")
def living_spend(ctx, name, subject):
    if name == FORGE_MARK and held_condition(ctx.actor, LIVING):
        ctx.engine._grant_temp_hp(ctx.actor, int(ctx.actor.proficiency_bonus), INCARNATION, ctx.actor.entity_id)
    if name == FORGE_MARK and subject is ctx.actor and mark_count(subject, ctx.actor.entity_id) == 0:
        ctx.engine._remove_condition(ctx.actor, EQUIPMENT, QUENCH)


@hook("turn_start")
@hook("turn_end")
def retire_declaration(engine, actor):
    if held_condition(actor, EQUIPMENT) and not mark_count(actor, actor.entity_id):
        engine._remove_condition(actor, EQUIPMENT, QUENCH)


def quench_available(engine, smith, kind, opponent):
    """Answer only the triggering opponent the shared reaction gate permits."""
    from .spirit_traditions import can_react
    from ..typed_reactions import reaction_permitted_against
    row = held_condition(smith, EQUIPMENT)
    return (owns(engine, smith, "quench") and can_react(smith) and row is not None
            and reaction_permitted_against(engine, smith, opponent)
            and row.data.get("kind") == kind and mark_count(smith, smith.entity_id) > 0
            and smith.turn_flags.get("blacksmith_quench_round_used") != engine.state.round_number)


def pay_quench(engine, smith, opponent, intent, prompt, provenance):
    """Offer the correction, naming the action that asked and the creature it concerns.

    ``provenance`` is choice_prompt.action_context for the triggering attack, so the
    table reads "who struck, with what, landing on whom" instead of a bare sentence.
    """
    from . import ai_controlled
    from ..typed_reactions import reaction_permitted_against
    if not reaction_permitted_against(engine, smith, opponent):
        return False
    from .needle import ask, checkpoint_id
    chosen = ask(engine, intent, checkpoint_id(engine, "BLACKSMITH_QUENCH", smith.entity_id), smith,
        "choice:needle.blacksmith_quench", ["quench"], labels={"quench": "Spend your Reaction and 1 Forge Mark"},
        prompt=prompt, name="Quench Against the Grain", feature_id=QUENCH,
        allow_decline=True, default="first" if ai_controlled(engine, smith) else "decline", automatic=True,
        prompt_context={**provenance, "cost": "1 Reaction and 1 Forge Mark", "duration": "This roll only"})
    if not chosen:
        return False
    from ..typed_reactions import spend_reaction
    from .spirit_traditions import context, feature_action, numbers
    from .blacksmith_forge import spend_marks
    ctx = context(engine, smith, feature_action(engine, smith, QUENCH), [smith], numbers(engine, smith), intent)
    spend_reaction(engine, smith, {"feature_id": QUENCH})
    # Not an assert: python -O would strip the payment itself.
    if spend_marks(ctx, smith, 1, QUENCH) != 1:
        raise RuntimeError("Quench resolved without spending its Forge Mark")
    smith.turn_flags["blacksmith_quench_round_used"] = int(engine.state.round_number)
    engine._append_event("REACTION_RESOLVED", QUENCH, actor_id=smith.entity_id,
                        target_ids=(smith.entity_id,), payload={"text": prompt})
    return True


def attack_context(engine, attacker, target, spec):
    """Name the attack that asked for the correction, and the creature it lands on.

    Both Quench corrections answer one attack, so both describe it the same way: the
    creature whose strike triggered the question, and the creature that strike concerns.
    ``spec`` is the engine's own attack record, so a native and a typed attack name
    themselves identically.
    """
    from .choice_prompt import action_context
    return action_context(engine, attacker, str(spec.get("source_definition_id") or ""), target)


@hook("attack_miss_outcome")
def correct_miss(engine, attacker, target, spec, roll, intent, total, armor_class):
    if (not quench_available(engine, attacker, "weapon", target) or not 1 <= armor_class - total <= 2
            or str((spec.get("parameters") or {}).get("attack_kind") or "").lower() != "weapon"):
        return None
    from . import ai_controlled
    from ..relations import ENEMY, relation
    if ai_controlled(engine, attacker) and relation(engine, attacker, target) != ENEMY:
        return None
    if pay_quench(engine, attacker, target, intent, f"Your marked weapon missed {target.display_name} by {armor_class - total}. Turn this miss into a hit?",
                  attack_context(engine, attacker, target, spec)):
        return {"source_id": QUENCH, "label": "Quench Against the Grain", "force_hit": True}
    return None


@hook("hit_response")
def correct_hit(engine, attacker, target, spec, total, natural, effective_ac):
    # Printed hit-by-two includes a tie. This is an explicit forced outcome,
    # including a natural 20 whose final total is within the printed margin.
    if not quench_available(engine, target, "armor", attacker) or not 0 <= total - effective_ac <= 2:
        return None
    if pay_quench(engine, target, attacker, engine._active_intent, f"{attacker.display_name} hit you by {total - effective_ac}. Use your marked armor or shield to turn this hit into a miss?",
                  attack_context(engine, attacker, target, spec)):
        from ..attack_outcomes import unconditional_miss
        return unconditional_miss()
    return None


def smiths_tools(name):
    return str(name or "").replace("’", "'").replace("_", " ").casefold() in {"smith's tools", "smiths tools"}


@hook("d20_bonus")
def steady_bonus(engine, roll, intent):
    actor = engine.state.actors.get(roll.actor_id)
    if actor is None or not owns(engine, actor, "steady") or not str(roll.reason).startswith("CHECK:"):
        return None
    context = engine.d20_context(roll) or {}
    if not smiths_tools(context.get("skill") or str(roll.reason).rpartition(":")[2]):
        return None
    if smith_proficiency(engine, actor) == 1:
        return {"source_id": STEADY, "bonus": int(actor.proficiency_bonus)}
    return None


@hook("skill_check_mode")
def steady_expertise(ctx, actor, ability, skill):
    if not smiths_tools(skill) or not owns(ctx.engine, actor, "steady") or held_condition(actor, EXPERT_USED):
        return None
    if smith_proficiency(ctx.engine, actor) != 2:
        return None
    pending = held_condition(actor, EXPERT_PENDING)
    intent_id = str(getattr(ctx.intent, "intent_id", ""))
    if pending and pending.data.get("source") == ctx.source and pending.data.get("intent") == intent_id:
        return "ADVANTAGE"
    if pending:
        ctx.engine._remove_condition(actor, EXPERT_PENDING, STEADY)
    from .needle import ask, checkpoint_id
    from .choice_prompt import action_context, initiating_actor
    # The sheet that carries Steady Hammer is the subject of the check, so it is the
    # creature this question concerns. It is not necessarily the creature whose action
    # asked for the check: on an opposed check's defending side the check rides another
    # creature's action, and the table must say "who acted" and "who is checked" apart.
    action = getattr(ctx, "action", None)
    meta = action_context(ctx.engine, initiating_actor(ctx.engine, actor, action), ctx.source, actor,
                          action=action)
    if not ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "STEADY_HAMMER", actor.entity_id), actor,
        "choice:needle.blacksmith_steady", ["advantage"], labels={"advantage": "Use your once-per-short-rest Advantage"},
        prompt="Use Steady Hammer Breathing on this Smith's Tools check?", name="Steady Hammer Breathing",
        allow_decline=True, default="decline", automatic=True, prompt_context=meta):
        return None
    # The selection keeps its own identity: which check it was chosen for, under which
    # action and intent. Producers disagree about what a roll reason spells out, so the
    # receipt is matched against this rather than against a parsed reason string.
    ctx.engine._apply_condition(actor, EXPERT_PENDING, STEADY, actor.entity_id, expires_on="UNTIL_REMOVED",
        data={"source": ctx.source, "intent": intent_id, "skill": str(skill),
              "label": "Steady Hammer Breathing: Advantage selected for this check"})
    return "ADVANTAGE"


def smith_proficiency(engine, actor):
    """Explicit sealed tool rank, accepting the printed apostrophe spellings.

    Conflicting duplicate ranks are unknown rather than guessed from a total.
    """
    bundle = next((b for b in engine.typed_bundle_documents if b.get("actor_id") == actor.entity_id), {})
    ranks = {v for k, v in (bundle.get("skill_proficiency") or {}).items() if smiths_tools(k)}
    return next(iter(ranks)) if len(ranks) == 1 else None


def receipt_skill(payload, actor_id):
    """The skill a CHECK_ROLLED producer named for this side, or None.

    Producers disagree about what they name: an ordinary skill_check names its skill
    in the payload, while resolve_opposed_check names only the acting side's. A side
    that names none stays unknown here rather than being guessed out of the roll
    reason, which for opposed checks carries the action id instead of a skill.
    """
    for key in ("actor", "roll"):
        roll = payload.get(key)
        if isinstance(roll, dict) and str(roll.get("actor_id") or "") == str(actor_id):
            return payload.get("skill")
    return None


@hook("event")
def steady_check_rolled(engine, event_type, kwargs):
    """Spend the pending Advantage on the die that actually carried it.

    The selection is matched by its own recorded identity -- subject skill, source and
    intent -- plus the roll's own applied mode, both of which a check producer reports
    the same way whether the check was an ordinary skill_check or one side of an
    opposed check. The roll's reason is never parsed, so a producer that spells out a
    skill and one that spells out an action both settle correctly.
    """
    if event_type != "CHECK_ROLLED":
        return
    from .roll_context import check_receipts
    payload = kwargs.get("payload") or {}
    intent_id = str(getattr(engine._active_intent, "intent_id", ""))
    for actor_id, roll in check_receipts(kwargs):
        actor = engine.state.actors.get(actor_id)
        pending = held_condition(actor, EXPERT_PENDING) if actor else None
        if (pending is None or pending.data.get("source") != kwargs.get("source_definition_id")
                or pending.data.get("intent") != intent_id):
            continue
        named = receipt_skill(payload, actor_id)
        if not smiths_tools(str(pending.data.get("skill") or "")) or (named is not None and not smiths_tools(str(named))):
            continue
        # The use belongs to the completed check that received the selection. Advantage
        # and Disadvantage cancel to a NORMAL die, but that check still received the
        # selected benefit by canceling its Disadvantage. Mode queries without a roll
        # never emit this receipt and therefore still spend nothing.
        engine._remove_condition(actor, EXPERT_PENDING, STEADY)
        engine._apply_condition(actor, EXPERT_USED, STEADY, actor.entity_id, expires_on="UNTIL_REMOVED",
            data={"label": "Steady Hammer Breathing: Advantage used until the next short rest"})


@hook("turn_end")
def steady_unused_query(engine, actor):
    if held_condition(actor, EXPERT_PENDING):
        engine._remove_condition(actor, EXPERT_PENDING, STEADY)
