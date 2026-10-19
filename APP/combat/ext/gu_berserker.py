"""Berserker sphere: Batter (Gu Xiangze, 2026-09-28).

TAL_BERSERKER_BATTER is catalogued as an automatic base-sphere ability
(catalog_authority/cat3/generated/matrices/automatic_base_component_matrix.json:
"candidate_record_id": "TAL_BERSERKER_BATTER", "automatic_grant": true,
"cat1_classification": "BASE_SPHERE_ABILITY" -- the same status as Brutal Shove for
Brute), but the character sheet's own `automatic_sphere_component_record_ids` (built
by an earlier, out-of-scope pipeline stage -- sphere_component_authority.py /
character_sheet/service.py, not touched here) never lists it, so it never reaches
`ids`/`owned` in factory_compiler.compile_character and is never compiled. Without
Batter, four owned Berserker talents (Bone-Breaker, Bell-Ringer, Brutal Strike,
Cultivation Sunder) and Shatter Earth's own "Instead of attacking a creature, Batter
the ground" have nothing to attach to or replace -- the whole sphere is dead. This
plug-in supplies the missing base action directly, keyed off owning the Berserker
sphere, so the sheet-generation bug does not have to be fixed to make the sphere work
in a fight.

Printed text (TAL_BERSERKER_BATTER): "A Batter is a Special Attack made with: a melee
weapon; an unarmed strike; a natural weapon; a thrown weapon. On a hit that deals
damage, the target becomes Battered until the end of your next turn. A Battered
creature has no automatic penalty by itself. Exertion talents exploit the opening
created by Batter."

We deliver Batter with the character's own natural/unarmed strike (Iron Fist, a Body
Refining path feature owned by another worker; only its already-compiled
`natural_weapon` passive row is read here, not modified) rather than re-deriving a
generic weapon-binding pipeline (the authority's `weapon_delivery` auto-detection only
runs for economy in ("action", "bonus_action") and only matches an explicit "Make a
weapon attack..." sentence -- Batter's own text has neither, so it cannot go through
that path without a shared, corpus-wide change to tools/build_typed_mechanics_authority.py
that is out of scope here). A GM-only rider says plainly that the printed text also
allows a melee or thrown weapon, which this table action does not model.

No talent Gu owns reads "is this creature currently Battered" as a precondition --
Bone-Breaker/Bell-Ringer/Brutal Strike/Cultivation Sunder all trigger directly off
"when Batter deals damage" (the hit itself), each with its own separately-stated
duration -- so the Battered condition's own expiry is cosmetic for this character;
END_OF_HOLDER_NEXT_TURN (this engine's only "next turn" token anchored on the
recipient) is used rather than inventing a "the attacker's next turn" token that does
not exist in gate2_engine._expire_typed_for_checkpoint.

Body 2026-09-29 (wave-2 Berserker sphere owner, fixing a docket-peer-reported bug): the
printed sphere rule is "apply ONE Exertion talent" per Batter, not every owned one at
once. This module used to bake Brutal Strike into every unarmed Batter unconditionally
and fire Bone-Breaker + Bell-Ringer + Cultivation Sunder together on every damaging hit
-- free, stacked power the printed text does not give. It also only ever covered the
unarmed Batter this module itself builds; once combat/ext/docket_maneuvers.py started
building a second and third Batter per melee weapon (its own "maneuvers" hook, matching
Snipe Shot/Barrage), those weapon Batters got no Exertion talent at all, because this
module's after_hit hook read a per-action "exertion" flag only its own compile_actions
had ever set.

Fixed as two different shapes, because Brutal Strike is not like the other three:
- Brutal Strike changes the ATTACK ROLL ITSELF ("take -5 to the attack roll"), which
  must be known before the roll, not decided after a hit lands -- and this engine has
  no generic "add a flat modifier to my own next attack roll" mechanism outside of
  baking it into a compiled action's own numbers at compile time (gate2_engine.py, on
  this task's do-not-edit list, only ever consumes attack_roll/SUBTRACT_DIE, never a
  flat ADD). So Brutal Strike is left OUT of blocks["automated"] and OUT of
  feature_status "applied": combat/ext/docket_maneuvers.py's own generic "one Exertion
  talent" modifier-variant system (the same one that builds "Snipe Shot: <weapon> +
  <talent>") picks it up and builds "Batter: Brutal Strike" as its own separate,
  choosable action for the unarmed Batter this module builds AND for every weapon
  Batter docket_maneuvers builds -- correctly, because a self-targeted "attack_modifier"
  effect survives that pipeline as a real first_roll_bonus (docket_maneuvers.py
  _mark_first_hit, typed_executor.py line ~507), unlike a target-targeted one.
- Bone-Breaker (a real SUBTRACT_DIE modifier on the TARGET's future attack roll) and
  Bell-Ringer (a real bell_rung condition) both need custom code that a generic
  target-directed "attack_modifier"/"condition" effect would silently degrade to a
  GM-only rider if routed through docket_maneuvers's generic pipeline (that pipeline
  only recognises effect types typed_executor.py's BLOCKS dict already runs; an
  unregistered type falls back to block_rider). Cultivation Sunder is GM-only either
  way (no generic "compare damage to an arbitrary effect's rank" exists). All three are
  marked "automated" (combat/rules/feature_blocks.d/body.json, block
  "gu_berserker_exertion") so docket_maneuvers's own generic pass leaves them alone,
  and kept here as a free player toggle ("Exertion: Bone-Breaker" / "... Bell-Ringer" /
  "... Cultivation Sunder" / "... off", kept until changed, Black-Vein-Palm style):
  whichever is currently chosen fires once on any damaging Batter, unarmed or weapon
  (matched by typed["source"] == TAL_BERSERKER_BATTER, which docket_maneuvers stamps
  onto every Batter it builds too) -- except a hit made with the "Batter: Brutal
  Strike" variant, which already spent this attack's one Exertion talent on Brutal
  Strike (typed["modifier"]["id"] identifies it).
"""
from __future__ import annotations

from typing import Any

from . import effect, hook
from .exertion_talents import CHOICE as EXERTION_CHOICE
from .exertion_talents import CUSTOM as EXERTION_CUSTOM
from .exertion_talents import TALENTS as EXERTION_TALENTS
from .exertion_talents import label as exertion_label
from .exertion_talents import write_standing
from ..gate2_runtime_models import ActionDefinition, EconomyKind

BERSERKER = "tianxia.sphere.berserker"
BATTER_SOURCE = "TAL_BERSERKER_BATTER"
EXERTION_BLOCK = "gu_berserker_exertion"
EXERTION_CHOICES = sorted(EXERTION_CUSTOM)
EXERTION_LABELS = {key: exertion_label(key) for key in EXERTION_CHOICES}
EXERTION_LABELS["off"] = "off"




@hook("compile_block")
def _compile_block(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block == EXERTION_BLOCK:
        return [row]  # a bare marker row carrying its own feature_id; the after_hit hook below reads which of the
    return None        # three Exertion talents this specific actor owns from that (typed_reactions._rows)


@hook("compile_actions")
def batter(info: dict[str, Any]) -> list[Any] | None:
    if BERSERKER not in info["spheres"]:
        return None
    natural = next((row for row in info["passives"] if row.get("block") == "natural_weapon"), None)
    mods = info["mods"]
    pb = int(info["pb"])
    if natural:
        ability = max(natural.get("abilities") or ["STR"], key=lambda a: mods.get(a, 0))
        count, _, sides = str(natural.get("dice") or "1d4").lower().partition("d")
        count, sides = int(count or 1), int(sides or 4)
        damage_type = str(natural.get("damage_type") or "BLUDGEONING")
        bonus_value = int(natural.get("bonus_value") or 0)
        source_name = natural.get("name") or "Unarmed Strike"
    else:  # no natural-weapon block owned: the bare 2024 Unarmed Strike (1 + Strength)
        ability, count, sides, damage_type, bonus_value, source_name = "STR", 0, 0, "BLUDGEONING", 1, "Unarmed Strike"
    bonus = mods.get(ability, 0) + bonus_value
    # "On a hit that deals damage, the target becomes Battered until the end of your next turn": the same ``batter`` effect the weapon
    # Batters run (combat/ext/docket_maneuvers.py: damage dealt, the Batterer's next turn end) -- rider lane C13, 2026-09-30.
    on_hit = [{"type": "damage", "weapon_damage": True}, {"type": "batter"}]
    attack_bonus = pb + mods.get(ability, 0)
    riders = []  # weapon Batters are combat/ext/docket_maneuvers.py's; the rest of the Attack action is combat/ext/special_attacks.py's
    typed = {
        "effects": [{"type": "attack", "attack_kind": "unarmed", "count": 1, "on_hit": on_hit}],
        "numbers": {**info["numbers"], "attack_bonus": attack_bonus},
        "weapon": {"damage": {"count": count, "sides": sides, "modifier": bonus} if count else None,
                   "fixed_damage": bonus if not count else None, "damage_type": damage_type},
        "duration": {"kind": "instant"}, "range_ft": None, "riders": riders, "source": BATTER_SOURCE,
    }
    expected = (count * (sides + 1)) // 2 + bonus if count else bonus
    actions: list[Any] = [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.granted.tal_berserker_batter", display_name="Batter",
        owner_id=info["actor_id"], economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
        range_ft=5, parameters={"typed": typed, "expected_damage": expected},
    )]
    # "Apply one Exertion talent" per Batter (owner ruling 2026-09-29): a free toggle, kept until changed, covering
    # every Exertion talent this fighter owns that is worked out on a hit.  One toggle serves every Batter the
    # character has (this one and every weapon Batter docket_maneuvers builds), since the after_hit hook below
    # matches on typed["source"], which every Batter carries.  The registry, and the way a talent's own effect is
    # read back, belong to combat/ext/exertion_talents.py (shared with Extended Exertion, Heaven-Crushing Exertion
    # and The Blow Heaven Refused to Receive, which apply more than one at a time).
    from . import exertion_talents

    owned_exertion = exertion_talents.owned_probe(info)
    if owned_exertion:
        for key in (*owned_exertion, "off"):
            actions.append(ActionDefinition(
                source_definition_id=f"action:typed.{info['short']}.gu_berserker_exertion.{key}",
                display_name=f"Exertion: {EXERTION_LABELS.get(key, exertion_talents.label(key))}", owner_id=info["actor_id"], economy=EconomyKind.NONE,
                resolution_kind="TYPED", target_kind="SELF",
                parameters={"setting_only": True, "typed": {"effects": [{"type": "gu_berserker_exertion_choice", "choice": key}], "numbers": info["numbers"],
                                      "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0, "player_only": True}))
    return actions


@effect("gu_berserker_exertion_choice")
def _exertion_choice(ctx: Any, eff: dict[str, Any]) -> None:
    """The free standing choice of one Exertion talent.  Picking the talent that is already chosen clears it, so the
    same button turns it off; the printed number per attack is set by whoever applies more than one (Extended
    Exertion's armed second slot, Heaven-Crushing Exertion, The Blow Heaven Refused to Receive)."""
    from . import exertion_talents

    choice = str(eff.get("choice") or "off")
    standing = exertion_talents.standing(ctx.actor)
    off = choice == "off" or choice in standing  # picking the talent that is already chosen turns it off
    write_standing(ctx.engine, ctx.actor, "" if off else choice, ctx.source)
    ctx.rider(f"Exertion talent set to {'off' if off else exertion_talents.label(choice)}.")


@hook("after_hit")
def exertion(ctx: Any, target: Any, kind: str) -> None:
    """Apply the chosen Exertion talents to this Batter's hit.

    "When Batter deals damage, ..." -- one talent per Batter from the free toggle above, plus any second slot a printed
    talent armed for this attack (Extended Exertion's second talent, which this attack spends whether or not the standing
    toggle also ran).  An attack that IS already a "Batter: <talent>" variant has spent this attack's one Exertion talent
    on that variant, so the toggle does not run on it -- and it can still carry Extended Exertion's second slot, which
    is the printed "two Exertion talents on one Batter attack" (Brutal Strike and Reaper's Momentum are never applied
    here: they change the attack roll, so they are chosen as their own variant before the roll).
    """
    from . import exertion_talents

    if ctx.typed.get("source") != BATTER_SOURCE or not exertion_talents.dealt_damage(ctx, target):
        return
    variant = str(((ctx.typed.get("modifier") or {}) or {}).get("id") or "")
    picked = exertion_talents.armed(ctx.engine, ctx.actor, BATTER_SOURCE, variant_spent=exertion_talents.is_talent(variant))
    if not picked:
        return  # owns no Exertion talent at all
    exertion_talents.spend_extra_slot(ctx.engine, ctx.actor, BATTER_SOURCE)  # paid for once, so it is spent here
    exertion_talents.apply(ctx, target, picked, more_if_battered=berserker_was_battered(ctx, target))


def berserker_was_battered(ctx: Any, target: Any) -> bool:
    """"If the target was already Battered" -- combat/ext/berserker.py owns the sample (it also knows the two printed
    attacks that say the target counts as already Battered whatever it carries)."""
    from . import berserker

    return berserker.was_battered(ctx, target)


def apply_exertion(ctx: Any, key: str, target: Any) -> None:
    """One Exertion talent that needs its own code (Bone-Breaker, Bell-Ringer, Cultivation Sunder).

    Public because combat/ext/exertion_talents.py -- the shared registry Extended Exertion, Heaven-Crushing Exertion
    and The Blow Heaven Refused to Receive go through -- hands these three here instead of re-typing them.
    """
    if key == "bone_breaker":
        # "subtract 1d4 from attack rolls made by the target until the start of your next turn" -- gate2_engine's
        # existing attack_roll/SUBTRACT_DIE modifier already implements exactly this (used elsewhere for the same
        # -1d4 penalty); it is consumed on the target's next attack roll, with START_OF_SOURCE_NEXT_TURN as a
        # backstop if the target never attacks before then.
        ctx.engine._add_modifier(target, ctx.source, "attack_roll", "SUBTRACT_DIE", 1, "NEXT_ATTACK",
                                 expires_on=exertion_expiry(ctx, "START_OF_SOURCE_NEXT_TURN"))
    elif key == "bell_ringer":
        # Disadvantage on Intelligence saving throws is enforced through the condition's save_mode (typed_conditions
        # .json: "bell_rung"). Intelligence *checks* and Concentration-saves-specifically (as opposed to any
        # Constitution save, which this table cannot narrow to "for Concentration only") are GM-only riders: the
        # engine's condition rules only key disadvantage off a whole ability, and a blanket CON-save disadvantage
        # would over-apply to unrelated Constitution saves.
        ctx.engine._apply_condition(target, "condition:typed.bell_rung", ctx.source, ctx.actor.entity_id,
                                    expires_on=exertion_expiry(ctx, "START_OF_SOURCE_NEXT_TURN"))
        ctx.rider("Bell-Ringer: the target also has Disadvantage on Intelligence checks and on Concentration saving "
                 "throws (including one this Batter caused) until the start of your next turn -- apply by hand.")
    elif key == "cultivation_sunder":
        # "Compare Batter damage to 10 + effect rank" needs a GM judgment of an arbitrary ongoing effect's rank; the
        # engine has no generic registry of "effect rank" for enemy conditions/zones to automate the comparison.
        ctx.rider("Cultivation Sunder: you may attempt to suppress (or, by 5+, dispel) one ongoing supernatural "
                 "effect on the target, the struck area, or a Barrier you struck -- GM compares this Batter's "
                 "damage to 10 + the effect's rank.")


def exertion_expiry(ctx: Any, printed: str) -> str:
    """The Exertion talents' own "until the start of your next turn", or Beat Down's second turn (combat/ext/berserker.py)."""
    from . import berserker

    return berserker.exertion_expiry(ctx.engine, ctx.actor, printed) or printed
