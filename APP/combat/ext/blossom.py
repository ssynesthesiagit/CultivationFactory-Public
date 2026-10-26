"""The Flowers sphere's Blossoms (owner 2026-09-29: "i want everything we can automated"): a Blossom is a spiritual flower
that lies dormant on a creature or a square until its creator makes it bloom.  Owner rules:
LocalSources/04_spheres_talents/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md ("Core Flower Rules") and
authority/typed_mechanics/rules_text.json (TAL_FLOWERS_* and tianxia.talent.flowers.* texts).  Where the text is silent the
default is named below; Spheres 5e and D&D 5.5e were not needed.

What a Blossom is (Core Flower Rules): it "occupies one creature, object, or 5-foot space"; dormant it lasts 1 hour; "you may
maintain a number of dormant Blossoms up to your Proficiency Bonus"; it is visible as a faint spiritual flower; "a creature may
use an Action to remove one visible Blossom attached to itself or an object it carries"; on bloom "you resolve one Blossom talent
you know and pay its CP cost", and the Blossom withers after blooming.  Here a Blossom is a placement (combat/ext/placed.py): a
typed zone, tag "blossom", drawn on the table with a hover text; a creature it rides gets the condition "Blossom on it" (the
hover text says what it is and who made it).  Past the limit the oldest dormant Blossom withers (the text leaves the choice to you).

Buttons (all free choices of the player; the AI does not use them):
- Cultivate Blossom (Action, 60 ft): one dormant Blossom on a willing creature (an ally or yourself), an unoccupied space, or an
  unwilling creature ("Make a ranged Cultivation Attack. Hit: Apply the Blossom. Miss: No effect.") -- an enemy is unwilling, an
  ally or you willing (the text says "willing", the table has no other test).
- Cultivate Blossom (bloom at once): Immediate Bloom, "cause it to bloom immediately as part of the same Action", paying the CP.
- Delayed Bloom (Bonus Action): "cause one of your dormant Blossoms within 60 feet to bloom. Choose one Blossom talent you know
  and pay its CP cost" -- the Blossom is the one at the square chosen; the talent is the one picked with the free
  "Blossom: ..." buttons (shown only when more than one is known; Medicinal Blossom is known with the sphere).
- Remove Blossom (Action, anyone): "remove one visible Blossom attached to itself" (a Seed first, else the oldest).

The Blossom talents (each a bloom, its CP taken at once):
- Medicinal Blossom (1 CP): "choose one living creature within 5 feet" regains 1d8/2d8/3d8 (CL 1-10/11-16/17-20) + Path key
  ability modifier, "only once per short rest" per creature -- the wounded ally (or you) nearest death within 5 ft of the Blossom
  (the text leaves the choice to you: a default).
- Thorned Bloom (2 CP, Concentration up to 1 minute): "a 10-foot-radius field of thorned flowers centered on itself", Difficult
  Terrain; a hostile creature that enters "for the first time on a turn or starts its turn inside" makes a Dexterity save, Piercing
  2d6/4d6/6d6, half on success, "only once per turn" (the zone's own per-turn guard).
- Exploding Seed (3 CP, CL 5+): "lasts until the end of your next turn", then "explodes in a 10-foot-radius sphere": Dexterity
  save, 4d6/6d6/8d6 Piercing or Poison (the free "Seed damage" button), half on success; a carrier removes it with Remove Blossom.
- Scented Trace (1 CP, 8 hours): a creature only ("dissolves into a trace on the subject"); an unwilling creature makes a
  Dexterity save when it blooms (success: the trace fails); "maintain up to PB traces" (the oldest goes); the log names the
  direction sense ("approximate direction within 10 x PB miles").
- Spirit Lotus (6 CP, CL 10+, Concentration up to 1 minute): a lotus on the square that at the end of your turn acts on a
  creature within 30 feet -- Restoration 2d8 + key modifier (once per short rest per creature), Purifying Pollen (one repeated
  save against Charmed, Frightened or Poisoned) or Piercing Petals (a Cultivation Attack, 3d8 Slashing); the free "Lotus" button
  picks one or "automatic" (heal the most wounded, else purify, else petals).
- Traveling Garden (+1 CP, CL 7+, on Thorned Bloom): the field is anchored to the creature carrying the Blossom; an unwilling
  creature makes a Wisdom save (failed: it moves with the bearer; it repeats the save at the end of each of its turns, the engine's
  own repeat save).  Only Thorned Bloom is an area that blooms from a Blossom, so it is the only one this changes.
- Flower of False Death (Reaction, 6 CP, CL 10+, "once per long rest per creature"): "Cause one Blossom already attached to the
  creature to bloom": it must carry one of yours; it drops to 1 HP instead of 0, is Invisible until the start of its next turn, and
  "a blossom appears where the creature would have fallen" (a new dormant Blossom on its square).
- Corpse-Blooming Flower (Reaction, 4 CP, CL 10+): a living creature dies within 60 feet: a flower on its square for 1 minute;
  at the start of your turn Funeral Medicine (an ally within 15 ft regains 2d8 + key) or Grave Pollen (an enemy within 15 ft:
  Constitution save, 3d8 Poison or Necrotic, half on success); "Only one may exist at a time"; not from a temporary summon.
- Ten-Thousand Bloom Scripture (Bonus Action, 10 CP, once per long rest, 1 minute): maximum dormant Blossoms twice PB; Cultivate
  Blossom makes two; "once per turn, cause one dormant Blossom to bloom without spending a Bonus Action"; "the first Blossom talent
  you activate each turn costs 1 fewer CP, minimum 1".

Hooks added to the framework: ``ally_row_allowed(engine, reactor, subject, row)`` (combat/ext/__init__.py) -- the ally-reaction twin
of ``reaction_subject_allowed``, for a "you or an ally" row that answers an ally's event.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook, placed

SPHERE = "tianxia.sphere.flowers"
SETUP = "condition:typed.blossom_setup"
CARRIED = "condition:typed.blossom_carried"
ANCHORED = "condition:typed.blossom_anchored"
SCRIPTURE_ON = "condition:typed.blossom_scripture"
MEDICINE_USED = "condition:typed.blossom_medicine_used"
LOTUS_USED = "condition:typed.blossom_lotus_used"
TRACE_ON = "condition:typed.blossom_trace"
FALSE_DEATH_USED = "condition:typed.blossom_false_death_used"

THORN, SEED, TRACE, LOTUS = ("TAL_FLOWERS_THORNED_BLOOM", "TAL_FLOWERS_EXPLODING_SEED", "TAL_FLOWERS_SCENTED_TRACE",
                             "tianxia.talent.flowers.spirit_lotus")
GARDEN, FALSE_DEATH = "TAL_FLOWERS_TRAVELING_GARDEN", "TAL_FLOWERS_FLOWER_OF_FALSE_DEATH"
CORPSE, SCRIPTURE = "tianxia.talent.flowers.corpse_blooming_flower", "tianxia.talent.flowers.ten_thousand_bloom_scripture"

RANGE_FT = 60  # Cultivate Blossom's range and Delayed Bloom's
DORMANT_ROUNDS = 600  # "Duration: 1 hour or until bloomed"
CONCENTRATION_ROUNDS = 10  # "Concentration, up to 1 minute"
SCRIPTURE_ROUNDS = 10  # "Duration: 1 minute"
FIELD_FT = 10  # Thorned Bloom and Exploding Seed: "10-foot-radius"

# kind -> (name, the talent it needs (None: known with the sphere), CP)
BLOOMS: dict[str, tuple[str, str | None, int]] = {
    "medicinal": ("Medicinal Blossom", None, 1), "thorned": ("Thorned Bloom", THORN, 2), "seed": ("Exploding Seed", SEED, 3),
    "trace": ("Scented Trace", TRACE, 1), "lotus": ("Spirit Lotus", LOTUS, 6)}
# (low CL, high CL, value): the rules' Cultivation Level tables
MEDICINE_DICE = [(1, 10, 1), (11, 16, 2), (17, 99, 3)]  # d8
THORN_DICE = [(1, 10, 2), (11, 16, 4), (17, 99, 6)]  # d6
SEED_DICE = [(1, 10, 4), (11, 16, 6), (17, 99, 8)]  # d6
SEED_TYPES = {"piercing": "Piercing", "poison": "Poison"}
LOTUS_MODES = {"auto": "automatic", "restore": "Restoration", "purify": "Purifying Pollen", "petals": "Piercing Petals"}
CORPSE_MODES = {"auto": "automatic", "medicine": "Funeral Medicine", "pollen_poison": "Grave Pollen (Poison)",
                "pollen_necrotic": "Grave Pollen (Necrotic)"}
AURA_FT = 30  # Spirit Lotus: "a creature within 30 feet"
CORPSE_FT = 15  # Corpse-Blooming Flower: "within 15 feet"


# ------------------------------------------------------------------------------------------------ the kit a caster owns
def _kit(engine: Any, owner: Any) -> dict[str, Any] | None:
    """The owner's Cultivate Blossom action's own record: the talents it owns, its numbers and the CP pool."""
    for action in engine.action_catalog.values():
        params = action.parameters or {}
        if action.owner_id == owner.entity_id and params.get("blossom_kit"):
            typed = params.get("typed") or {}
            return {"action": action, "owned": set(params.get("blossom_owned") or ()), "numbers": typed.get("numbers") or {},
                    "pool": params.get("blossom_pool") or "resource:core.qi", "source": action.source_definition_id}
    return None


def _config(owner: Any) -> dict[str, Any]:
    for condition in owner.conditions.values():
        if condition.condition_id == SETUP:
            return dict(condition.data or {})
    return {}


def _known(kit: dict[str, Any]) -> list[str]:
    return [kind for kind, (_name, talent, _cost) in BLOOMS.items() if talent is None or talent in kit["owned"]]


def _kind(kit: dict[str, Any], config: dict[str, Any]) -> str | None:
    known = _known(kit)
    chosen = config.get("bloom")
    return chosen if chosen in known else (known[0] if known else None)


def _scripture(owner: Any) -> bool:
    return any(condition.condition_id == SCRIPTURE_ON for condition in owner.conditions.values())


def _limit(kit: dict[str, Any], owner: Any) -> int:
    pb = int(kit["numbers"].get("pb") or 2)
    return pb * (2 if _scripture(owner) else 1)  # Scripture: "maximum dormant Blossoms becomes twice your Proficiency Bonus"


def _garden(kit: dict[str, Any], kind: str, config: dict[str, Any], bearer: Any) -> bool:
    """Whether Traveling Garden is used: it "anchors an area to the creature or object carrying the Blossom", so a Blossom on an
    empty square has nothing to anchor to and its Thorned Bloom costs no more."""
    return kind == "thorned" and GARDEN in kit["owned"] and config.get("garden") != "off" and bearer is not None


def _cost(engine: Any, owner: Any, kit: dict[str, Any], kind: str, garden: bool) -> int:
    listed = BLOOMS[kind][2] + (1 if garden else 0)  # Traveling Garden: "+1 CP"
    cost = listed
    if _scripture(owner) and not owner.turn_flags.get("blossom_discount_used"):
        cost = max(1, cost - 1)  # "the first Blossom talent you activate each turn costs 1 fewer CP, minimum 1"
    return dict(engine.effective_costs(owner, BLOOMS[kind][1] or kit['source'],
        ((kit['pool'], listed),), reduced_costs=((kit['pool'], cost),)))[kit['pool']]


def _blocker(engine: Any, owner: Any, kit: dict[str, Any], kind: str | None, bearer: Any) -> str | None:
    """Why this Blossom cannot bloom as that talent now (None: it can)."""
    if kind is None:
        return "no Blossom talent is known"
    cost = _cost(engine, owner, kit, kind, _garden(kit, kind, _config(owner), bearer))
    if owner.resources.get(kit["pool"], 0) < cost:
        return f"{BLOOMS[kind][0]} needs {cost} CP"
    if kind == "trace" and bearer is None:
        return "a Scented Trace needs a creature to mark"
    return None


def _used(subject: Any, owner: Any, condition_id: str) -> bool:
    return any(c.condition_id == condition_id and c.source_actor_id == owner.entity_id for c in subject.conditions.values())


def _creature_at(engine: Any, cell: Any) -> Any | None:
    found = [actor for actor in engine.state.actors.values() if actor.active and engine._footprint_intersects(actor, (cell,))]
    return min(found, key=lambda actor: actor.entity_id) if found else None


def _near(engine: Any, centre: Any, actor: Any, feet: int) -> bool:
    return engine.grid.distance_ft(centre, actor.position) <= feet


def _blossoms(engine: Any, owner: Any | None = None, states: tuple[str, ...] = ("dormant", "seed")) -> list[Any]:
    return [zone for zone in placed.of(engine, "blossom", owner_id=owner.entity_id if owner is not None else None)
            if placed.data(zone).get("state") in states]


def _carried(engine: Any, bearer: Any) -> list[Any]:
    """The live Blossoms riding a creature (a condition whose Blossom has gone is ignored here and cleared at its turn)."""
    found = []
    for condition in bearer.conditions.values():
        if condition.condition_id == CARRIED:
            zone = engine.state.zones.get(str((condition.data or {}).get("zone_id")))
            if zone is not None and zone.active and placed.data(zone).get("bearer") == bearer.entity_id and placed.data(zone).get("state") in ("dormant", "seed"):
                found.append(zone)
    return sorted(found, key=lambda zone: (placed.data(zone).get("state") != "seed", zone.created_round, int(zone.zone_id.rsplit(":", 1)[-1])))


# ------------------------------------------------------------------------------------------------------------ the buttons
def _bloom_effects(numbers: dict[str, Any]) -> dict[str, str]:
    """Each Blossom talent's printed effect at this Cultivation Level; presentation only, with no live-state lookup."""
    cl = int(numbers.get("cl") or 1)
    medicine = placed.cl_row(cl, MEDICINE_DICE)
    thorns = placed.cl_row(cl, THORN_DICE)
    seed = placed.cl_row(cl, SEED_DICE)
    return {
        "medicinal": f"heals {medicine}d8 + your Path key ability modifier HP immediately. The table chooses the "
        "eligible wounded ally (including you) within 5 feet of the Blossom with the lowest fraction of HP remaining. "
        "Each creature can receive this healing from you only once per short rest. If nobody is eligible, "
        "the Blossom withers without healing, but you still pay the point cost.",
        "thorned": f"creates a 10-foot-radius field centered on the Blossom; Concentration, up to 1 minute. "
        "The field is difficult terrain (movement costs twice as much). An enemy entering it for the first time "
        f"on a turn or starting its turn there makes a Dexterity save: {thorns}d6 Piercing damage, half on success, "
        "at most once per turn.",
        "seed": "creates a seed that explodes at the end of your next turn in a 10-foot-radius sphere. "
        f"Every creature inside makes a Dexterity save: {seed}d6 Piercing damage (or Poison if chosen with "
        "the Seed damage buttons), half on success. A carrier can use an Action to remove it before it explodes.",
        "trace": "marks the creature carrying the Blossom for 8 hours. You sense its approximate direction "
        "on the same plane within 10 times your Proficiency Bonus in miles. An unwilling creature makes a "
        "Dexterity save; success prevents the trace. You can keep traces up to your Proficiency Bonus; the oldest ends first.",
        "lotus": "creates a lotus at the Blossom; Concentration, up to 1 minute. At the end of your turn it "
        "affects one creature within 30 feet: Restoration heals an eligible wounded ally for 2d8 + your Path "
        "key ability modifier HP (once per short rest per creature); Purifying Pollen lets an ally repeat a "
        "save against Charmed, Frightened or Poisoned; Piercing Petals makes a Cultivation Attack against "
        "the nearest enemy for 3d8 Slashing on a hit. The Lotus buttons choose the mode; automatic mode "
        "heals the ally with the lowest fraction of HP remaining, otherwise tries pollen, otherwise petals.",
    }


# Plain wording of the Blossom talents for an option button: the printed effect, then the cost, with no internal ids.
def _immediate_description(owned: set[str], numbers: dict[str, Any]) -> str:
    """Explain the existing default/standing selections; presentation only, with no live-state lookup."""
    effects = _bloom_effects(numbers)
    known = _known({"owned": owned})
    text = ("Costs an Action. Choose a square within 60 feet: place a Blossom on a willing creature "
            "(an ally or yourself), an unoccupied space, or an unwilling creature. On an unwilling creature, "
            "make a ranged Cultivation Attack: on a hit the Blossom is applied; on a miss nothing happens. "
            "It blooms as part of the same Action, resolving your selected Blossom talent and paying its "
            "Cultivation Point cost immediately. Medicinal Blossom is the default.")
    if len(known) > 1:
        text += " Use the Blossom: talent buttons to change the selection before using this Action; the selection stays until changed."
    for kind in known:
        name, _talent, cost = BLOOMS[kind]
        text += f"\n\n{name} — {cost} Cultivation Point{'s' if cost != 1 else ''}: {effects[kind]}"
    if GARDEN in owned and "thorned" in known:
        text += ("\n\nTraveling Garden adds 1 Cultivation Point to Thorned Bloom when the Blossom is on a creature "
                 "and anchoring is enabled (the default). The field moves with its bearer; an unwilling bearer "
                 "makes a Wisdom save to resist and repeats it at the end of each turn to end the anchor. "
                 "Use Traveling Garden: leave the field where it blooms to disable this extra cost.")
    if SCRIPTURE in owned:
        text += ("\n\nWhile Ten-Thousand Bloom Scripture is active, your first Blossom talent each turn "
                 "costs 1 fewer Cultivation Point, minimum 1. Other active cost reductions also apply.")
    return text


@hook("compile_actions")
def blossom_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..factory_compiler import RESOURCE_IDS
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    owned = set(info["owned_ids"])
    out: list[Any] = []

    def make(key: str, name: str, effects: list[dict[str, Any]], economy: Any = EconomyKind.NONE, target: str = "SELF",
             range_ft: int | None = None, **params: Any) -> Any:
        return ActionDefinition(
            source_definition_id=f"action:typed.{short}.{key}", display_name=name, owner_id=actor_id, economy=economy, resolution_kind="TYPED",
            target_kind=target, range_ft=range_ft,
            parameters={"typed": {"effects": effects, "numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": SPHERE},
                        "expected_damage": 0, "player_only": True, **params})

    if SPHERE in info["spheres"]:
        pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
        parent = f"action:typed.{short}.blossom.cultivate"  # the menu groups the pickers and bloom-at-once under this ability
        out.append(make("blossom.cultivate", "Cultivate Blossom", [{"type": "blossom_cultivate"}], EconomyKind.ACTION, "CELL", RANGE_FT,
                        any_cell=True, blossom_kit=True, blossom_cultivate=True, blossom_owned=sorted(owned), blossom_pool=pool))
        out.append(make("blossom.cultivate_bloom", "Cultivate Blossom (bloom at once)", [{"type": "blossom_cultivate", "immediate": True}],
                        EconomyKind.ACTION, "CELL", RANGE_FT, any_cell=True, blossom_cultivate=True, blossom_immediate=True,
                        menu_parent=parent, placement_prompt="Cultivate Blossom: choose where the blossom blooms.",
                        description=_immediate_description(owned, numbers)))
        out.append(make("blossom.delayed", "Delayed Bloom", [{"type": "blossom_delayed"}], EconomyKind.BONUS_ACTION, "CELL", RANGE_FT,
                        any_cell=True, blossom_delayed=True))
        if SCRIPTURE in owned:
            out.append(make("blossom.delayed_free", "Delayed Bloom (Scripture, no action)", [{"type": "blossom_delayed", "free": True}],
                            EconomyKind.NONE, "CELL", RANGE_FT, any_cell=True, blossom_delayed=True, blossom_free=True))
        kit = {"owned": owned}
        known = _known(kit)
        if len(known) > 1:
            effects = _bloom_effects(numbers)
            for kind in known:
                name, _talent, cost = BLOOMS[kind]
                out.append(make(f"blossom.pick.{kind}", f"Blossom: {name} ({cost} CP)", [{"type": "blossom_setup_pick", "field": "bloom", "value": kind}],
                                setting_only=True, menu_parent=parent, description=f"{name}: {effects[kind]} Cost: {cost} CP."))
        if SEED in owned:
            for value, label in SEED_TYPES.items():
                out.append(make(f"blossom.seed.{value}", f"Seed damage: {label}", [{"type": "blossom_setup_pick", "field": "seed", "value": value}],
                                setting_only=True, menu_parent=parent,
                                description=f"Choose {label} damage for your next Exploding Seed; it bursts at the end of your next turn."))
        if LOTUS in owned:
            for value, label in LOTUS_MODES.items():
                out.append(make(f"blossom.lotus.{value}", f"Lotus: {label}", [{"type": "blossom_setup_pick", "field": "lotus", "value": value}], setting_only=True))
        if CORPSE in owned:
            for value, label in CORPSE_MODES.items():
                out.append(make(f"blossom.corpse.{value}", f"Corpse flower: {label}", [{"type": "blossom_setup_pick", "field": "corpse", "value": value}], setting_only=True))
        if GARDEN in owned:
            for value, label in (("on", "anchor the field to its bearer"), ("off", "leave the field where it blooms")):
                out.append(make(f"blossom.garden.{value}", f"Traveling Garden: {label}", [{"type": "blossom_setup_pick", "field": "garden", "value": value}], setting_only=True))
    # "A creature may use an Action to remove one visible Blossom attached to itself or an object it carries." (Core Flower Rules)
    out.append(make("blossom.remove", "Remove Blossom", [{"type": "blossom_remove"}], EconomyKind.ACTION, "SELF", None,
                    blossom_remove=True, requires_condition=CARRIED, expected_damage=1))
    return out


@hook("button_description")
def removal_description(row: dict[str, Any]) -> str | None:
    """Core Flower Rules: removal is an Action, with no roll or cultivation cost."""
    effects = ((row.get("parameters") or {}).get("typed") or {}).get("effects") or []
    if any(eff.get("type") == "blossom_remove" for eff in effects):
        return ("Action: remove one visible Blossom attached to you or an object you carry and throw it away. "
                "No check or cultivation points are required. The removed Blossom withers and can no longer bloom. "
                "The table removes an Exploding Seed first, otherwise the oldest Blossom.")
    return None


@hook("button_selection")
def setup_selection(parameters: dict[str, Any]) -> dict[str, Any] | None:
    pick = next((eff for eff in (parameters.get("typed") or {}).get("effects") or [] if eff.get("type") == "blossom_setup_pick"), None)
    return {"condition": SETUP, "equals": {pick["field"]: pick.get("value")}} if pick else None


@hook("option_composition")
def composition(action):
    """Independent, absolute Blossom fields; a bloom still selects one talent."""
    effects = (action.parameters.get("typed") or {}).get("effects") or []
    if len(effects) != 1 or effects[0].get("type") != "blossom_setup_pick":
        return None
    pick = effects[0]
    values = {"bloom": BLOOMS, "seed": SEED_TYPES, "lotus": LOTUS_MODES,
              "corpse": CORPSE_MODES, "garden": {"on", "off"}}
    if pick.get("value") not in values.get(pick.get("field"), ()):
        return None
    cost = BLOOMS[pick["value"]][2] if pick["field"] == "bloom" else 0
    return {"key": ["blossom", pick["field"]], "mode": "select",
            "family": action.parameters.get("menu_parent"), "cost_label": f"{cost} CP" if cost else ""}


@effect("blossom_setup_pick")
def setup_pick(ctx: Any, eff: dict[str, Any]) -> None:
    config = _config(ctx.actor)
    config[str(eff["field"])] = eff.get("value")
    kit = _kit(ctx.engine, ctx.actor)
    kind = _kind(kit, config) if kit else None
    config["label"] = ("Blossoms: " + (BLOOMS[kind][0] if kind else "none")
                       + (f", seed {SEED_TYPES.get(config.get('seed') or 'piercing')}" if kit and SEED in kit["owned"] else "")
                       + (f", lotus {LOTUS_MODES.get(config.get('lotus') or 'auto')}" if kit and LOTUS in kit["owned"] else "")
                       + (f", corpse flower {CORPSE_MODES.get(config.get('corpse') or 'auto')}" if kit and CORPSE in kit["owned"] else "")
                       + (", garden off" if config.get("garden") == "off" else ""))
    ctx.engine._remove_condition(ctx.actor, SETUP, ctx.source)
    # This is private button-selection state, not a Blossom placed on the actor.
    # Keep it in fight state for the next action, but omit it from the event log.
    ctx.engine._apply_condition(ctx.actor, SETUP, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={**config, "hidden": True})


# ------------------------------------------------------------------------------------------------------ which square
@hook("candidate_allowed")
def blossom_candidates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = getattr(action, "parameters", None) or {}
    aim = getattr(candidate, "destination", None)
    if params.get("blossom_remove"):
        return bool(_carried(engine, actor))
    if not (params.get("blossom_cultivate") or params.get("blossom_delayed")):
        return None
    kit = _kit(engine, actor)
    if kit is None or aim is None:
        return False
    if params.get("blossom_cultivate"):
        who = _creature_at(engine, aim)
        if who is None and _object_at(engine, aim) is None and not placed.free_square(engine, aim):
            return False  # "One creature, object, or unoccupied 5-foot space"
        if params.get("blossom_immediate"):
            return _blocker(engine, actor, kit, _kind(kit, _config(actor)), who) is None
        return True
    if params.get("blossom_free") and (not _scripture(actor) or actor.turn_flags.get("blossom_free_bloom")):
        return False  # Scripture: "once per turn"
    zone = _dormant_at(engine, actor, aim)
    if zone is None:
        return False
    return _blocker(engine, actor, kit, _kind(kit, _config(actor)), engine.state.actors.get(placed.data(zone).get("bearer") or "")) is None


def _object_at(engine: Any, cell: Any) -> Any | None:
    """A live object whose footprint covers the square (the Cultivate target may be an object)."""
    from .objects import rectangular_cells
    for obj in sorted(engine.state.objects.values(), key=lambda o: o.object_id):
        if obj.destroyed or obj.position is None:
            continue
        cells = rectangular_cells(engine, obj) or (obj.position,)
        if any((c.x, c.y) == (cell.x, cell.y) for c in cells):
            return obj
    return None


def _dormant_at(engine: Any, owner: Any, cell: Any) -> Any | None:
    found = [zone for zone in placed.at(engine, cell, "blossom") if zone.owner_id == owner.entity_id and placed.data(zone).get("state") == "dormant"]
    return found[0] if found else None


# ------------------------------------------------------------------------------------------------- cultivating a Blossom
@effect("blossom_cultivate")
def cultivate(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects

    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    cell = getattr(ctx.intent, "destination", None)
    if kit is None or cell is None:
        ctx.rider("Cultivate Blossom: no square was chosen.")
        return
    who = _creature_at(engine, cell)
    if who is None and (obj := _object_at(engine, cell)) is not None:
        # "Object: The Blossom is applied to it automatically" (a willing bearer; no creature condition).
        _plant_and_bloom(engine, owner, kit, ctx.source, cell, None, True, bool(eff.get("immediate")), obj=obj)
        return
    row = {"type": "blossom_apply", "immediate": bool(eff.get("immediate")), "cell": [cell.x, cell.y]}
    if who is not None and who.team_id != owner.team_id:
        # "Unwilling Creature: Make a ranged Cultivation Attack. Hit: Apply the Blossom. Miss: No effect."
        inner = placed.context(engine, owner, ctx.source, ctx.numbers, [who], action=ctx.action)
        inner.typed["range_ft"] = RANGE_FT
        run_effects(inner, [{"type": "attack", "attack_kind": "cultivation", "on_hit": [row]}])
        return
    _plant_and_bloom(engine, owner, kit, ctx.source, cell, who, True, bool(eff.get("immediate")))


@effect("blossom_apply")
def apply(ctx: Any, eff: dict[str, Any]) -> None:
    """The hit of an unwilling creature's Cultivation Attack: the Blossom is applied to it."""
    kit = _kit(ctx.engine, ctx.actor)
    who = ctx.target
    if kit is None or who is None or not who.active:
        return
    _plant_and_bloom(ctx.engine, ctx.actor, kit, ctx.source, who.position, who, False, bool(eff.get("immediate")))


def _plant_and_bloom(engine: Any, owner: Any, kit: dict[str, Any], source: str, cell: Any, bearer: Any, willing: bool, immediate: bool, obj: Any = None) -> None:
    made = [_plant(engine, owner, kit, source, cell, bearer, willing, obj) for _ in range(2 if _scripture(owner) else 1)]  # Scripture: "may create two"
    if immediate and made:
        _bloom(engine, owner, made[0], kit, source)  # "cause it to bloom immediately as part of the same Action" (the first one)


def _plant(engine: Any, owner: Any, kit: dict[str, Any], source: str, cell: Any, bearer: Any, willing: bool, obj: Any = None) -> Any:
    from .objects import rectangular_cells
    numbers = kit["numbers"]
    where = f" on {bearer.display_name}" if bearer is not None else f" at ({cell.x}, {cell.y})"
    if obj is not None:
        from ..object_rules import label
        where = f" on {label(obj)}"
    cells = bearer.position if bearer is not None else cell
    if obj is not None:
        cells = list(rectangular_cells(engine, obj) or (obj.position,))
    zone = placed.place(
        engine, owner, source=kit["source"], tag="blossom", cells=cells, numbers=numbers,
        duration_rounds=DORMANT_ROUNDS, name=f"{owner.display_name}'s dormant Blossom{where}", color="#e58fb4", material="vines",
        anchor_id=bearer.entity_id if bearer is not None else None,
        placed={"state": "dormant", "bearer": bearer.entity_id if bearer is not None else (obj.object_id if obj is not None else None), "willing": bool(willing),
                "cl": int(numbers.get("cl") or 1), "pb": int(numbers.get("pb") or 2)})
    if bearer is not None:
        engine._apply_condition(bearer, CARRIED, kit["source"], owner.entity_id, expires_on="UNTIL_REMOVED",
                                data={"zone_id": zone.zone_id, "owner": owner.entity_id, "label": f"A dormant Blossom of {owner.display_name}'s"})
    placed.note(engine, source, owner, f"{owner.display_name} cultivated a Blossom{where}.", targets=(bearer,) if bearer is not None else ())
    mine = _blossoms(engine, owner, ("dormant",))
    while len(mine) > _limit(kit, owner):
        oldest = mine.pop(0)
        if oldest.zone_id != zone.zone_id:
            _wither(engine, oldest, "LIMIT")  # "up to your Proficiency Bonus": the oldest withers
            placed.note(engine, source, owner, f"{owner.display_name}'s oldest dormant Blossom withered (the limit is {_limit(kit, owner)}).")
    return zone


def _wither(engine: Any, zone: Any, reason: str) -> None:
    _release(engine, zone)
    if zone.active:
        placed.drop(engine, zone, reason)


def _release(engine: Any, zone: Any) -> None:
    """The carried condition goes when its Blossom stops being dormant or withers."""
    bearer = engine.state.actors.get(placed.data(zone).get("bearer") or "")
    if bearer is None:
        return
    for iid, condition in list(bearer.conditions.items()):
        if condition.condition_id == CARRIED and (condition.data or {}).get("zone_id") == zone.zone_id:
            del bearer.conditions[iid]
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id,
                                 target_ids=(bearer.entity_id,), payload={"condition_id": CARRIED, "instance_id": iid})


# ------------------------------------------------------------------------------------------------------- blooming
@effect("blossom_delayed")
def delayed(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    cell = getattr(ctx.intent, "destination", None)
    zone = _dormant_at(engine, owner, cell) if (kit is not None and cell is not None) else None
    if zone is None:
        ctx.rider("Delayed Bloom: no dormant Blossom of yours is at that square.")
        return
    if eff.get("free"):
        owner.turn_flags["blossom_free_bloom"] = True
    _bloom(engine, owner, zone, kit, ctx.source)


def _bloom(engine: Any, owner: Any, zone: Any, kit: dict[str, Any], source: str) -> bool:
    d = placed.data(zone)
    config = _config(owner)
    kind = _kind(kit, config)
    bearer = engine.state.actors.get(d.get("bearer") or "")
    reason = _blocker(engine, owner, kit, kind, bearer)
    if reason is not None:
        placed.note(engine, source, owner, f"{owner.display_name}'s Blossom stays dormant: {reason}.")
        return False
    garden = _garden(kit, kind, config, bearer)
    cost = _cost(engine, owner, kit, kind, garden)
    engine._spend_resource(owner, kit["pool"], cost, source)
    if _scripture(owner):
        owner.turn_flags["blossom_discount_used"] = True
    if kind != "seed":
        _release(engine, zone)  # an Exploding Seed stays on its carrier: "a carrier may use its Action to remove it before it detonates"
    where = f" on {bearer.display_name}" if bearer is not None else f" at ({zone.center.x}, {zone.center.y})"
    placed.note(engine, source, owner, f"{owner.display_name}'s Blossom{where} blooms: {BLOOMS[kind][0]} ({cost} CP).", targets=(bearer,) if bearer is not None else ())
    {"medicinal": _medicinal, "thorned": _thorned, "seed": _seed, "trace": _trace, "lotus": _lotus}[kind](engine, owner, zone, kit, source, config, garden)
    return True


def _run(engine: Any, owner: Any, zone: Any, source: str, targets: list[Any], effects: list[dict[str, Any]]) -> None:
    from ..typed_executor import run_effects

    numbers = dict(zone.trigger_profile.get("numbers") or {})
    run_effects(placed.context(engine, owner, source, numbers, targets, action=engine.action_catalog.get(zone.source_definition_id)), effects)


def _dice(count: int, sides: int, dtype: str | None = None, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"applies_to": "target", "dice": {"count": count, "sides": sides}, "flat": 0, "formula": "none"}
    if dtype is None:
        return {"type": "healing", **row, "formula": extra.pop("formula", "none"), **extra}
    return {"type": "damage", **row, "damage_types": [dtype.lower()], **extra}


# --- Medicinal Blossom
def _medicinal(engine: Any, owner: Any, zone: Any, kit: dict[str, Any], source: str, config: dict[str, Any], garden: bool) -> None:
    near = [a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id and _near(engine, zone.center, a, 5)]
    eligible = [a for a in near if a.current_hp < a.maximum_hp and not _used(a, owner, MEDICINE_USED)]
    if not eligible:
        placed.note(engine, source, owner, "Medicinal Blossom: nobody within 5 feet needs healing (or has already had it since a short rest); it withers.")
    else:
        who = min(eligible, key=lambda a: (a.current_hp / max(1, a.maximum_hp), a.entity_id))
        count = placed.cl_row(int(kit["numbers"].get("cl") or 1), MEDICINE_DICE)
        _run(engine, owner, zone, source, [who], [_dice(count, 8, None, formula="key_ability_modifier")])
        # "A creature may benefit from your Medicinal Blossom only once per short rest." (a fight holds no rest: the marker lasts the fight,
        # the way the rest-bound markers below do; combat code names only expiries something removes, tests/test_expiry_names.py)
        engine._apply_condition(who, MEDICINE_USED, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                                data={"owner": owner.entity_id, "label": f"Healed by {owner.display_name}'s Medicinal Blossom"})
    _wither(engine, zone, "BLOOMED")


# --- Thorned Bloom and Traveling Garden
def _thorned(engine: Any, owner: Any, zone: Any, kit: dict[str, Any], source: str, config: dict[str, Any], garden: bool) -> None:
    d = placed.data(zone)
    numbers = kit["numbers"]
    bearer = engine.state.actors.get(d.get("bearer") or "")
    count = placed.cl_row(int(numbers.get("cl") or 1), THORN_DICE)
    trigger = {"id": f"blossom:{zone.zone_id}", "name": "Thorned Bloom", "on": ["enter", "start"], "who": "hostile",
               "effects": [{"type": "save", "ability": "dex", "on_fail": [_dice(count, 6, "PIERCING")], "on_success": [{"type": "half_damage"}]}]}
    bound = bool(garden and bearer is not None and _bind(engine, owner, bearer, zone, numbers, source, bool(d.get("willing"))))
    zone.created_round, zone.duration_rounds, zone.concentration_link = engine.state.round_number, CONCENTRATION_ROUNDS, True
    engine._start_concentration(owner, source)
    if owner.concentration is not None:
        owner.concentration.zone_id = zone.zone_id  # ending the Concentration ends the field
    placed.reshape(
        engine, zone, cells=placed.area(engine, zone.center, "sphere", FIELD_FT), center=zone.center, triggers=[trigger],
        name=f"{owner.display_name}'s Thorned Bloom ({count}d6 Piercing, Dexterity save)" + (" anchored to its bearer" if bound else ""),
        profile={"shape": "sphere", "size_ft": FIELD_FT, "difficult": "all", "color": "#7fa14a", "visual": {"material": "thorns"},
                 **({} if bound else {"anchor_id": None, "follows_owner": False})}, state="field", garden=bound)


def _bind(engine: Any, owner: Any, bearer: Any, zone: Any, numbers: dict[str, Any], source: str, willing: bool) -> bool:
    """Traveling Garden: "anchor it to the creature or object carrying it. An unwilling creature makes a Wisdom saving throw. Failed
    Save: the area moves with the bearer. Successful Save: the area remains in the original space. The creature repeats the saving
    throw at the end of each of its turns; on a success the anchor ends" (the engine's repeat save, data "repeat_save")."""
    dc = int(numbers.get("save_dc") or 10)
    if not willing:
        roll = engine._roll_save(bearer, "WIS", dc, source)
        if roll.total >= dc:
            placed.note(engine, source, owner, f"{bearer.display_name} resisted the Traveling Garden: the thorns stay where they bloomed.", targets=(bearer,))
            return False
    data = {"zone_id": zone.zone_id, "owner": owner.entity_id, "label": f"The thorned field of {owner.display_name}'s Traveling Garden moves with it"}
    if not willing:
        data["repeat_save"] = {"ability": "WIS", "dc": dc, "when": "end"}
    engine._apply_condition(bearer, ANCHORED, source, owner.entity_id, expires_on="UNTIL_REMOVED", data=data)
    return True


@hook("event")
def anchor_ended(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_REMOVED" or (kwargs.get("payload") or {}).get("condition_id") != ANCHORED:
        return None
    for bearer_id in kwargs.get("target_ids") or ():
        _unanchor_free(engine, bearer_id)
    return None


def _unanchor_free(engine: Any, bearer_id: str) -> None:
    """A Traveling Garden whose bearer no longer holds the anchor stays where it is."""
    bearer = engine.state.actors.get(bearer_id)
    for zone in placed.of(engine, "blossom"):
        if zone.trigger_profile.get("anchor_id") == bearer_id and placed.data(zone).get("garden") and not (
                bearer is not None and any(c.condition_id == ANCHORED and (c.data or {}).get("zone_id") == zone.zone_id for c in bearer.conditions.values())):
            placed.unanchor(engine, zone, garden=False)


# --- Exploding Seed
def _seed(engine: Any, owner: Any, zone: Any, kit: dict[str, Any], source: str, config: dict[str, Any], garden: bool) -> None:
    zone.created_round, zone.duration_rounds = engine.state.round_number, 2
    kind = config.get("seed") if config.get("seed") in SEED_TYPES else "piercing"
    placed.reshape(engine, zone, name=f"{owner.display_name}'s Exploding Seed ({SEED_TYPES[kind]}): explodes at the end of {owner.display_name}'s next turn",
                   profile={"color": "#d98a3d"}, state="seed", explode_round=engine.state.round_number + 1, damage=kind)


def _explode(engine: Any, owner: Any, zone: Any) -> None:
    d = placed.data(zone)
    numbers = dict(zone.trigger_profile.get("numbers") or {})
    count = placed.cl_row(int(numbers.get("cl") or 1), SEED_DICE)
    cells = placed.area(engine, zone.center, "sphere", FIELD_FT)
    victims = [a for a in engine.state.actors.values() if a.active and engine._footprint_intersects(a, cells)]
    placed.note(engine, zone.source_definition_id, owner, f"{owner.display_name}'s Exploding Seed at ({zone.center.x}, {zone.center.y}) explodes "
                f"({count}d6 {SEED_TYPES.get(d.get('damage') or 'piercing', 'Piercing')}, Dexterity save).", targets=victims)
    _wither(engine, zone, "EXPLODED")
    if victims:
        _run(engine, owner, zone, zone.source_definition_id, victims, [{
            "type": "save", "ability": "dex", "on_fail": [_dice(count, 6, d.get("damage") or "PIERCING")], "on_success": [{"type": "half_damage"}]}])


# --- Scented Trace
def _trace(engine: Any, owner: Any, zone: Any, kit: dict[str, Any], source: str, config: dict[str, Any], garden: bool) -> None:
    d = placed.data(zone)
    bearer = engine.state.actors.get(d.get("bearer") or "")
    dc = int(kit["numbers"].get("save_dc") or 10)
    pb = int(kit["numbers"].get("pb") or 2)
    if bearer is not None and not d.get("willing"):
        roll = engine._roll_save(bearer, "DEX", dc, source)  # "An unwilling creature makes a Dexterity saving throw when it blooms"
        if roll.total >= dc:
            placed.note(engine, source, owner, f"{bearer.display_name} shook off the Scented Trace: it fails.", targets=(bearer,))
            _wither(engine, zone, "BLOOMED")
            return
    for other in [a for a in engine.state.actors.values() if a.active]:
        traces = [(iid, c) for iid, c in other.conditions.items() if c.condition_id == TRACE_ON and c.source_actor_id == owner.entity_id]
        if other is bearer:
            for iid, _c in traces:
                del other.conditions[iid]  # a second trace on the same creature replaces the first
                engine._append_event("CONDITION_REMOVED", source, actor_id=owner.entity_id, target_ids=(other.entity_id,), payload={"condition_id": TRACE_ON, "instance_id": iid})
    held = [(a, iid, c) for a in engine.state.actors.values() for iid, c in a.conditions.items() if c.condition_id == TRACE_ON and c.source_actor_id == owner.entity_id]
    held.sort(key=lambda row: row[2].applied_sequence)
    while len(held) >= pb:
        creature, iid, condition = held.pop(0)  # "maintain up to PB traces"
        del creature.conditions[iid]
        engine._append_event("CONDITION_REMOVED", source, actor_id=owner.entity_id, target_ids=(creature.entity_id,), payload={"condition_id": TRACE_ON, "instance_id": iid})
    engine._apply_condition(bearer, TRACE_ON, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"owner": owner.entity_id, "label": f"{owner.display_name} senses which way it goes, within {10 * pb} miles"})
    dx, dy = bearer.position.x - owner.position.x, bearer.position.y - owner.position.y
    placed.note(engine, source, owner, f"{owner.display_name} knows the direction of {bearer.display_name}'s Scented Trace ({_compass(dx, dy)}, within {10 * pb} miles, 8 hours).", targets=(bearer,))
    _wither(engine, zone, "BLOOMED")


def _compass(dx: int, dy: int) -> str:
    names = {(0, -1): "north", (1, -1): "north-east", (1, 0): "east", (1, 1): "south-east", (0, 1): "south", (-1, 1): "south-west", (-1, 0): "west", (-1, -1): "north-west"}
    sign = lambda n: (n > 0) - (n < 0)  # noqa: E731
    return names.get((sign(dx), sign(dy)), "here")


# --- Spirit Lotus
def _lotus(engine: Any, owner: Any, zone: Any, kit: dict[str, Any], source: str, config: dict[str, Any], garden: bool) -> None:
    pb, cl = int(kit["numbers"].get("pb") or 2), int(kit["numbers"].get("cl") or 1)
    zone.created_round, zone.duration_rounds, zone.concentration_link = engine.state.round_number, CONCENTRATION_ROUNDS, True
    engine._start_concentration(owner, source)
    if owner.concentration is not None:
        owner.concentration.zone_id = zone.zone_id
    placed.reshape(engine, zone, cells=zone.center, center=zone.center,
                   name=f"{owner.display_name}'s Spirit Lotus (AC {13 + pb}, {5 * cl} HP, acts at the end of {owner.display_name}'s turn)",
                   profile={"anchor_id": None, "follows_owner": False, "color": "#f0a6c8"}, state="lotus", garden=False)


def _lotus_acts(engine: Any, owner: Any, zone: Any) -> None:
    """"At the end of your turn, the Lotus may act on one creature within 30 feet": Restoration (2d8 + key modifier, once per short
    rest per creature), Purifying Pollen (one repeated saving throw against Charmed, Frightened or Poisoned) or Piercing Petals (a
    Cultivation Attack, 3d8 Slashing)."""
    from .repeat_saves import repeatable as _repeatable, save_of as _save_of

    mode = _config(owner).get("lotus") or "auto"
    allies = [a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id and _near(engine, zone.center, a, AURA_FT)]
    hurt = [a for a in allies if a.current_hp < a.maximum_hp and not _used(a, owner, LOTUS_USED)]
    cursed = [a for a in allies if _repeatable(a, ("charmed", "frightened", "poisoned"))]
    foes = [a for a in engine.state.actors.values() if a.active and a.team_id != owner.team_id and _near(engine, zone.center, a, AURA_FT)]
    if mode == "auto":
        mode = "restore" if hurt else "purify" if cursed else "petals"
    source = zone.source_definition_id
    if mode == "restore" and hurt:
        who = min(hurt, key=lambda a: (a.current_hp / max(1, a.maximum_hp), a.entity_id))
        _run(engine, owner, zone, source, [who], [_dice(2, 8, None, formula="key_ability_modifier")])
        engine._apply_condition(who, LOTUS_USED, source, owner.entity_id, expires_on="UNTIL_REMOVED",
                                data={"owner": owner.entity_id, "label": f"Restored by {owner.display_name}'s Spirit Lotus"})
        placed.note(engine, source, owner, f"The Spirit Lotus restores {who.display_name} (Restoration).", targets=(who,))
    elif mode == "purify" and cursed:
        who = cursed[0]
        iid, condition = _repeatable(who, ("charmed", "frightened", "poisoned"))[0]
        save = _save_of(condition)
        roll = engine._roll_save(who, str(save["ability"]).upper(), int(save["dc"]), source)
        placed.note(engine, source, owner, f"The Spirit Lotus's Purifying Pollen gives {who.display_name} another save.", targets=(who,))
        if roll.total >= int(save["dc"]) and iid in who.conditions:
            del who.conditions[iid]
            engine._append_event("CONDITION_REMOVED", source, actor_id=owner.entity_id, target_ids=(who.entity_id,),
                                 payload={"condition_id": condition.condition_id, "instance_id": iid, "repeat_save": True})
    elif mode == "petals" and foes:
        from ..typed_executor import run_effects

        foe = min(foes, key=lambda a: (engine.grid.distance_ft(zone.center, a.position), a.entity_id))
        inner = placed.context(engine, owner, source, dict(zone.trigger_profile.get("numbers") or {}), [foe], action=engine.action_catalog.get(source))
        inner.typed["range_ft"] = AURA_FT
        placed.note(engine, source, owner, f"The Spirit Lotus flings Piercing Petals at {foe.display_name}.", targets=(foe,))
        run_effects(inner, [{"type": "attack", "attack_kind": "cultivation", "on_hit": [_dice(3, 8, "SLASHING")]}])


# ------------------------------------------------------------------------------------------------ Remove Blossom
@effect("blossom_remove")
def remove(ctx: Any, eff: dict[str, Any]) -> None:
    engine, actor = ctx.engine, ctx.actor
    found = _carried(engine, actor)
    if not found:
        return
    zone = found[0]  # a Seed first, then the oldest
    owner = engine.state.actors.get(zone.owner_id)
    _wither(engine, zone, "REMOVED")
    placed.note(engine, ctx.source, actor, f"{actor.display_name} removed a Blossom from itself and threw it away"
                + (f" ({owner.display_name}'s)." if owner is not None and owner is not actor else "."))


# ------------------------------------------------------------------------------------- Ten-Thousand Bloom Scripture
@effect("blossom_scripture")
def scripture(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    engine._remove_condition(owner, SCRIPTURE_ON, ctx.source)
    engine._apply_condition(owner, SCRIPTURE_ON, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"round": engine.state.round_number, "label": "Ten-Thousand Bloom Scripture: twice the dormant Blossoms, two per Cultivate, "
                                  "one free Delayed Bloom a turn, the first Blossom talent each turn costs 1 fewer CP"})


# -------------------------------------------------------------------------------------- Flower of False Death, Corpse flower
def _false_death_ok(engine: Any, reactor: Any, subject: Any) -> bool:
    """"Cause one Blossom already attached to the creature to bloom": one of the reactor's is on it; once per long rest per creature."""
    if subject is None or _used(subject, reactor, FALSE_DEATH_USED):
        return False
    return any(placed.data(zone).get("state") == "dormant" and zone.owner_id == reactor.entity_id for zone in _carried(engine, subject))


def _corpse_ok(engine: Any, reactor: Any, dying: Any) -> bool:
    """"Only one Corpse-Blooming Flower may exist at a time. It cannot be created from ... temporary summons"."""
    if dying is None or dying.summon is not None:
        return False
    return not any(placed.data(zone).get("state") == "corpse" for zone in placed.of(engine, "blossom", owner_id=reactor.entity_id))


def _damaged(engine: Any, reactor: Any, other: Any | None) -> Any:
    """The creature about to drop to 0 HP.  The engine names it while it resolves the reactions to a hit; without that (a reaction
    offered directly) it is ``other`` when that is the reactor's ally, else the reactor itself (the own-drop path passes the attacker)."""
    named = engine.state.actors.get(getattr(engine, "_gate4_damaged_target_id", None) or "")
    if named is not None:
        return named
    return other if other is not None and other is not reactor and other.team_id == reactor.team_id else reactor


@hook("reaction_subject_allowed")
def reaction_gate(engine: Any, reactor: Any, other: Any, row: dict[str, Any]) -> bool | None:
    feature = row.get("feature_id")
    if feature == FALSE_DEATH:  # the reactor's own drop (``other`` is the attacker); an ally's goes through ally_row_allowed
        return _false_death_ok(engine, reactor, _damaged(engine, reactor, other))
    if feature == CORPSE:
        return _corpse_ok(engine, reactor, other)
    return None


@hook("ally_row_allowed")
def ally_gate(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    return _false_death_ok(engine, reactor, subject) if row.get("feature_id") == FALSE_DEATH else None


@effect("blossom_false_death")
def false_death(ctx: Any, eff: dict[str, Any]) -> None:
    """"The creature drops to 1 HP instead of 0 HP" is the row's hold_at_1hp; here: the attached Blossom blooms and withers, the
    creature is Invisible "until the start of its next turn" (it ends "until it attacks or activates a harmful ability": the
    condition's own rule), and "A blossom appears where the creature would have fallen"."""
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    subject = _damaged(engine, owner, ctx.target)
    if kit is None or subject is None:
        return
    attached = [zone for zone in _carried(engine, subject) if zone.owner_id == owner.entity_id and placed.data(zone).get("state") == "dormant"]
    if not attached:
        return
    _wither(engine, attached[0], "BLOOMED")
    engine._apply_condition(subject, FALSE_DEATH_USED, ctx.source, owner.entity_id, expires_on="UNTIL_REMOVED",
                            data={"owner": owner.entity_id, "label": f"{owner.display_name}'s Flower of False Death has saved it once"})
    placed.note(engine, ctx.source, owner, f"A Blossom on {subject.display_name} blooms (Flower of False Death): it stays at 1 HP and vanishes from sight.", targets=(subject,))
    inner = placed.context(engine, owner, ctx.source, ctx.numbers, [subject], action=ctx.action)
    from ..typed_executor import run_effects

    run_effects(inner, [{"type": "condition", "condition": "invisible", "applies_to": "target", "duration": "until_start_of_next_turn",
                         "evidence": "Until the start of its next turn it becomes Invisible until it attacks or activates a harmful ability."}])
    _plant(engine, owner, kit, ctx.source, subject.position, None, True)


@effect("blossom_corpse_flower")
def corpse_flower(ctx: Any, eff: dict[str, Any]) -> None:
    engine, owner = ctx.engine, ctx.actor
    kit = _kit(engine, owner)
    dying = ctx.target
    if kit is None or dying is None or not _corpse_ok(engine, owner, dying):
        return
    placed.place(engine, owner, source=kit["source"], tag="blossom", cells=dying.position, numbers=kit["numbers"], duration_rounds=CONCENTRATION_ROUNDS,
                 name=f"{owner.display_name}'s Corpse-Blooming Flower (Funeral Medicine or Grave Pollen at the start of {owner.display_name}'s turn)",
                 color="#9a6fb0", material="vines", placed={"state": "corpse", "bearer": None, "cl": int(kit["numbers"].get("cl") or 1),
                                                            "pb": int(kit["numbers"].get("pb") or 2)})
    placed.note(engine, ctx.source, owner, f"A spiritual flower erupts from {dying.display_name}'s corpse (Corpse-Blooming Flower).", targets=(dying,))


def _corpse_acts(engine: Any, owner: Any, zone: Any) -> None:
    mode = _config(owner).get("corpse") or "auto"
    source = zone.source_definition_id
    allies = [a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id and _near(engine, zone.center, a, CORPSE_FT)]
    hurt = [a for a in allies if a.current_hp < a.maximum_hp]
    foes = [a for a in engine.state.actors.values() if a.active and a.team_id != owner.team_id and _near(engine, zone.center, a, CORPSE_FT)]
    if mode == "auto":
        mode = "medicine" if hurt else "pollen_poison"
    if mode == "medicine" and hurt:
        who = min(hurt, key=lambda a: (a.current_hp / max(1, a.maximum_hp), a.entity_id))
        placed.note(engine, source, owner, f"Funeral Medicine from the corpse flower heals {who.display_name}.", targets=(who,))
        _run(engine, owner, zone, source, [who], [_dice(2, 8, None, formula="key_ability_modifier")])
    elif mode.startswith("pollen") and foes:
        foe = min(foes, key=lambda a: (engine.grid.distance_ft(zone.center, a.position), a.entity_id))
        dtype = "NECROTIC" if mode.endswith("necrotic") else "POISON"
        placed.note(engine, source, owner, f"Grave Pollen from the corpse flower drifts over {foe.display_name}.", targets=(foe,))
        _run(engine, owner, zone, source, [foe], [{"type": "save", "ability": "con", "on_fail": [_dice(3, 8, dtype)], "on_success": [{"type": "half_damage"}]}])


# ----------------------------------------------------------------------------------------------------------- turns
@hook("turn_start")
def turn_start(engine: Any, actor: Any) -> None:
    _forget_stale(engine, actor)
    kit = _kit(engine, actor)
    if kit is None:
        return
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id == SCRIPTURE_ON and engine.state.round_number - int((condition.data or {}).get("round") or 0) >= SCRIPTURE_ROUNDS:
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": SCRIPTURE_ON, "instance_id": iid})
            placed.note(engine, kit["source"], actor, f"{actor.display_name}'s Ten-Thousand Bloom Scripture ends.")
    mine = _blossoms(engine, actor, ("dormant",))
    while len(mine) > _limit(kit, actor):
        _wither(engine, mine.pop(0), "LIMIT")  # the Scripture's extra room is gone
    for zone in placed.of(engine, "blossom", owner_id=actor.entity_id):
        if placed.data(zone).get("state") == "corpse":
            _corpse_acts(engine, actor, zone)


@hook("turn_end")
def turn_end(engine: Any, actor: Any) -> None:
    for zone in placed.of(engine, "blossom", owner_id=actor.entity_id):
        d = placed.data(zone)
        if d.get("state") == "seed" and engine.state.round_number >= int(d.get("explode_round") or 0):
            _explode(engine, actor, zone)  # "explodes ... at the end of your next turn"
        elif d.get("state") == "lotus":
            _lotus_acts(engine, actor, zone)
    for creature in list(engine.state.actors.values()):
        _unanchor_free(engine, creature.entity_id)


def _forget_stale(engine: Any, actor: Any) -> None:
    """A condition for a Blossom that has withered (the zone ended by its own duration) is cleared at the bearer's turn."""
    for iid, condition in list(actor.conditions.items()):
        if condition.condition_id in (CARRIED, ANCHORED):
            zone = engine.state.zones.get(str((condition.data or {}).get("zone_id")))
            if zone is None or not zone.active:
                del actor.conditions[iid]
                engine._append_event("CONDITION_REMOVED", condition.source_definition_id, actor_id=condition.source_actor_id, target_ids=(actor.entity_id,),
                                     payload={"condition_id": condition.condition_id, "instance_id": iid})
