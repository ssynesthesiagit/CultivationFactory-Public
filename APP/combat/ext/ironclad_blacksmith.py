"""Blacksmith sphere mechanics for Lingfeng Ironclad (owner 2026-09-28, auto-ironclad worker; extended by auto17
round 25 for every Blacksmith).

Set Edge and Fit Armor -- two of the printed "Core Forge Responses" -- are entirely missing from the typed
mechanics authority: they exist in the source text (09_RULES/Source_Text/Tianxia_Sphere_Compendium_Latest_
R0I_85Spheres.md, "## Core Forge Responses", just after "### Blacksmith Talent Tags") but were never split into
their own mechanic ids the way Read the Flaw/Set the Workpiece/Hammer the Mark were, so there is nothing in
authority/typed_mechanics/reviewed_final.d to correct -- they are built directly here instead. Close the Crack,
Expose the Flaw and Temper the Tool are the same kind of gap but no Blacksmith talent on this table needs them, so
they are left out of scope (see combat/rules/feature_status.d/ironclad.json).

Building these here is also what lets Forge-Fitted Weapon and Forge-Fitted Armor -- already well-typed in the
authority, targeting "Set Edge"/"Fit Armor" by name -- have a real action to describe.

auto17 (round 25) closed what the printed text actually asks of those two responses. Set Edge's own second half is
"The next time before the start of your next turn that it hits with an attack **or is used for a relevant ability
check**, add your Proficiency Bonus to one damage roll or one check. This bonus does not stack with itself": the
damage-roll half ran through after_hit, the ability-check half was a GM line, and it is now the check_bonus seam
(one condition, so it cannot stack with itself). Forge-Fitted Weapon's four printed benefits were an unpriced
documented gap and are now one chosen benefit of a Temporary Temper, with the printed "spend 1 CP to extend the
Temporary Temper to 1 minute" as a priced second button. Fit Armor's two middle options were literal
{"type": "rider"} effects -- the wearer reduced nothing and ignored no forced movement -- and are now real
conditions read by the damage_reduction / forced_movement_reduction / save seams. Forge-Fitted Armor adds the
talent's own fourth choice ("Advantage on saving throws against being knocked Prone") and Armor Knows Its Owner
adds its three.
"""

from __future__ import annotations

from typing import Any

from . import effect, hook
from .blacksmith_forge import held_condition
from ..action_variants import choice, cost_delta, with_variant
from ..gate2_runtime_models import ActionDefinition, EconomyKind
from ..typed_executor import bears_mark, mark_condition_id

SET_EDGE_READY = "Set Edge Ready"
SET_EDGE_SOURCE = "tianxia.talent.blacksmith.set_edge"
# Edge Before Blood (auto-lane5 2026-09-29): Set Edge also marks the smith, and the first weapon hit while it stands treats the
# target's Resistance to the weapon's damage type as ordinary damage (the "resistance_ignored" hook below).
EDGE_BEFORE_BLOOD = "Edge Before Blood"

# The Forge Mark chassis's Temporary Temper: one workpiece's one improvement, so this module owns both the condition
# and every hook that reads its chosen printed benefit (combat/rules/feature_blocks.d/blacksmith.json).
TEMPER = "condition:typed.blacksmith_temporary_temper"
ARMOR_TEMPER = "condition:typed.blacksmith_armor_temper"
TEMPER_PICK = "condition:typed.blacksmith_temper_choice"
FORGE_FITTED_WEAPON = "tianxia.talent.blacksmith.forge_fitted_weapon"
FORGE_FITTED_ARMOR = "tianxia.talent.blacksmith.forge_fitted_armor"
ARMOR_KNOWS = "tianxia.talent.blacksmith.armor_knows_its_owner"

# One Temporary Temper, one printed benefit. The free toggle ("Set Edge: <benefit>") is the same shape as
# combat/ext/blacksmith_rebuke.py's and combat/ext/bodyb_choices.py's: the player sets it once and it stays.
TEMPER_BENEFITS: dict[str, tuple[str, str]] = {
    "attack": ("+1 to attack rolls", "until_start_of_next_turn"),
    "damage": ("+1 to damage rolls", "until_start_of_next_turn"),
    "magical": ("counts as magical against nonmagical resistance and immunity", "until_start_of_next_turn"),
    "reroll": ("reroll one damage die", "one_minute"),
    "armor_ac": ("+1 AC", "until_start_of_next_turn"),
    "armor_reduce": ("reduce the next Bludgeoning, Piercing, or Slashing damage by your Proficiency Bonus",
                     "until_start_of_next_turn"),
    "armor_push": ("ignore the next 5 feet of forced movement", "until_start_of_next_turn"),
    "armor_prone": ("Advantage on saving throws against being knocked Prone", "one_minute"),
    "stand": ("stand from Prone without spending movement", "instant"),
    "ungrapple": ("end one nonmagical Grappled state", "instant"),
    "save_advantage": ("Advantage on the next Strength or Dexterity saving throw", "until_start_of_next_turn"),
}
DEFAULT_BENEFIT = {"forge_fitted_weapon": "attack", "forge_fitted_armor": "armor_ac", ARMOR_KNOWS: "stand"}


@hook("status_description")
def edge_status_description(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    cid = str(row.get("condition_id") or "")
    if cid.startswith("condition:typed.mark.edge_before_blood."):
        from ..status_text import printed_excerpt

        return {"text": printed_excerpt("tianxia.talent.blacksmith.edge_before_blood"),
                "source_ability": "Set Edge, with Edge Before Blood",
                "handling": "On the first weapon hit, the table ignores resistance to the weapon's damage type, including magical resistance, because it cannot distinguish magical from nonmagical resistance. Immunity is unchanged. The printed rule requires GM approval to ignore magical resistance."}
    if not cid.startswith("condition:typed.mark.set_edge_ready."):
        return None
    return {"text": "Set Edge: the next hit or check with your current workpiece adds your Proficiency Bonus",
            "source_ability": "Set Edge",
            "handling": "The bonus is added once, to your next weapon hit or to your next ability check with the workpiece; it does not stack with itself."}


@hook("compile_actions")
def _compile_actions(info: dict[str, Any]) -> list[ActionDefinition]:
    if "tianxia.sphere.blacksmith" not in info["spheres"]:
        return []
    short, actor_id, numbers = info["short"], info["actor_id"], info["numbers"]
    owned = set(info["owned_ids"])
    weapon_temper = FORGE_FITTED_WEAPON in owned
    armor_temper = FORGE_FITTED_ARMOR in owned
    made = [ActionDefinition(
        source_definition_id=f"action:typed.{short}.blacksmith.set_edge", display_name="Set Edge",
        owner_id=actor_id, economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {
            "effects": [
                {"type": "spend_mark", "mark": "Forge Mark", "applies_to": "self", "evidence": "Spend 1 Forge Mark."},
                {"type": "mark", "mark": SET_EDGE_READY, "applies_to": "self", "duration": {"kind": "until_start_of_next_turn"}},
                *([{"type": "mark", "mark": EDGE_BEFORE_BLOOD, "applies_to": "self", "duration": {"kind": "until_start_of_next_turn"}}]
                  if "tianxia.talent.blacksmith.edge_before_blood" in owned else []),
                *([{"type": "blacksmith_temper", "duration": "until_start_of_next_turn"}] if weapon_temper else []),  # the chosen benefit, or the first one
            ],
            "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
        }, "expected_damage": 0},
    )]
    if weapon_temper:
        # Forge-Fitted Weapon: "you may spend 1 CP to extend the Temporary Temper to 1 minute".
        pool = _pool(info)
        made.append(with_variant(ActionDefinition(
            source_definition_id=f"action:typed.{short}.blacksmith.set_edge.extended", display_name="Set Edge (1 minute)",
            owner_id=actor_id, economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF",
            costs=((pool, 1),) if pool else (),
            parameters={"typed": {
                "effects": [
                    {"type": "spend_mark", "mark": "Forge Mark", "applies_to": "self", "evidence": "Spend 1 Forge Mark."},
                    {"type": "mark", "mark": SET_EDGE_READY, "applies_to": "self", "duration": {"kind": "one_minute"}},
                    *([{"type": "mark", "mark": EDGE_BEFORE_BLOOD, "applies_to": "self", "duration": {"kind": "one_minute"}}]
                      if "tianxia.talent.blacksmith.edge_before_blood" in owned else []),
                    {"type": "blacksmith_temper", "duration": "one_minute"},  # the chosen benefit, extended to 1 minute
                ],
                "numbers": numbers, "duration": {"kind": "instant"}, "riders": [],
            }, "expected_damage": 0}), f"action:typed.{short}.blacksmith.set_edge", "Set Edge",
            [choice("duration", "one_minute", "1 minute", cost_delta(((pool, 1),) if pool else ()))]))
        made.extend(_temper_pickers(info, "weapon", FORGE_FITTED_WEAPON, {
            "attack": "Forge-Fitted Weapon: +1 to attack rolls",
            "damage": "Forge-Fitted Weapon: +1 to damage rolls",
            "magical": "Forge-Fitted Weapon: the weapon counts as magical against nonmagical resistance and immunity",
            "reroll": "Forge-Fitted Weapon: reroll one damage die",
        }))
    options: list[tuple[str, str, list[dict[str, Any]]]] = [
        ("ac", "Fit Armor: +1 AC", [{"type": "blacksmith_temper", "benefit": "armor_ac", "a2": 1,
                                     "duration": "until_start_of_next_turn"}]),
        ("dmg", "Fit Armor: Reduce Weapon Damage",
         [{"type": "blacksmith_temper", "benefit": "armor_reduce", "a2": 1, "duration": "until_start_of_next_turn"}]),
        ("push", "Fit Armor: Ignore Forced Movement",
         [{"type": "blacksmith_temper", "benefit": "armor_push", "a2": 1, "duration": "until_start_of_next_turn"}]),
    ]
    if armor_temper:
        options.append(("prone", "Fit Armor: Advantage on saves against being knocked Prone",
                        [{"type": "blacksmith_temper", "benefit": "armor_prone", "a2": 1, "duration": "until_start_of_next_turn"}]))
    made.extend(_fit_armor(f"action:typed.{short}.blacksmith.fit_armor.{key}", name, actor_id, numbers, armor_temper, effects)
                for key, name, effects in options)
    if armor_temper:
        # Forge-Fitted Armor: "you may spend 1 CP to extend the Temporary Temper to 1 minute".
        pool = _pool(info)
        made.append(ActionDefinition(
            source_definition_id=f"action:typed.{short}.blacksmith.fit_armor.extended",
            display_name="Fit Armor (1 minute)", owner_id=actor_id, economy=EconomyKind.BONUS_ACTION,
            resolution_kind="TYPED", target_kind="SELF", costs=((pool, 1),) if pool else (),
            parameters={"typed": {"effects": [{"type": "spend_mark", "mark": "Forge Mark", "applies_to": "self",
                                               "evidence": "Spend 1 Forge Mark."},
                                              {"type": "blacksmith_temper", "kind": "armor", "duration": "one_minute", "a2": 1}],
                              "numbers": numbers, "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0}))
        made.extend(_temper_pickers(info, "armor", FORGE_FITTED_ARMOR, {
            "armor_ac": "Forge-Fitted Armor: +1 AC",
            "armor_reduce": "Forge-Fitted Armor: reduce nonmagical Bludgeoning, Piercing, or Slashing attack damage by your Proficiency Bonus once each round",
            "armor_push": "Forge-Fitted Armor: ignore the next 5 feet of forced movement each round",
            "armor_prone": "Forge-Fitted Armor: Advantage on saving throws against being knocked Prone",
        }))
    if ARMOR_KNOWS in owned:
        # Armor Knows Its Owner: "When you Fit Armor for a willing creature ... Choose one:" three printed results.
        made.extend(_fit_armor(f"action:typed.{short}.blacksmith.fit_armor.knows_{key}", name, actor_id, numbers, False, effects)
                    for key, name, effects in [
                        ("stand", "Fit Armor: Stand from Prone",
                         [{"type": "blacksmith_temper", "benefit": "stand", "duration": "instant"}]),
                        ("ungrapple", "Fit Armor: End a Grappled state",
                         [{"type": "blacksmith_temper", "benefit": "ungrapple", "duration": "instant"}]),
                        ("save", "Fit Armor: Advantage on the next Strength or Dexterity saving throw",
                         [{"type": "blacksmith_temper", "benefit": "save_advantage", "duration": "until_start_of_next_turn"}]),
                    ])
    return made


def _pool(info: dict[str, Any]) -> str | None:
    """The Path pool a printed "CP" belongs to for this character (combat/ext/cp_pools.py)."""
    from ..factory_compiler import RESOURCE_IDS

    return RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")


def _fit_armor(source_id: str, name: str, actor_id: str, numbers: dict[str, Any], extended: bool,
               effects: list[dict[str, Any]]) -> ActionDefinition:
    return ActionDefinition(
        source_definition_id=source_id, display_name=name, owner_id=actor_id, economy=EconomyKind.BONUS_ACTION,
        resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"effects": [{"type": "spend_mark", "mark": "Forge Mark", "applies_to": "self", "evidence": "Spend 1 Forge Mark."},
                                          *effects],
                              "numbers": numbers, "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0})


def _temper_pickers(info: dict[str, Any], kind: str, feature: str, labels: dict[str, str]) -> list[ActionDefinition]:
    """The free toggle that says which printed benefit a Temporary Temper carries, the same shape as
    combat/ext/blacksmith_rebuke.py's Hammer Rebuke picker: one setting action per benefit, kept until changed."""
    out = []
    for benefit, label in labels.items():
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.temper_pick.{kind}.{benefit}",
            display_name=label, owner_id=info["actor_id"], economy=EconomyKind.NONE, resolution_kind="TYPED",
            target_kind="SELF",
            parameters={"setting_only": True, "setting_description": (
                "This Temporary Temper's chosen benefit lasts as long as the temper does. Change it at any time "
                "before you use the response again."),
                        "typed": {"effects": [{"type": "blacksmith_temper_pick", "benefit": benefit, "kind": kind, "independent": 1,
                                               "feature": feature, "label": label}],
                                  "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": []},
                        "expected_damage": 0, "player_only": True}))
    return out


@effect("blacksmith_temper_pick")
def temper_pick(ctx: Any, row: dict[str, Any]) -> None:
    """Keep each workpiece kind's free setting independently until changed.

    New sealed pickers opt in; historical packets keep their singleton writes
    so replaying an old fight does not change its stored state or events.
    """
    smith = ctx.actor
    data = {"kind": str(row.get("kind") or ""), "feature": str(row.get("feature") or ""),
            "benefit": str(row.get("benefit") or ""), "label": str(row.get("label") or row.get("benefit") or "")}
    condition_id = TEMPER_PICK + "." + data["kind"] if row.get("independent") else TEMPER_PICK
    ctx.engine._remove_condition(smith, condition_id, ctx.source)
    ctx.engine._apply_condition(smith, condition_id, str(row.get("feature") or ctx.source), smith.entity_id,
                                expires_on="UNTIL_REMOVED", data=data)


def _chosen(ctx: Any, kind: str) -> str | None:
    if not ctx.actor.active:
        return None
    # Prefer this kind's new setting, retaining legacy singleton reads for
    # saved fights and characters that have not changed their old selection.
    row = held_condition(ctx.actor, TEMPER_PICK + "." + kind) or held_condition(ctx.actor, TEMPER_PICK)
    if row is None or (row.data or {}).get("kind") != kind:
        return None
    return str((row.data or {}).get("benefit") or "")


@effect("blacksmith_temper")
def blacksmith_temper(ctx: Any, row: dict[str, Any]) -> None:
    """Place the Forge chassis's Temporary Temper with the printed benefit the fighter chose (or the first one)."""
    from ..typed_executor import clock_expiry, stated_expiry

    smith = ctx.actor
    named = str(row.get("benefit") or "")
    kind = str(row.get("kind") or ("armor" if named.startswith("armor_") else "weapon"))
    # A button that names its printed benefit is that benefit; the free toggle only decides for the buttons that
    # do not (the priced one-minute upgrades), so a player pressing "Fit Armor: Reduce Weapon Damage" gets it.
    benefit = named or _chosen(ctx, kind) or ("armor_ac" if kind == "armor" else "attack")
    duration = str(row.get("duration") or "until_start_of_next_turn")
    expires = clock_expiry(ctx.engine, duration) or stated_expiry(ctx, {"duration": {"kind": duration}}, smith, condition=True)
    if row.get("a2") and duration == "until_start_of_next_turn":
        from .effect_durations import token

        # stated_expiry deliberately leaves this legacy short spelling to its
        # caller. New armor packets must name the actual next owner turn.
        expires = token("start", smith.entity_id, smith.turns_started + 1)
    # One temper per armor piece is not one temper for the creature's weapon
    # and armor combined. New armor actions use their own condition family;
    # historical sealed actions continue to use the legacy shared condition.
    condition_id = ARMOR_TEMPER if row.get("a2") and kind == "armor" else TEMPER
    old = held_condition(smith, condition_id)
    if row.get("a2"):
        # New sealed one-minute armor actions opt into recurring benefits. Old
        # saved actions and old one-use conditions retain their original route.
        old_modifier = (old.data or {}).get("ac_modifier") if old else None
        if old_modifier in smith.modifiers:
            modifier = smith.modifiers.pop(old_modifier)
            ctx.engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=smith.entity_id,
                                     target_ids=(smith.entity_id,), payload={"modifier_id": old_modifier, "reason": "REPLACED"})
        ctx.engine._remove_condition(smith, condition_id, SET_EDGE_SOURCE)
    if row.get("a2"):
        before = set(smith.modifiers)
        if benefit == "armor_ac":
            from ..typed_executor import run_effects

            run_effects(ctx, [{"type": "ac_bonus", "applies_to": "self", "flat": 1,
                               "duration": duration, "expires_on": expires}])
        added = sorted(set(smith.modifiers) - before)
    label = TEMPER_BENEFITS.get(benefit, (benefit, ""))[0]
    recurring = bool(row.get("a2") and duration == "one_minute")
    if recurring and benefit == "armor_reduce":
        label = "reduce nonmagical Bludgeoning, Piercing, or Slashing attack damage by your Proficiency Bonus once each round"
    elif recurring and benefit == "armor_push":
        label = "ignore the first 5 feet of forced movement each round"
    if row.get("a2"):
        label += " for 1 minute" if recurring else " until the start of your next turn"
    ctx.engine._apply_condition(smith, condition_id, SET_EDGE_SOURCE, smith.entity_id, expires_on=expires,
                                data={"benefit": benefit, "pb": int(ctx.numbers.get("pb") or 0),
                                      **({"a2": 1, "recurring": int(recurring)} if row.get("a2") else {}),
                                      **({"ac_modifier": added[0]} if row.get("a2") and added else {}),
                                      "label": f"Temporary Temper: {label}"})


@hook("after_hit")
def _after_weapon_hit(ctx: Any, target: Any, kind: str) -> None:
    """Set Edge's payout: "the next time it hits with an attack... add your Proficiency Bonus to one damage roll."""
    if kind != "weapon":
        return
    actor, engine = ctx.actor, ctx.engine
    if bears_mark(actor, actor.entity_id, EDGE_BEFORE_BLOOD):
        engine._remove_condition(actor, mark_condition_id(EDGE_BEFORE_BLOOD, actor.entity_id), SET_EDGE_SOURCE)  # "the first hit"
    if not bears_mark(actor, actor.entity_id, SET_EDGE_READY):
        return
    engine._remove_condition(actor, mark_condition_id(SET_EDGE_READY, actor.entity_id), SET_EDGE_SOURCE)
    if not target.active:
        return
    pb = int(ctx.numbers.get("pb") or 0)
    if pb > 0:
        damage_type = (ctx.typed.get("weapon") or {}).get("damage_type") or "BLUDGEONING"
        engine._commit_damage(target, pb, damage_type, f"{SET_EDGE_SOURCE}.buff", actor.entity_id, None, reaction_depth=0)
        ctx.rider(f"Set Edge: +{pb} damage.")


@hook("check_bonus")
def _set_edge_check_bonus(ctx: Any, smith: Any) -> int | None:
    """Set Edge's other printed half: "or is used for a relevant ability check, add your Proficiency Bonus to one
    damage roll or one check." Typed ability checks are the only ones the table rolls, so the same one-shot
    condition pays either half and cannot stack with itself."""
    if not bears_mark(smith, smith.entity_id, SET_EDGE_READY):
        return None
    engine = ctx.engine
    engine._remove_condition(smith, mark_condition_id(SET_EDGE_READY, smith.entity_id), SET_EDGE_SOURCE)
    return int(smith.proficiency_bonus or 0) or None


# --------------------------------------------------------------------------------- Temporary Temper benefits
def armor_temper(actor: Any) -> Any | None:
    """Armor state for this plug-in and its service tests; old saves fall back.

    A new armor condition takes priority over a legacy armor temper, without
    treating a weapon temper or Armor Knows' separate save benefit as armor.
    """
    row = held_condition(actor, ARMOR_TEMPER) if actor.active else None
    if row is not None:
        return row
    old = held_condition(actor, TEMPER) if actor.active else None
    return old if old is not None and str((old.data or {}).get("benefit") or "").startswith("armor_") else None


@hook("attack_bonus")
def _temper_attack_bonus(ctx: Any, actor: Any) -> int | None:
    row = held_condition(actor, TEMPER) if actor.active else None
    return 1 if row is not None and (row.data or {}).get("benefit") == "attack" else None


@hook("attack_damage_bonus")
def _temper_damage_bonus(ctx: Any, target: Any, row: dict[str, Any]) -> int | None:
    smith = ctx.actor
    condition = held_condition(smith, TEMPER) if smith.active else None
    return 1 if condition is not None and (condition.data or {}).get("benefit") == "damage" else None


@hook("damage_reduction")
def _temper_reduction(engine: Any, target: Any, damage_type: str, typed: dict[str, Any], source_actor_id: str | None,
                      applied: bool = False) -> int:
    """Fit Armor: "the wearer reduces the next Bludgeoning, Piercing, or Slashing damage taken before the start of
    your next turn by your Proficiency Bonus". Queries only quote the reduction; the applied notification
    consumes the basic temper after a positive damage packet. New one-minute
    armor instead records one qualified nonmagical attack reduction each round."""
    row = armor_temper(target)
    if row is None or (row.data or {}).get("benefit") != "armor_reduce":
        return 0
    if str(damage_type).upper() not in {"BLUDGEONING", "PIERCING", "SLASHING"}:
        return 0
    if (row.data or {}).get("recurring"):
        # The documented flat-reduction seam is queried purely, then notified
        # once when committed. Keep this armor use in that one provider: the
        # extra-defense-row route can collect the same row twice.
        if not typed.get("mundane") or not any(effect.get("type") == "attack" for effect in typed.get("effects") or []):
            return 0
        from . import run

        if source_actor_id and any(run("attack_magical", engine, source_actor_id, typed)):
            return 0
        key = f"blacksmith_armor_reduce_round_used:{row.source_actor_id}"
        if target.turn_flags.get(key) == engine.state.round_number:
            return 0
        if applied:
            target.turn_flags[key] = engine.state.round_number
        return int((row.data or {}).get("pb") or 0)
    if applied:
        engine._remove_condition(target, row.condition_id, SET_EDGE_SOURCE)  # "the next ... damage", never a preview
    return int((row.data or {}).get("pb") or 0)


@hook("forced_movement_reduction")
def _temper_ignores_push(ctx: Any, subject: Any) -> int | None:
    """Fit Armor: "the wearer ignores the next 5 feet of forced movement before the start of your next turn"."""
    row = armor_temper(subject)
    if row is None or (row.data or {}).get("benefit") != "armor_push":
        return None
    if (row.data or {}).get("recurring"):
        key = f"blacksmith_armor_push_round_used:{row.source_actor_id}"
        if subject.turn_flags.get(key) == ctx.engine.state.round_number:
            return None
        subject.turn_flags[key] = ctx.engine.state.round_number
        return 5
    ctx.engine._remove_condition(subject, row.condition_id, SET_EDGE_SOURCE)
    return 5


@hook("save")
def _temper_save_advantage(ctx: Any, subject: Any, ability: str, named: set[str]) -> dict[str, Any] | None:
    """Forge-Fitted Armor: "Advantage on saving throws against being knocked Prone", and Armor Knows Its Owner's
    "Advantage on the next Strength or Dexterity saving throw made before the start of your next turn"."""
    row = armor_temper(subject)
    # Armor Knows' one-save adjustment is independent of the armor temper.
    adjustment = held_condition(subject, TEMPER) if subject.active else None
    if adjustment is not None and (adjustment.data or {}).get("benefit") == "save_advantage" and str(ability).upper() in {"STR", "DEX"}:
        ctx.engine._remove_condition(subject, TEMPER, SET_EDGE_SOURCE)
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    if row is None or subject.entity_id != row.source_actor_id:
        return None
    benefit = (row.data or {}).get("benefit")
    if benefit == "armor_prone" and "prone" in named:
        return {"bonus": 0, "modes": ["ADVANTAGE"]}
    return None


@hook("damage_dice_reroll")
def _temper_reroll(ctx: Any, row: dict[str, Any], kinds: list[str], dice_count: int) -> int | None:
    """Forge-Fitted Weapon: "once during the duration, the wielder may reroll one damage die and use the new roll"."""
    if row is None or _chosen(ctx, "weapon") != "reroll":
        return None
    smith = ctx.actor
    condition = held_condition(smith, TEMPER) if smith.active else None
    if condition is None or (condition.data or {}).get("benefit") != "reroll" or dice_count <= 0:
        return None
    ctx.engine._remove_condition(smith, TEMPER, SET_EDGE_SOURCE)  # "once during the duration"
    ctx.rider("Forge-Fitted Weapon: one damage die rerolled, the new roll is used.")
    return 1


@hook("immunity_as_resistance")
def _temper_counts_as_magical(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str | None,
                               target: Any) -> bool | None:
    """Forge-Fitted Weapon: "the weapon counts as magical for overcoming resistance and immunity to nonmagical
    attacks". The table tells no magical damage from a nonmagical one, so the smith's marked weapon is read as
    magical against every Immunity (Edge Before Blood's resistance_ignored then works off this)."""
    smith = engine.state.actors.get(source_actor_id) if source_actor_id else None
    if smith is None or not smith.active:
        return None
    condition = held_condition(smith, TEMPER)
    if condition is None or (condition.data or {}).get("benefit") != "magical":
        return None
    return bears_mark(smith, smith.entity_id, SET_EDGE_READY)


@hook("status_description")
def _temper_status(engine: Any, holder: Any, row: dict[str, Any], data: dict[str, Any]) -> dict[str, str] | None:
    if str(row.get("condition_id") or "") not in {TEMPER, ARMOR_TEMPER, TEMPER_PICK}:
        return None
    return {"text": str(data.get("label") or "Temporary Temper"),
            "source_ability": "Set Edge or Fit Armor",
            "handling": "A workpiece carries one Temporary Temper from you at a time; a new one ends the previous."}


@hook("resistance_ignored")
def _edge_before_blood(engine: Any, kind: str, typed: dict[str, Any], source_actor_id: str, target: Any = None) -> bool | None:
    """Edge Before Blood: "the first hit with that weapon also treats the target's nonmagical resistance to that damage type as
    one step weaker: resistance becomes normal damage".  The damage type is the weapon's own; the table does not tell a
    magical Resistance from a nonmagical one, so this reads every Resistance to it (Immunity is untouched, as printed)."""
    actor = engine.state.actors.get(source_actor_id)
    weapon = typed.get("weapon") or {}
    if actor is None or not weapon or not bears_mark(actor, actor.entity_id, EDGE_BEFORE_BLOOD):
        return None
    return kind in [str(name).upper() for name in weapon.get("damage_types") or [weapon.get("damage_type")]]
