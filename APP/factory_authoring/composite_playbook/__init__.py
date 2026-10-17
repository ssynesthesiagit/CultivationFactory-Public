"""Standalone, data-driven Composite Playbook validator.

Layout
------
``schemas/``    vendor JSON Schemas (byte-identical copies; see ``schemas/PROVENANCE.md``)
``rules/``      JSON rule data (buckets, capacities, limits, enabled rule codes)
``rules.py``    ``RuleSet`` / ``load_rules`` — data loading and validation only
``registry.py`` ``ActionRegistry`` / ``ActionRecord`` — action-data adapters
``sheet_adapter.py`` sealed owner-sheet records -> ``ActionRegistry`` + resource pools
``templates.py`` ``TemplateSet`` / ``load_templates`` — playbook shapes from ``rules/playbook_templates.v1.json``
- hooks.py -- Dao / I Ching hooks from Aspect keyword evidence, real costs and the sheet's authored themes.
- rules/dao_aspects.v1.json -- the 17 active Dao Aspects with their keyword tags.
``proposer.py`` deterministic template filler -> validated vendor-shaped rows (``propose_playbooks`` / ``propose_from_sheet``)
``validator.py`` ``RULES``, the rule functions and ``validate_playbook``
"""

from __future__ import annotations

from .hooks import Aspect, AspectTable, DEFAULT_ASPECTS_PATH, Themes, aspect_hits, build_dao_hook, build_i_ching_hook, load_aspects, themes_from_surface
from .registry import ActionRecord, ActionRegistry
from .rules import DEFAULT_RULES_PATH, SCHEMA_DIR, RuleSet, load_rules
from .sheet_adapter import forged_technique_rows, forged_technique_to_action, load_base_actions, primary_resource_pool, registry_from_sheet, sheet_record_to_action
from .templates import DEFAULT_TEMPLATES_PATH, Slot, Template, TemplateSet, load_templates
from .proposer import ProposalResult, propose_from_sheet, propose_playbooks
from .validator import (
    RULES,
    Diagnostic,
    ValidationContext,
    ValidationReport,
    validate_playbook,
    validate_playbook_document,
)

__all__ = [
    "load_rules", "RuleSet", "ActionRecord", "ActionRegistry", "SCHEMA_DIR", "DEFAULT_RULES_PATH",
    "RULES", "Diagnostic", "ValidationContext", "ValidationReport",
    "validate_playbook", "validate_playbook_document",
    "registry_from_sheet", "sheet_record_to_action", "load_base_actions", "primary_resource_pool",
    "load_templates", "TemplateSet", "Template", "Slot", "DEFAULT_TEMPLATES_PATH",
    "propose_playbooks", "propose_from_sheet", "ProposalResult",
    "Aspect", "AspectTable", "DEFAULT_ASPECTS_PATH", "Themes", "aspect_hits", "build_dao_hook",
    "build_i_ching_hook", "load_aspects", "themes_from_surface",
    "forged_technique_rows", "forged_technique_to_action",
]
