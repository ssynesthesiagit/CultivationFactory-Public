"""Yin's Waning Mark family: preservation, limits and the Diminishing Responses.

Covers the printed records ``TAL_YIN_MARKED_ALLIES``, ``TAL_YIN_MARK_LIMIT``,
``TAL_YIN_QUIET_RECEPTION``, ``TAL_YIN_PRESERVING_YIN`` and the rest of
``TAL_YIN_SPENDING_A_WANING_MARK``.  Diminish Force and Diminish Recovery keep
their existing owners (the generic reaction compiled from splits.json and
combat/ext/healing_interception.py); this module adds the four responses they do
not own and the two passive rules, and shares the printed once-a-round flag with
both, so one mark still buys one response.

Rows: this plug-in's own ``yin_marked_allies`` and ``yin_preserving_yin`` blocks
(combat/rules/feature_blocks.d/mgr_t15_yin_marks.json) plus Mark Limit's shared
``mark_caps`` row (rules/feature_blocks.d/elements.json), which is why Mark Limit
is recognized by its feature id rather than by a block of its own.  A character
without the rows is inert in every hook here.

Marked Allies
  A Waning Mark placed on a creature of the marker's own team is a preservation
  mark (``data.preserved = 1``), and every creature that bears one answers the
  printed "willing" question through the shared consent transport: a player is
  asked, an automatic seat decides for itself.  Team membership never stands in
  for consent.  While the mark is preserved:
    * Diminish Aim and Diminish Readiness are never offered (not in the printed
      list of responses that may benefit the ally).
    * Diminish Power is offered only when the ally is the creature making the
      saving throw (the only case where adding the die benefits it).
    * Diminish Step is never offered (slowing the ally never benefits it).
    * Diminish Force is refused on a preserved mark (reducing the ally's own
      damage cannot benefit it).
    * Diminish Recovery keeps its existing owner and already states the printed
      "only if it benefits that creature" in its prompt.
  Every response prompt for a preserved mark repeats that restriction.

Mark Limit
  Same plane: the engine has no planar travel, so a creature's plane is a persisted
  plane condition (default ``material``).  A plane change ends a mark whose marker is
  on another plane at once (event hook, mid-turn too); the start of a marked
  creature's turn re-reads it as a backstop.
  Willing self-removal: the printed clause is "A willing creature may end your Waning
  Mark on itself at any time, no Action required" (Marked Allies; the same willing
  creature may also give back a Mark Limit mark).  The creature gets its own free
  "End a Waning Mark on you" button (a catalog Action with no Action or Bonus Action
  cost) for the whole of its turn, so it can end the mark whenever it is making a
  decision during that turn.  The button asks which mark to end when the creature
  bears several.  Off its own turn the same creature is asked at every turn boundary
  (``turn_start_choice``): the printed "at any time" is not limited to its own turn,
  and the shared choice transport can put that free question to a player whose
  creature is not the current actor.  An automatic seat keeps the mark unless its
  controller accepts the choice.

Quiet Reception
  The compiled generic reaction already answers ``ally_missed`` at 60 feet with
  sight.  Its mark lasts until the end of the marker's next turn unless the miss
  was caused by Disadvantage, concealment, cover or one of this Yin character's
  own penalties; then it lasts 1 minute.  The cause is read from the actual
  attack: the roll's mode, its cover bonus, the concealment percentile receipt,
  or the Diminish Aim penalty this module applied.

Preserving Yin
  A native ``would_drop`` answer replaces the generic row (so the printed 2 CP
  and the willing creature are read before anything is paid): every recipient
  answers the printed "willing creature" question through the shared consent
  transport -- an allied player included, and the owner itself is willing by
  definition -- then the owner is asked, the 2 CP and the Reaction are paid only
  on an accepted preservation, the creature drops to 1 HP, cannot regain HP until
  the start of the owner's next turn, takes PB less damage from every later
  packet until that same moment, and gains the Waning Mark.  The creature cannot
  benefit again until a Long Rest; the receipt is a persisted integer flag on the
  creature.

Diminishing Responses (shared once a round, no Action, marker must perceive the
marked creature, mark spent only when the response is taken):
  Aim         the marked creature makes an attack roll: -1d4 (-1d6 at CL 11).
  Power       it forces a save: one creature making that save adds 1d4 (1d6 at CL 11).
  Step        it begins movement: one Speed drops 10 feet (20 at CL 11) until the turn ends.
              When the movement is the creature's own teleport, the same response instead
              shortens that teleport by 10 feet (20 at CL 11), through the general
              declaration-time movement budget (technique_declared movement_cap_ft) that
              every teleport already honours: a landing square beyond the shortened
              distance fails visibly, exactly as any other budget-limited teleport does.
  Readiness   it takes a Reaction: it cannot take Reactions until the start of
              its next turn.  The same response cancels the triggering Advantage on the
              marked creature's roll, whichever roll it is: the printed trigger names any
              roll, so one implementation answers at the shared pre-draw checkpoint
              (``d20_mode_removed``) for attack rolls, saving throws and ability checks
              alike, and leaves every other roll untouched.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

SPEND = "TAL_YIN_SPENDING_A_WANING_MARK"
MARK = "Waning Mark"
MARKED_ALLIES = "TAL_YIN_MARKED_ALLIES"
MARK_LIMIT = "TAL_YIN_MARK_LIMIT"
QUIET = "TAL_YIN_QUIET_RECEPTION"
PRESERVING = "TAL_YIN_PRESERVING_YIN"
AIM = SPEND + "#diminish_aim"
POWER = SPEND + "#diminish_power"
STEP = SPEND + "#diminish_step"
READINESS = SPEND + "#diminish_readiness"
FORCE = SPEND + "#diminish_force"
ONCE = "once_per_round:typed." + SPEND  # typed_reactions._once_key for the shared group
WARD = "condition:typed.yin_preserving_yin"
RECEIPT = "condition:typed.yin_preserved"
DENIED = "condition:typed.reaction_denied"
PLANE = "condition:typed.plane."
PRESERVED = "preserved"
PLANE_DEFAULT = "material"
REMOVE = "system:combat.yin_mark.remove"


# ------------------------------------------------------------------------------------------ shared helpers
def _rows(engine: Any, actor: Any, block: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", None), [])
            if row.get("block") == block]


def _all_rows(engine: Any, actor: Any) -> list[dict[str, Any]]:
    return [row for pool in ("typed_passive_rows", "typed_reaction_rows")
            for row in ((getattr(engine, pool, {}) or {}).get(getattr(actor, "entity_id", None), []) or [])]


def owns_spend(engine: Any, actor: Any) -> bool:
    """Whether ``actor`` owns Spending a Waning Mark (the compiled child or its Recovery row)."""
    return any(str(row.get("feature_id") or "") == SPEND
               or str(row.get("feature_id") or "").startswith(SPEND + "#")
               or row.get("block") == "diminish_recovery" for row in _all_rows(engine, actor))


def numbers(engine: Any, actor: Any) -> dict[str, int]:
    for row in _all_rows(engine, actor):
        nums = row.get("numbers") or {}
        if nums:
            return {"pb": int(nums.get("pb") or 2), "cl": int(nums.get("cl") or 1), "key_mod": int(nums.get("key_mod") or 0),
                    "save_dc": int(nums.get("save_dc") or 10)}
    return {"pb": int(getattr(actor, "proficiency_bonus", 2) or 2), "cl": int(getattr(actor, "cultivation_level", 1) or 1),
            "key_mod": 0, "save_dc": 10}


def _mark_id(owner_id: str) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(MARK, owner_id)


def mark_on(subject: Any, owner_id: str) -> Any:
    condition_id = _mark_id(owner_id)
    return next((row for row in subject.conditions.values() if row.condition_id == condition_id), None)


def preserved(subject: Any, owner_id: str) -> bool:
    mark = mark_on(subject, owner_id)
    if mark is None:
        return False
    data = mark.data or {}
    # A mark moved onto a creature no longer on the marker's team is harmful again.
    return bool(int(data.get(PRESERVED) or 0) and data.get("preserved_team") == getattr(subject, "team_id", None))


def _perceives(engine: Any, owner: Any, subject: Any) -> bool:
    if subject is owner:
        return True
    from .. import stealth

    return bool(stealth.sees(engine, owner, subject))


def _can_spend(engine: Any, owner: Any) -> bool:
    from . import needle

    return bool(owner.active and not needle.incapacitated(owner)
                and owner.turn_flags.get(ONCE) != engine.state.round_number)


def _spend(engine: Any, owner: Any, subject: Any, source: str, name: str) -> bool:
    """Take the marked creature's Waning Mark and claim the shared round."""
    from .states import context
    from ..typed_executor import block_spend_mark

    if mark_on(subject, owner.entity_id) is None:
        return False
    ctx = context(engine, owner, source, [subject], numbers(engine, owner))
    ctx.action = ctx.action.model_copy(update={"source_definition_id": source, "display_name": name})
    ctx.intent = getattr(engine, "_active_intent", None)
    block_spend_mark(ctx, {"type": "spend_mark", "mark": MARK, "applies_to": "target"})
    owner.turn_flags[ONCE] = int(engine.state.round_number)
    return True


def _ask(engine: Any, owner: Any, subject: Any, key: str, choice_id: str, label: str, prompt: str,
         *, want: bool) -> bool:
    from .needle import ask, checkpoint_id

    picked = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, key, getattr(subject, "entity_id", "")), owner, choice_id,
                 ["use"], labels={"use": label}, allow_decline=True,
                 default="first" if want else "decline", name=label.split(":")[0], feature_id=SPEND,
                 target_id=getattr(subject, "entity_id", None), prompt=prompt)
    return bool(picked)


def _benefit_note(engine: Any, owner: Any, subject: Any) -> str:
    """The printed Marked Allies restriction, present only on a preservation mark."""
    return (" This mark was placed to preserve an ally, so use it only if doing so benefits "
            f"{subject.display_name}." if preserved(subject, owner.entity_id) else "")


def _owners(engine: Any) -> list[Any]:
    return [actor for actor in engine.state.actors.values() if actor.active and owns_spend(engine, actor)]


def _consents(engine: Any, subject: Any, asker: Any, ability: str, prompt: str) -> bool:
    """The printed "willing" question, asked of ``subject``; the asker needs no consent from itself."""
    if subject is asker:
        return True
    from .willing_targets import asks_consent

    return asks_consent(engine, getattr(engine, "_active_intent", None), subject, ability, prompt,
                        prefer_accept=subject.team_id == asker.team_id, asker=asker)


# ------------------------------------------------------------------------------------------ compiling
@hook("compile_block")
def compile_yin_block(block: str, spec: dict[str, Any], row: dict[str, Any], nums: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block not in ("yin_marked_allies", "yin_mark_limit", "yin_preserving_yin"):
        return None
    return [{**row, "block": block, "pb": int(nums.get("pb") or 2), "cl": int(nums.get("cl") or 1),
             "key_mod": int(nums.get("key_mod") or 0),
             "save_dc": int((nums.get("record") or {}).get("technique_save_dc") or 10)}]


# ------------------------------------------------------------------------------------------ Marked Allies
@hook("mark_applied", priority=-10)
def preserve_ally_mark(ctx: Any, name: str, subject: Any) -> None:
    """A Waning Mark on a willing ally represents preservation, not harm.

    The realm's mark is placed first; this hook then asks the creature whose mark
    it is ("willing ally" is its answer, never its team) and only an explicit yes
    turns the mark into a preservation mark.  Preserving Yin already asked the
    same creature before placing its mark, so it is not asked twice.
    """
    if name.strip().lower() != MARK.lower() or subject is ctx.actor:
        return
    if not _rows(ctx.engine, ctx.actor, "yin_marked_allies") or subject.team_id != ctx.actor.team_id:
        return
    mark = mark_on(subject, ctx.actor.entity_id)
    if mark is None or int((mark.data or {}).get(PRESERVED) or 0):
        return
    if str(getattr(ctx, "source", "") or "") != PRESERVING and not _consents(
            ctx.engine, subject, ctx.actor, MARKED_ALLIES,
            f"Marked Allies: {ctx.actor.display_name} places a Waning Mark on you to preserve you. "
            "It can then be spent only in ways that help you, and you may end it at any time with no Action. "
            "Accept the preservation mark?"):
        return
    from .condition_ownership import remove_instance

    data = {**(mark.data or {}), PRESERVED: 1, "preserved_team": ctx.actor.team_id}
    remove_instance(ctx.engine, subject, mark.instance_id, MARKED_ALLIES)
    ctx.engine._apply_condition(subject, mark.condition_id, MARKED_ALLIES, ctx.actor.entity_id,
                                expires_on=mark.expires_on, data=data)


@hook("reaction_subject_allowed")
def force_needs_benefit(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    """Marked Allies: Diminish Force on a preservation mark never benefits that ally."""
    if row is None or str(row.get("feature_id") or "") != FORCE or other is None:
        return None
    return False if preserved(other, reactor.entity_id) else None


# ------------------------------------------------------------------------------------------ Mark Limit
def _owns_mark_limit(engine: Any, owner: Any) -> bool:
    """Mark Limit's compiled row is the shared mark cap, so its feature id is the ownership row.

    The feature declares one block (``mark_caps`` in rules/feature_blocks.d/elements.json):
    a second row for the same feature id would collide with that registration. The
    ``yin_mark_limit`` block name is accepted too for any older compilation.
    """
    return any(str(row.get("feature_id") or "") == MARK_LIMIT or row.get("block") == "yin_mark_limit"
               for row in _all_rows(engine, owner))


def _plane(actor: Any) -> str:
    """The engine has no planar travel; a plane is a persisted condition on the creature."""
    for condition in actor.conditions.values():
        if condition.condition_id.startswith(PLANE):
            return condition.condition_id[len(PLANE):]
    return PLANE_DEFAULT


def _end_off_plane_marks(engine: Any, actor: Any) -> None:
    """The same-plane clause for every mark on ``actor``, whenever a plane condition changes."""
    from .condition_ownership import remove_instance

    for owner in engine.state.actors.values():
        if not _owns_mark_limit(engine, owner) or not owner.active:
            continue
        mark = mark_on(actor, owner.entity_id)
        if mark is None:
            continue
        if _plane(actor) != _plane(owner):
            remove_instance(engine, actor, mark.instance_id, MARK_LIMIT)
            note(engine, MARK_LIMIT, owner,
                 f"Mark Limit: {owner.display_name}'s Waning Mark on {actor.display_name} ends because they are no longer "
                 "on the same plane of existence.", targets=[actor])


@hook("event", nested=True)
def plane_change_ends_marks(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """A plane change ends an off-plane mark at once, mid-turn as well as at the start of a turn."""
    if event_type not in ("CONDITION_APPLIED", "CONDITION_REMOVED"):
        return
    for actor in list(engine.state.actors.values()):
        if actor.conditions:
            _end_off_plane_marks(engine, actor)


@hook("turn_start")
def mark_limit_on_turn(engine: Any, actor: Any) -> None:
    """The same-plane clause, re-read when a marked creature's turn begins (a backstop to the event hook)."""
    _end_off_plane_marks(engine, actor)


def _willing_removal_owned(engine: Any, owner: Any) -> bool:
    """The removal clause is Marked Allies'; Mark Limit carries the same willing creature's mark."""
    return bool(_owns_mark_limit(engine, owner) or _rows(engine, owner, "yin_marked_allies"))


def removable_marks(engine: Any, actor: Any) -> list[Any]:
    """Every same-team Waning Mark ``actor`` may end on itself, with the marker that placed it."""
    out = []
    for owner in engine.state.actors.values():
        if owner is actor or not owner.active or not _willing_removal_owned(engine, owner):
            continue
        mark = mark_on(actor, owner.entity_id)
        if mark is None or actor.team_id != owner.team_id:
            continue
        if _plane(actor) != _plane(owner):
            continue  # the same-plane clause already ended it
        out.append((owner, mark))
    return out


def _end_mark(engine: Any, actor: Any, owner: Any, mark: Any) -> None:
    """End one removable Waning Mark on ``actor``; no Action, Bonus Action or Reaction is spent."""
    from .condition_ownership import remove_instance

    remove_instance(engine, actor, mark.instance_id, MARK_LIMIT)
    note(engine, MARK_LIMIT, actor, f"Mark Limit: {actor.display_name} ends {owner.display_name}'s Waning Mark.",
         targets=[actor])


@hook("turn_start_choice")
def offer_removal_off_turn(engine: Any, actor: Any) -> None:
    """The printed "at any time, no Action required" includes a turn that is not the bearer's own.

    The creature whose turn is opening is left to its own menu (the free button below);
    every other bearer of a removable mark is asked here, at this turn boundary as at
    any other, through the shared off-turn choice transport.
    """
    from . import ai_controlled
    from .needle import ask, checkpoint_id

    intent = getattr(engine, "_active_intent", None)
    if intent is None:
        return
    for bearer in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if bearer is actor or not bearer.active or ai_controlled(engine, bearer):
            continue
        marks = removable_marks(engine, bearer)
        if not marks:
            continue
        labels = {mark.instance_id: f"End {owner.display_name}'s Waning Mark on you (no Action)"
                  for owner, mark in marks}
        picked = ask(engine, intent, checkpoint_id(engine, "yin_mark_remove_off_turn", bearer.entity_id),
                     bearer, "choice:needle.yin_mark_remove", list(labels), labels=labels,
                     allow_decline=True, default="decline", name="End a Waning Mark", feature_id=MARK_LIMIT,
                     target_id=bearer.entity_id,
                     prompt=f"End a Waning Mark: {bearer.display_name} bears a Waning Mark that preserves it. "
                            "It may end that mark at any time with no Action. End it now?")
        if not picked:
            continue
        owner, mark = next((owner, mark) for owner, mark in marks if mark.instance_id == picked[0])
        _end_mark(engine, bearer, owner, mark)


@hook("match_start")
def install_removal_action(engine: Any) -> None:
    """The printed no-Action self-removal is a free button on the marked creature's own menu."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    engine.action_catalog[REMOVE] = ActionDefinition(
        source_definition_id=REMOVE, display_name="End a Waning Mark on you", owner_id="*",
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "end_yin_mark"}], "numbers": {},
                              "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "free_primary": True,
                    "description": "End a Yin ally's Waning Mark on you. It costs no Action "
                    "or Bonus Action, and you may use it at any time during your turn."})


@hook("additional_actions")
def offer_removal_action(engine: Any, actor: Any) -> list[str]:
    if REMOVE not in engine.action_catalog or not removable_marks(engine, actor):
        return []
    return [REMOVE]


@hook("candidate_allowed")
def removal_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is not None and action.source_definition_id == REMOVE:
        return bool(removable_marks(engine, actor))
    return None


@effect("end_yin_mark")
def end_yin_mark(ctx: Any, row: dict[str, Any]) -> None:
    """End one of the willing marks on the acting creature; no Action is spent."""
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    marks = removable_marks(engine, actor)
    if not marks:
        return
    labels = {mark.instance_id: f"End {owner.display_name}'s Waning Mark on you (no Action)"
              for owner, mark in marks}
    if len(marks) == 1:
        picked = list(labels)
    else:
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "yin_mark_remove", actor.entity_id), actor,
                     "choice:needle.yin_mark_remove", list(labels), labels=labels, allow_decline=True,
                     default="decline", name="End a Waning Mark", feature_id=MARK_LIMIT,
                     target_id=actor.entity_id,
                     prompt=f"{actor.display_name} bears more than one Waning Mark. Which one ends? "
                            "No Action is required.")
    if not picked:
        return
    owner, mark = next((owner, mark) for owner, mark in marks if mark.instance_id == picked[0])
    _end_mark(engine, actor, owner, mark)


# ------------------------------------------------------------------------------------------ Quiet Reception
def _miss_caused_by_a_qualifying_source(engine: Any, attacker_id: str, owner_id: str) -> bool:
    """Disadvantage, concealment, cover, or a penalty from this Yin character's own features."""
    for event in reversed(engine.events[-40:]):
        if getattr(event, "actor_id", None) != attacker_id:
            continue
        payload = event.payload or {}
        if event.event_type == "ATTACK_ROLLED":
            if payload.get("mode") == "DISADVANTAGE" or int(payload.get("cover_bonus") or 0) > 0:
                return True
            return _yin_penalty(engine, attacker_id, event, owner_id)
        if event.event_type == "PASSIVE_TRIGGERED" and payload.get("miss_chance_percent") is not None:
            return bool(payload.get("missed"))
        if event.event_type in ("ATTACK_RESOLVED", "DAMAGE_COMMITTED", "MOVEMENT_COMMITTED"):
            break
    return False


def _yin_penalty(engine: Any, attacker_id: str, roll: Any, owner_id: str) -> bool:
    """True only when THIS Yin character's Diminish Aim receipt was spent on THIS attack roll.

    The receipt records its owner: a Diminish Aim from another Yin cultivator is not
    "a penalty imposed by one of your Yin features", so it must not lengthen this
    mark. The receipt is written before the roll, and a roll consumes it: it applies
    to the first attack roll by that creature recorded after the receipt. Later
    rolls, and a receipt whose roll never happened, do not qualify.
    """
    receipt = getattr(engine, "_yin_aim_penalty", None)
    if not receipt or receipt[0] != owner_id or receipt[1] != attacker_id:
        return False
    spent_at, roll_at = int(receipt[2]), int(roll.sequence)
    if not spent_at < roll_at:
        return False
    return not any(int(e.sequence) > spent_at and int(e.sequence) < roll_at
                   and e.event_type == "ATTACK_ROLLED" and getattr(e, "actor_id", None) == attacker_id
                   for e in engine.events)


@hook("mark_duration")
def quiet_reception_duration(ctx: Any, name: str, duration_kind: str) -> dict[str, int | str] | None:
    """Quiet Reception's mark lasts a minute when the miss had one of the printed causes."""
    if str(getattr(ctx, "source", "")) != QUIET or name.strip().lower() != MARK.lower():
        return None
    marked = ctx.target
    if marked is None or not _miss_caused_by_a_qualifying_source(
            ctx.engine, marked.entity_id, getattr(ctx.actor, "entity_id", "")):
        return None
    return {"kind": "minutes", "amount": 1}


# ------------------------------------------------------------------------------------------ Preserving Yin
def _preserved_before(actor: Any, owner_id: str) -> bool:
    """The long-rest receipt: a persisted condition, so it survives every turn-flag reset."""
    return any(c.condition_id == RECEIPT and str((c.data or {}).get("owner") or "") == owner_id
               for c in actor.conditions.values())


@hook("would_drop")
def preserving_yin(engine: Any, target: Any, pending: int, source_actor_id: str | None) -> int | None:
    """The printed 2 CP preservation: asked and paid only when the willing creature accepts."""
    from .. import typed_reactions
    from .choice_costs import payable
    from .cp_pools import of
    from ..damage_allocation import maximum_packet_before_hp_floor

    if pending <= 0:
        return None
    for owner in engine.state.actors.values():
        row = next(iter(_rows(engine, owner, "yin_preserving_yin")), None)
        if row is None or not owner.active:
            continue
        if not target.active or engine._distance_actor_to_actor(owner, target) > 30 or not _perceives(engine, owner, target):
            continue
        if _preserved_before(target, owner.entity_id) or not typed_reactions.can_react(engine, owner):
            continue
        # "A willing creature within 30 feet" includes the owner itself, and an
        # allied player answers the same question as anyone else.
        if not _consents(
                engine, target, owner, PRESERVING,
                f"Preserving Yin: {owner.display_name} offers to keep you at 1 Hit Point instead of 0. "
                f"It costs {owner.display_name} 2 CP and their Reaction; you cannot regain Hit Points until the "
                f"start of {owner.display_name}'s next turn, but damage you take is reduced by their Proficiency "
                "Bonus until then, and you gain their Waning Mark. Accept?"):
            continue
        pool = of(owner, at_least=2)
        payment = payable(owner, pool or "", 2)
        if payment is None:
            continue
        if not _ask(engine, owner, target, "preserving_yin", "choice:needle.preserving_yin",
                    "Preserving Yin: keep the creature at 1 Hit Point",
                    f"Preserving Yin: {target.display_name} would drop to 0 Hit Points. Spend your Reaction and "
                    f"{payment.quote()} to leave it at 1 Hit Point, place your Waning Mark on it, and reduce the damage "
                    "it takes by your Proficiency Bonus until the start of your next turn? It cannot regain Hit Points "
                    "until then.", want=owner.team_id == target.team_id):
            continue
        payment.pay(engine, owner, PRESERVING)
        typed_reactions.open_reaction(engine, row, owner, (target.entity_id,), "DAMAGE_APPLICATION")
        typed_reactions.spend_reaction(engine, owner, row)
        cap = maximum_packet_before_hp_floor(engine, target, pending, 1, source_actor_id)
        _apply_preservation(engine, owner, target, row)
        engine._append_event("REACTION_RESOLVED", PRESERVING, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                             payload={"checkpoint": "DAMAGE_APPLICATION", "kind": "ally_drop_to_zero",
                                      "pending_before": pending, "pending_after": min(pending, cap),
                                      "log": f"Preserving Yin: {target.display_name} is left at 1 Hit Point "
                                             f"({owner.display_name} spends {payment.quote()} and their Reaction)."})
        return min(pending, cap)
    return None


def _apply_preservation(engine: Any, owner: Any, target: Any, row: dict[str, Any]) -> None:
    from ..typed_executor import Context, block_mark, run_effects

    nums = {"pb": int(row.get("pb") or 2), "cl": int(row.get("cl") or 1), "key_mod": int(row.get("key_mod") or 0)}
    inner = Context(engine, owner, engine.action_catalog.get(PRESERVING) or next(iter(engine.action_catalog.values())),
                    getattr(engine, "_active_intent", None), {"numbers": nums, "effects": []}, [target], target, {})
    inner = inner.with_source(PRESERVING)
    run_effects(inner, [{"type": "healing_reduction", "applies_to": "target", "duration": "until_start_of_next_turn",
                         "evidence": "Until the start of your next turn, it cannot regain Hit Points"}])
    block_mark(inner, {"mark": MARK, "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"}})
    engine._apply_condition(target, WARD, PRESERVING, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"pb": nums["pb"], "label": f"Preserving Yin: damage it takes is {nums['pb']} less "
                                                             f"(until the start of {owner.display_name}'s next turn)"})
    engine._apply_condition(target, RECEIPT, PRESERVING, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"owner": owner.entity_id,
                                  "label": "Preserving Yin: this creature cannot benefit from the same Yin talent "
                                           "again until it finishes a Long Rest"})


@hook("incoming_damage")
def ward_reduction(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str,
                   source_actor_id: str | None) -> int | None:
    cut = sum(int((condition.data or {}).get("pb") or 0) for condition in target.conditions.values()
              if condition.condition_id == WARD)
    return min(int(amount), cut) if cut and amount > 0 else None


@hook("status_description")
def ward_status(engine: Any, holder: Any, row: Any, data: Any) -> dict[str, Any] | None:
    if (row or {}).get("condition_id") != WARD:
        return None
    text = str((data or {}).get("label") or "")
    return {"text": text} if text else None


@hook("event", nested=True)
def clear_preservation_on_rest(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "LONG_REST":
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None:
        return
    from .condition_ownership import remove_instance

    for condition in [c for c in actor.conditions.values() if c.condition_id == RECEIPT]:
        remove_instance(engine, actor, condition.instance_id, PRESERVING)


# ------------------------------------------------------------------------------------------ Diminish Aim
def _diminish_die(engine: Any, owner: Any) -> int:
    return 6 if int(numbers(engine, owner)["cl"]) >= 11 else 4


@hook("attack_bonus")
def diminish_aim(ctx: Any, actor: Any) -> int | None:
    """The marked creature makes an attack roll: subtract 1d4 (1d6 at CL 11)."""
    from ..gate2_runtime_models import DiceSpec

    total = 0
    for owner in _owners(ctx.engine):
        if owner is actor or not _perceives(ctx.engine, owner, actor) or not _can_spend(ctx.engine, owner):
            continue
        if mark_on(actor, owner.entity_id) is None or preserved(actor, owner.entity_id):
            continue
        if not _ask(ctx.engine, owner, actor, "yin_diminish_aim", "choice:needle.yin_diminish_aim",
                    "Diminish Aim: subtract 1d4 from the attack roll",
                    f"Diminish Aim: {actor.display_name}, who bears your Waning Mark, makes an attack roll with "
                    f"{getattr(getattr(ctx, 'action', None), 'display_name', None) or 'an attack'}. Spend the mark to "
                    f"subtract 1d{_diminish_die(ctx.engine, owner)} from it? "
                    "Once a round; no Action."
                    + _benefit_note(ctx.engine, owner, actor), want=False):
            continue
        if not _spend(ctx.engine, owner, actor, AIM, "Diminish Aim"):
            continue
        roll = ctx.engine.roller.roll(DiceSpec(count=1, sides=_diminish_die(ctx.engine, owner), modifier=0),
                                      actor_id=owner.entity_id, reason="DIMINISH_AIM:" + AIM)
        ctx.engine._record_roll(roll)
        ctx.engine._append_event("CHECK_ROLLED", AIM, actor_id=owner.entity_id, target_ids=(actor.entity_id,),
                                 payload={**roll.model_dump(mode="json"), "purpose": "Diminish Aim penalty"})
        total -= int(roll.total)
        ctx.engine.__dict__["_yin_aim_penalty"] = (owner.entity_id, actor.entity_id,
                                                   int(ctx.engine.state.event_sequence))
        note(ctx.engine, AIM, owner, f"Diminish Aim: {owner.display_name} spends {actor.display_name}'s Waning Mark; "
                                     f"its attack roll is {int(roll.total)} lower.", targets=[actor])
        break
    return total or None


@hook("d20_bonus")
def diminish_native(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """Native attacks and saves use the shared d20 checkpoint; typed ones use attack_bonus/save."""
    if intent is None:
        return None
    context = engine.d20_context(roll) or {}
    action = engine.action_catalog.get(context.get("source_id"))
    if action is not None and action.resolution_kind == "TYPED":
        return None
    roller = engine.state.actors.get(getattr(roll, "actor_id", "") or "")
    if roller is None:
        return None
    if context.get("kind") == "attack":
        return _native_aim(engine, roller, engine.state.actors.get(context.get("target_id") or ""))
    if context.get("kind") == "save":
        caster = engine.state.actors.get(context.get("source_actor_id") or "")
        if caster is None or caster is roller:
            return None
        return _native_power(engine, caster, roller)
    return None


# ------------------------------------------------------------------------------------------ Diminish Power
@hook("save")
def diminish_power(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """The marked creature forces a save: one creature making it adds 1d4 (1d6 at CL 11)."""
    return _power_bonus(ctx.engine, ctx.actor, subject)


def _power_bonus(engine: Any, marked: Any, roller: Any) -> dict[str, Any] | None:
    from ..gate2_runtime_models import DiceSpec

    for owner in _owners(engine):
        if owner is marked or not _perceives(engine, owner, marked) or not _can_spend(engine, owner):
            continue
        if mark_on(marked, owner.entity_id) is None:
            continue
        if preserved(marked, owner.entity_id) and roller is not marked:
            continue  # Marked Allies: only the ally's own save is helped
        if not _ask(engine, owner, marked, "yin_diminish_power", "choice:needle.yin_diminish_power",
                    "Diminish Power: add 1d4 to the saving throw",
                    f"Diminish Power: {marked.display_name}, who bears your Waning Mark, forces a saving throw. Spend the "
                    f"mark so {roller.display_name} adds 1d{_diminish_die(engine, owner)} to its save? Once a round; no Action."
                    + _benefit_note(engine, owner, marked), want=False):
            continue
        if not _spend(engine, owner, marked, POWER, "Diminish Power"):
            continue
        die = engine.roller.roll(DiceSpec(count=1, sides=_diminish_die(engine, owner), modifier=0),
                                 actor_id=owner.entity_id, reason="DIMINISH_POWER:" + POWER)
        engine._record_roll(die)
        engine._append_event("CHECK_ROLLED", POWER, actor_id=owner.entity_id, target_ids=(marked.entity_id,),
                             payload={**die.model_dump(mode="json"), "purpose": "Diminish Power bonus"})
        note(engine, POWER, owner, f"Diminish Power: {owner.display_name} spends {marked.display_name}'s Waning Mark; "
                                   f"{roller.display_name}'s saving throw gains {int(die.total)}.", targets=[roller])
        return {"bonus": int(die.total)}
    return None


def _native_aim(engine: Any, marked: Any, target: Any) -> dict[str, Any] | None:
    from ..gate2_runtime_models import DiceSpec

    for owner in _owners(engine):
        if owner is marked or not _perceives(engine, owner, marked) or not _can_spend(engine, owner):
            continue
        if mark_on(marked, owner.entity_id) is None or preserved(marked, owner.entity_id):
            continue
        if not _ask(engine, owner, marked, "yin_diminish_aim", "choice:needle.yin_diminish_aim",
                    "Diminish Aim: subtract 1d4 from the attack roll",
                    f"Diminish Aim: {marked.display_name}, who bears your Waning Mark, makes an attack roll. Spend the mark "
                    f"to subtract 1d{_diminish_die(engine, owner)} from it? Once a round; no Action."
                    + _benefit_note(engine, owner, marked), want=False):
            continue
        if not _spend(engine, owner, marked, AIM, "Diminish Aim"):
            continue
        die = engine.roller.roll(DiceSpec(count=1, sides=_diminish_die(engine, owner), modifier=0),
                                 actor_id=owner.entity_id, reason="DIMINISH_AIM:" + AIM)
        engine._record_roll(die)
        engine._append_event("CHECK_ROLLED", AIM, actor_id=owner.entity_id, target_ids=(marked.entity_id,),
                             payload={**die.model_dump(mode="json"), "purpose": "Diminish Aim penalty"})
        engine.__dict__["_yin_aim_penalty"] = (owner.entity_id, marked.entity_id,
                                               int(engine.state.event_sequence))
        note(engine, AIM, owner, f"Diminish Aim: {owner.display_name} spends {marked.display_name}'s Waning Mark; "
                                 f"its attack roll is {int(die.total)} lower.", targets=[marked])
        return {"source_id": AIM, "bonus": -int(die.total)}
    return None


def _native_power(engine: Any, marked: Any, roller: Any) -> dict[str, Any] | None:
    answer = _power_bonus(engine, marked, roller)
    return {"source_id": POWER, "bonus": int(answer["bonus"])} if answer else None


# ------------------------------------------------------------------------------------------ Diminish Step
@hook("movement_begin")
def diminish_step(engine: Any, subject: Any, candidate: Any, intent: Any, granted_ft: int) -> None:
    """The marked creature begins movement: one Speed drops 10 feet (20 at CL 11) until this turn ends."""
    if engine.state.current_actor_id != subject.entity_id or engine._effective_speed(subject) <= 0:
        return
    from .condition_ownership import remove_instance
    from .effect_durations import token
    from ..typed_executor import Context, run_effects

    for owner in _owners(engine):
        if owner is subject or not _perceives(engine, owner, subject) or not _can_spend(engine, owner):
            continue
        if mark_on(subject, owner.entity_id) is None or preserved(subject, owner.entity_id):
            continue
        feet = 20 if int(numbers(engine, owner)["cl"]) >= 11 else 10
        if not _ask(engine, owner, subject, "yin_diminish_step", "choice:needle.yin_diminish_step",
                    "Diminish Step: reduce its Speed by 10 feet",
                    f"Diminish Step: {subject.display_name}, who bears your Waning Mark, begins moving. Spend the mark to "
                    f"reduce one of its Speeds by {feet} feet until the end of this turn? Once a round; no Action."
                    + _benefit_note(engine, owner, subject), want=False):
            continue
        if not _spend(engine, owner, subject, STEP, "Diminish Step"):
            continue
        subject.movement_remaining_ft = max(0, int(subject.movement_remaining_ft) - feet)
        inner = Context(engine, owner, engine.action_catalog.get(STEP) or next(iter(engine.action_catalog.values())),
                        intent, {"numbers": numbers(engine, owner), "effects": []}, [subject], subject, {})
        run_effects(inner.with_source(STEP),
                    [{"type": "speed", "applies_to": "target", "flat": -feet, "duration": "until_end_of_turn"}])
        note(engine, STEP, owner, f"Diminish Step: {owner.display_name} spends {subject.display_name}'s Waning Mark; its "
                                  f"Speed is {feet} feet lower until this turn ends.", targets=[subject])
        break


@hook("technique_declared")
def diminish_step_teleport(engine: Any, user: Any, action: Any, candidate: Any, intent: Any) -> dict[str, Any] | None:
    """The marked creature begins a teleport: shorten that teleport's distance by 10 feet (20 at CL 11).

    The reply uses the shared declaration-time movement budget, which native and
    typed teleports already spend: a landing square beyond the shortened distance
    fails visibly instead of silently landing elsewhere.
    """
    from .teleport_steps import self_teleport_action
    from ..typed_executor import teleport_reach

    if not self_teleport_action(action):
        return None
    reach = teleport_reach(engine, user, action)
    if not reach:
        return None
    for owner in _owners(engine):
        if owner is user or not _perceives(engine, owner, user) or not _can_spend(engine, owner):
            continue
        if mark_on(user, owner.entity_id) is None or preserved(user, owner.entity_id):
            continue
        feet = 20 if int(numbers(engine, owner)["cl"]) >= 11 else 10
        if not _ask(engine, owner, user, "yin_diminish_step_teleport", "choice:needle.yin_diminish_step",
                    "Diminish Step: shorten its teleport by 10 feet",
                    f"Diminish Step: {user.display_name}, who bears your Waning Mark, begins a teleport. Spend the mark "
                    f"to reduce that teleport's distance by {feet} feet? Once a round; no Action."
                    + _benefit_note(engine, owner, user), want=False):
            continue
        if not _spend(engine, owner, user, STEP, "Diminish Step"):
            continue
        note(engine, STEP, owner, f"Diminish Step: {owner.display_name} spends {user.display_name}'s Waning Mark; "
                                  f"its teleport is {feet} feet shorter.", targets=[user])
        return {"source_id": STEP, "label": f"Diminish Step: the teleport is {feet} feet shorter",
                "movement_cap_ft": max(0, int(reach) - feet)}
    return None


# ------------------------------------------------------------------------------------------ Diminish Readiness
@hook("reaction_resolved")
def diminish_readiness(engine: Any, event: Any) -> None:
    """The marked creature takes a Reaction: it cannot take Reactions until the start of its next turn."""
    if getattr(event, "event_type", None) != "REACTION_RESOLVED":
        return
    reactor = engine.state.actors.get(getattr(event, "actor_id", None) or "")
    if reactor is None or not reactor.active:
        return
    source = str(getattr(event, "source_definition_id", "") or "")
    if source in (AIM, POWER, STEP, READINESS, FORCE) or source.startswith(SPEND):
        return
    action = engine.action_catalog.get(source)
    reaction_name = getattr(action, "display_name", None) or "a Reaction"
    for owner in _owners(engine):
        if owner is reactor or not _perceives(engine, owner, reactor) or not _can_spend(engine, owner):
            continue
        if mark_on(reactor, owner.entity_id) is None or preserved(reactor, owner.entity_id):
            continue
        if not _ask(engine, owner, reactor, "yin_diminish_readiness", "choice:needle.yin_diminish_readiness",
                    "Diminish Readiness: take away its Reactions",
                    f"Diminish Readiness: {reactor.display_name}, who bears your Waning Mark, takes a Reaction "
                    f"({reaction_name}). Spend the mark so it cannot take Reactions until the start of its next turn? "
                    "Once a round; no Action."
                    + _benefit_note(engine, owner, reactor), want=False):
            continue
        if not _spend(engine, owner, reactor, READINESS, "Diminish Readiness"):
            continue
        engine._apply_condition(reactor, DENIED, READINESS, owner.entity_id, expires_on="START_OF_TARGET_NEXT_TURN",
                                data={"reaction_denied": True,
                                      "label": "Diminish Readiness: cannot take Reactions until its next turn starts"})
        note(engine, READINESS, owner, f"Diminish Readiness: {owner.display_name} spends {reactor.display_name}'s Waning "
                                       "Mark; it cannot take Reactions until the start of its next turn.", targets=[reactor])
        break


def _roll_kind(reason: str) -> str:
    """Plain words for the d20 the marker is being asked about."""
    if reason.startswith("SAVE:"):
        return "a saving throw"
    if reason.startswith("ATTACK:"):
        return "an attack roll"
    if reason.startswith("CHECK:"):
        return "an ability check"
    return "a roll"


@hook("d20_mode_removed")
def readiness_cancels_advantage(engine: Any, request: Any, intent: Any) -> list[str] | None:
    """The printed Readiness trigger names any roll: cancel that roll's Advantage before the die is drawn.

    The shared pre-draw checkpoint already holds the resolved mode, so one answer
    covers attack rolls, saving throws and ability checks without a per-kind branch.
    """
    if str((request or {}).get("mode") or "") != "ADVANTAGE":
        return None
    roller = engine.state.actors.get(str((request or {}).get("actor_id") or ""))
    if roller is None or not roller.active:
        return None
    what = _roll_kind(str((request or {}).get("reason") or ""))
    for owner in _owners(engine):
        if owner is roller or not _perceives(engine, owner, roller) or not _can_spend(engine, owner):
            continue
        if mark_on(roller, owner.entity_id) is None or preserved(roller, owner.entity_id):
            continue
        if not _ask(engine, owner, roller, "yin_diminish_readiness", "choice:needle.yin_diminish_readiness",
                    "Diminish Readiness: cancel its Advantage",
                    f"Diminish Readiness: {roller.display_name}, who bears your Waning Mark, would gain Advantage on "
                    f"{what}. Spend the mark to cancel it? Once a round; no Action."
                    + _benefit_note(engine, owner, roller), want=False):
            continue
        if not _spend(engine, owner, roller, READINESS, "Diminish Readiness"):
            continue
        note(engine, READINESS, owner, f"Diminish Readiness: {owner.display_name} spends {roller.display_name}'s Waning "
                                       f"Mark; its Advantage on {what} is cancelled.", targets=[roller])
        return ["ADVANTAGE"]
    return None
