from __future__ import annotations

CANDIDATE_STATUS = "CANDIDATE_NON_AUTHORITATIVE"
TOOL_SCHEMA_VERSION = "TianxiaContentPackValidatorReport.v1"

CAPABILITY_NAMES = (
    "advancement",
    "character_sheet",
    "gm_display",
    "combat_execution",
    "ai_policy",
)

CAPABILITY_STATES = (
    "SUPPORTED",
    "PARTIAL",
    "UNSUPPORTED",
    "NOT_APPLICABLE",
    "STALE",
    "BLOCKED_BY_DEPENDENCY",
)

KNOWN_SCHEMA_VERSIONS = {
    "manifest": {"TianxiaContentPackCandidate.Manifest.v1"},
    "records": {"TianxiaContentPackCandidate.Definitions.v1"},
    "advancement": {"TianxiaContentPackCandidate.AdvancementRules.v1"},
    "character_sheet": {"TianxiaContentPackCandidate.CharacterSheetRules.v1"},
    "gm_display": {"TianxiaContentPackCandidate.GMDisplayRules.v1"},
    "combat": {"TianxiaContentPackCandidate.CombatDefinitions.v1"},
    "creatures": {"TianxiaContentPackCandidate.CreatureDefinitions.v1"},
    "policies": {"TianxiaContentPackCandidate.ControllerPolicies.v1"},
    "tests": {"TianxiaContentPackCandidate.ValidationCases.v1"},
    "primitive_registry": {"TianxiaContentPackCandidate.PrimitiveRegistry.v1"},
}

DEFAULT_CONTENT_FILES = {
    "records": "records/definitions.json",
    "advancement": "authority/advancement_rules.json",
    "character_sheet": "projection/character_sheet_rules.json",
    "gm_display": "projection/gm_display_rules.json",
    "combat": "execution/combat_definitions.json",
    "creatures": "creatures/creature_definitions.json",
    "policies": "policies/controller_policies.json",
    "tests": "tests/validation_cases.json",
}

EXECUTABLE_SUFFIXES = {
    ".py",
    ".pyc",
    ".pyo",
    ".js",
    ".mjs",
    ".cjs",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".psm1",
    ".bat",
    ".cmd",
    ".com",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".jar",
    ".class",
    ".wasm",
    ".vbs",
    ".vbe",
    ".wsf",
    ".scr",
    ".msi",
    ".app",
}

MACRO_SUFFIXES = {".docm", ".dotm", ".xlsm", ".xltm", ".pptm", ".potm", ".ppam"}

FORBIDDEN_RUNTIME_KEYS = {
    "post_install",
    "post_install_script",
    "activation_script",
    "install_script",
    "entrypoint",
    "runtime_module",
    "module_reference",
    "dynamic_import",
    "import_module",
    "python_module",
    "javascript_module",
    "shell_command",
    "powershell_command",
}

FORBIDDEN_RUNTIME_PREFIXES = (
    "python:",
    "javascript:",
    "js:",
    "shell:",
    "powershell:",
    "cmd:",
    "module:",
    "import:",
)

RECORD_ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$"
PACK_ID_PATTERN = RECORD_ID_PATTERN
PRIMITIVE_ID_PATTERN = RECORD_ID_PATTERN
SHA256_PATTERN = r"^[0-9a-f]{64}$"
SEMVER_PATTERN = r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"

REPORT_FILENAMES = (
    "validation_report.json",
    "validation_report.txt",
    "record_capability_matrix.json",
    "dependency_graph.json",
    "unsupported_primitives.json",
    "source_binding_report.json",
    "checksum_inventory.json",
    "verdict.json",
)
