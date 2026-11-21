from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

from .canonical import canonical_bytes
from .gate2_engine import Gate2Engine
from .gate2_grid import SquareGrid
from .gate2_rolls import DeterministicRollAuthority
from .gate2_runtime_content import ACTIONS


_SCHEMA = "TianxiaGate2RuntimeProfileCoverage.v1"

_ACTION_HANDLERS = {
    "action:an_eui.first_arm": ("Gate2Engine._resolve_first_arm",),
    "action:an_eui.paired_bi_shou_assault": ("Gate2Engine._resolve_attack_action", "Gate2Engine._resolve_attack_spec"),
    "action:an_eui.paired_strike": ("Gate2Engine._resolve_attack_action",),
    "action:an_eui.ruin_tempered_armament_quick": ("Gate2Engine._resolve_state_action",),
    "action:an_eui.scouring_destruction_blast": ("Gate2Engine._resolve_attack_then_save",),
    "action:bai_meizhen.blackwater_serpent_court": ("Gate2Engine._resolve_zone_action", "Gate2Engine._resolve_zone_effect"),
    "action:bai_meizhen.command_cui": ("Gate2Engine._resolve_command_cui", "Gate2Engine._resolve_cui_strike"),
    "action:bai_meizhen.numbing_venom_palm": ("Gate2Engine._resolve_attack_then_save", "Gate2Engine._apply_dose"),
    "action:bai_meizhen.water_lash": ("Gate2Engine._resolve_attack_action",),
    "action:bai_meizhen.water_whip": ("Gate2Engine._resolve_optional_rider",),
    "action:lee_jia.gather_charge": ("Gate2Engine._resolve_gather_charge",),
    "action:lee_jia.hidden_sleeve_shock_talisman": ("Gate2Engine._resolve_attack_action",),
    "action:lee_jia.lightning_lash": ("Gate2Engine._resolve_lightning_lash",),
    "action:ling_qi.dissonant_note": ("Gate2Engine._resolve_save_damage",),
    "action:ling_qi.forgotten_vale_nocturne": ("Gate2Engine._resolve_zone_action", "Gate2Engine._resolve_zone_effect"),
    "action:ling_qi.keep_the_measure": ("Gate2Engine._resolve_keep_measure",),
    "action:ling_qi.music_resonant_note": ("Gate2Engine._resolve_attack_action",),
    "action:ling_qi.sound_resonant_note": ("Gate2Engine._resolve_save_damage",),
}

_CONDITION_HANDLERS = {
    "condition:an_eui.ruin_tempered": ("Gate2Engine._resolve_state_action", "Gate2Engine._start_concentration", "Gate2Engine._end_concentration"),
    "condition:core.break_the_guard": ("Gate2Engine._apply_condition", "Gate2Engine._consume_attack_modifiers", "Gate2Engine._ac_modifier"),
    "condition:core.dodging": ("Gate2Engine._cui_default_dodge", "Gate2Engine._attack_mode", "Gate2Engine._roll_save"),
    "condition:core.dose_marked": ("Gate2Engine._apply_dose",),
    "condition:core.grappled": ("Gate2Engine._effective_speed", "Gate2Engine._resolve_optional_rider"),
    "condition:core.reaction_denied": ("Gate2Engine._reaction_usable", "Gate2Engine._resolve_zone_effect"),
    "condition:core.soaked": ("Gate2Engine._resolve_attack_spec", "Gate2Engine._apply_condition"),
}

_PASSIVE_HANDLERS = {
    "passive:an_eui.severance_edge": ("Gate2Engine._maybe_gain_severance",),
    "passive:bai_meizhen.serpent_kinship": ("Gate2Engine._resolve_command_cui", "Gate2Engine._cui_guard_and_rescue_default"),
    "passive:ling_qi.mirror_trace": ("Gate2Engine._maybe_gain_mirror_trace", "Gate2Engine._resolve_optional_rider"),
}

_REACTION_HANDLERS = {
    "reaction:an_eui.sheath_bone_guard": ("Gate2Engine._resolve_damage_reaction",),
    "reaction:bai_meizhen.spirit_intercession": ("Gate2Engine._resolve_attack_spec",),
    "reaction:bai_meizhen.water_shield": ("Gate2Engine._resolve_damage_reaction",),
    "reaction:core.stamina_guard": ("Gate2Engine._resolve_damage_reaction",),
    "reaction:ling_qi.qi_armor": ("Gate2Engine._resolve_attack_spec",),
    "reaction:ling_qi.rhythmic_guard": ("Gate2Engine._resolve_damage_reaction",),
}

_RESOURCE_HANDLERS = {
    "resource:an_eui.battle_hands": ("Gate2Engine._resolve_attack_spec",),
    "resource:an_eui.destruction_dice": ("Gate2Engine._create_match",),
    "resource:an_eui.martial_focus": ("Gate2Engine._resolve_attack_spec", "Gate2Engine._gain_resource"),
    "resource:an_eui.severance_edge": ("Gate2Engine._maybe_gain_severance", "Gate2Engine._resolve_first_arm"),
    "resource:an_eui.stamina": ("Gate2Engine._spend_resource", "Gate2Engine._gain_resource", "Gate2Engine._resolve_damage_reaction"),
    "resource:bai_meizhen.ancestral_resonance": ("Gate2Engine._maybe_gain_ancestral_resonance", "Gate2Engine._resolve_optional_rider"),
    "resource:bai_meizhen.cui_bond_strain": ("Gate2Engine._resolve_cui_strike", "Gate2Engine._cui_guard_and_rescue_default"),
    "resource:bai_meizhen.moon_sea_radiance": ("Gate2Engine._maybe_gain_moon_sea", "Gate2Engine._resolve_optional_rider", "Gate2Engine._resolve_sea_risen_bearing"),
    "resource:bai_meizhen.qi": ("Gate2Engine._spend_resource", "Gate2Engine._resolve_zone_action", "Gate2Engine._resolve_optional_rider"),
    "resource:lee_jia.lightning_charge": ("Gate2Engine._resolve_gather_charge", "Gate2Engine._resolve_lightning_lash", "Gate2Engine._expire_all_lightning_charges"),
    "resource:lee_jia.martial_focus": ("Gate2Engine._create_match",),
    "resource:lee_jia.prepared_talismans": ("Gate2Engine._spend_resource",),
    "resource:lee_jia.qi": ("Gate2Engine._spend_resource",),
    "resource:ling_qi.martial_focus": ("Gate2Engine._create_match",),
    "resource:ling_qi.mirror_trace": ("Gate2Engine._maybe_gain_mirror_trace", "Gate2Engine._resolve_optional_rider", "Gate2Engine._roll_save"),
    "resource:ling_qi.qi": ("Gate2Engine._spend_resource", "Gate2Engine._resolve_zone_action", "Gate2Engine._resolve_damage_reaction"),
}

_SYSTEM_HANDLERS = {
    "system:combat.action_economy": ("Gate2Engine._consume_economy", "Gate2Engine.legal_candidates"),
    "system:combat.attack_natural_results": ("Gate2Engine._resolve_attack_spec", "DeterministicRollAuthority.d20", "DeterministicRollAuthority.roll"),
    "system:combat.concentration": ("Gate2Engine._start_concentration", "Gate2Engine._concentration_check", "Gate2Engine._end_concentration"),
    "system:combat.cover_and_line_of_sight": ("SquareGrid.line_of_sight", "SquareGrid.cover_bonus", "Gate2Engine._action_candidates"),
    "system:combat.initiative": ("Gate2Engine._create_match",),
    "system:combat.nonlethal_defeat": ("Gate2Engine._defeat",),
    "system:combat.opportunity_attack": ("Gate2Engine._resolve_leave_reach",),
    "system:combat.saving_throw_modifiers": ("Gate2Engine._roll_save",),
    "system:combat.simultaneous_terminal": ("Gate2Engine._check_victory", "Gate2Engine._end_match"),
    "system:combat.temporary_hit_points": ("Gate2Engine._grant_temp_hp", "Gate2Engine._commit_damage"),
    "system:hazard.sect_training_court.qi_disruption": ("Gate2Engine._resolve_qi_hazard",),
}

_TALENT_HANDLERS = {
    "talent:an_eui.stomping_step": ("Gate2Engine._resolve_stomping_step",),
    "talent:lee_jia.aura_reading_countercurrent": ("Gate2Engine._resolve_countercurrent",),
    "talent:lee_jia.spark_step": ("Gate2Engine._resolve_optional_rider",),
}

_DISPOSITIONS = {
    "passive:lee_jia.reed_flex": "No Gate 2 trigger exists in the exact accepted fight surface; retained as an explicit no-use profile.",
    "resource:ling_qi.smoke_trace": "No source-authorized Gate 2 gain or spend exists; retained at zero and not exposed as a candidate.",
    "talent:an_eui.scouring_destruction": "Its executable contribution is already bound into action:an_eui.scouring_destruction_blast; no separate runtime trigger is emitted.",
}


def _available_handler_names() -> set[str]:
    names: set[str] = set()
    for cls in (Gate2Engine, SquareGrid, DeterministicRollAuthority):
        for name, member in inspect.getmembers(cls):
            if callable(member):
                names.add(f"{cls.__name__}.{name}")
    return names


def _handlers_for(source_id: str, status: str) -> tuple[tuple[str, ...], str]:
    if source_id in _DISPOSITIONS:
        return (), _DISPOSITIONS[source_id]
    if source_id == "creature:bai_cui":
        return (
            "Gate2Engine._resolve_command_cui",
            "Gate2Engine._resolve_cui_strike",
            "Gate2Engine._cui_default_dodge",
            "Gate2Engine._cui_guard_and_rescue_default",
        ), "First-class ActorState and nested companion activation."
    tables = (
        _ACTION_HANDLERS,
        _CONDITION_HANDLERS,
        _PASSIVE_HANDLERS,
        _REACTION_HANDLERS,
        _RESOURCE_HANDLERS,
        _SYSTEM_HANDLERS,
        _TALENT_HANDLERS,
    )
    for table in tables:
        if source_id in table:
            return table[source_id], "Concrete source-authorized runtime handlers."
    return (), "MISSING"


def build_runtime_profile_coverage(lock_path: Path) -> dict[str, Any]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    available = _available_handler_names()
    profiles: list[dict[str, Any]] = []
    for profile in lock["profiles"]:
        source_id = profile["source_definition_id"]
        status = profile["status"]
        handlers, disposition = _handlers_for(source_id, status)
        missing_handlers = sorted(set(handlers) - available)
        runtime_status = "COVERED"
        if disposition == "MISSING" or missing_handlers:
            runtime_status = "MISSING"
        elif status in {"LOCKED_TRACKED_PASSIVE", "LOCKED_NO_GATE2_USE"} and not handlers:
            runtime_status = "DISPOSITION_RECORDED"
        profiles.append(
            {
                "source_definition_id": source_id,
                "mechanics_lock_status": status,
                "profile_kind": profile["profile_kind"],
                "runtime_status": runtime_status,
                "handlers": list(handlers),
                "missing_handlers": missing_handlers,
                "disposition": disposition,
            }
        )
    missing = [p["source_definition_id"] for p in profiles if p["runtime_status"] == "MISSING"]
    result = {
        "schema": _SCHEMA,
        "mechanics_lock_sha256": lock["lock_sha256"],
        "profile_count": len(profiles),
        "covered_count": sum(p["runtime_status"] == "COVERED" for p in profiles),
        "disposition_count": sum(p["runtime_status"] == "DISPOSITION_RECORDED" for p in profiles),
        "missing_count": len(missing),
        "missing_profile_ids": missing,
        "profiles": profiles,
        "status": "PASS" if not missing else "FAIL",
    }
    return result


def write_runtime_profile_coverage(lock_path: Path, output_path: Path) -> dict[str, Any]:
    result = build_runtime_profile_coverage(lock_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical_bytes(result) + b"\n")
    return result
