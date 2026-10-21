"""Core maneuvers the category talents change (docket 2026-09-28; owner 2026-09-28: "Missing core maneuvers so category
talents can attach: Snipe Shot (Sniper), ... Barrage"; Batter found the same way -- Heaven-Shaking Batter had nothing to
change). Each is built from the character's own weapon attacks, then its sphere's talents are applied to it by the same
modifier rules as every other ability (combat/factory_compiler.py apply_modifiers), through the compiler's "maneuvers" hook.

  Batter (Berserker)     "A Batter is a Special Attack made with: a melee weapon; an unarmed strike; a natural weapon; a
                         thrown weapon. On a hit that deals damage, the target becomes Battered until the end of your next
                         turn." -- "Batter: <weapon>", one of the Attack action's attacks (Extra Attack keeps the others).
                         Exertion talents ("When Batter deals damage ...") change it.
  Snipe Shot (Sniper)    "When you take the Attack action, you may replace one attack with a Snipe Shot ... choose one Snipe
                         talent you know and apply it to that attack" -- "Snipe Shot: <weapon> + <Snipe talent>", one per
                         talent (a Snipe Shot with none is the plain attack, so it is not offered on its own).
  Barrage (Barrage)      "Make one ranged weapon attack with a thrown or ranged weapon. You may then make one additional
                         ranged weapon attack with the same weapon as a Bonus Action" (the follow-up adds no positive
                         ability modifier to damage) -- "Barrage: <weapon>" (a Special Attack of the Attack action), then
                         "Barrage follow-up: <weapon>" that turn. One Blitz talent per Barrage ("apply only one Blitz talent
                         to one Barrage").
  Broken-Rhythm Strike   "Make an Unarmed Strike using the Damage option, an improvised melee weapon attack, or a melee
                         weapon attack" (Drunken Style) -- "Broken-Rhythm Strike: <weapon>", one per melee, unarmed or natural
                         attack, on a hit the target is Off-Rhythm from you and a miss by 5 or less may leave it a False
                         Opening. Eleven printed talents say "with Broken-Rhythm Strike", so the maneuver is published here
                         and not from combat/ext/drunken_style.py: built there it was invisible to the compiler's modifier
                         pass and every one of those talents reported "no matching ability" and never ran.
                         "sphere_grants": False -- this is a talent the character takes, not a base ability the sphere gives.

A spec key this module reads: "on_miss" (a list of rows put on the maneuver's own attack roll, as "on_hit" is).
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

BATTERED = "condition:typed.battered"

MANEUVERS = (
    {"key": "batter", "name": "Batter", "records": ("TAL_BERSERKER_BATTER",), "sphere": "tianxia.sphere.berserker",
     "kinds": ("melee", "unarmed", "natural", "thrown"), "plain": True, "on_hit": [{"type": "batter"}], "one_talent": True, "source_record": True},
    {"key": "snipe", "name": "Snipe Shot", "records": ("TAL_SNIPER_SNIPER_TRAINING",), "sphere": "tianxia.sphere.sniper",
     "kinds": ("ranged", "thrown"), "plain": False, "on_hit": [], "one_talent": True},
    {"key": "barrage", "name": "Barrage", "records": (), "sphere": "tianxia.sphere.barrage",
     "kinds": ("ranged", "thrown"), "plain": True, "on_hit": [], "one_talent": True, "follow_up": True},
    {"key": "broken_rhythm", "name": "Broken-Rhythm Strike", "records": ("TAL_DRUNKEN_STYLE_BROKEN_RHYTHM_STRIKE",),
     "sphere": "tianxia.sphere.drunken_style", "kinds": ("melee", "unarmed", "natural"), "plain": True,
     "sphere_grants": False, "one_talent": False, "source_record": True,
     # "Hit: ... the target becomes Off-Rhythm from you": the mark itself is combat/ext/drunken_style.py's
     # drunken_off_rhythm effect, named here the way Batter names brute_riders' "batter" effect.
     "on_hit": [{"type": "drunken_off_rhythm", "applies_to": "target"}],
     "on_miss": [{"type": "if_missed_by", "max": 5, "effects": [{"type": "drunken_false_opening", "asked": True}],
                  "evidence": "Miss by 5 or Less: You may choose to create a False Opening for the target."}]},
)


def _owns(spec: dict[str, Any], info: dict[str, Any]) -> bool:
    """Whether this character takes the maneuver. Owning the printed talent is enough; a base ability ("records" empty)
    is granted by holding the Sphere, unless the spec says "sphere_grants": False."""
    owned = set(info["owned"])
    if owned & set(spec["records"]):
        return True
    return bool(spec.get("sphere_grants", True)) and spec["sphere"] in set(info.get("spheres") or ())


@hook("maneuvers")
def maneuvers(info: dict[str, Any]) -> dict[str, Any] | None:
    from .weapon_actions import weapon_attacks, delivery_range_ft
    from .. import factory_compiler as fc
    from ..gate2_runtime_models import EconomyKind

    mechanics, actor_id = info["mechanics"], info["actor_id"]
    out_actions: list[Any] = []
    out_rows: list[dict[str, Any]] = []
    weapons = weapon_attacks(info["actions"], actor_id)
    for spec in MANEUVERS:
        if not _owns(spec, info):
            continue
        # Another plug-in may have built this maneuver already (auto/gu's Batter, delivered with the unarmed strike): that
        # one stays; the weapons it leaves out get theirs here, and the talents it does not handle apply to all of them.
        existing = [row for row in info["actions"] if str(((row.parameters or {}).get("typed") or {}).get("source") or "") in spec["records"]
                    and row.owner_id == actor_id]
        covered = {"unarmed", "natural"} if any(
            any(isinstance(e, dict) and e.get("type") == "attack" for e in ((row.parameters or {}).get("typed") or {}).get("effects") or [])
            for row in existing) else set()
        fitting = [(row, typed, attack, False) for row, typed, attack, kind in weapons if kind in spec["kinds"] and kind not in covered]
        for row in existing:
            typed = (row.parameters or {}).get("typed") or {}
            attack = next((e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
            if attack is not None:
                fitting.append((row, typed, attack, True))
        if not fitting:
            continue
        target_name = fc._norm_name(spec["name"])
        handled = {key for key, row in fc.feature_status().items() if row.get("status") == "applied"}  # another plug-in runs them
        wanted = [mid for mid in dict.fromkeys(info["owned"]) if mid not in info["automated"] and mid not in handled
                  and any(fc._norm_name(t) == target_name for t in (((mechanics.get(mid) or {}).get("modifier") or {}).get("targets") or []))]
        fake_key = f"maneuver:{spec['key']}"
        built: dict[str, dict[str, Any]] = {}
        for row, typed, attack, already in fitting:
            name = row.display_name[:-len(" attack")] if row.display_name.endswith(" attack") else row.display_name
            key = f"maneuver-built:{spec['key']}:{row.source_definition_id}"
            if already:  # its own action and name ("Batter"); only the talents' variants are added
                built[key] = {"action_id": row.source_definition_id, "name": row.display_name, "economy": "action", "target_kind": row.target_kind,
                              "range_ft": delivery_range_ft(row), "costs": list(row.costs), "typed": copy.deepcopy(typed),
                              "mechanic": {"name": row.display_name, "sphere_id": spec["sphere"], "duration": {"kind": "instant"}},
                              "modifiers": [], "variants": [], "_action": row, "_existing": True}
                continue
            own = [{**copy.deepcopy(hit), "first_hit_only": True} for hit in spec["on_hit"]]
            new_attack = {**copy.deepcopy(attack), "on_hit": [*copy.deepcopy(attack.get("on_hit") or []), *own]}
            if spec.get("on_miss"):
                new_attack["on_miss"] = [*copy.deepcopy(attack.get("on_miss") or []), *copy.deepcopy(spec["on_miss"])]
            action_id = f"{row.source_definition_id}.{spec['key']}"
            new_typed = {**copy.deepcopy(typed), "effects": [new_attack if e is attack else copy.deepcopy(e) for e in typed.get("effects") or []],
                         "maneuver": spec["key"], "maneuver_of": row.source_definition_id,
                         # Maneuvers and all their modifiers use this weapon, not another held copy.
                         "weapon_source_id": row.source_definition_id,
                         # the maneuver's own record, so a plug-in keyed on it (auto/gu's Exertion talents) treats it as one
                         **({"source": spec["records"][0]} if spec.get("source_record") else {})}
            if spec.get("follow_up"):
                # Owner Barrage talents are compiled into this character's own action, so the hit plug-in
                # never has to infer ownership from names or from another fighter's actions.
                new_typed["barrage_owned"] = [mid for mid in info["owned"] if mid.startswith("TAL_BARRAGE_")]
                new_typed["opens"] = [*(new_typed.get("opens") or []), f"barrage:{row.source_definition_id}"]
            built[key] = {"action_id": action_id, "name": f"{spec['name']}: {name}", "economy": "action", "target_kind": row.target_kind,
                          "range_ft": delivery_range_ft(row), "costs": list(row.costs), "typed": new_typed,
                          "mechanic": {"name": f"{spec['name']}: {name}", "sphere_id": spec["sphere"], "duration": {"kind": "instant"}},
                          "modifiers": [], "variants": [], "_action": row}
        # "Choose one Snipe talent ... and apply it" / "apply only one Blitz talent to one Barrage": each is a choice.
        local = {**mechanics, fake_key: {"name": spec["name"], "sphere_id": spec["sphere"]}}
        if spec["one_talent"]:
            for mid in wanted:
                local[mid] = {**local[mid], "modifier": {**local[mid]["modifier"], "optional": True}}
        rows = fc.apply_modifiers(built, [*wanted, fake_key], local, info["primary"], info["pools"], automated=info["automated"],
                                  foundation_resource=info["foundation_resource"], option_index={fake_key: list(built)}) if wanted else []
        out_rows += [row for row in rows if row.get("id") in wanted]
        for key, row in built.items():
            base = row["_action"]
            extra = {k: v for k, v in base.parameters.items() if k not in ("typed", "expected_damage")}
            if spec["plain"] and not row.get("_existing"):
                out_actions.append(base.model_copy(update={"source_definition_id": row["action_id"], "display_name": row["name"],
                                                           "parameters": {**extra, "typed": row["typed"],
                                                                          "expected_damage": int(base.parameters.get("expected_damage") or 0)}}))
            for variant in row["variants"]:
                _mark_first_hit(variant["typed"])
                made = fc._action_definition(variant, actor_id, info["numbers"])
                out_actions.append(made.model_copy(update={"parameters": {**extra, **made.parameters}}))
            if spec.get("follow_up") and not row.get("_existing"):
                out_actions.append(_follow_up(base, row, EconomyKind))
                if "TAL_BARRAGE_CASCADING_BARRAGE" in row["typed"].get("barrage_owned", ()):
                    cascade = _follow_up(base, row, EconomyKind)
                    cascade_typed = {**cascade.parameters["typed"], "maneuver": "barrage_cascade", "uses": []}
                    out_actions.append(cascade.model_copy(update={
                        "source_definition_id": f"{base.source_definition_id}.barrage_cascade",
                        "display_name": cascade.display_name.replace("Barrage follow-up:", "Cascading Barrage:"),
                        "economy": EconomyKind.NONE,
                        "parameters": {**cascade.parameters, "typed": cascade_typed, "requires_turn_flag": None}}))
    return {"actions": out_actions, "rows": out_rows} if out_actions or out_rows else None


def _mark_first_hit(typed: dict[str, Any]) -> None:
    """A talent applied to the maneuver changes that one attack, not the Attack action's others. What it does to the target
    rides that attack's hit: damage or a condition "to the target" of an attack lands only if it hits ("If the attack hits,
    it deals +10 damage": Deadly Shot), never on its own; its own attack-roll penalty or bonus ("take a -5 penalty to the
    attack roll") is on that attack's roll (first_roll_bonus). Its user's other effects (Martial Focus, a cost) stay where
    they are."""
    effects = typed.get("effects") or []
    attack = next((row for row in effects if isinstance(row, dict) and row.get("type") == "attack"), None)
    if attack is None:
        return
    kept = []
    for row in effects:
        if row is attack or not isinstance(row, dict) or not row.get("source_modifier"):
            kept.append(row)
        elif row.get("type") == "attack_modifier" and row.get("applies_to") in (None, "self") and isinstance(row.get("flat"), int) and row.get("flat"):
            attack["first_roll_bonus"] = int(attack.get("first_roll_bonus") or 0) + int(row["flat"])
        elif row.get("applies_to") == "target" and row.get("type") not in ("spend_resource", "gain_resource"):
            attack.setdefault("on_hit", []).append(row)
        else:
            kept.append(row)
    typed["effects"] = kept
    attack["on_hit"] = [{**hit, "first_hit_only": True} if isinstance(hit, dict) and hit.get("source_modifier") else hit
                        for hit in attack.get("on_hit") or []]


def _follow_up(base: Any, row: dict[str, Any], EconomyKind: Any) -> Any:
    """"You may then make one additional ranged weapon attack with the same weapon as a Bonus Action"; "the follow-up attack
    does not add a positive ability modifier to damage; a negative ability modifier still applies"."""
    from .barrage_common import follow_up

    name = row["name"].split(": ", 1)[1]
    return follow_up(base, base.parameters["typed"], base.source_definition_id,
                     f"barrage:{base.source_definition_id}", list(row["typed"].get("barrage_owned") or []),
                     f"{base.source_definition_id}.barrage_follow_up", f"Barrage follow-up: {name}",
                     f"After your primary Barrage attack, spend your Bonus Action on one {name} attack; omit a positive ability modifier to damage unless a talent allows it.")


@effect("batter")
def batter(ctx: Any, eff: dict[str, Any]) -> None:
    """"On a hit that deals damage, the target becomes Battered until the end of your next turn."

    The printed length is one turn, unless an owning talent says otherwise: the generic ``condition_turns`` hook
    (``engine``, ``actor``, the bare condition name) -> a number of turns answers for a fighter who keeps it longer
    (Berserker's Beat Down: "until the end of your second turn").  A bare name the engine already removes is still
    what is written, so an old saved fight's Battered is unchanged.
    """
    from . import run

    engine, target = ctx.engine, ctx.target
    if target is None or not target.active:
        return
    dealt = next((event for event in reversed(engine.events[-20:]) if event.event_type == "DAMAGE_COMMITTED"
                  and target.entity_id in (event.target_ids or ())), None)
    payload = (dealt.payload or {}) if dealt is not None else {}
    if int(payload.get("hp_damage") or 0) + int((payload or {}).get("temporary_hp_absorbed") or 0) <= 0:
        return
    turns = max([1, *[int(value) for value in run("condition_turns", engine, ctx.actor, "battered")
                      if isinstance(value, int) and value > 0]])
    engine._remove_condition(target, BATTERED, ctx.source)
    engine._apply_condition(target, BATTERED, ctx.source, ctx.actor.entity_id,
                            expires_on=f"END_OF_SOURCE_TURN_AT:{int(ctx.actor.turns_started) + turns}", data={"label": "Battered"})
