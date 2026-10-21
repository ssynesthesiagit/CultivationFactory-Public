"""The Warleader Sphere's Standards, Commanded allies, Shouts, Momentum Marks and Command Responses (sys-resources-states
2026-09-29: the whole Sphere was unautomated -- "Shouts / Commanded / Standards / Momentum" were blocked systems).

Source (owner text: authority/typed_mechanics/rules_text.json WARLEADER_BASE_* and tianxia.talent.warleader.*, the Sphere
Compendium's Warleader chapter -- there is no Spheres 5e or D&D 5.5e equivalent to fall back on):
  Command Range 30 feet. A creature is COMMANDED when it is within Command Range and perceives the leader's current Standard:
  it must see or hear the leader (a Deafened creature cannot take a purely spoken order unless it also sees the leader or a
  signal). An Unconscious, Incapacitated or Paralyzed creature cannot follow a Standard. The leader is always Commanded by
  its own Standard while it is conscious and able to act.
  Set the Standard: a Bonus Action, "Choose one Standard you know. Until the start of your next turn, you and Commanded
  allies may benefit from that Standard." One Standard at a time; setting a new one ends the old. Not magical, not a
  Formation, and it "does not force an ally to act". Press the Opening is known from the start.
  Momentum Marks: "You can hold a number of Momentum Marks equal to your Proficiency Bonus. You gain 1 the first time on each
  turn that one of these happens: a Commanded ally benefits from your active Standard; a Commanded ally hits a creature you
  identified as the objective; a Commanded ally uses the Help action to aid another Commanded ally; a Commanded ally
  succeeds on a saving throw after gaining a bonus or reroll from one of your Warleader talents. They last until combat
  ends, until you are Incapacitated, or until you complete a short or long rest. You cannot gain more than one from the
  same creature on the same turn."
Reading choices (the text does not settle them; each is a judgment, flagged in the report):
  * "first time on each turn" is one Mark per turn (whoever's turn it is) from these four sources: Coordinated Aid's "even
    if you have already gained a Momentum Mark this turn" only makes sense if there is such a per-turn limit.
  * An ally "benefits from your active Standard" when the Standard's effect is applied to a real roll or hit of that ally
    (the +2 AC on an attack roll made against it, a +2 to its save or attack roll, the damage the Standard reduced, the
    extra Speed it moved with). The engine cannot know whether the +2 changed the outcome.
  * Secondary Standards (Layered Orders, Ten Thousand Banners Doctrine) give their passive benefit only and grant no
    Momentum. The printed text asks the leader to choose them, so a player at the table gets a menu (secondaries); a fighter
    the table plays, or a fight with nobody answering, keeps the fixed preference (PASSIVE_ORDER below), which is what every
    saved fight was recorded with.

Plug-in surface: effect types "warleader_standard" (a Bonus Action row's effect: sets the leader's Standard),
"warleader_shout" (a Shout row's first effect: who hears it, the chosen shape, self included), the feature block
"warleader_known" (a compiled flag: the leader knows this talent) and the hook choice_options (this module's own
choice id SECONDARY_CHOICE, the Layered Orders menu). The Standard is a condition on the leader
("condition:typed.warleader_standard", with hover text); who is Commanded is worked out each time it matters.

Shared Warleader-family API. The other two modules of this family -- combat/ext/warleader_commands.py (Standards, Standards
Talents and the Court of Moving Banners) and combat/ext/warleader_shouts.py (the Shouts) -- read this module's data through
these public functions only: rows reads a compiled feature block for a creature, proficiency reads a creature's Proficiency
Bonus, leaders lists every active Standard in the fight, and shout_area reads the chosen shape of a Shout. A fourth family
member must use these public names too, never an underscore-prefixed one: anything another module needs belongs here, named
without an underscore, and this paragraph is where its consumers are recorded.
warleader_second_pass consumes commanded, leaders, proficiency, gain_momentum,
spend_momentum, choose, table_driven, has_benefited and shout_area for its printed
Command the Gap, Standard-Bearer Adept and Voice That Carries contracts.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, note

CONDITION = "condition:typed.warleader_standard"
MOMENTUM = "resource:named.momentum_mark"
FOCUS = "resource:core.martial_focus"
BASE_TALENT = "tianxia.talent.warleader."  # the printed id a feature_blocks row or a prompt names this Sphere's talents by
COMMAND_RANGE_FT = 30
BANNERS_RANGE_FT = 120  # Ten Thousand Banners Doctrine: "While you hold Martial Focus, your Command Range increases to 120 feet."
COURT = "condition:typed.warleader_court"  # Warleader Domain: Court of Moving Banners (combat/ext/warleader_commands.py)
COURT_RANGE_FT = 60  # "your Command Range becomes the Domain area": a 60-foot Emanation

STANDARDS: dict[str, tuple[str, str]] = {
    "press_the_opening": ("Press the Opening", "When two Commanded allies have the same hostile creature within reach, each of those allies gains +2 to the "
                                               "first attack roll it makes against that creature on its turn (once per creature per turn)."),
    "shieldbrothers": ("Shieldbrothers", "A Commanded ally gains +2 AC while adjacent to at least one other Commanded ally."),
    "ironclad_line": ("Ironclad Line", "Commanded allies reduce nonmagical Bludgeoning, Piercing and Slashing damage by the leader's Proficiency Bonus "
                                        "while adjacent to at least one other Commanded ally."),
    "couriers_dash": ("Courier's Dash", "Commanded allies gain +10 feet Speed until the start of the leader's next turn (only while moving toward an "
                                        "enemy, ally, objective, exit or battlefield position the leader identified -- the engine cannot check that)."),
    "coordinated_reflexes": ("Coordinated Reflexes", "Commanded allies gain +2 on Dexterity saving throws against effects that target an area while adjacent "
                                                     "to at least one other Commanded ally. The leader may spend 1 Momentum Mark to let a Commanded ally reroll a failed one."),
    "fortifying_phalanx": ("Fortifying Phalanx", "Commanded allies gain +2 on Constitution saving throws while adjacent to at least one other Commanded "
                                                 "ally. The leader may spend 1 Momentum Mark to let a Commanded ally reroll a failed one."),
    "militant_will": ("Militant Will", "Commanded allies gain +2 on saving throws against the Charmed and Frightened conditions. The leader may spend 1 "
                                       "Momentum Mark to let a Commanded ally reroll a failed one."),
    "marked_objective": ("Marked Objective", "The leader identified an objective. The first Commanded ally each turn that moves at least 10 feet toward it "
                                             "or hits it gains the chosen benefit."),
    "deadly_herdsman": ("Deadly Herdsman", "Once per turn when a Commanded ally damages a hostile creature with an attack, that ally may Shove the target as a "
                                           "Bonus Action; if that moves it out of another Commanded ally's reach, that ally may make an Opportunity Attack."),
    "legion_unending": ("Legion Unending", "If a Commanded ally would be reduced to 0 Hit Points, the leader may spend 1 Momentum Mark as a Reaction: the ally "
                                           "gains Temporary HP equal to 2 x the leader's CL before the damage, until the start of the leader's next turn."),
    "preparation": ("Preparation", "Outside combat, Commanded allies who can hear or see the preparations gain a bonus to Initiative equal to the leader's "
                                   "Proficiency Bonus (nothing to apply once a fight has begun)."),
}
# Standards whose benefit is passive, so Layered Orders / Ten Thousand Banners may carry them as secondaries; the fixed
# order is the reading a fighter the table plays gets (see secondaries), and the menu's preferred order for everyone else.
PASSIVE_ORDER = ("shieldbrothers", "ironclad_line", "press_the_opening", "fortifying_phalanx", "coordinated_reflexes", "militant_will", "couriers_dash")
OBJECTIVE_BENEFITS = {"attack": "+2 to the triggering attack roll", "speed": "+10 feet Speed until the end of the turn",
                        "temp_hp": "Temporary HP equal to the leader's Proficiency Bonus"}  # Marked Objective's printed menu
# What each secondary Standard actually does, in one plain line, so a menu label compares the choices instead of
# only naming them (change standard 13). Kept beside PASSIVE_ORDER, which lists the same Standards.
PASSIVE_BENEFITS = {
    "shieldbrothers": "a Commanded ally standing beside another Commanded ally gains +2 Armor Class",
    "ironclad_line": "a Commanded ally beside another Commanded ally takes less nonmagical weapon damage (the leader's Proficiency Bonus less)",
    "press_the_opening": "+2 to the first attack roll two Commanded allies make against the same foe",
    "fortifying_phalanx": "a Commanded ally beside another Commanded ally gains +2 on Constitution saving throws",
    "coordinated_reflexes": "a Commanded ally beside another Commanded ally gains +2 on Dexterity saves against area effects",
    "militant_will": "a Commanded ally gains +2 on saving throws against being Charmed or Frightened",
    "couriers_dash": "a Commanded ally gains +10 feet of Speed",
}


# ------------------------------------------------------------------------------------------------------ who is Commanded
def rows(engine: Any, actor: Any, block: str) -> list[dict[str, Any]]:
    from .. import typed_reactions

    return typed_reactions._rows(engine, actor.entity_id, block)


def knows(engine: Any, actor: Any, talent: str) -> bool:
    return any(row.get("talent") == talent for row in rows(engine, actor, "warleader_known"))


def known_standards(engine: Any, actor: Any) -> list[str]:
    """The Standards this leader can Set: one per row of its own actions (combat/factory_compiler.py builds a Bonus Action row
    for the base Press the Opening and for every Standard talent)."""
    found: list[str] = []
    for action_id in actor.action_ids:
        action = engine.action_catalog.get(action_id)
        for row in (((action.parameters or {}).get("typed") or {}).get("effects") or []) if action is not None else []:
            if isinstance(row, dict) and row.get("type") == "warleader_standard" and row.get("standard") not in found:
                found.append(str(row["standard"]))
    return found


def standard_of(leader: Any) -> dict[str, Any] | None:
    for condition in leader.conditions.values():
        if condition.condition_id == CONDITION and condition.source_actor_id == leader.entity_id:
            return (condition.data or {}).get("warleader") or None
    return None


def _cannot_follow(actor: Any) -> bool:
    """"Unconscious, Incapacitated or Paralyzed" -- every one of them carries the no_actions rule."""
    from ..typed_executor import condition_rules

    return not actor.active or any(row.get("no_actions") for row in condition_rules(actor))


def _blind(actor: Any) -> bool:
    return any(condition.condition_id == "condition:typed.blinded" for condition in actor.conditions.values())


def court_of(leader: Any) -> Any | None:
    """The leader's running Court of Moving Banners (a Martial Domain that lasts a minute), if any."""
    return next((condition for condition in leader.conditions.values() if condition.condition_id == COURT), None)


def command_range(engine: Any, leader: Any, data: dict[str, Any]) -> int:
    """30 feet; 120 with Ten Thousand Banners Doctrine while it holds Martial Focus; the Court's 60-foot Domain while it runs (the wider
    of the two when both apply: neither says it replaces the other)."""
    reach = COMMAND_RANGE_FT
    if data.get("banners") and leader.resources.get(FOCUS, 0) >= 1:
        reach = BANNERS_RANGE_FT
    return max(reach, COURT_RANGE_FT) if court_of(leader) is not None else reach


def perceives(engine: Any, leader: Any, ally: Any) -> bool:
    """It must see or hear the leader; Deafened, it needs to see the leader (or a banner or signal), and a Blinded creature hears."""
    from ..typed_executor import cant_hear

    if not cant_hear(ally):
        return True
    return not _blind(ally) and bool(engine._line_of_sight_actor_to_actor(ally, leader))


def commanded(engine: Any, leader: Any, data: dict[str, Any], subject: Any) -> bool:
    if subject.entity_id == leader.entity_id:
        return leader.active and not _cannot_follow(leader)  # "always Commanded by its own Standard while conscious and able to act"
    if subject.team_id != leader.team_id or _cannot_follow(subject) or _cannot_follow(leader):
        return False
    return engine._distance_actor_to_actor(leader, subject) <= command_range(engine, leader, data) and perceives(engine, leader, subject)


def leaders(engine: Any) -> list[tuple[Any, dict[str, Any]]]:
    found = []
    for actor in engine.state.actors.values():
        data = standard_of(actor) if actor.active else None
        if data:
            found.append((actor, data))
    return found


def commanders(engine: Any, subject: Any, standard: str, *, primary_only: bool = False) -> list[tuple[Any, dict[str, Any]]]:
    """Leaders whose active Standard (the primary, or a secondary unless ``primary_only``) is ``standard`` and who command ``subject``."""
    out = []
    for leader, data in leaders(engine):
        if data.get("standard") == standard or (not primary_only and standard in (data.get("secondary") or [])):
            if commanded(engine, leader, data, subject):
                out.append((leader, data))
    return out


def adjacent_commanded(engine: Any, leader: Any, data: dict[str, Any], subject: Any) -> bool:
    """"While adjacent to at least one other Commanded ally": the leader is Commanded too, so standing beside it counts."""
    return any(other.entity_id != subject.entity_id and engine._distance_actor_to_actor(subject, other) <= 5 and commanded(engine, leader, data, other)
               for other in engine.state.actors.values() if other.active and other.team_id == leader.team_id)


# ------------------------------------------------------------------------------------------------------ Momentum Marks
def _turn_token(engine: Any) -> str:
    return f"{engine.state.round_number}:{engine.state.current_actor_id}"


def gain_momentum(engine: Any, leader: Any, source: Any, why: str, *, uncapped: bool = False) -> bool:
    """One Momentum Mark: not more than one a turn from these sources (``uncapped``: Coordinated Aid's Help says "even if you have
    already gained a Momentum Mark this turn"), not more than one from the same creature a turn. A leader whose Sphere has no
    Momentum pool (it does not know the Sphere's marks) gains nothing."""
    if MOMENTUM not in leader.resources or not leader.active or _cannot_follow(leader):
        return False
    token = _turn_token(engine)
    from_key = "typed_round_wl_momentum_from"
    seen = str(leader.turn_flags.get(from_key) or "")
    seen = seen.split("|", 1)[1] if seen.startswith(token + "|") else ""
    sources = [part for part in seen.split(",") if part]
    if not uncapped and (leader.turn_flags.get("typed_round_wl_momentum") == token or source.entity_id in sources):
        return False
    if leader.resources[MOMENTUM] >= leader.resource_maximums.get(MOMENTUM, 0):
        return False
    amount = 1
    if court_of(leader) is not None and leader.resources[MOMENTUM] + 1 < leader.resource_maximums.get(MOMENTUM, 0):
        amount = 2  # Court of Moving Banners: "when you gain a Momentum Mark, gain one additional Momentum Mark, up to your normal maximum"
    engine._gain_resource(leader, MOMENTUM, amount, "warleader:momentum")
    leader.turn_flags["typed_round_wl_momentum"] = token
    leader.turn_flags[from_key] = token + "|" + ",".join([*sources, source.entity_id])
    note(engine, "warleader:momentum", leader, f"{leader.display_name} gains a Momentum Mark ({why}).", (source,))
    return True


def benefit(engine: Any, subject: Any, standard: str, why: str) -> None:
    """A Commanded creature benefited from an active primary Standard: its leader gains a Momentum Mark."""
    for leader, data in commanders(engine, subject, standard, primary_only=True):
        from .warleader_second_pass import fulfilled
        fulfilled(engine, leader, subject, standard)
        gain_momentum(engine, leader, subject, why)


def spend_momentum(engine: Any, leader: Any, source: str, amount: int = 1) -> bool:
    if leader.resources.get(MOMENTUM, 0) < amount:
        return False
    engine._spend_resource(leader, MOMENTUM, amount, source)
    return True


# ------------------------------------------------------------------------------------------------------ Set the Standard
def _reading(name: str, text: str, data: dict[str, Any]) -> str:
    out = f"{name}: {text}"
    for slug in data.get("secondary") or []:
        out += f" Also carries the secondary Standard {STANDARDS[slug][0]} (passive benefit only, no Momentum Marks or Command Responses)."
    if data.get("objective_name"):
        out += f" Objective: {data['objective_name']} -- benefit: {OBJECTIVE_BENEFITS.get(data.get('benefit'), '')}."
    return out


_TALENT_SPELLING = {"couriers_dash": "courier_s_dash"}  # the only Standard whose talent id is spelled differently
SECONDARY_CHOICE = "choice:warleader.secondary_standard"  # this plug-in's own choice id (choice_options)


def talent_of_standard(slug: str) -> str:
    """The printed talent slug behind a Standard (Press the Opening is the base Set the Standard's own Standard)."""
    return _TALENT_SPELLING.get(slug, slug)


def choose(engine: Any, leader: Any, intent: Any, checkpoint: str, choice_id: str, options: list[str], *,
           labels: dict[str, str], prompt: str, name: str, feature_id: str,
           target_id: str | None = None) -> tuple[bool, str | None]:
    """One printed "choose ..." of a Warleader talent, asked of a player who is at the table as a labelled menu with the
    options named, the triggering action named and the affected creature named (needle.ask, the documented choice
    transport; the labels and the prompt travel to the table through the ``choice_options`` hook below). Returns
    ``(asked, option id)``: ``asked`` is False when the fighter's controller decides for itself (an AI fighter, or a fight
    nobody answers -- so a saved AI replay never gains a question it did not have), in which case the caller picks for it;
    ``asked`` is True with the chosen option, or True with None when the player at the table declined. Shared by every
    Warleader "choose" so each one is worded and transported the same way."""
    from . import needle

    if not options or table_driven(engine, leader) or not hasattr(engine, "_gate4_reaction_cache"):
        return False, None
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, checkpoint, leader.entity_id, target_id or "", str(len(options))),
                        leader, choice_id, options, labels=labels, prompt=prompt, minimum=1, maximum=1,
                        allow_decline=True, name=name, feature_id=feature_id, target_id=target_id)
    return True, (picked[0] if picked else None)


def table_driven(engine: Any, actor: Any) -> bool:
    """Whether this fight's controller chooses for ``actor`` (an AI fighter, or a player left on Auto). A player who is
    actually at the table is asked instead. Used wherever the printed text says "choose", so a fighter the table plays
    keeps the fixed reading the engine has always used and its saved replays stay identical."""
    modes = getattr(engine, "typed_control_modes", {}) or {}
    owner = actor.owner_id if not actor.primary_combatant else None
    return modes.get(owner or actor.entity_id) in {"LOCAL_AUTO", "API_AUTO"}


def secondaries(engine: Any, leader: Any, intent: Any, owned: list[str], slots: int, source: str, *,
                 required: bool = True) -> list[str]:
    """The secondary Standards Layered Orders ("choose one primary Standard and one secondary Standard") and Ten Thousand
    Banners Doctrine ("choose up to three Standards. One is primary and two are secondary") carry. The printed text asks the
    leader to choose, so a player at the table gets a menu of the passive Standards it knows, each labelled with what its passive
    benefit actually is; a fighter the table plays (and a fight with nobody answering) keeps PASSIVE_ORDER, which is the reading
    every saved fight was recorded with. ``required`` is the printed difference between the two: Layered Orders asks for *one*
    secondary Standard, so its menu has no decline and takes one; Ten Thousand Banners says *up to* three, so its menu offers
    decline and a leader who declines carries none. A secondary Standard is passive only: it never pays a Momentum Mark or a
    Command Response, which `commanders(primary_only=True)` reads. An empty answer is kept as given (a decline), never replaced
    by the fixed reading; only a fight nobody answers falls back, which `needle.ask` does itself."""
    from . import needle

    slugs = [slug for slug in PASSIVE_ORDER if slug in owned]
    if not slugs or table_driven(engine, leader) or not hasattr(engine, "_gate4_reaction_cache"):
        return slugs[:slots]
    labels = {slug: f"{STANDARDS[slug][0]}: {PASSIVE_BENEFITS[slug]} (as a second Standard: passive only, no Momentum Mark or "
                       f"Command Response)" for slug in slugs}
    picked = needle.ask(engine, intent, needle.checkpoint_id(engine, "WARLEADER_SECONDARY_STANDARD", leader.entity_id, source),
                        leader, SECONDARY_CHOICE, slugs, labels=labels,
                        prompt=(f"Set the Standard: choose the secondary Standard{'s' if slots > 1 else ''} this leader carries "
                                f"alongside the primary one. It pays no Momentum Mark and gives no Command Response."),
                        preferred=slugs[:slots], minimum=1 if required else 0, maximum=min(slots, len(slugs)),
                        default="all", default_count=slots, allow_decline=not required,
                        name="Secondary Standard", feature_id=BASE_TALENT + "layered_orders", target_id=leader.entity_id)
    # An answer is the answer: a declined Ten Thousand Banners menu (minimum 0, decline allowed) carries none, and is
    # never replaced by the fixed reading. Only a fight nobody answers falls back, which needle.ask does itself.
    picked = [slug for slug in slugs if slug in picked][:slots]
    needle.say(engine, SECONDARY_CHOICE, leader,
               (f"{leader.display_name} carries the secondary Standard{'s' if len(picked) > 1 else ''} "
                f"{', '.join(STANDARDS[slug][0] for slug in picked)}." if picked else
                f"{leader.display_name} carries no secondary Standard (it chose none)."))
    return picked


@hook("choice_options")
def warleader_choice(engine: Any, intent: Any, checkpoint: str, reactor_id: str, choice_id: str,
                    context: dict[str, Any]) -> dict[str, Any] | None:
    """Every Warleader "choose ..." menu this module asks (the Layered Orders / Ten Thousand Banners secondary Standard,
    Reactive Position's partner, Battlefield Coordination's Disadvantage source), transported by the shared choice_options hook
    so the table shows labelled buttons and can answer them. Only this module's own ``choice:warleader.`` namespace, so it is
    inert for every other ability and every old saved fight. The option bounds and the decline rule come from the menu itself."""
    if not choice_id.startswith(CHOICE) or not (context or {}).get("needle_options"):
        return None
    return {"option_ids": list(context["needle_options"]), "minimum_selections": int(context.get("minimum", 1)),
            "maximum_selections": int(context.get("maximum", 1)), "allow_decline": bool(context.get("allow_decline", False)),
            "automatic_use": bool(context.get("automatic", True)),
            "preferred_option_ids": list(context.get("preferred") or [])}


@effect("warleader_standard")
def set_standard(ctx: Any, eff: dict[str, Any]) -> None:
    """Set the Standard (a Bonus Action): the leader's previous Standard ends; the new one lasts until the start of the leader's
    next turn. Layered Orders adds a secondary, Ten Thousand Banners Doctrine two, and lengthens the Command Range while the
    leader holds Martial Focus."""
    from .. import typed_executor

    slug = str(eff.get("standard") or "press_the_opening")
    if slug not in STANDARDS:
        return
    leader, engine = ctx.actor, ctx.engine
    if any(condition.condition_id == CONDITION for condition in leader.conditions.values()):
        engine._remove_condition(leader, CONDITION, ctx.source)  # "setting a new Standard ends your previous Standard"
    data: dict[str, Any] = {"standard": slug, "secondary": [], "banners": knows(engine, leader, "ten_thousand_banners_doctrine")}
    slots = 2 if data["banners"] else 1 if knows(engine, leader, "layered_orders") else 0
    if slots:
        owned = [option for option in known_standards(engine, leader) if option != slug]
        # Layered Orders: "choose one primary Standard and one secondary Standard" (a secondary Standard is required, so
        # its menu has no decline). Ten Thousand Banners Doctrine: "choose up to three Standards. One is primary and two are
        # secondary" ("up to" means none is legal, so that menu can be declined).
        data["secondary"] = secondaries(engine, leader, getattr(ctx, "intent", None), owned, slots, ctx.source,
                                        required=not data["banners"])
    if eff.get("benefit") in OBJECTIVE_BENEFITS:
        objective = ctx.target if ctx.target is not None and ctx.target.team_id != leader.team_id else _nearest_foe(engine, leader)
        if objective is not None:
            data.update(objective=objective.entity_id, objective_name=objective.display_name, benefit=eff["benefit"])
    name, text = STANDARDS[slug]
    court = court_of(leader)  # Court of Moving Banners: "maintain one Standard without spending a Bonus Action each round"
    expiry = court.expires_on if court is not None else "START_OF_SOURCE_NEXT_TURN"
    from .effect_durations import apply_condition_preserving_clock
    apply_condition_preserving_clock(engine, leader, court, CONDITION, ctx.source, leader.entity_id, expires_on=expiry,
                            data={"warleader": data, "label": f"Standard: {name}", "reading": _reading(name, text, data)})
    note(engine, "warleader:standard", leader, f"{leader.display_name} sets the Standard: {name}.")
    from .warleader_second_pass import standard_set
    standard_set(ctx, data)
    if slug == "couriers_dash" or "couriers_dash" in data["secondary"]:
        leader.movement_remaining_ft += 10  # the leader is Commanded by its own Standard: the extra Speed starts now


def _nearest_foe(engine: Any, leader: Any) -> Any | None:
    foes = [other for other in engine.state.actors.values() if other.active and other.team_id != leader.team_id
            and engine._distance_actor_to_actor(leader, other) <= COMMAND_RANGE_FT]
    return min(foes, key=lambda other: (engine._distance_actor_to_actor(leader, other), other.entity_id)) if foes else None


@hook("compile_block")
def compile_known(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "warleader_known":
        return None
    return [{**row, "talent": spec.get("talent"), "numbers": {"pb": numbers.get("pb"), "key_mod": numbers.get("key_mod"), "cl": numbers.get("cl")}}]


# ------------------------------------------------------------------------------------------------------ passive Standards
@hook("ac")
def shieldbrothers_ac(engine: Any, target: Any) -> int | None:
    """Shieldbrothers: +2 AC to a Commanded ally adjacent to another (the leader counts)."""
    for leader, data in commanders(engine, target, "shieldbrothers"):
        if adjacent_commanded(engine, leader, data, target):
            return 2
    return None


@hook("speed")
def couriers_dash_speed(engine: Any, actor: Any) -> int | None:
    return 10 if commanders(engine, actor, "couriers_dash") else None


@hook("damage_reduction")
def ironclad_line(engine: Any, target: Any, damage_type: str, typed: dict[str, Any], source_actor_id: str | None, applied: bool = False) -> int | None:
    """Ironclad Line: nonmagical Bludgeoning, Piercing and Slashing damage reduced by the leader's PB while adjacent to another Commanded ally."""
    if str(damage_type).upper() not in ("BLUDGEONING", "PIERCING", "SLASHING") or not typed.get("mundane"):
        return None
    for leader, data in commanders(engine, target, "ironclad_line"):
        if adjacent_commanded(engine, leader, data, target):
            if applied and data.get("standard") == "ironclad_line":
                benefit(engine, target, "ironclad_line", "Ironclad Line reduced the damage")
            return proficiency(leader)
    return None


def proficiency(actor: Any) -> int:
    return int(actor.proficiency_bonus)


@hook("attack_mode")
def remember_target(ctx: Any, target: Any) -> None:
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_wl_attack_target")
    ctx.engine._wl_attack_target = target.entity_id  # attack_bonus below is given no target; this runs just before it for the same roll
    return None


@hook("attack_bonus")
def attack_bonus(ctx: Any, actor: Any) -> int | None:
    """Press the Opening: +2 to the first attack roll a Commanded ally makes against a hostile creature that it and another Commanded ally
    both have within reach; Marked Objective's +2 to the first Commanded ally's attack roll against the objective."""
    from ..paid_relocation import preserve_pending
    preserve_pending(ctx.engine, "_wl_attack_target")
    engine = ctx.engine
    target = engine.state.actors.get(getattr(engine, "_wl_attack_target", None) or "")
    engine._wl_attack_target = None
    if target is None or target.team_id == actor.team_id:
        return None
    total = 0
    from ..typed_reactions import physical_melee_reach

    # "On its turn" excludes reaction attacks. Reach is the creature's current
    # melee reach, independent of the attack's range or an available Reaction.
    own_turn = engine.state.current_actor_id == actor.entity_id
    press_leaders = commanders(engine, actor, "press_the_opening")
    flag = f"wl_press:{target.entity_id}"
    first = own_turn and not actor.turn_flags.get(flag)
    reach = None
    if press_leaders and first:
        reach = physical_melee_reach(engine, actor)
        # The first attack against this creature has happened even if the pair
        # is not yet in reach; moving later cannot turn a second attack into it.
        actor.turn_flags[flag] = 1
    for leader, data in press_leaders if first else []:
        if reach is None or engine._distance_actor_to_actor(actor, target) > reach:
            continue
        if any(other.entity_id != actor.entity_id
               and (other_reach := physical_melee_reach(engine, other)) is not None
               and engine._distance_actor_to_actor(other, target) <= other_reach and commanded(engine, leader, data, other)
               for other in engine.state.actors.values() if other.active and other.team_id == leader.team_id):
            total += 2
            if data.get("standard") == "press_the_opening":
                benefit(engine, actor, "press_the_opening", "Press the Opening's +2 on an attack roll")
            break
    for leader, data in leaders(engine):
        if data.get("standard") == "marked_objective" and data.get("benefit") == "attack" and data.get("objective") == target.entity_id \
                and commanded(engine, leader, data, actor) and not _objective_used(engine, leader):
            _objective_used(engine, leader, mark=True)
            total += 2
            from .warleader_second_pass import fulfilled
            fulfilled(engine, leader, actor, "marked_objective")
    return total or None


def _objective_used(engine: Any, leader: Any, *, mark: bool = False) -> bool:
    """"The first Commanded ally on each turn": once per turn, whosever turn it is."""
    token = _turn_token(engine)
    if mark:
        leader.turn_flags["typed_round_wl_objective"] = token
        return True
    return leader.turn_flags.get("typed_round_wl_objective") == token


@hook("save")
def standard_save_bonus(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    """Coordinated Reflexes (Dexterity vs an area), Fortifying Phalanx (Constitution), Militant Will (Charmed / Frightened): +2."""
    engine, bonus = ctx.engine, 0
    area = bool((ctx.typed.get("area") or {}).get("size_ft"))
    checks = []
    if ability == "DEX" and area:
        checks.append(("coordinated_reflexes", True))
    if ability == "CON":
        checks.append(("fortifying_phalanx", True))
    if named & {"charmed", "frightened"}:
        checks.append(("militant_will", False))
    for standard, needs_neighbour in checks:
        for leader, data in commanders(engine, subject, standard):
            if needs_neighbour and not adjacent_commanded(engine, leader, data, subject):
                continue
            bonus += 2
            if data.get("standard") == standard:
                benefit(engine, subject, standard, f"{STANDARDS[standard][0]}'s +2 on a saving throw")
            break
    return {"bonus": bonus} if bonus else None


@hook("event")
def standard_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "ATTACK_ROLLED":
        for target_id in kwargs.get("target_ids") or ():
            target = engine.state.actors.get(target_id)
            if target is not None and commanders(engine, target, "shieldbrothers", primary_only=True) and shieldbrothers_ac(engine, target):
                benefit(engine, target, "shieldbrothers", "Shieldbrothers' +2 AC against an attack roll")
    elif event_type == "MOVEMENT_COMMITTED":
        actor = engine.state.actors.get(kwargs.get("actor_id") or "")
        if actor is None or payload.get("forced") or payload.get("dragged_by"):
            return
        if commanders(engine, actor, "couriers_dash", primary_only=True) and actor.movement_remaining_ft < 10 and engine.state.current_actor_id == actor.entity_id:
            benefit(engine, actor, "couriers_dash", "moved on Courier's Dash speed")
        _objective_movement(engine, actor, payload)
    elif event_type == "CONDITION_APPLIED":
        subject = engine.state.actors.get((kwargs.get("target_ids") or (None,))[0] or "")
        held = standard_of(subject) if subject is not None else None
        if held and held.get("extended") and _cannot_follow(subject):
            engine._remove_condition(subject, CONDITION, "warleader:quick_commands")  # Quick Commands: "If you are Incapacitated, the extended Standard ends."
        if subject is not None and subject.resources.get(MOMENTUM, 0) > 0 and _cannot_follow(subject):
            engine._spend_resource(subject, MOMENTUM, subject.resources[MOMENTUM], "warleader:momentum")  # "until you are Incapacitated"
            note(engine, "warleader:momentum", subject, f"{subject.display_name} is Incapacitated and loses every Momentum Mark.")


def _objective_movement(engine: Any, actor: Any, payload: dict[str, Any]) -> None:
    """Marked Objective: "The first Commanded ally on each turn that moves at least 10 feet toward the objective"."""
    from ..gate2_runtime_models import Position

    path = payload.get("path") or []
    if len(path) < 2:
        return
    for leader, data in leaders(engine):
        objective = engine.state.actors.get(data.get("objective") or "")
        if objective is None or not objective.active or _objective_used(engine, leader) or not commanded(engine, leader, data, actor):
            continue
        before = engine._distance_actor_to_actor(actor, objective, actor_position=Position(**path[0]))
        after = engine._distance_actor_to_actor(actor, objective)
        if before - after >= 10:
            _objective_benefit(engine, leader, data, actor, objective, "moved toward the objective")


def _objective_benefit(engine: Any, leader: Any, data: dict[str, Any], actor: Any, objective: Any, how: str) -> None:
    _objective_used(engine, leader, mark=True)
    kind = data.get("benefit")
    if kind == "temp_hp":
        engine._grant_temp_hp(actor, proficiency(leader), "warleader:marked_objective", leader.entity_id)
    elif kind == "speed":
        actor.movement_remaining_ft += 10
    note(engine, "warleader:marked_objective", leader, f"{actor.display_name} {how}: Marked Objective gives {OBJECTIVE_BENEFITS.get(kind, 'its benefit')}.", (actor,))
    if data.get("standard") == "marked_objective":
        from .warleader_second_pass import fulfilled
        fulfilled(engine, leader, actor, "marked_objective")
        gain_momentum(engine, leader, actor, "Marked Objective")


@hook("after_hit")
def objective_hit(ctx: Any, target: Any, kind: str) -> None:
    """A Commanded ally hits the identified objective: a Momentum Mark, and Marked Objective's benefit (Temporary HP or Speed)."""
    engine, actor = ctx.engine, ctx.actor
    for leader, data in leaders(engine):
        if data.get("objective") != target.entity_id or not commanded(engine, leader, data, actor) or actor.entity_id == target.entity_id:
            continue
        gain_momentum(engine, leader, actor, f"hit the objective, {target.display_name}")
        if data.get("benefit") in ("temp_hp", "speed") and not _objective_used(engine, leader):
            _objective_benefit(engine, leader, data, actor, target, "hit the objective")


# ------------------------------------------------------------------------------------------------------ Shouts
# A Shout is an Action with a shape (Breath Support: "normal 15-foot Emanation; 20-foot Cone; 30-foot Line that is 5 feet wide;
# at CL 11+ the Cone is 30 feet and the Line 60") whose ally half reaches "affected allies" -- the leader too (Focusing Cry
# says "You cannot choose yourself", which only means something if the leader is otherwise one of them). Every Shout row's first
# effect is {"type": "warleader_shout"}; the typed effects after it are ordinary ones, and their "ally" subjects are the audience
# below (typed_executor._allies_near asks the ``ally_subjects`` hook).
FIERCE = "condition:typed.warleader_fierce_shout"
BREATH_SUPPORT = "tianxia.talent.warleader.breath_support"


def shout_area(ctx: Any) -> dict[str, Any]:
    return ctx.typed.get("area") or {"shape": "emanation", "size_ft": 15, "centered_on_self": True}


def _once_of(ctx: Any) -> str | None:
    """The Shout whose once-per-rest limit keeps a creature out of the audience ("once": marked on every one who hears it;
    "once_only": the Shout's own effect marks just those it really worked on -- Harangue)."""
    return next((row.get("once") or row.get("once_only") for row in ctx.typed.get("effects") or []
                 if isinstance(row, dict) and row.get("type") == "warleader_shout"), None)


CHOICE = "choice:warleader."  # this plug-in's own choice namespace, transported by the choice_options hook


def once_marker(slug: str) -> str:
    return f"condition:typed.warleader_once_{slug}"


def has_benefited(creature: Any, slug: str) -> bool:
    return any(condition.condition_id == once_marker(slug) for condition in creature.conditions.values())


def mark_benefited(engine: Any, creature: Any, slug: str, source_id: str, label: str, reading: str) -> None:
    """"once per long rest" is once per fight at this table (there is no rest inside one), so the use is a durable
    marker condition that outlives the window that granted it and survives a table commit: a talent that may be used
    once a long rest must not be reusable once its temporary effect has ended. Shared by every "once per ..." Warleader
    talent, on the same terms as :func:`once_marker`."""
    engine._apply_condition(creature, once_marker(slug), source_id, creature.entity_id, expires_on="UNTIL_REMOVED",
                            data={"label": label, "reading": reading})


def audience_at(engine: Any, leader: Any, area: dict[str, Any], aim: Any = None, once: str | None = None) -> list[Any]:
    """The leader and the allies a Shout of this shape reaches from where the leader stands, who perceive it and, for a Shout a creature
    can benefit from only once per rest, have not yet had it."""
    from ..typed_executor import in_area

    size, shape = int(area.get("size_ft") or 15), str(area.get("shape") or "emanation")
    found = [leader]
    for ally in sorted(engine.state.actors.values(), key=lambda row: row.entity_id):
        if ally is leader or not ally.active or ally.team_id != leader.team_id:
            continue
        inside = in_area(engine, leader.position, aim or leader.position, ally.position, area) if shape in ("cone", "line") \
            else engine._distance_actor_to_actor(leader, ally) <= size
        if inside and perceives(engine, leader, ally):
            found.append(ally)
    return [creature for creature in found if not (once and has_benefited(creature, once))]


def audience(ctx: Any) -> list[Any]:
    """The leader and the allies the Shout reaches (in its shape, able to perceive it), worked out once per use."""
    cached = ctx.damage_cache.get("wl_audience")
    if cached is not None:
        return cached
    aim = None
    if ctx.typed.get("_area_aim"):
        from ..gate2_runtime_models import Position

        aim = Position(x=ctx.typed["_area_aim"][0], y=ctx.typed["_area_aim"][1])
    found = audience_at(ctx.engine, ctx.actor, shout_area(ctx), aim, _once_of(ctx))
    from .warleader_second_pass import voice_audience
    found = voice_audience(ctx, found, aim, _once_of(ctx))
    ctx.damage_cache["wl_audience"] = found
    return found


@hook("ally_subjects")
def shout_allies(ctx: Any, eff: dict[str, Any]) -> list[Any] | None:
    if not any(isinstance(row, dict) and row.get("type") == "warleader_shout" for row in ctx.typed.get("effects") or []):
        return None
    return audience(ctx)


@effect("warleader_shout")
def shout(ctx: Any, eff: dict[str, Any]) -> None:
    """The shout itself: the audience is fixed here (a log line names them); Fierce Shout also puts its bonus on each of them."""
    engine, leader = ctx.engine, ctx.actor
    heard = audience(ctx)
    area = shout_area(ctx)
    shape = (f"{area.get('size_ft')}-foot Emanation" if area.get("shape") == "emanation"
             else f"{area.get('size_ft')}-foot {area.get('shape')}")
    if not eff.get("hostile"):  # a hostile Shout's save names its own targets
        note(engine, ctx.source, leader, f"{leader.display_name} shouts ({shape}); allies who hear: "
                                         + (", ".join(ally.display_name for ally in heard if ally is not leader) or "none") + ".",
             tuple(ally for ally in heard if ally is not leader))
    if eff.get("once"):  # "A creature can benefit from <Shout> once per short rest" (no rest passes inside one fight)
        label = str(eff["once"]).replace("_", " ").title()
        for ally in heard:
            engine._apply_condition(ally, once_marker(str(eff["once"])), ctx.source, leader.entity_id, expires_on="UNTIL_REMOVED",
                                    data={"label": f"{label} (used)", "reading": f"Has benefited from {label} and cannot again until a short rest."})
    if eff.get("shout") == "fierce_shout":
        for ally in heard:
            engine._remove_condition(ally, FIERCE, ctx.source)  # "A creature can benefit from only one Fierce Shout at a time"
            engine._apply_condition(ally, FIERCE, ctx.source, leader.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                    data={"fierce": {"pb": _pb_of(ctx), "leader": leader.entity_id},
                                          "label": "Fierce Shout",
                                          "reading": f"The first attack this creature hits with before the start of {leader.display_name}'s next turn "
                                                     f"adds +{_pb_of(ctx)} (the Warleader's Proficiency Bonus) to its damage."})


def _pb_of(ctx: Any) -> int:
    return int(ctx.actor.proficiency_bonus)


@hook("after_hit")
def fierce_shout_bonus(ctx: Any, target: Any, kind: str) -> None:
    """Fierce Shout: "add your Proficiency Bonus to the damage roll of the first attack they hit with". It is dealt as a second packet
    of the attack's own damage type, as every other on-hit bonus the engine has is (typed_executor._on_hit_bonuses)."""
    from .. import typed_executor as te

    actor = ctx.actor
    condition = next((c for c in actor.conditions.values() if c.condition_id == FIERCE), None)
    if condition is None or ctx.damage_cache.get("_bonus") or target.team_id == actor.team_id:
        return
    pb = int((condition.data or {}).get("fierce", {}).get("pb") or 0)
    engine = ctx.engine
    engine._remove_condition(actor, FIERCE, ctx.source)
    dtype = next((str((event.payload or {}).get("damage_type") or "UNTYPED") for event in reversed(engine.events[-12:])
                  if event.event_type == "DAMAGE_COMMITTED" and target.entity_id in (event.target_ids or ())), "UNTYPED")
    if pb <= 0 or not target.active:
        return
    note(engine, "warleader:fierce_shout", actor, f"{actor.display_name}'s first hit adds +{pb} damage (Fierce Shout).", (target,))
    te._deal(te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {"_potency_used": True, "_bonus": True}), target, pb, dtype)


@hook("compile_actions")
def breath_support_shapes(info: dict[str, Any]) -> list[Any] | None:
    """Breath Support: every Shout also as a Cone or a Line, aimed like any other cone or line the table has (a cell)."""
    if BREATH_SUPPORT not in info["owned_ids"]:
        return None
    cl = int(info["numbers"].get("cl") or 1)
    cone, line = (30, 60) if cl >= 11 else (20, 30)
    made = []
    for action in info["actions"]:
        typed = (action.parameters or {}).get("typed") or {}
        if not any(isinstance(row, dict) and row.get("type") == "warleader_shout" for row in typed.get("effects") or []):
            continue
        if (typed.get("area") or {}).get("shape") != "emanation":
            continue
        for tag, label, size, area in (("cone", f"{cone}-ft Cone", cone, {"shape": "cone", "size_ft": cone}),
                                       ("line", f"{line}-ft Line", line, {"shape": "line", "size_ft": line, "width_ft": 5})):
            made.append(action.model_copy(update={
                "source_definition_id": f"{action.source_definition_id}+{tag}", "display_name": f"{action.display_name} ({label})",
                "target_kind": "CELL", "range_ft": size,
                "parameters": {**action.parameters, "typed": {**typed, "area": area, "range_ft": size}}}))
    return made or None


@hook("ai_candidate_allowed")
def ai_restraint(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """The built-in AI never ends a turn with a Bonus Action or Action to spare (fight audit 2026-09-29), so it would set the same
    Standard again, or shout again, every turn it could. It is kept from setting the Standard it already holds until it is due to
    run out (a player's menu keeps it), and from a Fierce Shout while it still holds one."""
    effects = (((getattr(action, "parameters", None) or {}).get("typed") or {}).get("effects")) or []
    for eff in effects:
        if not isinstance(eff, dict):
            continue
        if eff.get("type") == "warleader_standard":
            held = standard_of(actor)
            if held and held.get("standard") == eff.get("standard") and (eff.get("benefit") is None or held.get("benefit") == eff.get("benefit")):
                return False
        elif eff.get("type") == "warleader_shout" and eff.get("shout") == "fierce_shout":
            if any(condition.condition_id == FIERCE for condition in actor.conditions.values()):
                return False
    return None
