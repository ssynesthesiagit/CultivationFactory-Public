"""Body Refining integrated weapons: the Constitution option (rider lane C7, 2026-09-30). Shared helper: reach_bonus.py
uses ``in_group``; chain_tethers.py uses ``in_group`` for its Chain-weapon hits; hundred_hands.py and kensei.py read ``FORMS``.

Chain-Body Integration, Bow Body, Crescent-Body Integration, Weapon-Wheel Body ("Use Constitution instead of Strength or Dexterity for attack and
damage rolls. You may use your Cultivation Attack Modifier."): an owned row

    {"type": "path_passive", "kind": "integrated_weapon", "group": "chain" | "bow" | "polearm" | "one_handed_melee" | "melee" | "blade", "dex": true?}

adds, for each of the character's weapon attack actions of that proficiency group (combat/rules/weapon_specials.json
proficiency.groups; "blade": the Blade Weapon Forms below and cutting axes), a "(Constitution)" variant whose attack roll uses the Cultivation Attack Modifier and whose damage adds
the Constitution modifier (plus the weapon's own magic bonus). The original action stays. Staff Form keeps its own variants
(combat/ext/bojutsu.py). Proficiency itself is granted by weapon_specials.json. No row: nothing is added.

``"choose": n`` (Drawn from Stillness: "Choose one Draw Blade as your Draw Weapon"): the sheet does not record the pick, so,
as combat/factory_compiler.py _weapon_proficiency does for a choose grant, it is the first n weapons of the group the character
carries (``chosen_items``, in action-id order); only they get the variant. Shared helper: still_water.py calls
``chosen_items`` to know which weapon is the Draw Weapon during a fight; sun_bow.py calls ``in_group``, ``integrated_groups``
and ``constitution_typed`` (a compile hook does not see the variants another hook adds, so it builds its own); reach_bonus.py calls
``integrated_bases`` and ``constitution_typed``.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import hook

RULES = Path(__file__).resolve().parents[1] / "rules" / "weapon_specials.json"


# Hundred-Hand Battle Mandala's Weapon Forms: the printed construction rules ("edged cutting weapon as Blade; mace, hammer, club, or striking axe as Hafted; spear, staff,
# glaive, or halberd as Polearm; chain, whip, rope dart, or flexible segmented weapon as Flexible") applied to the catalog.
FORMS = {
    **dict.fromkeys(("bi_shou", "dao", "duan_dao", "duan_jian", "emei_ci", "gou_shuang_gou", "hu_die_dao", "jian", "lian", "liu_ye_dao",
                     "xi_jian", "zhan_ma_dao", "zi_wu"), "Blade"),
    **dict.fromkeys(("bang", "chui", "da_chui", "gan_bang", "gu_duo", "lang_ya_bang", "shou_chui", "tie_bian", "tie_chi", "tie_jian",
                     "zhan_chui", "zhan_gao", "fu", "shou_fu", "yue", "zhan_fu"), "Hafted"),
    **dict.fromkeys(("biao_qiang", "cha_hu_cha", "chang_qiang", "duan_cha", "duan_qiang", "gang_cha", "ge", "guandao_yanyuedao", "gun", "ji",
                     "mao", "mei_jian_dao", "qiang", "yue_ya_chan"), "Polearm"),
    **dict.fromkeys(("jie_bian", "liu_xing_chui", "ruan_bian", "san_jie_gun", "sheng_biao", "lian_jia_bang"), "Flexible"),
    **dict.fromkeys(("fei_biao", "tong_zhu"), "Thrown"),
}
BLADE_AXES = ("fu", "shou_fu", "yue", "zhan_fu")  # Kensei: "A Blade is a dagger, sword, saber, cutting-edged axe"


@lru_cache(maxsize=1)
def _groups() -> dict[str, list[str]]:
    return ((json.loads(RULES.read_text(encoding="utf-8")).get("proficiency") or {}).get("groups") or {})


def in_group(typed: dict[str, Any], group: str) -> bool:
    """Whether a compiled weapon action's item (its typed source) belongs to a weapon proficiency group. The group
    "one_handed_melee" (Weapon-Wheel Body: "any one-handed melee weapon you are proficient with") is read from the weapon
    itself: a melee attack (no range) whose properties do not say Two-Handed, with the character proficient."""
    if group == "draw_blade":
        # Body R8 Weapon Groups: narrower than Blade (axes/greatblades do not qualify).
        weapon = (typed or {}).get("weapon") or {}
        item = str((typed or {}).get("source") or "").rsplit(".", 1)[-1]
        tags = str(weapon.get("properties") or "").lower()
        return bool(weapon) and (item in {"bi_shou", "dao", "duan_dao", "duan_jian", "hu_die_dao", "jian", "liu_ye_dao", "xi_jian"}
                                 or "draw blade" in tags or "draw_blade" in tags)
    if group == "blade":
        item = str((typed or {}).get("source") or "").rsplit(".", 1)[-1]
        weapon = (typed or {}).get("weapon") or {}
        # Properties are sealed from the actual item authority. Only an explicit
        # complete Blade tag counts; damage types and display names do not.
        import re
        explicit = "blade" in {tag.strip().casefold() for tag in re.split(r"[,;|]", str(weapon.get("properties") or ""))}
        unarmed = any(row.get("attack_kind") == "unarmed" for row in (typed or {}).get("effects") or [] if isinstance(row, dict))
        return bool(weapon) and not unarmed and (FORMS.get(item) == "Blade" or item in BLADE_AXES or explicit)
    if group == "melee":  # Thousand-Fold Steel Body's Tempered Weapon: "one melee weapon you are proficient with"
        return bool((typed or {}).get("weapon")) and not (typed or {}).get("range_ft") and bool((typed or {}).get("proficient")) \
            and str((typed or {}).get("source") or "") != "improvised_weapon"
    if group == "one_handed_melee":
        weapon = (typed or {}).get("weapon") or {}
        return bool(weapon) and not (typed or {}).get("range_ft") and bool((typed or {}).get("proficient")) \
            and "two-handed" not in str(weapon.get("properties") or "").lower() and str((typed or {}).get("source") or "") != "improvised_weapon"
    members = _groups().get(group) or []
    item = str((typed or {}).get("source") or "").rsplit(".", 1)[-1]
    return bool((typed or {}).get("weapon")) and (members == "*" or item in members)


def chosen_items(actions: Any, group: str, count: int) -> list[str]:
    """The first ``count`` distinct weapon items of ``group`` among ``actions`` (base weapon attacks, in action-id order)."""
    out: list[str] = []
    for action in sorted(actions, key=lambda a: a.source_definition_id):
        typed = (action.parameters or {}).get("typed") or {}
        if "#" in action.source_definition_id or not in_group(typed, group) \
                or not any(isinstance(e, dict) and e.get("type") == "attack" for e in typed.get("effects") or []):
            continue
        item = str(typed.get("source") or "").rsplit(".", 1)[-1]
        if item not in out:
            out.append(item)
        if len(out) >= count:
            break
    return out


def constitution_typed(info: dict[str, Any], typed: dict[str, Any]) -> dict[str, Any]:
    """A copy of a weapon attack's typed spec using the Cultivation Attack Modifier and the Constitution modifier for damage."""
    variant = copy.deepcopy(typed)
    variant["numbers"]["attack_bonus"] = info["numbers"]["attack_bonus"]
    variant["weapon"]["damage"]["modifier"] = int((info.get("mods") or {}).get("CON", 0) or 0) + int(typed.get("magic_bonus") or 0)
    variant.update(binding_metadata(info, typed))
    if any(row.get("selection_source") and in_group(typed, str(row.get("group"))) for row in _integrated_rows(info)):
        variant["weapon"].update(ability="CON", ability_modifier=int((info.get("mods") or {}).get("CON", 0)))
    return variant


def integrated_groups(info: dict[str, Any]) -> set[str]:
    """The groups this character's integrated-weapon rows name."""
    return {str(row.get("group")) for mid in info["owned_ids"] for row in (info["mechanics"].get(mid) or {}).get("effects") or []
            if isinstance(row, dict) and row.get("type") == "path_passive" and row.get("kind") == "integrated_weapon"}


def _integrated_rows(info: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for mid in info["owned_ids"] for row in (info["mechanics"].get(mid) or {}).get("effects") or []
            if isinstance(row, dict) and row.get("type") == "path_passive" and row.get("kind") == "integrated_weapon"]


def binding_metadata(info: dict[str, Any], typed: dict[str, Any]) -> dict[str, str]:
    """Shared binding guard for base/reach/other Constitution profile consumers.

    An independent owning integration keeps its own permission; a source-bound
    row cannot revoke another family's profile. No bound row means no metadata.
    """
    item = str(typed.get("source") or "").rsplit(".", 1)[-1]
    matching = [row for row in _integrated_rows(info) if in_group(typed, str(row.get("group")))
                and (not row.get("choose") or row.get("selection_source")
                     or item in chosen_items(info["actions"], str(row["group"]), int(row["choose"])))]
    bindings = [row for row in matching if row.get("selection_source")]
    if not bindings or not all(row.get("selection_source") for row in matching):
        return {}
    return {"integrated_selection_source": str(bindings[0]["selection_source"]), "integrated_selection_item": item}


def integrated_bases(info: dict[str, Any]) -> list[Any]:
    """The base weapon attack actions that get a "(Constitution)" variant (their group integrated; a "choose" group only its
    chosen weapons). reach_bonus.py calls it so an integrated weapon's reach variant exists in its Constitution form too."""
    from ..gate2_runtime_models import EconomyKind

    rows = _integrated_rows(info)
    groups = sorted({str(row.get("group")) for row in rows})
    if not groups:
        return []
    # A group whose every row says "choose" is limited to the chosen weapons (a row without it keeps the whole group).
    limits = {g: max(int(row.get("choose") or 0) for row in rows if str(row.get("group")) == g) for g in groups
              if all(row.get("choose") for row in rows if str(row.get("group")) == g)}
    allowed = {g: set(chosen_items([a for a in info["actions"] if a.economy == EconomyKind.ACTION], g, n)) for g, n in limits.items()
               if not any(row.get("selection_source") for row in rows if str(row.get("group")) == g)}
    out = []
    for base in info["actions"]:
        typed = (base.parameters or {}).get("typed") or {}
        item = str(typed.get("source") or "").rsplit(".", 1)[-1]
        if base.economy != EconomyKind.ACTION or "#" in base.source_definition_id or not any(
                in_group(typed, g) and (g not in allowed or item in allowed[g]) for g in groups):
            continue
        if any(isinstance(e, dict) and e.get("type") == "attack" for e in typed.get("effects") or []):
            out.append(base)
    return out


@hook("compile_actions")
def constitution_variants(info: dict[str, Any]) -> list[Any] | None:
    rows = _integrated_rows(info)
    dex_groups = {str(row.get("group")) for row in rows if row.get("dex")}
    out = []
    for base in integrated_bases(info):
        typed = (base.parameters or {}).get("typed") or {}
        variant = constitution_typed(info, typed)
        extra = binding_metadata(info, typed)
        if extra:
            variant["weapon"].update(ability="CON", ability_modifier=int((info.get("mods") or {}).get("CON", 0)))
        out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#integrated_con",
                                           "display_name": base.display_name + " (Constitution)", "parameters": {**base.parameters, **extra, "typed": variant}}))
        # ``dex`` (Kensei's Blade Fist: "Use Dexterity or Constitution"): a "(Dexterity)" variant when the weapon's own ability is
        # lower and it is not a Finesse weapon (whose own attack already takes the better of Strength and Dexterity).
        dex = int((info.get("mods") or {}).get("DEX", 0) or 0)
        weapon = typed.get("weapon") or {}
        if any(in_group(typed, g) for g in dex_groups) and dex > int(weapon.get("ability_modifier") or 0) \
                and "finesse" not in str(weapon.get("properties") or "").lower():
            swap = copy.deepcopy(typed)
            swap["numbers"]["attack_bonus"] = int(typed["numbers"].get("attack_bonus") or 0) - int(weapon.get("ability_modifier") or 0) + dex
            swap["weapon"]["damage"]["modifier"] = dex + int(typed.get("magic_bonus") or 0)
            swap["weapon"]["ability_modifier"] = dex
            out.append(base.model_copy(update={"source_definition_id": base.source_definition_id + "#integrated_dex",
                                               "display_name": base.display_name + " (Dexterity)", "parameters": {**base.parameters, "typed": swap}}))
    return out or None


def selection_allowed(engine: Any, actor: Any, action: Any) -> bool | None:
    """Source-owned bound-item variants; absent metadata preserves older catalogs.

    Consumers publish integrated_weapon_selected(engine, actor, source, item).
    A bound variant requires an affirmative owning provider; other families do
    not receive binding metadata and are strictly unchanged.
    """
    from . import query
    params = getattr(action, "parameters", None) or {}
    typed = params.get("typed") or {}
    source = params.get("integrated_selection_source") or typed.get("integrated_selection_source")
    recorded=typed.get('integration_sources')
    if recorded:
        if action.owner_id!=actor.entity_id:return False
        from .body_modes_scene_resources import bundle_of,available
        levels=bundle_of(engine,actor).get('body_feature_levels',{})
        accepted=[]
        for feature in recorded:
            from . import run_strict
            replies=run_strict('integrated_feature_available',engine,actor,feature)
            if any(type(r) is not bool for r in replies if r is not None):raise ValueError('Integration availability requires boolean replies')
            allowed=False not in replies
            if feature.startswith(('tianxia.path.body_refining.','tianxia.subpath.body.')):
                allowed=allowed and available(engine,actor,feature,int(levels.get(feature,0)),requires_conscious=False)
            accepted.append(allowed)
        if not any(accepted):return False
    if not source:
        return None
    return any(answer is True for answer in query("integrated_weapon_selected", engine, actor, source,
                                                  params.get("integrated_selection_item") or typed.get("integrated_selection_item")))


@hook("candidate_allowed")
def bound_candidate(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    return selection_allowed(engine, actor, action)


@hook("attack_allowed")
def bound_attack(ctx: Any, target: Any, effect: Any) -> bool | None:
    return selection_allowed(ctx.engine, ctx.actor, ctx.action)


def recorded_integration(engine: Any, actor: Any, typed: dict[str, Any], group: str) -> bool:
    """Read a concrete integration already sealed into this actor's catalog.

    Kensei uses this for Blade-only riders and granted attacks. Matching an item
    group alone never grants integration. The actor's existing Constitution
    profile records the same physical item; ordinary profiles remain eligible.
    Unknown or unarmed sources, foreign owners and absent profiles are inert.
    Possession/readiness and legal attack geometry remain the caller's gates.
    """
    source = typed.get("source")
    if not source or not in_group(typed, group):
        return False
    return any(action.owner_id == actor.entity_id and "#integrated_" in action.source_definition_id
               and selection_allowed(engine, actor, action) is not False
               and (action.parameters.get("typed") or {}).get("source") == source
               for action in engine.action_catalog.values())


def integration_sources(info,typed):
    """Actual owning feature IDs for one compiled integration; no source inferred."""
    item=str(typed.get('source') or '').rsplit('.',1)[-1]
    result=[]
    for feature in info['owned_ids']:
        for row in (info['mechanics'].get(feature) or {}).get('effects',[]):
            if row.get('type')!='path_passive' or row.get('kind')!='integrated_weapon' or not in_group(typed,str(row.get('group'))):continue
            if row.get('choose') and not row.get('selection_source') and item not in chosen_items(info['actions'],str(row['group']),int(row['choose'])):continue
            result.append(feature)
    return sorted(set(result))
