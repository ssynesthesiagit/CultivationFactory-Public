"""Athletics sphere automation (lane AUTO8; reviewed typing in authority/typed_mechanics/reviewed_final.d/auto8-athletics.json
and the passive rows in combat/rules/feature_blocks.d/auto8-athletics.json).

Every rule this module owns is printed in the owner's Sphere Compendium and read from
``authority/typed_mechanics/rules_text.json``; nothing here is keyed on an ability id inside a core engine file, and no hook
fires for a creature that does not own the row it checks, or does not hold the condition the clause needs.

Deliberately NOT automated here (the lane report names each one with its reason): the maps carry no water, no climbable
face and no separate altitude kind, so Shark Swim's Swim Speed, Spider's Touch's Climb Speed, Terrain Glide, Rope Swing
Adept's climb, Wall Stunt's vertical running and Air Stunt are map-shaped text rather than engine work; there is no breath
clock, so Strong Lungs' breath-holding multiplier stays text; there is no Tumble check on this table, so Sudden Flank and
Whirlwind Flip have no check to hang a trigger on; Body Beyond Distance and Athletic Training are travel and character
creation; a jump here rises whole 5-foot steps and has no horizontal-distance value, so Polearm Vaulter's +10 feet of
jump distance stays GM-read. Court of Ten Thousand Steps moved here from the retired combat/ext/bodyb_motion.py so one
module owns the whole talent; its stance condition id, its +20 feet Speed and its 1-minute clock are unchanged, and every
clause is read from that persisted stance, so a fight stored before these rows existed keeps the Speed, the free stand and
the terrain clause it was always given.

Ownership and shared helpers (consumers: this module, the Athletics regression tests, and the
``athletics`` rows themselves):

  owns(engine, actor, kind)    -> bool: this fighter has that Athletics passive row.
  focus_held(actor)            -> int: Martial Focus currently held (spending is not an Action).
  turn_moved_ft(engine, actor) -> int: this turn's own willing movement (combat.ext.hold_still.moved_ft, the one
                                  implementation; teleports count as the ground they cross, forced displacement does not).
  _moved_ft_this_turn(...)     -> that plus the route in progress (combat.movement_steps.context), so one
                                  uninterrupted 20-foot route reads as 20 feet at its own checkpoints.
  used_this_turn / mark_turn_use / spent_this_turn -> the once-per-turn flags, stored as strings (a turn stamp, so a
                                  saved fight reloads them unchanged and nothing rests the rest of the fight by accident).
  _drop_condition(...)         -> remove exactly one condition instance (combat/gate2_engine._remove_condition
                                  removes every instance of an id, which would end another creature's hold too).

Shared beyond this module: combat/flight.py ``jump_score`` reads the two documented jump hooks (``jump_ability``,
``jump_bonus_ft``) this module answers for Mighty Conditioning, Polearm Vaulter and Flowing Pursuit. The "+N Armor Class
against one named creature" it applies for Flowing Pursuit is the ``condition:typed.ac_against`` shape
combat/ext/nine_star.py owns (its ``ac_against`` effect and its generic ``hit_response`` reader); no second Armor Class
reader is registered here.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, needle, note
from .hold_still import moved_ft as turn_moved_ft
from .needle import ask, checkpoint_id

BLOCK = "athletics"
FOCUS = "resource:core.martial_focus"
COORDINATED = "ATHLETICS_BASE_COORDINATED_MOVEMENT"
CHOICE_PREFIX = "choice:needle.athletics."

# The passive kinds this module owns. ``compile_athletics`` refuses anything else, so a typo in the feature blocks file is
# inert rather than a silent behaviour change.
KINDS = (
    "moving_target", "court_of_steps", "heaven_treading", "sparrows_path", "powerful_wings",
    "helicopter_descent", "flash_step", "speed_boost", "dizzying_tumble",
    "meridian_threading", "flowing_pursuit", "one_breath", "polearm_vaulter", "mighty_conditioning",
)
# The shared combat/motion.py row kinds an Athletics clause may borrow (Speed, difficult terrain, Focus on an action).
MOTION_KINDS = ("speed_bonus", "ignore_difficult", "oa_disadvantage", "afterimage", "regain_focus")


def rows_of(engine: Any, actor: Any) -> dict[str, dict[str, Any]]:
    """This fighter's Athletics rows, keyed by kind."""
    return {str(row.get("kind")): row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, ())
            if row.get("block") == BLOCK and row.get("kind")}


def owns(engine: Any, actor: Any, kind: str) -> bool:
    return kind in rows_of(engine, actor)


def row_of(engine: Any, actor: Any, kind: str) -> dict[str, Any] | None:
    return rows_of(engine, actor).get(kind)


def focus_held(actor: Any) -> int:
    return int(actor.resources.get(FOCUS, 0) or 0)


def _turn_key(engine: Any, actor: Any) -> str:
    return f"athletics_turn:{engine.state.round_number}:{engine.state.current_slot_index}:{actor.entity_id}"


def used_this_turn(engine: Any, actor: Any, flag: str) -> bool:
    """Whether that once-per-turn use is already spent (a pure read, so an offer can ask without spending it)."""
    return str(actor.turn_flags.get(f"athletics_used:{flag}") or "") == _turn_key(engine, actor)


def mark_turn_use(engine: Any, actor: Any, flag: str) -> None:
    actor.turn_flags[f"athletics_used:{flag}"] = _turn_key(engine, actor)


def spent_this_turn(engine: Any, actor: Any, flag: str) -> bool:
    """Read and record one once-per-turn use. Both are strings: a saved-fight-safe turn stamp."""
    if used_this_turn(engine, actor, flag):
        return True
    mark_turn_use(engine, actor, flag)
    return False


def hostiles(engine: Any, actor: Any) -> list[Any]:
    return sorted((other for other in engine.state.actors.values()
                   if other.active and other.team_id != actor.team_id and other.entity_id != actor.entity_id),
                  key=lambda other: other.entity_id)


def _opportunity_reactors(engine: Any, mover: Any) -> list[str]:
    """Every creature that could make an Opportunity Attack against ``mover`` right now, as ids.

    The shared granted-movement path (``combat/ext/granted_movement.py``) suppresses exactly the ids it is
    handed, so a clause that is printed for every enemy has to name them all: handing it only the attacker that
    just missed left every other enemy free to attack ``mover`` for stepping out of *its* reach
    (independent review AUTO8r1, R2). The enemy test is the engine's own ``relation`` query -- the same one
    ``gate2_engine._resolve_leave_reach`` uses to collect its reactors -- so nothing the engine would not have
    attacked is exempted, and nothing it would have attacked is left standing."""
    from ..relations import ENEMY, relation

    return sorted(other.entity_id for other in engine.state.actors.values()
                  if other.active and other.entity_id != mover.entity_id
                  and relation(engine, other, mover) == ENEMY)


def _moved_ft_this_turn(engine: Any, mover: Any, previous: Any, nxt: Any) -> int:
    """How far this fighter has moved this turn, including the step being taken right now.

    ``turn_moved_ft`` counts this turn's *committed* routes; the route in progress is committed only when
    it finishes, so a single continuous 20-foot walk looks like 5, 10, 15 feet at its own checkpoints. The
    movement checkpoint's read-only context (combat/movement_steps.context) carries the feet already
    covered on the route in progress, which is what makes one uninterrupted route count as 20 feet."""
    from .. import movement_steps

    walked = turn_moved_ft(engine, mover)
    on_route = int(movement_steps.context(engine, mover).get("travelled_ft") or 0)
    return walked + max(on_route, engine.grid.distance_ft(previous, nxt) if previous is not None and nxt is not None else 0)


def _grant_step(engine: Any, actor: Any, feet: int, source: str, *, free_of_oa: bool = True) -> None:
    """Immediate movement that costs no Action: the same shape as Banner's and Formation's printed free steps."""
    actor.movement_remaining_ft += feet
    if free_of_oa:
        actor.turn_flags["oa_free_ft"] = int(actor.turn_flags.get("oa_free_ft") or 0) + feet
    engine._append_event("MOVEMENT_GRANTED", source, actor_id=actor.entity_id, payload={"distance_ft": feet})


@hook("compile_block")
def compile_athletics(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    """One passive row per printed clause of an Athletics feature (``rules``), or one for a single ``kind``.

    A clause may also ask for one of the shared ``motion`` row kinds (combat/motion.py: Speed, difficult terrain, Focus),
    which is how the sphere's other movement passives are declared; ``purchases`` counts a talent bought twice."""
    if block != BLOCK:
        return None
    rules = spec.get("rules") if isinstance(spec.get("rules"), list) else [spec]
    out = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        kind = str(rule.get("kind") or "")
        if kind in KINDS:
            out.append({**row, "block": BLOCK, "kind": kind, "numbers": dict(numbers),
                        **{key: value for key, value in rule.items() if key not in {"kind", "motion"}}})
        for shared in rule.get("motion") or ():
            if str(shared) not in MOTION_KINDS:
                continue
            out.append({**row, "block": "motion", "kind": str(shared), "numbers": dict(numbers),
                        **{key: value for key, value in rule.items() if key not in {"kind", "motion"}}})
    return out or None


# =========================================================================================== Heaven-Treading Body
# "Your cultivated motion no longer requires ordinary support. Gain: Fly Speed equal to land Speed; Hover; ignore
#  nonmagical difficult terrain; move across water, fragile surfaces, falling debris, and open air as though they were stable
#  terrain; reduce falling damage to 0."
HEAVEN = "TAL_ATHLETICS_HEAVEN_TREADING_BODY"
SPARROWS = "TAL_ATHLETICS_SPARROW_S_PATH"
WINGS = "TAL_ATHLETICS_POWERFUL_WINGS"


def _own_fly_speed(engine: Any, actor: Any) -> int:
    """The Fly Speed this fighter already has from recorded data or this module's own rows."""
    speed = int(actor.fly_speed_ft or 0)
    if owns(engine, actor, "heaven_treading"):
        speed = max(speed, engine._effective_speed(actor))
    if owns(engine, actor, "sparrows_path"):
        speed = max(speed, int(actor.speed_ft or 0) // 2)
    for condition in actor.conditions.values():
        speed = max(speed, int((condition.data or {}).get("fly_speed_ft") or 0))
    return speed


@hook("flight")
def athletics_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Heaven-Treading Body (Fly Speed equal to land Speed, Hover) and Sparrow's Path (half the base land Speed)."""
    row = row_of(engine, actor, "heaven_treading")
    if row is not None:
        return {"fly_speed_ft": int(engine._effective_speed(actor)), "flight_hover": 1}
    row = row_of(engine, actor, "sparrows_path")
    if row is not None:
        return {"fly_speed_ft": max(1, int(actor.speed_ft or 0) // 2)}
    return None


@hook("falling_damage")
def heaven_no_fall_damage(engine: Any, target: Any, defended: int, fall: Any, intent: Any) -> dict[str, Any] | None:
    """Heaven-Treading Body: "reduce falling damage to 0" (its "land on your feet" is Hover's ordinary landing)."""
    if not owns(engine, target, "heaven_treading"):
        return None
    return {"amount": 0, "land_prone": False}


# =========================================================================================== Powerful Wings
@hook("flight")
def powerful_wings_hover(engine: Any, actor: Any) -> dict[str, Any] | None:
    """Powerful Wings: "If you possess a Fly Speed through physical wings, you may Hover."

    The fighter's own Heaven-Treading Body and Sparrow's Path rows are its physical flight; a recorded Fly Speed from any
    other source (Featherfall's protection, another sphere's temporary flight) is not wings and gets no Hover."""
    if not owns(engine, actor, "powerful_wings"):
        return None
    return {"flight_hover": 1} if _own_fly_speed(engine, actor) > 0 else None


# =========================================================================================== Moving Target
# "When you move more than 20 feet during your turn, gain Half Cover against ranged attacks and ranged supernatural effects
#  until the start of your next turn. If you move at least 40 feet, expend Martial Focus to gain Three-Quarters Cover
#  instead." A second purchase: "Its cover applies against melee attacks as well."
MOVING_TARGET = "TAL_ATHLETICS_MOVING_TARGET"
MOVING_TARGET_DEEP = "condition:typed.moving_target_three_quarters"
MOVING_TARGET_LABEL = "Moving Target: Three-Quarters Cover"


def _moving_target(engine: Any, actor: Any) -> int:
    """0, 2 or 5: the cover this fighter currently has from Moving Target (pure; spends nothing)."""
    row = row_of(engine, actor, "moving_target")
    if row is None or turn_moved_ft(engine, actor) <= 20:
        return 0
    if any(c.condition_id == MOVING_TARGET_DEEP for c in actor.conditions.values()):
        return 5
    return 2


@hook("cover")
def moving_target_cover(engine: Any, attacker: Any, target: Any) -> int | None:
    """Half/Three-Quarters Cover against ranged attacks (the printed base case)."""
    if target is None:
        return None
    return _moving_target(engine, target) or None


@hook("directional_cover")
def moving_target_melee(engine: Any, attacker: Any, target: Any, ray: dict[str, Any]) -> int | None:
    """A second purchase: "Its cover applies against melee attacks as well" (melee rays only)."""
    if target is None or ray.get("purpose") != "attack" or ray.get("ranged"):
        return None
    row = row_of(engine, target, "moving_target")
    if row is None or int(row.get("purchases") or 1) < 2:
        return None
    return _moving_target(engine, target) or None


@hook("compile_actions")
def moving_target_choice(info: dict[str, Any]) -> list[Any] | None:
    """A free choice: spend Martial Focus to take Three-Quarters Cover instead of Half Cover this turn.

    Not a ``setting_only`` selector: paying Martial Focus is a real cost, so the engine's ordinary payment path owns it."""
    if MOVING_TARGET not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "moving_target_deep", "applies_to": "self",
                          "evidence": "If you move at least 40 feet, expend Martial Focus to gain Three-Quarters Cover instead."}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": MOVING_TARGET}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.moving_target_deep",
                             display_name="Moving Target: Three-Quarters Cover", owner_id=info["actor_id"],
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                             costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0})]


@hook("candidate_allowed")
def moving_target_choice_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != MOVING_TARGET:
        return None
    if any(c.condition_id == MOVING_TARGET_DEEP for c in actor.conditions.values()):
        return False  # already taken this turn
    if focus_held(actor) < 1:
        return False
    return None if turn_moved_ft(engine, actor) >= 40 else False


@effect("moving_target_deep")
def moving_target_deep(ctx: Any, row: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    engine._apply_condition(actor, MOVING_TARGET_DEEP, MOVING_TARGET, actor.entity_id,
                            expires_on="START_OF_SOURCE_NEXT_TURN", data={"label": MOVING_TARGET_LABEL})


@hook("status_description")
def moving_target_text(engine: Any, holder: Any, row: Any = None, data: Any = None) -> dict[str, Any] | None:
    bonus = _moving_target(engine, holder) if holder is not None else 0
    if not bonus:
        return None
    return {"text": f"{'Three-Quarters' if bonus == 5 else 'Half'} Cover (Moving Target)"}

# ================================================================================= Court of Ten Thousand Steps
# "For the duration: increase all movement Speeds by 20 feet; ignore nonmagical difficult terrain; stand from Prone without
#  spending movement; move through allied spaces normally; climb ordinary surfaces without a check; once per turn after
#  moving at least 20 feet, regain Martial Focus; once per turn when a hostile creature misses you, move 5 feet without
#  provoking Opportunity Attacks. Court of Ten Thousand Steps ends early if you become Incapacitated."
#
# The 1-minute Bonus Action stance and its +20 feet Speed are the printed action and its ``speed`` hook. The remaining
# clauses are read from the same stance while it lasts. "Move through allied spaces normally" is what the table already
# does (only hostile spaces are Difficult Terrain, combat/gate2_engine.py _hostile_difficult_cells), and the maps carry no
# climbable face, so neither needs a row here.
COURT = "TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS"
COURT_STANCE = "Court of Ten Thousand Steps"
# Court's own condition id. The sphere never lends the shared ``condition:typed.ignore_difficult`` to
# another creature (or takes it away from one): Thousand-Mile Legs, Lotus Step and the Jade Sovereign
# each apply that id for their own talent, and ``_remove_condition`` removes by condition id, not by
# source. The rule row "court_of_steps" in combat/rules/typed_conditions.json carries the printed terrain
# clause, so combat/motion.py ignores_difficult still reads it through the shared query.
COURT_CLAUSES = "condition:typed.court_of_steps"
# The condition id Court published for the same printed clause before it had an id of its own. A fight stored
# then still holds that instance, so the terrain clause has to be recognised by *source* as well as by id
# (independent review AUTO8r1, R3): matching only ``COURT_CLAUSES`` left a resumed old cast's terrain benefit
# in the fight after its owner was incapacitated, because ``motion.ignores_difficult`` still read the shared
# row until that instance's own expiry. Only instances this stance applied are ever touched -- another
# creature's ``condition:typed.ignore_difficult`` (Thousand-Mile Legs, Lotus Step, the Jade Sovereign) has a
# different source and is left alone.
COURT_LEGACY_CLAUSES = "condition:typed.ignore_difficult"
COURT_CLAUSE_LABEL = "Court of Ten Thousand Steps: difficult terrain ignored, stand from Prone for free"


def _court_stance(actor: Any) -> Any | None:
    from .. import stances

    return next((condition for condition in stances.active(actor)
                 if str((condition.data or {}).get("name") or "") == COURT_STANCE), None)


def _court(engine: Any, actor: Any) -> bool:
    """Whether Court of Ten Thousand Steps is running for this fighter right now.

    Read from the persisted stance alone, never from this lane's passive row: a bundle compiled before
    those rows existed still carries the named one-minute stance, and the +20 feet Speed it has always
    been given must survive that (the retired combat/ext/bodyb_motion.py read the stance and nothing
    else). Only Court's own action puts that stance on a creature, so a fighter that does not own the
    talent can never hold one and this stays inert for everyone else."""
    return _court_stance(actor) is not None


def _court_markers(actor: Any) -> list[Any]:
    """Every instance of the printed terrain clause that Court's own stance put on this fighter.

    Both the current ``court_of_steps`` id and the ``ignore_difficult`` id an older stored cast used are
    recognised, and only when the source is Court, so one talent's instance is never confused with another's.
    There is at most one of each, but this returns a list because the early end has to take off whichever of
    them a given save happens to be holding."""
    return [condition for condition in actor.conditions.values()
            if condition.condition_id in (COURT_CLAUSES, COURT_LEGACY_CLAUSES)
            and condition.source_definition_id == COURT]


def _drop_condition(engine: Any, actor: Any, instance_id: str, source: str, *, label: str = "") -> bool:
    """Take off exactly one condition instance (``_remove_condition`` takes off every instance of the id)."""
    if instance_id not in actor.conditions:
        return False
    condition_id = actor.conditions[instance_id].condition_id
    del actor.conditions[instance_id]
    engine._append_event("CONDITION_REMOVED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"condition_id": condition_id, "instance_id": instance_id,
                                  **({"reason": label} if label else {})})
    return True


@hook("speed")
def court_speed(engine: Any, actor: Any) -> int | None:
    """+20 feet to every movement Speed while the stance runs."""
    return 20 if _court(engine, actor) else None


@hook("speed_explanation")
def court_speed_label(engine: Any, actor: Any) -> list[dict[str, Any]] | None:
    """The player-facing cause of the +20 feet (combat/ext/__init__.py movement presentation query)."""
    if not _court(engine, actor):
        return None
    return [{"label": "Court of Ten Thousand Steps", "delta_ft": 20, "source_id": COURT}]


def _apply_court_clauses(engine: Any, actor: Any) -> None:
    """Publish Court's standing clauses on its own condition id, for the stance's own clock.

    A stance that a save was already holding carries the older ``ignore_difficult`` instance instead, so it is
    migrated onto the current id here rather than left behind: both rows grant the same printed clause, and
    leaving both would show the fighter two terrain pills for one stance."""
    stance = _court_stance(actor)
    if stance is None:
        return
    markers = _court_markers(actor)
    if any(condition.condition_id == COURT_CLAUSES for condition in markers):
        return
    for condition in markers:
        _drop_condition(engine, actor, condition.instance_id, COURT, label="moved to Court's own condition")
    engine._apply_condition(actor, COURT_CLAUSES, COURT, actor.entity_id, expires_on=stance.expires_on,
                            data={"label": COURT_CLAUSE_LABEL})


@hook("technique_used")
def court_clauses(ctx: Any) -> None:
    """While the stance runs: ignore nonmagical difficult terrain (the printed clause)."""
    if str(ctx.typed.get("source") or "") == COURT:
        _apply_court_clauses(ctx.engine, ctx.actor)


@hook("turn_start")
def court_clauses_republished(engine: Any, actor: Any) -> None:
    """Re-publish the stance's clauses at a turn boundary if they are missing.

    A saved fight that already held the stance when it was stored has no clause condition of this
    lane's shape in it (it was compiled before the row existed); the printed terrain clause is part of
    the stance, not of the cast, so it comes back at the next turn rather than never."""
    _apply_court_clauses(engine, actor)


@hook("became_incapacitated")
def court_ends_incapacitated(engine: Any, actor: Any, event: Any) -> None:
    """"Court of Ten Thousand Steps ends early if you become Incapacitated" (its own instances only).

    Both of the condition ids a stored cast may carry are taken off, so a fight saved before Court had an id of
    its own loses the terrain clause with the stance instead of keeping it until that instance's own expiry."""
    stance = _court_stance(actor)
    if stance is None:
        return
    for marker in _court_markers(actor):
        _drop_condition(engine, actor, marker.instance_id, COURT)
    _drop_condition(engine, actor, stance.instance_id, stance.source_definition_id)


@hook("stand_cost")
def court_stand_free(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """"stand from Prone without spending movement", read from the stance so a resumed old fight keeps it."""
    return 0 if _court(engine, actor) else None


@hook("movement_step")
def court_regain_focus(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """"once per turn after moving at least 20 feet, regain Martial Focus"."""
    if mover is None or not _court(engine, mover) or mover.entity_id != engine.state.current_actor_id:
        return None
    if _moved_ft_this_turn(engine, mover, previous, nxt) < 20:
        return None
    # Nothing is spent until the printed Focus can actually come back: regaining "only if it is
    # currently absent", and a fighter already holding it has not used the once-per-turn benefit.
    if used_this_turn(engine, mover, "court_focus") or focus_held(mover) >= 1:
        return None
    mark_turn_use(engine, mover, "court_focus")
    engine._gain_resource(mover, FOCUS, 1, COURT)
    note(engine, COURT, mover, f"{mover.display_name} moves at least 20 feet and regains Martial Focus (Court of Ten Thousand Steps).")
    return None


@hook("after_miss")
def court_step_after_a_miss(ctx: Any, target: Any) -> None:
    """"once per turn when a hostile creature misses you, move 5 feet without provoking Opportunity Attacks".

    ``ctx.actor`` is the attacker that missed and ``target`` the creature it missed, so the stance is read
    from the creature that was attacked (the same reading combat/ext/bodyb_choices.py's Turning Guard uses).
    The move is a real, immediate and optional step resolved by the shared granted-movement path
    (combat/ext/granted_movement.py, the one implementation behind Swaying Guard's printed 5 feet), not a
    movement allowance the next turn's reset would take back."""
    from . import rider_choices

    engine, attacker = ctx.engine, ctx.actor
    if target is None or not target.active or attacker.team_id == target.team_id or not _court(engine, target):
        return
    if used_this_turn(engine, target, "court_step"):
        return
    feet = int((row_of(engine, target, "court_of_steps") or {}).get("miss_step_ft") or 5)
    if not rider_choices.step(engine, target, "court_step_after_a_miss", COURT_STANCE, attacker, feet, COURT,
                              ctx.intent, trigger=(f"{attacker.display_name} misses {target.display_name}; move up to "
                                                  f"{feet} feet without provoking any Opportunity Attack"),
                              ignored_oa=_opportunity_reactors(engine, target)):
        return
    mark_turn_use(engine, target, "court_step")
    note(engine, COURT, target,
         f"{target.display_name} moves {feet} feet without an Opportunity Attack (Court of Ten Thousand Steps).",
         (attacker,))


# =========================================================================================== Speed Boost
# "When taking Dash or Disengage as an Action, move an additional 10 feet. You may also expend Martial Focus to increase
#  all movement Speeds by 50 feet for rounds equal to your Constitution modifier, minimum 1 round. When the duration
#  ends, gain one level of Exhaustion until completing a short or long rest. This Exhaustion applies even if you are
#  normally immune. You cannot activate this boost while your Exhaustion exceeds 2."
SPEED_BOOST = "TAL_ATHLETICS_SPEED_BOOST"
BOOST_CONDITION = "condition:typed.speed_boost"
BOOST_LABEL = "Speed Boost: +50 feet of Speed"


def _con_modifier(engine: Any, actor: Any) -> int:
    """"rounds equal to your Constitution modifier": the fighter's own persisted Constitution modifier."""
    from ..ability_checks import ability_modifier

    return int(ability_modifier(actor, "CON"))


@hook("compile_actions")
def speed_boost_actions(info: dict[str, Any]) -> list[Any] | None:
    """The printed Dash/Disengage extension rides the shared ``motion`` rows; this is the optional +50 foot boost."""
    if SPEED_BOOST not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "speed_boost", "applies_to": "self", "evidence": "expend Martial Focus to increase all movement "
                                                                                      "Speeds by 50 feet for rounds equal to your "
                                                                                      "Constitution modifier, minimum 1 round"}],
             "numbers": info["numbers"], "duration": {"kind": "rounds", "amount": 1}, "riders": [], "source": SPEED_BOOST}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.speed_boost",
                             display_name="Speed Boost: +50 feet of Speed", owner_id=info["actor_id"],
                             economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF", costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0})]


@hook("candidate_allowed")
def speed_boost_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Once a round, and never while Exhaustion is above 2 (the printed activation limit)."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != SPEED_BOOST:
        return None
    from . import forged_exhaustion

    if forged_exhaustion.level(actor) > 2:
        return False
    if any(c.condition_id == BOOST_CONDITION for c in actor.conditions.values()):
        return False
    return None if not used_this_turn(engine, actor, "speed_boost") else False


@effect("speed_boost")
def speed_boost(ctx: Any, row: dict[str, Any]) -> None:
    """+50 feet of Speed for rounds equal to the Constitution modifier, minimum 1 (the printed formula)."""
    engine, actor = ctx.engine, ctx.actor
    rounds = max(1, _con_modifier(engine, actor))
    engine._apply_condition(actor, BOOST_CONDITION, SPEED_BOOST, actor.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + rounds}",
                            data={"label": BOOST_LABEL, "con_mod": rounds})
    note(engine, SPEED_BOOST, actor,
         f"{actor.display_name} spends Martial Focus: every movement Speed rises by 50 feet for {rounds} round"
         f"{'' if rounds == 1 else 's'}, then one level of Exhaustion.")


@hook("effect_expiring")
def speed_boost_exhaustion(engine: Any, holder: Any, row: Any) -> None:
    """"When the duration ends, gain one level of Exhaustion until completing a short or long rest"."""
    if holder is None or getattr(row, "condition_id", None) != BOOST_CONDITION:
        return
    from . import forged_exhaustion

    forged_exhaustion.add(engine, holder, 1, SPEED_BOOST)
    note(engine, SPEED_BOOST, holder, f"{holder.display_name}'s Speed Boost ends, leaving one level of Exhaustion.")


@hook("speed")
def speed_boost_speed(engine: Any, actor: Any) -> int | None:
    if not any(c.condition_id == BOOST_CONDITION for c in actor.conditions.values()):
        return None
    row = row_of(engine, actor, "speed_boost")
    return int(row.get("boost_ft") or 50) if row is not None else None


@hook("speed_explanation")
def speed_boost_label(engine: Any, actor: Any) -> list[dict[str, Any]] | None:
    if not any(c.condition_id == BOOST_CONDITION for c in actor.conditions.values()):
        return None
    return [{"label": "Speed Boost", "delta_ft": 50, "source_id": SPEED_BOOST}]


@hook("action_completed")
def speed_boost_dash_extra(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    """"When taking Dash or Disengage as your Action, move an additional 10 feet" (never as a Bonus Action)."""
    from .. import motion

    if economy != "ACTION" or motion.ACTIONS.get(source_definition_id) not in ("dash", "disengage"):
        return
    row = row_of(engine, actor, "speed_boost")
    if row is None:
        return
    _grant_step(engine, actor, int(row.get("action_extra_ft") or 10), SPEED_BOOST, free_of_oa=False)


# =========================================================================================== Flash Step
# "When you take the Dash Action, expend Martial Focus. Teleport into your final destination without passing through
#  intervening spaces. The destination: must be visible; must be legal and unoccupied; must be within the distance you
#  could move through the Dash; cannot cross a Dimensional Lock; cannot cross a sealed boundary."
# The teleport itself is the shared self-teleport shape (combat/gate4_engine.py builds the visible, legal, unoccupied
# squares within reach; combat/ext/teleport_steps.py owns the sealed-boundary and Dimensional-Lock refusals), so this
# module only owns what the talent adds: the button and its Martial Focus cost.
FLASH_STEP = "TAL_ATHLETICS_FLASH_STEP"


@hook("compile_actions")
def flash_step_action(info: dict[str, Any]) -> list[Any] | None:
    if FLASH_STEP not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "teleport", "applies_to": "self", "distance_ft": "speed",
                          "evidence": "Teleport into your final destination without passing through intervening spaces."}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": FLASH_STEP}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.flash_step",
                             display_name="Flash Step", owner_id=info["actor_id"], economy=EconomyKind.ACTION,
                             resolution_kind="TYPED", target_kind="SELF", costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0})]


@hook("candidate_allowed")
def flash_step_needs_focus(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Only while the printed Martial Focus is held: it is the whole cost, and one Focus is the limit the text sets.

    The printed trigger is "when you take the Dash Action". The table cannot re-open a spent Action, so Flash Step is
    the Action that spends that Dash: the fighter teleports instead of walking, at their Speed, which is the distance the
    printed text measures. The Dash Action itself stays available and unchanged."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != FLASH_STEP:
        return None
    return None if focus_held(actor) >= 1 else False


# =================================================================================== Helicopter Descent
# "When you end your turn in the air while wielding an appropriate polearm, rope, chain, whip, or tether item, use your
#  Reaction and expend Martial Focus. For rounds equal to your Proficiency Bonus: fall no faster than 60 feet per round;
#  take no falling damage if you land before the effect ends; land on your feet."
HELICOPTER = "TAL_ATHLETICS_HELICOPTER_DESCENT"
HELICOPTER_CONDITION = "condition:typed.helicopter_descent"
# The printed equipment requirement, matched against the authoritative item record (weapon_family, name and
# tags) of every weapon the fighter actually holds (combat/weapon_delivery.available_weapons, the one
# possession query, which already excludes a dropped, disarmed or stolen weapon). The first five words are
# the printed ones; the rest are the owner catalogue's own names for the pole-weapon kind the line names.
HELICOPTER_GEAR_WORDS = ("polearm", "rope", "chain", "whip", "tether",
                         "spear", "pike", "halberd", "trident", "spade", "guandao", "naginata")


def helicopter_gear(engine: Any, actor: Any) -> list[str]:
    """The names of the polearm, rope, chain, whip or tether items this fighter is actually holding.

    Read from the authoritative item record (weapon_family, name and tags) of every weapon
    combat/weapon_delivery.available_weapons reports as possessed, which already excludes a dropped,
    disarmed or stolen weapon. "Appropriate" is read as the printed words themselves."""
    from factory_authoring.starting_kits import item_definition

    from ..weapon_delivery import available_weapons

    names = []
    for action in available_weapons(engine, actor).values():
        item = item_definition(str(((action.parameters or {}).get("typed") or {}).get("source") or "")) or {}
        described = f"{item.get('weapon_family') or ''} {item.get('name') or ''} {item.get('tags') or ''}".lower()
        if any(word in described for word in HELICOPTER_GEAR_WORDS):
            names.append(str(item.get("name") or action.display_name))
    return names


@hook("turn_end")
def helicopter_descent(engine: Any, actor: Any) -> None:
    """Ending a turn in the air with the printed gear: a safe, upright descent for rounds equal to your Proficiency Bonus."""
    from .. import falling

    row = row_of(engine, actor, "helicopter_descent")
    if row is None or not actor.position.z or falling.supported(engine, actor):
        return
    if not helicopter_gear(engine, actor):
        return  # "while wielding an appropriate polearm, rope, chain, whip, or tether item"
    from ..typed_reactions import can_use_reaction, open_reaction

    if not can_use_reaction(engine, actor, None, row):
        return
    if focus_held(actor) < 1:
        return
    rounds = max(1, int(actor.proficiency_bonus))
    fall_ft = int(row.get("fall_speed_ft") or 60)
    checkpoint = checkpoint_id(engine, "helicopter_descent", actor.entity_id)
    chosen = ask(engine, getattr(engine, "_active_intent", None), checkpoint, actor, CHOICE_PREFIX + "helicopter_descent",
                 ["descend"],
                 labels={"descend": f"Fall no faster than {fall_ft} feet this round, take no falling damage if you land "
                                   f"first, and land on your feet, for {rounds} round{'' if rounds == 1 else 's'}"},
                 allow_decline=True, default="first",
                 prompt=(f"Helicopter Descent: end your turn in the air using your Reaction and one Martial Focus (your "
                         f"ki reserve) to fall no faster than {fall_ft} feet a round, take no falling damage if you land "
                         f"before {rounds} round{'' if rounds == 1 else 's'} have passed, and land on your feet instead "
                         "of falling? You can pass and simply fall."),
                 name="Helicopter Descent", feature_id=HELICOPTER)
    if not chosen:
        return
    engine._spend_resource(actor, FOCUS, 1, HELICOPTER)
    open_reaction(engine, row, actor, (), checkpoint)
    engine._apply_condition(actor, HELICOPTER_CONDITION, HELICOPTER, actor.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + rounds}",
                            data={"label": f"Helicopter Descent: a safe upright fall for {rounds} round"
                                           f"{'' if rounds == 1 else 's'}",
                                  "fall_speed_ft": fall_ft, "fall_damage_immune": 1,
                                  "fall_lands_upright": 1})
    note(engine, HELICOPTER, actor,
         f"{actor.display_name} slows the fall to {fall_ft} feet a round and will land on their feet for {rounds} round"
         f"{'' if rounds == 1 else 's'}.")


# =========================================================================================== Dizzying Tumble
# "When you exit a space adjacent to a hostile creature, spend 10 feet of movement to force that creature to make a
#  Wisdom saving throw. Failed Save: The creature has Disadvantage on attack rolls until the end of your next turn.
#  Successful Save: It becomes immune to your Dizzying Tumble until you complete a short or long rest."
DIZZYING = "TAL_ATHLETICS_DIZZYING_TUMBLE"
DIZZY_IMMUNE = "condition:typed.dizzying_tumble_immune"
DIZZY = "condition:typed.dizzy"


def _dizzy_immune_to(other: Any, mover: Any) -> bool:
    """Whether this creature is immune to *this* tumbler: "immune to your Dizzying Tumble" is per caster,
    so one fighter's successful save does not protect it from another fighter's tumble."""
    return any(condition.condition_id == DIZZY_IMMUNE and str(condition.source_actor_id or "") == mover.entity_id
               for condition in other.conditions.values())


def _leaving_neighbours(engine: Any, mover: Any, previous: Any, nxt: Any) -> list[Any]:
    """The hostile creatures this step walks away from: beside the fighter now, not beside them after it."""
    return [other for other in hostiles(engine, mover)
            if engine.grid.distance_ft(other.position, previous) <= 5
            and engine.grid.distance_ft(other.position, nxt) > 5]


@hook("movement_attempt")
def dizzying_tumble(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """Leaving a space beside a hostile creature costs 10 feet of movement and rolls that creature's Wisdom save.

    The printed trigger names "that creature", so the fighter chooses which of the creatures it is leaving,
    and may decline: both are the player's decision, asked through the public Needle transport. Asking here is
    safe because ext.ControllerPause is a BaseException, so a hook that needs an answer unwinds the intent and
    is replayed from the same checkpoint with the answer in hand, exactly as a leave-reach Opportunity Attack
    asked mid-route is. Nothing is paid until the chosen creature is known and still able to be Dizzy."""
    row = row_of(engine, mover, "dizzying_tumble") if mover is not None else None
    if row is None or mover.entity_id != engine.state.current_actor_id:
        return None
    cost = int(row.get("cost_ft") or 10)
    if mover.movement_remaining_ft < cost or used_this_turn(engine, mover, "dizzying_tumble"):
        return None
    neighbours = [other for other in _leaving_neighbours(engine, mover, previous, nxt) if other.active]
    if not neighbours:
        return None
    labels = {other.entity_id: f"Make {other.display_name} Dizzy (Disadvantage on its attack rolls until the end of "
                              f"your next turn): costs {cost} feet of movement" for other in neighbours}
    picked = ask(engine, intent, checkpoint_id(engine, "dizzying_tumble", mover.entity_id), mover,
                 CHOICE_PREFIX + "dizzying_tumble", [other.entity_id for other in neighbours], labels=labels,
                 preferred=[other.entity_id for other in neighbours][:1], allow_decline=True, default="first",
                 prompt=(f"Dizzying Tumble: you are leaving a space beside "
                         f"{' and '.join(other.display_name for other in neighbours)}. Spend {cost} feet of your "
                         "movement to make one of them roll a Wisdom saving throw, or pass."),
                 name="Dizzying Tumble", feature_id=DIZZYING)
    if not picked:
        return None
    neighbour = engine.state.actors.get(picked[0])
    if neighbour is None or not neighbour.active or neighbour not in neighbours:
        return None  # the creature left the fighter's side, or the answer named something else
    if _dizzy_immune_to(neighbour, mover):
        note(engine, DIZZYING, mover,
             f"{mover.display_name} tumbles away from {neighbour.display_name}, which is already immune to their "
             "Dizzying Tumble; no movement is spent.", (neighbour,))
        return None
    mark_turn_use(engine, mover, "dizzying_tumble")
    mover.movement_remaining_ft -= cost
    engine._append_event("MOVEMENT_GRANTED", DIZZYING, actor_id=mover.entity_id, payload={"distance_ft": -cost})
    dc = int(row.get("numbers", {}).get("save_dc") or 0) or needle.save_dc(engine, mover)
    saved = engine._roll_save(neighbour, "WIS", dc, DIZZYING).total >= dc
    if saved:
        engine._apply_condition(neighbour, DIZZY_IMMUNE, DIZZYING, mover.entity_id, expires_on="UNTIL_REMOVED",
                                data={"against": mover.entity_id, "label": "Immune to Dizzying Tumble until a short or long rest"})
        note(engine, DIZZYING, mover,
             f"{neighbour.display_name} saves against Dizzying Tumble and is immune to it until a short or long rest.",
             (neighbour,))
        return None
    # "until the end of *your* next turn" is the tumbler's turn, not the Dizzy creature's: the expiry name the
    # engine removes for the end of the source's own Nth turn (``END_OF_SOURCE_TURN_AT:N``), the same one
    # Helicopter Descent below uses. END_OF_HOLDER_NEXT_TURN would run the clock from the creature that was
    # tumbled, which is not what the printed line says.
    engine._apply_condition(neighbour, DIZZY, DIZZYING, mover.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(mover.turns_started) + 1}",
                            data={"label": f"Dizzy: Disadvantage on attack rolls (Dizzying Tumble by {mover.display_name})"})
    note(engine, DIZZYING, mover,
         f"{mover.display_name} tumbles away from {neighbour.display_name}, leaving it Dizzy: Disadvantage on its attack rolls "
         "until the end of your next turn.", (neighbour,))
    return None


# ================================================ Meridian-Threading Dash (Coordinated Movement's own Focus)
# "When Coordinated Movement restores Martial Focus, choose one: move 10 feet without provoking Opportunity
#  Attacks; stand from Prone without spending movement; end one ordinary Grappled effect affecting you; or gain
#  Advantage on your next Strength (Athletics) or Dexterity (Acrobatics) check before the end of your next turn."
#
# Coordinated Movement is the sphere's own base ability and its Focus grant is the shared combat/motion.py
# ``regain_focus`` row, which records RESOURCE_GAINED with the source ``passive:<its feature id>`` while the
# Action that triggered it is still resolving. ``action_completed`` then runs after that grant (combat/
# typed_reactions.on_action_completed). The stamp below names the *resolving action* rather than the event
# count at the grant, because anything else that records an event between the two -- Speed Boost's own
# "move an additional 10 feet" grant, for one -- is part of the same Action and must not invalidate it.
# Only the Dash or Disengage Action restores it: ``motion.after_action`` ignores every other action and every
# Bonus Action Dash, and this module never looks at the row itself.
#
# The stamp is bound to the resolution *transaction* as well (independent review AUTO8r1, R1). An actor id and
# an action definition id do not name one execution -- a second Dash on a later turn looks exactly like the
# first -- and this stamp is engine-only, so it outlives the resolution that wrote it. A fighter who ended a
# turn still holding the Focus that Dash had restored matched the old stamp again on the next Dash, in which
# ``motion.after_action`` correctly restores nothing, and was offered the printed choice a second time.
# Comparing the transaction keeps the offer inside the one resolution Coordinated Movement restored Focus for.
#
# A paused resolution is retried from the beginning: the grant is recorded again and re-stamps the same
# transaction id (the engine derives it from the event sequence and the intent id, both restored on rollback),
# so binding costs nothing across the table's pause/answer/reload path and an uninterrupted resolution and a
# reloaded one agree. The stamp is consumed the moment its own resolution claims it. It stays out of fight
# state because it is only ever read inside the resolution that wrote it, so a saved fight has nothing to
# disagree about; the once-per-turn flag that also gates the offer is a string on the actor.
MERIDIAN = "TAL_ATHLETICS_MERIDIAN_THREADING_DASH"
COORDINATED_FOCUS_SOURCE = f"passive:{COORDINATED}"
MERIDIAN_CHECK = "condition:typed.meridian_check"
MERIDIAN_LABEL = "Meridian-Threading Dash"
_RESTORED = "_athletics_focus_restored"
MERIDIAN_OPTIONS = ("step", "stand", "grapple", "check")
MERIDIAN_LABELS = {
    "step": "Move 10 feet without provoking Opportunity Attacks",
    "stand": "Stand up from lying down without spending movement",
    "grapple": "Break free of one grapple that is holding you",
    "check": "Advantage on your next Strength (Athletics) or Dexterity (Acrobatics) check",
}
GRAPPLED = "condition:typed.grappled"


@hook("state_event")
def coordinated_restored_focus(engine: Any, event: Any) -> None:
    """Stamp the sphere's own Coordinated Movement Focus grant against the resolution it happened in.

    ``event.transaction_id`` is the engine's own resolution id, so the stamp names this one execution of this
    one Action rather than an Action type that could recur on a later turn."""
    if event.event_type != "RESOURCE_GAINED" or event.source_definition_id != COORDINATED_FOCUS_SOURCE:
        return
    payload = event.payload or {}
    if payload.get("resource_id") != FOCUS or int(payload.get("gained") or 0) <= 0:
        return
    engine.__dict__[_RESTORED] = {"actor": event.actor_id,
                                  "action": getattr(engine, "_active_action_source_id", None),
                                  "transaction": str(event.transaction_id or "")}


def _focus_restored_now(engine: Any, actor: Any, economy: str, source_definition_id: str) -> bool:
    """Whether this very resolution is the one Coordinated Movement restored Martial Focus for.

    All three parts must agree: the fighter, the Action definition, and the resolution transaction. An empty
    transaction on either side never matches, so a grant recorded outside a resolution cannot be claimed. The
    stamp is consumed on the match, so one grant can only ever be claimed once even inside one resolution."""
    from .. import motion

    if economy != "ACTION" or motion.ACTIONS.get(source_definition_id) is None:
        return False
    mark = engine.__dict__.pop(_RESTORED, None)
    return bool(mark and mark.get("actor") == actor.entity_id
                and mark.get("action") == source_definition_id
                and mark.get("transaction")
                and mark.get("transaction") == str(getattr(engine, "_transaction_id", None) or ""))


@hook("action_completed")
def meridian_threading(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    """Coordinated Movement restored Martial Focus: offer the printed choice of one benefit."""
    row = row_of(engine, actor, "meridian_threading")
    if row is None or used_this_turn(engine, actor, "meridian_threading"):
        return
    if not _focus_restored_now(engine, actor, economy, source_definition_id):
        return
    mark_turn_use(engine, actor, "meridian_threading")
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "meridian_threading", actor.entity_id), actor,
                 CHOICE_PREFIX + "meridian_threading", list(MERIDIAN_OPTIONS),
                 labels=MERIDIAN_LABELS,
                 prompt=("Meridian-Threading Dash: Coordinated Movement has just given you back one Martial Focus "
                         "(your ki reserve). Choose one benefit."),
                 name=MERIDIAN_LABEL, feature_id=MERIDIAN)
    if chosen and chosen[0] == "step":
        feet = int(row.get("step_ft") or 10)
        _grant_step(engine, actor, feet, MERIDIAN)
        # The grant adds movement to spend; it does not move anybody, so the log says the fighter may.
        note(engine, MERIDIAN, actor,
             f"{actor.display_name} may move {feet} more feet this turn without provoking Opportunity Attacks "
             f"({MERIDIAN_LABEL}).")
    elif chosen and chosen[0] == "stand":
        _meridian_stand(engine, actor)
    elif chosen and chosen[0] == "grapple":
        _meridian_grapple(engine, actor)
    elif chosen:
        _meridian_check(engine, actor)


def _meridian_stand(engine: Any, actor: Any) -> None:
    """"stand from Prone without spending movement": combat.posture.stand_up is the one recorded transition.

    The printed benefit is the stand itself, so nothing is left behind afterwards: a second stand still costs
    the movement it normally costs."""
    from .. import posture

    if not posture.stand_up(engine, actor, cost=0, source_id=MERIDIAN):
        return
    note(engine, MERIDIAN, actor, f"{actor.display_name} stands up without spending movement ({MERIDIAN_LABEL}).")


def _meridian_grapple(engine: Any, actor: Any) -> None:
    """"end one ordinary Grappled effect affecting you": one grip, not a pin, and not every hold at once.

    ``_remove_condition`` takes off every instance of a condition id, which would end another grappler's hold
    as well, so exactly the chosen instance is taken off here (the same per-instance transition
    combat/posture.py stand_up uses). With more than one ordinary hold on it, which one is the fighter's to
    name, so it is asked.

    Not reported through combat/ext/hold_escapes.py: that shared seam records escapes, and this creature was
    never escaping -- it simply let the hold go, which its docstring lists as deliberately not reported."""
    holds = [(instance_id, condition) for instance_id, condition in actor.conditions.items()
             if condition.condition_id == GRAPPLED]
    if not holds:
        note(engine, MERIDIAN, actor, f"{actor.display_name} is not grappled, so {MERIDIAN_LABEL} spends nothing.")
        return
    if len(holds) > 1:
        labels = {}
        for instance_id, condition in holds:
            holder = engine.state.actors.get(str(condition.source_actor_id or ""))
            labels[instance_id] = (f"The hold {holder.display_name} has on you" if holder is not None
                                   else "An unnamed hold on you")
        picked = ask(engine, getattr(engine, "_active_intent", None),
                     checkpoint_id(engine, "meridian_grapple", actor.entity_id), actor,
                     CHOICE_PREFIX + "meridian_grapple", [instance_id for instance_id, _ in holds], labels=labels,
                     prompt="Meridian-Threading Dash: which one of the grapples holding you do you end?",
                     name=MERIDIAN_LABEL, feature_id=MERIDIAN)
        chosen = next(((instance_id, condition) for instance_id, condition in holds if instance_id in picked), None)
    else:
        chosen = holds[0]
    if chosen is None:
        return
    instance_id, released = chosen
    # The holder is resolved, never assumed. ``source_actor_id`` is an id string, so a hold recorded against a
    # creature that is no longer in the fight (it left, or the save predates it) has no actor to read; that is the
    # same "unnamed hold" the labels above already describe, so the hold is still ended and only the log's
    # subject goes unnamed. Reading the raw id as if it were a creature raised AttributeError here, which
    # aborted the Action after the condition had already been taken off.
    holder = engine.state.actors.get(str(released.source_actor_id or ""))
    _drop_condition(engine, actor, instance_id, MERIDIAN, label="MERIDIAN")
    note(engine, MERIDIAN, actor,
         f"{actor.display_name} breaks free of the grapple ({MERIDIAN_LABEL}).",
         tuple(creature for creature in (holder,) if creature is not None and creature.active))


def _meridian_check(engine: Any, actor: Any) -> None:
    """"gain Advantage on your next Strength (Athletics) or Dexterity (Acrobatics) check before the end of your next turn"."""
    engine._apply_condition(actor, MERIDIAN_CHECK, MERIDIAN, actor.entity_id, expires_on="END_OF_HOLDER_NEXT_TURN",
                            data={"label": "Advantage on your next Strength (Athletics) or Dexterity (Acrobatics) check"})
    note(engine, MERIDIAN, actor,
         f"{actor.display_name}'s next Strength (Athletics) or Dexterity (Acrobatics) check has Advantage "
         f"until the end of their next turn ({MERIDIAN_LABEL}).")


@hook("ability_check_mode")
def meridian_check_mode(engine: Any, actor: Any, ability: str, skill: Any, against: Any) -> str | None:
    """The printed Strength (Athletics) / Dexterity (Acrobatics) pair, spent by the check that takes it."""
    if str(ability).upper() not in ("STR", "DEX") or str(skill or "") not in ("Athletics", "Acrobatics"):
        return None
    held = [condition for condition in actor.conditions.values() if condition.condition_id == MERIDIAN_CHECK]
    if not held:
        return None
    engine._remove_condition(actor, MERIDIAN_CHECK, MERIDIAN)
    return "ADVANTAGE"


@hook("stand_cost")
def meridian_free_stand(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """No standing entitlement of its own: the printed benefit is the one stand ``_meridian_stand`` makes, so a
    second stand costs the movement it normally costs."""
    return None


# =========================================================================================== Flowing Pursuit
# "When you move at least 20 feet toward one creature during your turn, choose one: ignore Opportunity Attacks from
#  that creature; gain +2 AC against it until the start of your next turn; add 5 feet to one jump during the
#  movement; move through one allied creature's space without treating it as difficult terrain."
#
# The table offers the choice when the movement that closed the distance resolves (``action_completed``, the first
# seam after a move that may safely ask a player), so an Opportunity Attack provoked later in the same turn is
# already covered and the jump bonus covers a jump taken after the choice. The jump option is the printed one and is
# applied to the rest of the turn. "Move through one allied creature's space without treating it as difficult
# terrain" is what this table already does: only hostile spaces are difficult (combat/gate2_engine
# _hostile_difficult_cells), so it needs no row and is not offered as a fourth button.
PURSUIT = "TAL_ATHLETICS_FLOWING_PURSUIT"
PURSUIT_OA = "condition:typed.flowing_pursuit_no_oa"
PURSUIT_JUMP = "condition:typed.flowing_pursuit_jump"
# The +N AC against one named creature is the sphere-independent shape combat/ext/nine_star.py's ``ac_against``
# effect applies and its generic ``hit_response`` reads (data: against, amount), so this module reuses it rather
# than writing a second Armor Class reader.
AC_AGAINST = "condition:typed.ac_against"
PURSUIT_LABELS = {
    "no_oa": "Ignore that creature's Opportunity Attacks for the rest of this turn",
    "ac": "Gain 2 Armor Class against that creature until the start of your next turn",
    "jump": "Add 5 feet to one jump for the rest of this turn",
}


def _turn_legs(engine: Any, actor: Any) -> list[tuple[Any, Any]]:
    """This turn's own willing movement legs as (start, end) squares, oldest first.

    The same recorded-event walk as combat.ext.hold_still.moved_ft, its one implementation: teleports count as the
    ground they cross and forced displacement does not count at all."""
    from ..gate2_runtime_models import Position

    legs: list[tuple[Any, Any]] = []
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED" and event.actor_id == actor.entity_id:
            break
        if event.event_type != "MOVEMENT_COMMITTED" or event.actor_id != actor.entity_id:
            continue
        payload = event.payload or {}
        if payload.get("forced"):
            continue
        path = [Position(**cell) for cell in payload.get("path") or () if isinstance(cell, dict)]
        if len(path) >= 2:
            legs.append((path[0], path[-1]))
    legs.reverse()
    return legs


def _pursuit_target(engine: Any, actor: Any, row: dict[str, Any]) -> Any | None:
    """The first hostile creature this turn's movement closed at least the printed distance toward."""
    legs = _turn_legs(engine, actor)
    if not legs:
        return None
    close_ft = int(row.get("close_ft") or 20)
    origin = legs[0][0]
    return next((other for other in hostiles(engine, actor)
                 if engine.grid.distance_ft(origin, other.position)
                 - engine.grid.distance_ft(actor.position, other.position) >= close_ft), None)


def _offer_pursuit(engine: Any, actor: Any) -> None:
    """"When you move at least 20 feet toward one creature during your turn, choose one" -- once per creature per turn.

    Asked at the two points after a move that may safely put a question to a player (a completed Action and the end
    of the turn, both of which other printed choices already use), so the closing movement itself is never paused."""
    row = row_of(engine, actor, "flowing_pursuit")
    if row is None or actor.entity_id != engine.state.current_actor_id:
        return
    target = _pursuit_target(engine, actor, row)
    if target is None or spent_this_turn(engine, actor, f"flowing_pursuit:{target.entity_id}"):
        return
    mark_turn_use(engine, actor, f"flowing_pursuit:{target.entity_id}")
    chosen = ask(engine, getattr(engine, "_active_intent", None),
                 checkpoint_id(engine, "flowing_pursuit", actor.entity_id, target.entity_id), actor,
                 CHOICE_PREFIX + "flowing_pursuit", ["no_oa", "ac", "jump"],
                 labels=PURSUIT_LABELS,
                 prompt=(f"Flowing Pursuit: you closed at least 20 feet of ground toward {target.display_name} this "
                         "turn. Choose one benefit against that creature."),
                 target_id=target.entity_id, name="Flowing Pursuit", feature_id=PURSUIT)
    if not chosen or chosen[0] not in PURSUIT_LABELS:
        return
    label = PURSUIT_LABELS[chosen[0]]
    if chosen[0] == "no_oa":
        engine._apply_condition(actor, PURSUIT_OA, PURSUIT, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"against": target.entity_id,
                                      "label": f"{target.display_name} cannot make an Opportunity Attack against you this turn"})
    elif chosen[0] == "ac":
        engine._apply_condition(actor, AC_AGAINST, PURSUIT, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN",
                                data={"against": target.entity_id, "amount": int(row.get("ac_bonus") or 2),
                                      "label": f"+{int(row.get('ac_bonus') or 2)} Armor Class against {target.display_name}"})
    else:
        engine._apply_condition(actor, PURSUIT_JUMP, PURSUIT, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                                data={"jump_bonus_ft": 5,
                                      "label": "Your next jump this turn reaches 5 feet higher"})
    note(engine, PURSUIT, actor, f"{actor.display_name}: {label} (Flowing Pursuit).", (target,))


@hook("action_completed")
def flowing_pursuit_after_action(engine: Any, actor: Any, economy: str, source_definition_id: str) -> None:
    _offer_pursuit(engine, actor)


@hook("turn_end")
def flowing_pursuit_at_turn_end(engine: Any, actor: Any) -> None:
    _offer_pursuit(engine, actor)


@hook("opportunity_allowed")
def flowing_pursuit_no_oa(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """"ignore Opportunity Attacks from that creature" for the rest of the turn that earned it."""
    if mover is None or reactor is None:
        return None
    held = [condition for condition in mover.conditions.values() if condition.condition_id == PURSUIT_OA]
    if any(str((condition.data or {}).get("against") or "") == reactor.entity_id for condition in held):
        return False
    return None


@hook("event")
def pursuit_jump_spent(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"add 5 feet to *one* jump": the bonus ends with the jump it was bought for.

    Spent when a jump is actually committed (``MOVEMENT_COMMITTED`` in jump mode), never while a menu is being
    quoted: combat/flight.py asks jump_bonus_ft for every legal jump destination, so a reader that consumed the
    bonus would spend it on the first square the player merely looked at."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    event = engine.events[-1]
    payload = event.payload or {}
    if payload.get("movement_mode") != "jump" or payload.get("forced"):
        return
    mover = engine.state.actors.get(str(kwargs.get("actor_id") or ""))
    if mover is None:
        return
    held = [condition for condition in mover.conditions.values() if condition.condition_id == PURSUIT_JUMP]
    for condition in held:
        _drop_condition(engine, mover, condition.instance_id, PURSUIT, label="JUMP_TAKEN")
    if held:
        note(engine, PURSUIT, mover, f"{mover.display_name}'s Flowing Pursuit jump bonus is used by that jump.")


@hook("jump_bonus_ft")
def athletics_jump_bonus_ft(engine: Any, actor: Any) -> int | None:
    """The module's one jump_bonus_ft reader, shared by both printed sources of flat jump height:
    Polearm Vaulter's Bonus Action increase and Flowing Pursuit's "+5 feet to one jump". A pure read;
    ``pursuit_jump_spent`` is what ends the single-use one when a jump is actually committed."""
    return sum(int((condition.data or {}).get("jump_bonus_ft") or 0)
               for condition in actor.conditions.values()
               if condition.condition_id in (VAULTER_JUMP, PURSUIT_JUMP)) or None


# =========================================================== One Breath, Ten Thousand Steps (Focus per 20 feet)
# "each time you move at least 20 feet, regain Martial Focus" until the end of your turn. The other printed lines
# need nothing here: hostile spaces are already difficult terrain (combat/gate2_engine._hostile_difficult_cells)
# and every owned Motion passive already applies on its own, so there is nothing to lift.
ONE_BREATH = "TAL_ATHLETICS_ONE_BREATH_TEN_THOUSAND_STEPS"
ONE_BREATH_CONDITION = "condition:typed.one_breath_steps"
_ONE_BREATH_FT = "athletics_one_breath_ft"


@hook("technique_used")
def one_breath_steps(ctx: Any) -> None:
    """Start counting this activation's movement: the printed Focus returns every 20 feet from here on."""
    engine, actor = ctx.engine, ctx.actor
    if str(ctx.typed.get("source") or "") != ONE_BREATH:
        return
    actor.turn_flags[_ONE_BREATH_FT] = "0"
    engine._apply_condition(actor, ONE_BREATH_CONDITION, ONE_BREATH, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "One Breath, Ten Thousand Steps: Martial Focus returns every 20 feet you move"})


@hook("movement_step")
def one_breath_focus(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> dict[str, Any] | None:
    """One Martial Focus for each further 20 feet of movement while the activation runs."""
    row = row_of(engine, mover, "one_breath") if mover is not None else None
    if row is None or mover.entity_id != engine.state.current_actor_id:
        return None
    if not any(c.condition_id == ONE_BREATH_CONDITION for c in mover.conditions.values()):
        return None
    every = max(1, int(row.get("focus_ft") or 20))
    walked = int(mover.turn_flags.get(_ONE_BREATH_FT) or 0) + engine.grid.distance_ft(previous, nxt)
    mover.turn_flags[_ONE_BREATH_FT] = str(walked)
    while walked >= every:
        walked -= every
        if focus_held(mover) >= 1:
            continue
        engine._gain_resource(mover, FOCUS, 1, ONE_BREATH)
        note(engine, ONE_BREATH, mover,
             f"{mover.display_name} moves {every} feet and regains Martial Focus (One Breath, Ten Thousand Steps).")
    mover.turn_flags[_ONE_BREATH_FT] = str(walked)
    return None


# =============================================================================================== Polearm Vaulter
# "expend Martial Focus as a Bonus Action to increase: horizontal jump distance by 10 feet; or jump height by 5
#  feet. This increase does not depend on Strength, Dexterity, or remaining movement." The height is the printed
# value this table can measure: a jump rises whole 5-foot steps (combat/flight.py jump_steps) and has no separate
# horizontal-distance value, so the +10 feet of distance stays GM-read.
VAULTER = "TAL_ATHLETICS_POLEARM_VAULTER"
VAULTER_JUMP = "condition:typed.polearm_vaulter_jump"


@hook("compile_actions")
def polearm_vaulter_action(info: dict[str, Any]) -> list[Any] | None:
    """The Bonus Action that buys the printed jump increase; the ordinary movement budget is not charged for it."""
    if VAULTER not in set(info.get("owned_ids") or ()):
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    typed = {"effects": [{"type": "polearm_vaulter_jump", "applies_to": "self",
                          "evidence": "expend Martial Focus as a Bonus Action to increase: horizontal jump distance by "
                                      "10 feet; or jump height by 5 feet"}],
             "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": VAULTER}
    return [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.polearm_vaulter_jump",
                             display_name="Polearm Vaulter: jump 5 feet higher", owner_id=info["actor_id"],
                             economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", costs=((FOCUS, 1),),
                             parameters={"typed": typed, "expected_damage": 0})]


@hook("candidate_allowed")
def polearm_vaulter_offered(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Martial Focus is the whole cost, and the increase lasts for the jump it was bought for."""
    typed = (getattr(action, "parameters", None) or {}).get("typed") or {}
    if typed.get("source") != VAULTER:
        return None
    if any(c.condition_id == VAULTER_JUMP for c in actor.conditions.values()):
        return False
    return None if focus_held(actor) >= 1 else False


@effect("polearm_vaulter_jump")
def polearm_vaulter_jump(ctx: Any, row: dict[str, Any]) -> None:
    """+5 feet of jump height until the end of this turn; it needs no Strength and no movement left to spend."""
    engine, actor = ctx.engine, ctx.actor
    feet = int((row_of(engine, actor, "polearm_vaulter") or {}).get("height_ft") or 5)
    engine._apply_condition(actor, VAULTER_JUMP, VAULTER, actor.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"jump_bonus_ft": feet, "label": f"Your jumps reach {feet} feet higher this turn"})
    note(engine, VAULTER, actor, f"{actor.display_name}'s jumps reach {feet} feet higher for the rest of this turn.")


# ============================================================================================== Mighty Conditioning
# "You may use Dexterity instead of Strength when determining jump distance or height." Jump height is the only
# jump value this table measures, and the better of Strength and Dexterity is the reading the engine already uses
# for the printed "Strength (Athletics) or Dexterity (Acrobatics), your choice" lines (combat/ability_checks
# .escape_bonus, combat/ext/escape_checks.py, combat/ext/tabik_scoundrel.py).
MIGHTY = "TAL_ATHLETICS_MIGHTY_CONDITIONING"


@hook("jump_ability")
def mighty_conditioning_jump(engine: Any, actor: Any) -> str | None:
    """"use Dexterity instead of Strength when determining jump distance or height", when Dexterity is the better score."""
    if not owns(engine, actor, "mighty_conditioning"):
        return None
    from ..ability_checks import ability_modifier

    return "DEX" if ability_modifier(actor, "DEX") > ability_modifier(actor, "STR") else None
