"""Scoundrel talents whose printed effect the table still handed to the GM (AUTO11, round 24 lane, 2026-10-04).

Scope is the printed text in ``APP/authority/typed_mechanics/rules_text.json`` for the Scoundrel Sphere. Each talent below
names its own printed lines and the seam that now runs them. The shared choice, Martial Focus and duration helpers are the
public ones (combat/ext/needle.py, combat/ext/effect_durations.py); nothing here reads another plug-in's private state.

  Bob and Weave (TAL_SCOUNDREL_BOB_AND_WEAVE)
    "Requirement: One willing adjacent ally or one adjacent object must plausibly cover at least half your body. / Choose one
    qualifying ally or object as your cover anchor. You gain Half Cover while you remain adjacent to that anchor and it remains
    capable of plausibly covering at least half your body. / The benefit ends early if you are no longer adjacent to the chosen
    anchor, the anchor is destroyed or removed, or it can no longer plausibly cover at least half your body. You cannot change
    the chosen anchor without using Bob and Weave again. / The chosen ally spends no action and gains no benefit."
    ``cover_anchor`` asks which adjacent creature is the anchor, that creature is asked whether it agrees, and the fighter
    confirms that it can really cover half of them -- the printed Requirement, asked rather than assumed -- and files it as
    a condition. ``half_cover`` is a ``directional_cover`` provider, so the Half Cover reaches every attack that crosses a
    sight line (melee and ranged alike) and stops the moment the anchor is no longer adjacent, is gone, or is Incapacitated
    (it can no longer stand in it). The anchor spends no Action and gains nothing: the provider answers only for the creature
    that paid for the talent, and re-using the talent is the only way to change the anchor.
    An adjacent OBJECT is not offerable: this table keeps loose objects as an item's dropped_at square on the creature that
    dropped it (combat/carry.py), not as a free-standing anchor, so that half of the Requirement stays with the GM (rider).
  Quick Thievery (TAL_SCOUNDREL_QUICK_THIEVERY)
    "Expend Martial Focus to use Dirty Trick or Steal as a Bonus Action. / Use Quick Thievery only once per turn."
    ``quick_thievery_actions`` publishes one Bonus Action per printed ability, at that ability's own range, priced at 1
    Martial Focus and offered at most once a turn. ``rerun_ability_option`` runs that ability itself -- its own option menu
    for Dirty Trick, its own single Scoundrel Check for Steal -- with the rerun ability's own typed row, so its printed
    results, saves, riders and Difficult-Object branch are the ability's own and not the twin's.
  Impossible Fastening (TAL_SCOUNDREL_IMPOSSIBLE_FASTENING)
    "When a physical Dirty Trick you impose would end at the start of your next turn, expend Martial Focus to extend it to 1
    minute." ``impossible_fastening`` answers the general ``condition_state`` seam with a 1-minute clock for a hindrance a
    Dirty Trick lands, and never for Prone or Exploited Opening, exactly as printed. It records which hindrance it extended;
    ``fastening_marker`` consumes that one record, so no other condition picked up the undo.
  Master Thief (TAL_SCOUNDREL_MASTER_THIEF)
    "When you use Steal, expend Martial Focus to ignore Disadvantage caused by an object being securely fastened, worn
    tightly, or held in two hands." ``waive_steal_disadvantage`` answers the ``steal_check_waiver`` seam the Scoundrel Check
    in combat/ext/tabik_scoundrel.py consults before it rolls, and is asked only when the object actually chosen is one of
    those three kinds of object, so the Focus is never spent against a Disadvantage that was not printed. Master Thief does
    not widen what Steal can reach: its own last printed line ("Master Thief does not make ... a complete suit of worn
    armor ordinarily accessible") is what ``_unreachable`` reads, so a worn suit of armor is out of an ordinary Steal's
    menu for a thief with this talent exactly as it is for one without it. Only Steal Equipment's printed list names
    "suit of armor", so only Steal Equipment offers one.
  Filthy Distraction (TAL_SCOUNDREL_FILTHY_DISTRACTION)
    "it has Disadvantage on Wisdom (Perception) checks until the end of your next turn. / Its Passive Perception is reduced by
    5 for the same duration." ``filthy_distraction`` (called by tabik_scoundrel's own success) files a real condition carrying
    the Perception check mode -- that skill only, not every Wisdom check -- and ``filthy_passive_perception`` reports the -5
    through the shared ``passive_perception`` bonus every Passive Perception reader already consults. Both halves last the
    same printed duration, until the end of the thief's next turn (``end_of_your_next_turn``).
    The Dirty Trick hindrances in the same check end at the start of the thief's next turn.
  Steal (TAL_SCOUNDREL_STEAL) and Steal Equipment (TAL_SCOUNDREL_STEAL_EQUIPMENT)
    "Choose one accessible object. Attempt to take it, reposition it, or plant one Tiny object in an accessible location." /
    "...Make your check with Disadvantage if the object is securely fastened, worn tightly, held in two hands, or similarly
    difficult to remove. / Success: Choose one appropriate result: take the object into a free hand; cause the object to fall
    into an unoccupied space within your reach; reposition the object to another accessible location on the same target;
    plant one Tiny object in an accessible location on the target."
    ``steal_object_choice`` answers the ``scoundrel_object_choice`` seam combat/ext/tabik_scoundrel.py opens before the Scoundrel
    Check rolls -- the printed object comes FIRST, because it is what the printed difficulty and the printed result both
    depend on -- and hands back the chosen object plus the effect rows that move it. ``difficult_to_remove`` is the printed
    Disadvantage for that object; ``transfer_object`` is the printed result, recorded the way this table records gear: ONE
    record per object, filed on the creature whose bundle lists it (that is what combat/carry.py reweighs from and what
    gives the object its name), saying ``held_by`` and the hand it went into (a hand is a hand, so
    ``stolen_object_hands`` reports it to the shared hand model), or combat/carry.py's own DROPPED record with
    ``dropped_at`` for a square. ``_transfer_record`` moves that one record on every later handover, so an object has one
    home at a time and its own ``owner``/``item_name`` identity travels with it. Which object is being moved is decided
    by ``object_id`` -- the creature whose bundle lists it, and the item it is there -- and never by the item key alone,
    so two identical things in one fight (a thief's own pack and the pack they just took) are two objects, each with its
    own record, and one can never take the other's. The printed limits are enforced, not only
    described: one object (two with Cleaned Out's "up to two accessible objects instead of one"), Steal Equipment's one worn
    item alone (it removes, so it never plants and never takes two), a planted object that really is Tiny
    (``_tiny_enough`` asks, because this table keeps no item sizes), and "take nothing" or a decline meaning nothing is
    taken -- the check is still made, but no object moves and the table's own default disarm does not happen instead.
    With ``object_locations`` sealed in the effect, repositioning and planting choose an accessible carried
    location or a free hand. Owned weapons use journaled equipment readiness; owned shields use the
    shared inventory location for occupancy and permission; ordinary objects and received equipment use the transfer hand record. Without that opt-in, the legacy object choices stay unchanged.

Every hook returns early unless the creature owns the row (its bundle's ``scoundrel_talent`` passive kinds,
combat/rules/feature_blocks.d/auto11_scoundrel.json), so a fighter without these talents sees no change at all.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any

from . import effect, hook
from . import effect_durations
from . import needle

FOCUS = needle.FOCUS  # "resource:core.martial_focus"
BLOCK = "scoundrel_talent"
BOB, QUICK, FASTENING, MASTER = "bob_and_weave", "quick_thievery", "impossible_fastening", "master_thief"
EQUIPMENT = "steal_equipment"  # Steal Equipment: the same check, spent, for one worn thing instead of a weapon
FILTHY = "filthy"  # tabik.json already compiles Filthy Distraction under this kind
BOB_ID = "TAL_SCOUNDREL_BOB_AND_WEAVE"
QUICK_ID = "TAL_SCOUNDREL_QUICK_THIEVERY"
FASTENING_ID = "TAL_SCOUNDREL_IMPOSSIBLE_FASTENING"
MASTER_ID = "TAL_SCOUNDREL_MASTER_THIEF"
EQUIPMENT_ID = "TAL_SCOUNDREL_STEAL_EQUIPMENT"
FILTHY_ID = "TAL_SCOUNDREL_FILTHY_DISTRACTION"
STEAL_ID = "TAL_SCOUNDREL_STEAL"  # the ability whose own check this menu rides; Cleaned Out / Switcheroo name it
EQUIPMENT_ACTION = "steal_equipment"  # the action id suffix steal_equipment_actions compiles
QUICK_LABEL = "Quick Thievery"
QUICKED = ("TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_STEAL")  # the two abilities its printed text names
ANCHOR = "condition:typed.bob_and_weave_anchor"
FILTHY_CONDITION = "condition:typed.filthy_distraction"
FASTENING_MARK = "condition:typed.impossible_fastening"  # names the hindrance instances a Utilize action undoes
CHOICE = "choice:scoundrel."
COVER = 2  # Half Cover: the same number combat/ext/shield_faces.py's own faces and a Court's allies give
ADJACENT_FT = 5
ONE_MINUTE = 10  # rounds; the shared rules data counts 1 minute as 10 rounds (combat/ext/effect_durations.py)
FILTHY_PENALTY = 5
# "Impossible Fastening cannot extend Prone or Exploited Opening."
NEVER_EXTENDED = {"prone", "exploited_opening"}
EXTENDING = "impossible_fastening_extending"  # turn flag naming the exact hindrance being extended, consumed on use
TAKE, FALL, PLANT = "take", "fall", "plant"
REPOSITION = "reposition"  # the printed "take into a free hand" / "fall into an unoccupied space" / "plant"
NOTHING = "nothing"  # "take nothing": the check still happens, the table's own default object does
DISARMED = "condition:typed.disarmed"


def _register_utilize() -> None:
    """Reuse the table's existing Utilize action for the printed line that lets a creature undo the fastening by hand.

    "The target or an adjacent creature can take the Utilize action to end the hindrance early by undoing the knot, clearing
    the eyes, loosening the strap, removing the object, or otherwise solving the physical problem." No check is printed, and the
    helper need not be an ally, so this ending takes ANY_CREATURE (the same action, the same 5 feet, one per marker).
    """
    from . import utilize_end

    utilize_end.register_ending("scoundrel_fastening", {
        "marker": FASTENING_MARK, "self": True, "check": None, "target_kind": "ANY_CREATURE",
        "label": "Undo the fastening (hindrance from a Dirty Trick)",
        "describe": "Utilize: the target, or any creature within 5 feet of it, undoes the knot, clears the eyes, loosens the "
                    "strap or removes the object. The hindrance a Dirty Trick imposed ends."})


_register_utilize()



def owns(engine: Any, actor: Any, kind: str) -> bool:
    """Whether this creature's own compiled bundle carries the Scoundrel talent of this kind."""
    rows = (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
    return any(row.get("block") == BLOCK and row.get("kind") == kind for row in rows)


def _answering_for_itself(engine: Any, creature: Any) -> bool:
    """Whether nobody is answering for this creature, so its own controller picks (checklist 9: an AI actor decides)."""
    return (getattr(engine, "typed_control_modes", None) or {}).get(creature.entity_id) == "LOCAL_AUTO"


# ------------------------------------------------------------------------------------- Bob and Weave: Half Cover
def _talents(engine: Any, actor: Any) -> set[str]:
    """The Scoundrel talents this creature owns, by kind (the same row owns() reads)."""
    return {str(row.get("kind")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind")}


def _stands(engine: Any, anchor: Any) -> bool:
    """"it remains capable of plausibly covering at least half your body": an anchor that can still stand in it.

    A creature that is gone, defeated or Incapacitated cannot cover anything; everything else is a question of
    how big it is, which the printed text leaves as "plausibly" and this table has no size read for, so the
    fighter confirms it at the question below.
    """
    if not anchor.active or anchor.life_state is not None:
        return False
    from . import needle

    return not needle.incapacitated(anchor)


def _anchor(engine: Any, creature: Any) -> Any | None:
    """The creature named as the Bob and Weave anchor, while it can still cover the bearer.

    "The benefit ends early if you are no longer adjacent to the chosen anchor, the anchor is destroyed or
    removed, or it can no longer plausibly cover at least half your body": this
    observational query checks adjacency and standing. In new fights the event
    hook removes the anchor condition permanently on the first such loss; old
    saves retain their original live-adjacency behavior.
    """
    condition = next((row for row in creature.conditions.values()
                      if row.condition_id == ANCHOR and row.source_actor_id == creature.entity_id), None)
    if condition is None:
        return None
    anchor = engine.state.actors.get(str((condition.data or {}).get("anchor") or ""))
    if anchor is None or not _stands(engine, anchor):
        return None
    return anchor if engine._distance_actor_to_actor(creature, anchor) <= ADJACENT_FT else None


@hook("match_start")
def record_cover_expiry_policy(engine: Any) -> None:
    for event in engine.events:
        if event.event_type == "MATCH_CREATED":
            event.payload["cover_anchor_expiry_policy"] = 1
            return


@hook("event", nested=True)
def end_cover_anchor(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Printed early expiry is final; unstamped saves retain live-adjacency cover."""
    if event_type not in {"MOVEMENT_COMMITTED", "CONDITION_APPLIED", "DAMAGE_COMMITTED", "ENTITY_DEFEATED", "ACTOR_DEFEATED", "SUMMON_DISMISSED"}:
        return
    bearers = [actor for actor in engine.state.actors.values()
               if any(row.condition_id == ANCHOR for row in actor.conditions.values())]
    if not bearers or not any(event.event_type == "MATCH_CREATED" and
                             event.payload.get("cover_anchor_expiry_policy") == 1 for event in engine.events):
        return
    for actor in bearers:
        # A previous removal may dispatch child events. Recheck the snapshot
        # before removing; CONDITION_REMOVED itself is deliberately unwatched.
        if not any(row.condition_id == ANCHOR for row in actor.conditions.values()):
            continue
        anchor = _anchor(engine, actor)
        lost = anchor is None
        if anchor is not None and event_type == "MOVEMENT_COMMITTED":
            # A route can leave and return beside the anchor before its one
            # movement event. Early expiry also applies to intermediate cells.
            from ..gate2_runtime_models import Position
            mover_id = kwargs.get("actor_id")
            for cell in (kwargs.get("payload") or {}).get("path") or []:
                if mover_id == actor.entity_id:
                    projected = actor.model_copy(update={"position": Position.model_validate(cell)})
                    lost = engine._distance_actor_to_actor(projected, anchor) > ADJACENT_FT
                elif mover_id == anchor.entity_id:
                    projected = anchor.model_copy(update={"position": Position.model_validate(cell)})
                    lost = engine._distance_actor_to_actor(actor, projected) > ADJACENT_FT
                if lost:
                    break
        if lost:
            engine._remove_condition(actor, ANCHOR, BOB_ID)


@effect("cover_anchor")
def cover_anchor(ctx: Any, eff: dict[str, Any]) -> None:
    """Name the adjacent ally that covers the bearer, as the printed Requirement demands, and hold it until its next turn.

    Three printed things are asked rather than assumed: which adjacent ally, whether that ally agrees ("one willing
    adjacent ally"), and whether it really can cover half your body ("must plausibly cover at least half your body").
    An AI ally agrees to an ally of its own and refuses an enemy; with nobody answering, nothing is filed.
    """
    engine, actor = ctx.engine, ctx.actor
    intent = ctx.intent or getattr(engine, "_active_intent", None)
    adjacent = sorted((other for other in engine.state.actors.values()
                       if other.active and other.life_state is None and other.team_id == actor.team_id
                       and other.entity_id != actor.entity_id
                       and engine._distance_actor_to_actor(actor, other) <= ADJACENT_FT),
                      key=lambda other: other.entity_id)
    if not adjacent:
        ctx.rider("Bob and Weave: " + actor.display_name + " is not standing beside an ally, so nothing is covering them. "
                  "An adjacent object can be the anchor only if the table places one beside them.")
        return
    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "BOB_AND_WEAVE", actor.entity_id), actor,
                        CHOICE + "bob_and_weave", [other.entity_id for other in adjacent],
                        labels={other.entity_id: other.display_name for other in adjacent},
                        name="Bob and Weave", feature_id=BOB_ID, target_id=actor.entity_id,
                        automatic=_answering_for_itself(engine, actor),
                        prompt="Bob and Weave: choose the ally standing beside you who covers you. It must be willing, "
                               "and it must be able to cover at least half your body. You gain Half Cover (+2 to your "
                               "Armor Class against every attack) until the start of your next turn, and only while you "
                               "are still standing beside that ally.")
    anchor = next((other for other in adjacent if other.entity_id in chosen), None)
    if anchor is None:
        return
    agrees = needle.ask(engine, intent, needle.checkpoint_id(engine, "BOB_AND_WEAVE_CONSENT", anchor.entity_id), anchor,
                        CHOICE + "bob_and_weave_willing", ["accept", "refuse"],
                        labels={"accept": "Yes, I will cover " + actor.display_name + " while we stand together",
                                "refuse": "No, I will not cover " + actor.display_name},
                        preferred=["accept"] if anchor.team_id == actor.team_id else ["refuse"],
                        name="Bob and Weave: " + anchor.display_name + " is willing", feature_id=BOB_ID,
                        target_id=anchor.entity_id, automatic=_answering_for_itself(engine, anchor),
                        prompt="Bob and Weave: " + actor.display_name + " is using you as their cover anchor. "
                               "Covering them costs you no action and gains you nothing. Do you agree?")
    if "accept" not in agrees:
        return
    covers = needle.ask(engine, intent, needle.checkpoint_id(engine, "BOB_AND_WEAVE_COVERS", anchor.entity_id), actor,
                        CHOICE + "bob_and_weave_covers", ["yes", "no"],
                        labels={"yes": "Yes, " + anchor.display_name + " covers half of " + actor.display_name + "'s body",
                                "no": "No, it cannot cover half of " + actor.display_name + "'s body"},
                        name="Bob and Weave: can it cover you", feature_id=BOB_ID, target_id=anchor.entity_id,
                        automatic=_answering_for_itself(engine, actor),
                        prompt="Bob and Weave: can " + anchor.display_name + " plausibly cover at least half of "
                               + actor.display_name + "'s body? The printed talent needs one willing adjacent ally or "
                               "object that really does.")
    if "yes" not in covers:
        ctx.rider("Bob and Weave: " + anchor.display_name + " cannot cover half of " + actor.display_name
                  + "'s body, so the printed Requirement is not met and nothing is covering them.")
        return
    engine._apply_condition(actor, ANCHOR, ctx.source, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                            data={"anchor": anchor.entity_id,
                                  "label": f"Bob and Weave: {anchor.display_name} covers them (+2 AC against every attack) "
                                           f"until the start of their next turn"})


@hook("directional_cover")
def half_cover(engine: Any, attacker: Any, target: Any, ray: dict[str, Any]) -> int | None:
    """Bob and Weave's Half Cover, for as long as its anchor is still beside the bearer and can still cover it."""
    entity = getattr(target, "entity_id", None)
    if not entity or _anchor(engine, target) is None:
        return None
    return COVER


# ------------------------------------------------------------------------------------- Quick Thievery: a Bonus Action twin
def _ability_label(mechanics: dict[str, Any], ability: str) -> str:
    record = mechanics.get(ability) or {}
    printed = " ".join(str(record.get("name") or ability).split())
    return " ".join(word.capitalize() if word.isupper() else word for word in printed.split())


@lru_cache(maxsize=1)
def _printed_names() -> dict[str, str]:
    """The typed authority's own display name for every mechanic id (the file combat/factory_compiler.py reads)."""
    import json

    from ..factory_compiler import TYPED_AUTHORITY

    try:
        mechanics = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
    except (OSError, ValueError, KeyError):  # an unreadable authority never stops a fight; names fall back
        return {}
    return {key: " ".join(str(row.get("name") or "").split()) for key, row in mechanics.items()}


def printed_name(ability: str) -> str:
    """"Steal", "Dirty Trick": the ability's own printed name, never an internal id in a player's menu.

    Read from the typed authority, the same source the compile_actions twin names its buttons from; an id the
    authority does not carry falls back to its last word, so a player still never reads "TAL_SCOUNDREL_STEAL".
    """
    printed = _printed_names().get(str(ability), "")
    return " ".join(word.capitalize() if word.isupper() else word for word in printed.split()) \
        or str(ability).split("_")[-1].capitalize()


def _ability_option_rows(engine: Any, actor: Any, ability: str) -> list[dict[str, Any]]:
    """One row per printed result this creature's own compiled options give that ability ("Success: Choose one")."""
    options: list[dict[str, Any]] = []
    for action in engine.action_catalog.values():
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or str(typed.get("option_of") or "") != ability or not typed.get("option_label"):
            continue
        if not any(row["label"] == typed["option_label"] for row in options):
            options.append({"label": str(typed["option_label"]), "effects": copy.deepcopy(typed.get("effects") or [])})
    return options


def _ability_body(engine: Any, actor: Any, ability: str) -> dict[str, Any] | None:
    """The ability's own compiled typed row, the one whose effects it resolves with (Steal, not its options)."""
    for action in engine.action_catalog.values():
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id == actor.entity_id and str(typed.get("source") or "") == ability and typed.get("effects"):
            return copy.deepcopy(typed)
    return None


@hook("compile_actions")
def quick_thievery_actions(info: dict[str, Any]) -> list[Any] | None:
    """One Bonus Action for each ability Quick Thievery names, at that ability's own printed range, for 1 Martial Focus.

    The twin carries no effect of its own beyond asking for the ability's own result menu (``rerun_ability_option``), so
    the printed results, their saves and their riders all stay the ability's own.
    """
    if QUICK_ID not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    abilities: dict[str, dict[str, Any]] = {}
    for action in info.get("actions") or ():
        typed = (action.parameters or {}).get("typed") or {}
        ability = str(typed.get("option_of") or typed.get("source") or "")
        if ability not in QUICKED:
            continue
        spec = abilities.setdefault(ability, {"range_ft": 0, "base": action})
        spec["range_ft"] = max(int(spec["range_ft"]), int(action.range_ft or 0))
    out = []
    for ability, spec in abilities.items():
        label = _ability_label(info.get("mechanics") or {}, ability)
        typed = {"effects": [{"type": "rerun_ability_option", "ability": ability,
                              "evidence": f"{label}, used as a Bonus Action by spending 1 Martial Focus"}],
                 "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": QUICK_ID}
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.quick_thievery.{ability.split('_')[-1].lower()}",
            display_name=f"{label} ({QUICK_LABEL}: Bonus Action)", owner_id=info["actor_id"],
            economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind=spec["base"].target_kind,
            range_ft=spec["range_ft"] or None, radius_ft=spec["base"].radius_ft, costs=((FOCUS, 1),),
            parameters={"typed": typed, "expected_damage": 0, "quick_thievery": True, "ability": ability}))
    return out or None


@hook("candidate_allowed")
def quick_thievery_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """\"Use Quick Thievery only once per turn\", and never offered without the Martial Focus it costs."""
    if not (getattr(action, "parameters", None) or {}).get("quick_thievery"):
        return None
    if actor.turn_flags.get("quick_thievery_turn") == actor.turns_started:
        return False
    return None if actor.resources.get(FOCUS, 0) >= 1 else False


@hook("action_completed")
def quick_thievery_spent(engine: Any, actor: Any, economy: Any, source_definition_id: str) -> None:
    if ".quick_thievery." in str(source_definition_id):
        actor.turn_flags["quick_thievery_turn"] = actor.turns_started


@effect("rerun_ability_option")
def rerun_ability_option(ctx: Any, eff: dict[str, Any]) -> None:
    """\"Expend Martial Focus to use Dirty Trick or Steal as a Bonus Action\": run that ability itself.

    Dirty Trick is compiled as its own result menu, so its options are asked and one is run; Steal is a single
    Scoundrel Check with no options, so its own typed row runs whole. Either way the effects run under THAT
    ability's own typed row (its source, its numbers, its own printed source- and object-gates), so Impossible
    Fastening and Steal's own object choice recognise the rerun, while the triggering action stays the Bonus
    Action twin -- its cost, economy and chosen target are untouched.
    """
    engine, actor = ctx.engine, ctx.actor
    ability = str(eff.get("ability") or "")
    options = _ability_option_rows(engine, actor, ability)
    body = _ability_body(engine, actor, ability)
    if not options and body is None:
        return
    target = ctx.target or next(iter(ctx.targets or []), None)
    if target is None or not target.active:
        return
    if options:
        label = printed_name(ability)
        chosen = needle.ask(engine, ctx.intent or getattr(engine, "_active_intent", None),
                            needle.checkpoint_id(engine, "QUICK_THIEVERY", actor.entity_id, ability), actor,
                            CHOICE + "quick_thievery", [row["label"] for row in options],
                            labels={row["label"]: f"{label}: {row['label']} against {target.display_name}" for row in options},
                            name=f"{QUICK_LABEL}: {printed_name(ability)}", feature_id=QUICK_ID,
                            target_id=target.entity_id, automatic=_answering_for_itself(engine, actor),
                            prompt=f"{QUICK_LABEL}: spend 1 Martial Focus to use {printed_name(ability)} as a Bonus Action. "
                                   f"Choose the result your {printed_name(ability)} has against {target.display_name}.")
        row = next((item for item in options if item["label"] in chosen), None)
        if row is None:
            return
        effects, typed = row["effects"], body or {}
    else:
        effects, typed = (body or {}).get("effects") or [], body or {}
    # The rerun belongs to the ability being used, not to the twin: its own source, its own numbers, its own gates.
    typed = {**(ctx.typed or {}), **(typed or {}), "source": ability}
    from .. import typed_executor

    typed_executor.run_effects(typed_executor.Context(engine, actor, ctx.action, ctx.intent, typed, [target], target, {}),
                               effects)


# ------------------------------------------------------------------------------------- Impossible Fastening: a longer hindrance
@hook("condition_state")
def impossible_fastening(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> dict[str, Any] | None:
    """"When a physical Dirty Trick you impose would end at the start of your next turn, expend Martial Focus to extend it
    to 1 minute." Asks, spends the Focus, records which exact hindrance it extended for ``fastening_marker`` to consume, and
    hands the longer clock back through the shared condition_state seam."""
    engine, actor = ctx.engine, ctx.actor
    name = str(effect_row.get("condition") or "").strip().lower().removeprefix("condition:typed.")
    if name in NEVER_EXTENDED or "DIRTY_TRICK" not in str(ctx.typed.get("source") or ctx.source or "").upper():
        return None
    if str(effect_row.get("expires_on") or "") != "START_OF_SOURCE_NEXT_TURN":
        return None
    if not owns(engine, actor, FASTENING) or actor.resources.get(FOCUS, 0) < 1:
        return None
    chosen = needle.ask(engine, ctx.intent or getattr(engine, "_active_intent", None),
                        needle.checkpoint_id(engine, "IMPOSSIBLE_FASTENING", actor.entity_id, name), actor,
                        CHOICE + "impossible_fastening", ["extend"],
                        labels={"extend": "Keep this hindrance for 1 minute (spend 1 Martial Focus)"},
                        allow_decline=True, default="decline",  # "expend Martial Focus to extend it": spending is a choice
                        name="Impossible Fastening", feature_id=FASTENING_ID, target_id=subject.entity_id,
                        automatic=_answering_for_itself(engine, actor),
                        prompt=f"Impossible Fastening: {subject.display_name} is {name.replace('_', ' ')}. Spend 1 Martial Focus "
                               f"to keep that hindrance for 1 minute instead of until the start of your next turn?")
    if not chosen:
        return None
    needle.spend_focus(engine, actor, FASTENING_ID, "Impossible Fastening")
    # condition_applied consumes this immediately: only the hindrance this question was about may be undone by hand.
    actor.turn_flags[EXTENDING] = f"{subject.entity_id}|{name}"
    return {"expires_on": effect_durations.round_token(engine, ONE_MINUTE)}


@hook("condition_applied")
def fastening_marker(ctx: Any, name: str, subject: Any) -> None:
    """Tag the extended hindrance with the marker the printed Utilize ending looks for.

    Runs immediately after the condition it extends has landed, so the instance it names is the one this talent just made
    last for a minute. The pending record from ``impossible_fastening`` names that one condition and is consumed here, so a
    second, unextended condition on the same creature in the same turn gets no undo it never earned. Two extended hindrances
    keep ONE marker naming both instances, so the Action undoes exactly the fastenings and no other condition.
    """
    engine, actor = ctx.engine, ctx.actor
    pending = str(actor.turn_flags.pop(EXTENDING, "") or "")
    if pending != f"{subject.entity_id}|{name}":
        return
    mine = [(iid, row) for iid, row in subject.conditions.items()
            if row.condition_id == f"condition:typed.{name}" and row.source_actor_id == actor.entity_id]
    if not mine:
        return
    iid, condition = mine[-1]
    linked = [iid]
    for other_id, other in list(subject.conditions.items()):  # a snapshot: the merge below removes the old marker
        if other.condition_id != FASTENING_MARK or other.source_actor_id != actor.entity_id:
            continue
        linked.extend(str(was) for was in (other.data or {}).get("linked") or [] if str(was) not in linked)
        _remove(engine, subject, other_id, ctx.source, actor.entity_id)  # one marker, naming every fastening it undoes
    needle.timed_condition(engine, subject, FASTENING_MARK, ctx.source, actor.entity_id, condition.expires_on or "UNTIL_REMOVED",
                           {"label": f"Impossible Fastening: {subject.display_name} is {name.replace('_', ' ')} and will not shake "
                                     f"it off for 1 minute. {subject.display_name}, or any creature within 5 feet, can spend its "
                                     f"Action to undo it by hand",
                            "linked": linked})


# ------------------------------------------------------------------------------------- Master Thief: ignore the printed Disadvantage
@hook("steal_check_waiver")
def waive_steal_disadvantage(engine: Any, actor: Any, target: Any, source: str, effect_row: dict[str, Any]) -> bool | None:
    """"expend Martial Focus to ignore Disadvantage caused by an object being securely fastened, worn tightly, or held in two
    hands." True waives the printed Disadvantage for this check; the Focus is spent only when it is really waived.

    ``effect_row["object_difficult"]`` is the Scoundrel Check's own answer to "is the object you chose one of those three?".
    It is False when nothing was chosen and the table's default object is not difficult, so the question is asked -- and the
    Focus can be spent -- only against a Disadvantage the printed object actually caused.
    """
    if not effect_row.get("object_difficult") or not owns(engine, actor, MASTER) or actor.resources.get(FOCUS, 0) < 1:
        return None
    chosen = needle.ask(engine, getattr(engine, "_active_intent", None),
                        needle.checkpoint_id(engine, "MASTER_THIEF", actor.entity_id, getattr(target, "entity_id", "")),
                        actor, CHOICE + "master_thief", ["ignore"],
                        labels={"ignore": "Spend 1 Martial Focus to ignore the Disadvantage"},
                        name="Master Thief", feature_id=MASTER_ID, target_id=getattr(target, "entity_id", actor.entity_id),
                        automatic=_answering_for_itself(engine, actor), allow_decline=True, default="decline",
                        prompt=f"Master Thief: the object you chose on {getattr(target, 'display_name', 'that creature')} is worn or "
                               f"held in two hands, so the Steal check is made with Disadvantage. Spend 1 Martial Focus to ignore that?")
    if not chosen:
        return None
    needle.spend_focus(engine, actor, MASTER_ID, "Master Thief")
    return True


# ------------------------------------------------------------------------------------- Filthy Distraction: a real Perception penalty
def end_of_your_next_turn(engine: Any, creature: Any) -> str:
    """Filthy Distraction's 'your next turn' is the thief's next turn, including off-turn uses."""
    return effect_durations.token("end", creature.entity_id, int(creature.turns_started) + 1)


def filthy_distraction(ctx: Any, target: Any) -> None:
    """"it has Disadvantage on Wisdom (Perception) checks until the end of your next turn. / Its Passive Perception is reduced by
    5 for the same duration." Called by the Scoundrel Check that succeeded against a creature unaware of the thief.

    The duration belongs to the thief (``end_of_your_next_turn``), and the
    check penalty is filed under the Perception SKILL, not under Wisdom: a rule keyed on WIS would read as
    Disadvantage on every Wisdom check, which is not what the printed line says. The -5 is not filed separately:
    ``filthy_passive_perception`` reads this one condition, so both halves of the printed sentence last exactly as
    long as each other.
    """
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active:
        return
    engine._apply_condition(target, FILTHY_CONDITION, ctx.source, actor.entity_id,
                            expires_on=end_of_your_next_turn(engine, actor),
                            data={"rule": {"check_mode": {"Perception": "DISADVANTAGE"}},
                                  "label": f"Filthy Distraction: {target.display_name} has Disadvantage on Wisdom (Perception) "
                                           f"checks and 5 less Passive Perception until the end of {actor.display_name}'s next turn"})


@hook("passive_perception")
def filthy_passive_perception(engine: Any, creature: Any) -> int:
    """\"Its Passive Perception is reduced by 5 for the same duration.\" A bonus, so it lowers every reader's baseline."""
    return -FILTHY_PENALTY if _distracted(engine, creature) else 0


def _distracted(engine: Any, creature: Any) -> bool:
    return any(row.condition_id == FILTHY_CONDITION for row in creature.conditions.values())


def _remove(engine: Any, creature: Any, iid: str, source: str, actor_id: str) -> None:
    """Take off exactly one condition instance, keeping its replay identity in the log (combat/ext/condition_events)."""
    from .condition_events import drop_condition

    drop_condition(engine, creature, iid, source)


# ------------------------------------------------------------------- Steal Equipment: the same check, spent, for a worn thing
@hook("compile_actions")
def steal_equipment_actions(info: dict[str, Any]) -> list[Any] | None:
    """"Cost: Expend Martial Focus / attempt to remove one worn item ... Make the Steal check with Disadvantage.

    Steal Equipment's own modifier only types a disadvantage with free text ("on the Steal check") that no reader
    consults, so the talent compiled to nothing at all. This publishes the printed attempt as its own Action: 1 Martial
    Focus as printed, the shared Scoundrel Check with that Disadvantage as one of the roll's own sources, and the worn
    object chosen before the check, which is what that Disadvantage and the result both depend on.
    """
    if not any(row.get("block") == BLOCK and row.get("kind") == EQUIPMENT for row in info.get("passives") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    label = "Steal Equipment (take one worn thing)"
    typed = {"effects": [{"type": "steal_equipment", "applies_to": "target", "disadvantage": True,
                          "steal_object": "worn",
                          "evidence": "Attempt to remove one worn item; the Steal check is made with Disadvantage."}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": EQUIPMENT_ID}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.{EQUIPMENT_ACTION}", display_name=label, owner_id=info["actor_id"],
        economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY", range_ft=5, costs=((FOCUS, 1),),
        parameters={"typed": typed, "expected_damage": 0, "steal_equipment": True, "ability": "Steal Equipment",
                    "description": "Spend 1 Martial Focus, then attempt to take one worn thing (a belt, sash, cloak, quiver, "
                                   "scabbard, component pouch, robe, shield, helmet, worn talisman, suit of armor or "
                                   "comparable worn equipment) from a creature within reach. Choose the worn thing first, "
                                   "because the check is made against it; the check is made with Disadvantage and Master "
                                   "Thief does not remove that."})]


@effect("steal_equipment")
def steal_equipment(ctx: Any, eff: dict[str, Any]) -> None:
    """Steal Equipment's printed attempt: the shared Scoundrel Check, which asks for the worn object before it rolls.

    Nothing is handed over here: the object is chosen by ``scoundrel_object_choice`` (which this row names with
    ``steal_object``), and the transfer rows it returns run inside the check's own success branch, so a failed
    check costs the printed Martial Focus and nothing else.
    """
    from . import tabik_scoundrel

    tabik_scoundrel.scoundrel_check(ctx, {**eff, "on_success": []})


# ------------------------------------------------------------------- Steal: which object, and what happens to it
def object_id(owner_id: str, key: str) -> str:
    """One object's own name for the rest of the fight: whose bundle lists it, and the item it is there.

    Two fighters carrying the same thing are two objects, and an item key alone cannot say which: this table's bundles
    list a key, a name, a weight and whether the item is worn or a weapon, so the bundle a thing sits in is the only
    identity it has. That bundle never changes while the object's record exists (the record is what moves the object
    out of that creature's possession, not out of its bundle), so this stays the same through every handover -- and a
    fight saved before records carried it still works, because a record is filed on exactly that creature.
    """
    return f"{owner_id}|{key}"


def _record_identity(filed: Any, data: dict[str, Any]) -> str:
    """The identity a transfer record already names, or the one the creature it is filed on gives it."""
    return str(data.get("object_id") or "") or object_id(filed.entity_id, str(data.get("item_key") or ""))


def _handover_records(engine: Any, holder_id: str) -> list[tuple[Any, dict[str, Any]]]:
    """Every transfer record in the fight that says this creature has the object, as (creature filed on, record data).

    A record says who has the object; it stays filed on the creature whose bundle lists that object, which is what
    combat/carry.py reweighs from. Reading every creature's records is how a received object is found at all.
    """
    return [(creature, dict(row.data or {}))
            for creature in sorted(engine.state.actors.values(), key=lambda row: row.entity_id)
            for row in creature.conditions.values()
            if (row.data or {}).get("held_by") == holder_id]


def possessions(engine: Any, creature: Any) -> list[dict[str, Any]]:
    """Every item creature actually has on it right now, from its own bundle and from anything handed to it.

    An item lying on the ground or in someone else's hands is not here, and a weapon another creature has taken
    or knocked away is named by the action that no longer works -- both read from the conditions combat/carry.py
    reweighs from, so this is the same current possession the load sees. An item received from another creature
    is here too, so a thief can go on planting what they just took.

    A received object keeps its own identity through every handover: the record names the creature whose bundle
    lists it (``owner``) and the object's own name, so a pack planted in a stranger's hands is still that pack
    even though the stranger never carried it, and the load can still weigh it. Every row carries that identity as
    ``object``, so a creature holding two of the same thing (its own pack and the pack it took) is shown both: two
    identical items are two objects, and a record for one of them is never read as the other.
    """
    from .. import carry

    gone = {_record_identity(creature, row.data or {}) for row in creature.conditions.values()
            if (row.data or {}).get("dropped_at") or (row.data or {}).get("held_by")}
    # Only a real weapon identity can be "disabled": an ordinary object has no weapon action, and treating its empty
    # identity as disabled would hide every ordinary thing on the creature.
    disabled = {str((row.data or {}).get("disables_action") or "").split("#")[0]
                for row in creature.conditions.values() if (row.data or {}).get("disables_action")}
    held = [{**dict(item), "object": object_id(creature.entity_id, str(item.get("key") or ""))}
            for item in ((carry.carrying_of(engine, creature.entity_id) or {}).get("items") or [])
            if str(item.get("key") or "") and object_id(creature.entity_id, str(item.get("key") or "")) not in gone
            and (not str(item.get("weapon_action") or "")
                 or str(item.get("weapon_action")).split("#")[0] not in disabled)]
    seen = {str(row.get("object") or "") for row in held}
    for filed, data in _handover_records(engine, creature.entity_id):
        key, identity = str(data.get("item_key") or ""), _record_identity(filed, data)
        if not key or identity in seen or carry.external_item_location(data):
            continue
        source = engine.state.actors.get(str(data.get("owner") or "")) or filed
        item = carry.item_of(carry.carrying_of(engine, source.entity_id), key=key)
        held.append({**(dict(item) if item is not None
                          else {"key": key, "name": str(data.get("item_name") or "object"), "kind": "item"}),
                     "object": identity,
                     **({"location": data["object_location"], "worn": False}
                        if data.get("object_location") else {})})
        seen.add(identity)
    return held


def held_possessions(engine: Any, creature: Any) -> list[dict[str, Any]]:
    """Current possessions whose exact physical identity occupies a hand.

    Equipment occupants name owned shields/weapon actions, while transferred
    objects name their recorded part. A bare inventory key in that part cannot
    admit a different owner's copy, or a copy recorded in storage. This is a
    pure query over the public equipment model and the existing transfer ledger.
    """
    from . import hand_occupancy

    occupied = hand_occupancy.occupancy(engine, creature)
    hands = {value for occupants in occupied.values() for value in occupants}
    recorded = {}
    for filed, data in _handover_records(engine, creature.entity_id):
        part, key = str(data.get('hand') or ''), str(data.get('item_key') or '')
        if f'object:{key}' in occupied.get(part, ()):
            recorded[_record_identity(filed, data)] = part
    out = []
    for item in possessions(engine, creature):
        identity = str(item['object'])
        owned = identity == object_id(creature.entity_id, str(item['key']))
        if (identity in recorded or (owned and
                (f"weapon:{item.get('weapon_action')}" in hands or f"shield:{item['key']}" in hands))):
            out.append(item)
    return out


def drop_held_object(engine: Any, holder: Any, item: dict[str, Any], *, source: str, by: Any) -> bool:
    """Drop one exact held identity at the holder's feet, including borrowed gear.

    Public forced-drop adapter for commands. Protection and real hand occupancy
    are rechecked; the ordinary transfer ledger owns identity and encumbrance.
    """
    from .. import carry

    identity = str(item.get("object") or "")
    current = next((row for row in held_possessions(engine, holder)
                    if row.get("object") == identity), None)
    if current is None or any(current.get(flag) for flag in
            ("artifact", "soul_bound", "fused", "protected", "sealed")):
        return False
    key = str(current["key"])
    filed, iid = _transfer_record(engine, identity, key, holder)
    data = {"item_key": key, "item_name": current.get("name") or "object",
            "owner": filed.entity_id, "object_id": identity,
            "dropped_at": holder.position.model_dump(mode="json")}
    if current.get("weapon_action"):
        data["disables_action"] = current["weapon_action"]
    _rehome(engine, filed, iid, data, source=source, actor_id=by.entity_id,
            condition_id=carry.DROPPED)
    for creature in engine.state.actors.values():
        carry.refresh(engine, creature, source)
    note(engine, source, by, f"{holder.display_name} drops {data['item_name']} at its feet.", (holder.entity_id,))
    return True


def difficult_to_remove(engine: Any, item: dict[str, Any]) -> bool:
    """"securely fastened, worn tightly, or held in two hands": what makes the printed Steal check Disadvantage.

    An item its wearer has on is fastened or worn tightly, and a two-handed weapon is held in two hands. This
    table has no fastener flag, so an object that is "similarly difficult to remove" for some other reason stays
    the GM's, exactly as before.
    """
    if item.get("worn"):
        return True
    action = engine.action_catalog.get(str(item.get("weapon_action") or ""))
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    return "two-handed" in str((typed.get("weapon") or {}).get("properties") or "").lower()


def _unreachable(engine: Any, actor: Any, item: dict[str, Any], *, paid_equipment: bool = False) -> bool:
    """"Master Thief does not make a soul-bound object, artifact, body part, or complete suit of worn armor
    ordinarily accessible."

    A whole suit of worn armor is not an ordinary accessible object for anybody who has only Steal: Master Thief's
    own last printed line says it does not make one accessible, and the talent before it spends Martial Focus on
    Disadvantage and nothing else. Only Steal Equipment's own printed list reaches for a suit of armor ("suit of
    armor"; "At Core Formation, stealing a complete suit of armor is intentionally possible"). Smaller worn
    things are merely difficult to remove, not inaccessible.
    """
    return bool(item.get("worn")) and str(item.get("kind") or "") == "armor" and not paid_equipment


@hook("scoundrel_object_choice")
def steal_object_choice(engine: Any, actor: Any, target: Any, source: str, effect_row: dict[str, Any]) -> dict[str, Any] | None:
    """Steal and Steal Equipment's printed "Choose one accessible object", asked before the check it belongs to.

    Returns what the Scoundrel Check in combat/ext/tabik_scoundrel.py needs: whether the object it chose is a
    difficult one (the printed Disadvantage, and the only thing Master Thief may waive), and the rows that move
    it -- which that check runs only on a success.

    Three printed limits are enforced here rather than only described to the player:

    * the allowance is the printed one -- one object, or two with Cleaned Out ("up to two accessible objects
      instead of one"), and never more than the one worn item Steal Equipment prints ("attempt to remove one
      worn item ... the object appears in your free hand or one legal unoccupied space");
    * a planted object really is Tiny, which this table has no item sizes for, so the fighter is asked rather
      than the size assumed ("plant one Tiny object in an accessible location");
    * "take nothing", and declining, mean nothing is taken: the check is still made (it is what the action is),
      but no object moves and the table's own default disarm does not quietly happen instead.

    None -- no provider, an ability that steals no object, a fight nobody is answering (no transport, or one
    saved before this seam) -- leaves the Scoundrel Check's own row exactly as it was.
    """
    if target is None or not target.active:
        return None
    if str(source) == STEAL_ID:
        worn_only = False
        ability = printed_name(STEAL_ID)
    elif str(source) == EQUIPMENT_ID:
        worn_only = True
        ability = "Steal Equipment"
    else:
        return None  # another Scoundrel maneuver (Dirty Trick, Counter Theft): it steals no object
    from . import hand_occupancy

    checkpoint = needle.checkpoint_id(engine, "STEAL_OBJECTS", actor.entity_id, target.entity_id)
    # Steal Equipment prints one worn item, so Cleaned Out's second slot is not on offer there.
    slots = 2 if (not worn_only and "cleaned_out" in _talents(engine, actor)) else 1
    theirs = [item for item in possessions(engine, target)
              if not (worn_only and not item.get("worn"))
              and not _unreachable(engine, actor, item, paid_equipment=worn_only)]
    mine = [] if worn_only else possessions(engine, actor)  # Steal Equipment removes, it never plants
    free_hand = bool(hand_occupancy.free_hands(engine, actor))
    # Two fighters can carry the same thing, so an item key does not always name one object. Where the name would
    # not say which, the option carries the object's own identity and the label says whose it is; where it would,
    # both stay exactly as they were, so a fight with one of anything reads the same as before.
    twins = {key for key in (str(row.get("key") or "") for row in [*theirs, *mine]) if key
             and sum(1 for row in [*theirs, *mine] if str(row.get("key") or "") == key) > 1}
    options: list[str] = []
    labels: dict[str, str] = {}
    for item in theirs:
        option = _object_option(item, twins)
        named = _named(engine, item, actor, target, twins, "its")
        if free_hand:  # "take the object into a free hand"
            options.append(f"{TAKE}:{option}")
            labels[f"{TAKE}:{option}"] = f"Take {named} into your free hand"
        # "cause the object to fall into an unoccupied space within your reach": also the printed landing place
        # when there is no free hand for it ("You still need free hands or legal spaces for the objects").
        options.append(f"{FALL}:{option}")
        labels[f"{FALL}:{option}"] = f"Take {named} and let it fall in a square beside you"
        if not worn_only and effect_row.get("object_locations"):
            options.append(f"{REPOSITION}:{option}")
            labels[f"{REPOSITION}:{option}"] = f"Reposition {named} to another accessible location on {target.display_name}"
    for item in mine:
        if item.get("weapon_action") or str(item.get("kind") or "") != "item":
            continue  # a weapon is not a Tiny object, so it is never planted
        option = _object_option(item, twins)
        options.append(f"{PLANT}:{option}")
        place = (f"an accessible location on {target.display_name}" if effect_row.get("object_locations")
                 else f"{target.display_name}'s hands")
        labels[f"{PLANT}:{option}"] = (
            f"Plant {_named(engine, item, actor, target, twins, 'your own')} in "
            f"{place} instead (the printed rule allows only a Tiny object)")
    if not options:
        return {"difficult": False, "on_success": []} if effect_row.get("object_locations") else None
    options.append(NOTHING)
    labels[NOTHING] = (f"Take nothing (the check is still made, but nothing is "
                       f"{'removed' if worn_only else 'taken or planted'})")
    what = "worn thing" if worn_only else "object"
    intent = getattr(engine, "_active_intent", None)
    chosen = needle.ask(engine, intent, checkpoint, actor,
                        CHOICE + "steal_objects", options, labels=labels, minimum=0, maximum=slots,
                        allow_decline=True, default="decline",
                        name=f"{ability}: which object", feature_id=EQUIPMENT_ID if worn_only else STEAL_ID,
                        target_id=target.entity_id, automatic=_answering_for_itself(engine, actor),
                        prompt=f"{ability}: choose up to {slots} {what}{'s' if slots > 1 else ''} to "
                               f"{'remove from' if worn_only else 'take from'} {target.display_name}"
                               f"{' that it is wearing' if worn_only else ''}"
                               f"{(', or one of your own Tiny objects to plant in an accessible location on it'
                                   if effect_row.get('object_locations') else ', or one of your own Tiny objects to plant in its hands') if mine else ''}. "
                               f"You choose the object first, because the check is made against it: an "
                               f"object that is worn or held in two hands is harder to remove.")
    if not needle.answered(engine, checkpoint, actor, CHOICE + "steal_objects"):
        return None  # nobody answered: this fight predates the seam, so the row's own object stands
    rows: list[dict[str, Any]] = []
    difficult = False
    seen_objects: set[str] = set()
    for option in chosen[:slots]:
        kind, _, chosen_object = option.partition(":")
        item = next((row for row in (mine if kind == PLANT else theirs) if _is_that_object(row, chosen_object)), None)
        if item is None or str(item.get("object")) in seen_objects:
            continue
        seen_objects.add(str(item.get("object")))
        if kind == PLANT and not _tiny_enough(engine, intent, actor, target, item, source):
            continue  # "plant one Tiny object": a bigger object is not planted, and the log says so
        difficult = difficult or difficult_to_remove(engine, item)
        rows.append({"type": "transfer_object", "applies_to": "target", "from": "thief" if kind == PLANT else "victim",
                     "item": str(item.get("key") or ""), "object": str(item.get("object") or ""),
                     "as": kind, "ability": ability, "object_locations": bool(effect_row.get("object_locations")),
                     "evidence": "Steal: take the chosen object, let it fall, or plant a Tiny one."})
    # "Take nothing", and declining, are answers: the check is still made, but no object moves.
    return {"difficult": difficult, "on_success": rows}


def _object_option(item: dict[str, Any], twins: set[str]) -> str:
    """What an option says to name this object: its item key when that names one object, its own identity when not."""
    key = str(item.get("key") or "")
    return str(item.get("object") or "") if key in twins else key


def _is_that_object(item: dict[str, Any], chosen_object: str) -> bool:
    """Whether a menu answer is this object: by its own identity, or by the bare item key an older answer carries."""
    return str(item.get("object") or "") == chosen_object or str(item.get("key") or "") == chosen_object


def _named(engine: Any, item: dict[str, Any], actor: Any, holder: Any, twins: set[str], plain: str) -> str:
    """How to call this object in the menu the fighter is answering, in words a player understands.

    ``plain`` is the wording the fighter already knew ("its", "your own"), and it is kept whenever the object's
    name does say which object it is -- one of anything on the table reads exactly as it did before. Two fighters
    carrying the same thing is the only reason a name has to say whose it is: a creature's own object is "its own"
    (or "your own" when the thief is the one holding it) and an object that came from somebody else is named after
    them, so a player can tell the pack in their own hands from the pack they just took.
    """
    name = str(item.get("name") or "object")
    if str(item.get("key") or "") not in twins:
        return f"{plain} {name}"
    owner = engine.state.actors.get(str(item.get("object") or "").partition("|")[0])
    if owner is None:
        return f"{plain} {name}"  # nobody is named by the identity: the plain wording is the best one there is
    if owner.entity_id == actor.entity_id:
        return f"your own {name}"
    if owner.entity_id == holder.entity_id:
        return f"its own {name}"
    return f"the {name} belonging to {owner.display_name}"


def _tiny_enough(engine: Any, intent: Any, actor: Any, target: Any, item: dict[str, Any], source: str) -> bool:
    """"plant one Tiny object in an accessible location on the target": is the object you chose Tiny?

    This table keeps no object sizes (the compiled bundle's items carry a key, a name, a weight and whether the
    item is worn or a weapon, and nothing else), so the printed size is asked rather than assumed -- the same
    treatment Bob and Weave's "must plausibly cover at least half your body" gets. A fighter that says no has
    chosen something the printed rule does not allow, so nothing is planted and the log says why.
    """
    name = str(item.get("name") or "that object")
    answer = needle.ask(engine, intent,
                        needle.checkpoint_id(engine, "STEAL_TINY", actor.entity_id, target.entity_id,
                                             str(item.get("key") or "")),
                        actor, CHOICE + "steal_tiny", ["yes", "no"],
                        labels={"yes": f"Yes, my {name} is Tiny",
                                "no": f"No, my {name} is too big to plant"},
                        name="Steal: is it Tiny", feature_id=str(source) or STEAL_ID,
                        target_id=target.entity_id, automatic=_answering_for_itself(engine, actor),
                        prompt=f"Steal: the printed rule plants one Tiny object. Is your {name} Tiny -- small "
                               f"enough to slip into an accessible pocket, pouch or sleeve of "
                               f"{target.display_name}? You may only plant a Tiny object.")
    return "yes" in answer


@effect("transfer_object")
def transfer_object(ctx: Any, eff: dict[str, Any]) -> None:
    """The printed Steal result for one chosen object: into a hand, onto the ground, or into the target's hands.

    One record per object, all of it this table's own, so a handover moves in one event and a saved fight replays
    it. The record stays filed on the creature whose bundle lists the object -- that is what combat/carry.py
    reweighs from, and it is what gives the object its name and weight -- and says where the object went:

      into a hand   ``held_by`` naming the thief and the hand it went into, which is what
                    ``stolen_object_hands`` reports to the shared hand model -- "take the object into a free
                    hand" is a hand, so it occupies one;
      onto the ground  ``combat/carry.py`` DROPPED with ``dropped_at``, the same record the table's own Drop
                    uses, so the object lies in that square until somebody picks it up and its weight leaves
                    the creature that carried it;
      planted        ``held_by`` naming the target, on the thief's own record, for the object out of the thief's
                    own hands.

    A second theft or a planting of an object that is already away from its owner re-uses that same record
    (``_transfer_record``) instead of filing another one, so one object never has two homes at once and a
    creature that no longer holds it never keeps claiming it. ``owner`` and ``item_name`` carry the object's own
    identity with the record, so a planted object is still that object in somebody else's hands, and ``object_id``
    (``object_id``) says which object the record follows when two fighters carry the same thing -- without it a
    second identical object would take the first one's record, and the first object would lose its name and its
    place. The row names the object it moves (``object``), so the object chosen is the object moved.

    A weapon also carries the action it disables, which is how the table stops offering the victim that weapon.
    """
    from .. import carry
    from . import hand_occupancy
    from . import note

    engine, actor = ctx.engine, ctx.actor
    key, result = str(eff.get("item") or ""), str(eff.get("as") or TAKE)
    identity = str(eff.get("object") or "")
    ability = str(eff.get("ability") or "Steal")
    victim = actor if str(eff.get("from") or "victim") == "thief" else ctx.target
    if not key or victim is None or not victim.active:
        return
    item = next((row for row in possessions(engine, victim) if _is_that_object(row, identity or key)), None)
    if item is None:
        return
    # The one record following THIS object, wherever it is filed -- never another object's record for the same key.
    filed, iid = _transfer_record(engine, identity or str(item.get("object") or ""), key, victim)
    identity = identity or str(item.get("object") or "") or object_id(filed.entity_id, key)
    data = {"item_key": key, "item_name": str(item.get("name") or "object"), "owner": filed.entity_id,
            "object_id": identity}
    if result == REPOSITION or (result == PLANT and eff.get("object_locations")):
        location = _carried_location(ctx, ctx.target, item, requested=eff.get("object_location"))
        if location is None:
            return
        data["held_by"] = ctx.target.entity_id
        data["object_location"] = location
        if location.startswith("hand:"):
            data["hand"] = location.removeprefix("hand:")
        condition_id = DISARMED
        verb = "plants" if result == PLANT else "repositions"
        required = hand_occupancy.holding_hands(engine, str(item.get("weapon_action") or ""))
        place = ("an accessible carried location" if location == "carried" else
                 "an empty hand" if required == 1 else f"{required} empty hands")
        say = f"{ability}: {actor.display_name} {verb} {data['item_name']} in {place} on {ctx.target.display_name}."
    elif result == PLANT:
        data["held_by"] = ctx.target.entity_id
        condition_id = DISARMED
        say = (f"{ability}: {actor.display_name} plants {data['item_name']} in {ctx.target.display_name}'s hands "
               f"(\"plant one Tiny object in an accessible location on the target\").")
    elif result == FALL or not hand_occupancy.free_hands(engine, actor):
        spot = _landing_spot(ctx, actor, ability, feet=int(eff.get("landing_range_ft") or ADJACENT_FT),
                             object_id=identity if eff.get("landing_range_ft") else "")
        if spot is None:
            # "cause the object to fall into an unoccupied space within your reach": no square was chosen, so the
            # printed result did not happen. Say so instead of quietly handing over nothing.
            ctx.rider(f"{ability}: {item.get('name') or 'The object'} stays with {victim.display_name}: "
                      f"\"cause the object to fall into an unoccupied space within your reach\" needs a square, "
                      f"and none was chosen.")
            return
        data["dropped_at"] = spot
        condition_id = carry.DROPPED
        say = (f"{ability}: {actor.display_name} takes {data['item_name']} from {victim.display_name} and lets it fall "
               f"in the square at {spot.get('x')},{spot.get('y')}.")
    else:
        hand = hand_occupancy.free_hands(engine, actor)[0]
        data["held_by"] = actor.entity_id
        data["hand"] = hand
        condition_id = DISARMED
        say = f"{ability}: {actor.display_name} takes {data['item_name']} from {victim.display_name} into a free hand."
    if item.get("weapon_action") and not (data.get("held_by") == filed.entity_id
                                          and (data.get("hand") or data.get("object_location"))):
        data["disables_action"] = str(item["weapon_action"])
    if iid is not None and data.get("held_by") == filed.entity_id and not data.get("object_location"):
        # The object is back in the hands of the creature whose bundle lists it: it is home, so there is nothing
        # left to record. Dropping the record is what puts it back in that creature's possession and load.
        _remove(engine, filed, iid, ctx.source, actor.entity_id)
        note(engine, ctx.source, actor,
             f"{ability}: {actor.display_name} puts {data['item_name']} into {filed.display_name}'s hands.", (victim.entity_id,))
        carry.refresh(engine, filed, ctx.source)
        carry.refresh(engine, actor, ctx.source)
        return
    if item.get("weapon_action") and data.get("held_by") == filed.entity_id and data.get("object_location"):
        from .equipment_hands import set_weapon_readiness
        # Owned weapons use the public equipment model, not the lost-weapon
        # ledger. The shared model reserves all of its resting grips (two for
        # Paired weapons); ordinary objects and weapons held by someone else
        # still use the transfer hand record.
        hand = data.pop("hand", None)
        held = bool(hand)
        set_weapon_readiness(engine, filed, str(item["weapon_action"]), held,
                             source=ctx.source, source_actor_id=actor.entity_id, hand=hand)
    _rehome(engine, filed, iid, data, source=ctx.source, actor_id=actor.entity_id, condition_id=condition_id)
    note(engine, ctx.source, actor, say, (victim.entity_id, ctx.target.entity_id))
    for who in {actor.entity_id, victim.entity_id, ctx.target.entity_id}:
        who_creature = engine.state.actors.get(who)
        if who_creature is not None:
            carry.refresh(engine, who_creature, ctx.source)


def _carried_location(ctx: Any, target: Any, item: dict[str, Any], *, requested: str | None = None) -> str | None:
    """Choose a free hand or an accessible carried location; no activation is implied."""
    from . import hand_occupancy
    hands = hand_occupancy.free_hands(ctx.engine, target)
    # Owned readiness uses the same resting-hand requirement as Draw. A
    # Two-Handed weapon rests in one hand, while a Paired weapon needs two.
    # Each offered part anchors the first grip; occupancy reserves the rest.
    required = hand_occupancy.holding_hands(ctx.engine, str(item.get("weapon_action") or ""))
    if len(hands) < required:
        hands = ()
    options = ["carried", *[f"hand:{part}" for part in hands]]
    if requested is not None:
        # A parent choice may already have selected both object and location.
        # Validate against the same live hands; never ask twice or fall back
        # to a different location when the selected one is no longer legal.
        return requested if requested in options else None
    labels = {"carried": f"An accessible pocket, pouch, sleeve or other carried location on {target.display_name}"}
    hand_label = (f"An empty hand of {target.display_name}" if required == 1 else
                  f"{required} empty hands of {target.display_name}")
    labels.update({f"hand:{part}": hand_label for part in hands})
    chosen = needle.ask(ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, "STEAL_LOCATION", target.entity_id, item.get("object")),
        ctx.actor, CHOICE + "steal_location", options, labels=labels,
        minimum=1, maximum=1, allow_decline=False,
        name=ctx.action.display_name, target_id=target.entity_id,
        prompt=f"{ctx.action.display_name}: choose another accessible location for {item.get('name') or 'this object'} "
               f"on {target.display_name}. It remains carried by that creature. No extra cost; "
               "placing it does not activate or use it.")
    return chosen[0] if chosen and chosen[0] in options else None


@hook("hand_occupants")
def stolen_object_hands(engine: Any, actor: Any) -> dict[str, str] | None:
    """"take the object into a free hand": an ordinary object this creature is holding occupies that hand.

    The record of a stolen object lives on the creature whose bundle lists it (that is what combat/carry.py
    reweighs from), naming the hand the object went into, so every creature's records are read for the ones naming
    this one. There is only ever one record per object, so a hand is claimed by an object its holder really has.
    Only those records are answered, so no other character and no other source of gear is affected. A recorded
    hand that is no longer one of the creature's hands (a feature changed them) is not claimed, which leaves the
    object hand-less rather than blocking a hand it no longer has.
    """
    from . import hand_occupancy

    from .. import carry

    hands = hand_occupancy.hand_parts(engine, actor)
    out: dict[str, str] = {}
    for other in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        for row in other.conditions.values():
            data = row.data or {}
            part, key = str(data.get("hand") or ""), str(data.get("item_key") or "")
            if data.get("held_by") == actor.entity_id and part in hands and part not in out:
                item = carry.item_of(carry.carrying_of(engine, other.entity_id), key=key)
                # An owned relocated shield has one shield occupant, allocated
                # by hand_occupancy from this same authoritative location.
                if other.entity_id == actor.entity_id and (item or {}).get("shield") \
                        and carry.owned_item_location(actor, key) is not None:
                    continue
                out[part] = f"object:{key}"
    return out or None


def _landing_spot(ctx: Any, actor: Any, ability: str = "Steal", *, feet: int = ADJACENT_FT,
                  object_id: str = "") -> dict[str, Any] | None:
    """"cause the object to fall into an unoccupied space within your reach" / "one legal unoccupied space".

    Explicit object-radius landings use object_placement with a one-cell object
    footprint. Legacy reach menus retain their original Needle geometry and cap.
    Declining leaves the object where it was.
    """
    engine = ctx.engine
    if object_id:
        from ..object_placement import destinations
        cells = {cell: engine.grid.distance_ft(actor.position, cell)
                 for cell in destinations(engine, actor, feet)}
    else:
        cells = {cell: cost for cell, cost in needle.free_cells(engine, actor, feet).items()
                 if cell != actor.position}
    if not cells:
        return None
    ordered = sorted(cells, key=lambda cell: (cells[cell], cell.y, cell.x))
    if not object_id:
        ordered = ordered[:16]
    options = [needle.cell_id(cell) for cell in ordered]
    labels = {needle.cell_id(cell): f"Let it fall at {cell.x},{cell.y} ({cells[cell]} feet away)" for cell in ordered}
    chosen = needle.ask(engine, ctx.intent or getattr(engine, "_active_intent", None),
                        needle.checkpoint_id(engine, "STEAL_SPOT", actor.entity_id, *([object_id] if object_id else [])), actor,
                        CHOICE + "steal_spot", options, labels=labels, minimum=1, maximum=1, allow_decline=True,
                        default="decline", name=f"{ability}: where it falls",
                        feature_id=EQUIPMENT_ID if ability == "Steal Equipment" else STEAL_ID,
                        target_id=actor.entity_id, automatic=_answering_for_itself(engine, actor),
                        prompt=f"{ability}: the object must end up in an unoccupied square within {feet} feet of you. "
                               f"Choose which square it falls into.")
    return needle.position_of(chosen[0]).model_dump(mode="json") if chosen else None


def _transfer_record(engine: Any, identity: str, key: str, victim: Any) -> tuple[Any, str | None]:
    """The one record already following THIS object, and the creature it is filed on: (creature, instance id).

    An object is recorded on the creature whose bundle lists it, so a handover MOVES that record's "held_by"
    rather than filing a second one: one object, one record, however many hands it has passed through. The
    record that moves is the one that names this object (``object_id``, or the identity the creature it is filed
    on gives a record written before that field existed). Another object of the same kind is a different record
    and is never touched -- two identical packs in one fight are two objects, and a thief's own pack must not
    take the record of the pack they took. (victim, None) means this object has no record yet, and one is filed
    on the creature it came off, which is the bundle that lists it.
    """
    from .. import carry

    rows = [(creature, iid, row.data or {}) for creature in sorted(engine.state.actors.values(),
                                                                   key=lambda row: row.entity_id)
            for iid, row in creature.conditions.items()
            if str((row.data or {}).get("item_key") or "") == key
            and ((row.data or {}).get("held_by") or (row.data or {}).get("dropped_at"))
            and _record_identity(creature, row.data or {}) == identity]
    if not rows:
        return victim, None
    for creature, iid, _data in rows:
        if carry.item_of(carry.carrying_of(engine, creature.entity_id), key=key) is not None:
            return creature, iid
    return rows[0][0], rows[0][1]


def _rehome(engine: Any, owner: Any, iid: str | None, data: dict[str, Any], *, source: str, actor_id: str,
            condition_id: str = DISARMED) -> None:
    """Record an item's new holder or square as its own removal and its own application, so a saved fight replays it."""
    if iid is not None and iid in owner.conditions:
        old = owner.conditions.pop(iid)
        engine._append_event("CONDITION_REMOVED", source, actor_id=actor_id, target_ids=(owner.entity_id,),
                             payload={"condition_id": old.condition_id, "instance_id": iid})
    engine._apply_condition(owner, condition_id, source, actor_id, expires_on="UNTIL_REMOVED", data=data)


@hook("choice_options")
def scoundrel_options(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str,
                      context: dict[str, Any]) -> dict[str, Any] | None:
    """Every Scoundrel choice (id "choice:scoundrel.*"), through the shared Needle transport's own spec.

    Without it the table would present these menus as an ordinary Use/Pass window with no options, no labels and
    no bounds, which is what made them unanswerable. Default-inert for any other choice id.
    """
    return needle.option_spec(choice_id, context, CHOICE)
