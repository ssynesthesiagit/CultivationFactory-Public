"""Sect Stewardship's shared Merit pools, dice and saved combat roll providers.

`journey_institutions` supplies native persistent learning, current roles, real
institutional petitions, elapsed Duty work, verified rewards and conditional
rest recovery. It uses these same resource IDs, request profiles and printed
Merit arithmetic. Fresh catalogues route non-combat petitions and learning to
that producer; the handlers here keep archived combat catalogues replayable.

Base rules (SECT_STEWARDSHIP_BASE_*)
  * Merit Dice. "Your Merit Die begins as a d4." / "Your maximum number of Merit Dice is equal to your Proficiency
    Bonus, minimum 1." -- two integer pools, so they survive a table commit and reload. The two printed
    preconditions for refilling need facts only the table has: sect_merit_rest supplies explicit owner-confirmed
    journey recovery, including the traveling-away-from-institutions branch. Ordinary rests infer no such facts.
  * Sect Check. "roll: d20 + Proficiency Bonus + Sect Stewardship key ability modifier". "You may spend one Merit Die
    before or after rolling the d20 but before the GM declares the result. Roll the Merit Die and add it to the
    check." / "you cannot add more than one Merit Die to the same d20 roll." Both halves of that window run:
    the paid line is the BEFORE-the-d20 half (the ordinary action menu offers it while the d20 is still hidden) and
    ``after_roll_merit`` is the AFTER-the-d20 half, asked at the engine's own documented ``d20_bonus`` checkpoint,
    which fires after the die is drawn and before any outcome is consumed -- the same seam Sovereign Pack Mind
    asks its grant on. The one-die limit is enforced in both directions: whichever half is taken first, the other
    finds the receipt already on that d20 roll and offers nothing.
  * Learning Sect Stewardship. The creation sheet has no Sect-specific choice producer yet. Three free,
    player-only buttons record the learned Intelligence/Wisdom/Charisma choice once in an integer pool.
    New checks wait for that choice and read its compiled ability modifier, never the general path key.
    Catalogues already frozen in older saves retain their saved expression; no load-time migration is attempted.

Talents that print arithmetic on the die itself (the printed arithmetic is fully resolved; what the fee, the
schedule or the wastage it applies to was is the table's)
  * Communal Rice Bowl: "treat a Merit Die result of 1 as a 3" -- ``one_becomes=3``. Only a 1 is replaced: a 2 stays
    a 2 and stays in the printed "minimum help" band.
  * Medicine Hall Queue: "roll your Merit Die twice and use the higher result" -- ``twice=True``.
  * Contribution Exchange and Department Ledger: "reduce ... by 10 percent per number rolled on the Merit Die, to a
    maximum reduction of 50 percent" -- ``reduction_percent``.

How each runs
  * ``compile_resources`` grants the integer pools a Sect Stewardship fighter holds: the number of unspent Merit
    Dice (maximum = Proficiency Bonus, minimum 1, as printed) and the die's own size in faces (4, with 10 the
    printed maximum), and the recorded learning choice. All are plain integers, so they survive a table commit and reload.
  * ``compile_actions`` adds the Sect Check as an ordinary Action, offered twice: once bare and once costing one
    Merit Die. The printed "before or after rolling the d20" is a decision, and the BEFORE-d20 half of it is the one
    the ordinary action menu can offer: a player picks the paid line or the free one while the d20 is still
    unknown, so the die never reaches a declared result. The AFTER-d20 half runs at the ``d20_bonus`` checkpoint
    (see ``after_roll_merit`` below). Every line is ``player_only``: these are institutional
    requests with no fight-time Difficulty, so the built-in AI never spends a Merit Die on one (the fight's AI
    controller filters player_only actions out of its context, combat/gate4_context.py).
  * The die is paid by the action's own ``costs`` (the engine spends an action's costs before its effects run,
    combat/gate2_engine.py:1816), so no effect in this module ever pays a second time, and an action the character
    cannot afford is simply not offered.

Which requests a petition button offers
  A printed talent's rider applies to *what is requested*, not to which button is pressed: Communal Rice Bowl prints
  "When you Petition the Hall for food, lodging, work clothes, common tools, a bath, or safe storage ... treat a Merit
  Die result of 1 as a 3", so an owner who asks the ordinary-help button for a meal, a bed or work clothes must still
  read a 1 as a 3. Each printed request therefore declares the *kinds* of benefit it buys, each talent lists the kinds
  it names, and ``petition_groups`` routes the requests a talent names onto the button that carries that talent's
  rider. A covered request is never offered on a button without the printed change to the die, and every printed
  request is still offered exactly once: where a talent's list is finer than the base rule's wording for the same kind
  ("a meal and safe sleeping space"), the talent's own list is the one its button prints.

Judgment calls (the printed text leaves them to the table or names no number)
  * The Sect Check's Difficulty is whatever the calling talent or the table sets; the engine rolls and records the
    check with its total and does not invent a DC, because a DC here is the table's to name (Dormitory Network
    prints its own 12/15/18 ladder for its rumors).
  * Spending the die AFTER the d20 is rolled but before the result is declared runs at the engine's documented
    ``d20_bonus`` checkpoint, which fires between the draw and the outcome, so the die lands inside the printed
    window without a new seam. It was previously recorded here as a missing engine seam; it is not one.
  * A Merit Die can be spent only on Sect Stewardship features ("You can spend Merit Dice only on Sect Stewardship
    features unless another rule says otherwise"), so every action that costs one is declared by this module.
  * "Found a Branch Hall" ("While present in the branch and acting according to its purpose, your Merit Die
    increases by one step, to a maximum of d10") needs a branch hall to be present in and a purpose to be acting
    according to. No fight state carries either, so the die stays a d4 until a supported, persistent mechanism
    supplies that context; the size pool exists so such a mechanism can raise it without changing the shape.

Determinism: evented engine methods only; the die goes through the engine's roller and is recorded.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from . import effect, hook, note

SPHERE = "sect_stewardship"
SPHERE_RECORD = "tianxia.sphere." + SPHERE
BASE = "SECT_STEWARDSHIP_BASE_"
MERIT_CHECK = BASE + "SECT_CHECK"
PETITION = BASE + "PETITIONING_THE_HALL"

T = "tianxia.talent.sect_stewardship."
RICE_BOWL = "TAL_SECT_STEWARDSHIP_COMMUNAL_RICE_BOWL"
MEDICINE_QUEUE = "TAL_SECT_STEWARDSHIP_MEDICINE_HALL_QUEUE"
CONTRIBUTION = "TAL_SECT_STEWARDSHIP_CONTRIBUTION_EXCHANGE"
DEPARTMENT = "TAL_SECT_STEWARDSHIP_DEPARTMENT_LEDGER"

MERIT = "resource:sect_stewardship.merit_dice"
MERIT_SIZE = "resource:sect_stewardship.merit_die_size"
SECT_KEY = "resource:uses.sect_stewardship_key_ability"
# The existing internal-counter namespace keeps this encoded choice out of player resource bars.
# Zero means not recorded; the learning choice remains fixed for this fight.
SECT_ABILITIES = (("INT", "Intelligence"), ("WIS", "Wisdom"), ("CHA", "Charisma"))

BASE_DIE = 4
LARGEST_DIE = 10  # "your Merit Die increases by one step, to a maximum of d10"

# The base rule's five Standing grades, as one clause the button and log can use wherever the word "Standing" appears
# without explanation (checklist 13). The grades are No Standing, Servant, Outer, Inner and Core; a reader only needs
# to know that Standing is local recognition, not a rank or a cultivation level.
STANDING_NOTE = ("how much that institution recognizes you, from a stranger there, to a worker who does basic labor, "
                 "to someone trusted with ordinary duties, to someone trusted with restricted duties, to a holder of "
                 "the hall's own authority")

# ------------------------------------------------------------------ the printed requests a petition can be for
# Each request names what it buys, in ``kinds``. A printed talent then lists the kinds its own rider covers ("food,
# lodging, work clothes, common tools, a bath, or safe storage"), so which requests it answers is decided by the
# printed list rather than by searching the request's wording: a request a talent names is gathered onto the button
# that carries that talent's rider, and is never offered on a button that does not.
@dataclass(frozen=True)
class PetitionRequest:
    """One printed request the Hall can be petitioned for, and the kinds of benefit it buys."""

    kinds: tuple[str, ...]
    text: str


# "Common petitions include:", the base rule's own list, in the printed order. "Use of a common room, kitchen,
# stable, outer library desk or messenger channel" is access to a shared facility and is deliberately not the "food"
# kind: Communal Rice Bowl names a meal, not the use of a kitchen, so an owner still asks for the kitchen on the
# ordinary line, where no replacement is printed.
BASE_REQUESTS: tuple[PetitionRequest, ...] = (
    PetitionRequest(("food", "lodging"), "a meal and safe sleeping space"),
    PetitionRequest(("work_clothes",), "a clean set of robes or work clothes"),
    PetitionRequest(("common_tools",), "mundane tools for a duty"),
    PetitionRequest(("public_hall_entry",), "permission to enter a public hall"),
    PetitionRequest(("grounds_map",), "a basic map of the sect grounds"),
    PetitionRequest(("introduction",), "an introduction to a clerk, senior, farmer, guard or apprentice"),
    PetitionRequest(("public_notices",), "access to public notices"),
    PetitionRequest(("shared_facilities",),
                    "use of a common room, kitchen, stable, outer library desk or messenger channel"),
    PetitionRequest(("storage",), "temporary storage for ordinary goods"),
    PetitionRequest(("witness",), "a written receipt or witness statement"))

# Communal Rice Bowl's own printed list: "food, lodging, work clothes, common tools, a bath, or safe storage for
# ordinary possessions". Where the base rule's wording is coarser for a kind this talent names ("a meal and safe
# sleeping space"), the talent's own list is what the button prints, so every request is offered exactly once.
RICE_BOWL_REQUESTS: tuple[PetitionRequest, ...] = (
    PetitionRequest(("food",), "a meal"),
    PetitionRequest(("lodging",), "a bed"),
    PetitionRequest(("work_clothes",), "work clothes"),
    PetitionRequest(("common_tools",), "common tools for a duty"),
    PetitionRequest(("bath",), "a bath"),
    PetitionRequest(("storage",), "a safe place to store your ordinary possessions"))

# Medicine Hall Queue's own printed list: "ordinary medical treatment, antidotes, bandages, supervised recovery, or a
# Medicine Hall appointment".
MEDICAL_REQUESTS: tuple[PetitionRequest, ...] = (
    PetitionRequest(("treatment",), "ordinary treatment"),
    PetitionRequest(("antidotes",), "antidotes"),
    PetitionRequest(("bandages",), "bandages"),
    PetitionRequest(("recovery",), "supervised recovery"),
    PetitionRequest(("appointment",), "a Medicine Hall appointment"))

# The base rule's bands, as the log prints them: "On a 1-2 / On a 3-4 / On a 5 or higher". Communal Rice Bowl
# replaces only a 1, so a 2 stays in the first band.
PETITION_BANDS: tuple[tuple[int, str], ...] = (
    (2, "the minimum help your Standing allows"),
    (4, "useful help without extra trouble"),
    (LARGEST_DIE, "unusually timely, discreet, generous or well-matched help"))

# The printed lines the table, not the engine, still applies. They ride the action they belong to, which is what
# marks the ability "partly automated" on the sheet and what keeps the authority row at CORE_WITH_RIDERS.
PETITION_RIDERS = ("Petitioning cannot obtain rare treasures, secret manuals, combat allies, high-ranking "
                   "interventions, expensive materials, forbidden access, or anything the institution would not "
                   "plausibly grant. Use a non-combat Action during a scene, or petition during downtime. "
                   "The GM confirms that the authority is appropriate, what support it can plausibly provide, "
                   "and your Standing there. This roll does not grant goods, access, introductions, or information "
                   "automatically; the GM supplies the actual support.")
# The printed "before or after" window is automated on both sides, so the rider no longer names it as a gap; what
# genuinely stays with the table is the Difficulty and the meaning of the result, which the base rule never names.
SECT_CHECK_RIDERS = ("The engine rolls the check and adds at most one Merit Die, spent either before the d20 (the "
                     "paid Sect Check) or after it but before the result is declared (asked once the d20 is "
                     "visible). The table sets what the check is for, its Difficulty, and what the result means.")
MEDICINE_RIDERS = ("In addition, during downtime you may spend one Merit Die to reduce by half the wait time for one "
                   "ordinary treatment, if the institution has capacity.")
RICE_BOWL_RIDERS = ("If an ally lacks Standing but travels under your responsibility, you may include that ally in "
                    "your petition if the request is ordinary and non-sensitive.")


@dataclass(frozen=True)
class PetitionRider:
    """A printed talent's change to the petition's Merit Die, and the requests it prints for it.

    ``kinds`` is read off ``requests``, so what the talent names is the kinds its own request list buys and there is
    only that one list to keep true. ``topic`` is the printed group those requests are called (the talent's own
    printed header) and ``short`` the subject the button and the log use for them.
    """

    feature_id: str
    name: str  # the talent's printed name, so the button and the log can say which printed rule does this
    topic: str  # the printed group name, and the compiled action id's own word
    short: str  # what the group buys, in the button's and the log's words
    requests: tuple[PetitionRequest, ...]
    one_becomes: int | None = None  # "treat a Merit Die result of 1 as a 3"
    twice: bool = False  # "roll your Merit Die twice and use the higher result"
    rider_text: str = ""  # the printed line the table still applies

    @property
    def kinds(self) -> frozenset[str]:
        """The kinds of benefit this talent's printed list covers, which is what routes the request to its button."""
        return frozenset(kind for request in self.requests for kind in request.kinds)


# Every printed talent whose rider changes the petition's Merit Die. A request any of these covers is routed to the
# button this talent's rider rides, so "treat a 1 as a 3" reaches a petition for food, lodging or work clothes
# whichever button the player pressed: the printed talent applies by requested benefit, not by button name.
PETITION_TALENTS: tuple[PetitionRider, ...] = (
    PetitionRider(RICE_BOWL, "Communal Rice Bowl", "household",
                  "food, lodging, work clothes, tools, a bath or storage",
                  RICE_BOWL_REQUESTS, one_becomes=3, rider_text=RICE_BOWL_RIDERS),
    PetitionRider(MEDICINE_QUEUE, "Medicine Hall Queue", "medical", "medical help",
                  MEDICAL_REQUESTS, twice=True, rider_text=MEDICINE_RIDERS),
)
ORDINARY_TOPIC = "ordinary"
ORDINARY_SHORT = "ordinary help"

# The post-d20 ask's choice id, so the table sees one named prompt and the AI-step probe can answer it by name.
SECT_CHECK_AFTER = "choice:needle.sect_stewardship.add_merit_die"

# The roll reason this module gives its own Sect Check d20, and the paid line's own action id suffix. These name the
# check exactly, so the after-d20 ask can recognise its own roll and tell the paid line apart from the bare one.
SECT_CHECK_REASON = "SECT_CHECK:"
PAID_SUFFIX = ".sect_check.paid"


@dataclass(frozen=True)
class PetitionGroup:
    """One printed petition button: the requests that the printed rules answer the same way.

    Every request on one button carries the same riders, so a button never mixes a request a talent names (which
    gets that talent's printed change to the die) with one it does not.
    """

    topic: str
    requests: tuple[PetitionRequest, ...]
    riders: tuple[PetitionRider, ...] = ()
    short: str = ORDINARY_SHORT

    @property
    def label(self) -> str:
        return f"Petition the Hall for {self.short}"

    @property
    def texts(self) -> tuple[str, ...]:
        """The printed requests, as the button text and the event carry them."""
        return tuple(request.text for request in self.requests)

    @property
    def talent_names(self) -> tuple[str, ...]:
        return tuple(rider.name for rider in self.riders)

    @property
    def one_becomes(self) -> int | None:
        return next((rider.one_becomes for rider in self.riders if rider.one_becomes), None)

    @property
    def twice(self) -> bool:
        return any(rider.twice for rider in self.riders)

@dataclass(frozen=True)
class ReductionChoice:
    """One printed button of a reduction talent: what the percentage cuts, and the label that names it."""

    short: str  # the action id's own word, so two buttons of one talent never collide
    label: str  # the button text, which names the benefit it applies to
    cuts: str  # what the percentage is applied to, as the log prints it
    purpose: str  # what the player is asking for, so the button says who and what it affects


# The rows whose printed result is the same Merit Die percentage arithmetic over something else. Department Ledger
# prints "choose one", and two of its five options are that same percentage over different things (the project's
# time, its wastage), so they are two buttons: each names the benefit it applies to, and the log repeats it, instead
# of one button that leaves the table to guess which of the two was chosen.
REDUCTION_ROWS: dict[str, tuple[str, tuple[ReductionChoice, ...]]] = {
    CONTRIBUTION: ("Contribution Exchange", (
        ReductionChoice("cost", "Reduce the gold cost of an ordinary exchange",
                        "the gold cost of that exchange",
                        "Ask a hall you have Standing in for a recipe fragment, supervised use of a workshop, a map, "
                        "common supplies, harvesting permissions, travel papers, a letter of introduction, a "
                        "discount, or the loan of a common tool."),
    )),
    DEPARTMENT: ("Department Ledger", (
        ReductionChoice("time", "Cut a hall project's time (Department Ledger)",
                        "the time the project takes",
                        "You supervise a hall project for at least a day; this cuts how long the project takes."),
        ReductionChoice("waste", "Cut a hall project's wastage (Department Ledger)",
                        "ordinary wastage, spoilage or loss",
                        "You supervise a hall project for at least a day; this cuts what the project wastes or "
                        "spoils."),
    )),
}


# -------------------------------------------------------------------------------------------------- shared helpers
def is_steward(info: dict[str, Any]) -> bool:
    """Whether this character printed the Sect Stewardship sphere or one of its own records.

    A fighter with neither holds no Merit Dice: the plug-in is inert for every other character (checklist 3). The
    sphere is recognised by its catalog record id (``tianxia.sphere.sect_stewardship``) or by any of its own base
    rules and talents, so a character built from the sphere's records alone is still recognised.
    """
    spheres = {str(name) for name in info.get("spheres") or []}
    if SPHERE_RECORD in spheres or SPHERE in spheres:
        return True
    ids = [str(key) for key in info.get("owned_ids") or []]
    return any(key.startswith(BASE) or key.startswith(T) or key.startswith("TAL_SECT_STEWARDSHIP") for key in ids)


def merit_die_size(engine: Any, actor: Any) -> int:
    """The actor's Merit Die size in faces: 4 to start, never past the printed maximum of 10.

    The size is a plain integer pool, so a mechanism that can actually supply "present in the branch, acting
    according to its purpose" (``Found a Branch Hall``) raises it by writing that pool; until one exists the die
    stays the printed d4 rather than being widened by owning the talent alone.
    """
    held = actor.resources.get(MERIT_SIZE)
    return max(BASE_DIE, min(LARGEST_DIE, int(held if held else BASE_DIE)))


def merit_maximum(info: dict[str, Any]) -> int:
    """"Your maximum number of Merit Dice is equal to your Proficiency Bonus, minimum 1." """
    pb = info.get("pb")
    return max(1, int(2 if pb is None else pb))


def held_merit(engine: Any, actor: Any) -> int:
    return max(0, int(actor.resources.get(MERIT) or 0))


def roll_merit_die(engine: Any, actor: Any, source: str, *, twice: bool = False,
                   one_becomes: int | None = None) -> int:
    """One Merit Die, rolled through the engine's roller and recorded. Integers only, so it reloads.

    ``twice`` is Medicine Hall Queue's printed "roll your Merit Die twice and use the higher result"; ``one_becomes``
    is Communal Rice Bowl's printed "treat a Merit Die result of 1 as a 3", applied per die. Only the printed 1 is
    replaced: a 2 is still a 2. Both are the die's own arithmetic, taken here so no row reimplements it.
    """
    from ..gate2_runtime_models import DiceSpec

    sides = merit_die_size(engine, actor)
    spec = DiceSpec(count=2 if twice else 1, sides=sides, modifier=0)
    roll = engine.roller.roll(spec, actor_id=actor.entity_id, reason=f"MERIT_DIE:{source}")
    engine._record_roll(roll)
    return merit_result(roll.dice, one_becomes=one_becomes)


def merit_result(dice, *, one_becomes=None):
    """Shared printed Merit Die arithmetic for combat and Journey consumers."""
    return max(int(one_becomes) if one_becomes is not None and int(die)==1 else int(die) for die in dice)


def reduction_percent(number: int, *, per: int = 10, cap: int = 50) -> int:
    """"reduce the cost by 10 percent per number rolled on the Merit Die, to a maximum reduction of 50 percent".

    Shared by Contribution Exchange (a gold cost) and Department Ledger (a project's time or wastage), which print
    the same arithmetic over different things. Returns the percentage to subtract, never more than the printed cap.
    """
    return max(0, min(cap, per * max(0, int(number))))


def petition_band(number: int) -> str:
    """The base rule's printed band for one Merit Die: "On a 1-2 / On a 3-4 / On a 5 or higher"."""
    for top, band in PETITION_BANDS:
        if number <= top:
            return band
    return PETITION_BANDS[-1][1]


def petition_bands_sentence() -> str:
    """The printed bands as the one sentence a button offers: "on a 1-2 ..., on a 3-4 ..., on a 5 or higher ...".

    Built from ``PETITION_BANDS``, so the button text, the log and ``petition_band`` can never drift apart. The last
    band is open ended, as printed ("On a 5 or higher, if your Merit Die is large enough to roll that result"), so it
    reads as the bottom of the band only.
    """
    low = 1
    parts = []
    for position, (top, band) in enumerate(PETITION_BANDS):
        if position == len(PETITION_BANDS) - 1:
            parts.append(f"on a {low} or higher {band}")
        else:
            parts.append(f"on a {low}-{top} {band}")
        low = top + 1
    return "; ".join(parts)


# ---------------------------------------------------------------------------------------------------------------- compile
@hook("compile_resources")
def resources(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ResourceDefinition

    if not is_steward(info):
        return None
    most = merit_maximum(info)
    return [ResourceDefinition(resource_id=MERIT, initial=most, maximum=most),
            ResourceDefinition(resource_id=MERIT_SIZE, initial=BASE_DIE, maximum=LARGEST_DIE),
            ResourceDefinition(resource_id=SECT_KEY, initial=0, maximum=len(SECT_ABILITIES))]


def sect_key_actions(info: dict[str, Any]) -> list[Any]:
    """Record the printed learning choice through existing setting-only actions; no combat cost."""
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.sect_key.{ability.lower()}",
        display_name=f"Sect Stewardship: choose {label}", owner_id=info["actor_id"],
        economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"setting_only": True, "player_only": True, "sect_key_choice": value,
                    "setting_lifetime": "You can record this choice only once per fight; it lasts for this fight "
                                        "and cannot be changed here.",
                    "setting_description": "Record your existing Sect Stewardship learning choice for this fight. "
                                           "This does not change your character sheet.",
                    "description": f"Record {label} as the ability you chose when learning Sect Stewardship. "
                                   "Sect Checks use that ability's modifier. This choice lasts for this fight; "
                                   "it costs no action or Merit Dice and cannot be changed here.",
                    "typed": {"effects": [{"type": "sect_key_choice", "value": value}],
                              "numbers": {}, "duration": {"kind": "instant"}, "riders": []}})
            for value, (ability, label) in enumerate(SECT_ABILITIES, 1)]


@hook("candidate_allowed")
def sect_choice_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """New owned checks require a recorded learning choice; unrelated and old actions are inert."""
    parameters = getattr(action, "parameters", None) or {}
    if "sect_key_choice" in parameters:
        return SECT_KEY in actor.resources and actor.resources[SECT_KEY] == 0
    if parameters.get("sect_key_required"):
        return 1 <= int(actor.resources.get(SECT_KEY, 0)) <= len(SECT_ABILITIES)
    return None


@effect("sect_key_choice")
def choose_sect_key(ctx: Any, eff: dict[str, Any]) -> None:
    """Store only the printed three-way choice, once, in persisted integer state."""
    value = int(eff.get("value") or 0)
    if SECT_KEY not in ctx.actor.resources or ctx.actor.resources[SECT_KEY] != 0 or not 1 <= value <= len(SECT_ABILITIES):
        return
    ctx.actor.resources[SECT_KEY] = value
    label = SECT_ABILITIES[value - 1][1]
    note(ctx.engine, ctx.source, ctx.actor,
         f"Sect Stewardship: {label} is recorded as your chosen ability for Sect Checks. No action or Merit Dice spent.")


def _sect_check_action(info: dict[str, Any], paid: bool) -> Any:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    numbers = dict(info["numbers"])
    numbers["ability_mods"] = {ability: int(info["mods"][ability]) for ability, _ in SECT_ABILITIES}
    label = "Sect Check (spend 1 Merit Die)" if paid else "Sect Check"
    description = ("Roll a Sect Check: d20 + Proficiency Bonus + your Sect Stewardship key ability modifier. Spend one "
                   "Merit Die to add its roll to the check; only one Merit Die may be added to any one check."
                   if paid else
                   "Roll a Sect Check: d20 + Proficiency Bonus + your Sect Stewardship key ability modifier. Once the "
                   "d20 is rolled but before any result is decided, you are asked whether to spend one Merit Die and "
                   "add its roll to this check; only one Merit Die may be added to any one check.")
    if not paid:
        description += " The table decides what the check is for and whether the result succeeds."
    typed = {"effects": [{"type": "sect_check", "paid": paid,
                          "evidence": "Sect Check: d20 + Proficiency Bonus + Sect Stewardship key ability modifier"}],
             "numbers": numbers, "duration": {"kind": "instant"}, "riders": [SECT_CHECK_RIDERS],
             "source": MERIT_CHECK, "sphere": SPHERE, "typing_status": "sect_stewardship_plugin",
             "coverage": "CORE_WITH_RIDERS"}
    costs = ((MERIT, 1),) if paid else ()
    return ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.sect_check{'.paid' if paid else ''}",
        display_name=label, owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED",
        target_kind="SELF", costs=costs,
        parameters={"typed": typed, "expected_damage": 0, "player_only": True, "description": description,
                    "sect_key_required": True})


def petition_groups(owned_ids: frozenset[str]) -> tuple[PetitionGroup, ...]:
    """The petition buttons this character prints, one per printed group of requests.

    A printed talent's rider applies to *what is requested*, not to which button is pressed: "When you Petition the
    Hall for food, lodging, work clothes, common tools, a bath, or safe storage ... treat a Merit Die result of 1 as a
    3". So the requests a talent names are gathered onto the button that carries its rider, and the base rule's
    remaining requests stay on the ordinary button. Two consequences the printed rules ask for:

      * a covered request (food, lodging, work clothes, common tools, a bath, safe storage, ...) is never offered on a
        button without the printed change to the die, so an owner can no longer spend the die on a 1 for the
        "minimum help" band on a request that should have read as a 3;
      * every request the printed rules grant is still offered exactly once. Where a talent's own list is finer than
        the base rule's wording for the same kind ("a meal and safe sleeping space"), the talent's list is the one its
        button prints, because that list is what the printed talent names.

    A character who owns no such talent gets the base rule's whole list on the single ordinary button, exactly as
    printed.
    """
    covered: set[str] = set()
    groups: list[PetitionGroup] = []
    for rider in PETITION_TALENTS:
        if rider.feature_id not in owned_ids:
            continue
        covered |= rider.kinds
        groups.append(PetitionGroup(rider.topic, rider.requests, (rider,), rider.short))
    remaining = tuple(request for request in BASE_REQUESTS if not covered.intersection(request.kinds))
    if remaining or not groups:
        groups.insert(0, PetitionGroup(ORDINARY_TOPIC, remaining or BASE_REQUESTS))
    return tuple(groups)


def _list(requests: tuple[str, ...]) -> str:
    """The printed requests as one readable sentence."""
    if len(requests) == 1:
        return requests[0]
    return ", ".join(requests[:-1]) + " or " + requests[-1]


def _petition_action(info: dict[str, Any], group: PetitionGroup) -> Any:
    """Petitioning the Hall, once per printed group of requests that the printed rules answer the same way.

    The printed base action is one roll paid with one Merit Die, so it is offered as a single Action whose cost is
    that die. Which requests a button offers is settled by ``petition_groups`` from the ids this character printed:
    each talent's rider rides the button carrying the requests it names, and the owner picks the group that matches
    what they are asking for (checklist 9: a player-owned decision, asked on their turn).

    The riders are decided here, at compile time, and carried on the effect, so resolution reads only its own effect
    and needs no ownership query mid-fight.
    """
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    description = ("As a non-combat Action during a scene, or during downtime, ask an appropriate hall, superior, "
                   "clerk, family, steward or local authority for " + _list(group.texts) + ". "
                   "You spend 1 Merit Die and roll it: " + petition_bands_sentence() + ". Here your Standing is "
                   f"{STANDING_NOTE}.")
    effect_body: dict[str, Any] = {"type": "petition_the_hall", "topic": group.topic, "subject": group.short,
                                   "requests": list(group.texts), "talents": list(group.talent_names),
                                   "evidence": "Petitioning the Hall: spend one Merit Die and roll it"}
    riders = [PETITION_RIDERS]
    for rider in group.riders:
        riders.append(rider.rider_text)
        if rider.one_becomes is not None:
            effect_body["one_becomes"] = rider.one_becomes
            description += f" A roll of 1 counts as a {rider.one_becomes} ({rider.name})."
        if rider.twice:
            effect_body["twice"] = True
            description += f" Roll the Merit Die twice and use the higher result ({rider.name})."
    typed = {"effects": [effect_body],
             "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": riders, "source": PETITION,
             "sphere": SPHERE, "typing_status": "sect_stewardship_plugin", "coverage": "CORE_WITH_RIDERS"}
    return ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.petition.{group.topic}", display_name=group.label,
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
        costs=((MERIT, 1),),
        parameters={"typed": typed, "expected_damage": 0, "player_only": True, "description": description})


@hook("compile_actions")
def actions(info: dict[str, Any]) -> list[Any] | None:
    """The Sect Check as an ordinary Action (bare and paid), one Petition per printed group of requests, and one
    reduction button per thing a Merit Die percentage can cut.

    The printed "spend one Merit Die before or after rolling the d20 but before the GM declares the result" is a
    decision the player makes before the result is known. Both halves of that window are automated: the before-d20
    half is this menu (the player picks the paid line or the free one while the d20 is still hidden), and the
    after-d20 half is ``after_roll_merit`` at the engine's ``d20_bonus`` checkpoint.
    """
    if not is_steward(info):
        return None
    owned_ids = frozenset(str(key) for key in info.get("owned_ids") or [])
    out = [*sect_key_actions(info), _sect_check_action(info, paid=False), _sect_check_action(info, paid=True)]
    for group in petition_groups(owned_ids):
        out.append(_petition_action(info, group))
    for feature_id in (CONTRIBUTION, DEPARTMENT):
        if feature_id in owned_ids:
            out.extend(_reduce_actions(info, feature_id))
    return out


def _reduce_actions(info: dict[str, Any], feature_id: str) -> list[Any]:
    """A row whose printed result is the Merit Die's percentage: Contribution Exchange or Department Ledger.

    Each of its buttons spends one Merit Die (as the action's own cost) and cuts the thing its label names "by 10
    percent per number rolled on the Merit Die, to a maximum reduction of 50 percent". The engine pays, rolls and
    reports the percentage and names what it cuts; what the fee, the schedule or the wastage actually was is the
    table's, so nothing here invents a gold total or a duration.
    """
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    talent_name, buttons = REDUCTION_ROWS[feature_id]
    out = []
    for choice in buttons:
        typed = {"effects": [{"type": "merit_reduce", "source_row": feature_id, "talent": talent_name,
                              "cuts": choice.cuts, "short": choice.short,
                              "evidence": "reduce by 10 percent per number rolled on the Merit Die, maximum 50 percent"}],
                 "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [],
                 "source": feature_id, "sphere": SPHERE, "typing_status": "sect_stewardship_plugin",
                 "coverage": "CORE_WITH_RIDERS"}
        description = (f"{choice.label}. {choice.purpose} You spend 1 Merit Die and roll it; each number rolled cuts "
                       f"{choice.cuts} by 10%, to a maximum cut of 50%.")
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{choice.short}.reduce", display_name=choice.label,
            owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="SELF",
            costs=((MERIT, 1),),
            parameters={"typed": typed, "expected_damage": 0, "player_only": True, "description": description}))
    return out


# ---------------------------------------------------------------------------------------------------------------- effects
@effect("sect_check")
def sect_check(ctx: Any, eff: dict[str, Any]) -> None:
    """"d20 + Proficiency Bonus + Sect Stewardship key ability modifier", plus at most one Merit Die.

    The paid line's die was already taken by the action's cost; this adds its roll to the d20 and reports the total.
    The free line rolls no die and instead gets the after-d20 offer from ``after_roll_merit``, which asks at the
    engine's ``d20_bonus`` checkpoint. Either way exactly one die may reach a check, which is what the printed rule
    asks, and the die is added before any result is declared either way.
    """
    engine, actor = ctx.engine, ctx.actor
    source = ctx.source
    numbers = dict(ctx.typed.get("numbers") or {})
    pb = int(numbers.get("pb") or 2)
    if "ability_mods" not in numbers:
        # A pre-r1 immutable action has only its original compiled expression. Preserve its replay;
        # newly compiled checks always carry ability_mods and cannot enter this compatibility branch.
        key_mod = int(numbers.get("key_mod") or 0)
        label = "key ability"
    else:
        choice = int(actor.resources.get(SECT_KEY, 0))
        if not 1 <= choice <= len(SECT_ABILITIES):
            ctx.rider("Sect Check is not rolled: record the Intelligence, Wisdom, or Charisma choice you made "
                      "when learning Sect Stewardship before using this check.")
            return
        ability, label = SECT_ABILITIES[choice - 1]
        key_mod = int(numbers["ability_mods"][ability])
    added = roll_merit_die(engine, actor, source) if eff.get("paid") else 0
    modifier = pb + key_mod + added
    roll = engine.roller.d20(modifier=modifier, actor_id=actor.entity_id,
                             reason=SECT_CHECK_REASON + source, mode="NORMAL")
    engine._record_roll(roll)
    # Whatever reached the check, from either half of the printed window: the paid line put its die in the modifier
    # before the draw, and the after-d20 offer lands on the same roll at the d20_bonus checkpoint. The receipt is the
    # roll's own modifier, so the history entry and the note below cannot disagree with the printed total.
    reaching = int(roll.modifier) - pb - key_mod
    engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": None, "success": None,
                                  "check": "Sect Check", "merit_die": reaching,
                                  "merit_die_size": merit_die_size(engine, actor),
                                  "merit_dice_left": held_merit(engine, actor)})
    when = "before" if added else "after"
    spent = f" + {reaching} Merit Die ({when} the d20)" if reaching else ""
    note(engine, source, actor,
         f"Sect Check: {roll.total} (d20 {roll.natural_result} + {pb} proficiency + {key_mod} {label}{spent}). "
         f"The table decides what it is for.")


# ------------------------------------------------------------------------------------------- after the d20
@hook("d20_bonus")
def after_roll_merit(engine: Any, roll: Any, intent: Any) -> dict[str, Any] | None:
    """"You may spend one Merit Die ... **after** rolling the d20 but before the GM declares the result."

    The other half of the same printed sentence is the paid Sect Check, which the menu offers before the d20 exists.
    This is the half a menu cannot offer, because the decision only exists once the d20 has been drawn and before
    anything has been decided from it. It runs on the engine's own documented ``d20_bonus`` checkpoint, which every
    d20 passes between the draw and the outcome (combat/roll_checkpoints.py: ``rewrite_d20`` runs ``d20_bonus``
    subscribers after rewrites and before any caller consumes the result), so the die genuinely lands inside the
    window the text names. No engine change and no private state: this is the same seam, and the same kind of ask,
    that Sovereign Pack Mind uses to grant its bonus after a die (combat/ext/beastmastery_pack.py).

    Scope. Only this module's own Sect Check d20 qualifies, identified by the ``SECT_CHECK:`` roll reason it writes,
    so no other creature's attack or save is ever touched, and only the roller is ever asked, so a character without
    the sphere is never prompted (checklist 3).

    The one-die limit. "you cannot add more than one Merit Die to the same d20 roll." The reason carries the action
    id that produced the roll, so the paid line is recognisable directly: a roll from the paid action already has its
    die on it, and this asks nothing further. That keeps the limit true without any receipt kept outside the engine --
    no module-level set, no saved field, nothing that a preview could leave behind or a reload could restore stale.
    The printed escape ("unless a talent says otherwise") belongs to the talents that print it, not to this base rule.

    The player is asked; an AI owner decides for itself (checklist 9), and it decides from its own information: it
    declines, because the printed Sect Check carries no Difficulty, so nothing in the fight tells it whether the die
    would help. Spending happens only on acceptance, and only out of a pool that actually holds a die.
    """
    reason = str(roll.reason or "")
    if not reason.startswith(SECT_CHECK_REASON):
        return None
    source = reason[len(SECT_CHECK_REASON):]
    if source.endswith(PAID_SUFFIX):
        return None  # the BEFORE-d20 half already put its die on this roll
    actor = engine.state.actors.get(str(roll.actor_id or ""))
    if actor is None or not actor.active or held_merit(engine, actor) < 1:
        return None  # nothing to spend, so nothing is asked
    from . import needle

    chosen = needle.ask(engine, intent, needle.checkpoint_id(engine, "SECT_CHECK_MERIT", roll.roll_id), actor,
                        SECT_CHECK_AFTER, ["add"], labels={"add": "Add 1 Merit Die to this Sect Check"},
                        preferred=["add"], allow_decline=True, automatic=True, default="decline",
                        name="Sect Check", feature_id=MERIT_CHECK, target_id=actor.entity_id,
                        prompt=f"Your Sect Check is {roll.total}, and no result has been decided yet. Spend 1 Merit "
                               f"Die to roll it and add that result to this check? You have "
                               f"{held_merit(engine, actor)} Merit Die(s) left. Only one Merit Die may be added to "
                               f"any one Sect Check, and the table decides what the result means.",
                        prompt_context={"cost": "Costs 1 Merit Die, added after the d20 but before the result"})
    if chosen != ["add"]:
        return None
    number = roll_merit_die(engine, actor, source)
    actor.resources[MERIT] = held_merit(engine, actor) - 1
    note(engine, source, actor,
         f"Sect Check: {number} added from one Merit Die after the d20 was rolled "
         f"({held_merit(engine, actor)} Merit Die(s) left).")
    return {"source_id": MERIT_CHECK, "bonus": number}


@effect("petition_the_hall")
def petition_the_hall(ctx: Any, eff: dict[str, Any]) -> None:
    """"spend one Merit Die to petition ... for ordinary support. Roll the Merit Die." and its printed bands.

    The die is the action's own cost, so it is already paid by the time this runs. Communal Rice Bowl's "treat a
    Merit Die result of 1 as a 3" and Medicine Hall Queue's "roll your Merit Die twice and use the higher result"
    both apply to this same roll, because both print as a change to the petition's die. Only the printed 1 becomes a
    3, so a 2 is still a 2 and still reports the "minimum help" band.
    """
    engine, actor = ctx.engine, ctx.actor
    source = ctx.source
    topic = str(eff.get("topic") or ORDINARY_TOPIC)
    # Which riders apply, and which requests they were printed for, were decided at compile time from the ids this
    # character printed and carried on this effect, so resolution reads only its own effect: a petition for the food,
    # lodging, work clothes, tools, a bath or safe storage Communal Rice Bowl names always arrives on the button that
    # carries its "treat a 1 as a 3", whichever button the player pressed for it.
    one_becomes = int(eff["one_becomes"]) if eff.get("one_becomes") else None
    twice = bool(eff.get("twice"))
    subject = str(eff.get("subject") or ORDINARY_SHORT)
    talents = tuple(str(name) for name in eff.get("talents") or ())
    requests = tuple(str(request) for request in eff.get("requests") or ())
    number = roll_merit_die(engine, actor, source, twice=twice, one_becomes=one_becomes)
    engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": None, "dc": None, "success": None, "check": "Petitioning the Hall",
                                  "useful_help": number >= 3,
                                  "merit_die": number, "merit_die_size": merit_die_size(engine, actor),
                                  "topic": topic, "requests": list(requests), "talents": list(talents),
                                  "rolled_twice": twice, "one_becomes": one_becomes})
    extra = ""
    if twice:
        extra = f" (rolled twice, the higher kept{f', {talents[0]}' if talents else ''})"
    elif one_becomes is not None:
        extra = f" (a 1 reads as a {one_becomes}{f', {talents[0]}' if talents else ''})"
    band = petition_band(number)
    if number <= 2:
        band += f" (your Standing is {STANDING_NOTE})"
    note(engine, source, actor,
         f"Petitioning the Hall for {subject}: Merit Die {number} on a d{merit_die_size(engine, actor)}{extra} - "
         f"{band}. The GM confirms the appropriate authority, your Standing there, and the actual support.")


@effect("merit_reduce")
def merit_reduce(ctx: Any, eff: dict[str, Any]) -> None:
    """A cost, a time or a wastage cut by the printed Merit Die percentage, reported for the table to apply.

    Contribution Exchange and Department Ledger both reduce something "by 10 percent per number rolled on the Merit
    Die, to a maximum reduction of 50 percent". The die is the action's own cost, already paid before this runs, so
    this only rolls it: charging here as well would spend two dice for one benefit, and with a single die would spend
    the last one and then refuse to roll. The line names the talent and what the percentage cuts, so the table knows
    which exchange cost, schedule or wastage it applies to.
    """
    engine, actor = ctx.engine, ctx.actor
    source = ctx.source
    talent = str(eff.get("talent") or "Sect Stewardship")
    cuts = str(eff.get("cuts") or "the thing you named")
    number = roll_merit_die(engine, actor, source)
    percent = reduction_percent(number)
    engine._append_event("CHECK_ROLLED", source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                         payload={"actor": None, "dc": None, "success": None, "check": "Merit Die",
                                  "merit_die": number, "reduction_percent": percent, "cuts": cuts,
                                  "talent": talent, "merit_die_size": merit_die_size(engine, actor)})
    note(engine, source, actor,
         f"{talent}: Merit Die {number} on a d{merit_die_size(engine, actor)} cuts {cuts} by {percent}% "
         f"(at most 50%).")
