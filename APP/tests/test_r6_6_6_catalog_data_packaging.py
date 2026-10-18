from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORITY_SOURCE = ROOT / "catalog_authority/cat3/generated/catalog_authority.v1.json"
UI_LOGIC_SOURCE = ROOT / "static/sphere_talent_logic.js"
SPEC = ROOT / "packaging/windows_portable/TianxiaFactory.spec"
SELFCHECK = ROOT / "packaging/windows_portable/windows_build_selfcheck.py"
BUILD = ROOT / "packaging/windows_portable/Build-WindowsPortable.ps1"
VERIFY = ROOT / "packaging/windows_portable/Verify-WindowsPortable.ps1"


def test_catalog_authority_has_exact_source_to_runtime_mapping():
    assert AUTHORITY_SOURCE.is_file()
    service = (ROOT / "catalog/service.py").read_text(encoding="utf-8")
    assert "_cat3_talents_and_spheres()" in service
    assert "SPHERE_TALENT_AUTHORITY_PATH = " not in service
    spec = SPEC.read_text(encoding="utf-8")
    assert '(str(ROOT / "catalog_authority" / "cat3" / "generated"), "catalog_authority/cat3/generated")' in spec
    selfcheck = SELFCHECK.read_text(encoding="utf-8")
    assert 'CATALOG_AUTHORITY_SOURCE = Path("catalog_authority/cat3/generated/catalog_authority.v1.json")' in selfcheck
    assert 'if digest(packaged_catalog) != digest(source_catalog):' in selfcheck
    build = BUILD.read_text(encoding="utf-8")
    assert 'Assert-Hash $CatalogAuthorityRuntime (Sha256 $CatalogAuthoritySource)' in build


def test_source_and_packaged_tree_assertions_fail_closed():
    selfcheck = SELFCHECK.read_text(encoding="utf-8")
    assert 'CATALOG_AUTHORITY_SOURCE = Path("catalog_authority/cat3/generated/catalog_authority.v1.json")' in selfcheck
    assert 'CATALOG_AUTHORITY_RUNTIME = Path("Runtime/catalog_authority/cat3/generated/catalog_authority.v1.json")' in selfcheck
    assert 'if digest(packaged_catalog) != digest(source_catalog):' in selfcheck

    build = BUILD.read_text(encoding="utf-8")
    assert '$CatalogAuthorityRuntime = Join-Path $Portable "Runtime\\catalog_authority\\cat3\\generated\\catalog_authority.v1.json"' in build
    assert 'Assert-Hash $CatalogAuthorityRuntime (Sha256 $CatalogAuthoritySource)' in build

    verify = VERIFY.read_text(encoding="utf-8")
    assert '$CatalogAuthority = Join-Path $PortableRoot "Runtime\\catalog_authority\\cat3\\generated\\catalog_authority.v1.json"' in verify
    assert 'Required catalog authority data is missing' in verify


def test_other_new_r665_runtime_data_is_already_collected_and_asserted():
    assert UI_LOGIC_SOURCE.is_file()
    spec = SPEC.read_text(encoding="utf-8")
    assert '(str(ROOT / "static"), "static")' in spec

    selfcheck = SELFCHECK.read_text(encoding="utf-8")
    assert 'SPHERE_TALENT_UI_RUNTIME = Path("Runtime/static/sphere_talent_logic.js")' in selfcheck
    assert 'if digest(packaged_ui_logic) != digest(source_ui_logic):' in selfcheck

    build = BUILD.read_text(encoding="utf-8")
    assert '$SphereTalentUiRuntime = Join-Path $Portable "Runtime\\static\\sphere_talent_logic.js"' in build
    assert 'Assert-Hash $SphereTalentUiRuntime (Sha256 $SphereTalentUiSource)' in build
