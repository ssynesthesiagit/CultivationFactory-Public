"""Verdant Growth chassis: Living Claims, Growth Marks and the Verdant Responses, with the talents built on them (rider lane C16,
2026-09-30; owner: fill the sphere chassis from the owner's books, do not ask). Rules text: the owner's Sphere Compendium, "Sphere of
Verdant Growth", Core Verdant Growth Rules (Living Claims, Growth Marks, Verdant Responses are printed there, not in the typed
authority) and the talents below (authority/typed_mechanics/rules_text.json). Who has it: a character owning Sow Living Claim carries a
compiled ``verdant`` row of kind ``core`` (combat/rules/feature_blocks.d/riders_c16.json); talents add rows of their own kinds. Every
hook returns at once for a creature without a ``verdant`` row, so fights saved before this lane (bundles without the rows) replay
exactly.

Living Claims -- "a temporary plant-growth point ... occupies one 5-foot square ... lasts for 1 minute ... it is not automatically
  difficult terrain, cover ... A creature may destroy an unattended Living Claim by dealing damage to it. A basic Living Claim has: AC 10;
  HP equal to 5 + your Proficiency Bonus + your key ability modifier, minimum 5; vulnerability to Fire damage ...; immunity to Poison and
  Psychic damage." A claim is a map object (RuntimeObjectState, kind LIVING_CLAIM; "Attack an object" can break it; it never blocks its
  square). Sow Living Claim: a Bonus Action at a square within 30 feet (Body Refining: within reach, 5 feet); sown in your own square it
  is "on your body" and moves with you. "You may have a number of Living Claims active equal to your Proficiency Bonus. If you create a
  Living Claim beyond this number, choose one old Living Claim to wither" (asked; the AI withers the oldest). Ten rounds after it was
  made it withers at the start of your turn. Every change is an OBJECT_UPDATED event.
Contact (the table records no soil, plants or wood): a creature touches one of your Living Claims when the claim is in its space or on
  its body; it touches "your body" when it is within 5 feet of you; you touch a Living Medium when you touch one of your claims, carry
  seeds (Seed Pouch Method) or are a Living Medium yourself (Verdant Incarnation).
Growth Marks -- "a target can hold a maximum number of your Growth Marks equal to your Proficiency Bonus; Growth Marks last until the end
  of your next turn; when you spend a Growth Mark, remove it; you can spend only your own Growth Marks". One counted mark per marker and
  creature (condition:typed.mark.growth_mark.<you>, data.count); a new mark adds one (up to the limit) and renews the deadline. Marks
  are placed on creatures (a mark "on a space" is not tracked).
Verdant Responses -- "Unless a talent says otherwise, use no more than one Verdant Response per turn." No action cost is printed: a
  response is used on your own turn without an action (the default this lane chose: the owner's sibling rule, Earth's Burden Marks,
  "spend ... without using an Action"; and The Seed That Remembers the Forest names the Reaction only for its off-turn use). Buttons:
    Root    1 mark on a creature within 60 feet: its Speed -10 until the start of your next turn (-15 if it touches your claim or body)
    Bind    2 marks: Strength save; failed, Grappled by your growth until the end of your next turn (escape DC = your Verdant Growth
            save DC; it ends if the claim it touches is destroyed); success, Speed -10 until the end of the turn
    Shelter 1 mark on an ally touching your claim: Half Cover against its next attack, Temporary HP equal to your PB, or its space
            Lightly Obscured, until the start of your next turn
            Cover is consumed by the actual ATTACK_ROLLED event, hit or miss, after the resolver snapshots the protected AC.
            Nested event delivery covers reaction attacks too; legal-candidate/AC queries never consume it.
    Thorn   1 mark on a creature touching your claim or body: Piercing damage = PB (+1d6 at CL 5, 2d6 at CL 11, 3d6 at CL 17)
  Root Feed ("Feed the Root": once per turn, placing a mark on a creature touching your claim feeds your chosen claim within 60 feet, up
  to PB, until the end of your next turn) pays for a response through that claim instead of a mark, including mixed payment. Grove Domain: once per round, a
  response without a mark. Not built: Climb (heights, census row 1), Bloom (Perception/Nature checks and revealing an Invisible
  creature in a space: no table hook for either).
Talents (rows of block "verdant"):
  bark_back_guard   a claim sown on your body: Temporary HP = PB; while they last the first creature to hit you in melee takes PB
                    Piercing (once per round)
  bramble_refusal   a marked creature's melee attack on you or on an ally next to your claim: spend 1 mark (asked; no Reaction --
                    none is printed), it takes 1d8 Piercing and makes a Dexterity save or has Disadvantage on that attack
  hungry_root       a creature regaining HP while touching your claim: place a mark on it (asked; an unwilling one makes a
                    Constitution save; the AI marks only hostile creatures)
  medicinal_sprout  Shelter on an ally also gives Advantage on its next Constitution save against Poisoned before your next turn
  reed_screen       Shelter's obscuring screen lasts 1 minute or until your claim is destroyed
  shelter_grove     two Shelter options instead of one
  root_snare_step   new compiled step_snare rows: after ten physical feet on its turn, ask for 1 mark and a Strength save;
                    failure stops after the current step, success gives Speed -10 this turn. Older rows keep post-move timing.
  deep_root        before leaving a square adjacent to a claim, spend 2 marks (asked): STR failure Restrained through the owner's
                    next turn with end-turn repeat saves; success Grappled by the roots through this turn (not a hand-held grip).
  staff_branch      once per turn, a hit with a wooden weapon (staff, club, spear, bow, fan, brush) places a mark
  thorned_warning   a creature that damages or destroys your claim gets a mark; your Thorn on it before the end of your next turn adds
                    your key modifier. An evented condition on the owner identifies that creature, refreshes on qualifying damage,
                    and expires via effect_durations' END_OF_TURN_AT clock; ordinary turn-start flag cleanup cannot discard it.
  thorn_crown       a marked enemy damaging an ally within 60 feet (either touching your claim): spend up to 3 marks (asked): -PB
                    damage and PB Piercing to the enemy per mark
  willow_bend       forced movement on you while touching a Living Medium is 10 feet shorter; reduced to 0, the origin gets a mark
  forest_remembers  a marked creature moving or teleporting through a space within 60 feet: spend 1 mark (asked) to sow a claim
                    in a represented space it left or entered; teleport choices are departure/arrival only, after resolution
  branching_answer  once per round, a second different response on the same creature without another mark (asked)
  rooted_lineage    marks last one extra round while contact continues; a marked enemy starting its turn touching your claim:
                    Speed -5 until the end of that turn
  verdant_incarnation (while its state lasts) a free claim on your body at the start of your turn; a creature that hits you in melee
                    gets a mark; Bind costs one mark ("treat the number of marks spent as one higher")
  grove_domain      (while its state lasts) a free claim at the start of your turn; enemies starting their turn in your claim get a
                    mark; allies starting their turn in it gain PB Temporary HP; one response a round without a mark; your claims'
                    squares are difficult terrain for enemies
Stored data is integers and strings only.
"""

from __future__ import annotations

import json
from typing import Any

from factory_authoring.verdant_evidence import SHELTER_EVIDENCE

from . import effect, hook, note, run
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "verdant"
MARK = "Growth Mark"
KIND = "LIVING_CLAIM"
SOW = "TAL_VERDANT_GROWTH_SOW_LIVING_CLAIM"
SOURCE = "system:verdant.living_claim"
RESPONSES = ("root", "bind", "shelter", "thorn")
COST = {"root": 1, "bind": 2, "shelter": 1, "thorn": 1}
WOOD = ("staff", "club", "spear", "bow", "fan", "brush", "cudgel", "pole", "quarterstaff", "gun (", "bang")


# ------------------------------------------------------------------------------------------------ rows and numbers
def row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    from .passive_rows import row_of

    return row_of(engine, actor.entity_id, BLOCK, kind) if actor is not None else None


def is_verdant(engine: Any, actor: Any) -> bool:
    """Any compiled Verdant Growth row (Sow Living Claim's ``core``, or a talent's own)."""
    return actor is not None and any(r.get("block") == BLOCK for r in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


def _numbers(engine: Any, actor: Any) -> dict[str, int]:
    """The owner's compiled numbers (its Verdant Growth save DC is its Cultivation Save DC: "use your Cultivation Save DC")."""
    from .ability_source import numbers_of

    core, sealed = row(engine, actor, "core") or {}, numbers_of(engine, actor) or {}
    pb = int(core.get("pb") or sealed.get("pb") or actor.proficiency_bonus or 2)
    return {"pb": pb, "cl": int(core.get("cl") or sealed.get("cl") or 1), "key_mod": int(core.get("key_mod") or sealed.get("key_mod") or 0),
            "save_dc": int(sealed.get("save_dc") or 8 + pb + int(core.get("key_mod") or 0))}


@hook("compile_block")
def verdant_block(block: str, spec: dict[str, Any], row_: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row_, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
             "key_mod": int(numbers.get("key_mod") or 0), **({"keeps_compiling": True} if spec.get("keeps_compiling") else {}),
             **({"step_snare": True} if spec.get("step_snare") else {}),
             **({"medicinal_categories": 1} if spec.get("medicinal_categories") == 1 else {}),
             **({"fire_stunts_claim": 1} if spec.get("fire_stunts_claim") == 1 else {}),
             **({"perceived_response": 1} if spec.get("perceived_response") == 1 else {})}]


def _state(engine: Any, actor: Any, name: str) -> bool:
    from .states import active

    return active(engine, actor, name) is not None


def _round(engine: Any) -> str:
    return f"{engine.state.round_number}"


def _turn(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_slot_index}"


# ------------------------------------------------------------------------------------------------ Living Claims
def claims(engine: Any, owner: Any) -> list[Any]:
    """The owner's standing claims, oldest first."""
    found = [obj for obj in engine.state.objects.values() if not obj.destroyed and obj.object_kind == KIND
             and (obj.component or {}).get("owner") == owner.entity_id]
    return sorted(found, key=lambda obj: (int((obj.component or {}).get("made") or 0), obj.object_id))


def _claim_cells(engine: Any, obj: Any) -> set[tuple[int, int]]:
    holder = engine.state.actors.get(str((obj.component or {}).get("on") or ""))
    if holder is not None and holder.active:
        return set(engine._actor_cells(holder))
    return {(obj.position.x, obj.position.y)}


def touching(engine: Any, creature: Any, owner: Any) -> list[Any]:
    """The owner's claims the creature touches (in its space or on its body)."""
    if creature is None or not creature.active:
        return []
    mine = set(engine._actor_cells(creature))
    return [obj for obj in claims(engine, owner) if (obj.component or {}).get("on") == creature.entity_id or _claim_cells(engine, obj) & mine]


def in_contact(engine: Any, creature: Any, owner: Any) -> bool:
    """"touching a Living Claim, a plant, soil, wood, or your body": the owner's claim, or within 5 feet of the owner."""
    if creature is None:
        return False
    if creature.entity_id != owner.entity_id and engine._distance_actor_to_actor(creature, owner) <= 5:
        return True
    return bool(touching(engine, creature, owner))


def medium(engine: Any, owner: Any) -> bool:
    """Whether the owner touches a Living Medium (its claim, carried seeds, its own incarnated body)."""
    return (bool(touching(engine, owner, owner)) or row(engine, owner, "seed_pouch") is not None
            or (row(engine, owner, "verdant_incarnation") is not None and _state(engine, owner, "verdant_incarnation")))


def _update(engine: Any, obj: Any, actor_id: str | None = None, **component: Any) -> Any:
    from ..gate2_runtime_models import RuntimeObjectState

    data = {**(obj.component or {}), **component}
    after = RuntimeObjectState.model_validate(obj.model_copy(update={"component": data}).model_dump(mode="json"))
    engine._update_object(after, SOURCE, actor_id)
    return after


def wither(engine: Any, obj: Any, why: str) -> None:
    from ..gate2_runtime_models import RuntimeObjectState

    after = RuntimeObjectState.model_validate(obj.model_copy(update={"destroyed": True, "component": {**(obj.component or {}), "withered": 1}})
                                             .model_dump(mode="json"))
    engine._update_object(after, SOURCE, (obj.component or {}).get("owner"))
    owner = engine.state.actors.get(str((obj.component or {}).get("owner") or ""))
    note(engine, SOURCE, owner, f"A Living Claim of {owner.display_name if owner else 'a cultivator'} withers ({why}).")
    _claim_gone(engine, obj)


def sow(engine: Any, owner: Any, position: Any, source: str, intent: Any = None, *, on: str = "") -> Any | None:
    """Make one Living Claim (the shared helper: Sow Living Claim, Forest Remembers the Path, Grove Domain, Verdant Incarnation)."""
    from .. import object_rules
    from ..gate2_runtime_models import RuntimeObjectState

    numbers = _numbers(engine, owner)
    standing = claims(engine, owner)
    if len(standing) >= numbers["pb"]:
        labels = {obj.object_id: f"Let the claim at square {obj.position.x},{obj.position.y} wither" for obj in standing}
        picked = ask(engine, intent, checkpoint_id(engine, "WITHER_CLAIM", owner.entity_id), owner, CHOICE + "wither_claim", list(labels),
                     labels=labels, preferred=[standing[0].object_id], target_id=owner.entity_id, name="Living Claims",
                     prompt=f"You may have {numbers['pb']} Living Claims. Choose an old one to wither for the new one.")
        old = next((obj for obj in standing if picked and obj.object_id == picked[0]), standing[0])
        wither(engine, old, "a new claim was sown beyond the limit")
    hp = max(5, 5 + numbers["pb"] + numbers["key_mod"])
    immune = sorted({str(kind).upper() for kind in [*object_rules.rules().get("immune", []), "POISON", "PSYCHIC"]})
    made = int(engine.state.event_sequence) + 1
    obj = RuntimeObjectState(
        object_id=f"object:living_claim.{made}", object_kind=KIND, position=position, unattended=not on, flammable=True, ac=10,
        current_hp=hp, maximum_hp=hp, damage_immunities=tuple(immune), damage_threshold=None, destroyed=False,
        component={"name": f"Living Claim ({owner.display_name})", "material": "plant", "size": "small", "blocks": False,
                   "structure": False, "resilient": False, "artifact": False, "kind": "living_claim", "resist": [], "vulnerable": ["FIRE"],
                   "owner": owner.entity_id, "on": on, "made": made, "until_round": int(engine.state.round_number) + 10,
                   "feed": 0, "feed_until": 0})
    engine._update_object(obj, source, owner.entity_id)
    where = f"on {engine.state.actors[on].display_name}" if on else f"at square {position.x},{position.y}"
    note(engine, source, owner, f"{owner.display_name} sows a Living Claim {where} (AC 10, {hp} hit points; Fire breaks it fastest). "
         "It lasts 1 minute.")
    if on == owner.entity_id and row(engine, owner, "bark_back_guard") is not None:
        _bark_back(engine, owner)
    return obj


@effect("living_claim")
def sow_effect(ctx: Any, eff: dict[str, Any]) -> None:
    aim = ctx.damage_cache.get("_checkpoint_aim") or getattr(ctx.intent, "destination", None)
    if aim is None:
        return
    on = ctx.actor.entity_id if (aim.x, aim.y) in set(ctx.engine._actor_cells(ctx.actor)) else ""
    sow(ctx.engine, ctx.actor, ctx.actor.position if on else aim, ctx.source, ctx.intent, on=on)


def _claim_gone(engine: Any, obj: Any) -> None:
    """What hangs on a claim ends with it: a Bind's grapple on it, Reed Screen's screen."""
    from .rider_support import remove_instance

    for actor in engine.state.actors.values():
        for iid, condition in list(actor.conditions.items()):
            if (condition.data or {}).get("verdant_claim") == obj.object_id:
                remove_instance(engine, actor, iid, SOURCE)
    for zone in list(engine.state.zones.values()):
        if zone.active and zone.trigger_profile.get("verdant_claim") == obj.object_id:
            from .. import zones

            zones.remove(engine, zone, "its Living Claim was destroyed")


# ------------------------------------------------------------------------------------------------ Growth Marks
def _mark_id(owner_id: str) -> str:
    from ..typed_executor import mark_condition_id

    return mark_condition_id(MARK, owner_id)


def _mark(subject: Any, owner_id: str) -> Any | None:
    return next((c for c in subject.conditions.values() if c.condition_id == _mark_id(owner_id)), None) if subject is not None else None


def marks(subject: Any, owner: Any) -> int:
    held = _mark(subject, owner.entity_id)
    return max(1, int((held.data or {}).get("count") or 1)) if held is not None else 0


def _set_marks(engine: Any, owner: Any, subject: Any, number: int, source: str, *, renew: bool) -> None:
    from .effect_durations import token, apply_condition_preserving_clock, expiry_key
    from .rider_support import remove_instance

    old = _mark(subject, owner.entity_id)
    if old is not None:
        remove_instance(engine, subject, old.instance_id, source)
        if renew or number <= 0:
            subject.turn_flags.pop(expiry_key(old), None)
    if number <= 0:
        return
    fresh = renew or old is None
    data = {"marker_turn": int(owner.turns_started)} if fresh else dict(old.data or {})
    expires = (token("end", owner.entity_id, int(owner.turns_started) + 1)
               if row(engine, owner, "rooted_lineage") is not None else "END_OF_MARKER_NEXT_TURN") if fresh else old.expires_on
    deadline = (f"they last until the end of {owner.display_name}'s next turn"
                if not data.get("lineage_extended") else "Rooted Lineage Scripture keeps them for one additional round while contact continues")
    apply_condition_preserving_clock(engine, subject, old if not fresh else None, _mark_id(owner.entity_id), source if renew or old is None else old.source_definition_id, owner.entity_id,
                            expires_on=expires,
                            data={**data, "count": int(number),
                                  "label": f"{number} Growth Mark{'s' if number > 1 else ''} ({owner.display_name}): spent on Verdant Responses; "
                                           f"{deadline}"})


def claim_marks(obj: Any, owner: Any) -> int:
    """Growth Marks the owner has placed on one Living Claim instead of on a creature.

    Hungry Root Drinks the Spill prints "that creature or on the Living Claim"; the claim is not an actor, so its
    count lives on the object's own component and dies with the claim.
    """
    return int(((obj.component or {}).get("growth_marks") or {}).get(owner.entity_id, {}).get("count") or 0)


def claim_deadline(held: dict[str, Any] | None, owner: Any) -> int:
    """The owner's turn number whose END removes Growth Marks held on a Living Claim.

    The marker's NEXT turn, exactly as a mark on a creature ends (see ``_set_marks`` and the engine's
    ``END_OF_TURN_AT:<id>:<N>`` name). Rows written before this helper existed stored a boolean here; they are
    read as the printed deadline rather than as "already due".

    ``marker_turn`` is a turn counter, so 0 is a real value and not a missing one. Only an absent (or boolean)
    counter falls back to the turn being asked about.
    """
    stored = (held or {}).get("deadline")
    if isinstance(stored, int) and not isinstance(stored, bool) and stored > 0:
        return int(stored)
    marker = (held or {}).get("marker_turn")
    if isinstance(marker, int) and not isinstance(marker, bool):
        return int(marker) + 1
    return int(owner.turns_started) + 1


def place_claim_marks(engine: Any, owner: Any, obj: Any, number: int) -> None:
    """Count, place and spend Growth Marks held on a Living Claim. Only integers and strings are persisted.

    Like ``place`` on a creature, placing a mark starts a fresh deadline; spending one keeps it.
    """
    stored = {key: dict(value) for key, value in ((obj.component or {}).get("growth_marks") or {}).items()}
    marker_turn = int(owner.turns_started)
    stored[owner.entity_id] = {"count": max(0, int(number)),
                               "marker_turn": marker_turn,
                               "deadline": marker_turn + 1}
    if stored[owner.entity_id]["count"] <= 0:
        stored.pop(owner.entity_id, None)
    _update(engine, obj, owner_id=owner.entity_id, growth_marks=stored,
            name=(obj.component or {}).get("name") or f"Living Claim ({owner.display_name})")


@hook("effect_expiring")
def rooted_lineage_expiring(engine: Any, holder: Any, condition: Any) -> None:
    """At the normal deadline, extend an owned Growth Mark once using the existing turn clock.

    Only compiled Rooted Lineage rows opt in. Spending preserves this deadline; placing a new mark starts a new one.
    Unrepresented plants, soil and wood remain GM contact rulings (the table's existing contact model).
    """
    from .effect_durations import token, apply_condition_preserving_clock
    from .rider_support import remove_instance

    owner = engine.state.actors.get(getattr(condition, "source_actor_id", None))
    if owner is None or row(engine, owner, "rooted_lineage") is None or condition.condition_id != _mark_id(owner.entity_id):
        return
    if (condition.data or {}).get("lineage_extended") or not _lineage_contact(engine, holder, owner):
        return
    data = {**condition.data, "lineage_extended": 1,
            "label": f"{marks(holder, owner)} Growth Marks ({owner.display_name}): spent on Verdant Responses; "
                     "Rooted Lineage Scripture keeps them for one additional round while contact continues"}
    remove_instance(engine, holder, condition.instance_id, condition.source_definition_id)
    apply_condition_preserving_clock(engine, holder, condition, condition.condition_id, condition.source_definition_id, owner.entity_id,
                            expires_on=token("end", owner.entity_id, int(data["marker_turn"]) + 2), data=data)


def _lineage_contact(engine: Any, holder: Any, owner: Any) -> bool:
    """Scripture's duration says 'a Living Claim'; its separate Speed penalty says 'one of your Living Claims'.

    Any represented claim can sustain the duration, including another cultivator's. The marker's own body counts too.
    """
    return (holder.entity_id == owner.entity_id or in_contact(engine, holder, owner)
            or any(touching(engine, holder, other) for other in _verdants(engine) if other.entity_id != owner.entity_id))


def _end_lineage_contact(engine: Any, owners: list[Any]) -> None:
    """Movement or loss of a claim ends only the contact-dependent additional round, through recorded removal events."""
    from .rider_support import remove_instance

    for owner in owners:
        if row(engine, owner, "rooted_lineage") is None:
            continue
        for holder in engine.state.actors.values():
            condition = _mark(holder, owner.entity_id)
            if condition is not None and (condition.data or {}).get("lineage_extended") and not _lineage_contact(engine, holder, owner):
                remove_instance(engine, holder, condition.instance_id, "tianxia.talent.verdant_growth.rooted_lineage_scripture")


def place(engine: Any, owner: Any, subject: Any, number: int, source: str, intent: Any = None) -> int:
    """Place Growth Marks (up to the PB limit; a new mark renews the deadline). Returns how many were added."""
    if subject is None or not subject.active or number <= 0:
        return 0
    held = marks(subject, owner)
    new = min(_numbers(engine, owner)["pb"], held + number)
    _set_marks(engine, owner, subject, max(new, held), source, renew=True)
    _feed_the_root(engine, owner, subject, source, intent)
    return new - held


def spend(engine: Any, owner: Any, subject: Any, number: int, source: str) -> bool:
    held = marks(subject, owner)
    if held < number or number <= 0:
        return False
    _set_marks(engine, owner, subject, held - number, source, renew=False)
    return True


@hook("mark_apply")
def growth_mark_applied(ctx: Any, eff: dict[str, Any], subject: Any, expires: str, data: dict[str, Any] | None) -> bool | None:
    """Growth Marks placed by a Verdant Growth cultivator compiled with its rows (a fight saved before rider lane C16 keeps its old,
    uncounted marks, so it replays exactly)."""
    if str(eff.get("mark") or "") != MARK or not is_verdant(ctx.engine, ctx.actor):
        return None
    place(ctx.engine, ctx.actor, subject, 1, ctx.source, ctx.intent)
    return True


@hook("mark_consume")
def growth_mark_spent(ctx: Any, eff: dict[str, Any], subject: Any) -> bool | None:
    if str(eff.get("mark") or "") != MARK or not is_verdant(ctx.engine, ctx.actor):
        return None
    return spend(ctx.engine, ctx.actor, subject, max(1, int(eff.get("count") or 1)), ctx.source)


def _feed_the_root(engine: Any, owner: Any, subject: Any, source: str, intent: Any = None) -> None:
    """Feed the Root: "Trigger: You place a Growth Mark on a creature ... touching one of your Living Claims. Use Limit: Once per turn.
    Choose one of your Living Claims within 60 feet. It gains one Root Feed until the end of your next turn."

    Player owners choose even on another actor's AI turn; AI prefers the touched claim, then the oldest claim with room.
    """
    if row(engine, owner, "feed_the_root") is None or owner.turn_flags.get("verdant_round_feed") == _turn(engine):
        return
    touched = touching(engine, subject, owner)
    if not touched:
        return
    near = [obj for obj in claims(engine, owner) if engine.grid.distance_ft(obj.position, owner.position) <= 60]
    if not near:
        return
    from .choice_prompt import action_context

    intent = intent or getattr(engine, "_active_intent", None)
    action = engine.action_catalog.get(getattr(engine, "_active_action_source_id", None) or source)
    source_id = action.source_definition_id if action is not None else source
    trigger_actor = engine.state.actors.get(getattr(intent, "actor_id", "")) or owner
    pb = _numbers(engine, owner)["pb"]
    available = [obj for obj in near if _feed(engine, obj, owner) < pb]
    preferred = next((obj for obj in touched if obj in available), (available or near)[0])
    labels = {obj.object_id: f"Feed your claim at square {obj.position.x},{obj.position.y}: "
                            + (f"+1 Root Feed ({_feed(engine, obj, owner) + 1}/{pb}); spend it as a Growth Mark "
                               "for a response through that claim, until the end of your next turn"
                               if _feed(engine, obj, owner) < pb else
                               f"already holds its maximum {pb} Root Feed; gains none") for obj in near}
    picked = ask(engine, intent, checkpoint_id(engine, "FEED_THE_ROOT", owner.entity_id, subject.entity_id), owner,
                 CHOICE + "feed_the_root", list(labels), labels=labels, preferred=[preferred.object_id], allow_decline=True,
                 target_id=owner.entity_id, name="Feed the Root", feature_id="TAL_VERDANT_GROWTH_FEED_THE_ROOT",
                 prompt=f"Feed the Root: {action.display_name if action else 'placing a Growth Mark'} placed your Growth Mark on "
                        f"{subject.display_name}, touching your Living Claim. Choose your claim within 60 feet to gain 1 Root Feed "
                        "until the end of your next turn. No action; once per turn.",
                 prompt_context=action_context(engine, trigger_actor, source_id, subject))
    target = next((obj for obj in near if picked == [obj.object_id]), None)
    if target is None:
        return
    owner.turn_flags["verdant_round_feed"] = _turn(engine)
    if _feed(engine, target, owner) >= pb:
        note(engine, "TAL_VERDANT_GROWTH_FEED_THE_ROOT", owner,
             f"Feed the Root: {owner.display_name}'s claim at square {target.position.x},{target.position.y} already holds its "
             f"maximum {pb} Root Feed; it gains none and existing feed keeps its deadline.")
        return
    buckets = _feed_buckets(target, owner)
    due = int(owner.turns_started) + 1
    buckets[due] = buckets.get(due, 0) + 1
    _write_feed(engine, target, owner, buckets)
    note(engine, "TAL_VERDANT_GROWTH_FEED_THE_ROOT", owner,
         f"Feed the Root: {owner.display_name}'s claim at square {target.position.x},{target.position.y} gains 1 Root Feed "
         "until the end of the next turn; spend it as a Growth Mark for a Verdant Response through that claim.")


def _feed_buckets(obj: Any, owner: Any) -> dict[int, int]:
    """Integer turn deadlines/counts encoded as a string; legacy aggregate feed retains its recorded deadline."""
    data = obj.component or {}
    if "feed_schedule" in data:
        buckets = {int(due): int(count) for due, count in json.loads(data["feed_schedule"]).items()}
    else:
        buckets = {int(data.get("feed_until") or 0): int(data.get("feed") or 0)}
    return {due: count for due, count in buckets.items() if due >= int(owner.turns_started) and count > 0}


def _write_feed(engine: Any, obj: Any, owner: Any, buckets: dict[int, int]) -> None:
    _update(engine, obj, owner.entity_id, feed=sum(buckets.values()), feed_until=max(buckets, default=0),
            feed_schedule=json.dumps(buckets, sort_keys=True, separators=(",", ":")))


def _feed(engine: Any, obj: Any, owner: Any) -> int:
    return sum(_feed_buckets(obj, owner).values())


@hook("turn_end")
def root_feed_expiry(engine: Any, actor: Any, *, nominal: bool = False) -> None:
    """Each grant ends at its own deadline; new feed does not renew older feed. Owning Feed rows only."""
    if row(engine, actor, "feed_the_root") is None:
        return
    from .effect_durations import custom_turn_due
    for obj in claims(engine, actor):
        buckets = _feed_buckets(obj, actor)
        remaining = {due: count for due, count in buckets.items() if not custom_turn_due(
            actor, due, actor.turn_flags, obj.object_id + ":feed", nominal=nominal)}
        if sum(remaining.values()) != int((obj.component or {}).get("feed") or 0):
            _write_feed(engine, obj, actor, remaining)


@hook("nominal_slot_boundary")
def nominal_claim_expiry(engine: Any, actor: Any, checkpoint: str) -> None:
    if checkpoint == "END_OF_TURN":
        root_feed_expiry(engine, actor, nominal=True)
    else:
        for obj in claims(engine, actor):
            if int(engine.state.round_number) >= int((obj.component or {}).get("until_round") or 0):
                wither(engine, obj, "its minute is over")


@hook("turn_end")
def claim_mark_expiry(engine: Any, actor: Any) -> None:
    """A Growth Mark placed on a Living Claim ends when the marker's next turn does, exactly as one on a creature does.

    The owner's turn counter is compared against the stored integer deadline, so a mark placed on the owner's own
    turn survives that turn and ends at the end of the turn after it -- the engine's ``END_OF_TURN_AT`` rule. Nothing
    here runs for an actor that owns no claim carrying its own mark, so other characters are unaffected.
    """
    for obj in claims(engine, actor):
        held = ((obj.component or {}).get("growth_marks") or {}).get(actor.entity_id)
        if held and int(actor.turns_started) >= claim_deadline(held, actor):
            place_claim_marks(engine, actor, obj, 0)


# ------------------------------------------------------------------------------------------------ Verdant Responses
def _free_response(engine: Any, owner: Any) -> bool:
    return _state(engine, owner, "grove_domain") and owner.turn_flags.get("verdant_round_grove_free") != _round(engine)


def _cost(engine: Any, owner: Any, response: str) -> int:
    cost = COST[response]
    if response == "bind" and _state(engine, owner, "verdant_incarnation"):
        cost -= 1  # "treat the number of marks spent as one higher"
    return max(1, cost)


def _payments(engine: Any, owner: Any, subject: Any, response: str) -> dict[str, tuple[int, str, int]]:
    """Legal payments (marks, claim ID, feed); pure menu query. A response through a touched claim can mix both pools."""
    payments = {"free": (0, "", 0)} if _free_response(engine, owner) else {}
    cost = _cost(engine, owner, response)
    if marks(subject, owner) >= cost:
        payments["marks"] = (cost, "", 0)
    for obj in touching(engine, subject, owner):
        for feed in range(min(cost, _feed(engine, obj, owner)), 0, -1):
            count = cost - feed
            if marks(subject, owner) >= count:
                key = f"mixed:{count}:{obj.object_id}" if count else f"feed:{obj.object_id}"
                payments[key] = (count, obj.object_id, feed)
    return payments


def _usable(engine: Any, owner: Any, subject: Any, response: str) -> bool:
    if subject is None or not subject.active or engine.state.current_actor_id != owner.entity_id:
        return False
    if owner.turn_flags.get("verdant_response_turn") == _turn(engine):
        return False  # "use no more than one Verdant Response per turn"
    if engine._distance_actor_to_actor(owner, subject) > 60:
        return False
    if response == "thorn" and not in_contact(engine, subject, owner):
        return False
    if response == "shelter" and not (touching(engine, subject, owner) or subject.entity_id == owner.entity_id and medium(engine, owner)):
        return False
    return bool(_payments(engine, owner, subject, response))


def _pay(engine: Any, owner: Any, subject: Any, response: str, source: str, intent: Any = None) -> bool:
    payments = _payments(engine, owner, subject, response)
    if not payments:
        return False
    how = next(iter(payments))  # Preserve AI's existing free/marks-first preference.
    if len(payments) > 1:
        from .choice_prompt import action_context

        labels = {}
        for key, (count, claim_id, feed) in payments.items():
            if key == "free":
                labels[key] = "Use Grove Domain's free response (once per round; spend no Growth Marks or Root Feed)"
                continue
            parts = [f"{count} Growth Mark{'s' if count != 1 else ''} on {subject.display_name}"] if count else []
            if feed:
                obj = engine.state.objects[claim_id]
                parts.append(f"{feed} Root Feed from your claim at square {obj.position.x},{obj.position.y} (used as Growth Marks)")
            labels[key] = "Spend " + " and ".join(parts)
        picked = ask(engine, intent, checkpoint_id(engine, "VERDANT_PAYMENT", owner.entity_id, subject.entity_id), owner,
                     CHOICE + "verdant_payment", list(payments), labels=labels, preferred=[how], target_id=owner.entity_id,
                     name=f"Verdant Response: {_NAMES[response]}",
                     prompt=f"Verdant Response: {_NAMES[response]} on {subject.display_name}. Choose how to pay its "
                            f"{_cost(engine, owner, response)} Growth Mark cost; Root Feed through a claim it touches pays as marks. "
                            "No action; one response per turn.", prompt_context=action_context(engine, owner, source, subject))
        if not picked or picked[0] not in payments:
            return False
        how = picked[0]
    count, claim_id, feed = payments[how]
    if how == "free":
        owner.turn_flags["verdant_round_grove_free"] = _round(engine)
    if count and not spend(engine, owner, subject, count, source):
        return False
    if feed:
        obj = engine.state.objects[claim_id]
        buckets = _feed_buckets(obj, owner)
        left = feed
        for due in sorted(buckets):  # Spend the earliest-expiring feed first.
            used = min(left, buckets[due])
            buckets[due] -= used
            left -= used
        _write_feed(engine, obj, owner, {due: n for due, n in buckets.items() if n})
    return True


_NAMES = {"root": "Root", "bind": "Bind", "shelter": "Shelter", "thorn": "Thorn"}
_TEXT = {"root": "Spend 1 Growth Mark on it: its Speed drops by 10 feet (15 if it touches your Living Claim or you) until the start of "
                 "your next turn",
         "bind": "Spend 2 Growth Marks on it: Strength save or it is Grappled by your growth until the end of your next turn (success: "
                 "Speed -10 this turn)",
         "shelter": SHELTER_EVIDENCE,
         "thorn": "Spend 1 Growth Mark on a creature touching your Living Claim or within 5 feet of you: Piercing damage equal to your "
                  "Proficiency Bonus (more dice at higher Cultivation Levels)"}


@hook('button_description')
def response_description(row: dict[str, Any]) -> str | None:
    """A response's ownership source is Sow; its own text is not Sow's activation.

    Resolve through the shared read-only hook so already sealed current-format
    actions receive the correction too. Other characters' rows are inert.
    """
    response = ((row.get('parameters') or {}).get('typed') or {}).get('verdant_response')
    if not isinstance(response, str) or response not in _TEXT:
        return None
    return (f"Verdant Response: {_NAMES[response]}\n"
            "Use on your turn; no action. Use at most one Verdant Response per turn.\n"
            f"Range: 60 feet\n{_TEXT[response]}.")


@hook("compile_actions")
def verdant_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info.get("owned_ids") or ())
    if SOW not in owned:
        return None
    path = str(((info.get("owner_sheet") or {}).get("identity") or {}).get("path") or "")
    reach = 5 if path.lower().startswith("body") else 30
    pb = int(info["numbers"].get("pb") or 2)
    hp = max(5, 5 + pb + int(info["numbers"].get("key_mod") or 0))
    out = [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.granted.sow_living_claim", owner_id=info["actor_id"],
        display_name="Sow Living Claim", economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=reach,
        parameters={"typed": {"effects": [{"type": "living_claim", "evidence": (
                                  f"Use a Bonus Action to grow a Living Claim, a small patch of your plants, within {reach} feet for "
                                  f"1 minute. It has AC 10 and {hp} Hit Points, takes double Fire damage, and ignores Poison and Psychic "
                                  f"damage. In your square it grows on your body. Keep up to {pb} claims; choose an old one to wither "
                                  "if you grow another. Verdant Responses spend your Growth Marks to slow, bind, shelter or hurt creatures.")}],
                              "numbers": info["numbers"], "duration": {"kind": "minutes", "amount": 1}, "range_ft": reach, "source": SOW,
                              "riders": []}, "expected_damage": 0, "any_cell": True})]
    for response in RESPONSES:
        kind = "ALLY_OR_SELF" if response == "shelter" else "HOSTILE_ENTITY"
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.granted.verdant_{response}", owner_id=info["actor_id"],
            display_name=f"Verdant Response: {_NAMES[response]}", economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind=kind,
            range_ft=60, parameters={"typed": {"effects": [{"type": "verdant_response", "response": response, "applies_to": "target",
                                                            "evidence": _TEXT[response]}],
                                               "numbers": info["numbers"], "duration": {"kind": "instant"}, "range_ft": 60, "source": SOW,
                                               "riders": [], "verdant_response": response},
                                     "expected_damage": 0}))
    return out


def _response_of(action: Any) -> str | None:
    return ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("verdant_response")


@hook("candidate_allowed")
def response_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    response = _response_of(action)
    if response is None:
        return None
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    return None if _usable(engine, actor, target, response) else False


def _response(ctx: Any, target: Any, response: str, *, paid: bool) -> None:
    from dataclasses import replace

    from ..typed_executor import run_effects

    engine, owner = ctx.engine, ctx.actor
    one = replace(ctx, target=target, targets=[target], typed={**ctx.typed, "numbers": {**ctx.numbers, **_numbers(engine, owner)}})
    if response == "root":
        feet = 15 if in_contact(engine, target, owner) else 10
        run_effects(one, [{"type": "speed", "flat": -feet, "applies_to": "target", "duration": "until_start_of_next_turn",
                           "evidence": f"Verdant Response, Root: Speed -{feet} feet until the start of your next turn"}])
    elif response == "bind":
        dc = _numbers(engine, owner)["save_dc"]
        claim = next(iter(touching(engine, target, owner)), None)
        run_effects(replace(one, typed={**one.typed, "numbers": {**one.typed["numbers"], "save_dc": dc}}), [{
            "type": "save", "ability": "str", "applies_to": "target",
            "evidence": "Verdant Response, Bind: the creature makes a Strength saving throw",
            "on_fail": [{"type": "verdant_bind", "claim": claim.object_id if claim is not None else ""}],
            "on_success": [{"type": "speed", "flat": -10, "applies_to": "target", "duration": "until_end_of_turn",
                            "evidence": "Bind: Speed -10 until the end of the current turn"}]}])
    elif response == "thorn":
        cl = _numbers(engine, owner)["cl"]
        dice = 3 if cl >= 17 else 2 if cl >= 11 else 1 if cl >= 5 else 0
        warning = any(c.condition_id == f"condition:typed.verdant_thorned.{target.entity_id}"
                      for c in owner.conditions.values())
        # Sealed saves made before this fix may still carry the old flag on the triggering turn.
        legacy_deadline = int(owner.turn_flags.get(f"verdant_thorned:{target.entity_id}") or 0)
        warning = warning or bool(legacy_deadline and legacy_deadline >= int(owner.turns_started))
        bonus = _numbers(engine, owner)["key_mod"] if warning and row(engine, owner, "thorned_warning") is not None else 0
        damage = {"type": "damage", "applies_to": "target", "flat": _numbers(engine, owner)["pb"] + bonus, "damage_types": ["piercing"],
                  "evidence": "Verdant Response, Thorn: Piercing damage equal to your Proficiency Bonus"
                              + (f" + {dice}d6" if dice else "") + (" + your key modifier (Thorned Warning)" if bonus else "")}
        if dice:
            damage["dice"] = {"count": dice, "sides": 6}
        run_effects(one, [damage])
    elif response == "shelter":
        _shelter(ctx, target)


@effect("verdant_bind")
def verdant_bind(ctx: Any, eff: dict[str, Any]) -> None:
    """Grappled by your growth until the end of your next turn; the escape DC is your Verdant Growth save DC; it ends with its claim."""
    target, owner = ctx.target, ctx.actor
    if target is None or not target.active:
        return
    dc = _numbers(ctx.engine, owner)["save_dc"]
    ctx.engine._apply_condition(target, "condition:typed.grappled", ctx.source, owner.entity_id,
                                expires_on=f"END_OF_SOURCE_TURN_AT:{int(owner.turns_started) + 1}",
                                data={"escape_dc": int(dc), "verdant_bind": 1, "verdant_claim": str(eff.get("claim") or ""),
                                      "label": f"Grappled by {owner.display_name}'s growth (escape DC {dc}) until the end of "
                                               f"{owner.display_name}'s next turn"})


def _shelter(ctx: Any, ally: Any) -> None:
    engine, owner = ctx.engine, ctx.actor
    options = {"cover": f"Half Cover for {ally.display_name}: +2 AC against one attack, or +2 to one Dexterity save" if row(engine, owner, "shelter_grove") is not None else f"Half Cover for {ally.display_name}: +2 AC against its next attack",
               "temp_hp": f"{_numbers(engine, owner)['pb']} Temporary HP for {ally.display_name}",
               "obscure": f"{ally.display_name}'s space Lightly Obscured" + (" for 1 minute (Reed Screen)" if row(engine, owner, "reed_screen") else "")}
    two = row(engine, owner, "shelter_grove") is not None
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "VERDANT_SHELTER", owner.entity_id, ally.entity_id), owner, CHOICE + "verdant_shelter",
                 list(options), labels=options, preferred=["temp_hp", "cover"][:2 if two else 1], minimum=2 if two else 1, maximum=2 if two else 1,
                 default_count=2 if two else 1, target_id=owner.entity_id, name="Shelter",
                 prompt=f"Shelter: choose {'two' if two else 'one'} for {ally.display_name}, until the start of your next turn.")
    picked = [p for p in picked if p in options][:2 if two else 1] or ["temp_hp"]
    if "temp_hp" in picked:
        engine._grant_temp_hp(ally, _numbers(engine, owner)["pb"], ctx.source, owner.entity_id)
    if "cover" in picked:
        cover_scope = "one attack or one Dexterity save" if two else "the next attack"
        engine._apply_condition(ally, "condition:typed.verdant_shelter_cover", ctx.source, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": f"Sheltered by leaves and branches: Half Cover (+2 AC) against {cover_scope}" + (" or +2 to one Dexterity save" if two else "") + ", until "
                                               f"the start of {owner.display_name}'s next turn",
                                      **({"grove_dex_save": 1} if two else {})})
    if "obscure" in picked:
        _screen(ctx, ally)
    if row(engine, owner, "medicinal_sprout") is not None:
        engine._apply_condition(ally, "condition:typed.verdant_medicinal", "TAL_VERDANT_GROWTH_MEDICINAL_SPROUT", owner.entity_id,
                                expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={**({"medicinal_categories": 1} if (row(engine, owner, "medicinal_sprout") or {}).get("medicinal_categories") == 1 else {}),
                                      "label": "Medicinal Sprout: Advantage on the next Constitution save against Poisoned"
                                               + (", disease, exhaustion from environmental exposure, or ongoing poison damage" if
                                                  (row(engine, owner, "medicinal_sprout") or {}).get("medicinal_categories") == 1 else "")
                                               + f" before {owner.display_name}'s next turn"})


def _screen(ctx: Any, ally: Any) -> None:
    from .. import zones
    from ..gate2_runtime_models import ZoneState

    engine, owner = ctx.engine, ctx.actor
    reed = row(engine, owner, "reed_screen") is not None
    claim = next(iter(touching(engine, ally, owner)), None)
    zone = ZoneState(zone_id=f"zone:verdant_screen:{engine.state.event_sequence + 1}", source_definition_id=ctx.source, owner_id=owner.entity_id,
                     center=ally.position, radius_cells=0, affected_cells=(ally.position,), concentration_link=False,
                     duration_rounds=10 if reed else 1, created_round=int(engine.state.round_number),
                     trigger_profile={"kind": zones.KIND, "name": "Reed Screen" if reed else "Shelter: leafy screen", "terrain": [],
                                      "difficult": None, "obscured": "light", "color": zones.terrain_rules().get("default_color"),
                                      "follows_owner": False, "shape": "square", "size_ft": 5, "triggers": [], "move_through": None,
                                      "talents": [], "inside": [], "verdant_claim": claim.object_id if (reed and claim is not None) else "",
                                      "visual": {"material": "foliage"}, "numbers": {}})
    engine.state.zones[zone.zone_id] = zone
    engine._append_event("ZONE_CREATED", ctx.source, actor_id=owner.entity_id, payload={"zone": zone.model_dump(mode="json")})


@effect("verdant_response")
def verdant_response(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    response = str(eff.get("response") or "")
    if target is None or response not in RESPONSES or not _usable(engine, owner, target, response):
        ctx.rider("That Verdant Response cannot be used now.")
        return
    if not _pay(engine, owner, target, response, ctx.source, ctx.intent):
        return
    owner.turn_flags["verdant_response_turn"] = _turn(engine)
    note(engine, ctx.source, owner, f"Verdant Response, {_NAMES[response]}: {owner.display_name} on {target.display_name}.", (target,))
    _response(ctx, target, response, paid=True)
    _branching(ctx, target, response)


def _branching(ctx: Any, target: Any, first: str) -> None:
    """Branching Answer Scripture: "When you use a Verdant Response, choose a second different Verdant Response and apply it to the same
    target ... without spending an additional Growth Mark. Use Branching Answer Scripture once per round.\""""
    engine, owner = ctx.engine, ctx.actor
    if row(engine, owner, "branching_answer") is None or owner.turn_flags.get("verdant_round_branch") == _round(engine) or not target.active:
        return
    hostile = target.team_id != owner.team_id
    options = [r for r in (("root", "bind", "thorn") if hostile else ("shelter",)) if r != first
               and (r != "thorn" or in_contact(engine, target, owner)) and (r != "shelter" or touching(engine, target, owner))]
    if not options:
        return
    labels = {r: f"Also {_NAMES[r]} {target.display_name} (no Growth Mark)" for r in options}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BRANCHING_ANSWER", owner.entity_id, target.entity_id), owner,
                 CHOICE + "branching_answer", options, labels=labels, preferred=options[:1], allow_decline=True, target_id=owner.entity_id,
                 name="Branching Answer Scripture",
                 prompt=f"Branching Answer Scripture (once per round): apply a second, different Verdant Response to {target.display_name} "
                        "without spending another Growth Mark?")
    if not picked or picked[0] not in options:
        return
    owner.turn_flags["verdant_round_branch"] = _round(engine)
    _response(ctx, target, picked[0], paid=False)


@hook("ac")
def shelter_cover(engine: Any, target: Any) -> int:
    return 2 if any(c.condition_id == "condition:typed.verdant_shelter_cover" for c in target.conditions.values()) else 0


@hook("event", nested=True)
def shelter_attack_rolled(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Spend only existing Shelter cover after AC is captured, before later/nested attacks.

    The actual rolled target (including a redirected target) owns the benefit.
    Both hits and misses consume it. No condition means no mutation or event;
    the ordinary expiry still removes cover if no attack is made.
    """
    if event_type != "ATTACK_ROLLED":
        return
    from .rider_support import remove_instance

    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None:
            continue
        for condition in tuple(target.conditions.values()):
            if condition.condition_id == "condition:typed.verdant_shelter_cover":
                remove_instance(engine, target, condition.instance_id, condition.source_definition_id)


@hook("save")
def medicinal_sprout(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if str(ability).upper() != "CON":
        return None
    sprout = next((c for c in subject.conditions.values() if c.condition_id == "condition:typed.verdant_medicinal"), None)
    if sprout is None:
        return None
    # Historical grants retain their original named-Poisoned behavior.
    # Fresh grants use the outcome-aware provider, not recursive condition tags.
    if (sprout.data or {}).get("medicinal_categories") == 1 or "poisoned" not in {str(n).lower() for n in named or ()}:
        return None
    from .rider_support import remove_instance

    remove_instance(ctx.engine, subject, sprout.instance_id, "TAL_VERDANT_GROWTH_MEDICINAL_SPROUT")  # its next such save only
    return {"bonus": 0, "modes": ["ADVANTAGE"]}


@hook("save")
def shelter_grove_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """Shelter-Grove cover also protects against one Dexterity save, then is spent."""
    if str(ability).upper() != "DEX":
        return None
    shelter = next((c for c in subject.conditions.values()
                    if c.condition_id == "condition:typed.verdant_shelter_cover"
                    and int((c.data or {}).get("grove_dex_save") or 0) == 1), None)
    if shelter is None:
        return None
    from .rider_support import remove_instance

    remove_instance(ctx.engine, subject, shelter.instance_id, shelter.source_definition_id)
    return {"bonus": 2, "modes": []}


# ------------------------------------------------------------------------------------------------ events
def _verdants(engine: Any) -> list[Any]:
    rows = getattr(engine, "typed_passive_rows", {}) or {}
    return [actor for actor_id, owned in sorted(rows.items()) if (actor := engine.state.actors.get(actor_id)) is not None and actor.active
            and any(r.get("block") == BLOCK for r in owned)]


@hook("event")
def verdant_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type not in ("OBJECT_UPDATED", "MOVEMENT_COMMITTED", "HEALING_APPLIED"):
        return
    owners = _verdants(engine)
    if not owners:
        return
    if event_type == "OBJECT_UPDATED":
        _claim_damaged(engine, kwargs)
    elif event_type == "MOVEMENT_COMMITTED":
        _moved(engine, owners, kwargs)
    elif event_type == "HEALING_APPLIED":
        _hungry_root(engine, owners, kwargs)
    if event_type in ("OBJECT_UPDATED", "MOVEMENT_COMMITTED"):
        if event_type == "MOVEMENT_COMMITTED":
            _end_binds_without_contact(engine, owners)
        _end_lineage_contact(engine, owners)


def _end_binds_without_contact(engine: Any, owners: list[Any]) -> None:
    """End a Verdant Bind after movement separates its target from every legal medium."""
    from .rider_support import remove_instance

    for owner in owners:
        for holder in engine.state.actors.values():
            for condition in list(holder.conditions.values()):
                data = condition.data or {}
                if (condition.condition_id != "condition:typed.grappled"
                        or condition.source_actor_id != owner.entity_id
                        or not (data.get("verdant_bind") or data.get("verdant_claim"))):
                    continue
                if not in_contact(engine, holder, owner):
                    remove_instance(engine, holder, condition.instance_id, SOURCE)


def _claim_damaged(engine: Any, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    obj = (payload.get("object") or {})
    data = obj.get("component") or {}
    if obj.get("object_kind") != KIND or not int((payload.get("damage") or {}).get("taken") or 0):
        return
    owner = engine.state.actors.get(str(data.get("owner") or ""))
    attacker = engine.state.actors.get(kwargs.get("actor_id"))
    if obj.get("destroyed"):
        stored = engine.state.objects.get(obj.get("object_id"))
        if stored is not None:
            _claim_gone(engine, stored)
    if owner is None or attacker is None or attacker.team_id == owner.team_id or row(engine, owner, "thorned_warning") is None:
        return
    from .. import stealth

    if engine._distance_actor_to_actor(owner, attacker) > 60 or not stealth.sees(engine, owner, attacker):
        return
    place(engine, owner, attacker, 1, "TAL_VERDANT_GROWTH_THORNED_WARNING")  # "place 1 Growth Mark on that creature"
    from .effect_durations import token

    # A normal turn flag is cleared at turn start. The evented condition survives that boundary,
    # refreshes on another qualifying hit, and the shared clock removes it at the printed deadline.
    condition_id = f"condition:typed.verdant_thorned.{attacker.entity_id}"
    source = "TAL_VERDANT_GROWTH_THORNED_WARNING"
    engine._remove_condition(owner, condition_id, source)
    engine._apply_condition(owner, condition_id, source, owner.entity_id,
                            expires_on=token("end", owner.entity_id, int(owner.turns_started) + 1),
                            data={"target": attacker.entity_id,
                                  "label": f"Thorned Warning: Thorn against {attacker.display_name} adds your key ability modifier "
                                           f"when spending its Growth Mark, until the end of {owner.display_name}'s next turn"})
    note(engine, "TAL_VERDANT_GROWTH_THORNED_WARNING", owner, f"Thorned Warning: {attacker.display_name} harmed {owner.display_name}'s "
         "Living Claim and gains a Growth Mark (Thorn on it adds the key modifier until the end of the next turn).", (attacker,))


def _bark_back(engine: Any, owner: Any) -> None:
    pb = _numbers(engine, owner)["pb"]
    before = owner.temporary_hp
    engine._grant_temp_hp(owner, pb, "TAL_VERDANT_GROWTH_BARK_BACK_GUARD", owner.entity_id)
    if owner.temporary_hp > before:
        owner.turn_flags.pop("verdant_round_bark", None)  # supersede a legacy spent grant only on an actual new grant


@hook("after_hit")
def verdant_melee_hit(ctx: Any, target: Any, kind: str) -> None:
    """Only settled melee hits trigger owning Verdant riders, including reach hits."""
    from ..attack_notifications import is_melee_hit

    if not is_melee_hit(ctx):
        return
    engine, attacker = ctx.engine, ctx.actor
    if _state(engine, target, "verdant_incarnation") and row(engine, target, "verdant_incarnation") is not None:
        place(engine, target, attacker, 1, "tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree")
    _bark_back_hit(ctx, target, attacker)


def _bark_back_hit(ctx: Any, owner: Any, attacker: Any) -> None:
    """Bark-Back Guard: "While you have those Temporary HP, the first creature that hits you with a melee attack takes Piercing damage
    equal to your Proficiency Bonus. Use Bark-Back Guard once per round.\""""
    if row(ctx.engine, owner, "bark_back_guard") is None:
        return
    from .temp_hp_grants import grant_at_hit

    grant = grant_at_hit(ctx, owner)
    engine = ctx.engine
    if grant is None or grant[0] != "TAL_VERDANT_GROWTH_BARK_BACK_GUARD":
        return
    if owner.turn_flags.get("verdant_round_bark_spent_grant") == grant[1] or owner.turn_flags.get("verdant_round_bark") == "spent":
        return
    if owner.turn_flags.get("verdant_round_bark_used") == _round(engine):
        return
    owner.turn_flags["verdant_round_bark_used"] = _round(engine)
    owner.turn_flags["verdant_round_bark_spent_grant"] = grant[1]
    engine._commit_damage(attacker, _numbers(engine, owner)["pb"], "PIERCING", "TAL_VERDANT_GROWTH_BARK_BACK_GUARD",
                          owner.entity_id, ctx.intent, reaction_depth=1)
    note(engine, "TAL_VERDANT_GROWTH_BARK_BACK_GUARD", owner,
         f"Bark-Back Guard: {attacker.display_name}'s melee hit triggers {_numbers(engine, owner)['pb']} Piercing damage "
         f"from {owner.display_name}'s protective bark (once per round).", (attacker,))


def _moved(engine: Any, owners: list[Any], kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    mover = engine.state.actors.get(kwargs.get("actor_id"))
    if mover is None or not mover.active:
        return
    for owner in owners:
        if owner.entity_id == mover.entity_id:
            for obj in claims(engine, owner):  # a claim on the owner's body moves with it
                if (obj.component or {}).get("on") == owner.entity_id and obj.position != owner.position:
                    _update(engine, obj.model_copy(update={"position": owner.position}), owner.entity_id)
        if not marks(mover, owner):
            continue
        if (owner.entity_id != mover.entity_id and not payload.get("forced") and not payload.get("reaction")
                and engine.state.current_actor_id == mover.entity_id):
            _root_snare(engine, owner, mover, payload)
        if mover.active and marks(mover, owner):
            _forest_remembers(engine, owner, mover, payload)


def _root_snare(engine: Any, owner: Any, mover: Any, payload: dict[str, Any]) -> None:
    """Root-Snare Step: "When a creature with one of your Growth Marks willingly moves 10 feet or more on its turn, spend 1 Growth Mark.
    The creature makes a Strength saving throw. Failed Save: Its movement ends after the current 5-foot step. Successful Save: Its Speed
    is reduced by 10 feet until the end of the turn." The table has no mid-move stop (census row 12): after a move of 10 feet or more,
    a failure ends its movement there (no movement left this turn)."""
    owned = row(engine, owner, "root_snare_step")
    if owned is None or owned.get("step_snare") or owner.turn_flags.get(f"verdant_round_snare:{mover.entity_id}") == _turn(engine):
        return
    feet = int(payload.get("cost_ft") or 0) or 5 * max(0, len(payload.get("path") or []) - 1)
    if feet < 10:
        return
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "ROOT_SNARE", owner.entity_id, mover.entity_id), owner,
                 CHOICE + "root_snare_step", ["snare"], labels={"snare": f"Spend a Growth Mark: {mover.display_name} makes a Strength save or stops"},
                 prompt=f"Root-Snare Step: {mover.display_name}, bearing your Growth Mark, moved {feet} feet. Spend 1 Growth Mark? On a failed "
                        "Strength save its movement ends; on a success its Speed drops by 10 feet this turn. No action.",
                 preferred=["snare"], allow_decline=True, target_id=owner.entity_id, name="Root-Snare Step")
    if picked != ["snare"] or not spend(engine, owner, mover, 1, "TAL_VERDANT_GROWTH_ROOT_SNARE_STEP"):
        return
    owner.turn_flags[f"verdant_round_snare:{mover.entity_id}"] = _turn(engine)
    from ..typed_executor import run_effects
    from .states import context

    run_effects(context(engine, owner, "TAL_VERDANT_GROWTH_ROOT_SNARE_STEP", [mover], _numbers(engine, owner)), [{
        "type": "save", "ability": "str", "applies_to": "target", "evidence": "Root-Snare Step: Strength saving throw",
        "on_fail": [{"type": "verdant_snared"}],
        "on_success": [{"type": "speed", "flat": -10, "applies_to": "target", "duration": "until_end_of_turn",
                        "evidence": "Root-Snare Step: Speed -10 until the end of the turn"}]}])


@effect("verdant_snared")
def snared(ctx: Any, eff: dict[str, Any]) -> None:
    target = ctx.target
    if target is not None and target.active:
        target.movement_remaining_ft = 0
        note(ctx.engine, "TAL_VERDANT_GROWTH_ROOT_SNARE_STEP", ctx.actor, f"Root-Snare Step: roots catch {target.display_name}; its movement "
             "ends for this turn.", (target,))


@hook("movement_step")
def root_snare_step(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Newly compiled Root-Snare rows answer after each actual five-foot step.

    Count physical distance on the creature's turn, including separate moves;
    difficult terrain costs extra allowance without counting as extra distance.
    Older rows retain their existing post-move behavior. A failed save ends this
    movement, rather than deleting every remaining movement option for the turn.
    """
    if engine.state.current_actor_id != mover.entity_id:
        return None
    owners = [owner for owner in _verdants(engine) if owner is not mover
              and (row(engine, owner, "root_snare_step") or {}).get("step_snare") and marks(mover, owner)]
    if not owners:
        return None
    turn = _turn(engine)
    stored = str(mover.turn_flags.get("auto36_snare_distance") or "")
    prefix, _, distance = stored.rpartition("/")
    feet = (int(distance) if prefix == turn and distance.isdigit() else 0) + 5
    mover.turn_flags["auto36_snare_distance"] = f"{turn}/{feet}"
    if feet < 10:
        return None
    from ..typed_executor import run_effects
    from .states import context

    source = "TAL_VERDANT_GROWTH_ROOT_SNARE_STEP"
    for owner in owners:
        picked = ask(engine, intent, checkpoint_id(engine, "ROOT_SNARE_STEP", owner.entity_id, mover.entity_id, feet), owner,
                     CHOICE + "root_snare_step", ["snare"], allow_decline=True, name="Root-Snare Step", feature_id=source,
                     target_id=mover.entity_id,
                     labels={"snare": "Spend 1 Growth Mark: Strength save; failure stops this movement, success reduces Speed by 10 feet"},
                     prompt=f"Root-Snare Step: {mover.display_name} has moved {feet} feet on its turn. Spend 1 of your Growth Marks "
                            "on it? A failed Strength save stops this movement here; a success reduces its Speed by 10 feet until "
                            "this turn ends. No action or Reaction.")
        if not picked:
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, source, independent=True):
            if not spend(engine, owner, mover, 1, source):
                continue
            ctx = context(engine, owner, source, [mover], _numbers(engine, owner))
            ctx.effect_source = source
            ctx.action = ctx.action.model_copy(update={"source_definition_id": source, "display_name": "Root-Snare Step"})
            ctx.intent = intent
            run_effects(ctx, [{"type": "save", "ability": "str", "applies_to": "target",
                              "on_fail": [{"type": "auto36_stop_growth"}],
                              "on_success": [{"type": "speed", "flat": -10, "applies_to": "target",
                                              "expires_on": "END_OF_CURRENT_TURN", "evidence": "Root-Snare Step: Speed -10 this turn"}]}])
            if ctx.damage_cache.get("auto36_stop_growth"):
                return {"stop": True, "source_id": source, "label": f"Root-Snare Step stops {mover.display_name} after this step."}
    return None


@effect("auto36_stop_growth")
def stop_growth(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.damage_cache["auto36_stop_growth"] = True


@hook("movement_attempt")
def deep_root_boundary(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Deep Root spends owned marks before leaving a square adjacent to a claim."""
    from ..typed_executor import run_effects
    from .states import context

    source = "TAL_VERDANT_GROWTH_DEEP_ROOT_HOLDS_THE_GATE"
    for owner in _verdants(engine):
        if row(engine, owner, "deep_root") is None or marks(mover, owner) < 2:
            continue
        prior = mover.model_copy(update={"position": previous})
        if not any(engine._distance_actor_to_cell(prior, obj.position) == 5 for obj in claims(engine, owner)):
            continue
        picked = ask(engine, intent, checkpoint_id(engine, "DEEP_ROOT", owner.entity_id, mover.entity_id, previous.x, previous.y), owner,
                     CHOICE + "deep_root", ["hold"], allow_decline=True, name="Deep Root Holds the Gate", feature_id=source,
                     target_id=mover.entity_id,
                     labels={"hold": "Spend 2 Growth Marks: Strength save; Restrained on failure, Grappled on success"},
                     prompt=f"Deep Root Holds the Gate: {mover.display_name} attempts to leave a square next to your Living Claim. "
                            "Spend 2 of your Growth Marks on it? A failed Strength save Restrains it until the end of your next "
                            "turn, with another save at each turn's end. A success Grapples it until this turn ends. No action or Reaction.")
        if not picked:
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, source, independent=True):
            if not spend(engine, owner, mover, 2, source):
                continue
            ctx = context(engine, owner, source, [mover], _numbers(engine, owner))
            ctx.effect_source = source
            ctx.action = ctx.action.model_copy(update={"source_definition_id": source, "display_name": "Deep Root Holds the Gate"})
            ctx.intent = intent
            run_effects(ctx, [{"type": "save", "ability": "str", "applies_to": "target",
                              "on_fail": [{"type": "condition", "condition": "restrained", "applies_to": "target",
                                           "duration": "until_end_of_your_next_turn", "repeat_save": {"ability": "STR", "when": "end"},
                                           "evidence": "Deep Root: Restrained until the end of your next turn; repeat save at end of its turn"}],
                              "on_success": [{"type": "condition", "condition": "grappled", "applies_to": "target",
                                              "condition_data": {"reach_ft": None},
                                              "expires_on": "END_OF_CURRENT_TURN", "evidence": "Deep Root: Grappled until this turn ends"}]}])
            # Roots hold the target in place; they do not give the caster a
            # physical grip, a distance expiry or permission to drag it.
            for held in mover.conditions.values():
                if held.source_definition_id == source and held.condition_id == "condition:typed.grappled" and held.data.get("reach_ft") is None:
                    held.data.pop("reach_ft", None)
            return {"stop": True, "source_id": source, "label": f"Deep Root Holds the Gate catches {mover.display_name} before leaving this square."}
    return None


def _forest_remembers(engine: Any, owner: Any, mover: Any, payload: dict[str, Any]) -> None:
    """Forest Remembers the Path: "When a creature with one of your Growth Marks teleports, flies, jumps, or moves through a space within
    60 feet, spend 1 Growth Mark. Choose one space the creature left or entered. Create a Living Claim there if the space can support it."

    Only committed path footprints are evidence; never interpolate teleportation or use the planned/interrupted remainder.
    The 60-foot clause gates the trigger, not the subsequent printed choice of a space left or entered.
    """
    if row(engine, owner, "forest_remembers") is None or not marks(mover, owner):
        return
    from ..gate2_runtime_models import Position
    from .choice_prompt import action_context
    from .needle import cell_id

    path = [Position.model_validate(p) for p in payload.get("path") or []]
    if payload.get("teleport") and path:
        path = [path[0], path[-1]]
    footprints = [set(engine.grid.footprint_cells(p, engine._footprint(mover))) for p in path]
    if len(footprints) < 2 or not any(engine._distance_actor_to_cell(owner, Position(x=x, y=y)) <= 60
                                     for cells in footprints for x, y in cells):
        return
    left, entered = set(), set()
    for before, after in zip(footprints, footprints[1:]):
        left.update(before - after)
        entered.update(after - before)
    # Claims do not block a square, so another creature's occupancy is not an exclusion.
    spaces = {cell_id(p): p for x, y in sorted(left | entered, key=lambda c: (c[1], c[0]))
              if engine.grid.in_bounds((x, y)) and (x, y) not in engine.grid.blocked
              for p in [Position(x=x, y=y)]}
    if ((row(engine, owner, "forest_remembers") or {}).get("perceived_response") == 1
            and (getattr(engine, "typed_control_modes", {}) or {}).get(owner.entity_id) == "LOCAL_AUTO"):
        from ..target_knowledge import can_see
        from ..senses import perceives_cell
        # Optional AI strategy: only the visible final footprint is known here.
        # Committed path data alone does not prove the observer witnessed it.
        if not can_see(engine, owner, mover):
            return
        arrival = set(engine._actor_cells(mover))
        spaces = {key: p for key, p in spaces.items()
                  if (p.x, p.y) in arrival and engine._distance_actor_to_cell(owner, p) <= 60
                  and perceives_cell(engine, owner, p)}
    if not spaces:
        return
    intent = getattr(engine, "_active_intent", None)
    source = "TAL_VERDANT_GROWTH_FOREST_REMEMBERS_THE_PATH"
    action = engine.action_catalog.get(getattr(engine, "_active_action_source_id", None))
    trigger = action.display_name if action is not None else "movement"
    trigger_actor = engine.state.actors.get(getattr(intent, "actor_id", "")) or mover
    labels = {key: f"Spend 1 Growth Mark on {mover.display_name}: sow a Living Claim at square {p.x},{p.y} "
                   f"({'left and entered' if (p.x, p.y) in left & entered else 'left' if (p.x, p.y) in left else 'entered'}); "
                   "lasts 1 minute; no action" for key, p in spaces.items()}
    preferred = cell_id(mover.position)
    if preferred not in spaces:
        preferred = next((key for key, p in spaces.items() if (p.x, p.y) in entered), next(iter(spaces)))
    context = action_context(engine, trigger_actor,
                             action.source_definition_id if action is not None else "system:combat.movement", mover)
    context["action_name"] = trigger
    picked = ask(engine, intent, checkpoint_id(engine, "FOREST_REMEMBERS", owner.entity_id, mover.entity_id), owner,
                 CHOICE + "forest_remembers", list(spaces), labels=labels,
                 prompt=f"Forest Remembers the Path: {mover.display_name} moved during {trigger_actor.display_name}'s {trigger}. "
                        "Movement has resolved. Spend 1 Growth Mark of yours "
                        f"on {mover.display_name} to sow a Living Claim in a square it left or entered? "
                        "Choose a square; the claim lasts 1 minute. No action; movement is not prevented.",
                 preferred=[preferred], allow_decline=True, automatic=marks(mover, owner) >= 2,
                 default="first" if marks(mover, owner) >= 2 else "decline", target_id=owner.entity_id,
                 name="Forest Remembers the Path", feature_id=source, prompt_context=context)
    chosen = spaces.get(picked[0]) if len(picked) == 1 else None
    if chosen is None or not spend(engine, owner, mover, 1, source):
        return
    sow(engine, owner, chosen, source, intent)


HUNGRY = "TAL_VERDANT_GROWTH_HUNGRY_ROOT_DRINKS_THE_SPILL"


def _hungry_root_refuses(engine: Any, owner: Any, target: Any) -> bool:
    """Hungry Root's printed Constitution save for an unwilling creature. True when it refuses, so NO mark is placed.

    One save governs BOTH printed recipients ("you may place 1 Growth Mark on that creature or on the Living
    Claim ... Successful Save: No mark"), so it is resolved before either placement rather than only before the
    mark on the creature. It uses the shared typed save path and the plug-in's flag effect to report the outcome.

    ``save_geometry`` is the documented seam for a save resolved outside an action of its own (ext/__init__.py:
    "Secondary typed saves may set Context.save_geometry"). Hungry Root is a passive, so the context carries no
    action of its own and the inherited action's range would be tested against the wrong creature instead;
    ``effect_source`` names the ability that actually asked for the save, so the roll is recorded against
    Hungry Root rather than against whatever action the context fell back to.
    """
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_verdant_flag")
    from ..typed_executor import run_effects
    from .states import context

    ctx = context(engine, owner, HUNGRY, [target], _numbers(engine, owner))
    ctx.save_geometry = {"origin_ids": [owner.entity_id], "range_ft": 60}
    ctx.effect_source = HUNGRY
    engine.__dict__.pop("_verdant_flag", None)
    run_effects(ctx, [{
        "type": "save", "ability": "con", "applies_to": "target",
        "evidence": "Hungry Root: an unwilling creature's Constitution save",
        "on_fail": [{"type": "verdant_flag", "flag": "hungry_root"}], "on_success": []}])
    return engine.__dict__.pop("_verdant_flag", None) != "hungry_root"


def _hungry_root(engine: Any, owners: list[Any], kwargs: dict[str, Any]) -> None:
    """Hungry Root Drinks the Spill: "When a creature within 60 feet regains HP while touching one of your Living Claims, you may place
    1 Growth Mark on that creature ... If the creature is unwilling, it makes a Constitution saving throw. Successful Save: No mark.\""""
    payload = kwargs.get("payload") or {}
    if int(payload.get("after") or 0) <= int(payload.get("before") or 0):
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        for owner in owners:
            if (target is None or row(engine, owner, "hungry_root") is None or not touching(engine, target, owner)
                    or engine._distance_actor_to_actor(owner, target) > 60):
                continue
            hostile = target.team_id != owner.team_id
            claims_touched = touching(engine, target, owner)
            claim = claims_touched[0] if claims_touched else None
            options = ["mark"] + (["claim"] if claim is not None else [])
            labels = {"mark": f"Place the Growth Mark on {target.display_name}: spend it on one of your Verdant Responses; "
                              f"it lasts until the end of {owner.display_name}'s next turn"}
            if claim is not None:
                labels["claim"] = (f"Place the Growth Mark on your Living Claim at square {claim.position.x},"
                                   f"{claim.position.y} instead of on the creature: it is held on the claim until the end of "
                                   f"{owner.display_name}'s next turn")
            picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "HUNGRY_ROOT", owner.entity_id, target.entity_id),
                         owner, CHOICE + "hungry_root", options, labels=labels,
                         prompt=f"Hungry Root Drinks the Spill: {target.display_name} regained Hit Points while touching your Living Claim. You may "
                                "place 1 Growth Mark on it or on that Living Claim; placing the mark costs no action and uses no resource."
                                + (f" A mark on {target.display_name} can be spent on one of your Verdant Responses" if claim is not None else "")
                                + (f". {target.display_name} is unwilling and makes a Constitution saving throw first; if it succeeds, no mark is "
                                   "placed anywhere." if hostile else ". Your ally does not resist, so the mark is placed as you choose."),
                         preferred=["mark"], allow_decline=True, automatic=hostile, default="first" if hostile else "decline",
                         target_id=owner.entity_id, name="Hungry Root Drinks the Spill")
            if picked == ["claim"] and claim is not None:
                if hostile and _hungry_root_refuses(engine, owner, target):
                    continue
                place_claim_marks(engine, owner, claim, claim_marks(claim, owner) + 1)
                note(engine, HUNGRY, owner,
                     f"A Growth Mark is placed on your Living Claim at square {claim.position.x},{claim.position.y}. It is held "
                     f"there until the end of {owner.display_name}'s next turn; placing it cost no action and no resource.")
                continue
            if picked != ["mark"]:
                continue
            if hostile and _hungry_root_refuses(engine, owner, target):
                continue
            place(engine, owner, target, 1, HUNGRY)


# ------------------------------------------------------------------------------------------------ attacks, damage, forced movement
@hook("before_attack")
def bramble_refusal(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """Bramble Refusal: "When a creature with one of your Growth Marks makes a melee attack against you or an ally adjacent to one of your
    Living Claims, spend 1 Growth Mark. The creature takes 1d8 Piercing damage and makes a Dexterity saving throw. Failed Save: It has
    Disadvantage on the triggering attack.\""""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_verdant_flag")
    if attacker is None or defender is None or engine._distance_actor_to_actor(attacker, defender) > 10:
        return None
    effect_row = context.get("effect") if isinstance(context.get("effect"), dict) else {}
    if "ranged" in str(effect_row.get("attack_kind") or "") or (context.get("range_ft") or 0) > 10:
        return None
    for owner in _verdants(engine):
        if row(engine, owner, "bramble_refusal") is None or owner.team_id != defender.team_id or not marks(attacker, owner):
            continue
        guarded = defender.entity_id == owner.entity_id or any(
            engine.grid.distance_between_cell_sets_ft(tuple(engine._actor_cells(defender)), tuple(_claim_cells(engine, obj))) <= 5
            for obj in claims(engine, owner))
        if not guarded:
            continue
        picked = ask(engine, intent, checkpoint_id(engine, "BRAMBLE_REFUSAL", owner.entity_id, attacker.entity_id), owner,
                     CHOICE + "bramble_refusal", ["bramble"], labels={"bramble": f"Spend a Growth Mark: thorns lash {attacker.display_name}"},
                     prompt=f"Bramble Refusal: {attacker.display_name}, bearing your Growth Mark, attacks {defender.display_name} in melee. Spend "
                            "1 Growth Mark? It takes 1d8 Piercing and makes a Dexterity save or has Disadvantage on this attack. No action.",
                     preferred=["bramble"], allow_decline=True, target_id=owner.entity_id, name="Bramble Refusal")
        if picked != ["bramble"]:
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, "TAL_VERDANT_GROWTH_BRAMBLE_REFUSAL", independent=True):
            if not spend(engine, owner, attacker, 1, "TAL_VERDANT_GROWTH_BRAMBLE_REFUSAL"):
                continue
            from ..typed_executor import run_effects
            from .states import context as state_context

            ctx = state_context(engine, owner, "TAL_VERDANT_GROWTH_BRAMBLE_REFUSAL", [attacker], _numbers(engine, owner))
            engine.__dict__.pop("_verdant_flag", None)
            run_effects(ctx, [{"type": "damage", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "damage_types": ["piercing"],
                               "evidence": "Bramble Refusal: 1d8 Piercing"},
                              {"type": "save", "ability": "dex", "applies_to": "target", "evidence": "Bramble Refusal: Dexterity save",
                               "on_fail": [{"type": "verdant_flag", "flag": "bramble"}], "on_success": []}])
            if engine.__dict__.pop("_verdant_flag", None) == "bramble":
                return {"mode": "DISADVANTAGE"}
            return {}
    return None


@effect("verdant_flag")
def verdant_flag(ctx: Any, eff: dict[str, Any]) -> None:
    """Hand a saving throw's outcome back to the trigger that ran it.

    A typed save resolves inside ``run_effects``, so the caller learns the result through this one flag slot on the
    engine: the ``on_fail`` branch writes its flag name and the caller reads and clears the slot. Bramble Refusal
    ("Disadvantage on the triggering attack") and Hungry Root's unwilling-creature save share this one effect.
    """
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_verdant_flag")
    ctx.engine._verdant_flag = str(eff.get("flag") or "")


@hook("final_damage")
def thorn_crown_reversal(engine: Any, target: Any, amount: int, damage_type: str, source_id: str, source_actor_id: str, intent: Any) -> dict[str, Any] | None:
    """Thorn Crown Reversal: "When a marked enemy deals damage to one of your allies within 60 feet and either the enemy or ally is
    touching one of your Living Claims, spend up to 3 Growth Marks from the enemy. For each mark spent: reduce the damage by your
    Proficiency Bonus; the enemy takes Piercing damage equal to your Proficiency Bonus.\""""
    if amount <= 0:
        return None
    enemy = engine.state.actors.get(source_actor_id or "")
    if enemy is None or not enemy.active:
        return None
    for owner in _verdants(engine):
        if (row(engine, owner, "thorn_crown") is None or owner.team_id != target.team_id or owner.team_id == enemy.team_id
                or target.entity_id == owner.entity_id or not marks(enemy, owner) or engine._distance_actor_to_actor(owner, target) > 60
                or not (touching(engine, enemy, owner) or touching(engine, target, owner))):
            continue
        pb = _numbers(engine, owner)["pb"]
        most = min(3, marks(enemy, owner))
        labels = {str(n): f"Spend {n} Growth Mark{'s' if n > 1 else ''}: {target.display_name} takes {n * pb} less, {enemy.display_name} "
                          f"takes {n * pb} Piercing" for n in range(1, most + 1)}
        need = -(-int(amount) // pb)
        preferred = str(min(most, max(1, need)))
        picked = ask(engine, intent, checkpoint_id(engine, "THORN_CROWN", owner.entity_id, enemy.entity_id), owner, CHOICE + "thorn_crown",
                     list(labels), labels=labels, preferred=[preferred], allow_decline=True, target_id=owner.entity_id,
                     name="Thorn Crown Reversal",
                     prompt=f"Thorn Crown Reversal: {enemy.display_name}, bearing your Growth Marks, deals {amount} damage to {target.display_name}. "
                            "Spend up to 3 of its marks? No action.")
        if not picked or picked[0] not in labels:
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, "TAL_VERDANT_GROWTH_THORN_CROWN_REVERSAL", independent=True):
            spent = int(picked[0])
            spend(engine, owner, enemy, spent, "TAL_VERDANT_GROWTH_THORN_CROWN_REVERSAL")
            from ..typed_executor import run_effects
            from .states import context

            run_effects(context(engine, owner, "TAL_VERDANT_GROWTH_THORN_CROWN_REVERSAL", [enemy], _numbers(engine, owner)),
                        [{"type": "damage", "applies_to": "target", "flat": spent * pb, "damage_types": ["piercing"],
                          "evidence": f"Thorn Crown Reversal: {spent} x your Proficiency Bonus Piercing"}])
            return {"amount": max(0, int(amount) - spent * pb)}
    return None


@hook("forced_movement_reduction")
def willow_bend(ctx: Any, subject: Any) -> int | None:
    """Willow-Bend Defense: "When you are pushed, pulled ... while touching a Living Medium, reduce the forced movement by 10 feet. If this
    reduces the movement to 0, place 1 Growth Mark on the creature or effect's origin if you can perceive it and it is within 60 feet.\""""
    engine = ctx.engine
    if row(engine, subject, "willow_bend") is None or not medium(engine, subject) or ctx.actor is subject:
        return None
    left = ctx.forced_movement_distance_ft
    if left is not None and int(left) <= 10 and ctx.actor.team_id != subject.team_id and engine._distance_actor_to_actor(ctx.actor, subject) <= 60:
        key = f"willow_bend:{subject.entity_id}"
        if not ctx.damage_cache.get(key):
            ctx.damage_cache[key] = True
            place(engine, subject, ctx.actor, 1, "TAL_VERDANT_GROWTH_WILLOW_BEND_DEFENSE")
    return 10


@hook("after_hit")
def staff_becomes_branch(ctx: Any, target: Any, kind: str) -> None:
    """Staff Becomes Branch: "Once per turn when you hit with a weapon made mostly of wood, place 1 Growth Mark on the target.\""""
    engine, owner = ctx.engine, ctx.actor
    if kind != "weapon" or row(engine, owner, "staff_branch") is None or target is None or not target.active:
        return
    name = f"{ctx.action.display_name} {(ctx.typed or {}).get('weapon_source_id') or ''}".lower()
    if not any(word in name for word in WOOD) or owner.turn_flags.get("verdant_round_staff") == _turn(engine):
        return
    owner.turn_flags["verdant_round_staff"] = _turn(engine)
    place(engine, owner, target, 1, "TAL_VERDANT_GROWTH_STAFF_BECOMES_BRANCH", ctx.intent)


# ------------------------------------------------------------------------------------------------ turns
@hook("turn_start")
def verdant_turn_start(engine: Any, actor: Any) -> None:
    owners = _verdants(engine)
    if not owners:
        return
    for owner in owners:
        if owner.entity_id == actor.entity_id:
            for obj in claims(engine, owner):
                if int(engine.state.round_number) >= int((obj.component or {}).get("until_round") or 0):
                    wither(engine, obj, "its minute is over")
            scorched = next((c for c in owner.conditions.values() if c.condition_id == "condition:typed.verdant_scorched"), None)
            skip_incarnation = scorched is not None
            if scorched is not None:
                from .rider_support import remove_instance
                remove_instance(engine, owner, scorched.instance_id, scorched.source_definition_id)
            if (_state(engine, owner, "grove_domain") and row(engine, owner, "grove_domain") is not None) or \
                    (_state(engine, owner, "verdant_incarnation") and row(engine, owner, "verdant_incarnation") is not None
                     and not skip_incarnation):
                sow(engine, owner, owner.position, "TAL_VERDANT_GROWTH_GROVE_DOMAIN_COURT_OF_ROOT_AND_BRANCH"
                    if _state(engine, owner, "grove_domain") else "tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree",
                    on="" if _state(engine, owner, "grove_domain") else owner.entity_id)
            continue
        if not touching(engine, actor, owner):
            continue
        if actor.team_id != owner.team_id:
            if _state(engine, owner, "grove_domain"):
                place(engine, owner, actor, 1, "TAL_VERDANT_GROWTH_GROVE_DOMAIN_COURT_OF_ROOT_AND_BRANCH")
            if row(engine, owner, "rooted_lineage") is not None and marks(actor, owner):
                from ..typed_executor import run_effects
                from .states import context

                run_effects(context(engine, owner, "tianxia.talent.verdant_growth.rooted_lineage_scripture", [actor]),
                            [{"type": "speed", "flat": -5, "applies_to": "target", "duration": "until_end_of_turn",
                              "evidence": "Rooted Lineage Scripture: a marked enemy starting its turn on your Living Claim: Speed -5 this turn"}])
        elif _state(engine, owner, "grove_domain"):
            engine._grant_temp_hp(actor, _numbers(engine, owner)["pb"], "TAL_VERDANT_GROWTH_GROVE_DOMAIN_COURT_OF_ROOT_AND_BRANCH", owner.entity_id)


@hook("zones", present=lambda engine: any(_state(engine, owner, "grove_domain") for owner in _verdants(engine)))
def grove_ground(engine: Any) -> list[Any] | None:
    """Grove Domain: "enemies treat spaces containing your Living Claims as difficult terrain"."""
    from .. import zones
    from ..gate2_runtime_models import Position, ZoneState

    out = []
    for owner in _verdants(engine):
        if not _state(engine, owner, "grove_domain"):
            continue
        cells = sorted({cell for obj in claims(engine, owner) for cell in _claim_cells(engine, obj)})
        if not cells:
            continue
        out.append(ZoneState(
            zone_id=f"zone:aura:{owner.entity_id}:verdant_grove_claims", source_definition_id="TAL_VERDANT_GROWTH_GROVE_DOMAIN_COURT_OF_ROOT_AND_BRANCH",
            owner_id=owner.entity_id, center=owner.position, radius_cells=0, affected_cells=tuple(Position(x=x, y=y) for x, y in cells),
            concentration_link=False, duration_rounds=None, created_round=0,
            trigger_profile={"kind": zones.KIND, "name": "Grove Domain: Living Claims are difficult terrain for enemies", "terrain": [],
                             "difficult": "hostile", "obscured": None, "color": zones.terrain_rules().get("default_color"), "follows_owner": False,
                             "shape": "painted", "size_ft": 5, "triggers": [], "move_through": None, "talents": [], "inside": [], "aura": True,
                             "visual": {"material": "foliage"}, "numbers": {}}))
    return out or None


@hook("candidate_allowed")
def thousand_root_prison(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Thousand-Root Prison: "Target: One creature with at least 3 of your Growth Marks"."""
    if ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") != "TAL_VERDANT_GROWTH_THOUSAND_ROOT_PRISON" \
            or not is_verdant(engine, actor):  # a saved fight's older bundle keeps its old targeting
        return None
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    return None if target is not None and marks(target, actor) >= 3 else False


@hook("ai_candidate_allowed")
def ai_keeps_claims(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI sows only where a claim helps: on itself, or next to a hostile creature."""
    if not str(getattr(action, "source_definition_id", "")).endswith(".granted.sow_living_claim"):
        return None
    aim = getattr(candidate, "destination", None)
    if aim is None:
        return False
    if (aim.x, aim.y) in set(engine._actor_cells(actor)):
        return None
    near_foe = any(other.active and other.team_id != actor.team_id and engine.grid.distance_ft(aim, other.position) <= 0
                   for other in engine.state.actors.values())
    return None if near_foe else False
