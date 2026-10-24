"""Brute: the Brutal Shove contest, Brute Maneuvers (Overrun, Shove Aside) and Manhandle stacking (rider lane C16, 2026-09-30;
owner: fill the sphere chassis from the owner's books, do not ask). Rules text: the owner's Sphere Compendium, "Sphere of Brute",
Core Brute Rules (authority/typed_mechanics/rules_text.json BRUTE_BASE_BRUTAL_SHOVE, BRUTE_BASE_BRUTE_MANEUVERS).

Brutal Shove was this table's attack-roll stand-in for a contest. Printed: "Target: One creature no more than one size larger than you.
Make: Strength (Athletics) contested by the target's: Strength (Athletics) or Dexterity (Acrobatics). The target chooses its skill.
Success: Choose to push the target 5 feet away or give it the Prone condition. Then: move it an additional 5 feet for every 5 points by
which your Athletics check exceeds its opposing check; apply this additional movement even when you chose Prone; deal Bludgeoning
damage equal to your Strength modifier, minimum 0; apply one Manhandle talent you know."

Shared helper API (users: this module, combat/ext/brute_riders.py for Dominoes' free shoves):
  contest(ctx, target, *, mine_mode=None, theirs_skills=("Athletics", "Acrobatics"), theirs_mode=None, purpose="shove")
      -> {"success": bool, "margin": int, "mine": int, "theirs": int, "skill": str}. The actor's Strength (Athletics) against the
      target's chosen skill; "The target chooses its skill": a player's creature set to Ask me is asked, the built-in AI takes its
      better bonus. A tie keeps things as they were (the shove fails; D&D 5.5e contest rule). One CHECK_ROLLED event records both
      rolls. Modes come from conditions and ability_check_mode hooks plus the documented ``contest_mode`` hook below.
  shove(ctx, target, row) -> dict | None   one Brutal Shove (the effect below), returns the contest result; for plug-ins that make
                                           a shove of their own (a free shove, a reaction shove)
  size_ok(ctx, target, row)               the printed size limit on effective sizes (typed_executor.size_width and its
                                           ``size_steps`` hook): no more than ``max_size_larger`` (1) sizes larger
Typed row:
  {"type": "brutal_shove", "success_branch": true, "on_success": [...], "mode": "push_or_prone" | "prone_only" | "aside",
   "no_damage": bool, "no_manhandle": bool, "ignore_size": bool, "max_size_larger": int, "disadvantage": bool,
   "direction": "away" | "toward", "tether": bool}
  ``on_success`` holds what a Manhandle variant adds ("Brutal Shove + Takedown": factory_compiler attaches a "hit"/"success"
  modifier there, the success_branch seam). Run in order: the push or Prone, the extra movement, the damage, ``on_success``.
  ``direction`` is the printed direction of the shove's own movement ("toward" for Get Over Here, "move the target toward you
  instead of away"); without it the push goes away from the shover, as Brutal Shove reads. ``tether`` marks a shove made
  through a tether (Get Over Here), which additionally restricts a Shove Aside to spaces at least diagonally closer
  (``_aside(closer=True)``); it changes nothing else about the contest.
Hooks this module offers (documented in combat/ext/__init__.py):
  shove_succeeded(ctx, target, result)   after a successful Brutal Shove's own effects (Break Defenses, Focused Might, Court and
                                         Sovereign extra pushes)
  shove_damage(ctx, target)              -> DiceSpec | None: replaces the Strength-modifier damage (Sovereign Weight Incarnation)
  contest_mode(engine, creature, role, purpose, other) -> "ADVANTAGE" | "DISADVANTAGE" | None for one side of a Brute contest
                                         (role "act" or "resist"; purpose "shove" or "overrun")
Choices: push or Prone is the shover's ("Choose to push the target ... or give it the Prone condition"): asked of a player's creature;
the built-in AI pushes when Hammer (holding Martial Focus), Dominoes (a creature right behind), Court of the Moving Mountain or Sovereign
Weight Incarnation pays off on a push or the target is already Prone, and otherwise knocks it Prone. Brutal Manhandle ("When applying one Manhandle talent,
expend Martial Focus to apply one additional Manhandle talent. You cannot apply the same Manhandle talent twice to one shove"): after a
successful shove the owner holding Martial Focus is asked for a second Manhandle talent it knows (the AI declines: it keeps its Focus).

Brute Maneuvers -- Overrun: "As an Action or Bonus Action, attempt to move through one hostile creature's space. Make: Strength
(Athletics) contested by the target's: Strength (Athletics). Gain Advantage if larger than the target. Suffer Disadvantage if smaller.
Success: Move through the hostile creature's space once during this turn. Treat that space as difficult terrain, and do not end movement
in an occupied space." The buttons "Overrun" (Action) and "Overrun (Bonus Action)" against an adjacent hostile creature; a success moves
the Brute straight through its space to the free square beyond (the space costs double, paid from its movement), as one move: the table
cannot keep "may pass through this space later this turn" open (census row 10, a locked movement seam). Not offered without the
movement to get through. Shove Aside: "Use Brutal Shove to move the target into one different legal space within your reach rather than
directly away. Make the Brutal Shove contest with Disadvantage" -- the button "Brutal Shove: Shove Aside"; the space is chosen by the
shover (asked; the AI takes the one farthest from its allies); no extra movement (it must end within your reach). Alternative Maneuvers:
no Disadvantage on Shove Aside; an Overrun success also deals the Brutal Shove damage and applies one Manhandle talent (asked).
Sizes: Court of the Moving Mountain and Muscular Surge count you one size larger, Sovereign Weight Incarnation two, for your shoves and
Overruns (the shover's side, as rider lanes C4 and C12 read them); Rooted Stance (holding Martial Focus) one size larger when resisting
them (``size_steps``).
Greater Brute: Expertise in Athletics ("does not stack with another feature granting Expertise"): the better of the sheet's Athletics and
Strength modifier + twice the Proficiency Bonus.
Living Battering Ram and Fortress-Line Breaker use a separately budgeted native move. Their scoped passage is only a
preview permission: movement_attempt settles the same Overrun contest before entry, and failure stops before that square.
Not built here: Disarm and Robbery (held items, census row 9), vertical throws (altitude, row 1).
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note, run
from .needle import CHOICE, ask, checkpoint_id

BRUTAL_SHOVE = "BRUTE_BASE_BRUTAL_SHOVE"
MANEUVERS = "BRUTE_BASE_BRUTE_MANEUVERS"
BRUTE = "tianxia.sphere.brute"
FOCUS = "resource:core.martial_focus"
BLOCK = "brute_shove"

# The shove's own Bludgeoning damage has always read the Strength score behind "auto51_strength_score".
# Sovereign Weight Incarnation's 2d8 replacement and Overrun damage only became score-based in AUTO107r1f1, so they are
# gated on this newer flag instead: a packet sealed before that change simply does not carry it and keeps the modifier it
# was saved with. Stamped into the compiled packet by sovereign_shove_damage's callers and overrun_buttons below.
DAMAGE_SCORE = "auto107_strength_score_damage"

# The one saved-fight population this gate cannot serve, named rather than left as a silent surprise.
#
# AUTO107r1f1 changed these two damage paths to read the Strength score, but stamped no marker, so it reused the older
# "auto51_strength_score" flag -- which every Brute packet has carried since AUTO51. For one review window that means
# packets sealed by the r1f1 builds read the score now and the saving throw at head:
#
#     damage reading of a Sovereign Weight shove / an Overrun, with the same sealed packet
#     sealed before 47fdd95e (AUTO107r1f1)   at that revision  saving throw   at head  saving throw   unchanged
#     sealed by 47fdd95e..60c3d3d0 (r1f1)    at that revision  score          at head  saving throw   CHANGED
#     sealed at 60c3d3d0 or later            score                               score                unchanged
#
# No packet data can separate the middle row from the first: sealing a bundle freezes its data, not the Python that reads
# it, and the r1f1 window changed only Python for these paths (its one typed-data change, the Get Over Here admission
# riders, is carried only by a Brute that owns that talent). A gate can therefore keep the older cohort *or* the r1f1
# cohort, never both. Exact replay of the middle cohort is explicitly unsupported for these two damage paths; this
# does NOT assert that no such saves exist. The existing saved-fight compatibility service detects divergent replay
# and offers explicit saved-state continuation with a verified backup, preserving past outcomes while disclosing
# that future outcomes may change. See docs/plans/AUTO107_SAVED_DAMAGE_BOUNDARY.md.
DAMAGE_SCORE_UNSUPPORTED = "auto/brute 47fdd95e inclusive..60c3d3d0 exclusive: exact Sovereign/Overrun damage replay"


def _row(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    from .passive_rows import row_of

    return row_of(engine, actor.entity_id, BLOCK, kind)


@hook("compile_block")
def brute_shove_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "cl": int(numbers.get("cl") or 1),
             **({"explicit_athletics": True} if spec.get("explicit_athletics") else {})}]


# ------------------------------------------------------------------------------------------------ sizes
def _state(engine: Any, actor: Any, name: str) -> bool:
    from .states import active

    return active(engine, actor, name) is not None


def _surging(engine: Any, actor: Any) -> bool:
    return _state(engine, actor, "muscular_surge")


@hook("size_steps")
def brute_sizes(engine: Any, creature: Any, role: str, purposes: Any) -> int | None:
    """Court of the Moving Mountain: "count as one size larger for Shove, Grapple, and Overrun"; Sovereign Weight Incarnation: "count as
    two sizes larger for Shove, Grapple, Overrun"; Muscular Surge: "count as one size larger when determining which creatures you may Shove
    or Grapple" -- all three on the side of the one shoving; Rooted Stance (holding Martial Focus): "count as one size larger when
    resisting Shove and Overrun".
    One answer for the Brute (the largest; these do not stack), added to other spheres' by typed_executor.size_width.
    New source-timed grapple conditions carry acting/resisting steps explicitly:
    Court and Sovereign cover both roles; Surge only changes what its user can grapple.
    Older sealed states have no such fields and preserve their former behavior."""
    if "grapple" in purposes:
        field = "brute_grapple_steps" if role == "act" else "brute_grapple_resist_steps"
        return max((int((c.data or {}).get(field) or 0)
                    for c in creature.conditions.values()), default=0) or None
    if not set(purposes) & {"brutal_shove", "overrun"}:
        return None
    steps = 0
    if role == "act":  # the shover's side (rider lanes C4/C12 read Court, Sovereign and Muscular Surge so; Sovereign resists moves itself)
        steps = 2 if _state(engine, creature, "sovereign_weight_incarnation") else 1 if (
            _state(engine, creature, "court_of_the_moving_mountain") or _surging(engine, creature)) else 0
    if role == "resist" and creature.resources.get(FOCUS, 0) >= 1:
        from .ability_source import has_row

        if has_row(engine, creature.entity_id, "brute_rooted"):
            steps = max(steps, 1)
    return steps or None


@hook("candidate_allowed")
def surge_exhaustion_gate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    rows = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if not any((row.get("condition_data") or {}).get("brute_surge_gate") for row in rows):
        return None
    from .forged_exhaustion import level

    return False if level(actor) else None


@hook("d20_bonus")
def explicit_athletics_expertise(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """New Greater Brute rows supplement explicitly identified Athletics checks."""
    actor = engine.state.actors.get(roll.actor_id)
    row = _row(engine, actor, "greater_brute") if actor is not None else None
    if row is None or not row.get("explicit_athletics"):
        return None
    context = engine.d20_context(roll) or {}
    if context.get("kind") != "check" or context.get("ability") != "STR" or context.get("skill") != "Athletics":
        return None
    from ..ability_checks import ability_modifier, skill_bonus

    base = ability_modifier(actor, "STR")
    floor = _score_modifier(engine, actor, "STR") + 2 * int(actor.proficiency_bonus)
    bonus = max(0, floor - skill_bonus(engine, actor, "Athletics", base))
    return {"source_id": "TAL_BRUTE_GREATER_BRUTE", "bonus": bonus} if bonus else None


def _width(ctx: Any, creature: Any, role: str, row: dict[str, Any]) -> int:
    from ..typed_executor import size_width

    return size_width(ctx, creature, role, {**row, "max_size_larger": row.get("max_size_larger", 1)})


def size_ok(ctx: Any, target: Any, row: dict[str, Any]) -> bool:
    """"One creature no more than one size larger than you" (``max_size_larger`` sizes; ``ignore_size``), on effective sizes."""
    if row.get("ignore_size"):
        return True
    return _width(ctx, target, "subject", row) <= _width(ctx, ctx.actor, "actor", row) + int(row.get("max_size_larger", 1))


# ------------------------------------------------------------------------------------------------ the contest
def _packet_marker(engine: Any, creature: Any, marker: str) -> bool:
    """Does this creature's own compiled packet carry ``marker`` on any effect row it will run?

    Sealing a bundle freezes its data, not the Python that reads it, so a saved fight's replay is only preserved when the
    marker that introduced a behaviour change is itself part of the saved data. Every marker read here is stamped into
    the packet at compile time, which is what makes ``marker`` a compatibility gate rather than a version guess.
    """
    for action_id in creature.action_ids:
        action = engine.action_catalog.get(action_id)
        typed = (action.parameters or {}).get("typed") or {} if action is not None else {}
        if any(isinstance(row, dict) and row.get(marker) for row in typed.get("effects") or []):
            return True
    return False


def strength_modifier(engine: Any, creature: Any, numbers: dict[str, Any] | None = None, *, marker: str = "auto51_strength_score") -> int:
    """"Your Strength modifier", one answer for every Brute damage path (the shove's own Bludgeoning damage, Sovereign
    Weight Incarnation's 2d8 + Strength replacement in combat/ext/brute_riders.py, and Alternative Maneuvers' Overrun
    damage).

    ``marker`` names the packet flag that opens the score-based reading. The shove's own damage has always used
    ``auto51_strength_score``, so it keeps that gate and its saved fights are untouched. The Sovereign replacement and
    Overrun damage only *became* score-based in AUTO107r1f1, so they are gated on their own, newer flag
    (``brute_shove.DAMAGE_SCORE``): a fight saved before that flag existed does not carry it and keeps reading the
    modifier its bundle was sealed with, which is what keeps those replays byte-identical.

    One cohort cannot be served by any flag -- see ``DAMAGE_SCORE_UNSUPPORTED`` above for the table and the reason. It is
    named there rather than hidden here, because "which reading does this packet use" is a property of the packet's data
    and a packet that cannot be told apart from an older one has no answer to give.
    """
    from ..ability_checks import ability_modifier

    if _packet_marker(engine, creature, marker):
        return _score_modifier(engine, creature, "STR")
    return ability_modifier(creature, "STR", numbers=numbers)


def _score_modifier(engine: Any, creature: Any, ability: str) -> int:
    """Do not interpret an omitted legacy Strength score as an actual score of 10."""
    from ..ability_checks import ability_modifier

    if ability in ((getattr(creature, "summon", None) or {}).get("ability_mods") or {}):
        return ability_modifier(creature, ability)
    if ability == "DEX":
        return (int(creature.dexterity_score) - 10) // 2
    template = engine.actor_templates.get(creature.entity_id)
    if template is not None and "strength_score" in template.model_fields_set:
        return (int(creature.strength_score) - 10) // 2
    bundle = next((b for b in getattr(engine, "typed_bundle_documents", ()) or ()
                   if b.get("actor_id") == creature.entity_id), {})
    score = (bundle.get("carrying") or {}).get("strength_score")
    return (score - 10) // 2 if type(score) is int else ability_modifier(creature, "STR")


def _bonus(engine: Any, creature: Any, skill: str, ability: str, *, score_modifiers: bool = False) -> int:
    from ..ability_checks import ability_modifier
    from .tabik_scoundrel import skill as sheet_skill

    if score_modifiers:
        base = _score_modifier(engine, creature, ability)
    else:
        base = strength_modifier(engine, creature) if ability == "STR" else ability_modifier(creature, ability)
    value = sheet_skill(engine, creature, skill, base)
    if skill == "Athletics" and _row(engine, creature, "greater_brute") is not None:
        value = max(value, base + 2 * int(creature.proficiency_bonus))  # Greater Brute: Expertise
    return int(value)


def _mode(engine: Any, creature: Any, ability: str, skill: str, other: Any, role: str, purpose: str, extra: set[str]) -> str:
    from ..typed_executor import check_modes

    modes = set(extra) | set(check_modes(creature, ability, skill, engine=engine, against_creature=other))
    modes |= {m for m in run("contest_mode", engine, creature, role, purpose, other) if m in ("ADVANTAGE", "DISADVANTAGE")}
    return modes.pop() if len(modes) == 1 else "NORMAL"


_SKILLS = {"Athletics": "STR", "Acrobatics": "DEX"}


def contest(ctx: Any, target: Any, *, mine_mode: set[str] | None = None, theirs_skills: tuple[str, ...] = ("Athletics", "Acrobatics"),
            theirs_mode: set[str] | None = None, purpose: str = "shove", label: str = "Brutal Shove") -> dict[str, Any]:
    engine, actor = ctx.engine, ctx.actor
    score_modifiers = _packet_marker(engine, actor, "auto51_strength_score")
    bonuses = {name: _bonus(engine, target, name, _SKILLS[name], score_modifiers=score_modifiers) for name in theirs_skills}
    best = max(bonuses, key=lambda name: (bonuses[name], name == "Athletics"))
    chosen = best
    if len(bonuses) > 1:
        labels = {name: f"Resist with {'Strength' if _SKILLS[name] == 'STR' else 'Dexterity'} ({name}) {bonuses[name]:+d}" for name in bonuses}
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "BRUTE_CONTEST_SKILL", target.entity_id, actor.entity_id), target,
                     CHOICE + "brute_contest_skill", list(bonuses), labels=labels, preferred=[best], target_id=target.entity_id,
                     name=f"Resist {label}",
                     prompt=f"{actor.display_name} uses {label} on {target.display_name}: its Strength (Athletics) check against your check. "
                            "Choose the skill you resist with.")
        chosen = picked[0] if picked and picked[0] in bonuses else best
    mine_bonus = _bonus(engine, actor, "Athletics", "STR", score_modifiers=score_modifiers)
    mine = engine.roller.d20(modifier=mine_bonus, actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:ATHLETICS",
                             mode=_mode(engine, actor, "STR", "Athletics", target, "act", purpose, set(mine_mode or ())))
    engine._record_roll(mine)
    theirs = engine.roller.d20(modifier=bonuses[chosen], actor_id=target.entity_id, reason=f"CHECK:{ctx.source}:OPPOSE",
                               mode=_mode(engine, target, _SKILLS[chosen], chosen, actor, "resist", purpose, set(theirs_mode or ())))
    engine._record_roll(theirs)
    from . import floored

    mine = floored(engine, actor, mine, theirs.total + 1)
    success = mine.total > theirs.total  # a tie: "the situation remains the same" (5.5e contests)
    engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                         payload={"actor": mine.model_dump(mode="json"), "target": theirs.model_dump(mode="json"), "success": success,
                                  "skill": "Athletics", "target_skill": chosen, "against": chosen, "contest": purpose})
    # Publish the ordinary opposed-check contract from these actual native
    # rolls. A shove defence prevents physical movement; Overrun does not.
    from ..typed_executor import OpposedCheckResult
    run('opposed_check_resolved',ctx,target,OpposedCheckResult(mine,theirs),
        {'kind':'check','ability':'STR','skill':'Athletics'},
        {'kind':'check','ability':_SKILLS[chosen],'skill':chosen,
         'hazards':['forced_movement'] if purpose=='shove' else []})
    return {"success": success, "margin": int(mine.total) - int(theirs.total), "mine": int(mine.total), "theirs": int(theirs.total),
            "skill": chosen}


# ------------------------------------------------------------------------------------------------ the shove
def _push(ctx: Any, target: Any, feet: int, why: str, direction: str = "away") -> None:
    from dataclasses import replace

    from ..typed_executor import run_effects

    if target.active and feet > 0:
        run_effects(replace(ctx, target=target, targets=[target]),
                    [{"type": "forced_movement", "applies_to": "target", "distance_ft": int(feet), "direction": direction, "evidence": why}])


def _aside(ctx: Any, target: Any, *, closer: bool = False) -> None:
    """Shove Aside: "move the target into one different legal space within your reach".

    ``closer`` keeps only the spaces that actually bring the target at least diagonally closer to the shover (Get Over
    Here: "When using Shove Aside, movement must still bring the target at least diagonally closer"), and aims the AI's
    automatic pick at the spot nearest the shover rather than the one farthest from its allies."""
    from ..gate2_runtime_models import Position
    from ..typed_reactions import physical_melee_reach

    engine, actor = ctx.engine, ctx.actor
    reach = int(physical_melee_reach(engine, actor) or 5)
    occupied = engine._occupied_cells_except(target.entity_id)
    footprint = engine._footprint(target)
    spots = []
    for y in range(engine.grid.height):
        for x in range(engine.grid.width):
            spot = Position(x=x, y=y)
            if spot == target.position or not engine.grid.placement_legal((x, y), footprint=footprint):
                continue
            cells = engine._actor_cells(target, spot)
            if set(cells) & occupied or engine.grid.distance_between_cell_sets_ft(cells, engine._actor_cells(actor)) > reach:
                continue
            if closer and not _diagonally_closer(engine, target, actor, spot):
                continue
            spots.append(spot)
    if not spots:
        ctx.rider("Shove Aside: there is no other legal space within reach for "
                  + (f"{target.display_name} that also brings it diagonally closer." if closer else f"{target.display_name}."))
        return
    if closer:
        far = min(spots, key=lambda s: (engine.grid.distance_ft(s, actor.position), s.y, s.x))
    else:
        allies = [a for a in engine.state.actors.values() if a.active and a.team_id == actor.team_id]
        far = max(spots, key=lambda s: (min((engine.grid.distance_ft(s, a.position) for a in allies), default=0), -s.y, -s.x))
    labels = {f"cell:{s.x},{s.y}": f"Move {target.display_name} to square {s.x},{s.y}" for s in spots}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "SHOVE_ASIDE", actor.entity_id, target.entity_id), actor,
                 CHOICE + "shove_aside", list(labels), labels=labels, preferred=[f"cell:{far.x},{far.y}"], target_id=actor.entity_id,
                 name="Shove Aside", prompt=f"Shove Aside: choose the space within your reach to move {target.display_name} into.")
    choice = picked[0] if picked and picked[0] in labels else f"cell:{far.x},{far.y}"
    x, y = (int(v) for v in choice.split(":", 1)[1].split(","))
    destination = Position(x=x, y=y)
    start = target.position
    target.position = destination
    engine._append_event("MOVEMENT_COMMITTED", ctx.source, actor_id=target.entity_id,
                         payload={"destination": destination.model_dump(mode="json"),
                                  "path": [start.model_dump(mode="json"), destination.model_dump(mode="json")], "cost_ft": 0, "forced": True})
    from .. import zones

    zones.on_moved(engine, target, start, destination, forced=True)


def _diagonally_closer(engine: Any, target: Any, actor: Any, spot: Any) -> bool:
    """"At least diagonally closer": the target's distance drops by a square or more in both directions at once -- one step
    on each axis, or one step on one axis and none on the other is not a diagonal approach."""
    from ..gate2_runtime_models import Position

    before = engine.grid.distance_ft(target.position, actor.position)
    after = engine.grid.distance_ft(spot, actor.position)
    if after >= before:
        return False
    dx = abs(spot.x - target.position.x)
    dy = abs(spot.y - target.position.y)
    return dx >= 1 and dy >= 1


def manhandle_options(engine: Any, actor: Any) -> dict[str, tuple[str, list[dict[str, Any]]]]:
    """The Manhandle talents the actor knows, as compiled into its Brutal Shove variants: name -> (variant id, rows).

    Public shared helper for a printed ability that applies "one Manhandle talent you know" without compiling its own
    Brutal Shove variant per pairing; a plug-in outside combat/ext must not read another plug-in's private helpers, so
    anything that needs this list calls it here.
    """
    return _manhandle_rows(engine, actor)


def apply_manhandle(ctx: Any, target: Any, *, feature: str, choice_id: str, prompt: str,
                    exclude: str | None = None, allow_decline: bool = False) -> str | None:
    """"Apply one Manhandle talent" from a printed ability that does not compile its own variant: ask which Manhandle
    talent the character means and run its compiled rows on the target. Returns the talent's printed name, or None when
    none was applied. Reuses the same variant rows the ordinary "Brutal Shove + <talent>" buttons run, so one Manhandle
    talent has one implementation and its own printed reach requirement is checked where that talent checks it.

    ``feature``/``choice_id``/``prompt`` are the caller's own names, so the question the player sees names the ability,
    the triggering action and the creature it affects. ``exclude`` drops a talent the shove already applied.
    """
    from dataclasses import replace

    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    options = {name: entry for name, entry in _manhandle_rows(engine, actor).items() if name != exclude}
    if not options or target is None or not target.active:
        return None
    labels = {name: f"Apply {name} to {target.display_name}" for name in options}
    preferred = list(options)[:1]
    picked = ask(engine, ctx.intent, checkpoint_id(engine, feature, actor.entity_id, target.entity_id), actor,
                 CHOICE + choice_id, list(options), labels=labels, preferred=[] if allow_decline else preferred,
                 allow_decline=allow_decline, default="decline" if allow_decline else None,
                 target_id=actor.entity_id, name=feature, prompt=prompt)
    if not picked or picked[0] not in options:
        return None
    # options[name] is the (variant id, rows) pair; apply_manhandle runs the rows, never the id.
    run_effects(replace(ctx, target=target, targets=[target]), options[picked[0]][1])
    return picked[0]


def _manhandle_rows(engine: Any, actor: Any) -> dict[str, tuple[str, list[dict[str, Any]]]]:
    """The Manhandle talents the actor knows, as compiled into its Brutal Shove variants: name -> (variant id, rows)."""
    out = {}
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
        if typed.get("source") != BRUTAL_SHOVE or " + " not in action.display_name or "#" in action_id:
            continue
        row = next((e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "brutal_shove"), None)
        if row is not None and row.get("on_success"):
            out[action.display_name.split(" + ", 1)[1]] = (action_id, copy.deepcopy(row["on_success"]))
    return out


def _brutal_manhandle(ctx: Any, target: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    if row.get("no_manhandle") or _row(engine, actor, "brutal_manhandle") is None or actor.resources.get(FOCUS, 0) < 1:
        return
    current = ctx.action.display_name.split(" + ", 1)[1] if " + " in ctx.action.display_name else None
    options = {name: rows for name, rows in _manhandle_rows(engine, actor).items() if name != current}
    if not options or not target.active:
        return
    labels = {name: f"Also apply {name}" for name in options}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "BRUTAL_MANHANDLE", actor.entity_id, target.entity_id), actor,
                 CHOICE + "brutal_manhandle", list(options), labels=labels, preferred=[], allow_decline=True, automatic=False,
                 default="decline", target_id=actor.entity_id, name="Brutal Manhandle",
                 prompt=f"Brutal Manhandle: spend Martial Focus to apply a second Manhandle talent to this shove on {target.display_name}?")
    if not picked or picked[0] not in options:
        return
    from dataclasses import replace

    from ..typed_executor import run_effects

    engine._spend_resource(actor, FOCUS, 1, "TAL_BRUTE_BRUTAL_MANHANDLE")
    note(engine, "TAL_BRUTE_BRUTAL_MANHANDLE", actor, f"Brutal Manhandle: {actor.display_name} also applies {picked[0]} to {target.display_name}.",
         (target,))
    run_effects(replace(ctx, target=target, targets=[target]), options[picked[0]][1])


def _wants_push(ctx: Any, target: Any) -> bool:
    """The built-in AI's pick: push when something it has pays off on a push (Hammer while holding Martial Focus, Dominoes with a
    creature right behind the target, Court of the Moving Mountain's or Sovereign Weight's extra push), or when the target is already
    Prone; otherwise knock it Prone."""
    from ..typed_executor import CONDITION_PREFIX
    from .ability_source import has_row

    engine, actor = ctx.engine, ctx.actor
    if any(c.condition_id == CONDITION_PREFIX + "prone" for c in target.conditions.values()):
        return True
    if _state(engine, actor, "court_of_the_moving_mountain") or _state(engine, actor, "sovereign_weight_incarnation"):
        return True
    if has_row(engine, actor.entity_id, "brute_hammer_owned") and actor.resources.get(FOCUS, 0) >= 1:
        return True
    if has_row(engine, actor.entity_id, "brute_dominoes"):
        dx, dy = target.position.x - actor.position.x, target.position.y - actor.position.y
        behind = (target.position.x + (dx > 0) - (dx < 0), target.position.y + (dy > 0) - (dy < 0))
        return any(other.active and other.entity_id != target.entity_id and (other.position.x, other.position.y) == behind
                   for other in engine.state.actors.values())
    return False


def _push_or_prone(ctx: Any, target: Any, direction: str = "away") -> str:
    """The printed "Choose to push the target 5 feet away or give it the Prone condition", asked with the shove's own
    direction: Get Over Here moves the creature toward the shover, so its buttons, prompt and result must say so."""
    push = _wants_push(ctx, target)
    toward = direction == "toward"
    move = (f"Pull {target.display_name} 5 feet toward you" if toward else f"Push {target.display_name} 5 feet away")
    labels = {"push": move, "prone": f"Knock {target.display_name} Prone"}
    name = "Get Over Here" if toward else "Brutal Shove"
    if ((ctx.action.parameters or {}).get("typed") or {}).get("source") in (RAM, LINE):
        name = f"{ctx.action.display_name}: Brutal Shove"
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "BRUTAL_SHOVE_RESULT", ctx.actor.entity_id, target.entity_id), ctx.actor,
                 CHOICE + "brutal_shove_result", list(labels), labels=labels, preferred=["push" if push else "prone"],
                 target_id=ctx.actor.entity_id, name=name,
                 prompt=f"{name} succeeded against {target.display_name}: {move.lower()} or knock it Prone? "
                        "The extra movement from your margin applies either way.")
    return picked[0] if picked and picked[0] in labels else ("push" if push else "prone")


def shove(ctx: Any, target: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    engine, actor = ctx.engine, ctx.actor
    if target is None or not target.active or target.entity_id == actor.entity_id:
        return None
    if not size_ok(ctx, target, row):
        ctx.rider(f"Brutal Shove: {target.display_name} is more than {int(row.get('max_size_larger') or 1)} size larger than "
                  f"{actor.display_name}; it cannot be shoved.")
        return None
    aside = row.get("mode") == "aside"
    disadvantage = bool(row.get("disadvantage")) or (aside and _row(engine, actor, "alternative_maneuvers") is None)
    result = contest(ctx, target, mine_mode={"DISADVANTAGE"} if disadvantage else set(),
                     label="Shove Aside" if aside else "Brutal Shove")
    if not result["success"]:
        note(engine, ctx.source, actor, f"{actor.display_name}'s shove fails: Athletics {result['mine']} against {target.display_name}'s "
             f"{result['skill']} {result['theirs']}.", (target,))
        return result
    return apply_shove_success(ctx, target, row, result)


def apply_shove_success(ctx: Any, target: Any, row: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Apply the existing shove outcome after a won contest (ordinary shove or an advancing Overrun).

    No second contest: the Overrun margin also owns the shove's extra movement. Keeping the ordinary shove context
    lets Hammer, collision reactions and shove_succeeded subscribers answer exactly as for the maneuver.
    """
    from dataclasses import replace
    from ..typed_executor import run_effects

    engine, actor = ctx.engine, ctx.actor
    aside = row.get("mode") == "aside"
    extra = 5 * (max(0, result["margin"]) // 5)
    # Get Over Here: "On a success, move the target toward you instead of away" -- the printed direction of the shove,
    # so the row carries it rather than this module hard-coding one. It also rides on the result the shove_succeeded
    # hook receives, so Court of the Moving Mountain's and Sovereign Weight Incarnation's extra movement pushes the
    # creature the same way this shove did instead of undoing the pull.
    direction = str(row.get("direction") or "away")
    result["direction"] = direction
    # Each shove rolls its own dice, as each hit of an attack does (typed_executor.block_attack's per-hit copy): only string keys
    # (per-activation flags, collision guards) carry over; dice cached under an effect's id must not leak into the next shove.
    outer = ctx
    ctx = replace(ctx, damage_cache={key: value for key, value in outer.damage_cache.items() if isinstance(key, str)})
    one = replace(ctx, target=target, targets=[target])
    if aside:
        _aside(ctx, target, closer=bool(row.get("tether")))
        what = "shoves it aside"
    else:
        choice = "prone" if row.get("mode") == "prone_only" else _push_or_prone(ctx, target, direction)
        if choice == "prone":
            run_effects(one, [{"type": "condition", "condition": "prone", "applies_to": "target", "evidence": "Brutal Shove: the Prone condition"}])
        what = "knocks it Prone" if choice == "prone" else ("drags it 5 feet toward" if direction == "toward" else "pushes it 5 feet")
        feet = (5 if choice == "push" else 0) + (0 if row.get("mode") == "prone_only" else extra)
        # Get Over Here: "On a success, move the target toward you instead of away" -- the printed direction of the shove,
        # so the row carries it rather than this module hard-coding one.
        _push(ctx, target, feet, "Brutal Shove: 5 feet away and 5 feet more for every 5 points the check won by"
              if choice == "push" else "Brutal Shove: the extra movement for every 5 points the check won by, even after Prone",
              direction=direction)
        if extra and row.get("mode") != "prone_only":
            what += f", {extra} feet farther"
    note(engine, ctx.source, actor, f"{actor.display_name}'s shove succeeds (Athletics {result['mine']} against {result['skill']} "
         f"{result['theirs']}) and {what}.", (target,))
    if not row.get("no_damage") and target.active:
        dice = next((answer for answer in run("shove_damage", ctx, target) if answer is not None), None)
        damage = {"type": "damage", "applies_to": "target", "damage_types": ["bludgeoning"],
                  "evidence": "Brutal Shove: Bludgeoning damage equal to your Strength modifier, minimum 0"}
        if dice is not None:
            damage.update(dice={"count": int(dice.count), "sides": int(dice.sides)}, flat=int(dice.modifier))
        else:
            damage["flat"] = max(0, strength_modifier(engine, actor, ctx.numbers))
        if damage.get("dice") or damage["flat"] > 0:
            run_effects(one, [damage])
    if row.get("on_success") and target.active:
        run_effects(one, copy.deepcopy(row["on_success"]))
    if not row.get("no_manhandle"):
        _brutal_manhandle(ctx, target, row)
    for _ in run("shove_succeeded", ctx, target, result):
        pass
    outer.damage_cache.update({key: value for key, value in ctx.damage_cache.items() if isinstance(key, str)})
    return result


@effect("brutal_shove")
def brutal_shove(ctx: Any, row: dict[str, Any]) -> None:
    for target in [ctx.target] if ctx.target is not None else list(ctx.targets):
        shove(ctx, target, row)


@hook("candidate_allowed")
def too_large(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The size limit is part of the target line: a creature too large is not offered."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    row = next((e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") in ("brutal_shove", "brute_overrun")), None)
    if row is None or row.get("ignore_size"):
        return None
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if target is None:
        return None
    if row["type"] == "brute_overrun":
        return None
    from ..typed_executor import Context

    return None if size_ok(Context(engine, actor, action, None, typed, [target], target, {}), target, row) else False


# ------------------------------------------------------------------------------------------------ Overrun
@hook("compile_actions")
def overrun_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info.get("owned_ids") or ())
    if BRUTE not in set(info.get("spheres") or ()) or MANEUVERS not in owned:
        return None
    base = next((a for a in info.get("actions") or () if ((a.parameters or {}).get("typed") or {}).get("source") == BRUTAL_SHOVE
                 and " + " not in a.display_name and "#" not in a.source_definition_id), None)
    out = []
    for economy, suffix, label in ((EconomyKind.ACTION, "overrun", "Overrun"), (EconomyKind.BONUS_ACTION, "overrun_bonus", "Overrun (Bonus Action)")):
        typed = {"effects": [{"type": "brute_overrun", "applies_to": "target", DAMAGE_SCORE: True, "named_passage": True,
                              "evidence": "Overrun: Strength (Athletics) contested by the target's Strength (Athletics); Advantage if larger, "
                                          "Disadvantage if smaller; success: move through its space (difficult terrain), not ending there"}],
                 "numbers": info["numbers"], "duration": {"kind": "instant"}, "range_ft": 5, "source": MANEUVERS, "riders": []}
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.granted.{suffix}", display_name=label,
                                    owner_id=info["actor_id"], economy=economy, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                                    range_ft=5, parameters={"typed": typed, "expected_damage": 0, "replaces_attack": 0}))
    if base is not None:
        params = copy.deepcopy(base.parameters)
        row = next((e for e in params["typed"].get("effects") or [] if isinstance(e, dict) and e.get("type") == "brutal_shove"), None)
        if row is not None:
            row["mode"] = "aside"
            out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#shove_aside",
                                               "display_name": "Shove Aside", "parameters": params}))
    return out


@effect("brute_overrun")
def brute_overrun(ctx: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    from dataclasses import replace

    from ..typed_executor import run_effects

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    mine, theirs = _width(ctx, actor, "actor", row), _width(ctx, target, "subject", row)
    mode = {"ADVANTAGE"} if mine > theirs else {"DISADVANTAGE"} if mine < theirs else set()
    result = contest(ctx, target, mine_mode=mode, theirs_skills=("Athletics",), purpose="overrun", label="Overrun")
    if not result["success"]:
        note(engine, ctx.source, actor, f"{actor.display_name} fails to overrun {target.display_name} (Athletics {result['mine']} against "
             f"{result['theirs']}).", (target,))
        return result
    if row.get("shove_on_success"):
        note(engine, ctx.source, actor,
             f"{ctx.action.display_name}: {actor.display_name} wins the Overrun against {target.display_name} "
             f"(Athletics {result['mine']} against {result['theirs']}) and can continue through its space.", (target,))
        apply_shove_success(ctx, target, {**row, "no_manhandle": True}, result)
        return result
    if row.get('named_passage'):
        from .creature_passage import grant_named
        grant_named(ctx, target)
        note(engine, ctx.source, actor,
             f"Overrun: move through {target.display_name}'s space once this turn using your movement. "
             "That space costs double movement; stop in a free space.", (target,))
    else:
        note(engine, ctx.source, actor,
         f"{actor.display_name} wins the Overrun contest against {target.display_name} "
         f"(Athletics {result['mine']} against {result['theirs']}). If the printed rule allows it, "
         f"the GM must move {actor.display_name} through {target.display_name}'s space by hand; "
         "this game does not move the creature automatically yet.", (target,))
    if _row(engine, actor, "alternative_maneuvers") is None or not target.active:
        return result
    # Alternative Maneuvers: "When making an Overrun attempt, apply Brutal Shove damage and one Manhandle talent as though it were a
    # Brutal Shove."
    one = replace(ctx, target=target, targets=[target])
    dice = next((answer for answer in run("shove_damage", ctx, target) if answer is not None), None)
    damage = {"type": "damage", "applies_to": "target", "damage_types": ["bludgeoning"],
              "evidence": "Alternative Maneuvers: the Overrun deals Brutal Shove damage"}
    if dice is not None:
        damage.update(dice={"count": int(dice.count), "sides": int(dice.sides)}, flat=int(dice.modifier))
    else:
        damage["flat"] = max(0, strength_modifier(ctx.engine, actor, ctx.numbers, marker=DAMAGE_SCORE))
    if damage.get("dice") or damage["flat"] > 0:
        run_effects(one, [damage])
    options = _manhandle_rows(engine, actor)
    if options and target.active:
        labels = {name: f"Apply {name}" for name in options}
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "OVERRUN_MANHANDLE", actor.entity_id, target.entity_id), actor,
                     CHOICE + "overrun_manhandle", list(options), labels=labels, preferred=list(options)[:1], allow_decline=True,
                     target_id=actor.entity_id, name="Alternative Maneuvers",
                     prompt=f"Alternative Maneuvers: apply one Manhandle talent you know to {target.display_name} after the Overrun?")
        if picked and picked[0] in options:
            run_effects(one, options[picked[0]][1])
    return result


# ------------------------------------------------------------------------------------------------ advancing Overruns
RAM = "TAL_BRUTE_LIVING_BATTERING_RAM"
LINE = "TAL_BRUTE_FORTRESS_LINE_BREAKER"


@hook("compile_action")
def advancing_overrun_action(action: Any, info: dict[str, Any]) -> Any:
    """The talent's owned action is its ownership record, as with the maneuver buttons.

    These talents have no passive brute_shove row. Transform their existing action rather than relying on row_of
    or adding duplicate buttons; preserve its economy, costs and source, including Line Breaker's Martial Focus.
    """
    typed = (action.parameters or {}).get("typed") or {}
    source = typed.get("source")
    if source not in (RAM, LINE) or source not in set(info.get("owned_ids") or ()):
        return None
    params = copy.deepcopy(action.parameters)
    params["typed"] = {**typed, "effects": [{"type": "brute_advance", "applies_to": "self",
        "auto51_strength_score": True, DAMAGE_SCORE: True}], "riders": []}
    # The object damage clause remains explicit, not silently claimed as automated.
    if source == LINE:
        params["typed"]["riders"] = ["Fortress-Line Breaker: deal double damage to unattended mundane objects "
            "in your path. The GM resolves damage to those objects; an intact barrier still stops your movement."]
    params["expected_damage"] = 0
    params.pop("inert", None)
    return action.model_copy(update={"parameters": params, "target_kind": "SELF", "range_ft": 0})


def _advance_scope(engine: Any, actor: Any) -> dict[str, Any] | None:
    scope = getattr(engine, "_brute_advance_scope", None)
    if scope is None or scope["ctx"].actor is not actor:
        return None
    native = engine.movement_scope(actor.entity_id)
    # A nested reaction may grant this same actor a different move. It gets none of this action's benefits.
    return scope if native is None or native["source_id"] == scope["ctx"].source else None


@hook("pass_through")
def advancing_passage(engine: Any, mover: Any, occupant: Any) -> str | None:
    from ..relations import ENEMY, relation

    scope = _advance_scope(engine, mover)
    if scope is None or relation(engine, mover, occupant) != ENEMY:
        return None
    # Pure speculative permission makes the route offerable. movement_attempt must win the contest before entry.
    return "difficult"


@hook("opportunity_allowed")
def advancing_protection(engine: Any, reactor: Any, mover: Any) -> bool | None:
    scope = _advance_scope(engine, mover)
    if scope is not None and scope["ctx"].source == RAM and reactor.entity_id in scope["attempted"]:
        return False
    return None


@hook("difficult_exempt")
def advancing_terrain(engine: Any, actor: Any) -> Any:
    scope = _advance_scope(engine, actor)
    if scope is None or scope["ctx"].source != LINE:
        return None
    from ..motion import TerrainExemption

    return TerrainExemption({(x, y) for x in range(engine.grid.width) for y in range(engine.grid.height)},
                            nonmagical_only=True)


def _advance_paths(ctx: Any, feet: int) -> dict[str, tuple[Any, ...]]:
    """Straight rays, plus native gently curving routes for Line Breaker; never cross walls or end occupied."""
    from ..gate2_runtime_models import Position
    from ..granted_movement import path_cost, routes
    from ..target_knowledge import actors_for
    from ..relations import ENEMY, relation
    from .needle import cell_id

    engine, actor = ctx.engine, ctx.actor
    hostiles = [other for other in actors_for(engine, actor) if other.active and relation(engine, actor, other) == ENEMY]
    out = {}
    def offer(path):
        crossed = {other.entity_id for other in hostiles
                   if any(set(engine._actor_volume(actor, p)) & set(engine._actor_volume(other)) for p in path[1:])}
        if ctx.source == RAM and len(crossed) > 1:
            return
        try:
            cost = path_cost(engine, actor, path)
        except ValueError:
            return
        if cost <= feet:
            out.setdefault(cell_id(path[-1]), tuple(path))
    # Rays stay available even when shortest-path search would prefer detouring around an Overrun.
    for dx, dy in ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)):
        path = [actor.position]
        for n in range(1, feet // engine.grid.square_size_ft + 1):
            x, y = actor.position.x + n*dx, actor.position.y + n*dy
            if not (0 <= x < engine.grid.width and 0 <= y < engine.grid.height):
                break
            path.append(Position(x=x, y=y, z=actor.position.z))
            offer(path)
    if ctx.source == LINE:
        for _, (path, _, _) in routes(engine, actor, feet).items():
            headings = [(b.x-a.x, b.y-a.y) for a, b in zip(path, path[1:])]
            # A gentle curve has no right-angle corner or doubling back.
            if all(ax*bx + ay*by > 0 for (ax, ay), (bx, by) in zip(headings, headings[1:])):
                offer(path)
    return out


@effect("brute_advance")
def advancing_overrun(ctx: Any, row: dict[str, Any]) -> None:
    """One transaction-local path/contest scope; player pauses unwind it along with native movement."""
    ctx = ctx.with_source(ctx.typed.get("source"))
    engine, actor = ctx.engine, ctx.actor
    if ctx.source not in (RAM, LINE):
        return
    feet = engine._effective_speed(actor) // (2 if ctx.source == RAM else 1)
    if feet <= 0:
        return
    previous_scope = getattr(engine, "_brute_advance_scope", None)
    scope = {"ctx": ctx, "attempted": set(), "manhandle": False}
    engine._brute_advance_scope = scope
    try:
        paths = _advance_paths(ctx, feet)
        if not paths:
            return
        from ..target_knowledge import actors_for
        from ..relations import ENEMY, relation

        hostiles = [other for other in actors_for(engine, actor) if other.active and relation(engine, actor, other) == ENEMY]
        def rank(key):
            path = paths[key]
            return (sum(any(set(engine._actor_volume(actor, p)) & set(engine._actor_volume(other)) for p in path[1:])
                        for other in hostiles), len(path))
        preferred = max(paths, key=rank)
        name = ctx.action.display_name
        picked = ask(engine, ctx.intent, checkpoint_id(engine, "BRUTE_ADVANCE", actor.entity_id), actor,
            CHOICE + "brute_advance_path", list(paths),
            labels={key: f"Move to ({path[-1].x}, {path[-1].y}), up to {feet} feet; Overrun enemies in the path"
                    for key, path in paths.items()}, preferred=[preferred], allow_decline=True,
            target_id=actor.entity_id, name=name,
            prompt=f"{name}: choose your movement path (up to {feet} feet). "
                   "An Overrun contests Strength (Athletics); failure stops before the creature. "
                   + ("The Overrun target cannot make an Opportunity Attack against this move." if ctx.source == RAM
                      else "This Action spends Martial Focus; one successful Overrun may also apply a Manhandle talent."))
        if picked and picked[0] in paths:
            engine.grant_movement(actor, paths[picked[0]], ctx.source, feet=feet, intent=ctx.intent)
    finally:
        engine._brute_advance_scope = previous_scope


@hook("movement_attempt")
def advancing_entry(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    from dataclasses import replace
    from ..relations import ENEMY, relation

    scope = _advance_scope(engine, mover)
    native = engine.movement_scope(mover.entity_id)
    if scope is None or native is None or native["source_id"] != scope["ctx"].source:
        return None
    ctx = scope["ctx"]
    after = set(engine._actor_volume(mover, nxt))
    before = set(engine._actor_volume(mover, previous))
    targets = [other for other in engine.state.actors.values()
               if other.active and relation(engine, mover, other) == ENEMY
               and after & set(engine._actor_volume(other)) and not before & set(engine._actor_volume(other))]
    for target in sorted(targets, key=lambda other: (engine._distance_actor_to_actor(mover, other), other.entity_id)):
        if target.entity_id in scope["attempted"]:
            continue
        if ctx.source == RAM and scope["attempted"]:
            return {"stop": True, "source_id": ctx.source,
                    "label": "Living Battering Ram stops: it allows only one Overrun during this move."}
        scope["attempted"].add(target.entity_id)
        # Hammer and every other shove rider recognize the ordinary Brutal Shove context.
        one = replace(ctx, intent=intent, target=target, targets=[target],
                      typed={**ctx.typed, "source": BRUTAL_SHOVE}, damage_cache={})
        result = brute_overrun(one, {"type": "brute_overrun", "shove_on_success": True})
        if not result or not result["success"]:
            return {"stop": True, "source_id": ctx.source,
                    "label": f"{ctx.action.display_name} stops before {target.display_name}: the Overrun failed."}
        if scope["manhandle"] or not manhandle_options(engine, mover) or not target.active:
            continue
        name = ctx.action.display_name
        if ctx.source == LINE:
            picked = ask(engine, intent, checkpoint_id(engine, "ADVANCE_MANHANDLE", mover.entity_id, target.entity_id), mover,
                         CHOICE + "advance_manhandle_when", ["apply", "save"],
                         labels={"apply": f"Apply one Manhandle talent to {target.display_name}",
                                 "save": "Save the Manhandle talent for a later successful Overrun in this move"},
                         preferred=["apply"], target_id=mover.entity_id, name=name,
                         prompt=f"{name}: your Overrun of {target.display_name} succeeded. Apply your one Manhandle talent now "
                                "or save it for a later success? No additional Action or resource cost.")
            if picked != ["apply"]:
                continue
        applied = apply_manhandle(one, target, feature=name, choice_id="advance_manhandle",
            prompt=f"{name}: which Manhandle talent do you apply to {target.display_name} after this successful Overrun? "
                   "No additional Action or resource cost.")
        scope["manhandle"] = applied is not None
    return None


# ------------------------------------------------------------------------------------------------ Rooted Stance, Mighty Hurl
def _rooted(engine: Any, creature: Any) -> bool:
    from .ability_source import has_row

    return creature.resources.get(FOCUS, 0) >= 1 and has_row(engine, creature.entity_id, "brute_rooted")


@hook("contest_mode")
def rooted_stance_contest(engine: Any, creature: Any, role: str, purpose: str, other: Any) -> str | None:
    """Rooted Stance (holding Martial Focus): "gain Advantage on checks and saving throws against forced movement" -- resisting a shove."""
    return "ADVANTAGE" if role == "resist" and purpose == "shove" and _rooted(engine, creature) else None


@hook("save")
def rooted_stance_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if "forced_movement" in {str(n) for n in named or ()} and _rooted(ctx.engine, subject):
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("forced_movement_bonus")
def mighty_hurl(ctx: Any, subject: Any, eff: dict[str, Any]) -> int | None:
    """Mighty Hurl: "When using Throw: increase additional movement from 10 feet to 20 feet"."""
    return 10 if eff.get("brute_throw") and _row(ctx.engine, ctx.actor, "mighty_hurl") is not None else None


@hook("reaction_geometry_allowed")
def shove_needs_reach(engine: Any, reactor: Any, source: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    """A reaction that answers with a Brutal Shove (Shift Weight: "Shove the triggering creature") needs that creature within reach,
    as the attack it replaced did (typed_reactions.attack_reaches only looks at attack rows)."""
    if source is None or not any(isinstance(e, dict) and e.get("type") == "brutal_shove" for e in row.get("effects") or []):
        return None
    from ..typed_reactions import opportunity_reach

    return None if engine._distance_actor_to_actor(reactor, source) <= int(opportunity_reach(engine, reactor) or 5) else False
