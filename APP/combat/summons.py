"""Summoned creatures and companions (owner 2026-09-27: "might as well do the summons too, ill want to test it anyway").

Which ability brings which creature, and every creature's numbers, are in the owner-editable
``combat/rules/summons.json``.  A summoner's compiled bundle (combat/factory_compiler.py) carries its creatures: each is
a fighter of its own -- template, actions, opportunity attack, damage and condition immunities -- on the summoner's
side.  None is a primary combatant, so a side still loses when its characters fall, and each takes its turn right
after its summoner's.  A creature present from the start (a ritual that lasts until destroyed, a manifested spirit, a
tamed beast) is on the map when the fight begins; one an ability calls (the Painted Beast, the Ghost Lantern) waits
off the map until that ability is used, and a Concentration summon leaves when the Concentration ends.  A commanded
creature can follow an order for its next turn; an uncommanded one acts on its own instincts, using only its
own stat-block actions and movement. These turns play out automatically through summon_default_turn; mounts and
free summons keep their own turn rules. A destroyed creature leaves the map.
"""

from __future__ import annotations

import json
import copy
import re
from pathlib import Path
from typing import Any

from .gate2_runtime_models import ActionDefinition, ActorState, ActorTemplate, EconomyKind, Position
from .creature_types import from_record as printed_creature_types

RULES_PATH = Path(__file__).resolve().parent / "rules" / "summons.json"
ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
COMMAND_SOURCE = "system:combat.summon_default"


def rules() -> dict[str, Any]:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def _value(formula: Any, names: dict[str, int]) -> int:
    """A number or a formula of pb, cl, key, atk, dc and the summoner's ability modifiers str..cha ("12+pb", "5*cl+key")."""
    if isinstance(formula, (int, float)):
        return int(formula)
    text = str(formula or "0").replace(" ", "")
    if not re.fullmatch(r"[0-9a-z+\-*()]+", text):
        raise ValueError(f"SUMMON_FORMULA_INVALID:{formula}")
    return int(eval(text, {"__builtins__": {}}, dict(names)))  # noqa: S307 -- digits, + - * ( ) and the names above only


def _dice(text: str) -> tuple[int, int]:
    count, _, sides = str(text).lower().partition("d")
    return int(count), int(sides)


def _mod(score: int) -> int:
    return (int(score) - 10) // 2


def _tamer(ids: list[str], mechanics: dict[str, Any], names: list[str]) -> bool:
    wanted = {name.lower() for name in names}
    return any(str((mechanics.get(key) or {}).get("name") or "").lower() in wanted for key in ids)


def _creature_bundle(*, owner_id: str, short: str, entity_id: str, group: str, creature: dict[str, Any], source_id: str,
                     source: dict[str, Any], names: dict[str, int], cl: int, pb: int, extra: list[dict[str, Any]],
                     table: dict[str, Any], owner_saves: dict[str, int] | None = None, reaction_ask: bool = False) -> dict[str, Any]:
    scores = {ability: int((creature.get("scores") or {}).get(ability, 10)) for ability in ABILITIES}
    mods = {ability: _mod(score) for ability, score in scores.items()}
    ac = _value(creature["ac"], names) + sum(int(row.get("ac") or 0) for row in extra)
    hp = max(1, _value(creature["hp"], names) + sum(_value(row.get("hp") or 0, names) for row in extra))
    tag = f"{short}.summon.{entity_id.rsplit('.summon.', 1)[-1]}"
    actions: list[ActionDefinition] = []
    for index, attack in enumerate(creature.get("attacks") or []):
        dice = attack["dice"]
        if dice == "companion":  # the Bonded Companion chassis: 1d8 / 2d8 / 3d8 / 4d8 by CL 1-4 / 5-10 / 11-16 / 17-20
            dice = next(value for level, value in sorted(((int(k), v) for k, v in table.items()), reverse=True) if cl >= level)
        elif attack.get("dice_by_cl"):  # "At CL17, damage becomes 3d8" (Paper Bite): the dice of the highest CL reached
            dice = next(value for level, value in sorted(((int(k), v) for k, v in attack["dice_by_cl"].items()), reverse=True) if cl >= level)
        count, sides = _dice(dice)
        bonus = _value(attack.get("bonus") or 0, names)
        on_hit: list[dict[str, Any]] = [{"type": "damage", "weapon_damage": True}]
        for row in extra:
            if row.get("extra_damage"):
                extra_count, extra_sides = _dice(row["extra_damage"]["dice"])
                on_hit.append({"type": "damage", "dice": {"count": extra_count, "sides": extra_sides},
                               "damage_types": [row["extra_damage"]["damage_type"].lower()], "evidence": row.get("evidence", "")})
        if attack.get("rider"):
            # A form's own ability on a hit (combat/ext/painting_forms.py: the Tiger's Pouncing Stroke, the Serpent's Coiling Stroke).
            on_hit.append({"type": "form_rider", "form": attack["rider"]})
        # Explicit creature-owned hit effects; never infer mechanics from names.
        on_hit.extend(json.loads(json.dumps(attack.get("on_hit_effects") or [])))
        save = attack.get("on_hit_save")
        if save:
            on_hit.append({"type": "save", "ability": save["ability"], "on_fail": [{"type": "condition", "condition": save["condition"],
                                                                                    "applies_to": "target"}], "on_success": []})
        kinds = [str(kind).upper() for kind in attack.get("damage_types") or [attack["damage_type"]]]  # "Slashing or Force": whichever lands hardest
        numbers = {"pb": pb, "cl": cl, "key_mod": names["key"], "attack_bonus": _value(attack["attack_bonus"], names),
                   "save_dc": _value((save or {}).get("dc") or attack.get("save_dc") or 8 + pb, names)}
        typed = {"effects": [{"type": "attack", "attack_kind": "natural", "count": 1, "on_hit": on_hit, "on_miss": []}],
                 "numbers": numbers, "weapon": {"damage": {"count": count, "sides": sides, "modifier": bonus},
                                                 "damage_type": kinds[0], "damage_types": kinds},
                 "duration": {"kind": "instant"}, "range_ft": None, "riders": [], "source": source_id}
        expected = count * (sides + 1) // 2 + bonus
        parameters: dict[str, Any] = {"typed": typed, "expected_damage": expected}
        variants = [(f"action:typed.{tag}.attack{index}", attack["name"], parameters)]
        if attack.get("bloodied_dice"):
            # "Below half HP, this damage becomes 2d8 + your key ability modifier" (Painted Formation)
            weak_count, weak_sides = _dice(attack["bloodied_dice"])
            weak = json.loads(json.dumps(typed))
            weak["weapon"]["damage"] = {"count": weak_count, "sides": weak_sides, "modifier": bonus}
            parameters["hp_band"] = "above_half"
            variants.append((f"action:typed.{tag}.attack{index}.weak", attack["name"],
                             {"typed": weak, "expected_damage": weak_count * (weak_sides + 1) // 2 + bonus, "hp_band": "half_or_less"}))
        for action_id, name, params in variants:
            actions.append(ActionDefinition(source_definition_id=action_id, display_name=name, owner_id=entity_id,
                                            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                                            range_ft=int(attack.get("reach_ft") or 5), parameters=params))
    for special in creature.get("specials") or []:
        # An action of the creature's own that is not an attack (the Crane's Painted Passage, combat/ext/painting_forms.py):
        # for a player's menu, the built-in AI does not use it.
        actions.append(ActionDefinition(
            source_definition_id=f"action:typed.{tag}.{special['id']}", display_name=special["name"], owner_id=entity_id,
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind=special.get("target_kind") or "SELF",
            range_ft=special.get("range_ft"),
            parameters={"typed": {"effects": json.loads(json.dumps(special.get("effects") or [special["effect"]])),
                                  "numbers": {"pb": pb, "cl": cl, "key_mod": names["key"],
                                              **{key: _value(value, names) for key, value in (special.get("numbers") or {}).items()}}, "weapon": None,
                                  "duration": {"kind": "instant"}, "range_ft": special.get("range_ft"), "riders": [], "source": source_id},
                        "expected_damage": 0, "player_only": True, **dict(special.get("parameters") or {})}))
    reactions = []
    guard = next((row["guard"] for row in extra if row.get("guard")), None)
    if guard:
        # Deathless Guard: "A Corpse Servant you command may take the Guard action. Until the start of your next turn, when a
        # creature within 5 feet of the servant is hit by an attack, the servant may use its Reaction to reduce the damage".
        guard_dice = next(value for level, value in sorted(((int(k), v) for k, v in guard["dice_by_cl"].items()), reverse=True) if cl >= level)
        guard_count, guard_sides = _dice(guard_dice)
        actions.append(ActionDefinition(
            source_definition_id=f"action:typed.{tag}.guard", display_name="Guard", owner_id=entity_id, economy=EconomyKind.ACTION,
            resolution_kind="TYPED", target_kind="SELF", range_ft=None,
            parameters={"typed": {"effects": [{"type": "condition", "condition": "guarding", "applies_to": "self",
                                               "expires_on": "START_OF_SELF_NEXT_TURN"}],
                                  "numbers": {"pb": pb, "cl": cl, "key_mod": names["key"]}, "weapon": None, "duration": {"kind": "instant"},
                                  "riders": [], "source": "TAL_DEATH_DEATHLESS_GUARD"}, "expected_damage": 0}))
        reactions.append({"block": "generic", "feature_id": "TAL_DEATH_DEATHLESS_GUARD", "name": "Deathless Guard", "kind": "ally_damaged",
                          "costs": [], "range_ft": int(guard.get("range_ft") or 5), "requires_condition": "condition:typed.guarding",
                          "numbers": {"pb": pb, "cl": cl, "key_mod": names["key"]},
                          "effects": [{"type": "damage_modifier", "dice": {"count": guard_count, "sides": guard_sides},
                                       "formula": str(guard.get("bonus") or "pb")}]})
    innate = creature.get("innate_reaction")
    if innate:
        # A creature's own always-on Reaction, not gated behind a commanded "Guard" action (ironroot 2026-09-28:
        # the Bone Guard's "Guard the Sovereign" -- "When you or an ally within 5 feet of the Bone Guard is
        # targeted by an attack, impose Disadvantage on that attack roll" -- needs no command to be active).
        reactions.append({"block": "generic", "feature_id": f"summon.{group}.innate_reaction", "name": innate["name"],
                          "kind": innate["kind"], "costs": [], "range_ft": int(innate.get("range_ft") or 5),
                          "numbers": {"pb": pb, "cl": cl, "key_mod": names["key"]}, "free": bool(innate.get("free")),
                          "effects": innate["effects"]})
    catalog = list(actions)
    attacks = [row for row in actions if row.target_kind == "HOSTILE_ENTITY"]
    if attacks:
        first = attacks[0]
        opportunity = ActionDefinition(source_definition_id=f"action:typed.{tag}.opportunity_attack", display_name="Opportunity Attack",
                                       owner_id=entity_id, economy=EconomyKind.REACTION, resolution_kind="TYPED",
                                       target_kind="HOSTILE_ENTITY", range_ft=first.range_ft,
                                       parameters={key: value for key, value in json.loads(first.model_dump_json())["parameters"].items() if key != "hp_band"})
        catalog.append(opportunity)
        reactions.append({"feature_id": "opportunity_attack", "name": "Opportunity Attack", "block": "opportunity", "resource_id": "",
                          "action_id": opportunity.source_definition_id, "reach_ft": int(first.range_ft or 5)})
    passives: list[dict[str, Any]] = []
    immune = [str(kind).upper() for kind in creature.get("immune_damage") or []]
    if immune:
        passives.append({"feature_id": f"summon.{group}.immunity", "name": f"{creature['name']} immunities", "block": "defense",
                         "kind": "immunity", "damage_types": immune, "amount": 0, "mundane_only": False, "attacks_only": False,
                         "martial_focus": False, "immune_below_cl": 0, "attack_kinds": [], "melee_only": False})
    resist = [str(kind).upper() for kind in creature.get("resist_damage") or []]
    if resist:
        passives.append({"feature_id": f"summon.{group}.resistance", "name": f"{creature['name']} resistances", "block": "defense",
                         "kind": "resistance", "damage_types": resist, "amount": 0, "mundane_only": False, "attacks_only": False,
                         "martial_focus": False, "immune_below_cl": 0, "attack_kinds": [], "melee_only": False})
    vulnerable = [str(kind).upper() for kind in creature.get("vulnerable_damage") or []]
    if vulnerable:
        passives.append({"feature_id": f"summon.{group}.vulnerability", "name": f"{creature['name']} vulnerabilities", "block": "defense",
                         "kind": "vulnerability", "damage_types": vulnerable, "amount": 0, "mundane_only": False, "attacks_only": False,
                         "martial_focus": False, "immune_below_cl": 0, "attack_kinds": [], "melee_only": False})
    if creature.get("immune_conditions"):
        passives.append({"feature_id": f"summon.{group}.condition_immunity", "name": f"{creature['name']} condition immunities",
                         "block": "condition_immunity", "conditions": [str(name).lower() for name in creature["immune_conditions"]]})
    saves = dict(mods)
    if creature.get("saves_from_owner"):
        # These printed bonuses come from the summoner, not the form's default ability scores.
        selected = ABILITIES if creature["saves_from_owner"] is True else tuple(str(a).upper() for a in creature["saves_from_owner"])
        saves.update({ability: int((owner_saves or {}).get(ability, 0)) for ability in selected if ability in ABILITIES})
    template = ActorTemplate(
        entity_id=entity_id, display_name=creature["name"], team_id="team:factory", primary_combatant=False, owner_id=owner_id,
        creature_types=printed_creature_types(creature),
        armor_class=ac, maximum_hp=hp, speed_ft=int(creature.get("speed") or 30), initiative_bonus=mods["DEX"],
        dexterity_score=scores["DEX"], proficiency_bonus=pb, saving_throws=saves, resources=(),
        action_ids=tuple(row.source_definition_id for row in actions), reaction_ids=(),
    )
    if reaction_ask:
        reactions = [{**row, "ask": True} if not row.get("free") else row for row in reactions]
    return {
        "actor_id": entity_id,
        "actor_template": template.model_dump(mode="json"),
        "action_catalog": [row.model_dump(mode="json") for row in catalog],
        "typed_reactions": reactions,
        "typed_passives": passives,
        "summon": {"owner": owner_id, "group": group, "source": source_id, "arrives": source.get("arrives", "start"),
                   # Own ability-CHECK modifiers, independently of owner-derived saving throws.
                   # Integer data travels with ActorState.summon through commit/reload.
                   "ability_mods": dict(mods),
                   # One of several forms of the same ability ("Choose: Tiger, Crane ... You may maintain one Living Painting"):
                   # the forms share a family; one is out at a time and one Command reaches it.
                   **({"family": source["family"], "family_name": source.get("family_name") or source["family"]} if source.get("family") else {}),
                   # Several groups one Bonus Action commands together (Commanding Death Servants: "command any number of undead
                   # assets created by your Death sphere talents"); unlike a family, all of them may be out at once.
                   **({"command_group": source["command_group"], "command_group_name": source.get("command_group_name") or source["command_group"]}
                      if source.get("command_group") else {}),
                   "command": source.get("command", "bonus_action"), "command_range_ft": int(source.get("command_range_ft") or 60),
                   "range_ft": int(source.get("range_ft") or 30), "concentration": bool(source.get("concentration")),
                   # The printed lifetime this source gives its creature, as one word: "ends_with_summoner" means its
                   # end conditions name no length of time and only its summoner can meet them (combat/rules/summons.json
                   # 'lifetime'; read by combat/ext/summon_lifetime.py). A string, so it travels with ActorState.summon
                   # through commit/reload. Absent = the creature keeps the lifetime its own printed text already gives.
                   **({"lifetime": str(source["lifetime"])} if source.get("lifetime") else {}),
                   **({"duration_rounds": int(source["duration_rounds"])} if source.get("duration_rounds") else {}),
                   **({"size": str(creature["size"]).lower()} if creature.get("size") else {}),
                   **({"light": dict(creature["light"])} if creature.get("light") else {}),  # the table draws its glow
                   **({"footprint": str(creature["footprint"])} if creature.get("footprint") else {}),  # a Large non-mount (Grave Formation)
                   "expected_damage": max([int(row.parameters.get("expected_damage") or 0) for row in attacks] or [0])},
    }


def compile_summons(ids: list[str], mechanics: dict[str, Any], *, owner_id: str, short: str, numbers: dict[str, Any], pb: int,
                    cl: int, plan: dict[str, Any] | None = None, mods: dict[str, int] | None = None,
                    reaction_ask: bool = False, owner_saves: dict[str, int] | None = None) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """(the character's creatures, {ability id: what using it does now, "_options": what the sheet offers}) -- the
    Painted Beast's own action summons the beast instead of making its Ink Fang attack itself (the typed text alone gave
    Ning Kai the beast's bite and AC); ``plan`` ({"counts": {group: n}, "beasts": [keys]}) is the owner's pick for this
    character: fewer than the most (0 leaves a group at home), and which beasts a Tamer brings."""
    table = rules()
    owned = set(ids)
    names = {"pb": pb, "cl": cl, "key": int(numbers.get("key_mod") or 0), "atk": int(numbers.get("attack_bonus") or pb),
             "dc": int(numbers.get("save_dc") or 8 + pb),
             **{ability.lower(): int((mods or {}).get(ability, 0)) for ability in ABILITIES}}  # "2d8 + Constitution modifier"
    plan = dict(plan or {})
    counts = {**{key: value for key, value in plan.items() if key not in ("counts", "beasts", "mount")}, **(plan.get("counts") or {})}
    out: list[dict[str, Any]] = []
    summoning: dict[str, dict[str, Any]] = {}
    groups: list[tuple[str, str, dict[str, Any], dict[str, Any], int]] = []
    options: dict[str, Any] = {"groups": [], "tamer": False, "beast_limit": max(1, pb),
                               "beasts": [{"key": key, "name": row["name"], "cr": row.get("cr")} for key, row in (table.get("beasts") or {}).items()]}
    # General seam (owner 2026-10-13): a printed rule may
    # raise a control pool's limit for particular groups only
    # (Bone General: "+1 Death Control Limit ... only for
    # Corpse Servants or Lesser Corpse Servants"). Each
    # plug-in answer is (extra slots, the groups they fit --
    # None means every group). The printed limit stays what
    # any group may use; a group the extra fits also reads
    # the higher "up to your Death Control Limit" count, so
    # the extra slot is reachable. Eligible restricted
    # slots are spent first (see _within_control_limits),
    # preserving general slots for groups they exclude;
    # excluded groups never use restricted slots.
    from . import ext
    pool_extra: dict[str, tuple[int, set[str] | None, int]] = {}
    for source_id, source in (table.get("sources") or {}).items():
        pool = source.get("control")
        if not pool or pool in pool_extra:
            continue
        reserved, reserved_for, open_slots = 0, None, 0
        for answer in (ext.run("control_limit_extra", pool, tuple(ids)) or []):
            if not answer:
                continue
            extra, allowed = answer
            extra = max(0, int(extra or 0))
            if allowed is None:
                open_slots += extra
            else:
                reserved += extra
                if reserved_for is None:
                    reserved_for = set()
                reserved_for.update(str(group) for group in allowed)
        pool_extra[pool] = (reserved, reserved_for, open_slots)
    for source_id, source in (table.get("sources") or {}).items():
        if source_id in ("tamer", "rider") or (source.get("ability") or source_id) not in owned or not all(need in owned for need in source.get("requires") or []):
            continue
        key = source.get("group") or source["creature"]  # a "group" reuses a creature's stats under its own name (Legion's formations)
        creature = table["creatures"][source["creature"]]
        if source.get("name"):
            creature = {**creature, "name": source["name"]}
        reserved, reserved_for, open_slots = pool_extra.get(source.get("control") or "", (0, None, 0))
        # "You may maintain any number of Corpse Servants up to your Death
        # Control Limit": the count a reserved group reads includes the
        # reserved extra, so Bone General's +1 slot is reachable.
        most = _value(source.get("count", 1), names) + (
            reserved + open_slots if reserved_for is None or key in reserved_for else open_slots)
        count = max(0, min(most, int(counts.get(key, most))))
        groups.append((key, source_id, source, creature, count))
        options["groups"].append({"group": key, "name": creature["name"], "count": count, "max": most,
                                  "arrives": source.get("arrives", "start"), **({"family": source["family"]} if source.get("family") else {}),
                                  **({"control": source["control"], "load": int(source.get("load") or 1)} if source.get("control") else {})})
        if source.get("arrives") == "action":
            summoning[source_id] = {"group": key, "concentration": bool(source.get("concentration")),
                                    **({"placement_range_ft": int(source["range_ft"])}
                                       if source.get("choose_visible_space") and count == 1 else {})}
    groups = _within_control_limits(groups, table, names, counts, options, tuple(ids))
    if _tamer(ids, mechanics, table.get("tamer_talents") or []):
        chosen = plan["beasts"] if "beasts" in plan else (table.get("tamer_default") or [])
        picks = [pick for pick in chosen if pick in table.get("beasts", {})][:max(1, pb)]
        options.update(tamer=True, picked=picks)
        for index, pick in enumerate(picks):
            groups.append((f"beast{index}.{pick}", "tamer", table["sources"]["tamer"], table["beasts"][pick], 1))
    # Mounts (combat/ext/mounts.py; owner 2026-09-29): a rider with the Rider Package starts the fight in the saddle of a
    # Large beast; the sheet's ``mount`` pick ("" = none) replaces the default.
    options["mounts"] = [{"key": key, "name": row["name"]} for key, row in (table.get("beasts") or {}).items() if row.get("mountable")]
    if "BEASTMASTERY_BASE_RIDER_PACKAGE" in owned and all(need in owned for need in (table["sources"].get("rider") or {}).get("requires") or []):
        chosen_mount = plan["mount"] if "mount" in plan else table.get("mount_default", "")
        if chosen_mount in (table.get("beasts") or {}) and table["beasts"][chosen_mount].get("mountable"):
            groups.append((f"mount.{chosen_mount}", "rider", table["sources"]["rider"], table["beasts"][chosen_mount], 1))
            options["mount"] = chosen_mount
        else:
            options["mount"] = ""
    trained = "tianxia.talent.beastmastery.mount_training" in owned  # "Tame Creatures count as trained mounts" (owner)
    riding = trained or "BEASTMASTERY_BASE_RIDER_PACKAGE" in owned
    for key, source_id, source, creature, count in groups:
        extra = [row for row_id, row in (table.get("improvements") or {}).items() if row_id in owned and row.get("creature") == key]
        for index in range(max(0, count)):
            entity_id = f"{owner_id}.summon.{key}.{index + 1}"
            bundle = _creature_bundle(owner_id=owner_id, short=short, entity_id=entity_id, group=key, creature=creature,
                                      source_id=source.get("ability") or source_id, source=source, names=names, cl=cl, pb=pb, extra=extra,
                                      table=table.get("companion_dice_by_cl") or {"1": "1d8"}, owner_saves=owner_saves or mods,
                                      reaction_ask=reaction_ask)
            if count > 1:
                bundle["actor_template"]["display_name"] = f"{creature['name']} {index + 1}"
            if creature.get("mountable") and (source_id == "rider" or riding):
                # A Large beast its owner can ride: it is drawn 2x2 (add_to_match) and can carry a rider (combat/ext/mounts.py).
                # 5.5e Mounted Combat: only a trained animal (the Rider Package's steed, or any Tame Creature with Mount
                # Training) is a Controlled Mount; any other is an Independent Mount that acts on its own turn.
                bundle["summon"].update(mountable=True, size=str(creature.get("size") or "large"),
                                        trained=bool(source_id == "rider" or trained), starts_mounted=bool(source_id == "rider"))
            if source.get("appearance_traits"):
                bundle["summon"]["appearance_traits"] = copy.deepcopy(source["appearance_traits"])
            # Compose pure extensions on the individual bundle before sealing.
            from . import ext
            bundle = ext.transform("compile_summon", copy.deepcopy(bundle), {
                "owned_ids": tuple(ids), "creature_key": source.get("creature") or key, "group": key,
                "source": copy.deepcopy(source), "plan": copy.deepcopy(plan),
                "numbers": dict(numbers), "pb": pb, "cl": cl})
            if not isinstance(bundle, dict) or bundle.get("actor_id") != entity_id:
                raise ValueError("compile_summon must retain the creature identity")
            out.append(bundle)
    summoning["_options"] = options
    return out, summoning


def _within_control_limits(groups: list[tuple[str, str, dict[str, Any], dict[str, Any], int]], table: dict[str, Any],
                           names: dict[str, int], counts: dict[str, Any], options: dict[str, Any],
                           owned: tuple[str, ...] = ()) -> list[tuple[str, str, dict[str, Any], dict[str, Any], int]]:
    """General seam (rider lane C14, BLOCKED_CENSUS.md row 26): groups whose source names a shared ``control`` pool
    (summons.json "control_limits": {"death": {"limit": "pb"}}) share it -- each creature costs its source's ``load``
    (Death: "Your Death Control Limit equals your Proficiency Bonus ... Corpse Servant: 1 Control Load ... Grave Formation:
    3"; "You cannot willingly exceed your Death Control Limit"). The owner's own counts (the sheet plan) are kept first, in
    the table's order, as far as the pool allows; the other groups then fill what is left, the heaviest asset first (one Grave
    Formation before a fourth Corpse Servant). Groups without ``control`` are untouched, and a pool with a single group gives
    exactly the counts it gave before.

    A printed rule may add slots to a pool for particular groups only (Bone General: "+1 Death Control Limit, but the
    extra capacity can be used only for Corpse Servants or Lesser Corpse Servants"). ``ext.run("control_limit_extra",
    pool, owned)`` answers with ``(extra slots, the groups they fit)`` -- ``None`` as the second item means every group.
    The printed limit stays what any group may use. Eligible groups spend restricted slots first, preserving
    unrestricted capacity for later requested groups that cannot use the bonus. Excluded groups never touch it."""
    limits = table.get("control_limits") or {}
    from . import ext
    pools = {str(source["control"]) for _key, _sid, source, _creature, _count in groups if source.get("control")}
    if not pools:
        return groups
    out = list(groups)
    for pool in sorted(pools):
        left = _value((limits.get(pool) or {}).get("limit", "pb"), names)
        reserved = 0
        reserved_for: set[str] | None = None
        open_slots = 0
        for answer in (ext.run("control_limit_extra", pool, owned) or []):
            if not answer:
                continue
            extra, allowed = answer
            extra = max(0, int(extra or 0))
            if allowed is None:
                open_slots += extra
            else:
                reserved += extra
                if reserved_for is None:
                    reserved_for = set()
                reserved_for.update(str(group) for group in allowed)
        members = [index for index, row in enumerate(out) if row[2].get("control") == pool]
        explicit = [index for index in members if out[index][0] in counts]
        rest = sorted((index for index in members if index not in explicit), key=lambda index: (-int(out[index][2].get("load") or 1), index))
        for index in [*explicit, *rest]:
            key, source_id, source, creature, count = out[index]
            load = max(1, int(source.get("load") or 1))
            if reserved_for is not None and key not in reserved_for:
                available = left + open_slots
            else:
                available = left + open_slots + reserved
            fits = min(count, max(0, available) // load)
            spent = fits * load
            from_reserved = min(spent, reserved) if reserved_for is None or key in reserved_for else 0
            reserved -= from_reserved
            spent -= from_reserved
            from_base = min(spent, left)
            left -= from_base
            remainder = spent - from_base
            from_open = min(remainder, open_slots)
            open_slots -= from_open
            out[index] = (key, source_id, source, creature, fits)
        for row in options["groups"]:
            match = next((entry for entry in out if entry[0] == row["group"] and entry[2].get("control") == pool), None)
            if match is not None:
                row.update(count=match[4], pool_limit=_value((limits.get(pool) or {}).get("limit", "pb"), names))
    return out


# ------------------------------------------------------------------ engine side
def register(engine: Any, bundle: dict[str, Any]) -> None:
    """Add a summoner's creatures to the engine's templates, actions and reaction rows (before the match exists)."""
    from .factory_compiler import register_bundle

    for creature in bundle.get("summons") or []:
        actor_id = register_bundle(engine.actor_templates, engine.action_catalog, creature)
        engine.typed_actor_ids.add(actor_id)
        engine.typed_reaction_rows[actor_id] = list(creature.get("typed_reactions") or [])
        engine.typed_passive_rows[actor_id] = list(creature.get("typed_passives") or [])
        engine.summon_records[actor_id] = dict(creature["summon"])
        # Scope footprint authority to this engine/bound bundle. A later load of
        # an older bundle with the same actor ID must not inherit another save's size.
        from .footprint_registry import resolve_actor_footprint
        footprint, _ = resolve_actor_footprint(actor_id, summon_record=creature['summon'])
        engine.__dict__.setdefault('_summon_footprints', {})[actor_id] = footprint


def add_to_match(engine: Any, actors: dict[str, ActorState], order: list[str], teams: dict[str, str]) -> list[str]:
    """Each summoner's creatures: after the summoner in initiative, on its side; one present from the start is placed
    on the nearest free squares to it, one called later waits off the map (inactive) at its summoner's square."""
    records = getattr(engine, "summon_records", {})
    # The engine is reconstructed from this fight's saved bundles on reload.
    # Resolve sizes here, before placement, into its own registry. Never consult
    # current rules for an old bundle: an absent size retains its one-cell shape.
    from .footprint_registry import resolve_actor_footprint

    for actor_id, record in records.items():
        engine.actor_footprints[actor_id], _ = resolve_actor_footprint(actor_id, summon_record=record)
    placed: list[str] = []
    for actor_id, record in records.items():
        owner = actors.get(record["owner"])
        if owner is None:
            continue
        template = engine.actor_templates[actor_id]
        present = record["arrives"] != "action"
        footprint = engine._footprint(actor_id)
        if footprint.width_cells > 1 or footprint.height_cells > 1:
            # A starting rider may share the steed's occupied squares; every summon otherwise uses its data footprint.
            position = _free_anchor_near(engine, owner.position, actors, footprint,
                                         around=owner.position if record.get("starts_mounted") else None) if present else owner.position
            if present and position is None and record.get("starts_mounted"):
                # A roof may have room for the rider but not its steed. Place
                # the creature nearby without inventing a saddle across floors.
                position = _free_anchor_near(engine, owner.position, actors, footprint)
        else:
            position = _free_square_near(engine, owner.position, actors) if present else owner.position
        if position is None:
            present, position = False, owner.position
        actors[actor_id] = ActorState(
            entity_id=actor_id, display_name=template.display_name, team_id=owner.team_id, primary_combatant=False,
            creature_types=template.creature_types, size_category=template.size_category,
            owner_id=owner.entity_id, armor_class=template.armor_class, maximum_hp=template.maximum_hp,
            current_hp=template.maximum_hp, position=position, speed_ft=template.speed_ft,
            movement_remaining_ft=template.speed_ft if present else 0, initiative_bonus=template.initiative_bonus,
            dexterity_score=template.dexterity_score, proficiency_bonus=template.proficiency_bonus,
            saving_throws=dict(template.saving_throws), skills=dict(template.skills), resources={}, resource_maximums={},
            action_ids=template.action_ids, reaction_ids=template.reaction_ids, active=present,
            action_available=False, bonus_action_available=False, reaction_available=present,
            summon={**record, "status": "present" if present else "waiting", "commanded": False},
        )
        teams[actor_id] = owner.team_id
        placed.append(actor_id)
        if present and record.get("starts_mounted") and record.get("mountable") and record.get("size") == "large":
            from .ext import mounts

            if owner.position.z == position.z and set(engine._actor_cells(owner)) < set(engine._actor_cells(actors[actor_id])):
                mounts.start_bond(owner, actors[actor_id])  # the rider starts in the saddle (combat/ext/mounts.py)
    for actor_id in placed:
        owner_id = actors[actor_id].owner_id
        after = max(index for index, row in enumerate(order) if row == owner_id or actors[row].owner_id == owner_id
                    and actors[row].summon is not None)
        order.insert(after + 1, actor_id)
    return placed


def _free_anchor_near(engine: Any, anchor: Position, actors: dict[str, ActorState], footprint: Any, *,
                      around: Position | None = None, toward: Position | None = None,
                      within_ft: int | None = None) -> Position | None:
    """The nearest anchor whose whole footprint is on the map, unblocked and free of other creatures; with ``around``, only
    an anchor whose footprint holds that square (the rider's own, which does not count as taken).
    Placement uses full creature volumes and supported elevations (the owner's
    floor or the ground). A starting saddle must be on the rider's elevation;
    creatures above/below another floor do not occupy its space. The same seam
    serves starting companions and automatic action summons, of every size.
    Active life state alone does not occupy space: the general battlefield-presence
    query also governs automatic summon placement, including restored creatures."""
    from itertools import product
    from .space import volume

    taken = {cell for other in actors.values() if other.active and engine._on_battlefield(other)
             and (around is None or other.position != around)
             for cell in volume(other.position, engine._footprint(other))}
    best = None
    elevations = (anchor.z,) if around is not None else tuple(dict.fromkeys((anchor.z, 0)))
    for z, y in product(elevations, range(engine.grid.height)):
        for x in range(engine.grid.width):
            candidate = Position(x=x, y=y, z=z)
            cells = footprint.occupied_cells(candidate) if footprint is not None else ((x, y),)
            if around is not None and (around.x, around.y) not in cells:
                continue
            if not engine.grid.volume_legal(candidate, footprint=footprint, occupied_cells=taken):
                continue
            if z and not (engine.grid.roof_supported(candidate, footprint) or any(
                    engine.grid.terrain_at((cx, cy, z - 1), "BLOCKED") for cx, cy in cells)):
                continue
            distance = engine.grid.distance_ft(anchor, candidate)
            if (distance == 0 and around is None) or (within_ft is not None and distance > within_ft):
                continue
            key = (distance, engine.grid.distance_ft(candidate, toward) if toward is not None else 0, y, x, z)
            if best is None or key < best[0]:
                best = (key, candidate)
    return best[1] if best else None


def _free_square_near(engine: Any, anchor: Position, actors: dict[str, ActorState], *, toward: Position | None = None,
                      within_ft: int | None = None) -> Position | None:
    """One-cell placement uses the same physical-presence contract as whole footprints."""
    return _free_anchor_near(engine, anchor, actors, None, toward=toward, within_ft=within_ft)


def never_entered_play(actor: Any) -> bool:
    """Whether ``actor`` is a summon made at fight start for a later call that has not appeared yet.

    The engine's own marker: add_to_match records such a creature with status "waiting" (inactive, standing on its
    owner's square), and only summon() or a SUMMON_APPEARED event makes it "present"; nothing sets "waiting" again.
    Defeated ("destroyed"), dismissed and hidden creatures are never waiting, and a primary fighter has no summon
    record. General seam for presentation shortcuts (combat/presentation.py project, combat/gate5_service.py
    presentation, combat/tabletop_service.py state): such a creature is off the map and takes part in nothing, so
    its action rows, feature rows and menu work are skipped until the read after it is summoned. Accepts an engine
    actor or a saved/projected actor dict.
    """
    summon = actor.get("summon") if isinstance(actor, dict) else getattr(actor, "summon", None)
    return isinstance(summon, dict) and summon.get("status") == "waiting"


def owned_by(engine: Any, owner_id: str, group: str | None = None) -> list[ActorState]:
    """The summoner's creatures; ``group`` is one group's (a Living Painting's Tiger) or a whole family's (every form)."""
    return [actor for actor in engine.state.actors.values()
            if actor.summon is not None and actor.summon["owner"] == owner_id
            and (group is None or group in (actor.summon["group"], actor.summon.get("family"), actor.summon.get("command_group")))]


def commandable(engine: Any, owner: ActorState, group: str) -> list[ActorState]:
    """The group's creatures a command now reaches: on the map, not yet commanded this round, within range.

    A plug-in may narrow that set with the ``command_reachable`` hook
    (``ext.run("command_reachable", engine, owner, group, creature)``; False keeps the creature out of the
    command), the one seam a printed "it cannot be commanded" rule uses. Absent an answer the group's own
    reach decides, so every existing command is unchanged.
    """
    from . import ext

    reach = [actor for actor in owned_by(engine, owner.entity_id, group)
             if actor.active and actor.summon["status"] == "present" and not actor.summon["commanded"]
             and engine._distance_actor_to_actor(owner, actor) <= int(actor.summon["command_range_ft"])]
    if not ext.has("command_reachable"):
        return reach
    return [actor for actor in reach
            if False not in ext.run("command_reachable", engine, owner, group, actor)]


def on_turn_start(engine: Any, actor: ActorState) -> bool:
    """Called as any turn begins; True when this creature's turn passes by itself.

    Not on the map: passes. Uncommanded: it takes an instinct turn with its own stat-block actions.
    Commanded: a one-turn directive plays out automatically; without a directive, the owner drives it.
    Mounts and free summons retain their own turn rules. A summoner's turn clears last round's commands."""
    # Timed departures belong exclusively to ext.summon_lifetime's early
    # turn_boundary_start hook, before any turn-start gameplay.
    for creature in owned_by(engine, actor.entity_id):
        creature.summon["commanded"] = False
    record = actor.summon
    if record is None:
        return False
    if not actor.active or record["status"] != "present":
        return True
    from .ext import run_strict
    policies = run_strict("summon_turn_policy", engine, actor)
    if any(not isinstance(policy, dict) or policy != {"skip": True} for policy in policies):
        raise ValueError("summon_turn_policy must return None or {'skip': True}")
    if policies:
        actor.action_available = actor.bonus_action_available = actor.reaction_available = False
        actor.movement_remaining_ft = 0
        return True
    actor.bonus_action_available = False  # a commanded creature takes one action from its stat block, no bonus action
    if record.get("mountable"):
        from .ext import mounts  # a Controlled Mount acts on its rider's turn, so its own passes (5.5e Mounted Combat)

        if mounts.turn_passes(engine, actor):
            return True
        if record["command"] == "mount":  # ridden independently, or riderless: it acts as it likes
            return False
    if record["command"] == "free":
        return False
    if record["commanded"]:
        if record.get("directive") is None:
            return False  # the owner drives this turn with the stat block
        # A directive from the command plays out automatically for this one turn.
    from .ext import run_strict
    if not record["commanded"]:
        run_strict("uncommanded_summon_turn", engine, actor)
    behavior = "DIRECTIVE" if record.get("directive") else "INSTINCT"
    engine._append_event("COMPANION_DEFAULT_APPLIED", COMMAND_SOURCE, actor_id=actor.entity_id, payload={"behavior": behavior})
    # No Dodge default: the summon_default_turn hook (combat/ext/summon_instinct.py) takes its instinct or directive turn.
    run_strict("summon_default_turn", engine, actor, behavior)
    actor.action_available = False
    actor.movement_remaining_ft = 0
    return True


def on_defeat(engine: Any, target: ActorState) -> None:
    if target.summon is not None and target.summon["status"] == "present":
        target.summon["status"] = "destroyed"


def on_concentration_end(engine: Any, owner: ActorState, source_id: str, reason: str) -> None:
    """A Concentration summon (the Painted Beast) leaves when its summoner's Concentration on it ends.  One of several
    forms of an ability (a Living Painting's Tiger) leaves only when the Concentration on its own form's action ends:
    that action names its group, so calling the Crane while the Tiger is out takes the Tiger away and not the Crane."""
    form = getattr(engine, "action_catalog", {}).get(source_id)
    group = (getattr(form, "parameters", None) or {}).get("summon_group") if form is not None else None
    for creature in owned_by(engine, owner.entity_id):
        record = creature.summon
        named = record["group"] == group if group else source_id.split("#", 1)[0].endswith("." + record["source"])
        if record["concentration"] and named and record["status"] == "present" and creature.active:
            _leave(engine, creature, "dismissed", reason)


def dismiss(engine: Any, creature: ActorState, reason: str, *, log: str | None = None) -> None:
    """Recorded departure shared by lifetime hooks and other summon lifecycle callers."""
    _leave(engine, creature, 'dismissed', reason, log=log)


def _leave(engine: Any, creature: ActorState, status: str, reason: str, *, log: str | None = None) -> None:
    if not creature.summon or creature.summon.get("status") != "present":
        return
    creature.active = False
    creature.action_available = creature.bonus_action_available = creature.reaction_available = False
    creature.movement_remaining_ft = 0
    creature.summon["status"] = status
    engine._append_event("SUMMON_DISMISSED", creature.summon["source"], actor_id=creature.entity_id,
                         payload={"owner": creature.summon["owner"], "reason": reason, **({"log": log} if log else {})})


def summon(engine: Any, owner: ActorState, group: str, source_id: str, near: Position | None = None,
           *, destination: Position | None = None, action: Any = None) -> list[str]:
    """Bring the group's creatures onto the map beside the summoner (toward ``near``, e.g. the nearest foe), fresh.
    Calling one that is already out calls it again ("only one Painted Beast may be active at a time")."""
    arrived: list[str] = []
    for creature in owned_by(engine, owner.entity_id, group):
        if destination is not None:
            from .cell_placement import legal
            if action is None or not legal(engine, owner, action, destination):
                engine._append_event('SUMMON_BLOCKED', source_id, actor_id=owner.entity_id,
                    target_ids=(creature.entity_id,), payload={'reason': 'the chosen space is unavailable'})
                continue
        record = creature.summon
        for other in owned_by(engine, owner.entity_id, record.get("family")) if record.get("family") else []:
            if other is not creature and other.active and other.summon["group"] != record["group"] and other.summon["status"] == "present":
                _leave(engine, other, "dismissed", "REPLACED")  # "You may maintain one Living Painting": the new form takes its place
        was_active = creature.active
        if creature.active:
            creature.active = False  # re-placed below, anywhere in range
        spot = destination if destination is not None else _free_anchor_near(
            engine, owner.position, engine.state.actors, engine._footprint(creature),
            toward=near, within_ft=int(record["range_ft"]))
        if spot is None:
            creature.active = was_active
            engine._append_event("SUMMON_BLOCKED", source_id, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                                 payload={"reason": "no free space in range"})
            continue
        from . import ext

        if False in ext.run("summon_check", engine, owner, creature, spot, was_active, source_id):  # a plug-in's effect stops it (Formations: Spirit-Lock, Mountain-Sealing)
            creature.active = was_active
            engine._append_event("SUMMON_BLOCKED", source_id, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                                 payload={"reason": "an effect prevents the summoning"})
            continue
        creature.position = spot
        creature.current_hp, creature.temporary_hp = creature.maximum_hp, 0
        # A fresh body ends the old body's effects through the same lifecycle
        # as dismissal/expiry. Never silently discard subscriber-owned links.
        from . import concentration
        concentration.end_all_copies(engine, creature, "REPLACED")
        for iid, condition in list(creature.conditions.items()):
            engine._remove_condition_instance(creature, iid, source_id, expected=condition)
        for mid, modifier in list(creature.modifiers.items()):
            engine._remove_modifier_instance(creature, mid, source_id, expected=modifier)
        creature.active = True
        creature.reaction_available = True
        creature.action_available = creature.bonus_action_available = False  # it acts on its own turn, after this one
        creature.movement_remaining_ft = 0
        record.update(status="present", commanded=False)
        # The approved h64 rider's lifetime data. Boundary consumption lives in
        # one plug-in; no late on_turn_start sweep remains here.
        form = engine.action_catalog.get(source_id)
        if form is None:
            form = engine.action_catalog.get(source_id.split('#', 1)[0])
        typed = (getattr(form, 'parameters', None) or {}).get('typed') or {}
        duration = typed.get('duration') or {}
        if str(duration.get('kind') or '').lower() in {'rounds', 'minutes'}:
            from .typed_executor import duration_expiry
            amount = int(duration.get('amount') or 1)
            kind = str(duration['kind']).lower()
            record['expires_on'] = duration_expiry(engine, duration)
            record['duration_text'] = f"{amount} {kind[:-1] if amount == 1 else kind}"
        engine._append_event("SUMMON_APPEARED", source_id, actor_id=owner.entity_id, target_ids=(creature.entity_id,),
                             payload={"position": spot.model_dump(mode="json"), "group": group})
        ext.run_strict("summon_appeared", engine, owner, creature, source_id)
        arrived.append(creature.entity_id)
    return arrived


def command(engine: Any, owner: ActorState, group: str, source_id: str, directive: dict[str, Any] | None = None) -> list[str]:
    commanded = [creature.entity_id for creature in commandable(engine, owner, group)]
    for creature_id in commanded:
        record = engine.state.actors[creature_id].summon
        record["commanded"] = True
        if directive is not None:  # one turn of orders: {"kind": "attack", "target_id": ...} etc.
            from .ext.summon_instinct import set_directive
            set_directive(record, directive["kind"], target_id=directive.get("target_id"), action_id=directive.get("action_id"))
    engine._append_event("SUMMONS_COMMANDED", source_id, actor_id=owner.entity_id, target_ids=tuple(commanded), payload={"group": group})
    return commanded


def owner_actions(bundle_summons: list[dict[str, Any]], *, owner_id: str, short: str, numbers: dict[str, Any]) -> list[ActionDefinition]:
    """One "Command" Bonus Action per commanded group (tamed beasts need none); the forms of one ability share one, and so do
    the groups of one ``command_group`` (every Death servant: one command reaches all of them)."""
    out = []
    seen: set[str] = set()

    def key_of(record: dict[str, Any]) -> str:
        return record.get("command_group") or record.get("family") or record["group"]

    for creature in bundle_summons:
        record = creature["summon"]
        key = key_of(record)
        if record["command"] != "bonus_action" or key in seen:
            continue
        seen.add(key)
        name = record.get("command_group_name") or record.get("family_name") or creature["actor_template"]["display_name"].rstrip(" 0123456789")
        members = [other for other in bundle_summons if key_of(other["summon"]) == key]
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.command.{key}", display_name=f"Command {name}", owner_id=owner_id,
            economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", range_ft=None,
            parameters={"typed": {"effects": [{"type": "command_summons", "group": key}], "numbers": numbers, "weapon": None,
                                  "duration": {"kind": "instant"}, "riders": [], "source": record["source"]},
                        # The whole group acts on one command (fight audit 2026-09-29: five Corpse Servants valued as one
                        # lost every turn to a single Bonded Spirit and stood Dodging all fight).
                        "summon_command": key,
                        "expected_damage": sum(int(other["summon"].get("expected_damage") or 0) for other in members)
                        if record.get("command_group") else
                        max(sum(int(other["summon"].get("expected_damage") or 0) for other in members
                                if other["summon"]["group"] == group)
                            for group in {other["summon"]["group"] for other in members})}))
    return out
