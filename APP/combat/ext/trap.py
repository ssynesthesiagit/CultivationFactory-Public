"""The Trap sphere (owner 2026-09-29: "i want everything we can automated"): a trap is a placed device on the map that
acts when a creature enters its square.  Owner rules: LocalSources/04_spheres_talents/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md
("Trap", Set Trap, Active Trap Limit, Default Trigger, Awareness, Disarming a Trap, Dart Mechanism, Tripwire, the talent
tags) and authority/typed_mechanics/rules_text.json (every TAL_TRAP_* and tianxia.talent.trap.* text).

Set Trap is a Ritual Procedure (1 minute, outside a fight); in a fight it is the Martial-Focus version: "You may instead
expend Martial Focus to set the trap as an Action. A trap placed this way lasts for 1 minute or until triggered."  So the
"Set Trap" action costs 1 Martial Focus and an Action, sets one trap in an unoccupied square within reach (5 ft) and lasts
10 rounds.  What it sets is chosen beforehand with free buttons kept until changed ("Trap form: ...", "Trap trigger: ...",
"Trap deployment: ...", "Trap aim: ...", the choose-one shape of combat/ext/bodyb_choices.py): the Set Trap text says "Choose one
trap pattern you know; one legal orientation; one Trigger talent; one Deployment talent", and a Dart or Snare talent goes with
the pattern ("apply only one Dart talent to one Dart Mechanism", "only one Snare talent to one trap").

A trap is a placement (combat/ext/placed.py): a typed zone, tag "trap", that carries its own settings.  Its "enter" trigger
runs ``placed_trap_fire`` -- "a creature triggers one of your traps when it enters one of the trap's spaces for the first time
on a turn", once per turn per creature (zones._run's guard) -- for every square a move crosses (placed.py's event hook).
Two of your traps never share a square; the Active Trap Limit is your Proficiency Bonus (+PB with Interlocking Lattice) and
past it "choose one older temporary trap to harmlessly fall apart" (the oldest, a default -- the text leaves the choice to you).

What runs: Dart Mechanism (a straight line of up to 90 ft in the direction set, first creature on it, a ranged Cultivation
Attack, Piercing 1d6/2d6/3d6/4d6 by CL), Tripwire (Dexterity save: Prone; success: it knows the trap; not destroyed; aware
creatures have Advantage; a Prone creature does not trigger it); the talents Aimed Shot, Blunt Dart (bludgeoning d10), Deadly Dart
(Piercing or Slashing d10), Net (Dart use and Snare use: Restrained until it escapes; escape is an Action against your Cultivation
Save DC), Noose, Razor Wire, Alarm Trap, Flash Trap, Terrain Trap (12 squares of Difficult Terrain around a corner for 1 minute,
or sprung at once), False Trigger, Warning Trigger, Chained Mechanism, Trap Wielder, Trapped Shield, Sneaky Trapper,
Interlocking Lattice's limit, Trapper's Recovery, Trap Expert.  A creature that saw the trap set knows it ("Awareness"); anyone
else may find it with the Search action (Wisdom (Perception) against your Cultivation Save DC; the ``after_search`` hook) and a
creature aware of it may disarm it with Utilize and a Dexterity check against the same DC (fail by 5+ triggers it); the trap's
own creator always succeeds.

Rider lane C4 (2026-09-30) added, at the end of this module: Court of the Hidden Nail, The Empty Road Was Never Empty, The Route Was
Chosen Already, Hundred-Mechanism Scripture, Trap Launcher, Stop Drop and Control with Pursuit Lattice, Trap Within the Trap,
Opportunist, Prepared Escape Route, Remote Trigger, the Noose's silence and Blunt Dart's knock-out.

The A2TRAP second pass adds sealed Aerial Rigging, Falling-Sky Mechanism and Heaven-Net Battlefield through trap_aerial,
including anchored raised-surface placement and Empty Road's two compatible Trigger talents. Old sealed packets are inert.

Not automated (each named in the talent's own rider): the Ritual setting and Persistent Trap (out of combat), Activation Trap and the
Script talents (they carry consumables, magic items and techniques), Layered Mechanism (which still carries a compatibility rider), a trap's own AC and HP (an object: the objects
system), and the hiding of a concealed trap from the table.
"""

from __future__ import annotations

from typing import Any

from . import damage_delivery as delivery, effect, hook, placed, trap_aerial

SPHERE = "tianxia.sphere.trap"
MF = "resource:core.martial_focus"
SETUP = "condition:typed.trap_setup"
NETTED = "condition:typed.netted"
LIFE_ROUNDS = 10  # "lasts for 1 minute or until triggered"
REACH_FT = 5  # "an unoccupied space within your reach"
DART_RANGE_FT = 90  # "a straight line up to 90 feet"

NET = "tianxia.talent.trap.net"
T = "TAL_TRAP_"

# form key -> (label, pattern, the talent it needs, damage type)
FORMS: dict[str, tuple[str, str, str | None, str]] = {
    "dart": ("Dart Mechanism", "dart", None, "PIERCING"),
    "aimed": ("Dart Mechanism + Aimed Shot", "dart", T + "AIMED_SHOT", "PIERCING"),
    "blunt": ("Dart Mechanism + Blunt Dart", "dart", T + "BLUNT_DART", "BLUDGEONING"),
    "deadly": ("Dart Mechanism + Deadly Dart (Piercing)", "dart", T + "DEADLY_DART", "PIERCING"),
    "deadly_slashing": ("Dart Mechanism + Deadly Dart (Slashing)", "dart", T + "DEADLY_DART", "SLASHING"),
    "dart_net": ("Net (Dart use)", "dart_net", NET, "UNTYPED"),
    "tripwire": ("Tripwire", "tripwire", None, "SLASHING"),
    "razor": ("Tripwire + Razor Wire", "tripwire", T + "RAZOR_WIRE", "SLASHING"),
    "net": ("Net (Snare use)", "net", NET, "UNTYPED"),
    "noose": ("Noose", "noose", T + "NOOSE", "UNTYPED"),
    "alarm": ("Alarm Trap", "alarm", T + "ALARM_TRAP", "UNTYPED"),
    "flash": ("Flash Trap", "flash", T + "FLASH_TRAP", "UNTYPED"),
    "terrain": ("Terrain Trap", "terrain", T + "TERRAIN_TRAP", "UNTYPED"),
    "terrain_now": ("Terrain Trap (sprung at once)", "terrain", T + "TERRAIN_TRAP", "UNTYPED"),
    "falling_sky": ("Dart Mechanism + Falling-Sky Mechanism", "dart", T + "FALLING_SKY_MECHANISM", "PIERCING"),
}
TRIGGERS = {"false": ("False Trigger", T + "FALSE_TRIGGER"), "warning": ("Warning Trigger", T + "WARNING_TRIGGER"),
            "chained": ("Chained Mechanism", T + "CHAINED_MECHANISM"),
            "aerial": ("Aerial Rigging", T + "AERIAL_RIGGING"), "remote": ("Remote Trigger", T + "REMOTE_TRIGGER"),
            "within": ("Trap Within the Trap", T + "TRAP_WITHIN_THE_TRAP")}
DEPLOYS = {"wielder": ("Trap Wielder", T + "TRAP_WIELDER"), "shield": ("Trapped Shield", T + "TRAPPED_SHIELD"),
           "sneaky": ("Sneaky Trapper", T + "SNEAKY_TRAPPER")}
AIMS = {"auto": ("toward the nearest foe", None), "n": ("north", (0, -1)), "ne": ("north-east", (1, -1)), "e": ("east", (1, 0)),
        "se": ("south-east", (1, 1)), "s": ("south", (0, 1)), "sw": ("south-west", (-1, 1)), "w": ("west", (-1, 0)),
        "nw": ("north-west", (-1, -1))}
AERIAL_AIMS = {"up": ("upward", (0, 0, 1)), "down": ("downward", (0, 0, -1)),
               **{f'{key}_up': (f'{label} and upward', (*vector, 1))
                  for key, (label, vector) in AIMS.items() if vector is not None},
               **{f'{key}_down': (f'{label} and downward', (*vector, -1))
                  for key, (label, vector) in AIMS.items() if vector is not None}}
# "Dart damage: CL 1-4: 1d6, CL 5-10: 2d6, CL 11-16: 3d6, CL 17-20: 4d6" (Dart Mechanism); Razor Wire uses the same table.
DICE_BY_CL = [(1, 4, 1), (5, 10, 2), (11, 16, 3), (17, 99, 4)]
DART_SIDES = {"dart": 6, "aimed": 8, "blunt": 10, "deadly": 10, "deadly_slashing": 10}


def _mod(score: int) -> int:
    return (int(score) - 10) // 2


# ------------------------------------------------------------------------------------------------ the kit a fighter owns
def _kit(engine: Any, owner: Any) -> dict[str, Any] | None:
    """The owner's Set Trap action's own record: the talents it owns and its numbers."""
    for action in engine.action_catalog.values():
        if action.owner_id == owner.entity_id and (action.parameters or {}).get("set_trap"):
            typed = (action.parameters or {}).get("typed") or {}
            return {"action": action, "owned": set((action.parameters or {}).get("trap_owned") or ()),
                    "runtime": (action.parameters or {}).get("trap_runtime") or {}, "numbers": typed.get("numbers") or {}}
    return None


def _limit(kit: dict[str, Any], engine: Any = None, owner: Any = None) -> int:
    pb = int(kit["numbers"].get("pb") or 2)
    extra = pb if T + "INTERLOCKING_LATTICE" in kit["owned"] else 0  # "Increase your active temporary-trap limit by your PB"
    if engine is not None and owner is not None:  # Court of the Hidden Nail / The Empty Road: "your active trap limit increases by your PB"
        extra += pb * sum(1 for name in (COURT, EMPTY_ROAD) if _state(engine, owner, name) is not None)
    return pb + extra


def _config(owner: Any) -> dict[str, Any]:
    for condition in owner.conditions.values():
        if condition.condition_id == SETUP:
            return dict(condition.data or {})
    return {}


# ------------------------------------------------------------------------------------------------------------ the buttons
@hook("compile_actions")
def trap_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out: list[Any] = []
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    owned = set(info["owned_ids"])
    runtime = trap_aerial.capabilities(info)

    def button(key: str, name: str, effects: list[dict[str, Any]], **params: Any) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id,
                                economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
                                parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                                            "expected_damage": 0, "player_only": True, **params})

    if SPHERE in info["spheres"]:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.set_trap", display_name="Set Trap", owner_id=actor_id, economy=EconomyKind.ACTION,
            resolution_kind="TYPED", target_kind="CELL", range_ft=REACH_FT, costs=((MF, 1),),
            parameters={"typed": {"effects": [{"type": "trap_place", "evidence": "You may instead expend Martial Focus to set the trap as an Action."}],
                                  "numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": SPHERE},
                        "expected_damage": 0, "player_only": True, "any_cell": True, "set_trap": True, "trap_owned": sorted(owned),
                        **({"trap_runtime": runtime} if runtime else {}),
                        **({"auto64_warning": True} if T + "WARNING_TRIGGER" in owned else {}),
                        **({"auto64_shield": True} if T + "TRAPPED_SHIELD" in owned else {})}))
        out.extend(_variant_actions(info, owned, numbers))
        if runtime:
            for raised, title in ((False, 'Set Trap: choose a space'), (True, 'Set Trap on a raised surface')):
                if raised and not runtime.get('aerial'):
                    continue
                out.append(ActionDefinition(source_definition_id=f'action:typed.{short}.set_trap.' + ('raised' if raised else 'choose_space'),
                    display_name=title, owner_id=actor_id, economy=EconomyKind.ACTION,
                    resolution_kind='TYPED', target_kind='SELF', costs=((MF, 1),),
                    parameters={'typed': {'effects': [{'type': 'trap_raised_place', 'include_ground': not raised}], 'numbers': numbers,
                        'duration': {'kind': 'instant'}, 'riders': []}, 'trap_raised': 1, 'trap_include_ground': not raised,
                        'player_only': False, 'expected_damage': 0,
                        'description': 'Action and Martial Focus: choose one visible unoccupied supported space '
                                       + ('above ground ' if raised else '') + 'within 5 feet for your configured trap. '
                                       'Physical anchors are required; unsupported air is illegal.'}))
        if T + 'WARNING_TRIGGER' in owned:
            out.append(ActionDefinition(source_definition_id=f'action:typed.{short}.warn_trap',
                display_name='Warn creatures about a trap', owner_id=actor_id, economy=EconomyKind.NONE,
                resolution_kind='TYPED', target_kind='CELL', range_ft=300,
                parameters={'typed': {'effects': [{'type':'trap_warn_later'}], 'numbers':numbers,
                    'duration':{'kind':'instant'}, 'riders':[]}, 'any_cell':True, 'trap_warn_later':True,
                    'expected_damage':0, 'player_only':True}))
        for key, (label, _pattern, talent, _type) in FORMS.items():
            if key == 'falling_sky' and not runtime.get('falling_sky'):
                continue
            if talent is None or talent in owned:
                out.append(button(f"trap_form.{key}", f"Trap form: {label}", [{"type": "trap_setup_pick", "field": "form", "value": key}],
                                  description=f"Choose {label} as the form of the next trap you set; this choice stays until changed.", setting_only=True))
        for field, table in (("trigger", TRIGGERS), ("deploy", DEPLOYS)):
            options = [(key, label) for key, (label, talent) in table.items() if talent in owned
                       and (field != 'trigger' or key in ('false', 'warning', 'chained') or runtime.get('dual_trigger'))
                       and (key != 'aerial' or runtime.get('aerial'))]
            if options:
                for key, label in [(None, "none"), *options]:
                    out.append(button(f"trap_{field}.{key or 'none'}", f"Trap {'trigger' if field == 'trigger' else 'deployment'}: {label}",
                                      [{"type": "trap_setup_pick", "field": field, "value": key}], setting_only=True))
        for key, (label, _vector) in AIMS.items():
            out.append(button(f"trap_aim.{key}", f"Trap aim: {label}", [{"type": "trap_setup_pick", "field": "aim", "value": key}],
                              description=f"Aim your next dart trap {label.lower()}; its projectile travels along that direction when triggered.", setting_only=True))
        if runtime.get('falling_sky'):
            for key, (label, _) in AERIAL_AIMS.items():
                out.append(button(f'trap_aim.{key}', f'Trap aim: {label}',
                    [{'type': 'trap_setup_pick', 'field': 'aim', 'value': key}], setting_only=True,
                    description=f'Choose {label} for your Falling-Sky dart. Its physical line stops at the first creature or solid obstacle.'))
        if runtime.get('aerial'):
            for value, title in ((1, 'on'), (0, 'off')):
                out.append(button(f'trap_aerial.{title}', f'Aerial Rigging: {title}',
                    [{'type': 'trap_setup_pick', 'field': 'aerial', 'value': value}], setting_only=True,
                    description=f'Aerial Rigging: choose {title} for traps you set next. Rigging requires physically plausible '
                                'wires, hooks, launched net or anchors on a supported surface. '
                                'Rigging uses one Trigger Talent; combining it with another needs active Empty Road. '
                                'Height is 10 feet at CL 5, 20 at CL 10, and 30 at CL 15. '
                                'Heaven-Net always rigs your Net and Terrain forms.'))
    # Anyone may disarm a trap they know and get out of a net (owner text: "A creature aware of one of your traps may take the
    # Utilize Action and make a Dexterity check using thieves' tools against your Cultivation Save DC"; Net: "A Restrained creature
    # may take the Utilize Action to make a Strength (Athletics) or Dexterity (Acrobatics) check against your Cultivation Save DC").
    from ..factory_compiler import _skill_bonus

    mods, sheet = info["mods"], info["owner_sheet"]
    proficient = SPHERE in info["spheres"]  # Trap Training: "gain proficiency with thieves' tools"
    tools = int(mods.get("DEX", 0)) + (int(info["pb"]) if proficient else 0) + (int(info["pb"]) if T + "TRAP_EXPERT" in owned or "tianxia.talent.trap.trap_expert" in owned else 0)
    out.append(ActionDefinition(
        source_definition_id=f"action:typed.{short}.disarm_trap", display_name="Disarm Trap", owner_id=actor_id, economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="CELL", range_ft=REACH_FT,
        parameters={"typed": {"effects": [{"type": "trap_disarm", "bonus": tools}], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 0, "player_only": True, "any_cell": True, "disarm_trap": True}))
    escape = max(_skill_bonus(sheet, "Athletics", mods.get("STR", 0)), _skill_bonus(sheet, "Acrobatics", mods.get("DEX", 0)))
    out.append(ActionDefinition(
        source_definition_id=f"action:typed.{short}.escape_net", display_name="Escape the net", owner_id=actor_id, economy=EconomyKind.ACTION,
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "trap_escape", "bonus": escape}], "numbers": numbers, "duration": {"kind": "instant"}, "riders": []},
                    "expected_damage": 1, "requires_condition": NETTED}))
    return out


@hook("button_description")
def contextual_description(row: dict[str, Any]) -> str | None:
    """Printed Disarming a Trap / Net rules for the universally available controls."""
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    for eff in effects:
        if eff.get("type") == "trap_disarm":
            return (f"Action: disarm a known trap within 5 feet. Make a Dexterity check using thieves' tools "
                    f"(1d20{int(eff.get('bonus') or 0):+d}) against its creator's Cultivation Save DC. "
                    "Success: it harmlessly falls apart. Failure: it stays armed; failing by 5 or more triggers it "
                    "if it can affect you. You always succeed on your own traps.")
        if eff.get("type") == "trap_escape":
            check = (f"{eff['check_skill']}" if eff.get("check_skill") else "Strength (Athletics) or Dexterity (Acrobatics), using your better bonus")
            return (f"Action: escape a net restraining you. Make a {check} check "
                    f"(1d20{int(eff.get('bonus') or 0):+d}) against the trap creator's "
                    "Cultivation Save DC. Success ends that net's Restrained condition on you; failure leaves you trapped.")
    return None


@hook("button_selection")
def setup_selection(parameters: dict[str, Any]) -> dict[str, Any] | None:
    pick = next((eff for eff in (parameters.get("typed") or {}).get("effects") or [] if eff.get("type") == "trap_setup_pick"), None)
    return {"condition": SETUP, "equals": {pick["field"]: pick.get("value")}} if pick else None


@effect("trap_setup_pick")
def setup_pick(ctx: Any, eff: dict[str, Any]) -> None:
    config = _config(ctx.actor)
    config[str(eff["field"])] = eff.get("value")
    config["label"] = _summary(config)
    ctx.engine._remove_condition(ctx.actor, SETUP, ctx.source)
    ctx.engine._apply_condition(ctx.actor, SETUP, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED", data=config)


def _summary(config: dict[str, Any]) -> str:
    form = FORMS.get(config.get("form") or "dart", FORMS["dart"])[0]
    parts = [form]
    if config.get("trigger"):
        parts.append(TRIGGERS[config["trigger"]][0])
    if config.get("deploy"):
        parts.append(DEPLOYS[config["deploy"]][0])
    return "Trap: " + ", ".join(parts) + f" (aim { {**AIMS, **AERIAL_AIMS}.get(config.get('aim') or 'auto', AIMS['auto'])[0]})"


def trap_configuration_allowed(engine, actor, kit):
    """Rigging is one Trigger; a second needs the active reviewed inheritance."""
    runtime = kit.get('runtime') or {}
    config = _config(actor)
    rigged = bool(runtime.get('aerial') and (config.get('aerial') or config.get('trigger') == 'aerial' or
                  (runtime.get('heaven_net') and config.get('form') in ('net', 'dart_net', 'terrain', 'terrain_now'))))
    return not (rigged and config.get('trigger') not in (None, 'aerial') and
                not (runtime.get('dual_trigger') and _state(engine, actor, EMPTY_ROAD) is not None))


# ------------------------------------------------------------------------------------------------------ which square
@hook("candidate_allowed")
def trap_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    aim = getattr(candidate, "destination", None)
    if params.get('trap_raised'):
        kit = _kit(engine, actor)
        if kit is None or not trap_configuration_allowed(engine, actor, kit):
            return False
        config = _config(actor)
        if config.get('deploy') in ('wielder', 'shield') or (config.get('aim') in AERIAL_AIMS and config.get('form') != 'falling_sky'):
            return False
        return bool(trap_aerial.raised_cells(engine, actor, include_ground=bool(params.get('trap_include_ground'))))
    if params.get("set_trap"):
        kit = _kit(engine, actor)
        if kit is not None and not trap_configuration_allowed(engine, actor, kit):
            return False
        if aim is None or _variant_allowed(engine, actor, aim, action) is False:
            return False
        runtime = params.get('trap_runtime') or {}
        config = _config(actor)
        if runtime.get('aerial') and (config.get('aerial') or (runtime.get('heaven_net') and config.get('form') in ('net', 'dart_net', 'terrain', 'terrain_now'))) and not trap_aerial.supported_cell(engine, aim):
            return False
        if config.get('aim') in AERIAL_AIMS and (not runtime.get('falling_sky') or config.get('form') != 'falling_sky'):
            return False
        if placed.at(engine, aim, "trap") and any(zone.owner_id == actor.entity_id for zone in placed.at(engine, aim, "trap")):
            return False  # "Two of your traps cannot occupy the same space"
        if _config(actor).get("deploy") == "wielder":
            # Trap Wielder: "place it directly in the space of one creature within your reach"
            return any(other.active and other.entity_id != actor.entity_id and engine._footprint_intersects(other, (aim,))
                       for other in engine.state.actors.values())
        if _config(actor).get("deploy") == "shield":
            # Trapped Shield: "set Dart Mechanism as an Action, attach that mechanism to a shield you wield" -- a Dart form, on yourself.
            if FORMS.get(_config(actor).get("form") or "dart", FORMS["dart"])[1] != "dart":
                return False
            if params.get('auto64_shield'):
                from ..armour import shield_bonus_earning
                if not shield_bonus_earning(engine, actor):
                    return False
            return placed.free_square(engine, aim)  # the square is only where the button points: the shield goes with you
        return placed.free_square(engine, aim)  # "an unoccupied space within your reach"
    if params.get("disarm_trap"):
        return aim is not None and any(_knows(zone, actor) for zone in placed.at(engine, aim, "trap"))
    if params.get('trap_warn_later'):
        return aim is not None and any(z.owner_id == actor.entity_id and placed.data(z).get('warning_choice')
                                       for z in placed.at(engine, aim, 'trap'))
    return None


def _warn_choices(engine, owner, intent, *, later=False, target_id=None):
    from ..target_knowledge import can_see
    from ..typed_executor import cant_hear, condition_rules
    from .needle import ask, checkpoint_id, CHOICE
    targets = [a for a in engine.state.actors.values() if a.active and (later or can_see(engine, owner, a))
               and (not later or (can_see(engine, a, owner) and not cant_hear(a)
                                  and not any(r.get('cant_speak') for r in condition_rules(owner))))]
    if not targets:
        return []
    # Automatic protection is a hard side filter. Manual owners retain the
    # printed freedom to warn an enemy; preferences alone never enroll one.
    if _automatic_owner(engine, owner):
        targets = [a for a in targets if a.team_id == owner.team_id]
    if not targets:
        return []
    return ask(engine, intent, checkpoint_id(engine,'trap_warn_later' if later else 'trap_warn',owner.entity_id,target_id), owner,
        CHOICE+'trap_warn_later' if later else CHOICE+'trap_warn', [a.entity_id for a in targets],
        labels={a.entity_id:f'Warn {a.display_name}: safe from this trap unless it chooses to trigger it' for a in targets},
        minimum=0, maximum=_warn_maximum(engine, owner, targets), allow_decline=True,
        preferred=[a.entity_id for a in targets if a.team_id==owner.team_id], name='Warning Trigger',
        automatic=_automatic_owner(engine, owner),
        prompt='Warning Trigger: choose any creatures to warn about this trap. No action or resource cost; the warning lasts until this trap ends.')


def _automatic_owner(engine: Any, owner: Any) -> bool:
    from .needle import answerable
    return not answerable(engine, owner)


def _warn_maximum(engine: Any, owner: Any, targets: list[Any]) -> int:
    """How many creatures an automatic Warning Trigger answer may warn.

    A warned creature is safe: it may decline to trigger the trap. The automatic controller answers by taking
    every option up to ``maximum`` (combat/gate4_controller.py ``choose_reaction``: ``ordered[:maximum]``), so
    ``maximum`` is what decides what an unanswered warning protects. At every visible creature it therefore made
    the owner's enemies safe too -- the trap stopped working against whoever it was set for. The owner's own side
    keeps the whole list to choose from: it is the owner who decides whether a warning is ever worth spending on
    an enemy. Only the automatic answer is narrowed, and only to the owner's allies (AUTO131r1f1)."""
    return len(targets) if not _automatic_owner(engine, owner) else sum(a.team_id == owner.team_id for a in targets)


@effect('trap_warn_later')
def warn_later(ctx, row):
    cell = getattr(ctx.intent,'destination',None)
    if cell is None:
        return
    for zone in placed.at(ctx.engine,cell,'trap'):
        if zone.owner_id==ctx.actor.entity_id and placed.data(zone).get('warning_choice'):
            chosen = _warn_choices(ctx.engine,ctx.actor,ctx.intent,later=True,target_id=zone.zone_id)
            if chosen:
                placed.update(ctx.engine,zone,warned=sorted(set(placed.data(zone).get('warned') or [])|set(chosen)))


def _knows(zone: Any, creature: Any) -> bool:
    d = placed.data(zone)
    return zone.owner_id == creature.entity_id or creature.entity_id in (d.get("aware") or ())


# ---------------------------------------------------------------------------------------------------------- setting one
@effect("trap_place")
def trap_place(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    cell = getattr(ctx.intent, "destination", None)
    kit = _kit(engine, owner)
    if cell is None or kit is None:
        ctx.rider("Set Trap: no square was chosen.")
        return
    config = _config(owner)
    zone = _set(engine, owner, ctx.action, ctx.intent, kit, cell, config)
    _after_variant(ctx, kit, cell, config, zone)


@effect('trap_raised_place')
def trap_raised_place(ctx: Any, eff: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id, CHOICE
    kit = _kit(ctx.engine, ctx.actor)
    if kit is None or not kit.get('runtime'):
        return
    cells = {f'cell:{p.x},{p.y},{p.z}': p for p in trap_aerial.raised_cells(
        ctx.engine, ctx.actor, include_ground=bool(eff.get('include_ground')))}
    from .. import senses
    foes = [a for a in ctx.engine.state.actors.values() if a.active and a.team_id != ctx.actor.team_id
            and senses.perceives(ctx.engine, ctx.actor, a)]
    preferred = sorted(cells, key=lambda k: (min((ctx.engine._distance_actor_to_cell(a, cells[k]) for a in foes), default=0),
                                            ctx.engine._distance_actor_to_cell(ctx.actor, cells[k]), k))[:1]
    chosen = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'trap_raised_space', ctx.actor.entity_id),
        ctx.actor, CHOICE + 'trap_raised_space', list(cells),
        labels={k: f'Set your trap at ({p.x}, {p.y}), {p.z * 5} feet above ground' for k, p in cells.items()},
        preferred=preferred, name='Set Trap: choose a space' if eff.get('include_ground') else 'Set Trap on a raised surface',
        prompt='Set Trap: choose a visible supported space within 5 feet for your configured physical device. '
               'This costs your Action and one Martial Focus; the trap lasts 1 minute or until triggered.')
    if chosen:
        _set(ctx.engine, ctx.actor, kit['action'], ctx.intent, kit, cells[chosen[0]], _config(ctx.actor))


def _set(engine: Any, owner: Any, action: Any, intent: Any, kit: dict[str, Any], cell: Any, config: dict[str, Any]) -> Any:
    from ..typed_executor import Context

    form_key = config.get("form") or "dart"
    label, pattern, _talent, dtype = FORMS.get(form_key, FORMS["dart"])
    trigger, deploy = config.get("trigger"), config.get("deploy")
    if deploy == "shield":
        cell = owner.position  # "attach that mechanism to a shield you wield instead of placing it on a surface"
    numbers = kit["numbers"]
    if trigger == 'aerial' and (kit.get('runtime') or {}).get('aerial'):
        config = {**config, 'aerial': 1}
    trigger_keys = [trigger] if trigger else []
    road_choices = bool((kit.get('runtime') or {}).get('dual_trigger') and _state(engine, owner, EMPTY_ROAD) is not None)
    if road_choices:
        # Aerial Rigging is itself a Trigger Talent, including mandatory
        # Heaven-Net rigging; it consumes one of the inheritance's two slots.
        aerial = bool((kit.get('runtime') or {}).get('aerial') and (config.get('aerial') or
                      ((kit.get('runtime') or {}).get('heaven_net') and form_key in ('net', 'dart_net', 'terrain', 'terrain_now'))))
        if aerial and 'aerial' not in trigger_keys:
            trigger_keys.append('aerial')
        from .needle import ask, checkpoint_id, CHOICE
        extra = [key for key, (_, talent) in TRIGGERS.items() if talent in kit['owned'] and key not in trigger_keys
                 and (key != 'aerial' or (kit.get('runtime') or {}).get('aerial'))
                 and (key != 'within' or not config.get('within_child'))]
        if extra and len(trigger_keys) < 2:
            chosen = ask(engine, intent, checkpoint_id(engine, 'trap_second_trigger', owner.entity_id,
                         f'{cell.x},{cell.y},{cell.z}'), owner, CHOICE + 'trap_second_trigger', ['none', *extra],
                         labels={'none': 'No additional Trigger talent', **{k: TRIGGERS[k][0] for k in extra}},
                         preferred=[extra[0]], name='The Empty Road Was Never Empty',
                         maximum=2 - len(trigger_keys),
                         prompt=('The Empty Road Was Never Empty: choose one additional compatible Trigger talent' if trigger_keys else
                                 'The Empty Road Was Never Empty: choose up to two compatible Trigger talents') +
                                ' for this trap, or none. These mechanisms share this physical device; a rigged lattice already uses one Trigger slot. '
                                'No extra Martial Focus, action or other resource cost.', prompt_context={'cost': 'None'})
            trigger_keys.extend(k for k in chosen if k != 'none')
        if 'aerial' in trigger_keys:
            config = {**config, 'aerial': 1}
    mine = placed.of(engine, "trap", owner_id=owner.entity_id)
    while len(mine) >= _limit(kit, engine, owner):
        placed.drop(engine, mine.pop(0), "TRAP_LIMIT")  # "choose one older temporary trap to harmlessly fall apart"
    vector = _vector(engine, owner, cell, config.get("aim") or "auto", modern=bool(kit.get('runtime')),
                     spatial=form_key == 'falling_sky')
    sees = [other for other in engine.state.actors.values() if other.active and other.entity_id != owner.entity_id
            and engine._line_of_sight_actor_to_cell(other, cell)]
    aware = [other.entity_id for other in sees]
    if deploy == "sneaky":
        aware = [other.entity_id for other in sees if not _unnoticed(engine, owner, other)]
    warned: list[str] = []
    if 'warning' in trigger_keys:
        # "designate any number of creatures you can see and warn": the default is every ally that sees it (and yourself).
        warned = [owner.entity_id, *[other.entity_id for other in sees if other.team_id == owner.team_id]]
        if (kit['action'].parameters or {}).get('auto64_warning'):
            warned = _warn_choices(engine,owner,intent)
    zid = placed.new_id(engine, owner, "trap")
    shield = deploy == "shield"
    profile, aerial = trap_aerial.placement(engine, kit, cell, config)
    corner = _corner(engine, owner, cell, modern=bool(kit.get('runtime')))
    if pattern == 'terrain' and aerial.get('heaven_net'):
        from .needle import ask, checkpoint_id, CHOICE
        corners = {'nw': (cell.x, cell.y), 'ne': (cell.x + 1, cell.y),
                   'sw': (cell.x, cell.y + 1), 'se': (cell.x + 1, cell.y + 1)}
        chosen = ask(engine, intent, checkpoint_id(engine, 'trap_terrain_corner', owner.entity_id, zid),
            owner, CHOICE + 'trap_terrain_corner', list(corners),
            labels={key: f'Terrain centered on the {key.upper()} corner of this trap space' for key in corners},
            preferred=[next(key for key, value in corners.items() if value == corner)], name='Terrain Trap',
            prompt='Terrain Trap: choose the corner of this trap space to center its 10-foot-radius difficult area. '
                   'Heaven-Net extends it through the rigging height. The field lasts 1 minute after triggering; '
                   'this corner choice costs no extra action or resource.')
        if chosen:
            corner = corners[chosen[0]]
    where = f", aimed { {**AIMS, **AERIAL_AIMS}[config.get('aim') or 'auto'][0]}" if pattern.startswith("dart") and form_key != "aimed" and not shield else ""
    zone = placed.place(
        engine, owner, source=action.source_definition_id, tag="trap", cells=cell, zone_id=zid, numbers=numbers, duration_rounds=LIFE_ROUNDS,
        name=f"{owner.display_name}'s trap: {label}{' on a shield' if shield else ''}{where}",
        color="#9a7b4f", material="generic", anchor_id=owner.entity_id if shield else None, follows_owner=shield,
        difficult='all' if aerial.get('heaven_net') and pattern != 'terrain' else None, extra=profile,
        triggers=[] if shield else [{"id": f"trap:{zid}", "name": label, "on": ["enter"], "who": "any",
                                     "effects": [{"type": "placed_trap_fire", "zone_id": zid}]}],
        placed={"form": form_key, "pattern": pattern, "trigger": trigger, "deploy": deploy, "dir": list(vector), "aimed": form_key == "aimed",
                "damage_type": dtype, "aware": aware, "warned": warned, "false_used": False, "walk_through": not shield, "shield": shield,
                "corner": list(corner), "cl": int(numbers.get("cl") or 1), "pb": int(numbers.get("pb") or 2),
                **aerial, **({'physical_3d': 1} if kit.get('runtime') else {}),
                **({'triggers': trigger_keys} if road_choices else {}),
                **({'falling_sky': 1} if form_key == 'falling_sky' and (kit.get('runtime') or {}).get('falling_sky') else {})})
    flags = {}
    if 'warning' in trigger_keys and (kit['action'].parameters or {}).get('auto64_warning'):
        flags['warning_choice']=1
    if shield and (kit['action'].parameters or {}).get('auto64_shield'):
        flags['shield_choice']=1
    if flags:
        placed.update(engine,zone,**flags)
    placed.note(engine, action.source_definition_id, owner, f"{owner.display_name} set a trap ({label}) at ({cell.x}, {cell.y})"
                + (": it triggers at once." if deploy == "wielder" or form_key == "terrain_now" else "."))
    if deploy == "wielder":
        victims = [other for other in engine.state.actors.values() if other.active and other.entity_id != owner.entity_id
                   and engine._footprint_intersects(other, (cell,))]
        typed = {"effects": [], "numbers": numbers, "weapon": None, "duration": {"kind": "instant"}, "riders": [], "source": f"trap:{zid}"}
        for victim in victims:
            _spring(Context(engine, owner, action, intent, typed, [victim], victim, {}), zone, victim, immediate=True)
    elif form_key == "terrain_now":
        typed = {"effects": [], "numbers": numbers, "weapon": None, "duration": {"kind": "instant"}, "riders": [], "source": f"trap:{zid}"}
        _spring(Context(engine, owner, action, intent, typed, [owner], owner, {}), zone, owner, immediate=True)
    return zone


def _vector(engine: Any, owner: Any, cell: Any, aim: str, *, modern: bool = False, spatial: bool = False) -> tuple:
    if aim in AERIAL_AIMS:
        return AERIAL_AIMS[aim][1]
    vector = AIMS.get(aim, AIMS["auto"])[1]
    if vector is not None:
        return vector
    foes = [other for other in engine.state.actors.values() if other.active and other.team_id != owner.team_id]
    if modern:
        from ..senses import perceives
        foes = [other for other in foes if perceives(engine, owner, other)]
    if foes:
        near = min(foes, key=lambda other: (engine.grid.distance_ft(cell, other.position), other.entity_id))
        dx, dy = near.position.x - cell.x, near.position.y - cell.y
        if spatial:
            vector = (dx, dy, near.position.z - cell.z)
            return vector if any(vector) else (1, 0, 0)
    else:
        dx, dy = cell.x - owner.position.x, cell.y - owner.position.y  # away from you
    return (dx, dy) if (dx, dy) != (0, 0) else (1, 0)


def _unnoticed(engine: Any, owner: Any, observer: Any) -> bool:
    """Sneaky Trapper: "make a Dexterity (Sleight of Hand) check contested by each observer's Passive Perception. On a success against
    an observer, that observer does not automatically notice you setting the trap.\""""
    from .eye_common import passive_perception
    from .tabik_scoundrel import skill

    bonus = skill(engine, owner, "Sleight of Hand", _mod(owner.dexterity_score))
    roll = engine.roll_check(
        modifier=bonus,
        actor_id=owner.entity_id,
        reason='CHECK:trap.sneaky_trapper:SLEIGHT_OF_HAND',
        ability='DEX',
        skill='Sleight of Hand',
    )
    engine._record_roll(roll)
    dc = passive_perception(engine, observer, owner)
    engine._append_event("CHECK_ROLLED", "trap:sneaky_trapper", actor_id=owner.entity_id, target_ids=(observer.entity_id,),
                         payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc, "skill": "Sleight of Hand"})
    return roll.total >= dc


# -------------------------------------------------------------------------------------------------------------- springing
@effect("placed_trap_fire")
def trap_fire(ctx: Any, eff: dict[str, Any]) -> None:
    zone = ctx.engine.state.zones.get(str(eff.get("zone_id")))
    creature = ctx.target
    if zone is None or not zone.active or creature is None or not creature.active:
        return
    _spring(ctx, zone, creature)


def _spring(ctx: Any, zone: Any, creature: Any, *, immediate: bool = False, chained: bool = False) -> None:
    engine, owner = ctx.engine, ctx.actor
    d = placed.data(zone)
    label = FORMS.get(d.get("form"), FORMS["dart"])[0]
    pattern = d.get("pattern")
    if not immediate or 'triggers' in d:
        if creature.entity_id in (d.get("warned") or ()):
            if not d.get('warning_choice'):
                return
            if not _ask(engine,ctx.intent,creature,'trap_warned_trigger',{'use':f'Trigger {owner.display_name}\'s {label}'},
                        f'Warning Trigger: you were warned about {owner.display_name}\'s {label}. Trigger it as you enter? No extra action or resource cost.',
                        'Warning Trigger',[],automatic=False):
                return
        if _spared(engine, owner, zone, creature, d):
            return  # Court of the Hidden Nail / The Empty Road: "your warned allies do not trigger your traps"
        if pattern == "tripwire" and any(c.condition_id == "condition:typed.prone" for c in creature.conditions.values()):
            return  # "A creature that already has the Prone condition does not trigger Tripwire."
        if 'false' in d.get('triggers', [d.get('trigger')]) and not d.get("false_used"):
            placed.update(engine, zone, false_used=True)
            placed.note(engine, zone.source_definition_id, owner, f"{creature.display_name} triggered the {label}: it only clicks (False Trigger) -- "
                        "a warning, nothing fires; the next trigger is dangerous.", targets=(creature,))
            _trap_within(ctx, zone, d)
            return
    second = bool(d.get("false_used"))
    placed.note(engine, zone.source_definition_id, owner, f"{creature.display_name} sprang {owner.display_name}'s {label}.", targets=(creature,))
    ctx = _with_source(ctx, f"trap:{zone.zone_id}")
    # A trap is one general kind of delivery (combat/ext/damage_delivery.py), so a printed "damage
    # from a trap" limit can answer this and not a sword. The Dart Mechanism resolves a native
    # attack and the snare forms a typed save, both outside the typed executor's own frame, so the
    # trap says so here. Transient and restored; nothing is journalled or stored.
    with delivery.delivering(engine, f"trap:{zone.zone_id}", hazard=delivery.TRAP, area=zone.zone_id):
        hurt = _run_pattern(ctx, zone, d, creature, second)
    _recover_focus(ctx, hurt)
    if pattern != "tripwire" or immediate:
        placed.drop(engine, zone, "TRIGGERED")  # "Unless a talent says otherwise, a trap is destroyed after it triggers."
    if 'chained' in d.get('triggers', [d.get('trigger')]) and not chained and owner.active:
        _chain(ctx, zone, creature)
    _after_spring(ctx, zone, creature)


def _with_source(ctx: Any, source: str) -> Any:
    from ..typed_executor import Context

    typed = {**ctx.typed, "source": source}
    return Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, typed, list(ctx.targets), ctx.target, ctx.damage_cache)


def _run_pattern(ctx: Any, zone: Any, d: dict[str, Any], creature: Any, second: bool) -> bool:
    """Runs the pattern; returns whether a creature failed its save or took damage (Trapper's Recovery)."""
    engine, owner = ctx.engine, ctx.actor
    pattern, form = d.get("pattern"), d.get("form")
    if pattern == "dart":
        return _dart(ctx, zone, d, creature, second)
    if pattern == "dart_net":
        target = _dart_target(engine, zone, d, creature)
        return bool(target) and _snare(ctx, zone, d, [target], "net", second)
    if pattern in ("tripwire", "net", "noose"):
        return _snare(ctx, zone, d, [creature], "razor" if form == "razor" else pattern, second)
    if pattern == "flash":
        spaces = trap_aerial.threat_cells(zone) if d.get('aerial') else zone.affected_cells
        near = [other for other in engine.state.actors.values() if other.active and any(
            engine.grid.distance_ft(other.position, cell) <= 5 for cell in spaces)]
        return _snare(ctx, zone, d, near, "flash", second)
    if pattern == "alarm":
        placed.note(engine, zone.source_definition_id, owner, "A loud noise rings out, audible within 300 feet (Alarm Trap).", targets=(creature,))
        return False
    if pattern == "terrain":
        _terrain(ctx, zone, d)
    return False


# --- Dart Mechanism
def _line(engine: Any, zone: Any, d: dict[str, Any]) -> list[Any]:
    """The squares the dart crosses: from its origin square in the direction fixed when it was set, "up to 90 feet", stopping at "the
    first solid surface"."""
    from ..gate2_runtime_models import Position

    if d.get('falling_sky') or d.get('physical_3d'):
        from ..space import point, position, effect_ray
        origin = zone.affected_cells[0]
        vector = tuple(d.get('dir') or (1, 0, 0))
        if len(vector) == 2:
            vector = (*vector, 0)
        scale = max(map(abs, vector)) or 1
        end = tuple(v + round((DART_RANGE_FT // 5) * delta / scale) for v, delta in zip(point(origin), vector))
        path = []
        for voxel in effect_ray(origin, end)[1:]:
            if min(voxel) < 0:
                break
            cell = position(voxel)
            if not engine.grid.volume_legal(cell):
                break
            path.append(cell)
        return path

    ox, oy = zone.affected_cells[0].x, zone.affected_cells[0].y
    dx, dy = d.get("dir") or (1, 0)
    steps = max(abs(dx), abs(dy)) or 1
    out = []
    for k in range(1, DART_RANGE_FT // 5 + 1):
        x, y = ox + round(k * dx / steps), oy + round(k * dy / steps)
        if not engine.grid.in_bounds((x, y)) or (x, y) in engine.grid.blocked:
            break
        out.append(Position(x=x, y=y))
    return out


def _dart_target(engine: Any, zone: Any, d: dict[str, Any], trigger: Any) -> Any | None:
    if d.get("aimed"):
        return trigger  # Aimed Shot: "target the creature that triggers the trap instead of firing along a fixed line"
    for cell in _line(engine, zone, d):
        for other in engine.state.actors.values():
            if other.active and ((cell.x, cell.y, cell.z) in engine._actor_volume(other)
                                 if d.get('falling_sky') or d.get('physical_3d') else engine._footprint_intersects(other, (cell,))):
                return other  # "The projectile stops at the first solid surface or creature in its path."
    return None


def _dart(ctx: Any, zone: Any, d: dict[str, Any], trigger: Any, second: bool) -> bool:
    engine, owner = ctx.engine, ctx.actor
    target = _dart_target(engine, zone, d, trigger)
    if target is None:
        placed.note(engine, zone.source_definition_id, owner, "The dart flies out along its line and strikes nothing.")
        return False
    hurt = shoot(engine, owner, ctx, zone, d, target, second)
    if d.get("form") == "blunt":
        _blunt_knockout(ctx, zone, target)
    return hurt


def shoot(engine: Any, owner: Any, ctx: Any, zone: Any, d: dict[str, Any], target: Any, second: bool) -> bool:
    """One dart at one creature: "make a ranged Cultivation Attack against that creature. Hit: Deal Piercing damage" (Dart
    Mechanism); False Trigger's second trigger has Advantage on the roll."""
    from ..paid_relocation import preserve_pending
    preserve_pending(engine, "_typed_pending_attack")
    preserve_pending(engine, "_typed_negated")
    from ..gate2_runtime_models import DiceSpec
    from .. import typed_reactions

    numbers = ctx.numbers or {}
    form = d.get("form")
    count = placed.cl_row(int(d.get("cl") or numbers.get("cl") or 1), DICE_BY_CL)
    spec = {"attack_bonus": int(numbers.get("attack_bonus") or 0), "range_ft": DART_RANGE_FT,
            "damage": DiceSpec(count=count, sides=DART_SIDES.get(form, 6), modifier=0), "damage_type": d.get("damage_type") or "PIERCING", "parameters": {}}
    if second:
        engine._add_modifier(owner, zone.source_definition_id, "attack_mode", "SET", "ADVANTAGE", "NEXT_ATTACK", expires_on="CONSUMED")
    engine._typed_pending_attack = {"attacker": owner.entity_id, "target": target.entity_id, "bonus": spec["attack_bonus"], "reach": DART_RANGE_FT}
    if target.entity_id in getattr(engine, "typed_actor_ids", set()):
        typed_reactions.on_attacked(engine, owner, target, spec, ctx.intent)
    engine._typed_pending_attack = None
    negated = getattr(engine, "_typed_negated", set())
    if (owner.entity_id, target.entity_id) in negated:
        engine._typed_negated = negated - {(owner.entity_id, target.entity_id)}
        return False
    before = _hp(target)
    previous = getattr(engine, "_typed_pending_damage_type", None)
    engine._typed_pending_damage_type = spec["damage_type"]
    try:
        from .attack_defenses import resolving_defenses
        with resolving_defenses(engine, spec):
            hit = engine._resolve_attack_spec(owner, target, spec, ctx.intent, source_definition_id=zone.source_definition_id, attack_index=1)
    finally:
        engine._typed_pending_damage_type = previous
    if target.entity_id in getattr(engine, "typed_actor_ids", set()):
        typed_reactions.on_attack_resolved(engine, owner, target, spec, ctx.intent)
        if not hit and target.active:
            typed_reactions.on_attack_missed(engine, owner, target, spec, ctx.intent)
    if hit and d.get('falling_sky'):
        trap_aerial.falling_sky(ctx, zone, target)
    return bool(hit) and _hp(target) < before


def _hp(creature: Any) -> int:
    return int(getattr(creature, "current_hp", 0) or 0) + int(getattr(creature, "temporary_hp", 0) or 0)


# --- Tripwire, Net, Noose, Razor Wire, Flash Trap: a Dexterity save
def _snare(ctx: Any, zone: Any, d: dict[str, Any], victims: list[Any], kind: str, second: bool) -> bool:
    from ..typed_executor import run_effects

    engine, owner = ctx.engine, ctx.actor
    if not victims:
        return False
    fail: list[dict[str, Any]]
    if kind in ("tripwire", "razor"):
        fail = [{"type": "condition", "condition": "prone", "applies_to": "target", "evidence": "Failed Save: The creature has the Prone condition."}]
        if kind == "razor":
            count = placed.cl_row(int(d.get("cl") or 1), DICE_BY_CL)
            fail.append({"type": "damage", "applies_to": "target", "dice": {"count": count, "sides": 6}, "flat": 0, "formula": "none",
                         "damage_types": ["slashing"], "evidence": "Razor Wire: Slashing damage to a creature that fails its saving throw."})
    elif kind == "flash":
        fail = [{"type": "condition", "condition": "blinded", "applies_to": "target", "evidence": "Failed Save: The creature has the Blinded condition until the end of its next turn."}]
    else:  # net, noose
        fail = [{"type": "condition", "condition": "restrained", "applies_to": "target", "until_escape": True,
                 "hold_kind": "ordinary_physical",
                 "evidence": "Failed Save: The creature has the Restrained condition until it escapes or the net is destroyed."},
                {"type": "trap_netted", "noose": kind == "noose", "zone_id": zone.zone_id}]
        if d.get('aerial'):
            fail.insert(0, {'type': 'trap_anchor_pull', 'zone_id': zone.zone_id})
            if d.get('heaven_net'):
                fail[1]['condition_data'] = {'flight_suspended': 1}
    aware_effect = [{"type": "trap_aware", "zone_id": zone.zone_id}] if kind in ("tripwire", "razor") else []
    typed = {**ctx.typed, "source": f"trap:{zone.zone_id}"}
    cache: dict[Any, Any] = {}
    cache["_trap_existing_holds"] = {victim.entity_id: set(victim.conditions) for victim in victims}
    subject_ctx = placed.context(engine, owner, typed["source"], ctx.numbers, victims, action=ctx.action)
    subject_ctx.intent, subject_ctx.typed, subject_ctx.damage_cache = ctx.intent, typed, cache
    before = {victim.entity_id: _hp(victim) for victim in victims}
    run_effects(subject_ctx, [{"type": "save", "ability": "dex", "on_fail": fail, "on_success": aware_effect}])
    # Trapper's Recovery: "fails a saving throw against one of your traps or takes damage from one of your traps".
    return bool(cache.get("_trap_failed")) or any(_hp(victim) < before[victim.entity_id] for victim in victims)


@hook("after_save")
def save_failed_against_trap(ctx: Any, subject: Any, ability: str, named: set[str], failed: bool) -> None:
    if failed and str(ctx.typed.get("source") or "").startswith("trap:"):
        ctx.damage_cache.setdefault("_trap_failed", []).append(subject.entity_id)


@effect("trap_aware")
def trap_aware(ctx: Any, eff: dict[str, Any]) -> None:
    zone = ctx.engine.state.zones.get(str(eff.get("zone_id")))
    if zone is None or not zone.active or ctx.target is None:
        return
    d = placed.data(zone)
    if ctx.target.entity_id not in (d.get("aware") or ()):
        placed.update(ctx.engine, zone, aware=[*(d.get("aware") or ()), ctx.target.entity_id])  # "Successful Save: ... becomes aware of the trap"


@effect("trap_netted")
def trap_netted(ctx: Any, eff: dict[str, Any]) -> None:
    subject = ctx.target
    if subject is None or not any(c.condition_id == "condition:typed.restrained" and c.source_actor_id == ctx.actor.entity_id for c in subject.conditions.values()):
        return  # something stopped the Restrained condition from landing
    from . import run

    tracked = {}
    if any(run("hold_tracking", ctx.engine, subject)):
        before = ctx.damage_cache.get("_trap_existing_holds", {}).get(subject.entity_id, set())
        holds = [iid for iid, c in subject.conditions.items() if iid not in before
                 and c.condition_id == "condition:typed.restrained"
                 and c.source_actor_id == ctx.actor.entity_id and c.source_definition_id == ctx.source]
        if len(holds) != 1:
            return  # prevention must not attach a marker to a pre-existing restraint
        tracked = {"hold_id": holds[0]}
    if not tracked:
        ctx.engine._remove_condition(subject, NETTED, ctx.source)
    ctx.engine._apply_condition(subject, NETTED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"dc": int(ctx.numbers.get("save_dc") or 10), "noose": bool(eff.get("noose")),
                                      "label": "Held by a noose (cannot speak or breathe normally)" if eff.get("noose") else "Caught in a net",
                                      **tracked})
    if eff.get("noose"):
        # "While Restrained by this noose, it also cannot speak, supply Verbal components, or breathe normally": Silenced
        # (combat/speech.py) for as long as the noose's own Restrained lasts (linked_holds releases it with that hold).
        hold = tracked.get("hold_id") or max((iid for iid, c in subject.conditions.items() if c.condition_id == "condition:typed.restrained"
                                              and c.source_actor_id == ctx.actor.entity_id and c.source_definition_id == ctx.source),
                                             key=lambda iid: subject.conditions[iid].applied_sequence, default=None)
        if hold is not None:
            ctx.engine._apply_condition(subject, SILENCED, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                        data={"parent_hold": hold, "label": "Noose: cannot speak or supply Verbal components while held"})
    zone = ctx.engine.state.zones.get(eff.get('zone_id'))
    if zone is not None and placed.data(zone).get('heaven_net'):
        hold = next((iid for iid, c in reversed(list(subject.conditions.items()))
                     if c.condition_id == 'condition:typed.restrained' and c.source_actor_id == ctx.actor.entity_id
                     and c.source_definition_id == ctx.source), None)
        if hold is not None:
            trap_aerial.held_lattice(ctx, zone, subject, hold)


def net_bond(engine: Any, condition: Any) -> bool:
    """Whether this row is one of this plug-in's own nets or nooses: the trapper's Set Trap action owns it.

    Pure classification from the compiled action, never from the condition's name. Shared by the source
    classification and the companion cleanup below; reads catalogs and fight state and changes nothing.
    """
    action = engine.action_catalog.get(condition.source_definition_id)
    return bool(action is not None and action.parameters.get("set_trap")
                and action.owner_id == condition.source_actor_id)


@hook("hold_source")
def net_hold_source(engine: Any, condition: Any):
    """Only an exactly linked Net/Noose pair establishes this physical restraint's source."""
    if not net_bond(engine, condition):
        return None
    action = engine.action_catalog.get(condition.source_definition_id)
    for actor in engine.state.actors.values():
        for marker in actor.conditions.values():
            if marker.condition_id != NETTED or not marker.data.get("hold_id"):
                continue
            hold = actor.conditions.get(marker.data["hold_id"])
            if (hold is not None and hold.condition_id == "condition:typed.restrained"
                    and hold.source_actor_id == marker.source_actor_id == condition.source_actor_id
                    and hold.source_definition_id == marker.source_definition_id == condition.source_definition_id
                    and (condition is hold or condition is marker)):
                level = (action.parameters.get("typed", {}).get("numbers") or {}).get("cl")
                return True, int(level) if level is not None else None
    return None


def _untracked_net_markers(engine: Any, actor: Any, key: str, condition: Any) -> list[str] | None:
    """The ``netted`` markers of an unlinked net or noose: the restraint's own trapper and own trap.

    A restraint compiled before hold tracking, or one whose Restrained row landed without a link, carries
    its marker beside it with no ``hold_id``, so the tracked pair above cannot see it: ending the restraint
    left "Caught in a net" and the Escape the net action on the creature. Matching on the exact source --
    the same test ``life_riders._trap_bond`` uses to classify the bond -- makes the marker end with its
    restraint, and only that marker does: another restraint of another kind, another trap, or another
    trapper contributes nothing, so unrelated holds survive. Restraint to marker only, which is the
    direction every ``physical_holds.end_hold`` caller ends; the tracked branch above keeps its own pair.
    """
    if condition is None or condition.condition_id != "condition:typed.restrained" or not net_bond(engine, condition):
        return None
    return [iid for iid, marker in actor.conditions.items() if iid != key and marker.condition_id == NETTED
            and not marker.data.get("hold_id")
            and marker.source_actor_id == condition.source_actor_id
            and marker.source_definition_id == condition.source_definition_id]


@hook("hold_companions")
def net_hold_companions(engine: Any, actor: Any, key: str):
    condition = actor.conditions.get(key)
    if condition is None or not net_hold_source(engine, condition):
        return _untracked_net_markers(engine, actor, key, condition)
    return [iid for iid, marker in actor.conditions.items() if marker.condition_id == NETTED
            and marker.data.get("hold_id") == key] if condition.condition_id != NETTED else [condition.data["hold_id"]]


@hook("choice_options")
def net_escape_options(engine, intent, checkpoint, reactor_id, choice_id, context):
    if choice_id != "choice:trap.escape_net" or not context.get("trap_escape_holds"):
        return None
    return {"option_ids": context["trap_escape_holds"], "minimum_selections": 1,
            "maximum_selections": 1, "allow_decline": False, "automatic_use": True}


@hook("escape_grips")
def choose_net_escape(ctx: Any, grips: dict):
    """Tracked physical nets are individual holds even after an escape benefit expires."""
    from . import run

    if not grips or not all(c.condition_id == NETTED and net_hold_source(ctx.engine, c) for c in grips.values()):
        return None  # untracked old bundles keep their aggregate escape
    if len(grips) == 1:
        return list(grips)
    from .escape_checks import escape_hook_modes

    eff = next((e for e in ctx.typed.get("effects", []) if e.get("type") == "trap_escape"), {})
    ordered = sorted(grips, key=lambda iid: "ADVANTAGE" not in escape_hook_modes(
        ctx.engine, ctx.actor, [grips[iid]], eff.get("check_ability"), eff.get("check_skill")))
    decision = ctx.engine._reaction_decision(
        ctx.intent, f"TRAP_ESCAPE:{ctx.source}:{ctx.actor.entity_id}", ctx.actor.entity_id, "choice:trap.escape_net",
        context={"actor_id": ctx.actor.entity_id, "target_id": ctx.actor.entity_id, "trap_escape_holds": ordered,
                 "labels": {iid: f"{c.data.get('label', 'Net')} from "
                                 f"{getattr(ctx.engine.state.actors.get(c.source_actor_id), 'display_name', c.source_actor_id)}: "
                                 f"{ctx.engine.action_catalog[c.source_definition_id].display_name}"
                            for iid, c in grips.items()},
                 "prompt": f"Net / Noose: {ctx.action.display_name} by {ctx.actor.display_name}; choose the restraint affecting them to escape."})
    return list(decision.option_ids) if decision is not None else [ordered[0]]


@effect("trap_escape")
def trap_escape(ctx: Any, eff: dict[str, Any]) -> None:
    """"A Restrained creature may take the Utilize Action to make a Strength (Athletics) or Dexterity (Acrobatics) check against
    your Cultivation Save DC, ending the condition on itself on a success." (Net)"""
    from . import run
    from .physical_holds import end_hold
    from .scoped_checks import escape_modes, escape_skill_metadata
    from .escape_checks import escape_hook_modes

    engine, actor = ctx.engine, ctx.actor
    held = [(iid, c) for iid, c in actor.conditions.items() if c.condition_id == NETTED]
    if not held:
        return
    available = dict(held)
    selections = [answer for answer in run("escape_grips", ctx, available) if answer is not None]
    scoped = (len(selections) == 1 and isinstance(selections[0], (list, tuple)) and bool(selections[0])
              and all(isinstance(iid, str) and iid in available for iid in selections[0])
              and len(set(selections[0])) == len(selections[0]))
    if scoped:
        held = [(iid, available[iid]) for iid in selections[0]]
    dc = max(int((c.data or {}).get("dc") or 10) for _, c in held)
    from .escape_checks import choose_escape_check, resolve_escape_check
    selected = None if eff.get("check_ability") else choose_escape_check(
        ctx, {**eff, "escape_check_choices": ctx.typed.get("escape_check_choices")}, dc,
        [c for _, c in held], ("restrained",))
    if selected:
        success = resolve_escape_check(ctx, {**eff, "bonus": selected["bonus"]}, dc,
            [c for _, c in held], tuple(selected.get("hazards", ("restrained",))),
            check_name="Escape", check_ability=selected["ability"], check_skill=selected["skill"], escape_hooks=scoped)
    else:
        modes = escape_modes(actor, eff, ("restrained",), engine=engine)
        if scoped:
            modes.update(escape_hook_modes(engine, actor, [c for _, c in held],
                                           eff.get("check_ability"), eff.get("check_skill")))
        roll = engine.roller.d20(modifier=int(eff.get("bonus") or 0), actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}",
                                 mode=modes.pop() if len(modes) == 1 else "NORMAL")
        engine._record_roll(roll)
        success = roll.total >= dc
        engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "check": "Escape", **escape_skill_metadata(eff)})
    if success:
        if scoped:
            for iid, _ in held:
                end_hold(ctx, iid)
            placed.note(engine, ctx.source, actor, f"{actor.display_name} got out of the net.")
            return
        for _iid, condition in held:
            for iid, other in list(actor.conditions.items()):
                if other.condition_id == "condition:typed.restrained" and other.source_actor_id == condition.source_actor_id and other.expires_on == "UNTIL_REMOVED":
                    engine._remove_condition(actor, "condition:typed.restrained", ctx.source)
                    break
        engine._remove_condition(actor, NETTED, ctx.source)
        placed.note(engine, ctx.source, actor, f"{actor.display_name} got out of the net.")


# --- Terrain Trap
def _corner(engine: Any, owner: Any, cell: Any, *, modern: bool = False) -> tuple[int, int]:
    """"centered on one corner of one trap space chosen when you set the trap": the corner of the square nearest the closest foe
    (the hindering field goes between you and it) -- a default; the text leaves the corner to its setter."""
    foes = [other for other in engine.state.actors.values() if other.active and other.team_id != owner.team_id]
    if modern:
        from ..senses import perceives
        foes = [other for other in foes if perceives(engine, owner, other)]
    corners = [(cell.x + dx, cell.y + dy) for dy in (0, 1) for dx in (0, 1)]
    if not foes:
        return corners[0]
    near = min(foes, key=lambda other: (engine.grid.distance_ft(cell, other.position), other.entity_id))
    return min(corners, key=lambda c: ((near.position.x + 0.5 - c[0]) ** 2 + (near.position.y + 0.5 - c[1]) ** 2, c))


def _terrain(ctx: Any, zone: Any, d: dict[str, Any]) -> None:
    """"create a 10-foot-radius area of Difficult Terrain centered on one corner of one trap space chosen when you set the trap. The
    Difficult Terrain lasts for 1 minute."  The squares whose centre lies within 10 ft of the corner: a 4x4 block without its four
    corners (12 squares)."""
    engine, owner = ctx.engine, ctx.actor
    px, py = d.get("corner") or (zone.affected_cells[0].x, zone.affected_cells[0].y)
    cells = [(x, y) for x in range(px - 2, px + 2) for y in range(py - 2, py + 2)
             if (x + 0.5 - px) ** 2 + (y + 0.5 - py) ** 2 <= 4 and engine.grid.in_bounds((x, y))
             and (d.get('heaven_net') or (x, y) not in engine.grid.blocked)]
    if d.get('heaven_net'):
        from ..gate2_runtime_models import Position
        cells = [Position(x=x, y=y, z=zone.center.z) for x, y in cells]
    placed.place(engine, owner, source=zone.source_definition_id, tag="terrain_trap", cells=cells, name=f"{owner.display_name}'s Terrain Trap (Difficult Terrain)",
                 numbers=dict(ctx.numbers), duration_rounds=LIFE_ROUNDS, difficult="all", color="#7a6a4a", material="rubble", shape="placed", size_ft=5,
                 extra={'footprint_height_ft': zone.trigger_profile['footprint_height_ft']} if d.get('heaven_net') else None,
                 placed={'heaven_net': 1} if d.get('heaven_net') else None)


# --- Chained Mechanism, Trapper's Recovery
def _chain(ctx: Any, zone: Any, creature: Any) -> None:
    """Chained Mechanism: "choose one other trap you set within 30 feet. If the second trap has a legal target or area, it triggers
    immediately after the first trap resolves. A trap may trigger only once per turn through Chained Mechanism.\""""
    engine, owner = ctx.engine, ctx.actor
    turn = engine.state.round_number * 1000 + engine.state.current_slot_index
    modern = 'triggers' in placed.data(zone)
    options = {}
    labels = {}
    for other in placed.of(engine, "trap", owner_id=owner.entity_id):
        d = placed.data(other)
        if other.zone_id == zone.zone_id or d.get("shield") or d.get("chain_turn") == turn:
            continue
        if engine.grid.distance_ft(other.center, zone.center) > 30:
            continue
        from ..spatial_areas import zone_contains
        victims = [c for c in engine.state.actors.values() if c.active and
                   (zone_contains(engine, c, other) if other.trigger_profile.get('footprint_height_ft') else
                    engine._footprint_intersects(c, other.affected_cells))]
        if modern and _automatic_owner(engine, owner):
            from ..senses import perceives
            victims = [c for c in victims if c.team_id != owner.team_id and perceives(engine, owner, c)]
        legal = d.get("pattern") in ("dart", "dart_net", "flash", "alarm", "terrain") or bool(victims)
        if d.get("pattern") == "dart" and _dart_target(engine, other, d, creature) is None:
            legal = False
        if not legal:
            continue
        if modern:
            victim = victims[0] if victims and d.get('pattern') in ('tripwire', 'net', 'noose') else creature
            # Keep the triggering creature for Warning/Empty Road admission, but
            # describe the recipient using the same ray as actual pattern resolution.
            aimed = _dart_target(engine, other, d, creature) if d.get('pattern') in ('dart', 'dart_net') else victim
            if _automatic_owner(engine, owner):
                from ..senses import perceives
                if aimed is not None and (aimed.team_id == owner.team_id or not perceives(engine, owner, aimed)):
                    continue
            if d.get('pattern') == 'flash':
                effect_label = '5-foot burst around the trap spaces; creatures in the burst may be affected'
            elif d.get('pattern') == 'terrain':
                effect_label = '10-foot-radius Difficult Terrain area around its chosen corner'
            elif d.get('pattern') == 'alarm':
                effect_label = 'alarm sound audible within 300 feet'
            elif aimed is not None:
                effect_label = f'affected creature: {aimed.display_name}'
            else:
                effect_label = 'dart path; no creature currently in its path'
            labels[other.zone_id] = f'Trigger {other.trigger_profile.get("name", "trap")} at {_space_label(other.center)}; {effect_label}'
            options[other.zone_id] = (other, victim)
            continue
        placed.update(engine, other, chain_turn=turn)
        _spring(ctx, other, victims[0] if victims and d.get("pattern") in ("tripwire", "net", "noose") else creature, immediate=True, chained=True)
        return
    if options:
        from .needle import ask, checkpoint_id, CHOICE
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, 'trap_chained_pick', owner.entity_id, zone.zone_id),
            owner, CHOICE + 'trap_chained_pick', list(options),
            labels=labels, allow_decline=True, name='Chained Mechanism',
            prompt='Chained Mechanism: choose one other trap you set within 30 feet with a legal target or area, '
                   'or decline. Each option names the affected creature or describes the area. It resolves after this trap, '
                   'at most once this turn through Chained Mechanism. '
                   'No extra action or resource cost.', prompt_context={'cost': 'None'})
        if chosen:
            other, victim = options[chosen[0]]
            placed.update(engine, other, chain_turn=turn)
            _spring(ctx, other, victim, immediate=True, chained=True)


def _recover_focus(ctx: Any, hurt: bool) -> None:
    """Trapper's Recovery (Reaction): "A creature you can perceive fails a saving throw against one of your traps or takes damage from
    one of your traps. Regain Martial Focus." -- used automatically when the Reaction is free and Martial Focus is absent."""
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    if not hurt or kit is None or T + "TRAPPER_S_RECOVERY" not in kit["owned"] or not owner.active or not owner.reaction_available:
        return
    if owner.resources.get(MF, 0) >= owner.resource_maximums.get(MF, 1):
        return
    from ..paid_relocation import activation as relocation_activation
    with relocation_activation(engine, owner, "reaction:trap.trappers_recovery", independent=True):
        owner.reaction_available = False
        engine._gain_resource(owner, MF, 1, ctx.source)
        engine._append_event("REACTION_RESOLVED", "reaction:trap.trappers_recovery", actor_id=owner.entity_id, target_ids=(owner.entity_id,), payload={})
        placed.note(engine, ctx.source, owner, f"{owner.display_name} regained Martial Focus (Trapper's Recovery).")


# --- Trapped Shield
@hook("attack_resolved")
def trapped_shield(ctx: Any, target: Any, hit: bool, attack: dict[str, Any]) -> None:
    """Trapped Shield (Reaction): "A creature misses you with a melee attack while you wield the shield. Trigger the Dart Mechanism
    against that attacker." (the shield is not checked: the Set Trap choice states it)."""
    engine, attacker = ctx.engine, ctx.actor
    melee = not (ctx.typed.get("range_ft") is not None and int(ctx.typed.get("range_ft") or 0) > 5)
    if hit or not melee or not target.active or not attacker.active or target.entity_id == attacker.entity_id or not target.reaction_available:
        return
    for zone in placed.of(engine, "trap", owner_id=target.entity_id):
        d = placed.data(zone)
        if not d.get("shield"):
            continue
        if d.get('shield_choice'):
            from ..armour import shield_bonus_earning
            if not shield_bonus_earning(engine,target):
                continue
            if not _ask(engine,ctx.intent,target,'trapped_shield',{'use':f'Spend your Reaction: fire the shield dart at {attacker.display_name}'},
                        f'Trapped Shield: {attacker.display_name} missed you in melee. Spend your Reaction to trigger your shield dart?',
                        'Trapped Shield',['use']):
                continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, target, zone.source_definition_id, independent=True):
            target.reaction_available = False
            engine._append_event("REACTION_RESOLVED", zone.source_definition_id, actor_id=target.entity_id, target_ids=(attacker.entity_id,), payload={})
            placed.note(engine, zone.source_definition_id, target, f"{target.display_name}'s Trapped Shield fires its dart at {attacker.display_name}.", targets=(attacker,))
            inner = _with_source(_ctx_for(engine, target, zone), f"trap:{zone.zone_id}")
            with delivery.delivering(engine, f"trap:{zone.zone_id}", hazard=delivery.TRAP, area=zone.zone_id):
                hurt = shoot(engine, target, inner, zone, {**d, "aimed": True}, attacker, bool(d.get("false_used")))
            _recover_focus(inner, hurt)
            placed.drop(engine, zone, "TRIGGERED")
            return


def _ctx_for(engine: Any, owner: Any, zone: Any) -> Any:
    from ..typed_executor import Context

    action = engine.action_catalog.get(zone.source_definition_id)
    typed = {"effects": [], "numbers": dict(zone.trigger_profile.get("numbers") or {}), "weapon": None, "duration": {"kind": "instant"},
             "riders": [], "source": zone.source_definition_id}
    return Context(engine, owner, action, getattr(engine, "_active_intent", None), typed, [], None, {})


# ----------------------------------------------------------------------------------------- saves, finding, disarming
@hook("save")
def trap_save_modes(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    source = str(ctx.typed.get("source") or "")
    if not source.startswith("trap:"):
        return None
    zone = ctx.engine.state.zones.get(source[len("trap:"):])
    if zone is None:
        return None
    d = placed.data(zone)
    modes = []
    if d.get("pattern") == "tripwire" and subject.entity_id in (d.get("aware") or ()):
        modes.append("ADVANTAGE")  # "A creature aware of the Tripwire has Advantage on its saving throw against it."
    if 'false' in d.get('triggers', [d.get('trigger')]) and d.get("false_used"):
        modes.append("DISADVANTAGE")  # False Trigger: "creatures have Disadvantage on saving throws caused by the trap"
    elif ability.upper().startswith("DEX") and _remote_disadvantage(ctx, zone, subject):
        modes.append("DISADVANTAGE")  # Remote Trigger's alternative use
    return {"modes": modes} if modes else None


@hook("after_search")
def find_traps(ctx: Any, eff: dict[str, Any]) -> None:
    """"A creature may take the Search Action and make a Wisdom (Perception) check against your Cultivation Save DC to notice one
    concealed trap within a physically reasonable search area." -- every trap the searcher can see the square of, within 30 feet
    (a default for "physically reasonable"), that it does not know yet."""
    engine, actor = ctx.engine, ctx.actor
    from ..typed_executor import check_mode

    hidden = [zone for zone in placed.of(engine, "trap") if zone.owner_id != actor.entity_id and not placed.data(zone).get("shield")
              and actor.entity_id not in (placed.data(zone).get("aware") or ())
              and engine.grid.distance_ft(actor.position, zone.center) <= 30 and engine._line_of_sight_actor_to_cell(actor, zone.center)]
    if not hidden:
        return
    roll = engine.roller.d20(modifier=int(eff.get("bonus") or 0), actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:TRAPS",
                             mode=check_mode(actor, "WIS", "Perception", engine=ctx.engine))
    engine._record_roll(roll)
    for zone in hidden:
        dc = int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10)
        found = roll.total >= dc
        engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": found, "check": "Perception", "skill": "Perception"})
        if found:
            placed.update(engine, zone, aware=[*(placed.data(zone).get("aware") or ()), actor.entity_id])
            placed.note(engine, ctx.source, actor, f"{actor.display_name} noticed a trap at ({zone.center.x}, {zone.center.y}).")


@effect("trap_disarm")
def trap_disarm(ctx: Any, eff: dict[str, Any]) -> None:
    """"A creature aware of one of your traps may take the Utilize Action and make a Dexterity check using thieves' tools against your
    Cultivation Save DC. Successful Check: The trap is disarmed and harmlessly falls apart. Failed Check: The trap remains armed. If the
    failure is by 5 or more, the trap triggers if its pattern can legally affect the creature attempting to disarm it. You always succeed
    when disarming one of your own traps.\""""
    engine, actor = ctx.engine, ctx.actor
    aim = getattr(ctx.intent, "destination", None)
    zones = [zone for zone in (placed.at(engine, aim, "trap") if aim is not None else []) if _knows(zone, actor)]
    if not zones:
        return
    zone = zones[0]
    dc = int((zone.trigger_profile.get("numbers") or {}).get("save_dc") or 10)
    if zone.owner_id == actor.entity_id:
        success, margin = True, 0
    else:
        from ..typed_executor import check_mode

        roll = engine.roller.d20(modifier=int(eff.get("bonus") or 0), actor_id=actor.entity_id, reason=f"CHECK:{ctx.source}:THIEVES_TOOLS",
                                 mode=check_mode(actor, "DEX", None, engine=ctx.engine))
        engine._record_roll(roll)
        success, margin = roll.total >= dc, dc - roll.total
        engine._append_event("CHECK_ROLLED", ctx.source, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": success, "check": "Disarm"})
    if success:
        placed.drop(engine, zone, "DISARMED")
        placed.note(engine, ctx.source, actor, f"{actor.display_name} disarmed the trap at ({zone.center.x}, {zone.center.y}); it falls apart.")
        return
    placed.note(engine, ctx.source, actor, f"{actor.display_name} failed to disarm the trap" + (" and sets it off." if margin >= 5 else "; it stays armed."))
    owner = engine.state.actors.get(zone.owner_id)
    if margin >= 5 and owner is not None:
        from ..typed_executor import Context

        typed = {"effects": [], "numbers": dict(zone.trigger_profile.get("numbers") or {}), "weapon": None, "duration": {"kind": "instant"},
                 "riders": [], "source": f"trap:{zone.zone_id}"}
        _spring(Context(engine, owner, engine.action_catalog.get(zone.source_definition_id) or ctx.action, ctx.intent, typed, [actor], actor, {}),
                zone, actor, immediate=True)


# ------------------------------------------------------------------------------------------------------------------------------
# Rider lane C4 (2026-09-30; owner: "i want everything we can automated, keep going until its only the non-combat ones left").
# Printed text: authority/typed_mechanics/rules_text.json.
#   Court of the Hidden Nail (a ``state``, ending if Incapacitated): trap limit +PB; "once per turn, set one trap in an unoccupied
#     space within your reach without spending an Action" ("Set Trap (Court, no Action)": no Action and, as printed, no Martial Focus);
#     "a trap set this way lasts until the Court ends"; "your warned allies do not trigger your traps inside the Court" (an ally that
#     knows the trap); "when one of your traps triggers, move up to 5 feet without provoking Opportunity Attacks, or regain Martial
#     Focus if it is absent" (asked; the AI regains Focus when it is absent).
#   The Empty Road Was Never Empty (its Reaction; a ``state``): PB traps placed at once in the 60-foot Emanation (``trap_scatter``:
#     the free square beside each hostile nearest you, then nearest you); limit +PB; warned allies do not trigger your traps; "once
#     per turn, after a hostile creature moves at least 5 feet inside the Emanation, relocate one untriggered trap ... within 10 feet"
#     (asked; the trap nearest the mover moves to the free square nearest it).
#   The Route Was Chosen Already: "When Initiative is rolled, reveal up to your PB concealed traps" (fight setup; once;
#     placed as the Empty Road places them; hostiles are not aware of them).
#   Hundred-Mechanism Scripture: "Set Trap x3": up to three traps, each in a different free square within reach that the owner
#     names (up to two extra after the aimed one), once a fight.
#   Trap Launcher: "Set Trap (Trap Launcher)": Martial Focus, the Action and a Bonus Action; any free square in sight within the normal
#     range of a ranged weapon you wield.
#   Stop, Drop, and Control (Pursuit Lattice: two traps): after the Disengage Action, "Set Trap (Stop, Drop, and Control)" -- free,
#     one Martial Focus for the turn -- in a square you moved through this turn.
#   Trap Within the Trap: False Trigger's click places one more trap (same setting, no Trap Within the Trap) within 5 feet.
#   Opportunist (Reaction): one weapon attack or Unarmed Strike at the creature that sprang your trap, if you see it and reach it.
#   Prepared Escape Route (Reaction): a trap of yours within 30 feet springs -> move up to half your Speed away from the creature
#     without Opportunity Attacks (the AI uses it when that creature is within 10 feet of you).
#   Remote Trigger (Reaction): within 30 feet of your trap, when a hostile creature comes within 30 feet of it and the trap has a
#     legal target (a dart's line, Flash Trap's 5 feet, Alarm, Terrain), trigger it; or impose Disadvantage on a Dexterity save
#     against that trap.
#   Noose: Silenced (combat/speech.py) while the noose's Restrained lasts. Blunt Dart: a creature the dart drops to Dying may be made
#     Stable instead (asked; the AI declines).
COURT, EMPTY_ROAD = "court_of_the_hidden_nail", "empty_road_was_never_empty"
SILENCED = "condition:typed.silenced"
HUNDRED = "tianxia.talent.trap.hundred_mechanism_scripture"


def _state(engine: Any, owner: Any, name: str) -> Any:
    from . import states

    return states.active(engine, owner, name)


def _ask(engine: Any, intent: Any, owner: Any, key: str, options: dict[str, str], prompt: str, name: str, preferred: list[str], *, automatic: bool = True) -> list[str]:
    from .needle import CHOICE, ask, checkpoint_id

    return ask(engine, intent, checkpoint_id(engine, key, owner.entity_id), owner, CHOICE + key, list(options), labels=options, prompt=prompt,
               preferred=preferred, allow_decline=True, default="first" if preferred else "decline", name=name, automatic=automatic)


def _variant_actions(info: dict[str, Any], owned: set[str], numbers: dict[str, Any]) -> list[Any]:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from .weapon_actions import weapon_attacks

    short, actor_id = info["short"], info["actor_id"]
    made = []

    def variant(key: str, name: str, economy: Any, costs: tuple, range_ft: int, flag: str, text: str) -> None:
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.set_trap.{key}", display_name=name, owner_id=actor_id, economy=economy,
            resolution_kind="TYPED", target_kind="CELL", range_ft=range_ft, costs=costs,
            parameters={"typed": {"effects": [{"type": "trap_place", "evidence": text}], "numbers": numbers, "duration": {"kind": "instant"},
                                  "riders": [], "source": SPHERE},
                        "expected_damage": 0, "player_only": True, "any_cell": True, "set_trap": True, "trap_owned": sorted(owned), flag: True,
                        **({'trap_runtime': trap_aerial.capabilities(info)} if trap_aerial.capabilities(info) else {}),
                        **({"auto64_warning": True} if T + "WARNING_TRIGGER" in owned else {}),
                        **({"auto64_shield": True} if T + "TRAPPED_SHIELD" in owned else {}),
                        "description": text}))

    if T + "COURT_OF_THE_HIDDEN_NAIL" in owned:
        variant("court", "Set Trap (Court, no Action)", EconomyKind.NONE, (), REACH_FT, "court_set",
                "While your Court of the Hidden Nail lasts, once per turn: set a trap within reach without spending an Action; it lasts until the Court ends.")
    if HUNDRED in owned:
        variant("hundred", "Set Trap x3 (Hundred-Mechanism Scripture)", EconomyKind.ACTION, ((MF, 1),), REACH_FT, "hundred",
                "Martial Focus and an Action: set up to three traps, each in a different unoccupied space within your reach "
                "that you choose (you may stop at one). You can use this only once per fight.")
    ranged = [int(row.range_ft or typed.get("range_ft") or 0) for row, typed, _attack, kind in weapon_attacks(info["actions"], actor_id) if kind == "ranged"]
    if T + "TRAP_LAUNCHER" in owned and ranged and max(ranged) > REACH_FT:
        variant("launcher", "Set Trap (Trap Launcher)", EconomyKind.ACTION, ((MF, 1),), max(ranged), "launcher",
                "Martial Focus, your Action and your Bonus Action: launch the trap onto a free square you can see within your ranged weapon's normal range.")
    if T + "STOP_DROP_AND_CONTROL" in owned:
        variant("disengage", "Set Trap (Stop, Drop, and Control)", EconomyKind.NONE, (), 60, "sdc",
                "After you Disengage: one Martial Focus sets a trap (two with Pursuit Lattice) in a square you moved through this turn, with no extra Action.")
    return made


def _sdc_uses(kit: dict[str, Any]) -> int:
    return 2 if T + "PURSUIT_LATTICE" in kit["owned"] else 1  # Pursuit Lattice: "set up to two traps"


def _variant_allowed(engine: Any, actor: Any, aim: Any, action: Any) -> bool | None:
    params = action.parameters or {}
    if params.get("court_set"):
        return _state(engine, actor, COURT) is not None and not actor.turn_flags.get("trap_court_set")
    if params.get("hundred"):
        return not actor.turn_flags.get("trap_hundred_round_used")
    if params.get("launcher"):
        return actor.bonus_action_available and engine._line_of_sight_actor_to_cell(actor, aim)
    if params.get("sdc"):
        kit = _kit(engine, actor)
        path = {tuple(cell) for cell in actor.turn_flags.get("trap_sdc_path") or ()}
        used = int(actor.turn_flags.get("trap_sdc_used") or 0)
        paid = bool(actor.turn_flags.get("trap_sdc_paid"))
        return (kit is not None and bool(actor.turn_flags.get("disengaged")) and (aim.x, aim.y) in path and used < _sdc_uses(kit)
                and (paid or actor.resources.get(MF, 0) >= 1))
    return None


def _hundred_extra(ctx: Any, kit: dict[str, Any], cell: Any, config: dict[str, Any]) -> None:
    """Hundred-Mechanism Scripture: "set up to three traps instead. Each trap must occupy different legal spaces within your
    reach." The owner names the two extra spaces; the table used to take the two nearest free squares (AUTO131)."""
    from ..gate2_runtime_models import Position
    from .needle import CHOICE, ask, cell_id, checkpoint_id

    engine, owner = ctx.engine, ctx.actor
    mine = {(z.center.x, z.center.y) for z in placed.of(engine, "trap", owner_id=owner.entity_id)}
    radius = REACH_FT // engine.grid.square_size_ft  # "within your reach"
    spots = [Position(x=owner.position.x + dx, y=owner.position.y + dy)
             for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)
             if (dx or dy) and engine.grid.in_bounds((owner.position.x + dx, owner.position.y + dy))]
    legal = sorted((c for c in spots if engine.grid.distance_ft(c, owner.position) <= REACH_FT and placed.free_square(engine, c)
                    and (c.x, c.y) not in mine and (c.x, c.y) != (cell.x, cell.y)), key=lambda c: (c.x, c.y))
    if not legal:
        return
    by_id = {cell_id(candidate): candidate for candidate in legal}
    key = "trap_hundred_cells"
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, key, owner.entity_id), owner, CHOICE + key, list(by_id),
                 labels={k: f"Set another trap at ({candidate.x}, {candidate.y})" for k, candidate in by_id.items()},
                 minimum=0, maximum=2, default="all", allow_decline=True, name="Hundred-Mechanism Scripture",
                 prompt="Hundred-Mechanism Scripture: choose up to two more unoccupied spaces within your reach for the extra "
                        "traps, each in a different space from the first. Each counts against your active trap limit.")
    for picked in chosen:
        _set(engine, owner, ctx.action, ctx.intent, kit, by_id[picked], config)


def _after_variant(ctx: Any, kit: dict[str, Any], cell: Any, config: dict[str, Any], zone: Any) -> None:
    engine, owner = ctx.engine, ctx.actor
    params = ctx.action.parameters or {}
    if params.get("court_set"):
        owner.turn_flags["trap_court_set"] = True
        if zone is not None:
            placed.update(engine, zone, court=True)
    elif params.get("hundred"):
        owner.turn_flags["trap_hundred_round_used"] = True
        _hundred_extra(ctx, kit, cell, config)
    elif params.get("launcher"):
        owner.bonus_action_available = False  # "use a Bonus Action to launch the trap kit"
    elif params.get("sdc"):
        if not owner.turn_flags.get("trap_sdc_paid"):
            engine._spend_resource(owner, MF, 1, ctx.source)  # "expend Martial Focus to set one trap"
            owner.turn_flags["trap_sdc_paid"] = True
        owner.turn_flags["trap_sdc_used"] = int(owner.turn_flags.get("trap_sdc_used") or 0) + 1


def _spared(engine: Any, owner: Any, zone: Any, creature: Any, d: dict[str, Any]) -> bool:
    if creature.team_id != owner.team_id or creature.entity_id == owner.entity_id or creature.entity_id not in (d.get("aware") or ()):
        return False
    if _state(engine, owner, EMPTY_ROAD) is not None:
        return True
    return _state(engine, owner, COURT) is not None and engine.grid.distance_ft(owner.position, zone.center) <= 30


def _device_space(engine: Any, cell: Any) -> bool:
    """Modern physical device space: solid-volume legality, occupancy and anchor."""
    return trap_aerial.supported_cell(engine, cell) and not placed.occupied(engine, cell)


def _space_label(cell: Any) -> str:
    return f"({cell.x}, {cell.y})" + (f", {cell.z * 5} feet above ground" if cell.z else "")


def _trap_within(ctx: Any, zone: Any, d: dict[str, Any]) -> None:
    """Trap Within the Trap: "When False Trigger produces its warning sound, immediately place one additional trap in one unoccupied space
    within 5 feet of the original trap ... cannot also use Trap Within the Trap." (the original's setting, without a trigger talent).
    The owner names the space: the printed text says "one unoccupied space within 5 feet", which is their choice, not the
    nearest free square (AUTO131)."""
    from ..gate2_runtime_models import Position
    from .needle import CHOICE, ask, cell_id, checkpoint_id

    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    if kit is None or T + "TRAP_WITHIN_THE_TRAP" not in kit["owned"] or d.get("within_child") or ("triggers" in d and "within" not in d["triggers"]):
        return
    modern = bool(d.get('physical_3d'))
    mine = {(z.center.x, z.center.y, z.center.z if modern else 0)
            for z in placed.of(engine, "trap", owner_id=owner.entity_id)}
    radius = REACH_FT // engine.grid.square_size_ft
    heights = range(max(0, zone.center.z - radius), zone.center.z + radius + 1) if modern else (0,)
    spots = [Position(x=zone.center.x + dx, y=zone.center.y + dy, z=z)
             for z in heights for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)
             if (dx or dy or z != zone.center.z) and engine.grid.in_bounds((zone.center.x + dx, zone.center.y + dy))]
    legal = sorted((c for c in spots if engine.grid.distance_ft(c, zone.center) <= REACH_FT
                    and (_device_space(engine, c) if modern else placed.free_square(engine, c))
                    and (c.x, c.y, c.z) not in mine), key=lambda c: (c.x, c.y, c.z))
    if modern and _automatic_owner(engine, owner):
        legal = [c for c in legal if engine._line_of_sight_actor_to_cell(owner, c)]
    if not legal:
        return
    identify = (lambda c: f'cell:{c.x},{c.y},{c.z}') if modern else cell_id
    by_id = {identify(cell): cell for cell in legal}
    key = "trap_within_cell"
    chosen = ask(engine, ctx.intent, checkpoint_id(engine, key, owner.entity_id, zone.zone_id), owner, CHOICE + key, list(by_id),
                 labels={k: f"Place the second trap at {_space_label(cell)}" for k, cell in by_id.items()},
                 preferred=[identify(legal[0])], minimum=1, maximum=1, default="first", name="Trap Within the Trap",
                 prompt="Trap Within the Trap: choose the unoccupied space within 5 feet of the original trap for the second "
                        "trap. It uses a pattern you know, counts against your active trap limit, lasts 1 minute or until it "
                        "triggers, and cannot itself use Trap Within the Trap.")
    if not chosen:
        return
    child = _set(engine, owner, kit["action"], ctx.intent, kit, by_id[chosen[0]],
                 {"form": d.get("form"), "aim": "auto", "trigger": None, "deploy": None, "within_child": True})
    if child is not None:
        placed.update(engine, child, within_child=True)


def _after_spring(ctx: Any, zone: Any, creature: Any) -> None:
    from .. import typed_reactions
    from ..typed_executor import run_effects

    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    if kit is None or not owner.active:
        return
    owned = kit["owned"]
    if _state(engine, owner, COURT) is not None:
        options = {"move": f"Move up to 5 feet away from {creature.display_name} (no Opportunity Attacks)"}
        if owner.resources.get(MF, 0) < 1:
            options = {"focus": "Regain Martial Focus", **options}
        chosen = _ask(engine, ctx.intent, owner, "trap_court_step", options, "Court of the Hidden Nail: one of your traps triggered.",
                      "Court of the Hidden Nail", ["focus"] if "focus" in options else [])
        if chosen == ["focus"]:
            engine._gain_resource(owner, MF, 1, zone.source_definition_id)
        elif chosen == ["move"]:
            row = {"feature_id": T + "COURT_OF_THE_HIDDEN_NAIL", "name": "Court of the Hidden Nail",
                   "effects": [{"type": "reaction_move", "distance_ft": 5, "direction": "away"}]}
            run_effects(typed_reactions.triggered_context(engine, owner, creature, row, ctx.intent), row["effects"])
    if creature.active and creature.team_id != owner.team_id and T + "OPPORTUNIST" in owned and owner.reaction_available:
        from .. import stealth

        row = {"feature_id": T + "OPPORTUNIST", "name": "Opportunist", "numbers": dict(kit["numbers"]),
               "effects": [{"type": "attack", "attack_kind": "weapon", "count": 1, "on_hit": [], "on_miss": [],
                            "evidence": "Make one weapon attack or Unarmed Strike against that creature."}]}
        strike = typed_reactions.triggered_context(engine, owner, creature, row, ctx.intent)
        if stealth.sees(engine, owner, creature) and engine._distance_actor_to_actor(owner, creature) <= int(strike.action.reach_ft or REACH_FT):
            if _ask(engine, ctx.intent, owner, "trap_opportunist", {"use": f"Opportunist: attack {creature.display_name}"},
                    f"Opportunist: {creature.display_name} sprang your trap within reach. Spend your Reaction on one weapon attack?", "Opportunist", ["use"]):
                from ..paid_relocation import activation as relocation_activation
                with relocation_activation(engine, owner, T + "OPPORTUNIST", independent=True):
                    owner.reaction_available = False
                    engine._append_event("REACTION_RESOLVED", T + "OPPORTUNIST", actor_id=owner.entity_id, target_ids=(creature.entity_id,), payload={})
                    run_effects(strike, row["effects"])
    if T + "PREPARED_ESCAPE_ROUTE" in owned and owner.reaction_available and creature.entity_id != owner.entity_id \
            and engine.grid.distance_ft(owner.position, zone.center) <= 30:
        close = creature.active and creature.team_id != owner.team_id and engine._distance_actor_to_actor(owner, creature) <= 10
        if _ask(engine, ctx.intent, owner, "trap_escape_route", {"use": f"Move up to half your Speed away from {creature.display_name}"},
                "Prepared Escape Route: your trap triggered within 30 feet. Spend your Reaction to move?", "Prepared Escape Route", ["use"] if close else []):
            from ..paid_relocation import activation as relocation_activation
            with relocation_activation(engine, owner, T + "PREPARED_ESCAPE_ROUTE", independent=True):
                owner.reaction_available = False
                engine._append_event("REACTION_RESOLVED", T + "PREPARED_ESCAPE_ROUTE", actor_id=owner.entity_id, target_ids=(creature.entity_id,), payload={})
                row = {"feature_id": T + "PREPARED_ESCAPE_ROUTE", "name": "Prepared Escape Route",
                       "effects": [{"type": "reaction_move", "distance_ft": "half_speed", "direction": "away"}]}
                run_effects(typed_reactions.triggered_context(engine, owner, creature, row, ctx.intent), row["effects"])


def _remote_owner(engine: Any, zone: Any) -> Any:
    owner = engine.state.actors.get(zone.owner_id)
    kit = _kit(engine, owner) if owner is not None else None
    if kit is None or T + "REMOTE_TRIGGER" not in kit["owned"] or not owner.active or not owner.reaction_available:
        return None
    data = placed.data(zone)
    if "triggers" in data and "remote" not in data["triggers"]:
        return None
    return owner if engine.grid.distance_ft(owner.position, zone.center) <= 30 else None


def _remote_disadvantage(ctx: Any, zone: Any, subject: Any) -> bool:
    """Remote Trigger: "when a creature makes a Dexterity saving throw against one of your traps within 30 feet, use a Reaction to impose
    Disadvantage on that saving throw.\""""
    engine = ctx.engine
    owner = _remote_owner(engine, zone)
    if owner is None or subject.team_id == owner.team_id:
        return False
    if "triggers" in placed.data(zone):
        from ..senses import perceives
        if not perceives(engine, owner, subject):
            return False
    key = ("trap_remote_save", subject.entity_id)
    if key not in ctx.damage_cache:
        ctx.damage_cache[key] = bool(_ask(engine, ctx.intent, owner, "trap_remote_save", {"use": f"Disadvantage on {subject.display_name}'s save"},
                                          f"Remote Trigger: {subject.display_name} saves against your trap. Spend your Reaction for Disadvantage?",
                                          "Remote Trigger", ["use"]))
        if ctx.damage_cache[key]:
            from ..paid_relocation import activation as relocation_activation
            with relocation_activation(engine, owner, T + "REMOTE_TRIGGER", independent=True):
                owner.reaction_available = False
                engine._append_event("REACTION_RESOLVED", T + "REMOTE_TRIGGER", actor_id=owner.entity_id, target_ids=(subject.entity_id,), payload={})
    return ctx.damage_cache[key]


def _blunt_knockout(ctx: Any, zone: Any, target: Any) -> None:
    """Blunt Dart: "When this trap reduces a conscious and stable creature to 0 HP, you may choose for that creature to become
    Unconscious and stable rather than dying." (the table's default defeat already leaves the map; this is for a Dying creature)."""
    if getattr(target, "life_state", None) != "DYING":
        return
    if _ask(ctx.engine, ctx.intent, ctx.actor, "trap_blunt_knockout", {"stable": f"{target.display_name} is Unconscious and stable"},
            "Blunt Dart: the dart knocked this creature down. Leave it stable rather than dying?", "Blunt Dart", []):
        ctx.engine._set_life_state(target, "STABLE", zone.source_definition_id)


def _scatter_cells(engine: Any, owner: Any, count: int, within_ft: int) -> list[Any]:
    from ..gate2_runtime_models import Position

    taken = {(z.center.x, z.center.y) for z in placed.of(engine, "trap")}
    foes = sorted((a for a in engine.state.actors.values() if a.active and a.team_id != owner.team_id
                   and engine._distance_actor_to_actor(owner, a) <= within_ft), key=lambda a: (engine._distance_actor_to_actor(owner, a), a.entity_id))
    kit = _kit(engine, owner)
    if kit is not None and (kit.get('runtime') or {}).get('dual_trigger'):
        from ..senses import perceives
        foes = [a for a in foes if perceives(engine, owner, a)]
    near = lambda c: engine.grid.distance_ft(c, owner.position)  # noqa: E731
    ok = lambda c: engine.grid.in_bounds((c.x, c.y)) and placed.free_square(engine, c) and (c.x, c.y) not in taken and near(c) <= within_ft  # noqa: E731
    chosen: list[Any] = []
    for foe in foes:
        around = sorted((Position(x=foe.position.x + dx, y=foe.position.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                         if (dx or dy) and engine.grid.in_bounds((foe.position.x + dx, foe.position.y + dy))),
                        key=lambda c: (near(c), c.x, c.y))
        spot = next((c for c in around if ok(c)), None)
        if spot is not None and len(chosen) < count:
            chosen.append(spot)
            taken.add((spot.x, spot.y))
    radius = within_ft // engine.grid.square_size_ft
    rest = sorted((Position(x=owner.position.x + dx, y=owner.position.y + dy) for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1)
                   if (dx or dy) and engine.grid.in_bounds((owner.position.x + dx, owner.position.y + dy))), key=lambda c: (near(c), c.x, c.y))
    for spot in rest:
        if len(chosen) >= count:
            break
        if ok(spot):
            chosen.append(spot)
            taken.add((spot.x, spot.y))
    return chosen


def _scatter(engine: Any, owner: Any, intent: Any, count: int, within_ft: int, *, concealed: bool) -> None:
    kit = _kit(engine, owner)
    if kit is None:
        return
    from .needle import CHOICE, ask, cell_id, checkpoint_id

    legal = _scatter_cells(engine, owner, engine.grid.width * engine.grid.height, within_ft)
    if concealed:
        # Advance preparation must be physically reachable, not merely inside
        # the radius. An hour allows detours; this budget reaches the whole map.
        reachable = engine.grid.reachable(owner.position,
            movement_ft=engine.grid.width * engine.grid.height * engine.grid.square_size_ft * 2,
            occupied_cells=engine._occupied_cells_except(owner.entity_id),
            difficult_cells=engine._hostile_difficult_cells(owner), footprint=engine._footprint(owner))
        legal = [cell for cell in legal if cell in reachable]
    by_id = {cell_id(cell): cell for cell in legal}
    preferred = [cell_id(cell) for cell in _scatter_cells(engine, owner, count, within_ft) if cell_id(cell) in by_id]
    name = "The Route Was Chosen Already" if concealed else "The Empty Road Was Never Empty"
    selected = ask(engine, intent, checkpoint_id(engine, "trap_scatter", owner.entity_id), owner,
                   CHOICE + "trap_scatter", list(by_id),
                   labels={key: f"Place a trap at ({cell.x}, {cell.y})" for key, cell in by_id.items()},
                   preferred=preferred, minimum=1 if concealed else min(count, len(by_id)), maximum=count,
                   default_count=count, allow_decline=concealed, name=name,
                   prompt=f"{name}: choose {'up to ' if concealed else ''}{count} unoccupied trap spaces within "
                          f"{within_ft} feet of {owner.display_name}. "
                          + ("Reveal only traps you prepared during the previous hour in spaces you could physically reach, "
                             "or decline if you made no preparations. Once per long rest; these count against your active trap limit. "
                             if concealed else "These temporary traps last for this one-minute effect and count against your active trap limit. ")
                          + "This placement costs no additional action or resource.")
    config = _config(owner)
    for key in selected:
        cell = by_id[key]
        zone = _set(engine, owner, kit["action"], intent, kit, cell, {**config, "deploy": None})
        if zone is not None and concealed:  # "concealed traps that you prepared": its side knows them, the enemy does not
            placed.update(engine, zone, aware=[a.entity_id for a in engine.state.actors.values() if a.team_id == owner.team_id])


@effect("trap_scatter")
def trap_scatter(ctx: Any, eff: dict[str, Any]) -> None:
    """The Empty Road: "place a number of temporary traps equal to your Proficiency Bonus in legal unoccupied spaces within the Emanation"."""
    count = int(ctx.numbers.get("pb") or 2) if eff.get("count") == "pb" else int(eff.get("count") or 1)
    _scatter(ctx.engine, ctx.actor, ctx.intent, count, int(eff.get("within_ft") or 60), concealed=bool(eff.get("concealed")))


def _court_reconcile(engine: Any) -> None:
    for zone in placed.of(engine, "trap"):
        owner = engine.state.actors.get(zone.owner_id)
        if placed.data(zone).get("court") and (owner is None or _state(engine, owner, COURT) is None):
            placed.drop(engine, zone, "COURT_ENDED")  # "a trap set this way lasts until the Court ends"


@hook("turn_start")
@hook("turn_end")
def court_traps_at_turn(engine: Any, actor: Any) -> None:
    if any(placed.data(zone).get("court") for zone in placed.of(engine, "trap")):
        _court_reconcile(engine)


@hook("event")
def trap_rider_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type == "CONDITION_REMOVED":
        if str((kwargs.get("payload") or {}).get("condition_id") or "").endswith("." + COURT):
            _court_reconcile(engine)
        return
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    if mover is None or not mover.active:
        return
    path = (kwargs.get("payload") or {}).get("path") or []
    cells = [(int(p["x"]), int(p["y"])) if isinstance(p, dict) else (int(p.x), int(p.y)) for p in path]
    if mover.turn_flags.get("disengaged") and cells:
        kit = _kit(engine, mover)
        if kit is not None and T + "STOP_DROP_AND_CONTROL" in kit["owned"]:
            mover.turn_flags["trap_sdc_path"] = [list(c) for c in dict.fromkeys([*(tuple(c) for c in mover.turn_flags.get("trap_sdc_path") or ()), *cells])]
    traps = placed.of(engine, "trap")
    if not traps or kwargs.get("payload", {}).get("forced"):
        return
    _remote_approach(engine, mover, traps, cells)
    _relocate(engine, mover, traps, cells)


def _remote_approach(engine: Any, mover: Any, traps: list[Any], cells: list[tuple[int, int]]) -> None:
    from ..gate2_runtime_models import Position

    start = Position(x=cells[0][0], y=cells[0][1]) if cells else None
    for zone in traps:
        d = placed.data(zone)
        owner = _remote_owner(engine, zone) if not d.get("shield") else None
        if owner is None or owner.team_id == mover.team_id or not zone.active:
            continue
        if engine.grid.distance_ft(mover.position, zone.center) > 30 or (start is not None and engine.grid.distance_ft(start, zone.center) <= 30):
            continue  # "when one creature comes within 30 feet of the trap"
        if "triggers" in d:
            from ..senses import perceives
            if not perceives(engine, owner, mover):
                continue
        pattern = d.get("pattern")
        legal = (pattern in ("dart", "dart_net") and _dart_target(engine, zone, d, mover) is mover) or pattern in ("alarm", "terrain") or (
            pattern == "flash" and any(engine.grid.distance_ft(mover.position, cell) <= 5 for cell in zone.affected_cells))
        if not legal:
            continue  # "The trap must still have a legal target or area for its pattern."
        if not _ask(engine, getattr(engine, "_active_intent", None), owner, "trap_remote", {"use": f"Trigger your trap at {mover.display_name}"},
                    f"Remote Trigger: {mover.display_name} came within 30 feet of your trap. Spend your Reaction to trigger it?", "Remote Trigger",
                    ["use"] if pattern != "alarm" else []):
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, owner, T + "REMOTE_TRIGGER", independent=True):
            owner.reaction_available = False
            engine._append_event("REACTION_RESOLVED", T + "REMOTE_TRIGGER", actor_id=owner.entity_id, target_ids=(mover.entity_id,), payload={})
            _spring(_ctx_for(engine, owner, zone), zone, mover)
            return


def _relocate(engine: Any, mover: Any, traps: list[Any], cells: list[tuple[int, int]]) -> None:
    """The Empty Road: "once per turn, after a hostile creature moves at least 5 feet inside the Emanation, relocate one untriggered trap
    you set to one legal unoccupied space within 10 feet of its previous location"."""
    from ..gate2_runtime_models import Position

    if len(cells) < 2:
        return
    for owner in list(engine.state.actors.values()):
        if owner.team_id == mover.team_id or not owner.active or _state(engine, owner, EMPTY_ROAD) is None:
            continue
        if engine._distance_actor_to_actor(owner, mover) > 60:
            continue
        kit = _kit(engine, owner)
        if kit is not None and (kit.get('runtime') or {}).get('dual_trigger'):
            from ..senses import perceives
            if not perceives(engine, owner, mover):
                continue
        flag = f"trap_relocate_round_{engine.state.round_number}_{engine.state.current_slot_index}"
        if owner.turn_flags.get(flag):
            continue
        mine = [z for z in traps if z.owner_id == owner.entity_id and z.active and not placed.data(z).get("shield")]
        if not mine:
            continue
        modern = bool(kit and (kit.get('runtime') or {}).get('dual_trigger'))
        taken = {(z.center.x, z.center.y, z.center.z if modern else 0) for z in traps}
        options, destinations = {}, {}
        for zone in mine:
            spots = [Position(x=zone.center.x + dx, y=zone.center.y + dy, z=zone.center.z if modern else 0) for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)
                     if (dx or dy) and engine.grid.in_bounds((zone.center.x + dx, zone.center.y + dy))]
            for spot in spots:
                if not (engine.grid.in_bounds((spot.x, spot.y))
                        and (_device_space(engine, spot) if modern else placed.free_square(engine, spot))
                        and (spot.x, spot.y, spot.z) not in taken and engine.grid.distance_ft(spot, zone.center) <= 10):
                    continue
                if modern:
                    if _automatic_owner(engine, owner) and not engine._line_of_sight_actor_to_cell(owner, spot):
                        continue
                    from ..space import ray, position
                    route = tuple(position(p) for p in ray(zone.center, spot))
                    if not all(engine.grid.volume_step_legal(a, b) for a, b in zip(route, route[1:])):
                        continue
                key = f"{zone.zone_id}@{spot.x},{spot.y}" + (f',{spot.z}' if modern and spot.z else '')
                destinations[key] = (zone, spot)
                options[key] = f"Move your trap at {_space_label(zone.center)} to {_space_label(spot)}"
        if not options:
            continue
        nearest = min(mine, key=lambda z: (engine.grid.distance_ft(z.center, mover.position), z.zone_id))
        preferred = sorted((key for key, (zone, spot) in destinations.items() if zone is nearest
                            and engine.grid.distance_ft(spot, mover.position) < engine.grid.distance_ft(zone.center, mover.position)),
                           key=lambda key: (engine.grid.distance_ft(destinations[key][1], mover.position),
                                            destinations[key][1].x, destinations[key][1].y))[:1]
        chosen = _ask(engine, getattr(engine, "_active_intent", None), owner, "trap_relocate", options,
                    f"The Empty Road Was Never Empty: {mover.display_name} moved inside your Emanation. Choose one of "
                    f"{owner.display_name}'s traps and an unoccupied destination within 10 feet of it, or decline. "
                    "Once per turn; no action or resource cost.", "The Empty Road Was Never Empty", preferred, automatic=bool(preferred))
        if not chosen:
            continue
        zone, spot = destinations[chosen[0]]
        owner.turn_flags[flag] = True
        profile = None
        if modern and placed.data(zone).get('aerial'):
            profile, _ = trap_aerial.placement(engine, kit, spot, {'form': placed.data(zone)['form'], 'aerial': 1})
        placed.reshape(engine, zone, cells=(spot,), profile=profile)
        placed.note(engine, zone.source_definition_id, owner, f"The Empty Road: {owner.display_name}'s trap shifts to {_space_label(spot)}.")


@hook("fight_setup_tasks")
def prepared_trap_tasks(engine: Any) -> list[dict[str, str]]:
    """Owned placement work at initiative, never a constructor/turn event."""
    tasks = []
    for owner in engine.state.actors.values():
        kit = _kit(engine, owner) if owner.active else None
        road = any(row.get('feature_id') == T + 'THE_EMPTY_ROAD_WAS_NEVER_EMPTY'
                   and row.get('kind') == 'initiative' and not row.get('held_back')
                   and all(owner.resources.get(c['resource_id'], 0) >= c['amount'] for c in row.get('costs') or [])
                   for row in getattr(engine, 'typed_reaction_rows', {}).get(owner.entity_id, []))
        if kit and (T + 'THE_ROUTE_WAS_CHOSEN_ALREADY' in kit['owned'] or road):
            tasks.append({'actor_id': owner.entity_id, 'source_id': kit['action'].source_definition_id})
    return tasks


@hook("fight_setup")
def prepare_traps(engine: Any, owner: Any, source_id: str, intent: Any) -> bool | None:
    kit = _kit(engine, owner)
    if kit is None or source_id != kit['action'].source_definition_id or not kit['owned'] & {
            T + 'THE_ROUTE_WAS_CHOSEN_ALREADY', T + 'THE_EMPTY_ROAD_WAS_NEVER_EMPTY'}:
        return None
    if T + 'THE_ROUTE_WAS_CHOSEN_ALREADY' in kit['owned'] and not owner.turn_flags.get('trap_route_round_used'):
        _scatter(engine, owner, intent, int(kit['numbers'].get('pb') or 2), 60, concealed=True)
        owner.turn_flags['trap_route_round_used'] = 1
    if T + 'THE_EMPTY_ROAD_WAS_NEVER_EMPTY' in kit['owned']:
        # Ordinary reaction consent, price, availability, effects and later
        # enters-range trigger remain in one generic implementation.
        from ..typed_reactions import on_own_event
        on_own_event(engine, owner, None, 'initiative',
                     accept=lambda row: row.get('feature_id') == T + 'THE_EMPTY_ROAD_WAS_NEVER_EMPTY')
    owner.turn_flags['trap_setup_round_done'] = 1
    return True


@hook("row_allowed")
def prepared_road_initiative_allowed(engine: Any, owner: Any, row: dict[str, Any]) -> bool | None:
    if row.get('feature_id') != T + 'THE_EMPTY_ROAD_WAS_NEVER_EMPTY' or row.get('kind') != 'initiative':
        return None
    # Prevent the legacy first-turn initiative dispatcher from asking twice,
    # including after a decline. Other triggers and old saves stay unchanged.
    return not owner.turn_flags.get('trap_setup_round_done')
