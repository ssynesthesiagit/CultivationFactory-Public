from __future__ import annotations

import functools
import hashlib
import json
import os
import stat
import shutil
import unicodedata
import zipfile
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any
from character_sheet.path_display import path_display

from app.core import Database, FoundryError, canonical_json, sha256_bytes, sha256_file, sha256_json
from non_sphere_authority.method_mechanics import has_acquired_method
from non_sphere_authority.foundation_mechanics import has_acquired_foundation
from project_store.service import ProjectStore
from projector.service import ProjectionService
from character_sheet.current_rules import overlay_owner_current_rules


_DISPLAY_CONTRACT_NAME = "Tianxia_Fire_Qi_Character_Sheet_Display_Contract_R1.json"
_READINESS_PROFILE_NAME = "Tianxia_Character_Sheet_Readiness_Profile_R1.json"
_OWNER_SHEET_FILENAME = "Tianxia_Owner_Character_Sheet_v1.json"

_FORBIDDEN_DISPLAY_TOKENS = (
    "[object Object]",
    "TBD",
    "TODO",
    "placeholder",
    "lorem ipsum",
)

_LEGACY_REQUIRED_GM_SECTIONS = (
    "character",
    "core_stats",
    "background_origin",
    "path_selections",
    "spheres",
    "talents",
    "resources",
    "actions",
)

_COMPLETE_CHARACTER_SCHEMA = "TianxiaFoundry.CompleteCharacterMechanicsEnvelope.v1"
_COMPLETE_CHARACTER_SURFACE_IDS = (
    "overview_core_stats",
    "leveling",
    "background",
    "paths_subpaths",
    "spheres_talents",
    "insights",
    "actions",
    "forged_techniques",
    "manuals_recorded_arts",
    "immortal_arts",
    "foundation",
    "method",
    "companions",
    "equipment",
    "resources_states_suppression",
    "dao_i_ching",
    "diagnostics",
)

_COMPLETE_CHARACTER_MODEL_V1 = "Tianxia_GM_Character_Model_v1.json"
_COMPLETE_CHARACTER_MODEL_V2 = "Tianxia_GM_Character_Model_v2.json"
_COMPLETE_CHARACTER_VIEW = "Tianxia_GM_Character_View_Model_v2.json"
_COMPLETE_CHARACTER_DISPLAY_ROWS = "GM_Screen_Display_Rows.json"
_COMPLETE_CHARACTER_SURFACE_MEMBERS: dict[str, tuple[str, ...]] = {
    "overview_core_stats": (_COMPLETE_CHARACTER_VIEW, _COMPLETE_CHARACTER_MODEL_V2, _COMPLETE_CHARACTER_MODEL_V1),
    "leveling": ("Leveling_Ledger.json",),
    "background": ("Background_Origin_Ledger.json",),
    "paths_subpaths": (
        _COMPLETE_CHARACTER_DISPLAY_ROWS,
        _COMPLETE_CHARACTER_VIEW,
        _COMPLETE_CHARACTER_MODEL_V1,
        "Character_Master_Ledger.json",
    ),
    "spheres_talents": ("Selected_Spheres.json", "Talent_Source_Ledger.json", _COMPLETE_CHARACTER_DISPLAY_ROWS),
    "insights": ("Insight_Execution_Coverage.json", _COMPLETE_CHARACTER_DISPLAY_ROWS, "Character_Master_Ledger.json"),
    "actions": ("Complete_Action_Surface.json",),
    "forged_techniques": ("Forged_Techniques.json",),
    "manuals_recorded_arts": (
        "Martial_Arts_and_Manuals.json",
        "Manual_Lineage_Record.json",
        _COMPLETE_CHARACTER_VIEW,
        _COMPLETE_CHARACTER_MODEL_V1,
        _COMPLETE_CHARACTER_DISPLAY_ROWS,
    ),
    "immortal_arts": ("Immortal_Arts.json",),
    "foundation": ("Foundation_Detail_Ledger.json",),
    "method": ("Cultivation_Method_Profile.json",),
    "companions": ("Companion_Execution_Coverage.json", _COMPLETE_CHARACTER_VIEW, _COMPLETE_CHARACTER_MODEL_V1),
    "equipment": ("Equipment_Ledger.json",),
    "resources_states_suppression": (
        "Resources_and_States.json",
        _COMPLETE_CHARACTER_VIEW,
        _COMPLETE_CHARACTER_MODEL_V2,
        _COMPLETE_CHARACTER_MODEL_V1,
        "State_Effect_Registry.json",
        "Source_CL_and_Realm_Suppression.json",
    ),
    "dao_i_ching": ("Dao_IChing_Combat_Profile.json",),
    "diagnostics": (
        "Projection_Diagnostics.json",
        "Projection_Coverage_Report.json",
        "C2B3_Character_GM_Command_4_Validation.json",
        "C2B3_Character_GM_Deep_Audit.json",
        "C2B3_Character_GM_Live_Render_Seal.json",
        "Feature_Coverage_Manifest.json",
        "Release_Gate_Manifest.json",
        "Signature_Loadout.json",
        "Semantic_Validation_Report.json",
    ),
}
_COMPLETE_CHARACTER_DIAGNOSTIC_MEMBERS = _COMPLETE_CHARACTER_SURFACE_MEMBERS["diagnostics"]
_COMPLETE_CHARACTER_DISPLAY_TABS = {
    "paths_subpaths": "paths-subpaths",
    "spheres_talents": "spheres-talents",
    "insights": "insights",
    "manuals_recorded_arts": "martial-manuals-recorded-arts",
}
_COMPLETE_CHARACTER_UNSET = object()

_COMPLETE_CHARACTER_OVERVIEW_FIELDS = frozenset({
    "schema_version", "identity", "core_stats", "stats",
})
_COMPLETE_CHARACTER_OVERVIEW_NESTED_FIELDS = frozenset({
    "concept", "creature_type", "cultivation_level", "display_name", "key_ability", "path", "path_id",
    "path_ids", "paths", "proficiency_bonus", "realm", "realm_display", "size", "species", "title",
    "title_status", "display_name", "effective_cl", "selected_skills", "abilities", "ability", "modifier",
    "score", "armor_class", "base_value", "calculation", "conditional_note", "value", "hit_points",
    "maximum", "progression", "levels", "formula_id", "gain", "max_after_level", "initiative", "bonus",
    "check", "primary_resource", "build_state_current", "current_state_note", "definitions", "name", "skills",
    "speed", "generation", "walking_ft", "technique_attack_bonus", "technique_save_dc", "formula_trace",
    "node_count", "root", "schema_version", "subpath", "subpaths", "bindings", "subpath_id", "path_id",
})
_COMPLETE_CHARACTER_INSIGHT_OCCURRENCE_NESTED_FIELDS = frozenset({
    "insight_id", "name", "gained_at_cl", "acquisition_cl", "ability", "amount", "ability_change_applied", "repeat_index",
    "one_line_description", "full_description", "full_description_source", "description", "requirement", "benefit",
    "event_id", "event_hash", "sequence", "target_cl", "packet_id", "source_packet_ids", "source_record_hash",
    "source_record_id", "source_evidence", "content_binding", "execution_authority", "effect", "summary", "record_hash",
    "pack_id", "pack_version", "pack_hash", "source_path", "source_hash", "source_anchor", "source_id", "path", "anchor",
    "sha256", "source_file_sha256", "section_sha256", "action_types", "execution_profile", "execution_status",
    "manual_runtime_boundary", "resources", "rest_cadence", "action_or_procedure", "durations_detected", "expression_kind",
    "frequency_or_recharge", "ranges_detected", "recordkeeping_required", "resolution_methods", "resource_costs_detected",
    "source_cl_basis", "resource_id", "resource_name", "resource_cost", "resource_costs", "cost", "timing", "range", "target",
})
_COMPLETE_CHARACTER_LEVELING_FIELDS = frozenset({"schema_version", "levels"})
_COMPLETE_CHARACTER_LEVELING_NESTED_FIELDS = frozenset({
    *_COMPLETE_CHARACTER_INSIGHT_OCCURRENCE_NESTED_FIELDS,
    "cl", "event_id", "feature_record_id", "hp", "pb", "realm", "resource", "ability_scores_after",
    "formula_id", "gain", "max_after_level", "current_after_event", "maximum", "resource_id",
    "talent_record_ids_gained", "talent_record_ids_known", "trained_choices", "slot", "choice_type", "record_id", "source", "outcome", "bonus_talent_id", "schema", "mode", "route", "source_record_id", "source_provenance", "source_id", "source_hash", "source_anchor", "source_path", "record_hash", "rule_ids", "observed_play", "result", "counts_against_limit", "dice_simulated", "slot_cost", "state_after_hash", "STR", "DEX", "CON", "INT", "WIS", "CHA",
    "earned_feature_occurrences", "occurrence_id", "feature_id", "display_name", "parent_kind", "parent_record_id", "parent_record_hash",
    "parent_subpath_id", "parent_subpath_record_id", "owning_path_id", "required_path_level", "acquired_at_path_level",
    "acquired_at_character_cl", "acquisition_event", "attainment_event", "event", "source_backed", "acquisition_event_id", "acquisition_event_hash",
    "attainment_event_id", "attainment_event_hash", "event_hash", "event_sequence", "packet_id", "packet_ids", "source_packet_ids",
    "feature_record_hash", "derived_feature_hash", "components", "minimum_realm_band", "source_cl_basis", "source_text",
    "full_description", "full_description_source", "source_file_sha256", "factory_source_path", "line_start", "line_end",
    "section_sha256", "corpus_path", "source_file_hash", "source_record_hash", "kind", "insight_id", "target_cl", "sequence",
    "selection", "choice_kind", "deltas", "ability", "amount", "repeat_index", "insight_occurrence", "mechanical_identity",
    "mechanically_stacks", "stacking", "owning_path_level", "acquisition_cl", "attainment_cl", "derived_feature_snapshot",
    "canonical_id", "granted_at_cl", "source_evidence", "content_binding", "source_rules_text", "effective_rules_text",
})
_COMPLETE_CHARACTER_BACKGROUND_FIELDS = frozenset({"schema_version", "background_origin"})
_COMPLETE_CHARACTER_BACKGROUND_NESTED_FIELDS = frozenset({
    "background", "background_record_id", "background_talent_record_id", "background_talent_separate_from_learned_talents",
    "deception_expertise_result", "origin_insight", "origin_record_id", "ability_score_change", "background_id",
    "background_sphere", "background_talent", "languages", "name", "skill_proficiencies", "summary",
    "tool_proficiencies", "result", "selected_skill", "selected_tool", "selected_trade", "selected_language",
    "tool_expertise", "initiative_effect", "origin_insight_id", "source_backed",
})
_COMPLETE_CHARACTER_PATH_FIELDS = frozenset({
    "schema_version", "paths_subpaths", "paths_subpaths_insights", "path_selections", "subpaths", "path", "subpath",
    "earned_feature_occurrences",
})
_COMPLETE_CHARACTER_PATH_NESTED_FIELDS = frozenset({
    *_COMPLETE_CHARACTER_INSIGHT_OCCURRENCE_NESTED_FIELDS,
    "advancement_feature_record_ids", "bindings", "cinder_touch_record_id", "path", "path_feature_record_ids",
    "path_record_id", "path_record_ids", "paths", "source_granted_subpath_feature_record_ids", "subpath",
    "subpath_record_id", "subpath_record_ids", "subpaths", "display_name", "effective_cl", "key_ability", "path_id",
    "selected_skills", "name", "owning_path_id", "subpath_id", "selected_at_cl", "feature_ids_expected", "source_backed",
    "earned_feature_occurrences", "occurrence_id", "feature_id", "parent_kind", "parent_record_id", "parent_record_hash",
    "parent_subpath_id", "parent_subpath_record_id", "required_path_level", "acquired_at_path_level",
    "acquired_at_character_cl", "acquisition_event", "attainment_event", "event", "acquisition_event_id", "acquisition_event_hash",
    "attainment_event_id", "attainment_event_hash", "event_id", "event_hash", "event_sequence", "packet_id", "packet_ids",
    "source_packet_ids", "feature_record_hash", "derived_feature_hash", "components", "minimum_realm_band", "source_cl_basis",
    "source", "source_text", "full_description", "full_description_source", "source_hash", "source_file_sha256",
    "factory_source_path", "anchor", "line_start", "line_end", "section_sha256", "corpus_path", "source_path",
    "source_id", "source_file_hash", "source_record_hash", "kind", "record_id", "insight_id", "target_cl", "sequence",
    "selection", "choice_kind", "deltas", "ability_scores_after", "STR", "DEX", "CON", "INT", "WIS", "CHA", "ability", "amount", "repeat_index",
    "insight_occurrence", "mechanical_identity",
    "mechanically_stacks", "stacking", "owning_path_level", "acquisition_cl", "attainment_cl", "event_hash",
    "derived_feature_snapshot",
})
_COMPLETE_CHARACTER_SPHERE_FIELDS = frozenset({
    "schema_version", "spheres", "background_talents", "learned_talents", "spheres_talents",
    "automatic_sphere_component_record_ids", "automatic_sphere_components", "background_talent_record_id", "trained_choices",
    "cultivation_insight_occurrences", "cultivation_insight_record_ids", "learned_talent_record_ids", "sphere_record_ids",
})
_COMPLETE_CHARACTER_SPHERE_NESTED_FIELDS = frozenset({
    *_COMPLETE_CHARACTER_INSIGHT_OCCURRENCE_NESTED_FIELDS,
    "record_id", "display_name", "name", "one_line_description", "full_description", "full_description_source",
    "rules_text_source_locator", "description", "section",
    "subsection", "parent_sphere_id", "stage2_rule_id", "timing_or_category", "acquisition_cl", "acquisition_route",
    "owner_ruling", "display_only_not_execution_authority", "combat_execution_note", "capabilities", "ai_policy",
    "character_sheet", "combat_execution", "gm_display", "automatic_component_flags", "automatic_component_authority",
    "component_ids", "components", "component_id", "player_rules_text", "source_component_name",
    "counts_as_advancement_talent", "counts_as_talent_choice", "counts_as_training_talent", "automatic_grant", "trained_choices", "cl", "slot", "choice_type", "record_id", "source", "outcome", "bonus_talent_id", "schema", "mode", "route", "source_record_id", "source_provenance", "source_id", "source_hash", "source_anchor", "source_path", "record_hash", "rule_ids", "observed_play", "result", "counts_against_limit", "dice_simulated", "slot_cost",
    "structured_fields", "type", "value", "amount", "condition", "effect", "duration", "target", "range", "timing",
    "cost", "limit", "counterplay", "failure", "roll_save_check", "resource_costs", "resource_gains",
    "resource_requirements", "state_arrays", "state", "source_backed", "reason", "reason_code", "status",
})
_COMPLETE_CHARACTER_INSIGHT_FIELDS = frozenset({"schema_version", "coverage", "insights", "cultivation_insight_occurrences", "cultivation_insight_record_ids"})
_COMPLETE_CHARACTER_INSIGHT_NESTED_FIELDS = frozenset({
    *_COMPLETE_CHARACTER_INSIGHT_OCCURRENCE_NESTED_FIELDS,
    "record_id", "display_name", "name", "insight_id", "origin_insight_id", "occurrence_id", "source_backed", "state",
    "status", "coverage", "count", "required", "available", "selected_skill", "selected_tool", "selected_trade", "selected_language", "tool_expertise", "result", "summary", "initiative_effect",
    # Insight occurrences are milestone-bound display records.  Retain their
    # authenticated choice/effect and source bindings while continuing to
    # exclude arbitrary event payload metadata.
    "acquisition_cl", "event_id", "event_hash", "sequence", "target_cl", "packet_id", "source_packet_ids",
    "ability", "amount", "repeat_index", "effect", "content_binding", "source_evidence", "execution_authority",
    "record_hash", "pack_id", "pack_version", "pack_hash", "source_path", "source_hash", "source_anchor",
    "source_file_sha256", "section_sha256", "source_id", "source_record_hash", "source_record_id", "choice_kind",
})
_COMPLETE_CHARACTER_ACTION_FIELDS = frozenset({
    "schema_version", "status", "candidate_status", "execution_authority", "global_combat_readiness", "mechanical_authority",
    "signature_loadout_record_ids", "actions", "procedures", "ledger_order",
})
_COMPLETE_CHARACTER_ACTION_ROW_FIELDS = frozenset({
    "action_id", "record_id", "stable_id", "name", "display_name", "action_type", "type", "action_type_label", "bucket",
    "timing", "cost", "range", "target", "roll_save_check", "effect", "failure", "duration", "limit", "counterplay",
    "resource_costs", "resource_gains", "resource_requirements", "resource_cost_options", "state_arrays", "category",
    "one_line_description",
    "full_description", "capabilities", "combat_execution_status", "display_only_not_execution_authority", "ledger_ordinal",
    "runtime_kind",
})
_COMPLETE_CHARACTER_ACTION_NESTED_FIELDS = frozenset({
    "action_id", "record_id", "stable_id", "name", "display_name", "action_type", "type", "action_type_label", "bucket",
    "timing", "cost", "range", "target", "roll_save_check", "effect", "failure", "duration", "limit", "counterplay",
    "resource_costs", "resource_gains", "resource_requirements", "state_arrays", "category", "one_line_description",
    "full_description", "capabilities", "ai_policy", "character_sheet", "combat_execution", "gm_display",
    "combat_execution_status", "display_only_not_execution_authority", "ledger_ordinal", "runtime_kind", "amount", "condition",
    "resource_id", "minimum", "maximum", "current", "value", "text", "description", "ability", "ability_id", "check",
    "save", "attack", "dc", "formula", "dice", "damage", "damage_type", "kind", "state_id", "state", "application",
    "removal", "stacking", "quantity", "unit", "success", "on_success", "on_failure", "requirements", "requirement",
    "precondition", "preconditions", "priority", "priorities", "branch", "branches", "fallback", "sequence", "sequence_id",
    "action_ids", "ordered_action_ids", "resource_budget", "resources", "resource", "states", "state_array", "hook", "hooks",
    "dao", "i_ching", "dao_i_ching", "dao_i_ching_hooks", "dao_hooks", "i_ching_hooks", "goal", "tactical_goal",
    "classification", "status", "available", "required", "label", "order", "ordinal", "capability_status",
    "resource_cost_options", "default",
})
_COMPLETE_CHARACTER_RECORD_FIELDS = frozenset({
    "schema_version", "none_state", "forged_techniques", "manuals", "martial_manuals", "recorded_arts", "recorded_arts_none_state",
    "immortal_arts", "training_sources",
})
_COMPLETE_CHARACTER_RECORD_NESTED_FIELDS = frozenset({
    *_COMPLETE_CHARACTER_SPHERE_NESTED_FIELDS,
    *_COMPLETE_CHARACTER_ACTION_NESTED_FIELDS,
    "minimum_cl", "current_cl", "minimum", "maximum", "event_id", "mechanical_projection", "method", "foundation",
    # Manual lineage and recorded-art display fields.  These are explicit
    # source-backed members; arbitrary archive metadata remains filtered.
    "allocation_id", "contents", "false_routes", "methods", "recipes", "recorded_arts", "record_bindings", "theory", "warnings",
    "gained_at_cl", "mechanics_granted", "restrictions", "risks", "source_id", "source_packet_ids", "type", "record_text",
    "authority", "classification", "factory_source_type", "record_ids", "source_category", "summary", "profile_id", "profile_sha256",
    "acquisition_event_id", "acquisition_kind", "allowed_study_abilities", "associated_sphere_names", "associated_sphere_record_ids",
    "counts_against_trained_choices", "dm_facing_line", "execution", "execution_derivation", "expression_kind", "fixed_expression_warning",
    "learned_at_cl", "learning_dc", "access_category", "computed_dc", "difficulty", "prior_recorded_arts_this_cl", "rule_id", "value",
    "lineage_source", "background_id", "school_name", "sect_trial_sphere_id", "source_kind", "linked_action_id", "parent_manual_name", "parent_manual_record_id", "name",
    "outcome", "reproduced_component_names", "reproduced_component_record_ids", "requirements", "study_time", "technique_name",
    "training_source_access_event_id", "training_source_record_id", "source_block_sha256", "source_record_hash", "source_record_id",
    "state", "action_type", "attack_save_check", "augments", "backlash", "base_form", "cl_created", "complexity",
    "cp_cost", "drawbacks", "duration", "effect", "evolution_state", "exhausting", "known_after", "known_limit", "limits",
    "augment_id", "cp", "minimum_realm", "tier", "cp_reduction", "drawback_id", "restriction", "form_id", "starting_cp", "use",
    "final", "realm_maximum", "secondary_spheres", "drawback_reduction", "augment_names", "primary_effect_text",
    "material_cost_gp", "primary_sphere_effect", "research_days", "secondary_sphere_effects", "source_notes", "spheres_used", "sphere_id", "sphere_name",
    "talent_id", "talent_name", "talent_record_hash",
    "target_range_area", "technique_forging_dc", "technique_id", "action_surface", "activation_cp", "activation_cp_breakdown", "art_id",
    "automatic_construction", "burdens", "correspondence", "dao_aspect", "factor_escalation", "factors", "gm_review_required",
    "aspect_cp", "cp_modifier", "mandate_cost", "bridge_cp", "burden_cp_credit", "factor_cp", "formula", "aspect_cost", "bridge_factor_cost",
    "factor_cost", "source_package_modifier", "special_scale_cost", "bridge_factor_count", "bridge_rule", "matched_source_tags", "required_source_tags",
    "payment", "automatic_policy", "compiled_payload_hash", "factor_id",
    "component_record_ids", "derivation_kind", "source_execution_record_id", "factor_adapters",
    "heaven_pressure", "immortal_art_id", "key_ability", "mandate_complexity", "mandate_complexity_breakdown", "mandate_threshold",
    "owner_project_id", "path_id", "path_kind", "path_name", "pb_at_creation", "refinement_dc", "schema", "source_packages_used",
    "source_spheres_used", "source_record_ids", "steps", "activation", "area", "aspect_id", "base_source_resource_cost", "cleanup",
    "acquisition", "action_capacity", "at_owning_path_cl_14", "attack_roll", "bone_strike", "canonical_id", "corpus_path",
    "cp_credit", "cultivation_level", "default", "effective_effect", "excerpt", "factor_count", "feature_record_hash",
    "granted_at_cl", "guard_the_sovereign", "hp_restoration", "ownership", "reach", "realm", "roll", "saving_throws",
    "size", "stability_credit", "success_by_10", "threshold", "training_choice_cost",
    "cross_references", "dc_basis", "factor_application", "factor_ids", "failure_by_5", "normalized_procedure", "save_or_check",
    "source_binding", "source_mechanics", "source_tags", "success_by_5", "target", "trigger", "trigger_frequency", "resource_cost",
    "resource_name", "source_dependencies", "source_package_id", "supported_factor_ids", "acquired", "acquired_at_cl", "content_type",
    "credible_bridges", "feature_record_hash_kind", "owning_path_id", "progression", "published_text", "source_file_sha256",
    "factory_source_path", "path", "anchor", "sha256", "source_hash", "line_start", "line_end", "section_sha256", "source_section_sha256", "source_selection_score", "payload",
    "step", "source_chassis", "mechanical_chassis", "source_specific_mechanics", "source_healing_preserved", "source_action_preserved", "base_source_cp",
    "base_source_effect", "base_source_resource", "native_source_healing", "native_healing", "healing_output", "healing_formula",
    "restoration_check", "restoration_factor", "result_bands", "replacement", "replacement_rule", "resolution", "anti_healing",
    "secondary_benefits", "unaffected_harm", "healing", "cap", "die", "base_dice", "modifier", "factor_source", "feature_snapshot",
    "feature_record_id", "parent_record_id", "parent_record_hash", "parent_path_id", "owning_path_cl", "path_ability", "path_ability_modifier",
    "path_realm", "path_realm_input", "published_section", "source_line", "sidecar_file_sha256", "sidecar_path", "asset_type", "created_subject",
    "created_subject_frame", "creation_frame", "construct_puppet_body_creation", "command", "statistics", "hit_points", "armor_class",
    "attacks", "senses", "speed", "speech", "immunities", "movement", "maintenance", "options", "package", "rows", "source",
    "full_description", "full_description_source", "display_name", "feature_id", "minimum_realm_band", "source_cl_basis", "source_text",
})
_COMPLETE_CHARACTER_FOUNDATION_METHOD_FIELDS = frozenset({"schema_version", "foundation", "method"})
_COMPLETE_CHARACTER_FOUNDATION_METHOD_NESTED_FIELDS = frozenset({
    "record_id", "display_name", "name", "state", "status", "source_backed", "event_id", "mechanical_projection",
    "foundation_id", "method_id", "description", "summary", "capabilities", "character_sheet", "combat_execution", "gm_display",
    "full_description", "full_description_source", "source", "source_hash", "source_path", "source_anchor", "source_id",
    "source_packet_ids", "record_hash", "factory_source_path", "anchor", "source_file_sha256", "line_start", "line_end", "section_sha256",
    "path", "sha256", "display_only_not_execution_authority",
    # Display the authenticated lifecycle and source profiles. Formula ASTs
    # remain internal; the sheet consumes the causal resource totals elsewhere.
    "activation_event_id", "mechanics", "schema", "registry_sha256", "method_record_sha256",
    "per_path_resource_profiles", "path_id", "resource_id", "resource_name", "source_text",
    "delta_proficiency_bonus_units", "exact_modifier", "shape_key", "applies_independently",
    "conversion_permitted", "conversion_rule", "activation_min_cl", "refill_current",
    "acquisition_event_id", "stage", "initial_state", "mechanics_schema", "source_record_sha256",
    "stage_options", "default_stage", "active_expression_path_ids", "unsupported_active_path_ids", "dormant_expression_path_ids",
    "resource", "initial_current", "current", "maximum", "rule_descriptions", "source_rules_sha256", "execution_authority",
    "awards_stage_advancement", "grants_path_attainment", "source_passives", "source_fields", "source_feature_sha256",
    "Type", "Action", "Available At", "Trigger", "Effect", "Limit", "Range", "Target", "Duration", "Cost", "Counterplay and Boundaries",
    "conditional_modifiers", "statistic", "scope", "feature_name", "availability",
})
_COMPLETE_CHARACTER_COMPANION_FIELDS = frozenset({"schema_version", "coverage", "companions", "spirit_companions"})
_COMPLETE_CHARACTER_COMPANION_NESTED_FIELDS = frozenset({
    "companion_id", "record_id", "name", "display_name", "description", "state", "status", "coverage", "available",
    "required", "execution_authority", "linked_action_ids", "action_ids", "requirements", "preconditions", "source_backed",
})
_COMPLETE_CHARACTER_EQUIPMENT_FIELDS = frozenset({"schema_version", "equipment", "none_state"})
_COMPLETE_CHARACTER_EQUIPMENT_NESTED_FIELDS = frozenset({
    "item_id", "record_id", "name", "display_name", "description", "type", "quantity", "equipped", "state", "status",
    "source_backed", "reason", "reason_code", "available", "owner", "capacity", "properties",
    "starting_kit", "items", "trinkets", "coin_cc", "text", "printed", "source", "value_cc", "path_option",
    "resolved_treasure_weapon", "grade", "grade_label", "chassis", "material", "refinement_bonus", "enchantments",
    "enchantment_capacity", "total_effective_bonus", "value_gt", "damage", "affinities", "property_name", "property_text",
    "equivalent_bonus", "family", "resolved_treasure_armor", "resolved_treasure_purchases", "enhancements", "armor_class",
    "armor_category", "wondrous", "consumables", "item_type", "attunement_slots", "batch_quantity", "batch_unit",
    "batch_price_gt", "activation",
})
_COMPLETE_CHARACTER_RESOURCE_FIELDS = frozenset({
    "schema_version", "equipment_resources_states", "resources", "states", "status", "rule_exports", "character_cl",
})
_COMPLETE_CHARACTER_RESOURCE_NESTED_FIELDS = frozenset({
    "equipment", "resources", "states", "entries", "none_state", "resource_id", "name", "display_name", "description", "current", "maximum", "definitions", "build_state_current",
    "qi_maximum", "max",
    "current_state_note", "amount", "condition", "timing", "minimum", "maximum", "state_id", "state", "effect", "duration",
    "type", "status", "character_cl", "rule_id", "source_backed", "available", "required", "suppression", "rule", "value",
})
_COMPLETE_CHARACTER_DAO_FIELDS = frozenset({"schema_version", "dao", "i_ching", "dao_i_ching", "classification", "execution_authority"})
_COMPLETE_CHARACTER_DAO_NESTED_FIELDS = frozenset({
    "authoring_id", "core_theme", "display_name", "gm_usage_notes", "mechanical_effects", "principles", "relevant_record_ids",
    "risks", "roleplay_expression", "strengths", "tactical_expression", "effect", "duration", "condition", "state", "status",
})
_COMPLETE_CHARACTER_SURFACE_PROJECTION = {
    "overview_core_stats": (_COMPLETE_CHARACTER_OVERVIEW_FIELDS, _COMPLETE_CHARACTER_OVERVIEW_NESTED_FIELDS),
    "leveling": (_COMPLETE_CHARACTER_LEVELING_FIELDS, _COMPLETE_CHARACTER_LEVELING_NESTED_FIELDS),
    "background": (_COMPLETE_CHARACTER_BACKGROUND_FIELDS, _COMPLETE_CHARACTER_BACKGROUND_NESTED_FIELDS),
    "paths_subpaths": (_COMPLETE_CHARACTER_PATH_FIELDS, _COMPLETE_CHARACTER_PATH_NESTED_FIELDS),
    "spheres_talents": (_COMPLETE_CHARACTER_SPHERE_FIELDS, _COMPLETE_CHARACTER_SPHERE_NESTED_FIELDS),
    "insights": (_COMPLETE_CHARACTER_INSIGHT_FIELDS, _COMPLETE_CHARACTER_INSIGHT_NESTED_FIELDS),
    "forged_techniques": (_COMPLETE_CHARACTER_RECORD_FIELDS, _COMPLETE_CHARACTER_RECORD_NESTED_FIELDS),
    "manuals_recorded_arts": (_COMPLETE_CHARACTER_RECORD_FIELDS, _COMPLETE_CHARACTER_RECORD_NESTED_FIELDS),
    "immortal_arts": (_COMPLETE_CHARACTER_RECORD_FIELDS, _COMPLETE_CHARACTER_RECORD_NESTED_FIELDS),
    "foundation": (_COMPLETE_CHARACTER_FOUNDATION_METHOD_FIELDS, _COMPLETE_CHARACTER_FOUNDATION_METHOD_NESTED_FIELDS),
    "method": (_COMPLETE_CHARACTER_FOUNDATION_METHOD_FIELDS, _COMPLETE_CHARACTER_FOUNDATION_METHOD_NESTED_FIELDS),
    "companions": (_COMPLETE_CHARACTER_COMPANION_FIELDS, _COMPLETE_CHARACTER_COMPANION_NESTED_FIELDS),
    "equipment": (_COMPLETE_CHARACTER_EQUIPMENT_FIELDS, _COMPLETE_CHARACTER_EQUIPMENT_NESTED_FIELDS),
    "resources_states_suppression": (_COMPLETE_CHARACTER_RESOURCE_FIELDS, _COMPLETE_CHARACTER_RESOURCE_NESTED_FIELDS),
    "dao_i_ching": (_COMPLETE_CHARACTER_DAO_FIELDS, _COMPLETE_CHARACTER_DAO_NESTED_FIELDS),
}


def _foundation_printed_chapter(foundation: Mapping[str, Any]) -> list[dict[str, str]] | None:
    """The Foundation's published chapter, split at its numbered headings.

    Display only.  The section comes from the pinned v0.4C catalogue and must
    match the section hash the Foundation record itself carries.
    """

    import re

    from character_creation import foundation_corpus_release

    foundation_id = foundation.get("foundation_id")
    initial = (foundation.get("mechanics") or {}).get("initial_state") or {}
    expected = (initial.get("source") or {}).get("section_sha256")
    if not isinstance(foundation_id, str) or not isinstance(expected, str):
        return None
    try:
        section = foundation_corpus_release.verified_sections().get(
            f"{foundation_corpus_release.MEMBER_PREFIX}{foundation_id}.md"
        )
    except (FoundryError, OSError, ValueError):
        return None
    if not section or hashlib.sha256(section).hexdigest() != expected:
        return None
    text = section.decode("utf-8")
    parts = re.split(r"^## \d+\. (.+)$", text, flags=re.M)
    profile = re.sub(r"^# .+\n", "", parts[0], count=1).strip()
    chapter = [{"heading": "Profile", "text": profile}] if profile else []
    for index in range(1, len(parts) - 1, 2):
        body = parts[index + 1].strip()
        if body:
            chapter.append({"heading": parts[index].strip(), "text": body})
    return chapter or None


@functools.lru_cache(maxsize=2)
def _method_registry_rows(path_text: str, expected_sha256: str) -> dict[str, dict[str, Any]]:
    data = Path(path_text).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        return {}
    return {row["method_id"]: row for row in json.loads(data)["methods"] if isinstance(row, dict) and "method_id" in row}


def method_printed_entry(method: Mapping[str, Any]) -> dict[str, Any] | None:
    """Published owner-facing Method entry for creation and Grow. Display only.

    Read from the typed Method registry pinned by the record's own
    ``registry_sha256``.
    """

    mechanics = method.get("mechanics") or {}
    method_id = mechanics.get("method_id") or method.get("record_id")
    expected = mechanics.get("registry_sha256")
    if not isinstance(method_id, str) or not isinstance(expected, str):
        return None
    path = Path(__file__).resolve().parents[1] / "non_sphere_authority" / "authority" / "Tianxia_Methods_Typed_Registry_v0_6.json"
    try:
        row = _method_registry_rows(str(path), expected).get(method_id)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(row, dict):
        return None
    readable = row.get("owner_readable") or {}
    source = row.get("source_text") or {}
    acquisition = row.get("acquisition") or {}

    def text(value: Any) -> str:
        return value.strip().rstrip(".") + "." if isinstance(value, str) and value.strip() else ""

    tier = acquisition.get("access_tier")
    fields = [
        ("AP route", readable.get("ap_route_summary")),
        ("Resource", readable.get("resource_summary")),
        ("Breakthroughs", readable.get("breakthrough_summary")),
        ("Foundation relationship", readable.get("foundation_summary")),
        ("Compatible themes", source.get("compatible_themes_text")),
    ]
    access = [
        ("Access", tier.replace("_", " ").capitalize() if isinstance(tier, str) else None),
        ("Used by", acquisition.get("common_users")),
        ("Suited to", readable.get("access_summary")),
        ("Becoming Primary", acquisition.get("becoming_primary")),
    ]
    switching = row.get("switching_lifecycle") or {}
    return {
        "description": text(readable.get("full_description")),
        "fields": [{"label": label, "text": text(value)} for label, value in fields if text(value)],
        "access": [{"label": label, "text": text(value)} for label, value in access if text(value)],
        "risks": [text(value) for value in row.get("risks_limitations") or [] if text(value)],
        "switching": [
            {"label": label, "text": text(switching.get(key))}
            for key, label in (
                ("future_ap_rule", "Future AP"),
                ("resource_recalculation", "Resources"),
                ("path_features_after_switch", "Path features"),
                ("foundation_expression_rule", "Foundation expressions"),
            )
            if text(switching.get(key))
        ],
    }


class CharacterSheetService:
    """Deterministic owner-facing character read model.

    Mechanical state comes only from the canonical project, committed events,
    and the sealed projector artifacts. Source-backed display prose is governed
    by a small checksummed display contract and never promoted to execution
    authority.
    """

    def __init__(self, db: Database):
        self.db = db
        self.projects = ProjectStore(db)
        self.projections = ProjectionService(db)

    @property
    def _contracts_dir(self) -> Path:
        return Path(__file__).resolve().parent / "contracts"

    @classmethod
    def _creation_feature_choices(cls, project: dict[str, Any], path_feature_ids: list[str]) -> dict[str, Any]:
        """The Defensive Discipline (and other build) picks recorded at creation, in the compiler's grant shape."""
        from character_creation.feature_choices import resolve as resolve_feature_choices

        picks = cls._user_locks(project).get("character_sheet.feature_choices") or {}
        if not picks:
            return {}
        return resolve_feature_choices([{"canonical_id": row, "display_name": row} for row in path_feature_ids], picks, required=False)

    @staticmethod
    def _user_locks(project: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in project.get("user_locks") or []:
            if isinstance(item, dict) and isinstance(item.get("field"), str):
                result[item["field"]] = item.get("value")
        return result

    @staticmethod
    def _owner_lock_rows(project: dict[str, Any]) -> list[dict[str, Any]]:
        rows = [dict(item) for item in project.get("user_locks") or [] if isinstance(item, dict)]
        rows.sort(key=lambda item: (int(item.get("created_revision") or 0), str(item.get("lock_id") or "")))
        return rows

    @staticmethod
    def _verify_sealed_json(path: Path, *, expected_schema: str, error_prefix: str) -> tuple[dict[str, Any], str]:
        if not path.is_file():
            raise FoundryError(f"{error_prefix}_MISSING", f"Required sealed Character Sheet contract is missing: {path.name}")
        sidecar = path.with_suffix(path.suffix + ".sha256")
        if not sidecar.is_file():
            raise FoundryError(f"{error_prefix}_SIDECAR_MISSING", f"Required detached checksum is missing: {sidecar.name}")
        try:
            digest, declared_name = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
            declared_name = declared_name.strip().lstrip("*")
        except ValueError as exc:
            raise FoundryError(f"{error_prefix}_SIDECAR_INVALID", "The detached checksum sidecar is malformed.") from exc
        actual = sha256_file(path)
        if declared_name != path.name or digest.lower() != actual:
            raise FoundryError(
                f"{error_prefix}_STALE",
                "The sealed Character Sheet contract does not match its detached checksum.",
                details={"path": str(path), "expected": digest.lower(), "actual": actual, "declared_name": declared_name},
            )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != expected_schema:
            raise FoundryError(
                f"{error_prefix}_SCHEMA_UNSUPPORTED",
                "The Character Sheet contract schema is unsupported.",
                details={"expected": expected_schema, "actual": payload.get("schema_version")},
            )
        internal = payload.get("seal_sha256")
        unsigned = dict(payload)
        unsigned.pop("seal_sha256", None)
        calculated = sha256_json(unsigned)
        if not isinstance(internal, str) or internal != calculated:
            raise FoundryError(
                f"{error_prefix}_INTERNAL_SEAL_INVALID",
                "The Character Sheet contract internal seal is invalid.",
                details={"expected": internal, "actual": calculated},
            )
        return payload, actual

    def _display_contract(
        self,
        ledger: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], str]:
        ledger = ledger or {}
        provenance = provenance or {}
        project_contract = provenance.get("project_display_contract")
        if project_contract:
            unsigned = dict(project_contract)
            seal = unsigned.pop("seal_sha256", None)
            snapshot = provenance.get("typed_choice_snapshot") or {}
            if (
                project_contract.get("schema_version") != "TianxiaFoundry.CharacterSheetDisplayContract.v1"
                or project_contract.get("canonical_project_id") != (ledger.get("character") or {}).get("character_id")
                or project_contract.get("typed_choice_snapshot_sha256") != snapshot.get("snapshot_sha256")
                or seal != sha256_json(unsigned)
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_DISPLAY_CONTRACT_STALE",
                    "The project-derived Character Sheet display contract is not bound to the exact typed choice snapshot.",
                )
            return deepcopy(project_contract), sha256_json(project_contract)
        return self._verify_sealed_json(
            self._contracts_dir / _DISPLAY_CONTRACT_NAME,
            expected_schema="TianxiaFoundry.CharacterSheetDisplayContract.v1",
            error_prefix="CHARACTER_SHEET_DISPLAY_CONTRACT",
        )

    def _readiness_profile(self) -> tuple[dict[str, Any], str]:
        return self._verify_sealed_json(
            self._contracts_dir / _READINESS_PROFILE_NAME,
            expected_schema="TianxiaFoundry.CharacterSheetReadinessProfile.v1",
            error_prefix="CHARACTER_SHEET_READINESS_PROFILE",
        )

    def _blueprint(self, project_id: str) -> dict[str, Any] | None:
        with self.db.connection() as conn:
            row = conn.execute(
                """SELECT p.projection_json,p.projection_hash,c.committed_at,c.approved_by
                   FROM stage1_blueprint_heads h
                   JOIN stage1_blueprint_commits c ON c.commit_id=h.commit_id
                   JOIN stage1_blueprint_projections p ON p.commit_id=c.commit_id
                   WHERE h.project_id=?""",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["projection_json"])
        intent = payload.get("intent_state") or {}
        decisions = intent.get("decisions") or []
        selected: dict[str, list[dict[str, Any]]] = {}
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            records = decision.get("record_snapshots") or []
            normalized_records: list[dict[str, Any]] = []
            for record in records:
                if not isinstance(record, dict):
                    continue
                choice = record.get("choice_snapshot")
                if isinstance(choice, dict):
                    item = dict(choice)
                    item.setdefault("choice_id", record.get("record_id"))
                    item["authority_snapshot"] = {
                        key: record.get(key)
                        for key in ("record_id", "record_hash", "pack_id", "pack_version", "pack_hash", "choice_snapshot_hash")
                        if record.get(key) is not None
                    }
                    normalized_records.append(item)
                else:
                    normalized_records.append(dict(record))
            selected[str(decision.get("slot_id") or "unknown")] = normalized_records
        return {
            "status": "BLUEPRINT_COMMITTED",
            "projection_hash": row["projection_hash"],
            "committed_at": row["committed_at"],
            "approved_by": row["approved_by"],
            "mechanical_authority": False,
            "selected_records": selected,
            "planner_rationale": intent.get("planner_rationale") or "",
            "authored_notes": intent.get("authored_notes") or [],
        }

    def _compiled_artifacts(self, project_id: str) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any]]:
        try:
            status = self.projections.status(project_id)
        except FoundryError as exc:
            if exc.code in {"PROJECTION_NOT_FOUND", "PROJECT_NOT_FOUND"}:
                return None, {"status": "NOT_COMPILED", "eligible_for_command5": False}
            raise
        if status.get("status") != "READY":
            return None, status
        names = (
            "Character_Master_Ledger.json",
            "Rules_Selection_Packets.json",
            "Projection_Provenance_Map.json",
            "Projection_Coverage_Report.json",
            "Projection_Diagnostics.json",
        )
        artifacts: dict[str, dict[str, Any]] = {}
        try:
            for name in names:
                artifacts[name] = json.loads(self.projections.artifact(project_id, name).read_text(encoding="utf-8"))
        except (FoundryError, OSError, json.JSONDecodeError):
            return None, status
        return artifacts, status

    @staticmethod
    def _legacy_completed_gm_ready(ledger: dict[str, Any] | None, projection_status: dict[str, Any]) -> bool:
        """Preserve genuinely complete historical v1 export behavior.

        This is deliberately stricter than the legacy eligible_for_command5 bit:
        a stage-aware ledger is never treated as GM-ready, and every historical
        complete section must be materially populated.
        """
        if not ledger or ledger.get("readiness"):
            return False
        if not projection_status.get("eligible_for_command5"):
            return False
        if projection_status.get("command5_status") not in {None, "NOT_RUN", "COMMAND_5_GM_SCREEN_CANDIDATE_READY"}:
            return False
        return all(ledger.get(key) not in (None, "", [], {}) for key in _LEGACY_REQUIRED_GM_SECTIONS)

    @staticmethod
    def _record_ids_required(ledger: dict[str, Any], packets: dict[str, Any]) -> set[str]:
        required = {
            str(packet.get("record_id"))
            for packet in packets.get("packets") or []
            if isinstance(packet, dict)
            and packet.get("record_id")
            and packet.get("advancement_kind") != "non_sphere_method_access"
        }
        for feature in ledger.get("features") or []:
            if isinstance(feature, dict) and feature.get("feature_id"):
                required.add(str(feature["feature_id"]))
        for component in ledger.get("automatic_sphere_components") or []:
            if isinstance(component, dict) and component.get("component_id"):
                required.add(str(component["component_id"]))
        for receipt in ledger.get("automatic_sphere_component_receipts") or []:
            if not isinstance(receipt, dict):
                continue
            for component in receipt.get("components") or []:
                if isinstance(component, dict) and component.get("component_id"):
                    required.add(str(component["component_id"]))
        return required

    @staticmethod
    def _build_record_cards(
        ledger: dict[str, Any],
        packets: dict[str, Any],
        contract: dict[str, Any],
        contract_sha256: str,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        rules = contract.get("rules") or []
        by_record: dict[str, dict[str, Any]] = {}
        duplicate_ids: list[str] = []
        for rule in rules:
            if not isinstance(rule, dict) or not isinstance(rule.get("record_id"), str):
                raise FoundryError("CHARACTER_SHEET_DISPLAY_MAPPING_INVALID", "A display-contract rule lacks a stable record ID.")
            record_id = rule["record_id"]
            if record_id in by_record:
                duplicate_ids.append(record_id)
            by_record[record_id] = rule
        if duplicate_ids:
            raise FoundryError(
                "CHARACTER_SHEET_DUPLICATE_DISPLAY_MAPPING",
                "A selected record would be rendered more than once.",
                details={"record_ids": sorted(set(duplicate_ids))},
            )

        required = CharacterSheetService._record_ids_required(ledger, packets)
        mapped = set(by_record)
        missing = sorted(required - mapped)
        if missing:
            raise FoundryError(
                "CHARACTER_SHEET_DISPLAY_MAPPING_MISSING",
                "One or more selected records have no sealed Character Sheet display mapping.",
                details={"record_ids": missing},
            )
        unexpected = sorted(mapped - required)
        if unexpected:
            raise FoundryError(
                "CHARACTER_SHEET_DISPLAY_MAPPING_UNSELECTED",
                "The display contract contains a record not selected by this character.",
                details={"record_ids": unexpected},
            )

        packet_by_id = {
            str(packet.get("packet_id")): packet
            for packet in packets.get("packets") or []
            if isinstance(packet, dict) and packet.get("packet_id")
        }
        cards: list[dict[str, Any]] = []
        for record_id in sorted(required):
            rule = by_record[record_id]
            source = rule.get("source") or {}
            if not all(isinstance(source.get(key), str) and source.get(key) for key in ("path", "anchor", "source_hash")):
                raise FoundryError(
                    "CHARACTER_SHEET_DESCRIPTION_UNPROVEN",
                    "A Character Sheet display description lacks exact source identity.",
                    details={"record_id": record_id},
                )
            one_line = rule.get("one_line_description")
            full = rule.get("full_description")
            if not isinstance(one_line, str) or not one_line.strip() or not isinstance(full, str) or not full.strip():
                raise FoundryError(
                    "CHARACTER_SHEET_DESCRIPTION_UNPROVEN",
                    "A Character Sheet display description is missing or empty.",
                    details={"record_id": record_id},
                )
            packet_ids = list((rule.get("acquisition_source") or {}).get("packet_ids") or [])
            absent_packets = sorted(packet_id for packet_id in packet_ids if packet_id not in packet_by_id)
            if absent_packets and (ledger.get("advancement") or {}).get("historical_prefix_preserved") is False:
                acquisition_source = rule.get("acquisition_source") or {}
                matches = [
                    packet
                    for packet in packet_by_id.values()
                    if packet.get("record_id") == record_id
                    and packet.get("advancement_kind") == acquisition_source.get("advancement_kind")
                    and packet.get("target_cl") == acquisition_source.get("target_cl")
                ]
                if len(matches) == 1:
                    # Current project identities necessarily produce new event and
                    # packet hashes. Rebind only by the exact stable record, typed
                    # acquisition kind, and CL; historical packages retain their
                    # sealed packet IDs unchanged.
                    packet_ids = [matches[0]["packet_id"]]
                    absent_packets = []
            if absent_packets:
                raise FoundryError(
                    "CHARACTER_SHEET_PACKET_BINDING_MISSING",
                    "A display mapping refers to a source packet that is not in the canonical projection.",
                    details={"record_id": record_id, "packet_ids": absent_packets},
                )
            capabilities = deepcopy(rule.get("capabilities") or {})
            if capabilities.get("character_sheet") != "SUPPORTED":
                raise FoundryError(
                    "CHARACTER_SHEET_CAPABILITY_UNSUPPORTED",
                    "A selected record is not declared supported for owner-facing Character Sheet display.",
                    details={"record_id": record_id, "capability": capabilities.get("character_sheet")},
                )
            combat = capabilities.get("combat_execution")
            if combat not in {"SUPPORTED", "NOT_APPLICABLE"} and rule.get("display_only_not_execution_authority") is not True:
                raise FoundryError(
                    "CHARACTER_SHEET_FALSE_EXECUTION_CLAIM",
                    "Display prose would be promoted to combat authority without a typed execution definition.",
                    details={"record_id": record_id, "combat_execution": combat},
                )
            acquisition = deepcopy(rule.get("acquisition_source") or {})
            cards.append({
                "record_id": record_id,
                "record_hash": rule.get("record_hash"),
                "display_name": rule.get("display_name"),
                "section": rule.get("section"),
                "subsection": rule.get("subsection"),
                "acquisition_cl": acquisition.get("target_cl"),
                "acquisition_route": acquisition.get("advancement_kind"),
                "source_packet_ids": packet_ids,
                "timing_or_category": rule.get("display_timing_or_category"),
                "one_line_description": one_line.strip(),
                "full_description": full.strip(),
                "full_description_source": rule.get("full_description_source"),
                "source": {
                    "path": source["path"],
                    "anchor": source["anchor"],
                    "sha256": source["source_hash"],
                },
                "stage2_rule_id": rule.get("stage2_rule_id"),
                "display_contract": {
                    "contract_id": contract.get("contract_id"),
                    "contract_sha256": contract_sha256,
                },
                "capabilities": capabilities,
                "display_only_not_execution_authority": bool(rule.get("display_only_not_execution_authority")),
                "parent_sphere_id": rule.get("parent_sphere_id"),
                "component_hash": rule.get("component_hash"),
                "automatic_component_flags": deepcopy(rule.get("automatic_component_flags") or {}),
                "owner_ruling": deepcopy(rule.get("owner_ruling") or {}),
                "automatic_component_authority": deepcopy(rule.get("automatic_component_authority") or {}),
                "combat_execution_note": (
                    "Typed combat execution is available."
                    if combat == "SUPPORTED"
                    else "Combat execution is not yet typed; this description is display-only."
                    if combat != "NOT_APPLICABLE"
                    else "No combat execution definition is applicable."
                ),
            })
        cards.sort(key=lambda item: (
            str(item.get("section") or ""),
            -1 if item.get("acquisition_cl") is None else int(item.get("acquisition_cl")),
            str(item.get("display_name") or "").casefold(),
            item["record_id"],
        ))
        return cards, {card["record_id"]: card for card in cards}

    @staticmethod
    def _skills(core: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        multipliers = core.get("skill_proficiency_multipliers") or {}
        bonuses = core.get("skills") or {}
        sources = core.get("skill_sources") or {}
        ability_map = core.get("skill_ability_map") or {}
        for skill in sorted(set(bonuses) | set(multipliers) | set(sources), key=str.casefold):
            multiplier = int(multipliers.get(skill) or 0)
            rows.append({
                "skill": skill,
                "ability": ability_map.get(skill),
                "bonus": bonuses.get(skill),
                "proficiency": "expertise" if multiplier >= 2 else "proficient" if multiplier == 1 else "untrained",
                "proficiency_multiplier": multiplier,
                "sources": sorted(str(value) for value in sources.get(skill) or []),
            })
        return rows

    # Sections whose display cards are catalog rule text rather than a
    # one-line mechanical summary.  The catalog normalizer fills the sealed
    # display contract's full_description with the printed entry's first line
    # ("Action Type: Bonus Action"), so the real rules paragraph has to come
    # from the locked source block at the record's own anchor.
    _RULES_TEXT_SECTIONS = ("talents", "background_talent", "sphere_automatic_components", "spheres", "background_origin", "insights")
    # A sealed display text shorter than this is the catalog's first line, not
    # a rules paragraph; only those cards are worth re-reading the pack for.
    _RULES_TEXT_MIN_CHARS = 200

    def _authenticated_factory_root(self) -> Path | None:
        """Return the installed Factory root, or None when it is not configured."""

        try:
            return self.projections._factory_root()
        except FoundryError:
            return None

    def _authenticated_rules_block(
        self,
        source: dict[str, Any],
        factory_root: Path | None,
    ) -> tuple[str, str]:
        """Return (rules text, section identity) for one locked source anchor.

        The block is read from the installed pack and the source file must hash
        to the record's sealed ``source_hash``; anything unverifiable yields an
        empty string rather than a guess.
        """

        if factory_root is None or not isinstance(source, dict):
            return "", ""
        path_value = source.get("path")
        anchor_value = source.get("anchor")
        source_hash = source.get("sha256") or source.get("source_hash")
        if not all(isinstance(value, str) and value for value in (path_value, anchor_value, source_hash)):
            return "", ""
        try:
            from character_creation.constructed_arts.sources import published_block

            block = published_block(
                factory_root,
                {"path": path_value, "anchor": anchor_value, "source_hash": source_hash},
            )
        except (FoundryError, OSError, TypeError, ValueError):
            return "", ""
        if not isinstance(block, str) or not block.strip():
            return "", ""
        section_identity = f"{path_value}::{anchor_value}"
        return block.strip(), section_identity

    @staticmethod
    @functools.lru_cache(maxsize=4)
    def _verified_json(path_text: str, expected_sha256: str) -> Any:
        """Read one authenticated JSON file, or None when the bytes do not match."""

        try:
            path = Path(path_text)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @classmethod
    @functools.lru_cache(maxsize=4)
    def _talent_sphere_name_sources(cls, pairs: tuple[tuple[str, str], ...]) -> dict[str, str]:
        """Map talent record ids to their Sphere name from the sealed catalogs.

        The Character Sheet's talent rows carry a null ``parent_sphere_id``, so
        the Sphere a Talent belongs to exists only in the authenticated Sphere
        and Talent catalogs: the canonical Factory catalog for the source
        talents, and the classification authority for the ones the Factory
        synthesizes.  This returns display labels only, never mechanical
        authority, and both files are hash-checked before use.
        """

        names: dict[str, str] = {}
        for path_text, expected_sha256 in pairs:
            payload = cls._verified_json(path_text, expected_sha256)
            if not isinstance(payload, dict):
                continue
            for key in ("records", "synthesized_talents"):
                source = payload.get(key)
                if isinstance(source, dict):
                    rows = list(source.values())
                elif isinstance(source, list):
                    rows = source
                else:
                    continue
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    record_id = row.get("record_id") or row.get("canonical_talent_id")
                    sphere_name = row.get("sphere_name") or row.get("canonical_source_sphere")
                    if (
                        isinstance(record_id, str) and record_id
                        and isinstance(sphere_name, str) and sphere_name.strip()
                        and record_id not in names
                    ):
                        names[record_id] = sphere_name.strip()
        return names

    @staticmethod
    def _character_dao(snapshot: Any) -> dict[str, Any] | None:
        """The character's Dao from the Spheres it knows and the Talents learned in each."""

        block = (snapshot or {}).get("spheres_and_talents") if isinstance(snapshot, dict) else None
        if not isinstance(block, dict):
            return None
        sphere_ids = [value for value in block.get("sphere_record_ids") or [] if isinstance(value, str)]
        if not sphere_ids:
            return None
        talent_ids = {value for value in block.get("learned_talent_record_ids") or [] if isinstance(value, str)}
        if isinstance(block.get("background_talent_record_id"), str):
            talent_ids.add(block["background_talent_record_id"])
        try:
            from canonical_catalog.service import talent_sphere_ids
            from factory_authoring.sphere_dao import character_dao

            owners = talent_sphere_ids()
            counts = {sphere_id: 0 for sphere_id in sphere_ids}
            for talent_id in talent_ids:
                owner = owners.get(talent_id)
                if owner in counts:
                    counts[owner] += 1
            return character_dao(counts)
        except (FoundryError, OSError, ValueError, KeyError):
            return None

    def _talent_sphere_names(self, talent_record_ids: Any) -> dict[str, str]:
        """Sphere name per selected talent record id, for display grouping only."""

        wanted = {
            str(record_id)
            for record_id in (talent_record_ids or [])
            if isinstance(record_id, str) and record_id
        }
        if not wanted:
            return {}
        root = self._authenticated_factory_root()
        pairs: list[tuple[str, str]] = []
        try:
            manifest = json.loads(
                (Path(__file__).resolve().parents[1] / "catalog" / "sphere_talent_authority_v1.json").read_text(encoding="utf-8")
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            manifest = {}
        if root is not None and isinstance(manifest.get("catalog_path"), str) and isinstance(manifest.get("catalog_sha256"), str):
            catalog = Path(manifest["catalog_path"])
            if not catalog.is_absolute():
                catalog = root / catalog
            pairs.append((str(catalog), manifest["catalog_sha256"]))
        authority = Path(__file__).resolve().parents[1] / "catalog" / "sphere_talent_authority_v1.json"
        if authority.is_file():
            pairs.append((str(authority), sha256_file(authority)))
        names: dict[str, str] = {}
        try:
            if pairs:
                names.update(self._talent_sphere_name_sources(tuple(pairs)))
        except (OSError, TypeError, ValueError):
            pass
        # The canonical Talent matrix also names the Sphere of dotted ids
        # (tianxia.talent.sabers.*), which the catalogs above do not carry.
        try:
            from canonical_catalog.service import talent_sphere_display_names

            canonical = talent_sphere_display_names()
        except (OSError, TypeError, ValueError):
            canonical = {}
        return {
            record_id: names.get(record_id) or canonical[record_id]
            for record_id in sorted(wanted)
            if record_id in names or record_id in canonical
        }

    def _with_foundation_method_text(self, snapshot: Any) -> Any:
        """Attach the printed Foundation chapter and Method entry for display.

        The sealed records carry only what the Factory executes (a Foundation's
        resource, a Method's resource modifier); the owner also needs the
        published rules: the Foundation's Features, stages, risks and
        counterplay, and the Method's AP, breakthrough and Foundation behaviour.
        Returns a new top-level dict; the input snapshot is never modified.
        """

        if not isinstance(snapshot, dict):
            return snapshot
        result = snapshot
        foundation = snapshot.get("foundation")
        if isinstance(foundation, dict) and "printed_chapter" not in foundation:
            chapter = _foundation_printed_chapter(foundation)
            if chapter:
                result = {**result, "foundation": {**foundation, "printed_chapter": chapter}}
        method = snapshot.get("method")
        if isinstance(method, dict) and "printed_entry" not in method:
            entry = method_printed_entry(method)
            if entry:
                result = {**result, "method": {**method, "printed_entry": entry}}
        return result

    def _with_authenticated_rules_text(self, snapshot: Any) -> Any:
        """Return a deep-copied snapshot whose rule-text cards carry real rules.

        The sealed and cached owner snapshot keeps the display contract's text.
        This overlay adds the printed rules paragraph and applies owner edits
        to current-rule cards, including complete cards and path features.
        It changes display text only, never hashes, ids or sealed artifacts.
        """

        edits_path = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/owner_text_edits.json"
        edits = (json.loads(edits_path.read_text(encoding="utf-8")).get("records") or {}) if edits_path.is_file() else {}
        from factory_authoring.owner_text_edits import apply_edit
        state: dict[str, Any] = {"root": None, "resolved": False}

        def factory_root() -> Path | None:
            if not state["resolved"]:
                state["root"] = self._authenticated_factory_root()
                state["resolved"] = True
            return state["root"]

        return overlay_owner_current_rules(
            snapshot, edits=edits, apply_owner_edit=apply_edit, authenticated_rules_block=self._authenticated_rules_block,
            factory_root=factory_root,
        )

    @staticmethod
    def _card_groups(cards: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for card in cards:
            groups.setdefault(str(card.get("section") or "other"), []).append(card)
        return {key: groups[key] for key in sorted(groups)}

    @staticmethod
    def _enrich_selected_record_display(
        value: Any,
        cards_by_id: dict[str, dict[str, Any]],
        *,
        surface: str,
    ) -> dict[str, Any]:
        """Attach sealed display details to an already selected record.

        Method and Foundation rows in the advancement ledger intentionally
        carry only acquisition identity.  Their display descriptions are
        selected from the same sealed record cards used by the sheet contract.
        The record hash, name, and source locator are checked before any
        display-only fields are attached; the row's mechanical projection
        remains unchanged.
        """

        if value is None:
            return {}
        if not isinstance(value, dict):
            raise FoundryError(
                "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID",
                f"The selected {surface} projection is not an object.",
            )
        result = deepcopy(value)
        acquired = (
            has_acquired_foundation(result)
            if surface.casefold() == "foundation"
            else result.get("state") == "acquired" and bool(result.get("record_id"))
        )
        if not acquired:
            return result
        record_id = str(result["record_id"])
        card = cards_by_id.get(record_id)
        if not isinstance(card, dict):
            raise FoundryError(
                "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID",
                f"The selected {surface} has no authenticated display card.",
                details={"surface": surface, "record_id": record_id},
            )
        card_hash = card.get("record_hash")
        if not isinstance(card_hash, str) or not card_hash:
            raise FoundryError(
                "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID",
                f"The selected {surface} display card lacks a record hash.",
                details={"surface": surface, "record_id": record_id},
            )
        if result.get("record_hash") not in (None, card_hash):
            raise FoundryError(
                "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID",
                f"The selected {surface} record hash differs from its sealed display card.",
                details={"surface": surface, "record_id": record_id},
            )
        card_name = card.get("display_name")
        if not isinstance(card_name, str) or not card_name.strip():
            raise FoundryError(
                "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID",
                f"The selected {surface} display card lacks a name.",
                details={"surface": surface, "record_id": record_id},
            )
        if result.get("display_name") not in (None, card_name):
            raise FoundryError(
                "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID",
                f"The selected {surface} name differs from its sealed display card.",
                details={"surface": surface, "record_id": record_id},
            )
        source = card.get("source")
        if not isinstance(source, dict) or not all(
            isinstance(source.get(key), str) and source.get(key).strip()
            for key in ("path", "anchor", "sha256")
        ):
            raise FoundryError(
                "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID",
                f"The selected {surface} display card lacks exact source identity.",
                details={"surface": surface, "record_id": record_id},
            )
        existing_source = result.get("source")
        if existing_source is not None:
            if not isinstance(existing_source, dict) or any(
                existing_source.get(key) not in (None, source[key])
                for key in ("path", "anchor", "sha256")
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_SELECTED_RECORD_DISPLAY_INVALID",
                    f"The selected {surface} source identity differs from its sealed display card.",
                    details={"surface": surface, "record_id": record_id},
                )
        result.update({
            "record_hash": card_hash,
            "display_name": card_name,
            "full_description": card.get("full_description"),
            "full_description_source": card.get("full_description_source"),
            "source": deepcopy(source),
            "source_path": source["path"],
            "source_anchor": source["anchor"],
            "source_hash": source["sha256"],
            "display_only_not_execution_authority": True,
        })
        if not result.get("source_packet_ids") and card.get("source_packet_ids"):
            result["source_packet_ids"] = deepcopy(card["source_packet_ids"])
        return result

    @staticmethod
    def _levels_with_earned_feature_occurrences(
        levels: Any,
        occurrences: list[dict[str, Any]],
    ) -> list[Any]:
        """Join automatic Path occurrences to their actual level event.

        Subpath rows are deliberately excluded: a late Subpath acquisition is
        shown in the occurrence collection at its real acquisition event and
        must not be backdated onto an older printed threshold in Leveling.
        """

        by_acquisition_event: dict[str, list[dict[str, Any]]] = {}
        for occurrence in occurrences:
            if not isinstance(occurrence, dict) or occurrence.get("parent_kind") != "path":
                continue
            event = occurrence.get("acquisition_event")
            event_id = occurrence.get("acquisition_event_id")
            if (
                not isinstance(event, dict)
                or event.get("kind") != "level_advance"
                or not isinstance(event_id, str)
                or event.get("event_id") != event_id
            ):
                continue
            by_acquisition_event.setdefault(event_id, []).append(deepcopy(occurrence))

        if not isinstance(levels, list):
            return []
        enriched: list[Any] = []
        for level in levels:
            if not isinstance(level, dict):
                enriched.append(deepcopy(level))
                continue
            row = deepcopy(level)
            event_id = row.get("event_id")
            row["earned_feature_occurrences"] = deepcopy(
                by_acquisition_event.get(event_id, []) if isinstance(event_id, str) else []
            )
            enriched.append(row)
        return enriched

    @staticmethod
    def _validate_earned_feature_occurrences(
        contract: dict[str, Any],
        ledger: dict[str, Any],
        packets: dict[str, Any],
        provenance: dict[str, Any],
        path_rows: list[Any],
        subpath_rows: list[Any],
        factory_root: Path | None = None,
    ) -> list[dict[str, Any]]:
        """Validate the sealed, display-only Path/Subpath occurrence index.

        Progression children are not independent selected records.  Their
        display rows therefore carry a derived identity, while their parent
        record/hash and causal events must still resolve to the selected,
        sealed Path or Subpath contract.  This check deliberately validates
        the fields consumed by the complete-sheet filter instead of allowing
        an arbitrary metadata mapping to become presentation authority.
        """

        contract_rows = contract.get("earned_feature_occurrences")
        ledger_rows = ledger.get("earned_feature_occurrences")
        contract_rows = [] if contract_rows is None else contract_rows
        ledger_rows = [] if ledger_rows is None else ledger_rows
        if not isinstance(contract_rows, list) or not isinstance(ledger_rows, list) or contract_rows != ledger_rows:
            raise FoundryError(
                "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                "The sealed display contract and advancement ledger disagree about earned feature occurrences.",
            )
        if not contract_rows:
            return []
        selected_paths = {
            row.get("path_id")
            for row in path_rows
            if isinstance(row, dict) and isinstance(row.get("path_id"), str) and row.get("path_id")
        }
        selected_subpaths = {
            row.get("subpath_id")
            for row in subpath_rows
            if isinstance(row, dict) and isinstance(row.get("subpath_id"), str) and row.get("subpath_id")
        }
        rules_by_id = {
            row.get("record_id"): row
            for row in contract.get("rules") or []
            if isinstance(row, dict) and isinstance(row.get("record_id"), str)
        }
        packet_rows = [
            row for row in packets.get("packets") or []
            if isinstance(row, dict)
        ]
        packet_by_id = {
            row.get("packet_id"): row
            for row in packet_rows
            if isinstance(row.get("packet_id"), str)
        }
        if len(packet_by_id) != len(packet_rows):
            raise FoundryError(
                "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                "The sealed selection packet history contains a missing or duplicate packet identity.",
            )
        packet_by_event = {
            row.get("event_id"): row
            for row in packet_by_id.values()
            if isinstance(row.get("event_id"), str)
        }
        if len(packet_by_event) != len(packet_rows):
            raise FoundryError(
                "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                "The sealed selection packet history contains a missing or duplicate event identity.",
            )
        packet_sequences = [row.get("sequence") for row in packet_rows]
        if (
            any(type(sequence) is not int or sequence < 1 for sequence in packet_sequences)
            or sorted(packet_sequences) != list(range(1, len(packet_rows) + 1))
        ):
            raise FoundryError(
                "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                "The sealed selection packet history is not a gap-free event sequence.",
            )
        last_packet = max(packet_rows, key=lambda row: row["sequence"]) if packet_rows else {}
        last_packet_hash = last_packet.get("event_hash")
        advancement = ledger.get("advancement") or {}
        history_event_ids = provenance.get("event_ids")
        if (
            not isinstance(history_event_ids, list)
            or any(not isinstance(event_id, str) or not event_id for event_id in history_event_ids)
            or len(history_event_ids) != len(set(history_event_ids))
            or set(history_event_ids) != set(packet_by_event)
            or type(advancement.get("event_count")) is not int
            or advancement.get("event_count") != len(history_event_ids)
            or advancement.get("event_head_hash") != last_packet_hash
            or provenance.get("event_head_hash") != advancement.get("event_head_hash")
        ):
            raise FoundryError(
                "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                "The earned feature display is not bound to the complete sealed event history.",
                details={
                    "history_event_count": len(history_event_ids) if isinstance(history_event_ids, list) else None,
                    "packet_event_count": len(packet_by_event),
                    "ledger_event_count": advancement.get("event_count"),
                },
            )
        level_rows = [
            row for row in advancement.get("levels") or []
            if isinstance(row, dict)
        ]
        level_by_event = {
            row.get("event_id"): row
            for row in level_rows
            if isinstance(row.get("event_id"), str)
        }
        if len(level_by_event) != len(level_rows):
            raise FoundryError(
                "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                "The sealed level history contains a missing or duplicate event identity.",
            )
        provenance_event_rows = [
            row for row in (provenance.get("mappings") or {}).values()
            if isinstance(row, dict)
            and row.get("provenance_unit") in {"canonical_advancement_event", "canonical_non_sphere_authority_event"}
            and isinstance(row.get("event_id"), str)
        ]
        provenance_events = {
            row["event_id"]: row
            for row in provenance_event_rows
        }
        if (
            len(provenance_event_rows) != len(provenance_events)
            or set(provenance_events) != set(history_event_ids)
        ):
            raise FoundryError(
                "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                "The earned feature display is not bound to every event provenance mapping.",
                details={
                    "missing_event_ids": sorted(set(history_event_ids) - set(provenance_events)),
                    "extra_event_ids": sorted(set(provenance_events) - set(history_event_ids)),
                },
            )
        current_cl = (ledger.get("character") or {}).get("cl")
        level_event_sequences = sorted(
            packet["sequence"]
            for packet in packet_rows
            if packet.get("advancement_kind") == "level_advance"
        )
        seen_ids: set[str] = set()
        seen_choice_event_ids: set[str] = set()
        for occurrence in contract_rows:
            if not isinstance(occurrence, dict):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence is not an object.",
                )
            occurrence_id = occurrence.get("occurrence_id")
            if not isinstance(occurrence_id, str) or not occurrence_id or occurrence_id in seen_ids:
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "Earned feature occurrences require unique stable identities.",
                    details={"occurrence_id": occurrence_id},
                )
            seen_ids.add(occurrence_id)
            feature_id = occurrence.get("feature_id")
            parent_kind = occurrence.get("parent_kind")
            parent_id = occurrence.get("parent_record_id")
            parent_hash = occurrence.get("parent_record_hash")
            owning_path_id = occurrence.get("owning_path_id")
            if (
                not isinstance(feature_id, str)
                or not feature_id
                or parent_kind not in {"path", "subpath"}
                or not isinstance(parent_id, str)
                or not parent_id
                or not isinstance(parent_hash, str)
                or len(parent_hash) != 64
                or not isinstance(owning_path_id, str)
                or owning_path_id not in selected_paths
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence lacks a selected authenticated parent or owning Path.",
                    details={"occurrence_id": occurrence_id, "parent_record_id": parent_id},
                )
            if parent_kind == "path" and parent_id not in selected_paths:
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned Path feature occurrence names an unselected Path.",
                    details={"occurrence_id": occurrence_id, "parent_record_id": parent_id},
                )
            if parent_kind == "subpath" and parent_id not in selected_subpaths:
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned Subpath feature occurrence names an unselected Subpath.",
                    details={"occurrence_id": occurrence_id, "parent_record_id": parent_id},
                )
            if (
                (parent_kind == "path" and owning_path_id != parent_id)
                or (parent_kind == "path" and any(
                    occurrence.get(key) is not None
                    for key in ("parent_subpath_id", "parent_subpath_record_id")
                ))
                or (parent_kind == "subpath" and (
                    occurrence.get("parent_subpath_id") != parent_id
                    or occurrence.get("parent_subpath_record_id") != parent_id
                ))
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence contains inconsistent parent aliases.",
                    details={"occurrence_id": occurrence_id, "parent_record_id": parent_id},
                )
            selected_subpath = next(
                (
                    row for row in subpath_rows
                    if isinstance(row, dict) and row.get("subpath_id") == parent_id
                ),
                None,
            )
            if parent_kind == "subpath" and (
                not isinstance(selected_subpath, dict)
                or selected_subpath.get("owning_path_id") != owning_path_id
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned Subpath feature occurrence is not bound to its selected owning Path.",
                    details={"occurrence_id": occurrence_id, "parent_record_id": parent_id},
                )
            parent_rule = rules_by_id.get(parent_id)
            if (
                not isinstance(parent_rule, dict)
                or parent_rule.get("record_hash") != parent_hash
                or not parent_rule.get("source")
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence is not bound to the selected parent's sealed display rule.",
                    details={"occurrence_id": occurrence_id, "parent_record_id": parent_id},
                )
            required_level = occurrence.get("required_path_level")
            acquired_level = occurrence.get("acquired_at_path_level")
            acquired_cl = occurrence.get("acquired_at_character_cl")
            if (
                type(required_level) is not int
                or required_level < 1
                or type(acquired_level) is not int
                or acquired_level < required_level
                or type(acquired_cl) is not int
                or acquired_cl < 0
                or (type(current_cl) is int and acquired_cl > current_cl)
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence has an impossible printed threshold or causal level.",
                    details={"occurrence_id": occurrence_id, "required_path_level": required_level, "acquired_at_path_level": acquired_level, "acquired_at_character_cl": acquired_cl},
                )
            if not isinstance(occurrence.get("display_name"), str) or not occurrence["display_name"].strip():
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence lacks a display name.",
                    details={"occurrence_id": occurrence_id},
                )
            acquisition = occurrence.get("acquisition_event")
            attainment = occurrence.get("attainment_event")
            required_event_fields = ("event_id", "event_hash", "sequence", "kind", "target_cl", "packet_id")
            resolved_event_refs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
            for role, event in (("acquisition", acquisition), ("attainment", attainment)):
                if (
                    not isinstance(event, dict)
                    or any(not event.get(field) for field in required_event_fields)
                    or not isinstance(event.get("event_hash"), str)
                    or len(event["event_hash"]) != 64
                    or type(event.get("sequence")) is not int
                    or event["sequence"] < 1
                    or type(event.get("target_cl")) is not int
                    or event["target_cl"] < 0
                ):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature occurrence lacks a complete causal event identity.",
                        details={"occurrence_id": occurrence_id, "event_role": role},
                    )
                packet = packet_by_id.get(event["packet_id"])
                if (
                    not isinstance(packet, dict)
                    or packet.get("event_id") != event["event_id"]
                    or packet.get("event_hash") != event["event_hash"]
                    or packet.get("sequence") != event["sequence"]
                    or packet.get("target_cl") != event["target_cl"]
                    or packet.get("advancement_kind") != event["kind"]
                ):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature occurrence is not bound to its sealed selection packet.",
                        details={"occurrence_id": occurrence_id, "event_role": role},
                    )
                if event["event_id"] not in history_event_ids:
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature occurrence names an event outside the sealed event history.",
                        details={"occurrence_id": occurrence_id, "event_role": role, "event_id": event["event_id"]},
                    )
                provenance_event = provenance_events.get(event["event_id"])
                if (
                    not isinstance(provenance_event, dict)
                    or provenance_event.get("event_hash") != event["event_hash"]
                    or provenance_event.get("event_sequence") != event["sequence"]
                    or provenance_event.get("record_id") != packet.get("record_id")
                    or provenance_event.get("record_hash") != packet.get("record_hash")
                ):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature occurrence is not bound to its sealed event provenance.",
                        details={"occurrence_id": occurrence_id, "event_role": role, "event_id": event["event_id"]},
                    )
                resolved_event_refs[role] = (event, packet)
            source_packet_ids = occurrence.get("source_packet_ids")
            if (
                not isinstance(source_packet_ids, list)
                or not source_packet_ids
                or any(not isinstance(packet_id, str) or not packet_id for packet_id in source_packet_ids)
                or len(source_packet_ids) != len(set(source_packet_ids))
                or acquisition["packet_id"] not in source_packet_ids
                or attainment["packet_id"] not in source_packet_ids
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence lacks complete source packet provenance.",
                    details={"occurrence_id": occurrence_id},
                )
            if parent_kind == "path":
                if (
                    acquisition["kind"] != "level_advance"
                    or attainment["kind"] != "level_advance"
                    or acquisition["event_id"] != attainment["event_id"]
                    or acquisition["event_hash"] != attainment["event_hash"]
                ):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An automatic Path feature occurrence is not bound to one authenticated level grant.",
                        details={"occurrence_id": occurrence_id},
                    )
            elif parent_kind == "subpath":
                # A feature whose threshold was already reached before the
                # Subpath was selected is sourced from the later parent
                # acquisition, while a feature reached after selection is
                # sourced from its later level grant.  Both shapes retain the
                # parent packet and the actual chronological level event.
                parent_packets = [
                    packet_by_id[packet_id]
                    for packet_id in source_packet_ids
                    if packet_id in packet_by_id
                    and packet_by_id[packet_id].get("record_id") == parent_id
                    and packet_by_id[packet_id].get("advancement_kind") == "subpath_acquisition"
                ]
                if not parent_packets:
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "A Subpath feature occurrence lacks its selected-parent acquisition packet.",
                        details={"occurrence_id": occurrence_id, "parent_record_id": parent_id},
                    )
                parent_packet = min(parent_packets, key=lambda packet: packet["sequence"])
                parent_sequence = parent_packet["sequence"]
                parent_target_cl = parent_packet["target_cl"]
                parent_grant = (
                    acquisition["kind"] == "subpath_acquisition"
                    and attainment["kind"] == "level_advance"
                    and acquisition["event_id"] != attainment["event_id"]
                    and acquisition["event_hash"] != attainment["event_hash"]
                    and acquisition["sequence"] == parent_sequence
                    and acquisition["target_cl"] == parent_target_cl
                    and acquisition["packet_id"] == parent_packet["packet_id"]
                    and resolved_event_refs["acquisition"][1].get("record_id") == parent_id
                    and attainment["sequence"] < acquisition["sequence"]
                )
                later_level_grant = (
                    acquisition["kind"] == "level_advance"
                    and attainment["kind"] == "level_advance"
                    and acquisition["event_id"] == attainment["event_id"]
                    and acquisition["event_hash"] == attainment["event_hash"]
                    and acquisition["sequence"] == attainment["sequence"]
                    and acquisition["sequence"] > parent_sequence
                    and acquisition["target_cl"] >= parent_target_cl
                )
                if not (parent_grant or later_level_grant):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "A Subpath feature occurrence is not bound to its authenticated parent and chronological level grant.",
                        details={"occurrence_id": occurrence_id, "parent_record_id": parent_id},
                    )
            for role in ("acquisition", "attainment"):
                event, packet = resolved_event_refs[role]
                if event["kind"] == "level_advance":
                    level_row = level_by_event.get(event["event_id"])
                    if (
                        not isinstance(level_row, dict)
                        or level_row.get("event_id") != event["event_id"]
                        or level_row.get("cl") != event["target_cl"]
                        or level_row.get("feature_record_id") != packet.get("record_id")
                    ):
                        raise FoundryError(
                            "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                            "An earned feature occurrence level grant is absent from the sealed advancement history.",
                            details={"occurrence_id": occurrence_id, "event_role": role, "event_id": event["event_id"]},
                        )
            if (
                occurrence.get("acquired_at_character_cl") != acquisition.get("target_cl")
                or occurrence.get("acquisition_event_id") != acquisition.get("event_id")
                or occurrence.get("acquisition_event_hash") != acquisition.get("event_hash")
                or occurrence.get("attainment_event_id") != attainment.get("event_id")
                or occurrence.get("attainment_event_hash") != attainment.get("event_hash")
                or occurrence.get("event_id") != acquisition.get("event_id")
                or occurrence.get("event_hash") != acquisition.get("event_hash")
                or occurrence.get("event_sequence") != acquisition.get("sequence")
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence has inconsistent event aliases.",
                    details={"occurrence_id": occurrence_id},
                )
            selection = occurrence.get("selection")
            if selection is not None:
                if not isinstance(selection, dict) or not isinstance(selection.get("event"), dict):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature occurrence contains an incomplete authenticated choice selection.",
                        details={"occurrence_id": occurrence_id},
                    )
                choice_event = selection["event"]
                if any(not choice_event.get(field) for field in required_event_fields):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature choice selection lacks a complete event identity.",
                        details={"occurrence_id": occurrence_id},
                    )
                choice_packet = packet_by_id.get(choice_event.get("packet_id"))
                choice_provenance = provenance_events.get(choice_event.get("event_id"))
                if (
                    choice_event.get("event_id") not in history_event_ids
                    or not isinstance(choice_packet, dict)
                    or choice_packet.get("event_id") != choice_event.get("event_id")
                    or choice_packet.get("event_hash") != choice_event.get("event_hash")
                    or choice_packet.get("sequence") != choice_event.get("sequence")
                    or choice_packet.get("target_cl") != choice_event.get("target_cl")
                    or choice_packet.get("advancement_kind") != choice_event.get("kind")
                    or not isinstance(choice_provenance, dict)
                    or choice_provenance.get("event_hash") != choice_event.get("event_hash")
                    or choice_provenance.get("event_sequence") != choice_event.get("sequence")
                    or choice_provenance.get("record_id") != choice_packet.get("record_id")
                    or choice_provenance.get("record_hash") != choice_packet.get("record_hash")
                    or selection.get("choice_kind") != choice_event.get("kind")
                ):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature choice selection is not bound to its sealed event history.",
                        details={"occurrence_id": occurrence_id, "event_id": choice_event.get("event_id")},
                    )
                if choice_event["packet_id"] not in source_packet_ids:
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature choice selection is missing its source packet provenance.",
                        details={"occurrence_id": occurrence_id, "packet_id": choice_event["packet_id"]},
                    )
                next_level_sequence = next(
                    (sequence for sequence in level_event_sequences if sequence > acquisition["sequence"]),
                    None,
                )
                if (
                    choice_event["sequence"] <= acquisition["sequence"]
                    or (next_level_sequence is not None and choice_event["sequence"] >= next_level_sequence)
                    or choice_event["target_cl"] != acquisition["target_cl"]
                    or choice_event["event_id"] in seen_choice_event_ids
                ):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature choice selection is outside its grant interval or is reused.",
                        details={
                            "occurrence_id": occurrence_id,
                            "choice_event_id": choice_event.get("event_id"),
                            "grant_sequence": acquisition.get("sequence"),
                            "next_level_sequence": next_level_sequence,
                        },
                    )
                seen_choice_event_ids.add(choice_event["event_id"])
            source = occurrence.get("source")
            source_text = occurrence.get("source_text")
            full_description = occurrence.get("full_description")
            if (
                not isinstance(source, dict)
                or not all(isinstance(source.get(key), str) and source.get(key).strip() for key in ("path", "anchor", "source_hash"))
                or not isinstance(source_text, str)
                or not source_text.strip()
                or not isinstance(full_description, str)
                or not full_description.strip()
                or source_text != full_description
                or not isinstance(occurrence.get("source_hash"), str)
                or not occurrence["source_hash"].strip()
                or not isinstance(occurrence.get("source_file_sha256"), str)
                or len(occurrence["source_file_sha256"]) != 64
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence lacks complete source-backed text and hashes.",
                    details={"occurrence_id": occurrence_id},
                )
            expected_source_aliases = {
                "factory_source_path": source.get("factory_source_path") or source.get("path"),
                "anchor": source.get("anchor"),
                "source_hash": source.get("source_hash"),
                "source_file_sha256": source.get("source_file_sha256") or source.get("source_hash"),
            }
            if any(occurrence.get(key) != value for key, value in expected_source_aliases.items()):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence contains source aliases different from its locked binding.",
                    details={"occurrence_id": occurrence_id},
                )
            for key in ("line_start", "line_end", "section_sha256"):
                if key in source and occurrence.get(key) != source.get(key):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned feature occurrence contains source locator fields different from its locked binding.",
                        details={"occurrence_id": occurrence_id, "field": key},
                    )
            feature_rule = rules_by_id.get(feature_id)
            if parent_kind == "path":
                if (
                    not isinstance(feature_rule, dict)
                    or occurrence.get("feature_record_hash") != feature_rule.get("record_hash")
                    or occurrence.get("source") != feature_rule.get("source")
                    or occurrence.get("full_description") != feature_rule.get("full_description")
                    or "derived_feature_snapshot" in occurrence
                ):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "An earned Path feature occurrence differs from its selected sealed feature rule.",
                        details={"occurrence_id": occurrence_id, "feature_id": feature_id},
                    )
            else:
                feature_snapshot = occurrence.get("derived_feature_snapshot")
                snapshot_source = feature_snapshot.get("source") if isinstance(feature_snapshot, dict) else None
                snapshot_threshold = feature_snapshot.get("granted_at_cl") if isinstance(feature_snapshot, dict) else None
                if isinstance(snapshot_threshold, list):
                    threshold_values = [
                        value for value in snapshot_threshold
                        if type(value) is int and value > 0
                    ]
                    snapshot_threshold = min(threshold_values) if threshold_values else None
                if (
                    not isinstance(feature_snapshot, dict)
                    or feature_snapshot.get("canonical_id") != feature_id
                    or feature_snapshot.get("display_name") != occurrence.get("display_name")
                    or snapshot_threshold != required_level
                    or feature_snapshot.get("components") != occurrence.get("components")
                    or feature_snapshot.get("minimum_realm_band") != occurrence.get("minimum_realm_band")
                    or feature_snapshot.get("source_cl_basis") != occurrence.get("source_cl_basis")
                    or not isinstance(snapshot_source, dict)
                    or any(
                        snapshot_source.get(key) != source.get(key)
                        for key in ("factory_source_path", "source_file_sha256", "line_start", "line_end", "section_sha256")
                    )
                ):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "A derived Subpath feature occurrence differs from its authenticated progression snapshot.",
                        details={"occurrence_id": occurrence_id, "feature_id": feature_id},
                    )
                expected_feature_hash = sha256_json({
                    "parent_record_id": parent_id,
                    "parent_record_hash": parent_hash,
                    "feature": feature_snapshot,
                })
                if occurrence.get("feature_record_hash") != expected_feature_hash:
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "A derived Subpath feature occurrence has an invalid parent/feature commitment.",
                        details={"occurrence_id": occurrence_id, "feature_id": feature_id},
                    )
                source_locator = (
                    source.get("factory_source_path"),
                    source.get("source_file_sha256"),
                    source.get("line_start"),
                    source.get("line_end"),
                    source.get("section_sha256"),
                )
                if factory_root is None or not all(source_locator):
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "A derived Subpath feature occurrence lacks an installed source verification context.",
                        details={"occurrence_id": occurrence_id, "feature_id": feature_id},
                    )
                try:
                    from character_creation.constructed_arts.sources import published_section

                    installed_text = published_section(factory_root, source)
                except (FoundryError, OSError, TypeError, ValueError) as exc:
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "A derived Subpath feature occurrence could not be verified against the installed source section.",
                        details={"occurrence_id": occurrence_id, "feature_id": feature_id, "cause": getattr(exc, "code", type(exc).__name__)},
                    ) from exc
                if installed_text != source_text:
                    raise FoundryError(
                        "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                        "A derived Subpath feature occurrence contains source text different from its authenticated section.",
                        details={"occurrence_id": occurrence_id, "feature_id": feature_id},
                    )
            expected_derived_hash = sha256_json({
                "parent_record_id": parent_id,
                "parent_record_hash": parent_hash,
                "feature_id": feature_id,
                "feature_record_hash": occurrence.get("feature_record_hash"),
            })
            if (
                occurrence.get("source_backed") is not True
                or occurrence.get("mechanically_stacks") is not False
                or occurrence.get("mechanical_identity") != feature_id
                or not isinstance(occurrence.get("feature_record_hash"), str)
                or len(occurrence["feature_record_hash"]) != 64
                or not isinstance(occurrence.get("derived_feature_hash"), str)
                or len(occurrence["derived_feature_hash"]) != 64
                or occurrence.get("derived_feature_hash") != expected_derived_hash
            ):
                raise FoundryError(
                    "CHARACTER_SHEET_EARNED_FEATURE_OCCURRENCES_INVALID",
                    "An earned feature occurrence lacks its sealed display identity or non-stacking marker.",
                    details={"occurrence_id": occurrence_id},
                )
        return deepcopy(contract_rows)

    @staticmethod
    def _validate_snapshot(snapshot: dict[str, Any], required_record_ids: set[str], profile: dict[str, Any]) -> None:
        diagnostics: list[dict[str, Any]] = []
        readiness = snapshot.get("readiness") or {}
        expected = profile.get("stage_semantics") or {}
        for key, value in expected.items():
            if readiness.get(key) != value:
                diagnostics.append({"code": "CHARACTER_SHEET_READINESS_MISMATCH", "field": key, "expected": value, "actual": readiness.get(key)})
        section_rows = snapshot.get("selected_record_sections") or {}
        cards = [card for section in section_rows.values() for card in (section or [])]
        ids = [card.get("record_id") for card in cards if isinstance(card, dict)]
        if len(ids) != len(set(ids)):
            diagnostics.append({"code": "CHARACTER_SHEET_DUPLICATE_RECORD_PRESENTATION"})
        if set(ids) != required_record_ids:
            diagnostics.append({
                "code": "CHARACTER_SHEET_RECORD_COVERAGE_MISMATCH",
                "missing": sorted(required_record_ids - set(ids)),
                "extra": sorted(set(ids) - required_record_ids),
            })
        for card in cards:
            if not isinstance(card, dict):
                diagnostics.append({"code": "CHARACTER_SHEET_RECORD_CARD_INVALID"})
                continue
            source = card.get("source") or {}
            if not source.get("path") or not source.get("anchor") or not source.get("sha256"):
                diagnostics.append({"code": "CHARACTER_SHEET_DESCRIPTION_UNPROVEN", "record_id": card.get("record_id")})
            capabilities = card.get("capabilities") or {}
            if capabilities.get("combat_execution") not in {"SUPPORTED", "NOT_APPLICABLE"} and not card.get("display_only_not_execution_authority"):
                diagnostics.append({"code": "CHARACTER_SHEET_FALSE_EXECUTION_CLAIM", "record_id": card.get("record_id")})
        typed_none = snapshot.get("explicit_none_systems") or {}
        selected_method = snapshot.get("method") or {}
        method_acquired = has_acquired_method(selected_method)
        selected_foundation = snapshot.get("foundation") or {}
        foundation_acquired = has_acquired_foundation(selected_foundation)
        forged_known = isinstance(snapshot.get("forged_techniques"), list) and bool(snapshot.get("forged_techniques"))
        manuals_present = bool(snapshot.get("training_sources")) or (
            isinstance(snapshot.get("recorded_arts"), list) and bool(snapshot.get("recorded_arts"))
        )
        immortal_known = isinstance(snapshot.get("immortal_arts"), list) and bool(snapshot.get("immortal_arts"))
        target_cl = (snapshot.get("identity") or {}).get("cultivation_level")
        required_none_systems = ["method", "foundation", "manuals", "equipment", "forged_techniques"]
        if type(target_cl) is int and target_cl >= 15:
            required_none_systems.append("immortal_arts")
        for name in required_none_systems:
            if name == "method" and method_acquired:
                continue
            if name == "foundation" and foundation_acquired:
                continue
            if name == "forged_techniques" and forged_known:
                continue
            if name == "immortal_arts" and immortal_known:
                continue
            if name == "manuals" and manuals_present:
                continue
            if name == "equipment" and isinstance(snapshot.get("equipment"), list) and snapshot["equipment"]:
                continue
            row = typed_none.get(name) or {}
            if row.get("state") != "none" or row.get("source_backed") is not True:
                diagnostics.append({"code": "CHARACTER_SHEET_TYPED_NONE_INVALID", "system": name})
        if snapshot.get("later_stage_status", {}).get("gm_screen", {}).get("status") != "NOT_ATTEMPTED":
            diagnostics.append({"code": "CHARACTER_SHEET_FALSE_GM_READINESS"})
        if snapshot.get("later_stage_status", {}).get("combat", {}).get("status") != "NOT_ATTEMPTED":
            diagnostics.append({"code": "CHARACTER_SHEET_FALSE_COMBAT_READINESS"})
        serialized = canonical_json(snapshot)
        for token in _FORBIDDEN_DISPLAY_TOKENS:
            if token.casefold() in serialized.casefold():
                diagnostics.append({"code": "CHARACTER_SHEET_FORBIDDEN_PLACEHOLDER", "token": token})
        if diagnostics:
            raise FoundryError(
                "CHARACTER_SHEET_BUILD_BLOCKED",
                "The owner-facing Character Sheet failed its readiness contract.",
                details={"diagnostics": diagnostics},
            )

    def _snapshot_dir(self, project_id: str, sheet_id: str) -> Path:
        return self.db.settings.data_dir / "character_sheets" / project_id / sheet_id

    def _cached_snapshot(
        self,
        project_id: str,
        *,
        artifacts: dict[str, dict[str, Any]],
        project_revision: Any,
        projection_status: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        try:
            ledger = artifacts["Character_Master_Ledger.json"]
            provenance = artifacts["Projection_Provenance_Map.json"]
            _, current_contract_sha = self._display_contract(ledger, provenance)
            _, current_profile_sha = self._readiness_profile()
            if not isinstance(current_contract_sha, str) or not isinstance(current_profile_sha, str):
                return None
            artifact_hashes = {
                item["artifact_name"]: item["sha256"]
                for item in projection_status["artifacts"]
            }
            candidates = []
            for path in (self.db.settings.data_dir / "character_sheets" / project_id).glob(
                f"*/{_OWNER_SHEET_FILENAME}"
            ):
                try:
                    candidates.append((path.stat().st_mtime_ns, path))
                except OSError:
                    continue
            projection_id = projection_status["projection_id"]
        except (AttributeError, FoundryError, KeyError, OSError, TypeError, UnicodeError, ValueError):
            return None

        for _, path in sorted(candidates, key=lambda item: item[0], reverse=True):
            try:
                sidecar = path.with_suffix(path.suffix + ".sha256")
                if not sidecar.is_file():
                    continue
                digest, declared_name = sidecar.read_text(encoding="utf-8").strip().split("  ", 1)
                if (
                    len(digest) != 64
                    or any(character not in "0123456789abcdefABCDEF" for character in digest)
                    or declared_name != _OWNER_SHEET_FILENAME
                ):
                    continue
                actual = sha256_file(path)
                if digest.lower() != actual:
                    continue
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(snapshot, dict) or snapshot.get("sheet_id") != path.parent.name:
                    continue
                authority = snapshot.get("authority_and_artifact_identity")
                if not isinstance(authority, dict) or any(
                    key not in authority for key in ("project_id", "project_revision", "projection_id", "advancement_artifact_hashes")
                ):
                    continue
                if (
                    authority["project_id"] != project_id
                    or authority["project_revision"] != project_revision
                    or authority["projection_id"] != projection_id
                    or authority["advancement_artifact_hashes"] != artifact_hashes
                ):
                    continue
                display_contract = authority.get("display_contract")
                readiness_profile = authority.get("readiness_profile")
                if not isinstance(display_contract, dict) or not isinstance(readiness_profile, dict):
                    continue
                contract_sha = display_contract.get("sha256")
                profile_sha = readiness_profile.get("sha256")
                if (
                    not isinstance(contract_sha, str)
                    or not isinstance(profile_sha, str)
                    or contract_sha != current_contract_sha
                    or profile_sha != current_profile_sha
                ):
                    continue
                return snapshot, {
                    "sheet_id": snapshot["sheet_id"],
                    "path": str(path),
                    "sha256": actual,
                    "bytes": path.stat().st_size,
                    "display_contract_sha256": contract_sha,
                    "readiness_profile_sha256": profile_sha,
                }
            except (OSError, TypeError, UnicodeError, ValueError, json.JSONDecodeError):
                continue
        return None

    def _factory_workspace_status(self, project_id: str, *, include_candidate: bool = True) -> dict[str, Any]:
        pointer = self.db.settings.data_dir / "factory_workspaces" / project_id / "current.json"
        gm_receipt_pointer = self.db.settings.data_dir / "factory_gm_authoring" / project_id / "current.json"
        gm_receipt_present = gm_receipt_pointer.is_file()
        if not pointer.is_file():
            if gm_receipt_present:
                try:
                    from factory_authoring.service import FactoryAuthoringWorkspaceService
                    from security.integrity import IntegrityService

                    current_project = self.projects.get_project(project_id)["project"]
                    verifier = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
                    verifier.db = self.db
                    verifier.integrity = IntegrityService.for_database(self.db)
                    loaded = verifier._load_gm_authoring(
                        project_id,
                        project_revision=int(current_project["revision"]),
                    )
                    binding = loaded.get("binding") if isinstance(loaded, Mapping) else None
                    if not isinstance(binding, Mapping):
                        raise FoundryError("GM_AUTHORING_ARTIFACT_MISSING", "The server-owned GM receipt could not be loaded.")
                    return {
                        "status": "REBUILD_PENDING",
                        "workspace_id": None,
                        "workspace_sha256": None,
                        "gm_authoring": "ACTUAL_GM_AUTHORING",
                        "gm_authorship_status": "ACTUAL",
                        "gm_authoring_actual": True,
                        "gm_authoring_profile_classification": "ACTUAL_GM_AUTHORING",
                        "gm_receipt_id": binding.get("receipt_id"),
                        "gm_receipt_sha256": binding.get("receipt_sha256"),
                        "gm_artifact_sha256": binding.get("artifact_sha256"),
                        "gm_profile_sha256": binding.get("profile_sha256"),
                        "gm_source_snapshot_sha256": binding.get("source_snapshot_sha256"),
                        "gm_selected_record_content_sha256": binding.get("selected_record_content_sha256"),
                        "gm_owner_decision_id": binding.get("owner_decision_id"),
                        "gm_owner_ratified": binding.get("owner_ratified") is True,
                        "command5": "NOT_RUN",
                        "command6": "NOT_RUN",
                        "gm_screen_consumer_verification": "NOT_ATTEMPTED",
                        "gm_export_available": False,
                        "eligible_for_later_command5_checkpoint": binding.get("owner_ratified") is True,
                        "legacy_command5_eligible": False,
                        "provider_free_rebuild_available": True,
                    }
                except (FoundryError, OSError, ValueError, json.JSONDecodeError):
                    return {
                        "status": "STALE",
                        "gm_authoring": "STALE",
                        "command5": "NOT_RUN",
                        "command6": "NOT_RUN",
                        "gm_export_available": False,
                        "provider_free_rebuild_available": False,
                    }
            return {
                "status": "NOT_ATTEMPTED",
                "gm_authoring": "NOT_ATTEMPTED",
                "command5": "NOT_RUN",
                "command6": "NOT_RUN",
                "gm_export_available": False,
            }
        try:
            payload = json.loads(pointer.read_text(encoding="utf-8"))
            manifest_path = Path(str(payload.get("workspace_path") or "")) / "Workspace_Manifest.json"
            if not manifest_path.is_file() or sha256_file(manifest_path) != payload.get("manifest_sha256"):
                raise ValueError("stale workspace manifest")
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return {
                "status": "STALE",
                "gm_authoring": "STALE",
                "command5": "NOT_RUN",
                "command6": "NOT_RUN",
                "gm_export_available": False,
            }
        candidate_status = "NOT_RUN"
        candidate_details = None
        candidate_pointer = self.db.settings.data_dir / "factory_candidates" / project_id / "current.json"
        if include_candidate and candidate_pointer.is_file():
            try:
                candidate = json.loads(candidate_pointer.read_text(encoding="utf-8"))
                candidate_zip = Path(str(candidate.get("candidate_zip") or ""))
                model_path = Path(str(candidate.get("gm_model_path") or ""))
                if (
                    candidate.get("status") == "GM_MODEL_CANDIDATE_READY"
                    and candidate_zip.is_file()
                    and model_path.is_file()
                    and sha256_file(model_path) == candidate.get("gm_model_sha256")
                ):
                    candidate_archive = self._complete_character_archive(candidate_zip)
                    if candidate_archive.get("sha256") == candidate.get("candidate_sha256"):
                        candidate_status = "GM_MODEL_CANDIDATE_READY"
                        candidate_details = {
                            "build_profile": (candidate.get("build_profile") or {}).get("profile_id"),
                            "candidate_sha256": candidate.get("candidate_sha256"),
                            "gm_model_sha256": candidate.get("gm_model_sha256"),
                            "consumer_verification": "NOT_ATTEMPTED",
                        }
                    else:
                        candidate_status = "STALE"
                else:
                    candidate_status = "STALE"
            except (FoundryError, OSError, ValueError, json.JSONDecodeError):
                candidate_status = "STALE"
        manifest_profile = manifest_payload.get("gm_authoring_profile") if isinstance(manifest_payload, dict) else None
        manifest_classification = manifest_profile.get("classification") if isinstance(manifest_profile, dict) else None
        manifest_authorship = (
            manifest_payload.get("gm_authorship")
            if isinstance(manifest_payload, dict)
            else None
        ) or (manifest_profile.get("authorship") if isinstance(manifest_profile, dict) else None)
        verified_gm_binding = None
        gm_verification_attempted = False
        gm_workspace_bound = False
        if manifest_classification == "ACTUAL_GM_AUTHORING" or payload.get("gm_receipt_id") is not None or gm_receipt_present:
            try:
                from factory_authoring.service import FactoryAuthoringWorkspaceService
                from security.integrity import IntegrityService

                gm_verification_attempted = True
                current_project = self.projects.get_project(project_id)["project"]
                if manifest_payload.get("project_revision") != current_project.get("revision"):
                    if not gm_receipt_present:
                        raise FoundryError("GM_AUTHORING_ARTIFACT_STALE", "The workspace GM artifact belongs to an older project revision.")
                verifier = FactoryAuthoringWorkspaceService.__new__(FactoryAuthoringWorkspaceService)
                verifier.db = self.db
                verifier.integrity = IntegrityService.for_database(self.db)
                loaded = verifier._load_gm_authoring(
                    project_id,
                    project_revision=int(current_project["revision"]),
                )
                verified_gm_binding = loaded.get("binding") if isinstance(loaded, Mapping) else None
                manifest_binding = manifest_payload.get("gm_artifact_binding")
                binding_expected = manifest_classification == "ACTUAL_GM_AUTHORING" or payload.get("gm_receipt_id") is not None
                if not isinstance(verified_gm_binding, Mapping) or (binding_expected and not isinstance(manifest_binding, Mapping)):
                    raise FoundryError("GM_AUTHORING_MANIFEST_BINDING_INVALID", "The actual GM workspace lacks a verified artifact binding.")
                if isinstance(manifest_binding, Mapping):
                    for field in (
                        "receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256",
                        "source_snapshot_sha256", "selected_record_content_sha256", "owner_decision_id", "owner_ratified",
                    ):
                        if manifest_binding.get(field) != verified_gm_binding.get(field):
                            raise FoundryError("GM_AUTHORING_MANIFEST_BINDING_INVALID", "The workspace manifest does not match its server-owned GM receipt.", details={"field": field})
                pointer_fields = {
                    "gm_receipt_id": "receipt_id",
                    "gm_receipt_sha256": "receipt_sha256",
                    "gm_artifact_sha256": "artifact_sha256",
                    "gm_profile_sha256": "profile_sha256",
                    "gm_request_sha256": "request_sha256",
                    "gm_response_sha256": "response_sha256",
                    "gm_source_snapshot_sha256": "source_snapshot_sha256",
                    "gm_selected_record_content_sha256": "selected_record_content_sha256",
                    "gm_owner_decision_id": "owner_decision_id",
                }
                if binding_expected and any(payload.get(pointer_field) != verified_gm_binding.get(binding_field) for pointer_field, binding_field in pointer_fields.items()):
                    raise FoundryError("GM_AUTHORING_POINTER_BINDING_INVALID", "The workspace pointer does not match its server-owned GM receipt.")
                gm_workspace_bound = (
                    isinstance(manifest_binding, Mapping)
                    and manifest_payload.get("project_revision") == current_project.get("revision")
                    and all(
                        manifest_binding.get(field) == verified_gm_binding.get(field)
                        for field in (
                            "receipt_id", "receipt_sha256", "artifact_sha256", "profile_sha256",
                            "source_snapshot_sha256", "selected_record_content_sha256", "owner_decision_id", "owner_ratified",
                        )
                    )
                    and all(
                        payload.get(pointer_field) == verified_gm_binding.get(binding_field)
                        for pointer_field, binding_field in pointer_fields.items()
                    )
                )
            except (FoundryError, OSError, ValueError, json.JSONDecodeError):
                verified_gm_binding = None
                gm_authoring_status = "STALE"
                eligible_for_command5 = False
            else:
                gm_authoring_status = "ACTUAL_GM_AUTHORING"
                eligible_for_command5 = verified_gm_binding.get("owner_ratified") is True
        if isinstance(verified_gm_binding, Mapping):
            gm_authoring_status = "ACTUAL_GM_AUTHORING"
        elif gm_verification_attempted:
            gm_authoring_status = "STALE"
        elif manifest_classification == "PROVISIONAL_GM_GUIDANCE":
            gm_authoring_status = "PROVISIONAL_GM_GUIDANCE_ONLY"
        elif manifest_classification == "ACTUAL_GM_AUTHORING":
            gm_authoring_status = "STALE" if verified_gm_binding is None else "ACTUAL_GM_AUTHORING"
        else:
            gm_authoring_status = payload.get("gm_authoring_status") or "COMPLETE_AS_WORKSPACE_INPUT"
        eligible_for_command5 = (
            verified_gm_binding.get("owner_ratified") is True
            if isinstance(verified_gm_binding, Mapping)
            else False
            if manifest_classification == "ACTUAL_GM_AUTHORING"
            else payload.get("eligible_for_later_command5_checkpoint")
        )
        if type(eligible_for_command5) is not bool:
            eligible_for_command5 = False if gm_authoring_status == "PROVISIONAL_GM_GUIDANCE_ONLY" else (
                bool(manifest_authorship.get("owner_ratified"))
                if gm_authoring_status == "ACTUAL_GM_AUTHORING" and isinstance(manifest_authorship, dict)
                else gm_authoring_status == "COMPLETE_AS_WORKSPACE_INPUT" and candidate_status == "NOT_RUN"
            )
        result = {
            "status": "REBUILD_PENDING" if isinstance(verified_gm_binding, Mapping) and not gm_workspace_bound else payload.get("workspace_status"),
            "workspace_id": None if isinstance(verified_gm_binding, Mapping) and not gm_workspace_bound else payload.get("workspace_id"),
            "workspace_sha256": None if isinstance(verified_gm_binding, Mapping) and not gm_workspace_bound else payload.get("workspace_sha256"),
            "gm_authoring": gm_authoring_status,
            "command5": candidate_status,
            "command5_candidate": candidate_details,
            "command6": "NOT_RUN",
            "gm_screen_consumer_verification": "NOT_ATTEMPTED",
            "gm_export_available": False,
            "eligible_for_later_command5_checkpoint": eligible_for_command5,
            "legacy_command5_eligible": False,
            "provider_free_rebuild_available": isinstance(verified_gm_binding, Mapping) and not gm_workspace_bound,
        }
        if gm_authoring_status != "COMPLETE_AS_WORKSPACE_INPUT" or "gm_authoring_status" in payload:
            result.update({
                "gm_authorship_status": "ACTUAL" if isinstance(verified_gm_binding, Mapping) else payload.get("gm_authorship_status") or (manifest_authorship.get("status") if isinstance(manifest_authorship, dict) else None),
                "gm_authoring_actual": gm_authoring_status == "ACTUAL_GM_AUTHORING",
                "gm_authoring_profile_classification": "ACTUAL_GM_AUTHORING" if isinstance(verified_gm_binding, Mapping) else payload.get("gm_authoring_profile_classification") or manifest_classification,
            })
            if isinstance(verified_gm_binding, Mapping):
                result.update({
                    "gm_receipt_id": verified_gm_binding.get("receipt_id"),
                    "gm_receipt_sha256": verified_gm_binding.get("receipt_sha256"),
                    "gm_artifact_sha256": verified_gm_binding.get("artifact_sha256"),
                    "gm_profile_sha256": verified_gm_binding.get("profile_sha256"),
                    "gm_source_snapshot_sha256": verified_gm_binding.get("source_snapshot_sha256"),
                    "gm_selected_record_content_sha256": verified_gm_binding.get("selected_record_content_sha256"),
                    "gm_owner_decision_id": verified_gm_binding.get("owner_decision_id"),
                    "gm_owner_ratified": verified_gm_binding.get("owner_ratified") is True,
                })
        return result

    @staticmethod
    def _complete_character_unavailable(
        project_id: str,
        projection_id: Any,
        *,
        reason_code: str,
        reason: str,
        candidate_sha256: str | None = None,
        source_kind: str | None = None,
        package_sha256: str | None = None,
        finalized: bool = False,
    ) -> dict[str, Any]:
        surfaces = {
            surface_id: {
                "available": False,
                "status": "unavailable",
                "reason_code": reason_code,
                "data": None,
            }
            for surface_id in _COMPLETE_CHARACTER_SURFACE_IDS
        }
        return {
            "schema": _COMPLETE_CHARACTER_SCHEMA,
            "schema_version": _COMPLETE_CHARACTER_SCHEMA,
            "version": 1,
            "available": False,
            "source_kind": source_kind,
            "project_id": project_id,
            "projection_id": projection_id,
            "package_sha256": package_sha256,
            "candidate_sha256": candidate_sha256,
            "finalized": finalized,
            "required_surface_ids": list(_COMPLETE_CHARACTER_SURFACE_IDS),
            "surfaces": surfaces,
            "coverage": {
                "required_count": len(_COMPLETE_CHARACTER_SURFACE_IDS),
                "available_count": 0,
                "missing_ids": list(_COMPLETE_CHARACTER_SURFACE_IDS),
                "complete": False,
            },
            "reason_code": reason_code,
            "reason": reason,
        }

    @staticmethod
    def _complete_character_archive(path: Path) -> dict[str, Any]:
        """Verify a candidate/portable ZIP and decode only approved JSON members."""
        from portable_character.service import MAX_ARCHIVE_BYTES, MAX_ENTRIES, MAX_EXPANDED_BYTES

        fd: int | None = None
        try:
            if path.is_symlink():
                raise FoundryError(
                    "COMPLETE_CHARACTER_ARCHIVE_INVALID",
                    "The verified Character archive is a symbolic link.",
                )
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, "rb") as source:
                fd = None
                file_stat = os.fstat(source.fileno())
                if not stat.S_ISREG(file_stat.st_mode):
                    raise FoundryError(
                        "COMPLETE_CHARACTER_ARCHIVE_INVALID",
                        "The verified Character archive is not a regular file.",
                    )
                if file_stat.st_size > MAX_ARCHIVE_BYTES:
                    raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive is too large.")
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
                actual_sha256 = digest.hexdigest()
                source.seek(0)
                with zipfile.ZipFile(source) as archive:
                    infos = archive.infolist()
                    if len(infos) > MAX_ENTRIES:
                        raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive contains too many entries.")
                    names: set[str] = set()
                    folded: set[str] = set()
                    normalized: set[str] = set()
                    total = 0
                    info_by_name: dict[str, zipfile.ZipInfo] = {}
                    for info in infos:
                        name = info.filename.replace("\\", "/")
                        pure = PurePosixPath(name)
                        if pure.is_absolute() or ".." in pure.parts or not name or "\x00" in name:
                            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive contains an unsafe path.")
                        key = name.rstrip("/")
                        mode = info.external_attr >> 16
                        kind = stat.S_IFMT(mode)
                        if not key or kind == stat.S_IFLNK or kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive contains a special file.")
                        if info.flag_bits & 0x1 or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive uses unsupported ZIP features.")
                        fold = key.casefold()
                        norm = unicodedata.normalize("NFC", key).casefold()
                        if key in names or fold in folded or norm in normalized:
                            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive contains colliding paths.")
                        names.add(key)
                        folded.add(fold)
                        normalized.add(norm)
                        info_by_name[key] = info
                        total += info.file_size
                        if total > MAX_EXPANDED_BYTES:
                            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive expands beyond the configured limit.")
                    if "SHA256SUMS.txt" not in info_by_name or info_by_name["SHA256SUMS.txt"].is_dir():
                        raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive lacks its checksum manifest.")
                    if archive.testzip() is not None:
                        raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive failed CRC validation.")

                    declared: dict[str, str] = {}
                    for line in archive.read("SHA256SUMS.txt").decode("utf-8").splitlines():
                        if not line.strip():
                            continue
                        checksum, separator, member = line.partition("  ")
                        if (
                            not separator
                            or len(checksum) != 64
                            or any(character not in "0123456789abcdefABCDEF" for character in checksum)
                            or not member
                            or member in declared
                        ):
                            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character checksum manifest is malformed.")
                        declared[member] = checksum.lower()
                    payload_names = sorted(
                        name for name, info in info_by_name.items() if name != "SHA256SUMS.txt" and not info.is_dir()
                    )
                    if sorted(declared) != payload_names:
                        raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character checksum manifest does not cover the archive exactly.")
                    for member, expected in declared.items():
                        if sha256_bytes(archive.read(member)) != expected:
                            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "A verified Character archive member failed its checksum.")

                    fixed_members = sorted({
                        member
                        for members in _COMPLETE_CHARACTER_SURFACE_MEMBERS.values()
                        for member in members
                    })
                    decoded: dict[str, Any] = {}
                    for member in fixed_members:
                        if member not in info_by_name or info_by_name[member].is_dir():
                            continue
                        value = json.loads(archive.read(member).decode("utf-8"))
                        if not isinstance(value, (dict, list)):
                            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "A verified Character surface is not a JSON object or array.")
                        decoded[member] = value
                    return {
                        "sha256": actual_sha256,
                        "members": decoded,
                        "member_count": len(payload_names),
                        "checksum_count": len(declared),
                    }
        except FoundryError:
            raise
        except (OSError, KeyError, RuntimeError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
            raise FoundryError("COMPLETE_CHARACTER_ARCHIVE_INVALID", "The verified Character archive could not be read safely.") from exc
        finally:
            if fd is not None:
                os.close(fd)

    @staticmethod
    def _complete_character_candidate_pointer(data_dir: Path, project_id: str, projection_status: dict[str, Any]) -> dict[str, Any]:
        pointer_path = data_dir / "factory_candidates" / project_id / "current.json"
        if pointer_path.is_symlink() or not pointer_path.is_file():
            raise FoundryError("COMPLETE_CHARACTER_CANDIDATE_POINTER_MISSING", "The current Command 5 candidate pointer is unavailable.")
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise FoundryError("COMPLETE_CHARACTER_CANDIDATE_POINTER_INVALID", "The current Command 5 candidate pointer is unreadable.") from exc
        if not isinstance(pointer, dict):
            raise FoundryError("COMPLETE_CHARACTER_CANDIDATE_POINTER_INVALID", "The current Command 5 candidate pointer is not an object.")
        candidate_sha256 = pointer.get("candidate_sha256")
        if pointer.get("project_id") != project_id:
            raise FoundryError(
                "COMPLETE_CHARACTER_CANDIDATE_PROJECT_MISMATCH",
                "The current Command 5 candidate belongs to a different project.",
                details={"candidate_sha256": candidate_sha256},
            )
        if pointer.get("status") != "GM_MODEL_CANDIDATE_READY":
            raise FoundryError(
                "COMPLETE_CHARACTER_CANDIDATE_NOT_READY",
                "The current Command 5 candidate is not ready.",
                details={"candidate_sha256": candidate_sha256},
            )
        projection_id = projection_status.get("projection_id") if isinstance(projection_status, dict) else None
        if not projection_id or pointer.get("projection_id") != projection_id:
            raise FoundryError(
                "COMPLETE_CHARACTER_CANDIDATE_PROJECTION_MISMATCH",
                "The current Command 5 candidate is not bound to the current projection.",
                details={"candidate_sha256": candidate_sha256, "projection_id": projection_id},
            )
        candidate_value = pointer.get("candidate_zip")
        if not isinstance(candidate_value, str) or not candidate_value.strip():
            raise FoundryError(
                "COMPLETE_CHARACTER_CANDIDATE_ARCHIVE_MISSING",
                "The current Command 5 candidate archive path is missing.",
                details={"candidate_sha256": candidate_sha256},
            )
        candidate = Path(candidate_value)
        if candidate.is_symlink() or not candidate.is_file():
            raise FoundryError(
                "COMPLETE_CHARACTER_CANDIDATE_ARCHIVE_MISSING",
                "The current Command 5 candidate archive is missing or is not a regular file.",
                details={"candidate_sha256": candidate_sha256},
            )
        try:
            archive = CharacterSheetService._complete_character_archive(candidate)
        except FoundryError as exc:
            if exc.code == "COMPLETE_CHARACTER_ARCHIVE_INVALID" and not candidate.exists():
                raise FoundryError(
                    "COMPLETE_CHARACTER_CANDIDATE_ARCHIVE_MISSING",
                    "The current Command 5 candidate archive is missing or is not a regular file.",
                    details={"candidate_sha256": candidate_sha256},
                ) from exc
            raise
        actual = archive.get("sha256")
        if actual != candidate_sha256:
            raise FoundryError(
                "COMPLETE_CHARACTER_CANDIDATE_HASH_MISMATCH",
                "The current Command 5 candidate archive hash does not match its pointer.",
                details={"candidate_sha256": candidate_sha256, "actual_sha256": actual},
            )
        return {
            "path": candidate,
            "candidate_sha256": actual,
            "projection_id": projection_id,
            "archive": archive,
        }

    def _complete_character_finalized_source(
        self,
        project_id: str,
        projection_id: Any,
        candidate_sha256: str,
        *,
        verified: Any = _COMPLETE_CHARACTER_UNSET,
    ) -> dict[str, Any] | None:
        if verified is _COMPLETE_CHARACTER_UNSET:
            verified = self._portable_verified_status(project_id)
        if not isinstance(verified, dict) or verified.get("status") != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
            return None
        verified_projection_id = verified.get("projection_id")
        if verified.get("project_id") != project_id or (
            verified_projection_id is not None and verified_projection_id != projection_id
        ):
            return None
        package_value = verified.get("package_path")
        if not isinstance(package_value, str) or not package_value.strip():
            return None
        package = Path(package_value)
        if package.name != "current.zip" or package.parent.name != project_id or package.is_symlink() or not package.is_file():
            return None
        package_sha256 = verified.get("package_sha256")
        manifest_identity = verified.get("manifest_identity")
        pointer_candidate_sha256 = (
            manifest_identity.get("source_command5_candidate_sha256")
            if isinstance(manifest_identity, dict)
            else verified.get("source_command5_candidate_sha256")
        )
        audit = verified.get("audit")
        manifest = audit.get("manifest") if isinstance(audit, dict) else None
        if (
            not isinstance(package_sha256, str)
            or pointer_candidate_sha256 != candidate_sha256
            or not isinstance(audit, dict)
            or audit.get("valid") is not True
            or audit.get("sha256") != package_sha256
            or not isinstance(manifest, dict)
            or manifest.get("project_id") != project_id
            or manifest.get("source_command5_candidate_sha256") != candidate_sha256
        ):
            return None
        if manifest.get("projection_id") not in (None, projection_id):
            return None
        try:
            archive = self._complete_character_archive(package)
            actual = archive.get("sha256")
            if actual != package_sha256:
                return None
        except (OSError, FoundryError):
            return None
        return {
            "path": package,
            "package_sha256": actual,
            "candidate_sha256": candidate_sha256,
            "projection_id": projection_id,
            "archive": archive,
            "source_kind": "finalized",
            "finalized": True,
        }

    def _portable_verified_status(self, project_id: str) -> dict[str, Any] | None:
        try:
            from portable_character.service import PortableCharacterPackageService

            verified = PortableCharacterPackageService(self.db).verified_status(project_id)
        except Exception:
            return None
        return verified if isinstance(verified, dict) else None

    @staticmethod
    def _complete_character_project_value(value: Any, allowed_keys: frozenset[str]) -> Any:
        if isinstance(value, list):
            return [CharacterSheetService._complete_character_project_value(item, allowed_keys) for item in value]
        if not isinstance(value, dict):
            return deepcopy(value)
        return {
            key: CharacterSheetService._complete_character_project_value(item, allowed_keys)
            for key, item in value.items()
            if key in allowed_keys
        }

    @classmethod
    def _complete_character_project_document(
        cls,
        value: Any,
        fields: frozenset[str],
        nested_fields: frozenset[str],
    ) -> Any:
        if not isinstance(value, dict):
            return None
        return {
            key: cls._complete_character_project_value(item, nested_fields)
            for key, item in value.items()
            if key in fields
        }

    @classmethod
    def _complete_character_project_action_row(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return None
        return {
            key: cls._complete_character_project_value(value[key], _COMPLETE_CHARACTER_ACTION_NESTED_FIELDS)
            for key in _COMPLETE_CHARACTER_ACTION_ROW_FIELDS
            if key in value
        }

    @classmethod
    def _complete_character_project_action_document(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return None
        result = cls._complete_character_project_document(
            value,
            _COMPLETE_CHARACTER_ACTION_FIELDS,
            _COMPLETE_CHARACTER_ACTION_NESTED_FIELDS,
        )
        for key in ("actions", "procedures"):
            rows = value.get(key)
            if isinstance(rows, list):
                result[key] = [projected for row in rows if (projected := cls._complete_character_project_action_row(row)) is not None]
        return result

    @classmethod
    def _complete_character_display_row(cls, document: Any, tab_id: str, surface_id: str) -> Any:
        if not isinstance(document, dict) or not isinstance(document.get("rows"), list):
            return None
        for row in document["rows"]:
            if not isinstance(row, dict) or row.get("tab_id") != tab_id and row.get("tab") != tab_id:
                continue
            if "value" not in row:
                return None
            projection = _COMPLETE_CHARACTER_SURFACE_PROJECTION.get(surface_id)
            if projection is None:
                return None
            fields, nested_fields = projection
            if isinstance(row["value"], list):
                return cls._complete_character_project_value(row["value"], nested_fields)
            return cls._complete_character_project_document(row["value"], fields, nested_fields)
        return None

    @classmethod
    def _complete_character_model_surface(cls, surface_id: str, document: dict[str, Any]) -> Any:
        if surface_id == "overview_core_stats":
            fields, nested_fields = _COMPLETE_CHARACTER_SURFACE_PROJECTION[surface_id]
            return cls._complete_character_project_document(document, fields, nested_fields)
        if surface_id == "paths_subpaths":
            fields, nested_fields = _COMPLETE_CHARACTER_SURFACE_PROJECTION[surface_id]
            return cls._complete_character_project_document(document, fields, nested_fields)
        if surface_id == "manuals_recorded_arts":
            fields, nested_fields = _COMPLETE_CHARACTER_SURFACE_PROJECTION[surface_id]
            return cls._complete_character_project_document(document, fields, nested_fields)
        if surface_id == "resources_states_suppression":
            fields, nested_fields = _COMPLETE_CHARACTER_SURFACE_PROJECTION[surface_id]
            return cls._complete_character_project_document(document, fields, nested_fields)
        if surface_id == "companions":
            fields, nested_fields = _COMPLETE_CHARACTER_SURFACE_PROJECTION[surface_id]
            return cls._complete_character_project_document(document, fields, nested_fields)
        projection = _COMPLETE_CHARACTER_SURFACE_PROJECTION.get(surface_id)
        if projection is None:
            return None
        fields, nested_fields = projection
        return cls._complete_character_project_document(document, fields, nested_fields)

    @classmethod
    def _complete_character_project_member(cls, surface_id: str, member: str, document: Any) -> Any:
        if member == _COMPLETE_CHARACTER_DISPLAY_ROWS and surface_id in _COMPLETE_CHARACTER_DISPLAY_TABS:
            return cls._complete_character_display_row(
                document,
                _COMPLETE_CHARACTER_DISPLAY_TABS[surface_id],
                surface_id,
            )
        if surface_id == "actions":
            return cls._complete_character_project_action_document(document)
        if member in {_COMPLETE_CHARACTER_MODEL_V1, _COMPLETE_CHARACTER_MODEL_V2, _COMPLETE_CHARACTER_VIEW}:
            if not isinstance(document, dict):
                return None
            return cls._complete_character_model_surface(surface_id, document)
        projection = _COMPLETE_CHARACTER_SURFACE_PROJECTION.get(surface_id)
        if projection is None:
            return None
        fields, nested_fields = projection
        if isinstance(document, dict):
            return cls._complete_character_project_document(document, fields, nested_fields)
        if isinstance(document, list):
            return cls._complete_character_project_value(document, nested_fields)
        return None

    @staticmethod
    def _complete_character_diagnostics(source: dict[str, Any], archive: dict[str, Any], *, source_kind: str, finalized: bool) -> dict[str, Any]:
        scalar_keys = (
            "schema_version",
            "status",
            "valid",
            "verdict",
            "release_ready",
            "consumer_verification",
            "command6_status",
            "gm_screen_consumer_verification",
            "event_schema_version",
            "tab_count",
            "action_display_count",
            "selected_record_count",
            "training_coverage_count",
        )
        count_keys = frozenset({
            "available_count", "required_count", "missing_count", "unresolved_count", "issue_count", "member_count",
            "checksum_count", "entry_count", "file_count", "coverage_count", "selected_record_count",
            "training_coverage_count", "tab_count", "action_display_count",
        })
        reports: dict[str, Any] = {}
        for member in _COMPLETE_CHARACTER_DIAGNOSTIC_MEMBERS:
            document = source.get(member)
            if not isinstance(document, dict):
                continue
            report: dict[str, Any] = {
                key: deepcopy(document[key])
                for key in scalar_keys
                if key in document and isinstance(document[key], (bool, int, float, str))
            }
            for key in ("diagnostics", "issues", "unresolved"):
                value = document.get(key)
                if isinstance(value, (list, dict)):
                    report[f"{key}_count"] = len(value)
            counts = document.get("counts")
            if isinstance(counts, dict):
                report["counts"] = {
                    str(key): value
                    for key, value in counts.items()
                    if key in count_keys and isinstance(value, (bool, int, float, str))
                }
            reports[member] = report
        return {
            "archive": {
                "status": "VALID",
                "member_count": archive.get("member_count"),
                "checksum_count": archive.get("checksum_count"),
            },
            "source": {"kind": source_kind, "finalized": finalized},
            "reports": reports,
        }

    @classmethod
    def _complete_character_surfaces(
        cls,
        archive: dict[str, Any],
        *,
        source_kind: str,
        finalized: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        members = archive.get("members") if isinstance(archive, dict) else {}
        if not isinstance(members, dict):
            members = {}
        surfaces: dict[str, Any] = {}
        for surface_id in _COMPLETE_CHARACTER_SURFACE_IDS:
            if surface_id == "diagnostics":
                diagnostic_members = [member for member in _COMPLETE_CHARACTER_DIAGNOSTIC_MEMBERS if member in members]
                if not diagnostic_members:
                    surfaces[surface_id] = {
                        "available": False,
                        "status": "unavailable",
                        "reason_code": "COMPLETE_CHARACTER_SURFACE_MISSING",
                        "data": None,
                    }
                    continue
                surfaces[surface_id] = {
                    "available": True,
                    "status": "available",
                    "source_members": diagnostic_members,
                    "data": cls._complete_character_diagnostics(members, archive, source_kind=source_kind, finalized=finalized),
                }
                continue
            values: list[tuple[str, Any]] = []
            for member in _COMPLETE_CHARACTER_SURFACE_MEMBERS[surface_id]:
                document = members.get(member)
                if document is None:
                    continue
                value = cls._complete_character_project_member(surface_id, member, document)
                if value is None:
                    continue
                values.append((member, value))
                if surface_id in {"overview_core_stats", "paths_subpaths"}:
                    break
            if not values:
                surfaces[surface_id] = {
                    "available": False,
                    "status": "unavailable",
                    "reason_code": "COMPLETE_CHARACTER_SURFACE_MISSING",
                    "data": None,
                }
                continue
            data: Any = values[0][1] if len(values) == 1 else {member: value for member, value in values}
            surfaces[surface_id] = {
                "available": True,
                "status": "available",
                "source_member": values[0][0] if len(values) == 1 else None,
                "source_members": [member for member, _ in values],
                "data": data,
            }
        missing = [surface_id for surface_id, value in surfaces.items() if not value.get("available")]
        coverage = {
            "required_count": len(_COMPLETE_CHARACTER_SURFACE_IDS),
            "available_count": len(_COMPLETE_CHARACTER_SURFACE_IDS) - len(missing),
            "missing_ids": missing,
            "complete": not missing,
        }
        return surfaces, coverage

    def _index_recorded_art_rows(self, project_id: str) -> list[dict[str, Any]]:
        """Index the Recorded Arts a project's lineage Manuals grant.

        A lineage Manual's Recorded Arts live in the frozen project's lock set
        as a bundle contract, not in the ledger.  The rows are returned to the
        caller rather than stored on the service instance: the instance is
        process-wide, so per-request state on it was overwritten by a
        concurrent ``/api/characters`` sweep (``list_characters`` runs
        ``sheet(compact=True)`` for every project) and the reference sheet
        lost its arts.
        """

        rows: list[dict[str, Any]] = []
        try:
            from character_creation.constructed_arts.records import (
                constructed_art_contract as _constructed_art_contract,
            )
        except Exception:
            _constructed_art_contract = None
        if _constructed_art_contract is None:
            return rows
        try:
            with self.db.connection() as conn:
                art_rows = conn.execute(
                    "SELECT record_json FROM project_locked_records WHERE project_id=? ORDER BY record_id",
                    (project_id,),
                ).fetchall()
        except Exception:
            art_rows = []
        for stored in art_rows:
            raw = stored["record_json"] if not isinstance(stored, dict) else stored.get("record_json")
            if not isinstance(raw, str):
                continue
            try:
                record = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if not isinstance(record, dict) or record.get("content_type") != "recorded_art":
                continue
            contract = _constructed_art_contract(record)
            bundle = contract.get("bundle") if isinstance(contract, dict) else None
            arts = bundle.get("recorded_arts") if isinstance(bundle, dict) else None
            if not isinstance(arts, list):
                continue
            art_id = record.get("record_id")
            for art in arts:
                if isinstance(art, dict) and art.get("record_id") == art_id:
                    rows.append(deepcopy(art))
                    break
        return rows

    def _with_authenticated_recorded_arts(
        self,
        surfaces: Any,
        recorded_art_rows: list[dict[str, Any]] | None = None,
    ) -> Any:
        """Expose the Recorded Arts a lineage Manual grants on the sheet surface.

        The surface declares ``recorded_arts`` but the ledger only carries arts
        acquired through a causal acquisition event, so a Manual's three
        children never arrived and the tab rendered each Manual's one-line
        summary alone.  The arts themselves are complete in the frozen lock set
        (indexed per request by ``_index_recorded_art_rows``); this puts them
        where the section already looks.  Display only; the sealed artifact is
        untouched.
        """

        if not isinstance(surfaces, dict) or not recorded_art_rows:
            return surfaces
        recorded = surfaces.get("manuals_recorded_arts")
        data = recorded.get("data") if isinstance(recorded, dict) else None
        if not isinstance(data, dict):
            return surfaces
        result = None
        for key, value in data.items():
            if not isinstance(value, dict):
                continue
            if isinstance(value.get("recorded_arts"), list) and not value["recorded_arts"]:
                if result is None:
                    result = deepcopy(surfaces)
                target = result["manuals_recorded_arts"]["data"][key]
                target["recorded_arts"] = deepcopy(recorded_art_rows)
                target.pop("recorded_arts_none_state", None)
        return result if result is not None else surfaces

    def _index_insight_text_lookup(self, snapshot: Any) -> dict[str, dict[str, Any]]:
        """Index a request's locked Insight rows by id.

        The locked Insight records carry the printed text.  The mapping is
        returned to the caller rather than stored on the service instance: the
        instance is process-wide, so per-request state on it was overwritten by
        a concurrent non-compact ``sheet()`` for another project while a live
        page was being built, and that page lost its Insight rules text.
        """

        lookup: dict[str, dict[str, Any]] = {}
        try:
            locked_insight_rows = ((snapshot or {}).get("selected_record_sections") or {}).get("insights") or []
        except AttributeError:
            locked_insight_rows = []
        for locked_row in locked_insight_rows:
            if not isinstance(locked_row, dict):
                continue
            locked_id = locked_row.get("record_id") or locked_row.get("insight_id")
            if isinstance(locked_id, str) and locked_id:
                lookup[locked_id] = locked_row
        return lookup

    def _with_authenticated_insight_text(
        self,
        surfaces: Any,
        insight_text_lookup: dict[str, dict[str, Any]] | None = None,
    ) -> Any:
        """Attach each Insight's printed text to the insight surface rows.

        Insight rows were projected with only a name, a level and an ability
        change, so an owner saw no description at all.  The sealed snapshot
        already holds the locked record's text for every selected Insight
        (indexed per request by the caller before the envelope is built), so it
        is copied onto the surface rows here.  Display only: ids, hashes and the
        sealed artifact itself are untouched.
        """

        if not isinstance(surfaces, dict):
            return surfaces
        insights = surfaces.get("insights")
        data = insights.get("data") if isinstance(insights, dict) else None
        if not isinstance(data, dict):
            return surfaces
        ledger = data.get("Character_Master_Ledger.json")
        if not isinstance(ledger, dict):
            return surfaces
        targets: list[tuple[str, int, dict[str, Any]]] = []
        for key in ("cultivation_insight_occurrences", "insights"):
            for index, row in enumerate(ledger.get(key) or []):
                if not isinstance(row, dict):
                    continue
                current = row.get("full_description")
                if isinstance(current, str) and len(current.strip()) >= self._RULES_TEXT_MIN_CHARS:
                    continue
                targets.append((key, index, row))
        if not targets:
            return surfaces
        source = insight_text_lookup or {}
        if not source:
            return surfaces
        result = surfaces
        changed = False
        for key, index, row in targets:
            record_id = row.get("insight_id") or row.get("record_id") or row.get("source_record_id")
            locked = source.get(str(record_id)) if record_id else None
            if not isinstance(locked, dict):
                continue
            text = locked.get("full_description") or locked.get("one_line_description")
            if not isinstance(text, str) or not text.strip():
                continue
            if not changed:
                result = deepcopy(surfaces)
                changed = True
            target = result["insights"]["data"]["Character_Master_Ledger.json"][key][index]
            if not isinstance(target, dict):
                continue
            target["full_description"] = text.strip()
            target["full_description_source"] = locked.get("full_description_source") or "locked_typed_catalog_record"
            target["one_line_description"] = locked.get("one_line_description") or text.strip()
        return result

    def _with_authenticated_surface_rules_text(self, surfaces: Any) -> Any:
        """Attach the printed rules text to talent and Sphere surface rows.

        Owner request 2026-09-13 (plan B3): the Command 5 candidate stores the
        catalog's first line as a talent's ``full_description``.  The sealed
        candidate is never rewritten.  This view-time overlay resolves the same
        rows against the locked catalog record and the installed pack, so an
        already-finalized character reads like a newly finalized one.
        """

        if not isinstance(surfaces, dict):
            return surfaces
        data = surfaces.get("spheres_talents", {}).get("data") if isinstance(surfaces.get("spheres_talents"), dict) else None
        if not isinstance(data, dict):
            return surfaces
        ledger = data.get("Talent_Source_Ledger.json")
        sphere_document = data.get("Selected_Spheres.json")
        # (document, key, index, row) targets, so every enriched row maps back
        # to exactly one position in the response structure.
        targets: list[tuple[str, str, int, dict[str, Any]]] = []
        if isinstance(ledger, dict):
            for key in ("learned_talents", "background_talents"):
                for index, row in enumerate(ledger.get(key) or []):
                    if isinstance(row, dict):
                        targets.append(("Talent_Source_Ledger.json", key, index, row))
        if isinstance(sphere_document, dict):
            for index, row in enumerate(sphere_document.get("spheres") or []):
                if isinstance(row, dict):
                    targets.append(("Selected_Spheres.json", "spheres", index, row))
        if not targets:
            return surfaces
        if self._authenticated_factory_root() is None:
            return surfaces

        overlay = {"selected_record_sections": {"talents": [row for _m, _k, _i, row in targets]}}
        enriched = self._with_authenticated_rules_text(overlay)
        if enriched is overlay:
            return surfaces
        enriched_rows = enriched["selected_record_sections"]["talents"]

        result = deepcopy(surfaces)
        result_data = result["spheres_talents"]["data"]
        for (member, key, index, _row), replacement in zip(targets, enriched_rows):
            source_text = replacement.get("full_description")
            if not isinstance(source_text, str):
                continue
            target = result_data.get(member, {}).get(key, [])[index]
            if not isinstance(target, dict):
                continue
            target["full_description"] = source_text
            if replacement.get("full_description_source"):
                target["full_description_source"] = replacement["full_description_source"]
            target["rules_text_source_locator"] = replacement.get("rules_text_source_locator")
        return result

    def _complete_character_with_portable(
        self,
        project_id: str,
        projection_status: dict[str, Any],
        *,
        portable_verified: Any = _COMPLETE_CHARACTER_UNSET,
        recorded_art_rows: list[dict[str, Any]] | None = None,
        insight_text_lookup: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        projection_id = projection_status.get("projection_id") if isinstance(projection_status, dict) else None
        base_portable_verified = None if portable_verified is _COMPLETE_CHARACTER_UNSET else portable_verified
        try:
            candidate = self._complete_character_candidate_pointer(self.db.settings.data_dir, project_id, projection_status)
        except FoundryError as exc:
            details = exc.details if isinstance(exc.details, dict) else {}
            return self._complete_character_unavailable(
                project_id,
                projection_id,
                reason_code=exc.code,
                reason=exc.message,
                candidate_sha256=details.get("candidate_sha256"),
            ), base_portable_verified
        except Exception:
            return self._complete_character_unavailable(
                project_id,
                projection_id,
                reason_code="COMPLETE_CHARACTER_CANDIDATE_UNAVAILABLE",
                reason="The current Command 5 candidate could not be verified.",
            ), base_portable_verified

        selected = {
            "archive": candidate["archive"],
            "candidate_sha256": candidate["candidate_sha256"],
            "package_sha256": candidate["candidate_sha256"],
            "source_kind": "candidate",
            "finalized": False,
        }
        if portable_verified is _COMPLETE_CHARACTER_UNSET:
            portable_verified = self._portable_verified_status(project_id)
        finalized = self._complete_character_finalized_source(
            project_id,
            candidate["projection_id"],
            candidate["candidate_sha256"],
            verified=portable_verified,
        )
        if finalized is not None:
            selected = finalized
        surfaces, coverage = self._complete_character_surfaces(
            selected["archive"],
            source_kind=selected["source_kind"],
            finalized=selected["finalized"],
        )
        if coverage["missing_ids"]:
            return {
                "schema": _COMPLETE_CHARACTER_SCHEMA,
                "schema_version": _COMPLETE_CHARACTER_SCHEMA,
                "version": 1,
                "available": False,
                "source_kind": selected["source_kind"],
                "project_id": project_id,
                "projection_id": candidate["projection_id"],
                "package_sha256": selected["package_sha256"],
                "candidate_sha256": candidate["candidate_sha256"],
                "finalized": selected["finalized"],
                "required_surface_ids": list(_COMPLETE_CHARACTER_SURFACE_IDS),
                "surfaces": surfaces,
                "coverage": coverage,
                "reason_code": "COMPLETE_CHARACTER_SURFACE_MISSING",
                "reason": "The verified Character archive does not contain every canonical mechanics surface.",
            }, portable_verified
        if recorded_art_rows is None:
            # Direct callers (``_complete_character``) reach this method without
            # the sheet's per-request rows; index them here rather than reading
            # shared instance state.
            recorded_art_rows = self._index_recorded_art_rows(project_id)
        # ``insight_text_lookup`` stays ``None`` for the direct test-only caller
        # (``_complete_character``): no lookup means no enrichment.  The only
        # production caller, ``sheet()``, always passes this request's lookup.
        return {
            "schema": _COMPLETE_CHARACTER_SCHEMA,
            "schema_version": _COMPLETE_CHARACTER_SCHEMA,
            "version": 1,
            "available": True,
            "source_kind": selected["source_kind"],
            "project_id": project_id,
            "projection_id": candidate["projection_id"],
            "package_sha256": selected["package_sha256"],
            "candidate_sha256": candidate["candidate_sha256"],
            "finalized": selected["finalized"],
            "required_surface_ids": list(_COMPLETE_CHARACTER_SURFACE_IDS),
            # Display-only: talent and Sphere rows carry the printed rules text
            # rather than the catalog's first line (plan B3).
            "surfaces": self._with_authenticated_recorded_arts(
                self._with_authenticated_insight_text(
                    self._with_authenticated_surface_rules_text(surfaces),
                    insight_text_lookup,
                ),
                recorded_art_rows,
            ),
            "coverage": coverage,
            "reason_code": None,
            "reason": None,
        }, portable_verified

    def _complete_character(self, project_id: str, projection_status: dict[str, Any]) -> dict[str, Any]:
        envelope, _portable_verified = self._complete_character_with_portable(project_id, projection_status)
        return envelope

    def _publish_worn_armour(self, snapshot: dict[str, Any], ledger: dict[str, Any]) -> None:
        """Publish the Armor Class and Speed this character actually fights with.

        The sheet published only the unarmored calculation and the unpenalized Speed, so a character
        wearing heavy armour read an Armor Class and a Speed the table never used (AUDIT9b NEW-1,
        NEW-2).  ``combat.armour`` is the single reader of both equipment slots; this asks it the same
        question the compiler asks about the same published document, so the sheet and the fight use
        one derivation and cannot drift apart.

        The projection's own ``armor_class.base_value``/``value`` and ``speed.walking_ft`` are left
        exactly as they are: this document is what the compiler reads on the next compile, where
        ``_ac_basis`` recovers the unarmored basis from those AC fields and the Strength penalty is
        subtracted from ``walking_ft``.  The numbers a fight would use are published beside them as
        ``effective_value`` and ``effective_walking_ft``, with a plain sentence for each, alongside
        ``unarmored_value`` -- what the character would have with no armour and no Shield.

        The starting kit is read from the ledger's own equipment rows, which is where the compiler
        reads it from too; the compiler's equipment-normalization hook only re-keys thrown weapons and
        touches no armour number.  A sheet that records no starting kit publishes nothing here, and the
        fight is unchanged for such a character.
        """
        from combat import armour

        kit = next((row.get("starting_kit") for row in ledger.get("equipment") or []
                    if isinstance(row, dict) and row.get("starting_kit")), None)
        if not isinstance(kit, dict):
            return
        facts = armour.sheet_facts(snapshot, kit)
        statistics = snapshot["ability_scores_and_statistics"]
        statistics["armor_class"].update({
            "effective_value": facts["armor_class"],
            # The real unarmored total, for the "is the armour worth it?" comparison. ``base_value``
            # cannot be shown as "unarmored": it is the chosen calculation before the standing bonuses
            # are folded in, so it is not what the character would have without their armour.
            "unarmored_value": facts["unarmored"],
            "worn": facts["worn"],
            "worn_armor": facts["armor_name"],
            "worn_note": facts["armor_note"],
        })
        statistics["speed"].update({
            "effective_walking_ft": facts["speed_ft"],
            "worn_note": facts["speed_note"],
        })

    def _publish_starting_loadout(self, snapshot: dict[str, Any]) -> None:
        """The Factory/Grow sheet previews the same equipment policy as a new match."""
        if not snapshot.get("equipment"):
            return
        from combat.factory_compiler import compile_character
        bundle = compile_character(snapshot, actor_id="actor:factory.sheet_preview")
        snapshot["starting_loadout"] = deepcopy(bundle["carrying"]["starting_loadout"])

    def _with_starting_loadout(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Add a preview to older cached sheets without rewriting their sealed bytes."""
        if not snapshot.get("equipment") or snapshot.get("starting_loadout"):
            return snapshot
        display = deepcopy(snapshot)
        self._publish_starting_loadout(display)
        return display

    def _build_snapshot(
        self,
        *,
        project: dict[str, Any],
        artifacts: dict[str, dict[str, Any]],
        projection_status: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        ledger = artifacts["Character_Master_Ledger.json"]
        packets = artifacts["Rules_Selection_Packets.json"]
        provenance = artifacts["Projection_Provenance_Map.json"]
        coverage = artifacts["Projection_Coverage_Report.json"]
        projection_diagnostics = artifacts["Projection_Diagnostics.json"]
        if (ledger.get("readiness") or {}).get("advancement") != "ADVANCEMENT_READY":
            raise FoundryError(
                "CHARACTER_SHEET_ADVANCEMENT_NOT_READY",
                "The deterministic advancement projection must be ADVANCEMENT_READY before the owner-facing sheet can be built.",
                details={"readiness": ledger.get("readiness")},
            )
        if projection_diagnostics.get("valid") is not True:
            raise FoundryError("CHARACTER_SHEET_PROJECTION_BLOCKED", "The advancement projection contains blocking diagnostics.")

        contract, contract_sha = self._display_contract(ledger, provenance)
        profile, profile_sha = self._readiness_profile()
        cards, cards_by_id = self._build_record_cards(ledger, packets, contract, contract_sha)
        required_record_ids = self._record_ids_required(ledger, packets)
        groups = self._card_groups(cards)
        character = deepcopy(ledger.get("character") or {})
        core = deepcopy(ledger.get("core_stats") or {})
        background_origin = deepcopy(ledger.get("background_origin") or {})
        owner_locks = self._owner_lock_rows(project)
        owner_lock_values = {
            row.get("field"): row.get("value")
            for row in owner_locks
            if isinstance(row.get("field"), str)
        }
        final_display_name = owner_lock_values.get("character.identity.final_display_name")
        final_concept = owner_lock_values.get("character.identity.final_concept")
        if isinstance(final_display_name, dict):
            final_display_name = final_display_name.get("value")
        if isinstance(final_concept, dict):
            final_concept = final_concept.get("value")
        if isinstance(final_display_name, str) and final_display_name.strip():
            character["name"] = final_display_name.strip()
        if isinstance(final_concept, str) and final_concept.strip():
            character["concept"] = final_concept.strip()

        title = character.get("title")
        title_status = character.get("title_status") or ("SELECTED" if title else "OPTIONAL_OMITTED_BY_OWNER")
        ability_scores = core.get("ability_scores") or {}
        ability_modifiers = core.get("ability_modifiers") or {}
        ability_rows = [
            {"ability": ability, "score": ability_scores.get(ability), "modifier": ability_modifiers.get(ability)}
            for ability in ("STR", "DEX", "CON", "INT", "WIS", "CHA")
        ]
        ac_generation = core.get("ac_generation") or {}
        chosen_ac = next(
            (row for row in ac_generation.get("alternatives_considered") or []
             if row.get("calculation_id") == ac_generation.get("calculation_id")),
            None,
        )
        ac_calculation = (
            f"{chosen_ac['display_name']}: {core.get('ac_base')} base AC. {ac_generation.get('rule', '')}".strip()
            if chosen_ac else
            "See the authenticated armor class calculation trace."
        )
        conditional_ac = "; ".join(
            f"{row.get('display_name') or row['feature_id']}: "
            f"{('+' + str(row['bonus']) + ' AC; ') if row.get('bonus') is not None else ''}"
            f"{row.get('condition') or 'Requires its printed activation and conditions.'}"
            for row in ac_generation.get("conditional_bonus_sources") or []
        ) or "No conditional AC bonus is included in this value."
        background = background_origin.get("background") or {}
        origin = background_origin.get("origin_insight") or {}
        background_card = cards_by_id.get(str(background.get("background_id")))
        origin_card = cards_by_id.get(str(origin.get("origin_insight_id")))
        path_rows = deepcopy(ledger.get("path_selections") or [])
        subpath_rows = deepcopy(ledger.get("subpaths") or [])
        path_cards = [
            cards_by_id[str(row.get("path_id"))]
            for row in path_rows
            if isinstance(row, dict) and row.get("path_id") in cards_by_id
        ]
        path_card = cards_by_id.get(str(character.get("path_id"))) or (path_cards[0] if path_cards else None)
        primary_path_id = str((path_card or {}).get("record_id") or character.get("path_id") or "")
        subpath_cards = [
            cards_by_id[str(row.get("subpath_id"))]
            for row in subpath_rows
            if isinstance(row, dict) and row.get("subpath_id") in cards_by_id
        ]
        primary_subpath_row = next(
            (
                row for row in subpath_rows
                if isinstance(row, dict) and str(row.get("owning_path_id") or "") == primary_path_id
            ),
            None,
        )
        subpath_card = cards_by_id.get(str((primary_subpath_row or {}).get("subpath_id"))) if primary_subpath_row else None
        invalid_subpath_rows = [
            row for row in subpath_rows
            if not isinstance(row, dict)
            or not isinstance(row.get("owning_path_id"), str)
            or not row.get("owning_path_id")
            or row.get("owning_path_id") not in {path.get("path_id") for path in path_rows if isinstance(path, dict)}
        ]
        if invalid_subpath_rows:
            raise FoundryError(
                "CHARACTER_SHEET_SUBPATH_OWNER_UNRESOLVED",
                "A selected Subpath or Tradition lacks one exact selected owning Path.",
                details={"rows": invalid_subpath_rows},
                status_code=409,
            )
        occurrence_rows = contract.get("earned_feature_occurrences") or []
        known_feature_ids = {
            row.get("record_id")
            for row in contract.get("rules") or []
            if isinstance(row, dict) and isinstance(row.get("record_id"), str)
        }
        needs_installed_source = any(
            isinstance(row, dict) and row.get("feature_id") not in known_feature_ids
            for row in occurrence_rows
        )
        earned_feature_occurrences = self._validate_earned_feature_occurrences(
            contract,
            ledger,
            packets,
            provenance,
            path_rows,
            subpath_rows,
            factory_root=(self.projections._factory_root() if needs_installed_source else None),
        )
        method_projection = self._enrich_selected_record_display(
            ledger.get("method"),
            cards_by_id,
            surface="Method",
        )
        foundation_projection = self._enrich_selected_record_display(
            ledger.get("foundation"),
            cards_by_id,
            surface="Foundation",
        )

        canonical_allocations = []
        for packet in sorted(packets.get("packets") or [], key=lambda row: int(row.get("sequence") or 0)):
            canonical_allocations.append({
                "sequence": packet.get("sequence"),
                "target_cl": packet.get("target_cl"),
                "advancement_kind": packet.get("advancement_kind"),
                "record_id": packet.get("record_id"),
                "display_name": packet.get("display_name"),
                "event_id": packet.get("event_id"),
                "event_hash": packet.get("event_hash"),
                "packet_id": packet.get("packet_id"),
                "stage2_rule_id": packet.get("stage2_rule_id"),
            })

        trained_choices = [
            deepcopy(choice)
            for level in (ledger.get("advancement") or {}).get("levels") or []
            for choice in level.get("trained_choices") or []
            if isinstance(choice, dict)
        ]
        advancement_levels = self._levels_with_earned_feature_occurrences(
            (ledger.get("advancement") or {}).get("levels") or [],
            earned_feature_occurrences,
        )

        artifact_hashes = {item["artifact_name"]: item["sha256"] for item in projection_status.get("artifacts") or []}
        sheet_identity_input = {
            "project_id": project["project_id"],
            "project_revision": project["revision"],
            "projection_id": projection_status.get("projection_id"),
            "display_contract_sha256": contract_sha,
            "readiness_profile_sha256": profile_sha,
            "advancement_artifact_hashes": artifact_hashes,
        }
        sheet_id = sha256_json(sheet_identity_input)

        snapshot: dict[str, Any] = {
            "schema_version": "TianxiaFoundry.OwnerCharacterSheet.v1",
            "sheet_id": sheet_id,
            "sheet_role": "deterministic owner-facing projection; not canonical advancement or combat authority",
            "readiness": {
                "advancement": "ADVANCEMENT_READY",
                "character_sheet": "CHARACTER_SHEET_READY",
                "gm_screen": "NOT_ATTEMPTED",
                "combat": "NOT_ATTEMPTED",
            },
            "identity": {
                "display_name": character.get("name"),
                "title": title,
                "title_status": title_status,
                "concept": character.get("concept"),
                "species": character.get("species"),
                "creature_type": character.get("creature_type"),
                "size": character.get("size"),
                "cultivation_level": character.get("cl"),
                "realm": character.get("realm"),
                "realm_display": f"{character.get('realm')} Realm" if character.get("realm") else None,
                "path": character.get("path"),
                "path_id": character.get("path_id"),
                "paths": deepcopy(path_rows),
                "path_ids": [row.get("path_id") for row in path_rows if isinstance(row, dict) and row.get("path_id")],
                "key_ability": character.get("key_ability"),
                "proficiency_bonus": character.get("pb"),
            },
            "ability_scores_and_statistics": {
                "abilities": ability_rows,
                "armor_class": {
                    "value": core.get("ac_active"),
                    "base_value": core.get("ac_base"),
                    "generation": deepcopy(ac_generation),
                    "calculation": ac_calculation,
                    "formula_trace": deepcopy((core.get("ac_generation") or {}).get("trace")),
                    "conditional_note": conditional_ac,
                    "authority": deepcopy((ledger.get("authority_identities") or {}).get("core_baseline_pack")),
                },
                "initiative": {
                    "bonus": core.get("initiative_bonus"),
                    "check": "1d20 + initiative bonus",
                    "ability": "DEX",
                    "formula_trace": deepcopy((core.get("initiative_generation") or {}).get("trace")),
                    "situational_note": "Street-Hardened can grant Advantage under its authenticated trigger; it does not replace the Dexterity formula.",
                    "authority": deepcopy((ledger.get("authority_identities") or {}).get("core_baseline_pack")),
                },
                "speed": {"walking_ft": core.get("speed_ft"), "generation": deepcopy(core.get("speed_generation"))},
                "hit_points": {"maximum": core.get("hp_max"), "build_state_current": core.get("hp_current"), "progression": deepcopy(core.get("hp_generation"))},
                "primary_resource": {
                    "name": core.get("primary_resource_name"),
                    "maximum": core.get("primary_resource_max"),
                    "build_state_current": core.get("primary_resource_current"),
                    "current_state_note": "This is the deterministic build-state value, not mutable GM-session tracking.",
                    "definitions": deepcopy(ledger.get("resources") or []),
                },
                "technique_attack_bonus": core.get("technique_attack_bonus"),
                "technique_save_dc": core.get("save_dc"),
                "skills": self._skills(core),
            },
            "background_and_origin": {
                "background": background,
                "background_record_id": background_card.get("record_id") if background_card else None,
                "origin_insight": origin,
                "origin_record_id": origin_card.get("record_id") if origin_card else None,
                "background_talent_record_id": next(
                    (row.get("talent_id") for row in ledger.get("talents") or [] if row.get("acquisition_type") == "background_talent"),
                    None,
                ),
                "background_talent_separate_from_learned_talents": True,
                "deception_expertise_result": {
                    "selected_skill": "Deception",
                    "result": origin.get("result"),
                    "sources": (core.get("skill_sources") or {}).get("Deception") or [],
                },
            },
            "path_and_subpath": {
                "path": next(
                    (row for row in path_rows if isinstance(row, dict) and row.get("path_id") == primary_path_id),
                    path_rows[0] if path_rows else None,
                ),
                "path_record_id": path_card.get("record_id") if path_card else None,
                "paths": deepcopy(path_rows),
                "path_record_ids": [card["record_id"] for card in path_cards],
                "subpaths": deepcopy(subpath_rows),
                "subpath": primary_subpath_row,
                "subpath_record_id": subpath_card.get("record_id") if subpath_card else None,
                "subpath_record_ids": [card["record_id"] for card in subpath_cards],
                "bindings": [
                    {
                        "path_id": row.get("owning_path_id"),
                        "subpath_id": row.get("subpath_id"),
                        "source_packet_ids": deepcopy(row.get("source_packet_ids") or []),
                    }
                    for row in subpath_rows
                    if isinstance(row, dict)
                ],
                "path_feature_record_ids": [card["record_id"] for card in groups.get("path_features", [])],
                "feature_build_choices": self._creation_feature_choices(
                    project, [card["record_id"] for card in groups.get("path_features", [])]),
                "advancement_feature_record_ids": [card["record_id"] for card in groups.get("advancement_features", [])],
                "source_granted_subpath_feature_record_ids": [
                    row.get("feature_id") for row in ledger.get("features") or [] if row.get("category") == "subpath_feature"
                ],
                "earned_feature_occurrences": earned_feature_occurrences,
                "cinder_touch_record_id": next(
                    (row.get("feature_id") for row in ledger.get("features") or [] if row.get("feature_id") == "tianxia.subpath.qi.cinder_heart_cultivator.feature.cinder_touch"),
                    None,
                ),
            },
            "spheres_and_talents": {
                "sphere_record_ids": [card["record_id"] for card in groups.get("spheres", [])],
                "learned_talent_record_ids": [card["record_id"] for card in groups.get("talents", [])],
                "cultivation_insight_record_ids": [card["record_id"] for card in groups.get("insights", [])],
                "cultivation_insight_occurrences": deepcopy(ledger.get("cultivation_insight_occurrences") or []),
                "automatic_sphere_component_receipts": deepcopy(ledger.get("automatic_sphere_component_receipts") or []),
                "automatic_sphere_components": deepcopy(ledger.get("automatic_sphere_components") or []),
                "trained_choices": trained_choices,
                "automatic_sphere_component_record_ids": sorted({
                    str(row.get("component_id"))
                    for row in ledger.get("automatic_sphere_components") or []
                    if isinstance(row, dict) and row.get("component_id")
                }),
                "background_talent_record_id": next(
                    (row.get("talent_id") for row in ledger.get("talents") or [] if row.get("acquisition_type") == "background_talent"),
                    None,
                ),
            },
            "owner_facing_action_feature_index": [
                {"record_id": card["record_id"], "display_name": card["display_name"], "timing_or_category": card.get("timing_or_category")}
                for card in cards
                if card.get("timing_or_category") in {"Action", "Bonus Action", "Reaction", "Passive", "Feature"}
            ],
            "advancement_history": {
                "event_count": (ledger.get("advancement") or {}).get("event_count"),
                "event_head_hash": (ledger.get("advancement") or {}).get("event_head_hash"),
                "levels": advancement_levels,
                "canonical_allocations": canonical_allocations,
                "owner_choice_locks": [row for row in owner_locks if int(row.get("created_revision") or 0) == 27],
                "all_owner_locks": owner_locks,
                "typed_choice_snapshot": deepcopy(ledger.get("typed_choice_snapshot") or {}),
            },
            "explicit_none_systems": deepcopy(ledger.get("typed_none") or {}),
            # Present only when the causal stream acquired equipment (the
            # constructed starting kit); older sheets keep their exact shape.
            **({"equipment": deepcopy(ledger["equipment"])} if isinstance(ledger.get("equipment"), list) and ledger["equipment"] else {}),
            "forged_techniques": deepcopy(ledger.get("forged_techniques")),
            "recorded_arts": deepcopy(ledger.get("recorded_arts")),
            "immortal_arts": deepcopy(ledger.get("immortal_arts")),
            "training_sources": deepcopy(ledger.get("training_sources") or []),
            "method": method_projection,
            "foundation": foundation_projection,
            "selected_record_sections": groups,
            "selected_record_identity_index": [card["record_id"] for card in cards],
            "capability_status": {
                "summary": {
                    "advancement": "complete",
                    "character_sheet": "complete",
                    "gm_authoring": "pending",
                    "combat_execution": "pending",
                },
                "records": [
                    {
                        "record_id": card["record_id"],
                        "display_name": card["display_name"],
                        "character_sheet": card["capabilities"].get("character_sheet"),
                        "gm_display": card["capabilities"].get("gm_display"),
                        "combat_execution": card["capabilities"].get("combat_execution"),
                        "ai_policy": card["capabilities"].get("ai_policy"),
                        "display_only_not_execution_authority": card["display_only_not_execution_authority"],
                    }
                    for card in cards
                ],
                "pending_execution_surfaces": [
                    "Burn", "Fire Terrain", "typed actions", "typed reactions", "concentration",
                    "movement effects", "damage prevention", "modifiers", "procedures",
                ],
            },
            "later_stage_status": {
                "gm_screen": {
                    "status": "NOT_ATTEMPTED",
                    "next_step": "C2B.2 GM tactical authoring and Factory workspace completion",
                    "pending": deepcopy((ledger.get("later_stage_readiness") or {}).get("gm_screen", {}).get("pending") or []),
                },
                "combat": {
                    "status": "NOT_ATTEMPTED",
                    "pending": deepcopy((ledger.get("later_stage_readiness") or {}).get("combat", {}).get("pending") or []),
                },
            },
            "section_provenance": {
                "identity_and_core": {
                    "owner_lock_ids": [row.get("lock_id") for row in owner_locks if str(row.get("field", "")).startswith("character.")],
                    "core_baseline_authority": deepcopy((ledger.get("authority_identities") or {}).get("core_baseline_pack")),
                    "projection_mappings": [key for key in sorted((provenance.get("mappings") or {})) if key.startswith("/character") or key.startswith("/core_stats")],
                },
                "selected_records": [
                    {
                        "record_id": card["record_id"],
                        "record_hash": card["record_hash"],
                        "source": card["source"],
                        "stage2_rule_id": card["stage2_rule_id"],
                        "source_packet_ids": card["source_packet_ids"],
                        "display_contract_sha256": contract_sha,
                    }
                    for card in cards
                ],
                "advancement": {
                    "event_ids": deepcopy(provenance.get("event_ids") or []),
                    "event_head_hash": provenance.get("event_head_hash"),
                    "projection_input_hash": provenance.get("projection_input_hash"),
                },
                "explicit_none": [
                    {
                        "system": key,
                        "record_id": f"tianxia.c1a.none.{key}",
                        "source_backed": value.get("source_backed"),
                        "reason_code": value.get("reason_code"),
                    }
                    for key, value in sorted((ledger.get("typed_none") or {}).items())
                ],
            },
            "diagnostics": {
                "valid": True,
                "blocking": [],
                "notices": [
                    "GM tactical authoring has not been attempted.",
                    "Combat execution definitions have not been compiled.",
                    "Display descriptions are not executable combat authority unless explicitly marked SUPPORTED.",
                ],
                "advancement_projection": {
                    "projection_status": projection_status.get("status"),
                    "legacy_factory_authoring_input_signal": bool(projection_status.get("eligible_for_command5")),
                    "legacy_signal_is_not_gm_export_readiness": True,
                    "coverage_valid": coverage.get("valid"),
                    "diagnostics_valid": projection_diagnostics.get("valid"),
                },
            },
            "authority_and_artifact_identity": {
                "project_id": project["project_id"],
                "project_revision": project["revision"],
                "event_count": (ledger.get("advancement") or {}).get("event_count"),
                "event_head_hash": projection_status.get("event_head_hash"),
                "content_lock_hash": projection_status.get("content_lock_hash"),
                "typed_choice_snapshot_sha256": (provenance.get("typed_choice_snapshot") or {}).get("snapshot_sha256"),
                "projection_id": projection_status.get("projection_id"),
                "advancement_artifact_hashes": artifact_hashes,
                "display_contract": {
                    "contract_id": contract.get("contract_id"),
                    "version": contract.get("version"),
                    "sha256": contract_sha,
                    "internal_seal_sha256": contract.get("seal_sha256"),
                },
                "readiness_profile": {
                    "profile_id": profile.get("profile_id"),
                    "version": profile.get("version"),
                    "sha256": profile_sha,
                    "internal_seal_sha256": profile.get("seal_sha256"),
                },
                "upstream_authorities": deepcopy(ledger.get("authority_identities") or {}),
            },
        }
        self._publish_worn_armour(snapshot, ledger)
        self._publish_starting_loadout(snapshot)
        self._validate_snapshot(snapshot, required_record_ids, profile)

        output_dir = self._snapshot_dir(project["project_id"], sheet_id)
        output_file = output_dir / _OWNER_SHEET_FILENAME
        expected_text = canonical_json(snapshot) + "\n"
        if output_file.is_file() and output_file.read_text(encoding="utf-8") == expected_text:
            artifact_sha = sha256_file(output_file)
        else:
            staging = output_dir.with_name(output_dir.name + ".staging")
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            staging_file = staging / _OWNER_SHEET_FILENAME
            staging_file.write_text(expected_text, encoding="utf-8", newline="\n")
            artifact_sha = sha256_file(staging_file)
            (staging / f"{_OWNER_SHEET_FILENAME}.sha256").write_text(
                f"{artifact_sha}  {_OWNER_SHEET_FILENAME}\n", encoding="utf-8", newline="\n"
            )
            output_dir.parent.mkdir(parents=True, exist_ok=True)
            if output_dir.exists():
                shutil.rmtree(output_dir)
            staging.replace(output_dir)
        return snapshot, {
            "sheet_id": sheet_id,
            "path": str(output_file),
            "sha256": artifact_sha,
            "bytes": output_file.stat().st_size,
            "display_contract_sha256": contract_sha,
            "readiness_profile_sha256": profile_sha,
        }

    @staticmethod
    def _advancement_history_label(snapshot: dict[str, Any]) -> str:
        levels = (snapshot.get("advancement_history") or {}).get("levels") or []
        verified_levels = sorted({
            row.get("cl")
            for row in levels
            if isinstance(row, dict) and type(row.get("cl")) is int and row.get("cl") > 0
        })
        if not verified_levels:
            return "No advancement history verified"
        first, last = verified_levels[0], verified_levels[-1]
        if verified_levels == list(range(first, last + 1)) and first == 1:
            return f"CL1–CL{last} history verified"
        return f"CL{first}–CL{last} history requires review"

    @staticmethod
    def _compact_sections(snapshot: dict[str, Any] | None) -> dict[str, Any]:
        if not snapshot:
            return {}
        return {
            "identity_core": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("identity")},
            "abilities_statistics": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("ability_scores_and_statistics")},
            "background_origin": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("background_and_origin")},
            "path_subpath": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("path_and_subpath")},
            "spheres_talents": {"status": "ready", "label": "Character Sheet Ready", "data": snapshot.get("spheres_and_talents")},
            "selected_records": {"status": "ready", "label": "Source-backed descriptions and capability badges", "data": snapshot.get("selected_record_sections")},
            "actions_features": {"status": "ready", "label": "Display category index; combat typing remains pending", "data": snapshot.get("owner_facing_action_feature_index")},
            "advancement": {"status": "ready", "label": CharacterSheetService._advancement_history_label(snapshot), "data": snapshot.get("advancement_history")},
            "explicit_none": {"status": "ready", "label": "Authenticated intentional absence", "data": snapshot.get("explicit_none_systems")},
            "capabilities": {"status": "ready", "label": "Readiness and capability status", "data": snapshot.get("capability_status")},
            "diagnostics": {"status": "ready", "label": "No Character Sheet blockers", "data": snapshot.get("diagnostics")},
        }

    def list_characters(self) -> list[dict[str, Any]]:
        rows = []
        for wrapper in self.projects.list_projects():
            project_id = wrapper.get("project_id") or wrapper.get("project", {}).get("project_id")
            if not project_id:
                continue
            rows.append(self.list_row(str(project_id)))
        rows.sort(key=lambda item: (str(item.get("name") or "").casefold(), item["project_id"]))
        return rows

    def list_row(self, project_id: str) -> dict[str, Any]:
        """One Character Sheets list row (a compact sheet); the API caches it per project."""
        sheet = self.sheet(project_id, compact=True)
        # A multi-Path character lists every Path, like in-progress rows do (smoke test 2026-09-25).
        path_names = [row.get("display_name") for row in sheet["identity"].get("paths") or []
                      if isinstance(row, dict) and row.get("display_name")]
        return {
            "project_id": sheet["project_id"],
            "name": sheet["name"],
            "lifecycle": sheet["lifecycle"],
            "build_status": sheet["build_status"],
            "readiness": sheet["readiness"],
            "target_cl": sheet["identity"].get("target_cl"),
            "current_cl": sheet["identity"].get("current_cl"),
            "path": ", ".join(path_names) if len(path_names) > 1 else sheet["identity"].get("path"),
            "updated_at": sheet["updated_at"],
            "can_export_gm": sheet["gm_export"]["available"],
            "path_entries": sheet["path_entries"],
            "path_summary": sheet["path_summary"],
            "plain_summary": sheet["plain_summary"],
        }

    def sheet(self, project_id: str, *, compact: bool = False) -> dict[str, Any]:
        wrapper = self.projects.get_project(project_id)
        project = wrapper["project"]
        lifecycle = wrapper.get("builder_lifecycle") or self.projects.builder_lifecycle(project_id)
        locks = self._user_locks(project)
        blueprint = self._blueprint(project_id)
        artifacts, projection_status = self._compiled_artifacts(project_id)
        factory_workspace = self._factory_workspace_status(project_id, include_candidate=not compact)
        portable_verified = self._portable_verified_status(project_id)
        # A lineage Manual's Recorded Arts live in the frozen project's lock set
        # as a bundle contract, not in the ledger.  Index them once per request,
        # before the snapshot and the complete-character envelope are built, so
        # both the Manual nesting below and the surface overlay see this
        # request's rows.  They are request-local: a shared instance attribute
        # was overwritten by a concurrent /api/characters sweep
        # (list_characters), which runs sheet(compact=True) for every other project.
        recorded_art_rows = self._index_recorded_art_rows(project_id)
        ledger = (artifacts or {}).get("Character_Master_Ledger.json")
        compiled_character = (ledger or {}).get("character") or {}
        compiled_path = compiled_character.get("path")
        compiled_subpaths = (ledger or {}).get("subpaths") or []
        path_from_blueprint = None
        subpath_from_blueprint = None
        if blueprint:
            path_rows = blueprint["selected_records"].get("path_choice") or []
            subpath_rows = blueprint["selected_records"].get("subpath_choice") or []
            path_from_blueprint = (path_rows[0].get("canonical_name") or path_rows[0].get("name")) if path_rows else None
            subpath_from_blueprint = (subpath_rows[0].get("canonical_name") or subpath_rows[0].get("name")) if subpath_rows else None
            subpaths_from_blueprint = [
                {
                    "name": row.get("canonical_name") or row.get("name"),
                    "owning_path_id": row.get("owning_path_id"),
                    "subpath_id": row.get("choice_id"),
                }
                for row in subpath_rows
                if isinstance(row, dict) and (row.get("canonical_name") or row.get("name"))
            ]
        else:
            subpaths_from_blueprint = []

        snapshot: dict[str, Any] | None = None
        display_snapshot: dict[str, Any] | None = None
        sheet_artifact: dict[str, Any] | None = None
        legacy_gm_ready = self._legacy_completed_gm_ready(ledger, projection_status)
        if ledger and (ledger.get("readiness") or {}).get("advancement") == "ADVANCEMENT_READY":
            cached = self._cached_snapshot(
                project_id,
                artifacts=artifacts or {},
                project_revision=project["revision"],
                projection_status=projection_status,
            )
            if cached is None:
                snapshot, sheet_artifact = self._build_snapshot(project=project, artifacts=artifacts or {}, projection_status=projection_status)
            else:
                snapshot, sheet_artifact = cached
            # Owner request 2026-09-13 (plan B3): a cached or sealed snapshot
            # may carry the catalog's first line as a rules text.  The printed
            # rules paragraph is attached to a separate display copy; the sealed
            # snapshot itself is never rewritten, because the GM staging path
            # requires the returned owner_character_sheet to equal the sealed
            # artifact bytes exactly (candidate_gm._sheet_snapshot).
            display_snapshot = self._with_starting_loadout(
                self._with_foundation_method_text(self._with_authenticated_rules_text(snapshot)))

            # Nest each Manual with the Recorded Arts it grants.  This has to happen
            # on the snapshot before the complete-character envelope is built, since
            # the surface mapping reads the nested row through its allowlist.
            if recorded_art_rows:
                by_parent: dict[str, list[dict[str, Any]]] = {}
                for art in recorded_art_rows:
                    parent = art.get("parent_manual_record_id")
                    if isinstance(parent, str) and parent:
                        by_parent.setdefault(parent, []).append(art)
                manuals = (display_snapshot.get("selected_record_sections") or {}).get("manuals")
                if by_parent and isinstance(manuals, list):
                    display_snapshot = deepcopy(display_snapshot)
                    for row in display_snapshot["selected_record_sections"]["manuals"]:
                        if not isinstance(row, dict):
                            continue
                        children = by_parent.get(str(row.get("record_id") or ""))
                        if children:
                            row["recorded_arts"] = deepcopy(children)
            build_status = "CHARACTER_SHEET_READY"
        elif legacy_gm_ready:
            build_status = "GM_READY"
        elif ledger:
            build_status = "ADVANCEMENT_READY"
        elif blueprint:
            build_status = "BLUEPRINT"
        elif lifecycle.get("persistence_state") == "temporary":
            build_status = "TEMPORARY"
        else:
            build_status = "SAVED_DRAFT"

        status_copy = {
            "TEMPORARY": "Temporary character intake. Save Draft to retain it.",
            "SAVED_DRAFT": "Saved draft. The character has not completed Stage 1 yet.",
            "BLUEPRINT": "Character plan accepted and saved. Advancement compilation is still required.",
            "ADVANCEMENT_READY": "Advancement is deterministic and ready. The owner-facing Character Sheet is not complete yet.",
            "CHARACTER_SHEET_READY": (
                "Character Sheet Ready. Project-derived GM guidance is provisional; actual model authorship, source binding, "
                "and owner ratification remain required before Command 5. GM export remains unavailable."
                if factory_workspace.get("gm_authoring") == "PROVISIONAL_GM_GUIDANCE_ONLY"
                else "Character Sheet Ready. Actual GM authoring is bound, but the separately authorized Command 5 checkpoint remains pending."
                if factory_workspace.get("gm_authoring") == "ACTUAL_GM_AUTHORING"
                else "Character Sheet Ready. GM tactical authoring and the Factory Command 1–4 input workspace are complete; "
                "GM Screen verification remains unattempted."
                if factory_workspace.get("status") == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
                else "Character Sheet Ready. GM tactical authoring is the next step; GM export remains unavailable."
            ),
            "GM_READY": "Historical completed character is GM-ready under its validated legacy contract.",
        }[build_status]

        if snapshot:
            snap_identity = snapshot["identity"]
            identity = {
                "name": snap_identity.get("display_name"),
                "title": snap_identity.get("title"),
                "title_status": snap_identity.get("title_status"),
                "concept": snap_identity.get("concept"),
                "target_cl": locks.get("target_cl"),
                "current_cl": snap_identity.get("cultivation_level"),
                "target_realm": locks.get("target_realm"),
                "current_realm": snap_identity.get("realm"),
                "path": snap_identity.get("path"),
                "subpath": ((snapshot.get("path_and_subpath") or {}).get("subpath") or {}).get("name"),
                "paths": deepcopy((snapshot.get("path_and_subpath") or {}).get("paths") or []),
                "subpaths": deepcopy((snapshot.get("path_and_subpath") or {}).get("subpaths") or []),
                "subpath_bindings": deepcopy((snapshot.get("path_and_subpath") or {}).get("bindings") or []),
                "species": snap_identity.get("species"),
                "creature_type": snap_identity.get("creature_type"),
                "size": snap_identity.get("size"),
                "key_ability": snap_identity.get("key_ability"),
            }
            readiness = deepcopy(snapshot["readiness"])
        else:
            final_display_name = locks.get("character.identity.final_display_name")
            final_concept = locks.get("character.identity.final_concept")
            if isinstance(final_display_name, dict):
                final_display_name = final_display_name.get("value")
            if isinstance(final_concept, dict):
                final_concept = final_concept.get("value")
            identity = {
                "name": compiled_character.get("name") or final_display_name or project.get("name"),
                "title": compiled_character.get("title"),
                "concept": compiled_character.get("concept") or final_concept or locks.get("concept"),
                "target_cl": locks.get("target_cl"),
                "current_cl": compiled_character.get("cl"),
                "target_realm": locks.get("target_realm"),
                "current_realm": compiled_character.get("realm"),
                "path": compiled_path or path_from_blueprint,
                "subpath": ((compiled_subpaths[0].get("name") if isinstance(compiled_subpaths[0], dict) else compiled_subpaths[0]) if compiled_subpaths else subpath_from_blueprint),
                "paths": [
                    row.get("name") if isinstance(row, dict) else row
                    for row in ((ledger or {}).get("path_selections") or [])
                ],
                "subpaths": [
                    row.get("name") if isinstance(row, dict) else row
                    for row in compiled_subpaths
                ] if compiled_subpaths else [
                    row.get("name") for row in subpaths_from_blueprint if row.get("name")
                ],
                "subpath_bindings": deepcopy(
                    ((ledger or {}).get("subpaths") or [])
                    if compiled_subpaths
                    else subpaths_from_blueprint
                ),
                "species": compiled_character.get("species"),
                "key_ability": compiled_character.get("key_ability"),
            }
            readiness = {
                "advancement": "ADVANCEMENT_READY" if ledger else "NOT_ATTEMPTED",
                "character_sheet": "NOT_ATTEMPTED",
                "gm_screen": "GM_READY" if legacy_gm_ready else "NOT_ATTEMPTED",
                "combat": "NOT_ATTEMPTED",
            }

        # Compact list responses deliberately stop before loading any candidate
        # mechanics archive.  Portable verification remains an independent
        # readiness source for both compact and full responses; the complete
        # envelope may select it only after its candidate gate succeeds.
        complete_character = None
        # The Recorded Arts were indexed into the request-local
        # ``recorded_art_rows`` at the top of this method (before the snapshot
        # and the complete-character envelope); nothing is stored on ``self``.
        if not compact:
            # The locked Insight records carry the printed text.  Index them from
            # the sealed snapshot BEFORE the complete-character envelope is
            # built, because that envelope is where the insight surface rows are
            # enriched -- populating this afterwards had no effect.  The lookup is
            # request-local: a shared instance attribute was overwritten by a
            # concurrent non-compact sheet() for another project.
            insight_text_lookup = self._index_insight_text_lookup(snapshot)
            complete_character, portable_verified = self._complete_character_with_portable(
                project_id,
                projection_status,
                portable_verified=portable_verified,
                recorded_art_rows=recorded_art_rows,
                insight_text_lookup=insight_text_lookup,
            )
        source_consumer_verified = bool(portable_verified and portable_verified.get("status") == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED")
        gm_available = source_consumer_verified or legacy_gm_ready or (
            projection_status.get("command5_status") == "COMMAND_5_GM_SCREEN_CANDIDATE_READY"
            and projection_status.get("command6_status") == "SIMULATED_CONSUMER_PASS_REAL_GMSCREEN_ACCEPTANCE_REQUIRED"
        )
        if source_consumer_verified:
            readiness["gm_screen"] = "GM_READY_SOURCE_VERIFIED"
            readiness["combat"] = "NOT_ATTEMPTED"
            status_copy = "Character Sheet Ready. GM model built, exact bundled GM Screen source consumer verified, and Character ZIP ready. Native owner acceptance and combat execution remain pending."
        if gm_available:
            gm_blockers = []
        elif not ledger:
            gm_blockers = [
                "The mechanical projection has not been compiled yet.",
                "GM tactical authoring and verified GM model compilation have not been completed.",
            ]
        else:
            if factory_workspace.get("gm_authoring") == "PROVISIONAL_GM_GUIDANCE_ONLY":
                gm_blockers = [
                    "The Factory workspace contains provisional project-derived GM guidance only; it is not actual model authorship.",
                    "Bind actual model-authored Dao and I Ching guidance to acquired source records and obtain owner ratification before Command 5.",
                ]
            elif factory_workspace.get("gm_authoring") == "ACTUAL_GM_AUTHORING" and not factory_workspace.get("eligible_for_later_command5_checkpoint"):
                gm_blockers = [
                    "Actual model-authored GM guidance is bound, but owner ratification has not been recorded.",
                    "Command 5 remains blocked until the owner-ratification gate is satisfied.",
                ]
            elif factory_workspace.get("command5") == "GM_MODEL_CANDIDATE_READY":
                gm_blockers = [
                    "GM tactical authoring is complete, and the Character/GM Command 5 candidate and schema-valid GM model candidate are complete.",
                    "GM Screen consumer verification has not been attempted, so export remains unavailable.",
                ]
            elif factory_workspace.get("status") == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE":
                gm_blockers = [
                    "GM tactical authoring and the Factory Command 1–4 input workspace are complete, but Command 5 and Command 6 have not been run.",
                    "The final GM Screen model and consumer verification do not exist yet.",
                ]
            else:
                gm_blockers = [
                    "GM tactical authoring and verified GM model compilation have not been completed.",
                    "Advancement projection eligibility is only a legacy Factory-authoring input signal, not GM export readiness.",
                ]

        # Combat remains a separate, explicitly bounded contract.  Expose the
        # source-backed not-claimed/setup state so production release equality
        # cannot mistake an omitted field for a matching value.  A verified
        # portable runtime may override these fields only with values already
        # present in its authenticated package pointer.
        verified_combat = portable_verified if isinstance(portable_verified, dict) else {}
        combat_readiness = {
            "schema_version": "TianxiaFoundry.OwnerCharacterSheetCombatReadiness.v1",
            "combat": readiness.get("combat"),
            "combat_execution": verified_combat["combat_execution"] if "combat_execution" in verified_combat else "NOT_ATTEMPTED",
            "combat_runtime": verified_combat["combat_runtime"] if "combat_runtime" in verified_combat else "NOT_CLAIMED",
            "combat_sheet": verified_combat["combat_sheet"] if "combat_sheet" in verified_combat else "NOT_CLAIMED",
            "combat_ready_semantics": verified_combat["combat_ready_semantics"] if "combat_ready_semantics" in verified_combat else "NOT_CLAIMED",
            "encounter": verified_combat["encounter"] if "encounter" in verified_combat else "NOT_ATTEMPTED",
            "controller_selection": verified_combat["controller_selection"] if "controller_selection" in verified_combat else "NOT_ATTEMPTED",
            "encounter_setup_required": verified_combat["encounter_setup_required"] if "encounter_setup_required" in verified_combat else True,
            "current_resource_requirements": verified_combat["current_resource_requirements"] if "current_resource_requirements" in verified_combat else {"current_qi_required": False, "current_martial_focus_required": False},
            "current_qi_required": verified_combat["current_qi_required"] if "current_qi_required" in verified_combat else False,
            "current_martial_focus_required": verified_combat["current_martial_focus_required"] if "current_martial_focus_required" in verified_combat else False,
            "opponent_team_completion_required": verified_combat["opponent_team_completion_required"] if "opponent_team_completion_required" in verified_combat else True,
            "battlefield_choice": verified_combat["battlefield_choice"] if "battlefield_choice" in verified_combat else "NOT_ATTEMPTED",
            "battlefield_owner_choice_committed": verified_combat["battlefield_owner_choice_committed"] if "battlefield_owner_choice_committed" in verified_combat else False,
            "token_placement": verified_combat["token_placement"] if "token_placement" in verified_combat else "NOT_ATTEMPTED",
            "token_placement_committed": verified_combat["token_placement_committed"] if "token_placement_committed" in verified_combat else False,
            "initiative": verified_combat["initiative"] if "initiative" in verified_combat else "NOT_ATTEMPTED",
            "initiative_attempted": verified_combat["initiative_attempted"] if "initiative_attempted" in verified_combat else False,
        }

        if not isinstance(display_snapshot, dict):
            display_snapshot = snapshot
        talent_record_ids = (
            ((snapshot or {}).get("spheres_and_talents") or {}).get("learned_talent_record_ids")
            if isinstance(snapshot, dict)
            else []
        )
        result = {
            "schema_version": "TianxiaFoundry.OwnerCharacterSheetServiceResponse.v2",
            "project_id": project_id,
            # Display label only: which Sphere each learned Talent belongs to.
            # The sheet's own talent rows carry no Sphere link.
            "talent_sphere_names": self._talent_sphere_names(talent_record_ids),
            # Display and guidance: the character's Dao combined from its
            # Spheres (factory_authoring.sphere_dao); never mechanical authority.
            "character_dao": self._character_dao(snapshot),
            "name": identity["name"],
            "updated_at": project.get("updated_at"),
            "lifecycle": lifecycle,
            "build_status": build_status,
            "readiness": readiness,
            "combat_readiness": combat_readiness,
            "plain_summary": status_copy,
            "identity": identity,
            "sheet_artifact": sheet_artifact,
            # Sealed, artifact-identical snapshot: never enriched, so callers
            # that check it against the artifact bytes keep working.
            "owner_character_sheet": None if compact else snapshot,
            **path_display(snapshot or {}),
            # Display-only copy carrying the printed rules text.  Readers pick
            # this up when present and fall back to the sealed snapshot.
            "display_owner_character_sheet": None if compact else display_snapshot,
            "provenance": {
                "owner_locks": {"status": "available", "label": "Chosen by owner", "data": locks},
                "ai_blueprint": {"status": "available" if blueprint else "not_available", "label": "Accepted character plan" if blueprint else "Not accepted yet", "data": blueprint},
                "advancement_projection": {
                    "status": "available" if ledger else "not_compiled",
                    "label": "Advancement Ready" if ledger else "Not compiled yet",
                    "projection": projection_status,
                    "legacy_factory_authoring_input_signal": bool(projection_status.get("eligible_for_command5")),
                    "not_a_gm_export_gate": True,
                },
                "mechanical_projection": {
                    "status": "available" if ledger else "not_compiled",
                    "label": "Advancement Ready" if ledger else "Not compiled yet",
                    "projection": projection_status,
                    "deprecated_alias_for": "advancement_projection",
                },
                "character_sheet_projection": {
                    "status": "available" if snapshot else "not_compiled",
                    "label": "Character Sheet Ready" if snapshot else "Not compiled yet",
                    "artifact": sheet_artifact,
                },
            },
            "sections": {} if compact else self._compact_sections(snapshot),
            "factory_workspace": factory_workspace,
            "gm_export": {
                "available": gm_available,
                "label": "Export Character ZIP for GM Screen",
                "blockers": gm_blockers,
                "readiness": "GM_READY_SOURCE_VERIFIED" if source_consumer_verified else ("GM_READY" if legacy_gm_ready else "NOT_ATTEMPTED"),
                "source_consumer_verified": source_consumer_verified,
                "native_or_interactive_acceptance": (portable_verified or {}).get("native_or_interactive_acceptance", "NOT_RUN") if source_consumer_verified else "NOT_RUN",
                "combat": (portable_verified or {}).get("combat", "NOT_ATTEMPTED") if source_consumer_verified else "NOT_ATTEMPTED",
                "next_step": (
                    None
                    if gm_available
                    else "Complete explicit GM model authorship, source-artifact binding, and owner ratification before the separately authorized Command 5 checkpoint."
                    if factory_workspace.get("gm_authoring") == "PROVISIONAL_GM_GUIDANCE_ONLY"
                    else "Obtain owner ratification for the bound GM authoring artifact before the separately authorized Command 5 checkpoint."
                    if factory_workspace.get("gm_authoring") == "ACTUAL_GM_AUTHORING" and not factory_workspace.get("eligible_for_later_command5_checkpoint")
                    else "Proceed to the separately authorized Command 6 consumer-verification and portable-package checkpoint."
                    if factory_workspace.get("command5") == "GM_MODEL_CANDIDATE_READY"
                    else "Proceed to the separately authorized Command 5 candidate checkpoint."
                    if factory_workspace.get("status") == "FACTORY_COMMAND_1_TO_4_WORKSPACE_COMPLETE"
                    else "Complete C2B.2 GM tactical authoring and the existing Factory workspace lifecycle."
                ),
            },
            "advanced_details": {
                "projection_status": projection_status,
                "legacy_eligible_for_command5": bool(projection_status.get("eligible_for_command5")),
                "legacy_completed_gm_compatibility": legacy_gm_ready,
                "portable_character_verification": portable_verified,
            },
        }
        if not compact:
            result["complete_character"] = complete_character
        return result
