"""Pinned first-delivery rules. Text is data; only registered handlers execute."""
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from .models import require
from .trusted_producer import (
    AUTHORITY_PACK_PATH,
    AUTHORITY_PACK_SHA256,
    LEVEL0_EXPORTER_SOURCE_SHA256,
    PORTABLE_AUDIT_SOURCE_SHA256,
    PRODUCER_SOURCE_MANIFEST,
    _manifest_digest as producer_manifest_digest,
)


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=False, allow_nan=False).encode()).hexdigest()


SOURCES = {
    "CORE": {"version": "0.2C", "file": "GM Guide/Tianxia_Core_Rules_Reference_v0_2C.md",
             "sha256": "07dc678e2c686e191f7da34b959964cfe535c6368019ffaf37227eb39d87ad10"},
    "CH03": {"version": "R2", "file": "01_PHB/Tianxia_PHB_Chapter_03_Paths_and_Shared_Path_Rules_R2.md",
             "sha256": "f29ad8393ad49b03062580424451227705d0980effa8741ad06b8375a9a80698"},
    "PHB": {"version": "0.7", "file": "01_PHB/Tianxia_PHB_Manuscript_v0_7_Subpaths_Inserted.md",
            "sha256": "f2bb2eeba55a4b8b8630e02fbcb35d21ac80d2efb7ad4a9e91642522f82d7fe7"},
    "GM": {"version": "0.1", "file": "GM Guide/Tianxia_GM_Guide_v0_1_Polished_Manuscript.md",
           "sha256": "ab83a99b1d516db26af87ee997cec45efa482ac52c3e627042eacc3ee25f6713",
           "authority": "guidance_only"},
    "DND2024": {"version": "2024", "url": "https://www.dndbeyond.com/sources/dnd/br-2024/rules-glossary",
                "sha256": "d45a0acabe1ed9c5aa1bd9e346c269a5af2b0cfbb2f13da17cef1b2ae1d693c9",
                "hash_kind": "retrieved_html", "retrieved": "2026-09-08"},
    "EQUIPMENT2024": {"version": "2024", "url": "https://www.dndbeyond.com/sources/dnd/br-2024/equipment",
                      "sha256": "2db80ff584a2caefdc6f4578885d167129ce5879c6fea20947e3788773b26ce4",
                      "hash_kind": "retrieved_html", "retrieved": "2026-09-08"},
}

# The adapter consumes the producer's sealed-package audit result and verifies
# the bytes again before deriving gameplay state.  This identity is a declared
# external dependency, not a runtime import of the private creator checkout.
ADMISSION_DEPENDENCIES = {
    "portable_character_audit": {
        "id": "PortableCharacterPackageService.audit",
        "schema": "TianxiaFoundry.PortableCharacterPackage.v1",
        "source_path": "APP/portable_character/service.py",
        "source_sha256": PORTABLE_AUDIT_SOURCE_SHA256,
        "contract": "ZIP safety, CRC, exact SHA256SUMS member bytes, nested project identity, choice snapshot and GM model schema",
    },
    "mortal_level0_exporter": {
        "id": "TianxiaFoundry.MortalLevel0PackageService",
        "schema": "TianxiaFoundry.MortalLevel0Export.v1",
        "source_path": "APP/portable_character/level0.py",
        "source_sha256": LEVEL0_EXPORTER_SOURCE_SHA256,
        "contract": "Published Background/Origin records, six abilities, 6+CON HP, one d6, hidden zero Paths, empty resources, complete portable package",
    },
    "portable_producer_closure": {
        "schema": "factory-gameplay.portable-producer-source-manifest.v1",
        "source_manifest": PRODUCER_SOURCE_MANIFEST,
        "source_manifest_sha256": producer_manifest_digest(PRODUCER_SOURCE_MANIFEST),
        "authority_pack": {
            "path": f"APP/{AUTHORITY_PACK_PATH}",
            "sha256": AUTHORITY_PACK_SHA256,
        },
        "loader": "fresh-isolated-python-worker",
        "contract": "Every executable APP module imported by the producer audit/export route is hash-bound; the expected authority-pack digest is fixed in the trusted bridge; a fresh worker reruns the mortal validators and exporter and compares the complete derived authority before admission.",
    },
}

# This profile keeps the historical gameplay id for compatibility while making
# the current creator/exporter binding explicit and versioned.  A new opening
# campaign always records this binding in its profile digest.
CURRENT_PRODUCER_PROFILE = {
    "id": "factory-current-creator-level0",
    "version": 1,
    "source_manifest_sha256": producer_manifest_digest(PRODUCER_SOURCE_MANIFEST),
    "portable_audit_source_sha256": PORTABLE_AUDIT_SOURCE_SHA256,
    "level0_exporter_source_sha256": LEVEL0_EXPORTER_SOURCE_SHA256,
}

# Reuse the RAW registry vocabulary without importing its unrelated creation
# authority or claiming its 180 records are executable gameplay. RAW-128 is a
# related record; its Powering Path ruling does not implement recovery.
def rule(key, source, locator, scope, trigger, facts, preconditions, costs, effects,
         stacking="independent application identities", expiry="explicit", removal="explicit"):
    return {
        "id": key, "version": 1, "status": "verified", "authority_status": "admitted",
        "citations": [{"source_id": source, "source_hash": SOURCES[source]["sha256"],
                       "locator": locator}],
        "scope": scope, "trigger": trigger, "required_facts": facts,
        "preconditions": preconditions, "costs": costs, "check_save": None,
        "effects": effects, "effective_statement": effects, "stacking": stacking,
        "duration_expiry": expiry, "removal_recovery": removal, "ruling": None,
        "open_question_ids": [], "handler": {"id": "gameplay." + key, "version": 1},
        "source_tests": ["test_gameplay_rules.py"],
        "coverage": ["source_located", "mapped", "implemented"],
    }


RULES = [
    rule("short_rest", "DND2024", "Short Rest", "rest.short", "3600 observed seconds",
         ["starting_hp", "activity_mode"], ["hp >= 1", "uninterrupted light activity"], [],
         "Open optional individual Hit Die recovery; trigger admitted Path recovery."),
    rule("hit_die", "DND2024", "Short Rest / Hit Point Dice", "healing.hit_die",
         "individual election", ["typed_pool", "CON", "recorded_roll"],
         ["qualified recovery window", "remaining die"], ["one die from selected pool"],
         "Heal max(1, roll + CON modifier), capped at effective HP maximum."),
    rule("long_rest", "DND2024", "Long Rest", "rest.long", "28800 observed seconds",
         ["sleep_seconds", "light_seconds", "last_long_rest"],
         ["start hp >= 1", "21600 sleep seconds", "at most 7200 light seconds",
          "57600 seconds since last completion before start"], [],
         "Restore HP, all spent dice, ordinary reductions, one recoverable Exhaustion level; reset Path counters."),
    rule("path_recovery", "CH03", "Recovery by Path", "resources.path", "qualified rest",
         ["Path kind", "Path CL", "authoritative maximum"], ["per-Path counters"], [],
         "Body: half maximum twice on short, all on long. Qi/Spirit: Path CL once on short, half maximum on long; floor fractions."),
    rule("cultivation", "CH03", "Recovery by Path", "resources.cultivation",
         "7200 uninterrupted practice seconds", ["safe location", "admitted practice per Path"],
         ["appropriate practice and condition", "light practice for combined rest"], [],
         "Full refill once per Path between Long Rests. No HP, dice, AP, training or breakthrough."),
    rule("poisoned", "DND2024", "Poisoned", "conditions.poisoned", "admitted application",
         ["application source", "target"], [], [],
         "Attack and ability-check disadvantage; no saving-throw or healing-die disadvantage."),
    rule("exhaustion", "DND2024", "Exhaustion", "conditions.exhaustion", "admitted application",
         ["application source", "target", "levels"], ["levels 1..6 per application"], [],
         "D20 modifier -2 per level; speed -5 feet per level; persistent death at six total.",
         removal="Long Rest removes one recoverable level total."),
    rule("malnutrition", "DND2024", "Malnutrition", "conditions.exhaustion.recovery",
         "admitted malnutrition Exhaustion", ["application source", "target"], [], [],
         "This source's Exhaustion blocks Long Rest removal until nutrition is satisfied.",
         removal="Explicit GM-admitted removal; automated nutrition qualification unsupported."),
    rule("reduction", "DND2024", "Long Rest / Benefits", "reductions.recovery",
         "admitted stat reduction", ["target", "stat", "amount"], ["effective stat remains >= 1"], [],
         "Restore ordinary ability and HP maximum reductions on Long Rest."),
    rule("potion", "EQUIPMENT2024", "Potion of Healing", "items.healing",
         "drink owned potion", ["instance", "quantity", "recorded 2d4"],
         ["alive", "owned", "quantity > 0"], ["one potion"],
         "Heal 2d4+2 capped at effective HP maximum; no condition or Hit Die recovery."),
    rule("items", "EQUIPMENT2024", "Adventuring Gear", "items.ownership",
         "take or drop instance", ["location", "owner", "visibility"], ["available to actor"], [],
         "Transfer one existing identity without duplication."),
]

EFFECTS = {
    "poison": {"rule_id": "poisoned", "kind": "poisoned", "long_rest_recovery": False},
    "exhaustion": {"rule_id": "exhaustion", "kind": "exhaustion", "long_rest_recovery": True},
    "malnutrition": {"rule_id": "malnutrition", "kind": "exhaustion", "long_rest_recovery": False},
    "ordinary_reduction": {"rule_id": "reduction", "ends_on_long_rest": True},
}

COMMAND_RULES = {
    "start_activity": ["short_rest", "long_rest", "cultivation"],
    "cancel_activity": ["short_rest", "long_rest", "cultivation"],
    "advance_time": ["short_rest", "long_rest", "path_recovery", "cultivation", "poisoned", "exhaustion", "reduction"],
    "spend_hit_die": ["hit_die"], "finish_recovery": ["hit_die"],
    "take_item": ["items"], "drop_item": ["items"], "drink_potion": ["potion"],
    "apply_condition": ["poisoned", "exhaustion", "malnutrition"],
    "remove_condition": ["poisoned", "exhaustion", "malnutrition"],
    "apply_reduction": ["reduction"], "remove_reduction": ["reduction"],
    "interrupt_activity": ["short_rest", "long_rest", "cultivation", "path_recovery"],
    "damage": ["short_rest", "long_rest"],
}

# Stable labels identify the complete gameplay handler dependency surface.
# The gameplay modules live beside this file; engine.py is the package
# controller that owns gameplay request validation, commit, persistence and
# replay. Paths are resolved from this module, while labels are persisted in
# the profile so the binding remains independent of the checkout location.
HANDLER_SOURCE_PATHS = (
    ("gameplay/models.py", Path(__file__).with_name("models.py")),
    ("gameplay/rules.py", Path(__file__).with_name("rules.py")),
    ("gameplay/integration.py", Path(__file__).with_name("integration.py")),
    ("gameplay/profile.py", Path(__file__).with_name("profile.py")),
    ("gameplay/character_adapter.py", Path(__file__).with_name("character_adapter.py")),
    ("gameplay/trusted_producer.py", Path(__file__).with_name("trusted_producer.py")),
    ("engine.py", Path(__file__).parents[1] / "engine.py"),
)


@lru_cache(maxsize=1)
def _manifest():
    value = {
        "id": "factory-dm-gameplay-2024", "version": 9, "sources": SOURCES,
        "producer_profile": deepcopy(CURRENT_PRODUCER_PROFILE),
        "admission_dependencies": ADMISSION_DEPENDENCIES,
        "admission": {
            "schema": "factory-gameplay-level0-admission-v2",
            "adapter_id": "factory-dm-gameplay.level0-character-adapter",
            "adapter_version": 2,
            "level0_route": "sect_trial_pending",
            "path_attainment": {"body": 0, "qi": 0, "spirit": 0},
            "active_paths": [],
            "method_transition": "trial_awards_method; first_post_trial_cultivation_establishes_method_determined_path",
        },
        "rules": RULES, "effect_definitions": EFFECTS, "commands": COMMAND_RULES,
        "precedence": ["explicit_campaign_ruling", "applicable_current_specific",
                       "current_tianxia_shared", "adopted_2024"],
        "owner_rulings": [{"id": "combined-light-practice", "scope": "rest.combined",
                           "effect": "Independent 1-hour Short Rest and 2-hour cultivation milestones."}],
        "policies": {
            "zero_point_short_recovery": "A qualified Short Rest consumes a remaining Path recovery use even if capped at zero; no optional Path-recovery election in v1.",
            "long_rest_interruption": "Immediate resumption adds one hour to accumulated Long Rest duration. Each fresh uninterrupted one-hour qualifying segment claims one distinct partial Short Rest benefit identity; no prior segment time is re-counted.",
            "long_rest_partial_segment_interpretation": "The fresh-segment boundary and qualifying interruption set are a source-derived implementation interpretation of the preceding-rest Short Rest benefit, not an owner ruling.",
            "removal": "GM-admitted removal fact names the exact application; no general player cure",
        },
        "unsupported": ["source_blocked_stat_reduction",
                        "CP_zero_consequences", "concentration", "immunities", "periodic_damage",
                        "item_charges", "advancement", "general_creator_level0_route", "combat"],
        "handler_sources": {
            name: sha256(path.read_bytes()).hexdigest()
            for name, path in HANDLER_SOURCE_PATHS
        },
    }
    return {**value, "digest": digest(value)}


def manifest():
    return deepcopy(_manifest())


def identity():
    p = _manifest()
    return {key: p[key] for key in ("id", "version", "digest")}


# The one retained v9 profile whose source binding predates the current creator
# refresh.  This immutable compatibility record is checked by the complete
# profile digest and never synthesized from current source hashes, so a source
# refresh cannot silently rewrite an existing save.
RELEASED_CURRENT_PROFILE_V9_MANIFEST_DIGEST = "4443c6f6c8bac9d0e7884e576483d42cab322a7e79aa224ba6cdd52b828676f4"
RELEASED_CURRENT_PROFILE_V9_IDENTITY = {
    "id": "factory-dm-gameplay-2024",
    "version": 9,
    "digest": "66cc3be52b152f27637970b272d104e2afe4281ec73314bf137828a0768e9070",
}
PREVIOUS_PROFILE_V9_MANIFEST_DIGEST = "a4bc1a3bedc6f6f93d7c1c50b4b345fea3c50fdca22e207bf849399a77966ac7"
PREVIOUS_PROFILE_V9_IDENTITY = {
    "id": "factory-dm-gameplay-2024",
    "version": 9,
    "digest": "bf3d0b9beb349da392097e8fdf8810ad11e7cdb2d9d379d0480c7c2989b15a15",
}
PREVIOUS_CREATOR_PROFILE_V9_MANIFEST_DIGEST = "2688ba7b33210ae7e4c148dfb397020fe651a2325c95ffdc6a2219a02e0359a8"
PREVIOUS_CREATOR_PROFILE_V9_IDENTITY = {
    "id": "factory-dm-gameplay-2024",
    "version": 9,
    "digest": "d327c865b7d5b7390d115011912c73ada3050087ee06294d9525024f596bdad0",
}
LEGACY_PROFILE_V9_MANIFEST_DIGEST = "fc53639bb903e79d443b3657bd012fb0a6e8b9986a3300b74041d5ee7d954658"
LEGACY_PROFILE_V9_IDENTITY = {
    "id": "factory-dm-gameplay-2024",
    "version": 9,
    "digest": "ff59e53c6918f912c4250f725d116a9f3dbec33968951e3d34cc0a8cec535805",
}


def profile_identity_is_compatible(value):
    """Return whether a command identity belongs to the current v9 lineage."""

    return value in (
        identity(),
        RELEASED_CURRENT_PROFILE_V9_IDENTITY,
        PREVIOUS_CREATOR_PROFILE_V9_IDENTITY,
        PREVIOUS_PROFILE_V9_IDENTITY,
        LEGACY_PROFILE_V9_IDENTITY,
    )


def _is_previous_creator_profile_v9(value):
    return (
        isinstance(value, dict)
        and value.get("id") == PREVIOUS_CREATOR_PROFILE_V9_IDENTITY["id"]
        and value.get("version") == PREVIOUS_CREATOR_PROFILE_V9_IDENTITY["version"]
        and value.get("digest") == PREVIOUS_CREATOR_PROFILE_V9_IDENTITY["digest"]
        and digest(value) == PREVIOUS_CREATOR_PROFILE_V9_MANIFEST_DIGEST
    )


def _is_released_current_profile_v9(value):
    return (
        isinstance(value, dict)
        and value.get("id") == RELEASED_CURRENT_PROFILE_V9_IDENTITY["id"]
        and value.get("version") == RELEASED_CURRENT_PROFILE_V9_IDENTITY["version"]
        and value.get("digest") == RELEASED_CURRENT_PROFILE_V9_IDENTITY["digest"]
        and digest(value) == RELEASED_CURRENT_PROFILE_V9_MANIFEST_DIGEST
    )


def _is_previous_profile_v9(value):
    return (
        isinstance(value, dict)
        and value.get("id") == PREVIOUS_PROFILE_V9_IDENTITY["id"]
        and value.get("version") == PREVIOUS_PROFILE_V9_IDENTITY["version"]
        and value.get("digest") == PREVIOUS_PROFILE_V9_IDENTITY["digest"]
        and digest(value) == PREVIOUS_PROFILE_V9_MANIFEST_DIGEST
    )


def _is_legacy_profile_v9(value):
    return (
        isinstance(value, dict)
        and value.get("id") == LEGACY_PROFILE_V9_IDENTITY["id"]
        and value.get("version") == LEGACY_PROFILE_V9_IDENTITY["version"]
        and digest(value) == LEGACY_PROFILE_V9_MANIFEST_DIGEST
    )


def validate_profile(value):
    require(
        digest(value) == digest(_manifest())
        or _is_released_current_profile_v9(value)
        or _is_previous_creator_profile_v9(value)
        or _is_previous_profile_v9(value)
        or _is_legacy_profile_v9(value),
        "PROFILE_OR_HANDLER_MISMATCH",
    )


def rule_refs(command):
    require(command in COMMAND_RULES, "UNSUPPORTED_COMMAND")
    return [{"id": r["id"], "version": r["version"], "handler": r["handler"],
             "citations": r["citations"]} for r in RULES if r["id"] in COMMAND_RULES[command]]
