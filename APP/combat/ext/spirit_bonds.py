"""Spirit Companions: the bonded spirit's table riders (rider lane C9, 2026-09-30).

Rules text (owner's Sphere Compendium, "Sphere of Spirit Companions", authority/typed_mechanics/rules_text.json):

  Bond Strain         "Bond Strain measures stress ... in the bond. Bond Strain ranges from 0 to 3." At 3 the GM runs a crisis.
                      A counter on the cultivator (resource:named.bond_strain, 0-3; its printed maximum is in
                      resource_definitions.jsonl). Only the table-visible gains/losses below move it; the crisis stays the GM's.
  Battle Manifestation "If the manifestation is destroyed, the spirit ... retreats and gains Bond Strain 1. It cannot manifest
                      again until you finish a short rest or make an appropriate Offering unless you spend 2 CP to call it back
                      sooner." -> +1 Bond Strain when the Bonded Spirit is destroyed; "Call Back Bonded Spirit" (Action, 2 CP)
                      while it is destroyed. Manifesting takes an Action: Spirit Domain's "your bonded spirits can manifest
                      without using an Action" is the sphere's own statement of that (a reading).
  Spirit Recall       "As a Bonus Action, call a bonded spirit within 60 feet back to ... your side. If the spirit is willing and
                      not restrained, banished, sealed, or incapacitated, it immediately moves to the chosen legal location. This
                      movement does not provoke opportunity attacks ... At Foundation Realm, the range becomes 120 feet."
                      -> effect "spirit_recall": the player picks the square beside them; the spirit teleports there (the
                      ordinary typed teleport, so a sealed spirit -- a teleport ban -- stays).
                      -> "At Core Formation Realm, the spirit may be recalled from up to 1 mile if it is not in combat."
                      -> _recallable combines the printed range with that one-mile clause (so a distant spirit is never
                      hidden by a near one) and _recalled asks the owner about a fight the table cannot see, where only
                      an explicit "it is not in a fight" lets a distant spirit come.
  Guardian Spirit Posture "When your bonded spirit is within 10 feet of you or a protected ally ... Until the start of your next
                      turn, the first attack against the protected creature has Disadvantage, or the protected creature gains a
                      bonus to AC equal to your Proficiency Bonus against that attack. Choose when the posture is activated.
                      If the spirit's Nature is Guardian, Ancestor, Shield, Mountain, Shrine, Beast, or similar, the protected
                      creature also gains Temporary HP equal to your Proficiency Bonus."
                      -> effect "spirit_guard" (mode "disadvantage" | "ac"), one button per choice; the target must be within
                      10 feet of the user's active Bonded Spirit. The first attack roll against it uses the guard up. The
                      Temporary HP sentence belongs to BOTH choices and rides the same row as "nature_bonus"; a spirit's
                      Nature is a character fact the table cannot read, so the owner is asked once per posture.
  Spirit Intercession "you may use your Reaction to impose Disadvantage on the attack if you are within 30 feet of the spirit ...
                      If the attack still hits, increase Bond Strain by 1 unless you spend 1 CP." -> the generic ally_attacked
                      row and attack-scoped price live in spirit_intercession.py. This module supplies the shared
                      Bond Strain resource and recovery; no second eligibility or price hook is registered here.
  Shared Senses      "As an Action, you may share senses with a bonded spirit within 1 mile." -> candidate_allowed: a
                      cultivator who has learned the sphere's bond (Battle Manifestation or Covenant Spirit) and has no
                      Bonded Spirit to share with gets no button. Without the bond the ability is untouched.
  Pact-Brother Battle Rhythm "Once per round, when you damage a creature that your spirit damaged since the start of your last
                      turn, or when your spirit damages a creature you damaged since the start of your last turn, choose one:
                      reduce Bond Strain by 1 if the attack served the spirit's Nature; grant the next attack against that creature
                      Advantage; move yourself or the spirit up to 10 feet without provoking opportunity attacks; allow the spirit
                      to Help you as a Reaction." -> damage_dealt hook, asked of the cultivator; the four choices, their button wording
                      and every mechanical number they deliver are read from the talent's own typed record (_pact_choices and the
                      delivery helpers _pact_strain / _pact_feet / _pact_expiry), so that record is the one source of truth and editing
                      it changes play instead of drifting from it. "Your last turn" is read as the
                      cultivator's latest turn that has already begun before this one (on its own turn: the turn before), so the
                      spirit's blow on its turn -- right after yours -- counts on your next turn. Help (5.5e): Advantage on your
                      next attack roll against that creature before the start of the spirit's next turn; the target must be
                      within 5 feet of the spirit, and the spirit spends its Reaction. A Blow that lands the trigger is
                      already rolled, and the engine spends an attack_mode_vs benefit (the Vex shape) on the next roll
                      against that creature, so a Help asked for by an attack is kept in the Binder's turn_flags and written
                      by the attack_resolved hook, after the executor's own sweep and before any later roll.

Hooks: compile_block (block "spirit_bond"), compile_resources, compile_actions, candidate_allowed,
damage_dealt, attack_resolved, event. Effects: spirit_recall, spirit_guard, spirit_call_back.
Every hook returns early unless the creature owns the row or holds this plug-in's own condition: other characters and
fights saved before are unaffected. Public helpers: bonded_spirits, strain, add_strain.
"""

from __future__ import annotations

from typing import Any

from . import effect, effect_durations, hook, note
from .spirit_bond_state import STRAIN, STRAIN_MAX, add_strain, strain

PREFIX = "tianxia.talent.spirit_companions."
MANIFESTATION = PREFIX + "battle_manifestation"
INTERCESSION = PREFIX + "spirit_intercession"
PACT = PREFIX + "pact_brother_battle_rhythm"
RECALL = PREFIX + "spirit_recall"
GUARDIAN = PREFIX + "guardian_spirit_posture"
SHARED_SENSES = PREFIX + "shared_senses"
COVENANT = PREFIX + "covenant_spirit"
BOND_TALENTS = frozenset({MANIFESTATION, COVENANT})
GROUP = "bonded_spirit"
BLOCK = "spirit_bond"
GUARD = "condition:typed.spirit_guard"
PACT_USED = "spirit_pact_round_used"
# A Help asked for by an attack that had already rolled, kept until that roll is over (pact_help_delivered).
# No "_round_" in the name on purpose: the engine keeps only those turn flags across a turn, so an unspending
# marker can never outlive the turn it was written in.
PACT_HELP = "spirit_pact_help_pending"
FOUNDATION_CL = 5  # Foundation Realm begins at CL 5 (the realm bands the other Spirit Companions CL gates use)


# ------------------------------------------------------------------------------------------------ ownership
@hook("compile_block")
def spirit_bond_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    # choice_owner: a player controlling the cultivator is asked on other creatures' turns too (the spirit's blow).
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "choice_owner": True}] if block == BLOCK else None


def _kinds(engine: Any, actor_id: str) -> set[str]:
    return {str(row.get("kind")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor_id, [])
            if row.get("block") == BLOCK}


def bonded_spirits(engine: Any, owner: Any) -> list[Any]:
    """The owner's Bonded Spirits on the map now (combat/rules/summons.json group "bonded_spirit")."""
    from .. import summons

    return [creature for creature in summons.owned_by(engine, owner.entity_id, GROUP)
            if creature.active and (creature.summon or {}).get("status") == "present"]


def _destroyed_spirits(engine: Any, owner: Any) -> list[Any]:
    from .. import summons

    return [creature for creature in summons.owned_by(engine, owner.entity_id, GROUP)
            if (creature.summon or {}).get("status") == "destroyed"]


def _owner_of(engine: Any, creature: Any) -> Any | None:
    record = getattr(creature, "summon", None) or {}
    return engine.state.actors.get(record.get("owner") or "") if record.get("group") == GROUP else None


# ------------------------------------------------------------------------------------------------ Bond Strain
@hook("compile_resources")
def bond_strain_pool(info: dict[str, Any]) -> list[Any] | None:
    owned = set(info.get("owned_ids") or ())
    if not owned & {MANIFESTATION, INTERCESSION, PACT}:
        return None
    from ..gate2_runtime_models import ResourceDefinition

    return [ResourceDefinition(resource_id=STRAIN, initial=0, maximum=STRAIN_MAX)]


# ------------------------------------------------------------------------------------------------ Battle Manifestation
@hook("compile_actions")
def call_back_action(info: dict[str, Any]) -> list[Any] | None:
    owned = set(info.get("owned_ids") or ())
    passives = info.get("passives")
    if INTERCESSION in owned and isinstance(passives, list) and not any(row.get("feature_id") == INTERCESSION for row in passives):
        # Spirit Intercession's "pay 1 CP or take 1 Bond Strain" is asked on the attacker's turn: the player is the chooser.
        passives.append({"feature_id": INTERCESSION, "block": BLOCK, "kind": "intercession", "name": "Spirit Intercession",
                         "choice_owner": True})
    if MANIFESTATION not in owned:
        return None
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.spirit_bond.call_back", display_name="Call Back Bonded Spirit",
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=None,
        costs=((pool, 2),),
        parameters={"typed": {"sphere": "tianxia.sphere.spirit_companions", "source": MANIFESTATION,
                              "effects": [{"type": "spirit_call_back"}], "numbers": info.get("numbers") or {},
                              "duration": {"kind": "instant"}, "riders": []},
                    "spirit_call_back": True, "summon_group": GROUP, "expected_damage": 0,
                    "description": "Battle Manifestation: your Bonded Spirit was destroyed; spend 2 CP to call it back now instead of "
                                   "waiting for a short rest. It appears beside you with full Hit Points."})]


@effect("spirit_call_back")
def spirit_call_back(ctx: Any, row: dict[str, Any]) -> None:
    from .. import summons

    if not _destroyed_spirits(ctx.engine, ctx.actor):
        return
    arrived = summons.summon(ctx.engine, ctx.actor, GROUP, ctx.source)
    if arrived:
        note(ctx.engine, ctx.source, ctx.actor, f"Battle Manifestation: {ctx.actor.display_name} spends 2 CP and calls the Bonded Spirit back.",
             tuple(arrived))


@hook("event", nested=True)
def spirit_destroyed(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"If the manifestation is destroyed, the spirit ... retreats and gains Bond Strain 1"."""
    # New dying-rule fights deliver nested lifecycle events (e.g. turn-start
    # zone damage). Destruction must still strain the bond exactly once; keep
    # absent-rule saves on their historical non-nested subscription.
    if getattr(engine, "_ext_event_depth", 0) > 1 and engine.state.rules.get("zero_hp") != "dying_2024":
        return
    if event_type != "ENTITY_DEFEATED":
        return
    creature = engine.state.actors.get(kwargs.get("actor_id") or "")
    owner = _owner_of(engine, creature) if creature is not None else None
    if owner is None or (creature.summon or {}).get("source") != MANIFESTATION or STRAIN not in owner.resources:
        return
    add_strain(engine, owner, 1, MANIFESTATION, f"Battle Manifestation: {creature.display_name} is destroyed and retreats.")


# ------------------------------------------------------------------------------------------------ candidates
@hook("candidate_allowed")
def spirit_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    if params.get("spirit_call_back"):
        return None if _destroyed_spirits(engine, actor) and not bonded_spirits(engine, actor) else False
    typed = params.get("typed") or {}
    kinds = {row.get("type") for row in typed.get("effects") or () if isinstance(row, dict)}
    if "spirit_recall" in kinds:
        return None if _recallable(engine, actor, typed.get("numbers") or {}) else False
    if "spirit_guard" in kinds:
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", ()) or ()), "") or "")
        return None if target is not None and _guard_spirit(engine, actor, target) is not None else False
    if typed.get("source") == SHARED_SENSES and _bond_learned(engine, actor):
        # "you may share senses with a bonded spirit within 1 mile": with the bond learned and no spirit to share
        # with, the button has nothing to do. A cultivator who has not learned the sphere's bond keeps the button
        # exactly as it was -- the printed "with a bonded spirit" is not something the table can settle for them.
        return None if _any_spirit(engine, actor) else False
    return None


def _bond_learned(engine: Any, owner: Any) -> bool:
    """True when this cultivator owns the sphere's bond, so a Bonded Spirit is something they can have.

    Read from the owner's own compiled actions (their typed source), which is the same ``owned_ids`` fact the
    compile-time hooks use; a creature with neither talent is untouched.
    """
    return any(str(((getattr(action, "parameters", None) or {}).get("typed") or {}).get("source") or "") in BOND_TALENTS
               for action in engine.action_catalog.values() if action.owner_id == owner.entity_id)


def _any_spirit(engine: Any, owner: Any) -> list[Any]:
    """Every Bonded Spirit this owner has, manifest or not (a withdrawn spirit can still share senses)."""
    from .. import summons

    return [creature for creature in summons.owned_by(engine, owner.entity_id, GROUP)
            if (creature.summon or {}).get("source") == MANIFESTATION]


# ------------------------------------------------------------------------------------------------ Spirit Recall
def _recall_range(numbers: dict[str, Any]) -> int:
    return 120 if int(numbers.get("cl") or 1) >= FOUNDATION_CL else 60


CORE_FORMATION_CL = 10  # Core Formation Realm begins at CL 10
ONE_MILE_FT = 5280


def _free_to_move(creature: Any) -> bool:
    from .needle import incapacitated

    return not incapacitated(creature) and not any(c.condition_id.endswith(".restrained") for c in creature.conditions.values())


def _recallable(engine: Any, owner: Any, numbers: dict[str, Any]) -> list[Any]:
    """Every Bonded Spirit this order can reach: within the printed range, or -- at Core Formation Realm -- within one
    mile and out of combat. The two sets are combined, so a distant spirit is never hidden by a nearby one."""
    reach = _recall_range(numbers)
    long_range = int(numbers.get("cl") or 1) >= CORE_FORMATION_CL
    recalled = [spirit for spirit in bonded_spirits(engine, owner) if _free_to_move(spirit)
                and (engine._distance_actor_to_actor(owner, spirit) <= reach
                     or (long_range and _distant_free(engine, owner, spirit)))]
    return recalled


def _distant_free(engine: Any, owner: Any, spirit: Any) -> bool:
    """"At Core Formation Realm, the spirit may be recalled from up to 1 mile if it is not in combat": beyond the
    printed range, no further than a mile, and no hostile the table can see is on it."""
    return (engine._distance_actor_to_actor(owner, spirit) <= ONE_MILE_FT
            and not _in_combat(engine, spirit))


def _recalled(engine: Any, owner: Any, numbers: dict[str, Any]) -> list[Any]:
    """The eligible spirits once the owner has answered for any that are only eligible at one mile.

    "if it is not in combat" is a fact about a scene the table may not be looking at, so a spirit beyond the
    printed range is asked about rather than assumed, and only an explicit "it is not in a fight" makes one
    recallable: unanswered or declined leaves it where it is, which is the safe reading of a state the table
    cannot see."""
    reach = _recall_range(numbers)
    eligible = _recallable(engine, owner, numbers)
    near = [spirit for spirit in eligible if engine._distance_actor_to_actor(owner, spirit) <= reach]
    far = [spirit for spirit in eligible if engine._distance_actor_to_actor(owner, spirit) > reach]
    return near + [spirit for spirit in far if _answered_free(engine, owner, spirit, reach)]


def _answered_free(engine: Any, owner: Any, spirit: Any, reach: int) -> bool:
    """Whether the owner has said this distant spirit is not in a fight. Nobody answered is not yes."""
    from .needle import CHOICE, ask, checkpoint_id

    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "SPIRIT_IN_COMBAT", owner.entity_id, spirit.entity_id),
                 owner, CHOICE + "spirit_in_combat", ["in_combat", "free"],
                 labels={"in_combat": f"{spirit.display_name} is in a fight right now: it cannot be recalled",
                         "free": f"{spirit.display_name} is not in a fight: recall it from up to a mile away"},
                 automatic=False, allow_decline=True, default="decline", name="Spirit Recall", feature_id=RECALL,
                 target_id=spirit.entity_id,
                 prompt=f"Spirit Recall: {spirit.display_name} is more than {reach} feet away, so it can only be "
                        f"recalled from up to a mile and only if it is not in combat. The table cannot see where it "
                        f"is -- is it in a fight right now?")
    return bool(chosen) and chosen[0] == "free"


def _in_combat(engine: Any, spirit: Any) -> bool:
    """A hostile within the spirit's own command range, summoned or not: the engine-visible half of the printed
    "not in combat". What the table cannot see is a fight somewhere else on the map, so the owner is asked about
    that when it matters (``_recalled``); this only answers for hostiles that are here."""
    reach = int((spirit.summon or {}).get("command_range_ft") or 60)
    return any(other.active and other.team_id != spirit.team_id
               and engine._distance_actor_to_actor(spirit, other) <= reach
               for other in engine.state.actors.values())


def _beside(engine: Any, owner: Any, spirit: Any) -> list[Any]:
    """Squares within 5 feet of the owner where the spirit may stand (its own square included when it already is beside you)."""
    from ..gate2_runtime_models import Position

    footprint = engine._footprint(spirit)
    occupied = engine._occupied_cells_except(spirit.entity_id)
    out = []
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            x, y = owner.position.x + dx, owner.position.y + dy
            if x < 0 or y < 0 or not engine.grid.in_bounds((x, y)):
                continue
            cell = Position(x=x, y=y)
            if cell == owner.position or engine.grid.distance_ft(owner.position, cell) > 5:
                continue
            if engine.grid.placement_legal(cell, footprint=footprint, occupied_cells=occupied):
                out.append(cell)
    return sorted(out, key=lambda cell: (engine.grid.distance_ft(spirit.position, cell), cell.y, cell.x))


@effect("spirit_recall")
def spirit_recall(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import cell_id, position_of
    from .rider_choices import pick
    from .rider_support import teleport

    engine, owner = ctx.engine, ctx.actor
    spirits = _recalled(engine, owner, ctx.numbers)
    if not spirits:
        note(engine, ctx.source, owner, "Spirit Recall: no Bonded Spirit within range is free to come (restrained, "
                                        "incapacitated, in combat, or more than a mile away).")
        return
    spirit = spirits[0]
    if len(spirits) > 1:
        chosen = pick(engine, owner, "spirit_recall_which", "Spirit Recall", [s.entity_id for s in spirits], subject=owner,
                      labels={s.entity_id: f"Recall {s.display_name}" for s in spirits}, optional=False)
        spirit = next((s for s in spirits if s.entity_id in chosen), spirit)
    cells = _beside(engine, owner, spirit)
    if not cells:
        note(engine, ctx.source, owner, f"Spirit Recall: no free square beside {owner.display_name} for {spirit.display_name}.")
        return
    options = [cell_id(cell) for cell in cells[:16]]
    labels = {cell_id(cell): f"{spirit.display_name} to {cell.x},{cell.y}" for cell in cells[:16]}
    chosen = pick(engine, owner, "spirit_recall", "Spirit Recall", options, subject=spirit, labels=labels, optional=False,
                  trigger=f"call {spirit.display_name} to your side (no Opportunity Attacks)")
    destination = position_of(chosen[0]) if chosen else cells[0]
    if teleport(ctx, spirit, destination):
        note(engine, ctx.source, owner, f"Spirit Recall: {spirit.display_name} folds through the bond to {owner.display_name}'s side.",
             (spirit.entity_id,))


# ------------------------------------------------------------------------------------------------ Guardian Spirit Posture
def _guard_spirit(engine: Any, owner: Any, protected: Any) -> Any | None:
    """The owner's Bonded Spirit within 10 feet of the protected creature and within its command range, if any (the spirit
    guards you or an ally, not itself)."""
    for spirit in bonded_spirits(engine, owner):
        if spirit.entity_id == protected.entity_id:
            continue
        command = int((spirit.summon or {}).get("command_range_ft") or 60)
        if engine._distance_actor_to_actor(spirit, protected) <= 10 and engine._distance_actor_to_actor(owner, spirit) <= command:
            return spirit
    return None


@effect("spirit_guard")
def spirit_guard(ctx: Any, row: dict[str, Any]) -> None:
    """The printed posture choice, plus its printed Nature rider (``nature_bonus`` on this same row).

    "If the spirit's Nature is Guardian, Ancestor, Shield, Mountain, Shrine, Beast, or similar, the protected creature
    also gains Temporary HP equal to your Proficiency Bonus" applies to EITHER posture choice, and a spirit's Nature is
    a character fact the table cannot read, so the owner is asked once per posture whether it is one of the printed
    kinds; a "yes" grants the printed Temporary HP on the protected creature."""
    engine, owner = ctx.engine, ctx.actor
    protected = ctx.target if ctx.target is not None else owner
    spirit = _guard_spirit(engine, owner, protected)
    if spirit is None:
        return
    mode = "ac" if row.get("mode") == "ac" else "disadvantage"
    amount = int(ctx.numbers.get("pb") or owner.proficiency_bonus or 2)
    for iid, held in list(protected.conditions.items()):
        if held.condition_id == GUARD and held.source_actor_id == owner.entity_id:
            _end_guard(engine, protected, iid, ctx.source)  # a new Guard replaces this user's unspent one
    text = (f"the first attack roll against it has Disadvantage" if mode == "disadvantage"
            else f"+{amount} AC against the first attack roll against it")
    modifier_id = ""
    if mode == "disadvantage":  # a modifier the engine's own attack-mode rule reads, for every attacker (typed or not)
        modifier_id = f"modifier:{ctx.source}:{protected.entity_id}:{engine.state.event_sequence + 1}"
        engine._add_modifier(protected, ctx.source, "incoming_attack_mode", "SET", "DISADVANTAGE", "NEXT_ATTACK",
                             expires_on="START_OF_SOURCE_NEXT_TURN")
    engine._apply_condition(protected, GUARD, ctx.source, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"mode": mode, "amount": amount if mode == "ac" else 0, "modifier_id": modifier_id,
                                  "label": f"Spirit Guard ({owner.display_name}'s spirit): {text}, until the start of {owner.display_name}'s next turn"})
    note(engine, ctx.source, owner, f"Guardian Spirit Posture: {owner.display_name}'s spirit guards {protected.display_name} -- {text}.",
         (protected.entity_id,))
    _nature_bonus(ctx, row, spirit, protected, amount)


def _nature_bonus(ctx: Any, row: dict[str, Any], spirit: Any, protected: Any, amount: int) -> None:
    """The posture row's printed Nature rider, asked of the player: does this spirit's Nature earn the extra benefit?"""
    bonus = row.get("nature_bonus") or {}
    kinds = [str(kind) for kind in bonus.get("natures") or ()]
    if str(bonus.get("temp_hp") or "") != "pb" or not kinds:
        return
    from .needle import CHOICE, ask, checkpoint_id

    options = ["yes", "no"]
    labels = {"yes": f"{spirit.display_name}'s Nature is one of the printed kinds: {protected.display_name} gains "
                     f"{amount} Temporary HP",
              "no": f"{spirit.display_name}'s Nature is not one of them: no extra Temporary HP"}
    chosen = ask(ctx.engine, getattr(ctx.engine, "_active_intent", None),
                 checkpoint_id(ctx.engine, "GUARDIAN_NATURE", ctx.actor.entity_id, protected.entity_id),
                 ctx.actor, CHOICE + "guardian_nature", options, labels=labels, automatic=False, allow_decline=True,
                 default="decline", name="Guardian Spirit Posture", feature_id=GUARDIAN, target_id=protected.entity_id,
                 prompt=f"Guardian Spirit Posture: is {spirit.display_name}'s Nature {' or '.join(kinds)}, or similar? "
                        f"If it is, {protected.display_name} also gains {amount} Temporary HP.")
    if not chosen or chosen[0] != "yes":
        return
    ctx.engine._grant_temp_hp(protected, amount, ctx.source, ctx.actor.entity_id)
    note(ctx.engine, ctx.source, ctx.actor,
         f"Guardian Spirit Posture: {spirit.display_name}'s Nature is a guardian kind, so {protected.display_name} gains "
         f"{amount} Temporary HP.", (protected.entity_id,))


def _guards(target: Any) -> list[Any]:
    return [c for c in target.conditions.values() if c.condition_id == GUARD]


@hook("ac")
def guard_ac(engine: Any, target: Any) -> int:
    return sum(int((c.data or {}).get("amount") or 0) for c in _guards(target) if (c.data or {}).get("mode") == "ac")


def _end_guard(engine: Any, holder: Any, iid: str, source: str) -> None:
    """Remove exactly this Guard and the Disadvantage modifier it put on its holder."""
    from .rider_support import remove_instance

    held = holder.conditions.get(iid)
    modifier_id = str(((held.data or {}) if held is not None else {}).get("modifier_id") or "")
    modifier = holder.modifiers.pop(modifier_id, None) if modifier_id else None
    if modifier is not None:
        engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=holder.entity_id, target_ids=(holder.entity_id,),
                             payload={"modifier_id": modifier_id, "reason": "CONSUMED"})
    remove_instance(engine, holder, iid, source)


@hook("event")
def guard_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The first attack roll against the protected creature, hit or miss, uses the Guard up."""
    if event_type != "ATTACK_ROLLED":
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        for iid, held in list((target.conditions if target is not None else {}).items()):
            if held.condition_id == GUARD:
                _end_guard(engine, target, iid, "system:spirit_guard.spent")


# ------------------------------------------------------------------------------------------------ Pact-Brother Battle Rhythm
def _window_start(engine: Any, owner: Any) -> int:
    """The event sequence at which the owner's "last turn" began (see the module docstring)."""
    starts = [event.sequence for event in engine.events if event.event_type == "TURN_STARTED" and event.actor_id == owner.entity_id]
    if engine.state.current_actor_id == owner.entity_id and len(starts) >= 2:
        return starts[-2]
    return starts[-1] if starts else 0


def _damaged_since(engine: Any, dealer_id: str, target_id: str, since: int) -> bool:
    return any(event.event_type == "DAMAGE_COMMITTED" and event.sequence >= since and event.actor_id == dealer_id
               and target_id in event.target_ids
               and int((event.payload or {}).get("hp_damage") or 0) + int((event.payload or {}).get("temporary_hp_absorbed") or 0) > 0
               for event in engine.events)


@hook("damage_dealt")
def pact_rhythm(ctx: Any, target: Any, amount: int) -> None:
    engine, dealer = ctx.engine, ctx.actor
    owner = _owner_of(engine, dealer) or dealer
    if "pact_brother" not in _kinds(engine, owner.entity_id) or not target.active or target.team_id == owner.team_id:
        return
    if owner.turn_flags.get(PACT_USED) == str(engine.state.round_number):
        return
    since = _window_start(engine, owner)
    if dealer is owner:
        partners = [s for s in bonded_spirits(engine, owner) if _damaged_since(engine, s.entity_id, target.entity_id, since)]
    else:
        partners = [dealer] if _damaged_since(engine, owner.entity_id, target.entity_id, since) else []
    if not partners:
        return
    spirit = partners[0]
    owner.turn_flags[PACT_USED] = str(engine.state.round_number)
    _pact_choice(ctx, owner, spirit, target)


def _pact_choices() -> list[tuple[str, str, dict[str, Any]]]:
    """The printed choices, read from the talent's own typed record: ``(choice, label, row)`` in the owner's data order.

    One authoritative list (AUTO5f1): the record says which outcomes exist and what each button says, this hook
    delivers them. ``choice`` names the delivery branch; a record without it is matched by effect shape, so a save
    or data file written before this hook keeps working. ``{creature}``/``{spirit}`` in a label are filled in with the
    names the table knows, so no internal word is ever shown to a player."""
    from ..typed_numbers import authority_mechanics

    out = []
    for row in (authority_mechanics().get(PACT) or {}).get("effects") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("choice") or _PACT_BY_SHAPE.get((str(row.get("type")), str(row.get("applies_to"))), ""))
        label = str(row.get("label") or row.get("evidence") or "")
        if key and label:
            out.append((key, label, dict(row)))
    return out


_PACT_BY_SHAPE = {("advantage", "target"): "advantage", ("advantage", "self"): "help",
                  ("movement", "self"): "move", ("seal_strain", "self"): "strain"}


def _pact_choice(ctx: Any, owner: Any, spirit: Any, target: Any) -> None:
    from .rider_choices import pick

    engine = ctx.engine
    help_ready = spirit.active and spirit.reaction_available and engine._distance_actor_to_actor(spirit, target) <= 5
    rows = [row for row in _pact_choices()
            if not (row[0] == "help" and not help_ready) and not (row[0] == "strain" and strain(owner) <= 0)]
    if not rows:
        return
    options = [key for key, _, _ in rows]
    labels = {key: label.replace("{creature}", target.display_name).replace("{spirit}", spirit.display_name)
              for key, label, _ in rows}
    chosen = pick(engine, owner, "pact_brother", "Pact-Brother Battle Rhythm", options, subject=target, labels=labels,
                  preferred=[key for key in options if key == "advantage"], trigger=f"you and {spirit.display_name} both struck {target.display_name}")
    if not chosen:
        return
    source = PACT
    key = str(chosen[0])
    # The row the player just picked is the row that runs: every mechanical number below is read out of it, so the
    # record is the single source of truth for this talent and editing it changes play.
    row = next((data for candidate, _, data in rows if candidate == key), {})
    if key == "advantage":
        engine._add_modifier(target, source, "incoming_attack_mode", "SET", "ADVANTAGE", "NEXT_ATTACK",
                             expires_on=_pact_expiry(row, "end", expires_on="CONSUMED"), spend_on_roll=True)
        note(engine, source, owner, f"Pact-Brother Battle Rhythm: the next attack roll against {target.display_name} has Advantage.",
             (target.entity_id,))
    elif key == "help":
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, spirit, PACT, independent=True):
            spirit.reaction_available = False
            if _roll_still_resolving(ctx, owner):
                # The Blow that asked for Help has already been rolled, and the engine spends an ``attack_mode_vs``
                # benefit (the Vex shape) on the first attack roll against that creature made AFTER it is written --
                # which here is the roll already in progress. Writing the Advantage now would spend it on a roll the
                # player never made, which is the whole cost of Help for nothing (AUTO5r3 review finding 1). The promise
                # is kept in the Binder's own turn flags instead and written by pact_help_delivered once that roll is
                # over: still inside this same committed action, and before any later attack roll.
                from ..paid_relocation import capture, retain
                retain(engine, (PACT_HELP, owner.entity_id, spirit.entity_id, target.entity_id), capture(engine))
                owner.turn_flags[PACT_HELP] = f"{spirit.entity_id}|{target.entity_id}"
            else:
                _grant_help(engine, owner, spirit, target, row)
    elif key == "strain":
        add_strain(engine, owner, _pact_strain(row), source, "Pact-Brother Battle Rhythm: the blow served the spirit's Nature.")
    else:
        _pact_move(ctx, owner, spirit, target, _pact_feet(row))


def _pact_strain(row: dict[str, Any]) -> int:
    """How much Bond Strain this choice gives back, out of the chosen row's own ``flat`` (the printed "-1")."""
    return int(row.get("flat") or 0)


# ------------------------------------------------------------------------------------------------ Help, and the roll that must not spend it
def _help_row() -> dict[str, Any]:
    """The Help row of the talent's own record: the one that says what the spirit's Reaction buys."""
    return next((data for key, _, data in _pact_choices() if key == "help"), {})


def _roll_still_resolving(ctx: Any, owner: Any) -> bool:
    """Whether the damage being reported belongs to an attack that has already rolled and is still resolving.

    Attack provenance also accompanies late attached damage, after ``attack_resolved`` has run. Only the public
    consumption-phase flag says the current roll can still spend a newly granted benefit. A spirit's own roll
    never spends the Cultivator's benefit, so only the owner's pending sweep requires deferred delivery."""
    return ctx.actor is owner and bool(getattr(ctx, "attack_mode_consumption_pending", False))


def _grant_help(engine: Any, owner: Any, spirit: Any, target: Any, row: dict[str, Any]) -> None:
    """Write the printed Help: the Cultivator's next attack roll against that one creature, for the printed window.

    The row the player chose decides the window, but the answer must always exist: a record whose ``duration``
    states nothing ``_pact_expiry`` can read falls back to the printed Help window, the start of the spirit's next
    turn (5.5e Help expires then), built with the same helper so the name is one the engine removes by itself."""
    from .help_policy import allowed
    if not allowed(engine, spirit, owner):
        return
    engine._add_modifier(owner, PACT, "attack_mode_vs", "SET", f"ADVANTAGE:{target.entity_id}", "NEXT_ATTACK",
                         expires_on=_pact_expiry(row, "start", spirit=spirit,
                                                 expires_on=effect_durations.token("start", spirit.entity_id,
                                                                                   int(spirit.turns_started) + 1)))
    note(engine, PACT, owner, f"Pact-Brother Battle Rhythm: {spirit.display_name} Helps -- {owner.display_name}'s next attack roll "
                              f"against {target.display_name} has Advantage.", (spirit.entity_id, target.entity_id))


@hook("attack_resolved")
def pact_help_delivered(ctx: Any, target: Any, hit: bool, effect: Any) -> None:
    """Write a Help an attack asked for, once the roll that would have spent it is over (AUTO5r3 review finding 1).

    The ask keeps the promise in the Binder's own ``turn_flags`` as ``"<spirit>|<creature>"``; this hook is the
    documented ``attack_resolved`` point the executor runs after its own attack-mode sweep, so the Advantage is on
    the Binder before any later attack roll and the roll that asked for it keeps the printed meaning of "your NEXT
    attack roll". Nothing here runs without that marker, so a creature that does not own the talent is untouched;
    the marker is one plain string (no float, no object), it is cleared the moment it is spent, and the engine drops
    it with the rest of the turn flags at the Binder's next turn start, so a fight saved mid-delivery reloads to
    exactly what the table showed.
    """
    turn_flags = getattr(ctx.actor, "turn_flags", None) or {}
    spirit_id, _, target_id = str(turn_flags.get(PACT_HELP) or "").partition("|")
    if not spirit_id or target_id != target.entity_id:
        return
    del ctx.actor.turn_flags[PACT_HELP]
    spirit = ctx.engine.state.actors.get(spirit_id)
    if spirit is None:
        return
    from ..paid_relocation import causal_scope, take
    with causal_scope(ctx.engine, take(ctx.engine, (PACT_HELP, ctx.actor.entity_id, spirit_id, target_id))):
        _grant_help(ctx.engine, ctx.actor, spirit, target, _help_row())


def _pact_feet(row: dict[str, Any]) -> int:
    """How far the movement choice reaches, out of the chosen row's own ``distance_ft`` (the printed 10 feet)."""
    return max(0, int(row.get("distance_ft") or 0))


def _pact_expiry(row: dict[str, Any], edge: str, *, expires_on: str, spirit: Any = None) -> str:
    """The expiry name for a chosen row that lasts, built with the engine's own turn-clock helper so the name it writes
    is one the engine removes by itself.

    ``duration`` in the record names the window ("next_attack" is spent on the attack, anything reading as a start or
    end of the spirit's next turn is that turn's own clock). ``expires_on`` is the answer when the row states nothing
    this helper can read, so a record without a duration keeps working.
    """
    duration = str(row.get("duration") or "").strip().lower()
    if spirit is not None and "start" in duration:
        return effect_durations.token(edge, spirit.entity_id, int(spirit.turns_started) + 1)
    if spirit is not None and "end" in duration:
        return effect_durations.token("end", spirit.entity_id, int(spirit.turns_started) + 1)
    return expires_on


def _pact_move(ctx: Any, owner: Any, spirit: Any, target: Any, feet: int) -> None:
    from .needle import cell_options, free_cells, position_of, step_to
    from .rider_choices import pick

    engine = ctx.engine
    movers = [creature for creature in (owner, spirit) if creature.active and engine._effective_speed(creature) > 0]
    if not movers:
        return
    mover = movers[0]
    if len(movers) > 1:
        chosen = pick(engine, owner, "pact_brother_mover", "Pact-Brother Battle Rhythm", [m.entity_id for m in movers], subject=target,
                      labels={m.entity_id: f"Move {m.display_name}" for m in movers}, optional=False)
        mover = next((m for m in movers if m.entity_id in chosen), mover)
    options, labels = cell_options(engine, mover, free_cells(engine, mover, feet))
    chosen = pick(engine, owner, "pact_brother_step", "Pact-Brother Battle Rhythm", options, subject=mover, labels=labels,
                  trigger=f"move up to {feet} feet without Opportunity Attacks")
    if chosen and position_of(chosen[0]) != mover.position:
        step_to(engine, mover, position_of(chosen[0]), PACT)
        note(engine, PACT, owner, f"Pact-Brother Battle Rhythm: {mover.display_name} moves without provoking Opportunity Attacks.",
             (mover.entity_id,))
