"""Trusted exact-byte bridge to the isolated Factory producer snapshot.

The generic portable import helpers intentionally reject caller audit maps.
This module is the only gameplay entry point that loads the pinned producer
source, invokes ``PortableCharacterPackageService.audit`` itself, and then
checks the level-0 authority member against the audited package models.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


PORTABLE_AUDIT_SOURCE_SHA256 = "e572cb39a5a5975a1c54365ed6e3607fee2833dedd3a04403d33f6bd5baa8865"
LEVEL0_EXPORTER_SOURCE_SHA256 = "fbda9748973bb858cdccd6c61836d46891c2b0df874c9600744153a461147827"
LEVEL0_AUTHORITY_MEMBER = "Mortal_Level0_Authority.json"
LEVEL0_SCHEMA = "TianxiaFoundry.MortalLevel0Export.v1"
PORTABLE_SCHEMA = "TianxiaFoundry.PortableCharacterPackage.v1"
LEVEL0_SOURCE_ID = "PHB"
LEVEL0_SOURCE_SHA256 = "f2bb2eeba55a4b8b8630e02fbcb35d21ac80d2efb7ad4a9e91642522f82d7fe7"
LEVEL0_SOURCE_LOCATOR = "PHB v0.7 lines 324-345"
AUTHORITY_PACK_PATH = "catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json"
AUTHORITY_PACK_SHA256 = "0635ca8c652b042bff83d1d68afb3b74da1699806737bcb5db5403ff98b2911b"

# Versioned binding for the current Factory creator checkout.  The producer
# manifest is regenerated only when a creator dependency changes; the fresh
# audit below rejects any unbound or drifted source before admission.
PRODUCER_PROFILE_ID = "factory-current-creator-level0"
PRODUCER_PROFILE_VERSION = 1

# The immediately prior published creator binding remains a strict one-file
# compatibility seam when the current linear identity contract is repaired.
RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256 = "ea5254b4d7a63f77dc8c35d1bd2fb0dd5f220c0c0b7a26660f9a7390dcce886c"
RELEASED_CURRENT_LINEAR_PROMPT_SOURCE_SHA256 = "910c02eb7b4ad85c768700a39972e9fee119af29b9f37fa2afcadc74a8b1cf9d"

# Immutable source binding retained by gameplay profile v9 saves.  The
# current audit still rechecks every package byte and authority record.  The
# compatibility seams below accept only the recorded full manifest and the
# exact source-only substitutions named for that lineage.
LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256 = "b558558fe2fd0bd07ba34c5757072c1df1046541f1f59e5f9ee72e385b83d716"
LEGACY_PORTABLE_AUDIT_SOURCE_SHA256 = "288acbaa15fd74f4577ef8bc3cfcb39efa33527f7562f39f75ff17b54a2f928e"
PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256 = "952e19314db7baf340283bbca25fe4de4fafab44b8e8f49dfd5f6a98a9d2965d"
PREVIOUS_LINEAR_PROMPT_SOURCE_SHA256 = "748a936750a9b11f73e8cce7067a4b62a64d519e7ee8f76d92be05ccb5a397b8"
PREVIOUS_CREATOR_PRODUCER_SOURCE_MANIFEST_SHA256 = "c64b1694ef1530739725d6c0839ac45d2ee51ee3d33deb18e66ce5b7579d2d15"
PREVIOUS_CREATOR_LINEAR_PROMPT_SOURCE_SHA256 = "0448fa77201199c85a81b68366eaf56664cc54a36ba239b1ce99a8ccbf032477"

# This manifest is filled from the isolated creator snapshot after every
# producer change.  It is intentionally app-relative and includes every
# executable module observed by the fresh audit worker, plus the authority
# pack bytes whose records are copied into the level-0 authority member.
PRODUCER_SOURCE_MANIFEST: dict[str, str] = {
    'app/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'app/authorities.py': 'cfef447ef9b4f87918c142de2adadef1e8ff8b8508fcae87417ca20db03a9b4d',
    'app/core.py': '01c35a11f1a0efdfd8eb0f77c447bdd4d3bf8f599888211cd81af19bbbee860f',
    'app/runtime.py': '040b0a9f34111f9e9592fa40cf0a6ef53cfa2a715e65a0850f79983a08809948',
    'canonical_catalog/__init__.py': '675de8c0981c92a85bdc4f8c7041195514e90f200464be7ae47f9ef575a561c9',
    'canonical_catalog/service.py': '38ad0260735b8ad7ef7f85570ae62ff73edaed2d17ab59f6ea5bf7236a4d564e',
    'catalog/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'catalog/coverage.py': '8d4affb74a1bdc54d62000a3ec464173e869d68aaac1012d935ef7999261a964',
    'catalog/service.py': '528276ef7babef599ef94fc2ebb1c7b23b1410d36017ac6c2ab6de9c23d4bcf5',
    'catalog_choice_authority.py': 'e24a605f3c5576936600a82a1ccb585b2b0067dffe1b25a0728e964cc389c588',
    'character_builder/__init__.py': '17d0b97dcd47ca4c4911e32dfa0858d957bf64bcf7fa6f7bff1c658e288d8a4a',
    'character_builder/insight_authority.py': '739112a7211ef11e7d67b25229a8e488dd21906a2126f52bd164ce4d107d1a3a',
    'character_builder/origin_insight_route_binding.py': 'c50779973e61fa8115de7c0559d098307e530d0750ad5ef261395f454c2c1676',
    'character_builder/service.py': 'c187fc0932a0fbe338027a4364547c5171ba958060389918a02618ba8d427933',
    'character_creation/__init__.py': '5dd17d2ce736685183f3f1fc4bd86314da496f968ebb43aa3d86bb333c3bc1f0',
    'character_creation/choice_snapshot.py': '7806943895063a4f3a9651abd3aa52b3af3cdc9c5397049efadc547c8432e625',
    'character_creation/compiler_selection_authority.py': '3860c87c94108325af7d42b80032e5558e5e76ceadc7bb2c28a70370ccf71cb0',
    'character_creation/constructed_arts/__init__.py': 'f6b34f377fa13a6d8a53645fa8b165e322cb7d784ff89f787da1a5611ee62e91',
    'character_creation/constructed_arts/explicit_forging.py': '1178a84eaa981f3b07a99e6dedb5c3d389c6733b626524563f06039e01aa6766',
    'character_creation/creative_controller/__init__.py': 'e067376f21066073c506941a528238ea8d2abf6fcef2c7187a4050f558ad1f15',
    'character_creation/creative_controller/choice_semantics.py': '51378478717f4122daf06cbbffa5d48142834f9f7bcd29d4b207be78c7e943dd',
    'character_creation/creative_controller/clustering.py': '16b54871f92ad01460f6f96ab2448403d2c9c1d08cab8d7e8cc33fd39b250b72',
    'character_creation/creative_controller/content_snapshots.py': 'b1b3be7ec8b2be983bae003ebf83263fce1bc8e6877e8edfb41c143bbe051267',
    'character_creation/creative_controller/contracts.py': '070ed0c97ef271b53310118200e9ebb0c58f1e119eda54c98bc35e06d5cd5848',
    'character_creation/creative_controller/creative_menu.py': '3aa1042908d740c4add86e97e1b979b47618e90d48b06f6cd1047fba88989ba2',
    'character_creation/creative_controller/dcc_semantic_publication.py': '76890f181c9928de515ec0bb86b56b3ec8ed086d4fb69c221e86ebe0a12a3c3d',
    'character_creation/creative_controller/factory_catalog_adapter.py': 'fdb517ff3a4170028df20f5ea4a53b2538d6f33865176f8b6c1001eb4added20',
    'character_creation/creative_controller/factory_semantic_library.py': '2f187fcc2e71c53830c821f55e5254c33ae6fbdcea8d99eb4373a92b5a53528f',
    'character_creation/creative_controller/factory_validator.py': '4d130889289bfcfb52d4fba0ed9130a3a6ede483b5384cd5499af6a1f31c8057',
    'character_creation/creative_controller/legal_plan_compiler.py': 'fd4dfb555dcd4a732266e6fb16dd11cf1d900c4f1491ba0376654466fc1579cc',
    'character_creation/creative_controller/linear_assembly.py': '01bc3733667039e868c2f32072ed5082d4e324bdef406bc9b78c9ac30c64b0ee',
    'character_creation/creative_controller/linear_menus.py': '6248dcf2ebedf3966462a5b3d22c8d0df9d433f2a37839117427bc27571adea5',
    'character_creation/creative_controller/linear_persistence.py': 'b57a9518abcecaf022bdbeeceeed2bc47b6af653490a354232db92c79a187a62',
    'character_creation/creative_controller/linear_prompt.py': 'b58597ada54d6d5b347786aa19f3e4edcf004fc5135a5583671e7c4202d1bcf9',
    'character_creation/creative_controller/linear_walk.py': '6f01c89ee9cbac6e1a46edd9fc59cf4f766db8913c18a3bd25c0cf88a7bc8b81',
    'character_creation/creative_controller/manifest.py': 'a2f44f898f8f45f27bfaef0091a371cd36ca79dc032c082f5bf5f4ffee87b0d8',
    'character_creation/creative_controller/ranking.py': 'c475f96a722f689a7c33d832054aa774ef8ffc6ec830bae2ac8eca30e2d825d0',
    'character_creation/creative_controller/replay.py': '18d01151dd583f6bd8cb1c1af5fe05c980181aab303b9bcc4ebb6b4feda8bdb7',
    'character_creation/creative_controller/route_persistence.py': 'bc42bf8e39e7a1b5f6682fffd7e16145e5235f4e71a2cb2be661089abeebe146',
    'character_creation/creative_controller/semantic_admission.py': 'e37254b72142a9bf78256172f2a4a53962fd39d8cd5fc80b151169aa1e29d464',
    'character_creation/creative_controller/shadow.py': '8c8c64b83d6533f065aa984b8146ea7b220aa75a1f177c70d854164c4bf5e258',
    'character_creation/delegated_choice_authority.py': 'ce40dbd4a33bdb6a0ee9926ed73548cbfe672b66ebec7b8b1c28fca21e49f8a1',
    'character_creation/foundation_corpus_release.py': 'e362c2834af3b73aa83aead43d855946ee618cd0735f69743fa23f39feaf638c',
    'character_creation/method_corpus_release.py': 'acf14a869d988605883b526d3d1c0c6bbbc48ba873231079c5090138cebf1d0c',
    'character_creation/mortal_level0.py': 'a2a817a15dfd81fe0aaa5964b807128fe27b5f236d5dafc54d592b37c2692d92',
    'character_creation/path_attainment.py': '0ba941b41262c40ff6392aa3c6f9b504f8b9a644b48af49317ed708ec8401606',
    'character_creation/response_materialization.py': 'f84dee1462c00e229be8b84be7af3ecba2507e89a4f4e8d8b09234ed531c0aab',
    'content_packs/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'content_packs/identity.py': '956806ca5d3676115bf1306e7bd18b150f49eb4cc5cbbf97e0b5118b52df5177',
    'content_packs/membership.py': '03e89652d224cb0852b5743a2a5626d923e3e569810a72300e350c412537e1cf',
    'content_packs/service.py': 'd88ca22b435d74cd4380f29081c42f949e44ebb29ea763d52a90bf66849b9985',
    'contracts/__init__.py': 'ed97a7fe6a8bc6104cdb1f5ee7d01b25081402a5d08dc9f4d4c69fdbf0ec34a1',
    'contracts/canonical.py': 'ac5c43a7e57b75881fa7cd994677b6ab6975563943cc7c8f2c02b73d2e4fbc72',
    'contracts/registry.py': '59bd46003f16e1a3d9b13c04a2862b32cffdcfa7d76fed688f3485cde84b0e2a',
    'creation_training_authority.py': '1d67ced7038e03d431742cc61a4dc6e7d0fe91b7346abe3bf5b3a02a39a289fe',
    'gm2_contract/__init__.py': 'ca467e56c2ee13a22e62e10cae4ed2152b9552a47c27feca4e926b16a565fc74',
    'gm2_contract/adapter.py': '3e09e600baac1c9a619b47b42ce507111f0039736e8fc982b1076c673a8d18c9',
    'non_sphere_authority/__init__.py': '2dfe97c8669381a9c1769c5bc2268d9f8a0129ed4dd79a02978a09e7aa3a8262',
    'non_sphere_authority/semantic_validator.py': 'c485c8193f9fc2094471670b49434df378fad8e2f011ebfa8f420011f82c7f4e',
    'non_sphere_authority/service.py': 'a811afcb3d294de3e01171f189fda127d1e34a603db1b1de4ed410efe0ce067c',
    'path_method_authority.py': '36d0e66b08016c48c05a8ace9c4c2803e85510ae2f340d5f2d30fc0c1cfae235',
    'portable_character/__init__.py': '8c4446e5c8aa8e5faf9eb08ce9c778ba8b977cafc51c1032f7dca04d0e9057f3',
    'portable_character/level0.py': 'fbda9748973bb858cdccd6c61836d46891c2b0df874c9600744153a461147827',
    'portable_character/service.py': 'e572cb39a5a5975a1c54365ed6e3607fee2833dedd3a04403d33f6bd5baa8865',
    'product_bootstrap/__init__.py': 'f5b2ddc0cad083ee765cd5b6e8e760dbe8cabedd40dbe18fa0dc2931bb2d0d85',
    'product_bootstrap/service.py': 'dc2a5d21b40437c6e0ca556a7dc4b87c98694ae53d72ff47eebf9a1f0bb7f607',
    'project_store/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'project_store/service.py': 'dbe687211c167640bd23b863d9488f1c42f104408cd272c6ecae35a5b60f3a66',
    'security/__init__.py': '4aed847cb816ceb3b783d9a820376e6b01363115af01100da510d531a789dfed',
    'security/approval_challenges.py': '5a29fa11ea5151c5d36a428592df881c99234b29e17d6ab62382baa5a49add68',
    'security/clock_authority.py': '165092b72e6f79eb810b159ed1582dd7c1c982b935b11bb0710ac0c4196812e8',
    'security/integrity.py': '23e18fd65032fd66a47d6b4ca63fc4692d185388f0eef64f2fe5628fad8ba746',
    'security/local_identity.py': '797ad936993e7985f8a328d8e3fc7ce3be6d3f7034f5c857900506657eddf28a',
    'sphere_component_authority.py': '254cd1359ac404e458e8e28bace0e17458fcbee1165eb104449deda35ceb3796',
    'stage1/__init__.py': '266f3c58398759bfa5023c9a9552893e5a6c614389b845aeafbbdf7b9d32775e',
    'stage1/service.py': '4b81bc42e32c8083ca705d729ac3aa091c56bc8c8ccb9542f00f37975790ac82',
    'stage2/__init__.py': 'ec6d69e0493d79a124f6ef07f774ffcdfd51c725d6aca4fbf2fbd999205830ee',
    'stage2/authority_contract.py': 'edeb393faf6536f132dae8d5d1269fa83ae2d6d67adadf565d18c4954f93984b',
    'stage2/insight_authority.py': 'cd5333a34382f0e93cc0fe6518feb06f04f2a5ee21e2684658d42b49d5e6afca',
    'vendor_adapter/__init__.py': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    'vendor_adapter/service.py': '6bd56041e76b36982737f2cdda6d96797e84d6853048a76489e221e1588e3ee7',
}


class TrustedProducerError(ValueError):
    def __init__(self, code: str, **details: Any) -> None:
        self.code = code
        self.details = details
        message = code if not details else f"{code}: {json.dumps(details, sort_keys=True, default=str)}"
        super().__init__(message)


def _require(condition: bool, code: str, **details: Any) -> None:
    if not condition:
        raise TrustedProducerError(code, **details)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_root(producer_root: str | Path) -> tuple[Path, Path]:
    root = Path(producer_root).resolve()
    app_root = root / "APP"
    if not app_root.is_dir() and root.name == "APP":
        app_root = root
    _require(app_root.is_dir(), "PRODUCER_SOURCE_ROOT_MISSING", path=str(root))
    return root, app_root


def _manifest_digest(source_manifest: dict[str, str]) -> str:
    return _sha256_bytes(json.dumps(source_manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def source_manifest_is_compatible(
    current_manifest: dict[str, str],
    current_digest: str,
    persisted_manifest: dict[str, str],
    persisted_digest: str,
) -> bool:
    """Accept current bytes or one exact pinned v9 compatibility transition."""

    if current_manifest == persisted_manifest and current_digest == persisted_digest:
        return True

    if persisted_digest == RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256:
        if (
            _manifest_digest(dict(persisted_manifest)) != RELEASED_CURRENT_PRODUCER_SOURCE_MANIFEST_SHA256
            or persisted_manifest.get("character_creation/creative_controller/linear_prompt.py")
            != RELEASED_CURRENT_LINEAR_PROMPT_SOURCE_SHA256
        ):
            return False
        expected_current = dict(persisted_manifest)
        expected_current["character_creation/creative_controller/linear_prompt.py"] = PRODUCER_SOURCE_MANIFEST[
            "character_creation/creative_controller/linear_prompt.py"
        ]
        return current_manifest == expected_current and current_digest == _manifest_digest(current_manifest)

    if persisted_digest == PREVIOUS_CREATOR_PRODUCER_SOURCE_MANIFEST_SHA256:
        if (
            _manifest_digest(dict(persisted_manifest)) != PREVIOUS_CREATOR_PRODUCER_SOURCE_MANIFEST_SHA256
            or persisted_manifest.get("character_creation/creative_controller/linear_prompt.py")
            != PREVIOUS_CREATOR_LINEAR_PROMPT_SOURCE_SHA256
            or persisted_manifest.get("portable_character/service.py") != PORTABLE_AUDIT_SOURCE_SHA256
        ):
            return False
        expected_current = dict(persisted_manifest)
        expected_current["character_creation/creative_controller/linear_prompt.py"] = PRODUCER_SOURCE_MANIFEST[
            "character_creation/creative_controller/linear_prompt.py"
        ]
        return current_manifest == expected_current and current_digest == _manifest_digest(current_manifest)

    if persisted_digest == PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256:
        if (
            _manifest_digest(dict(persisted_manifest)) != PREVIOUS_PRODUCER_SOURCE_MANIFEST_SHA256
            or persisted_manifest.get("character_creation/creative_controller/linear_prompt.py")
            != PREVIOUS_LINEAR_PROMPT_SOURCE_SHA256
            or persisted_manifest.get("portable_character/service.py") != PORTABLE_AUDIT_SOURCE_SHA256
        ):
            return False
        expected_current = dict(persisted_manifest)
        expected_current["character_creation/creative_controller/linear_prompt.py"] = PRODUCER_SOURCE_MANIFEST[
            "character_creation/creative_controller/linear_prompt.py"
        ]
        return current_manifest == expected_current and current_digest == _manifest_digest(current_manifest)

    if persisted_digest != LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256:
        return False
    if (
        _manifest_digest(dict(persisted_manifest)) != LEGACY_PRODUCER_SOURCE_MANIFEST_SHA256
        or persisted_manifest.get("character_creation/creative_controller/linear_prompt.py")
        != PREVIOUS_LINEAR_PROMPT_SOURCE_SHA256
        or persisted_manifest.get("portable_character/service.py") != LEGACY_PORTABLE_AUDIT_SOURCE_SHA256
    ):
        return False
    expected_current = dict(persisted_manifest)
    expected_current["character_creation/creative_controller/linear_prompt.py"] = PRODUCER_SOURCE_MANIFEST[
        "character_creation/creative_controller/linear_prompt.py"
    ]
    expected_current["portable_character/service.py"] = PORTABLE_AUDIT_SOURCE_SHA256
    return current_manifest == expected_current and current_digest == _manifest_digest(current_manifest)


def _verify_source_manifest(app_root: Path) -> tuple[dict[str, str], str, str]:
    observed: dict[str, str] = {}
    for relative, expected in sorted(PRODUCER_SOURCE_MANIFEST.items()):
        path = app_root / relative
        _require(path.is_file() and not path.is_symlink(), "PRODUCER_SOURCE_MANIFEST_MISSING", path=relative)
        actual = _sha256_bytes(path.read_bytes())
        _require(actual == expected, "PRODUCER_SOURCE_MANIFEST_MISMATCH", path=relative, expected=expected, actual=actual)
        observed[relative] = actual
    pack = app_root / AUTHORITY_PACK_PATH
    _require(pack.is_file() and not pack.is_symlink(), "LEVEL0_AUTHORITY_PACK_MISSING", path=AUTHORITY_PACK_PATH)
    pack_hash = _sha256_bytes(pack.read_bytes())
    _require(
        pack_hash == AUTHORITY_PACK_SHA256,
        "LEVEL0_AUTHORITY_PACK_SOURCE_MISMATCH",
        expected=AUTHORITY_PACK_SHA256,
        actual=pack_hash,
    )
    return observed, _manifest_digest(observed), pack_hash


def _fresh_audit(path: Path, app_root: Path) -> dict[str, Any]:
    """Run the producer audit in a clean interpreter namespace."""

    worker = (
        "import json, sys, tempfile, zipfile\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[2])\n"
        "from portable_character.service import PortableCharacterPackageService\n"
        "from portable_character.level0 import build_mortal_level0_package, validate_mortal_level0_starter\n"
        "package = Path(sys.argv[1])\n"
        "report = PortableCharacterPackageService.audit(package)\n"
        "semantic = {'valid': False}\n"
        "try:\n"
        "    with zipfile.ZipFile(package) as zf:\n"
        "        authority = json.loads(zf.read('Mortal_Level0_Authority.json'))\n"
        "    identity = authority['identity']\n"
        "    raw_base = authority['base_abilities']\n"
        "    ordered_base = {name: raw_base[name] for name in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')}\n"
        "    background = authority['background_record']['canonical_record_id']\n"
        "    origin = authority['origin_record']['canonical_record_id']\n"
        "    validate_mortal_level0_starter(name=identity['display_name'], base_abilities=ordered_base, background_ability=authority['background_ability'], background_id=background, origin_insight_id=origin)\n"
        "    with tempfile.TemporaryDirectory(prefix='level0-semantic-') as temp:\n"
        "        derived_path = Path(temp) / 'derived.zip'\n"
        "        build_mortal_level0_package(derived_path, character_id=authority['character_id'], display_name=identity['display_name'], base_abilities=ordered_base, background_ability=authority['background_ability'])\n"
        "        with zipfile.ZipFile(derived_path) as zf:\n"
        "            derived_authority = json.loads(zf.read('Mortal_Level0_Authority.json'))\n"
        "    semantic = {'valid': True, 'derived_authority': derived_authority}\n"
        "except Exception as exc:\n"
        "    semantic = {'valid': False, 'error_code': getattr(exc, 'code', None) or exc.__class__.__name__, 'error': str(exc)[:500]}\n"
        "report['level0_semantics'] = semantic\n"
        "print(json.dumps(report, sort_keys=True, separators=(',', ':'), default=str))\n"
    )
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", worker, str(path), str(app_root)],
        cwd=str(app_root), env=env, capture_output=True, text=True, check=False,
    )
    _require(result.returncode == 0, "PRODUCER_AUDIT_WORKER_FAILED", stderr=result.stderr[-2000:])
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TrustedProducerError("PRODUCER_AUDIT_WORKER_OUTPUT_INVALID") from exc
    _require(isinstance(report, dict), "PRODUCER_AUDIT_WORKER_OUTPUT_INVALID")
    return report


def _json_member(zf: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = json.loads(zf.read(name))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise TrustedProducerError("LEVEL0_PACKAGE_MEMBER_INVALID", member=name) from exc
    _require(isinstance(value, dict), "LEVEL0_PACKAGE_MEMBER_INVALID", member=name)
    return value


def _assert_semantics(
    *,
    report: dict[str, Any],
    authority: dict[str, Any],
    manifest: dict[str, Any],
    model: dict[str, Any],
    owner_sheet: dict[str, Any],
    producer_root: Path,
) -> None:
    semantic = report.get("level0_semantics") if isinstance(report, dict) else None
    _require(isinstance(semantic, dict) and semantic.get("valid") is True,
             "LEVEL0_CREATOR_SEMANTICS_INVALID",
             error_code=(semantic or {}).get("error_code"),
             error=(semantic or {}).get("error"))
    derived_authority = semantic.get("derived_authority")
    _require(isinstance(derived_authority, dict), "LEVEL0_CREATOR_DERIVED_AUTHORITY_MISSING")
    _require(
        set(authority) == set(derived_authority),
        "LEVEL0_AUTHORITY_FIELDS_UNSUPPORTED",
        missing=sorted(set(derived_authority) - set(authority)),
        extra=sorted(set(authority) - set(derived_authority)),
    )
    _require(authority == derived_authority, "LEVEL0_DERIVED_AUTHORITY_MISMATCH")
    _require(authority.get("schema") == LEVEL0_SCHEMA, "LEVEL0_AUTHORITY_SCHEMA_UNSUPPORTED")
    _require(manifest.get("schema_version") == PORTABLE_SCHEMA, "PORTABLE_PACKAGE_SCHEMA_UNSUPPORTED")
    _require(manifest.get("build_profile") == "MORTAL_LEVEL0_SOURCE_VALIDATED", "LEVEL0_BUILD_PROFILE_MISSING")
    _require(
        manifest.get("level0_authority") == {
            "path": LEVEL0_AUTHORITY_MEMBER,
            "schema": LEVEL0_SCHEMA,
            "authoritative": True,
        },
        "LEVEL0_AUTHORITY_BINDING_INVALID",
    )
    _require(
        manifest.get("source_producer") == {
            "id": "TianxiaFoundry.MortalLevel0PackageService",
            "route": "completed_level0_mortal",
        },
        "LEVEL0_PRODUCER_BINDING_INVALID",
    )
    _require(authority.get("exporter") == {"id": "TianxiaFoundry.MortalLevel0PackageService", "version": 1}, "LEVEL0_EXPORTER_BINDING_INVALID")
    ident = authority.get("identity")
    stage = authority.get("stage")
    _require(isinstance(ident, dict) and ident.get("cultivation_level") == 0, "LEVEL0_IDENTITY_INVALID")
    _require(stage == {"level": 0, "route": "sect_trial_pending", "state": "completed_level0"}, "LEVEL0_STAGE_INVALID")
    _require(authority.get("binding") == {"faction_id": "party", "location_id": "mortal-start"}, "LEVEL0_BINDING_INVALID")
    abilities = authority.get("abilities")
    _require(isinstance(abilities, dict) and set(abilities) == {"STR", "DEX", "CON", "INT", "WIS", "CHA"}, "LEVEL0_ABILITIES_INVALID")
    _require(all(type(value) is int and 1 <= value <= 30 for value in abilities.values()), "LEVEL0_ABILITIES_INVALID")
    hp = authority.get("hp")
    _require(isinstance(hp, dict) and hp.get("formula") == "6 + CON modifier", "LEVEL0_HP_FORMULA_INVALID")
    _require(hp.get("current") == hp.get("maximum") == max(1, 6 + ((abilities["CON"] - 10) // 2)), "LEVEL0_HP_INVALID")
    die = authority.get("hit_dice")
    _require(die == {"sides": 6, "maximum": 1, "remaining": 1}, "LEVEL0_HIT_DICE_INVALID")
    _require(authority.get("speed") == {"walking_ft": 30}, "LEVEL0_SPEED_INVALID")
    paths = authority.get("paths")
    _require(isinstance(paths, dict), "LEVEL0_PATHS_INVALID")
    _require(paths.get("selected") == [] and paths.get("pools") == [] and paths.get("cultivation_permissions") == [], "LEVEL0_PATHS_ACTIVE")
    _require(isinstance(paths.get("attainment"), dict) and set(paths["attainment"]) == {
        "tianxia.path.body_refining", "tianxia.path.qi_cultivation", "tianxia.path.spirit_awakening",
    } and all(value == 0 for value in paths["attainment"].values()), "LEVEL0_PATH_ATTAINMENT_INVALID")
    background = authority.get("background_record")
    origin = authority.get("origin_record")
    _require(isinstance(background, dict) and background.get("canonical_record_id") == "tianxia.background.abandoned_orphan", "LEVEL0_BACKGROUND_INVALID")
    _require(isinstance(origin, dict) and origin.get("canonical_record_id") == "tianxia.origin_insight.street_hardened", "LEVEL0_ORIGIN_INVALID")
    _require(authority.get("source") == {
        "source_id": LEVEL0_SOURCE_ID,
        "source_hash": LEVEL0_SOURCE_SHA256,
        "locator": LEVEL0_SOURCE_LOCATOR,
    }, "LEVEL0_SOURCE_INVALID")
    _require(authority.get("authority_pack", {}).get("path") == AUTHORITY_PACK_PATH, "LEVEL0_AUTHORITY_PACK_INVALID")
    pack_path = producer_root / "APP" / authority["authority_pack"]["path"]
    if not pack_path.is_file() and producer_root.name == "APP":
        pack_path = producer_root / authority["authority_pack"]["path"]
    _require(pack_path.is_file(), "LEVEL0_AUTHORITY_PACK_MISSING", path=str(pack_path))
    pack_bytes = pack_path.read_bytes()
    _require(_sha256_bytes(pack_bytes) == authority["authority_pack"]["sha256"], "LEVEL0_AUTHORITY_PACK_HASH_MISMATCH")
    pack = json.loads(pack_bytes)
    _require(pack.get("records", {}).get(background["canonical_record_id"]) == background, "LEVEL0_BACKGROUND_RECORD_NOT_SOURCE_BACKED")
    _require(pack.get("records", {}).get(origin["canonical_record_id"]) == origin, "LEVEL0_ORIGIN_RECORD_NOT_SOURCE_BACKED")
    for field in ("identity", "stage", "abilities", "hp", "hit_dice", "speed", "paths", "background_origin"):
        if field in model and field in authority:
            expected = authority[field]
            if field == "background_origin":
                expected = {"background_id": background["canonical_record_id"], "origin_insight_ids": [origin["canonical_record_id"]], "exceptions": []}
            _require(model[field] == expected, "LEVEL0_MODEL_AUTHORITY_MISMATCH", field=field)
    _require(owner_sheet.get("identity") == ident and owner_sheet.get("stage") == stage, "LEVEL0_OWNER_SHEET_MISMATCH")


def audit_exact_package(package_path: str | Path, *, producer_root: str | Path) -> dict[str, Any]:
    """Run the real producer audit against one stable package byte sequence."""

    root, app_root = _source_root(producer_root)
    source_manifest, source_manifest_sha256, authority_pack_sha256 = _verify_source_manifest(app_root)
    path = Path(package_path).resolve()
    _require(path.is_file() and not path.is_symlink(), "PORTABLE_EXPORT_PATH_INVALID", path=str(path))
    before = path.stat()
    package_bytes = path.read_bytes()
    after = path.stat()
    _require((before.st_ino, before.st_size, before.st_mtime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns), "PORTABLE_EXPORT_CHANGED_DURING_READ")
    package_sha256 = _sha256_bytes(package_bytes)
    report = _fresh_audit(path, app_root)
    _require(report.get("valid") is True, "PORTABLE_EXPORT_AUDIT_FAILED")
    _require(report.get("sha256") == package_sha256, "PORTABLE_EXPORT_AUDIT_HASH_MISMATCH")
    _require(report.get("checksum_manifest", {}).get("coverage_status") == "EXACT", "PORTABLE_EXPORT_CHECKSUM_COVERAGE_INVALID")
    with zipfile.ZipFile(io.BytesIO(package_bytes)) as zf:
        authority = _json_member(zf, LEVEL0_AUTHORITY_MEMBER)
        manifest = _json_member(zf, "PACKAGE_MANIFEST.json")
        model = _json_member(zf, "Tianxia_GM_Character_Model_v2.json")
        owner_sheet = _json_member(zf, "Tianxia_Owner_Character_Sheet_v1.json")
    _assert_semantics(
        report=report,
        authority=authority,
        manifest=manifest,
        model=model,
        owner_sheet=owner_sheet,
        producer_root=root,
    )
    final = path.stat()
    _require((final.st_ino, final.st_size, final.st_mtime_ns) == (before.st_ino, before.st_size, before.st_mtime_ns), "PORTABLE_EXPORT_CHANGED_AFTER_AUDIT")
    return {
        "package_bytes": package_bytes,
        "package_sha256": package_sha256,
        "audit": report,
        "manifest": manifest,
        "authority": authority,
        "producer_root": str(root),
        "source_manifest": source_manifest,
        "source_manifest_sha256": source_manifest_sha256,
        "producer_profile": {"id": PRODUCER_PROFILE_ID, "version": PRODUCER_PROFILE_VERSION},
        "authority_pack_sha256": authority_pack_sha256,
    }


def audit_exact_package_bytes(package_bytes: bytes, *, producer_root: str | Path) -> dict[str, Any]:
    """Re-audit persisted package bytes through the isolated producer worker."""

    _require(isinstance(package_bytes, bytes) and package_bytes, "PORTABLE_EXPORT_BYTES_REQUIRED")
    _source_root(producer_root)
    handle = tempfile.NamedTemporaryFile(
        dir=str(Path(__file__).resolve().parent),
        prefix=".gameplay-portable-audit-", suffix=".zip", delete=False,
    )
    path = Path(handle.name)
    try:
        handle.write(package_bytes)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        result = audit_exact_package(path, producer_root=producer_root)
        _require(result["package_sha256"] == _sha256_bytes(package_bytes), "PORTABLE_EXPORT_BYTES_HASH_MISMATCH")
        return result
    finally:
        try:
            handle.close()
        finally:
            path.unlink(missing_ok=True)
