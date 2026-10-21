"""Shipped inputs for retained native catalog/builder acceptance.

Explicit paths let the public snapshot follow the registry\'s dynamically selected
schemas and catalog rebuild sources. Actual fixtures still load and validate them.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_RESOURCES = (
    ROOT / "character_creation/authority/Tool_Proficiency_Registry_v1.json",
    ROOT / "catalog_authority/cat3/source/INSIGHT_TYPE_MAPPING.json",
    ROOT / "catalog_authority/cat3/source/INSIGHT_GROUPING_INVENTORY.json",
    ROOT / "catalog_authority/cat3/source/SUPERSESSION_AND_COLLISION_LEDGER.json",
    ROOT / "catalog_authority/cat3/source/SPHERE_BASE_ABILITY_MATRIX.csv",
    ROOT / "catalog_authority/cat3/source/Tianxia_Central_Cultivation_Insights_AI_Reference_R5_Legacy_Restored.json",
    ROOT / "schemas/AI_Stage_Response.schema.json",
    ROOT / "schemas/Advancement_Event.schema.json",
    ROOT / "schemas/Advancement_Event_v2.schema.json",
    ROOT / "schemas/Advancement_Event_v3.schema.json",
    ROOT / "schemas/Blueprint_Decision.schema.json",
    ROOT / "schemas/Blueprint_Decision_Batch.schema.json",
    ROOT / "schemas/Blueprint_Intent_State.schema.json",
    ROOT / "schemas/Character_Project.schema.json",
    ROOT / "schemas/Content_Pack_Manifest.schema.json",
    ROOT / "schemas/Content_Pack_Signature.schema.json",
    ROOT / "schemas/Cultivation_Insight_Stage2_Authority_v1.schema.json",
    ROOT / "schemas/Foundation_Replacement_Map.schema.json",
    ROOT / "schemas/Leveling_Ledger_v1.schema.json",
    ROOT / "schemas/Leveling_Ledger_v2.schema.json",
    ROOT / "schemas/Project_Scoped_Forged_Technique.schema.json",
    ROOT / "schemas/Rules_Catalog_Record.schema.json",
    ROOT / "schemas/Service_API_Contracts.schema.json",
    ROOT / "schemas/Service_Error.schema.json",
    ROOT / "schemas/Sphere_Automatic_Component_Authority_v1.schema.json",
    ROOT / "schemas/Stage1_Clipboard_Exchange.schema.json",
    ROOT / "schemas/Stage1_Clipboard_Exchange_v2.schema.json",
    ROOT / "schemas/Stage1_Clipboard_Response.schema.json",
    ROOT / "schemas/Stage1_Clipboard_Response_v2.schema.json",
    ROOT / "schemas/Stage1_Prompt_Envelope.schema.json",
    ROOT / "schemas/Stage1_Prompt_Envelope_v2.schema.json",
    ROOT / "schemas/Stage2_Advancement_Proposal.schema.json",
    ROOT / "schemas/Stage2_Advancement_Proposal_v2.schema.json",
    ROOT / "schemas/Stage2_Blocker_Report.schema.json",
    ROOT / "schemas/Stage2_Field_Provenance_Map.schema.json",
    ROOT / "schemas/Stage2_Reconciliation_Report.schema.json",
    ROOT / "schemas/Stage2_Safe_Formula.schema.json",
    ROOT / "schemas/Stage2_Training_Transaction.schema.json",
    ROOT / "schemas/Stage2_Training_Transaction_v1.schema.json",
)
