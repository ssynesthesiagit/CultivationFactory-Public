from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

FACTORY_SHA = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
FOUNDATION_SHA = "df80217c64c0808190c85531095e5e78aa96ff6808be369915f36fbb4189771c"
CATALOG_AUTHORITY_SOURCE = Path("catalog_authority/cat3/generated/catalog_authority.v1.json")
CATALOG_AUTHORITY_RUNTIME = Path("Runtime/catalog_authority/cat3/generated/catalog_authority.v1.json")
TYPED_AUTHORITY_SOURCE = Path("catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json")
TYPED_AUTHORITY_RUNTIME = Path("Runtime/catalog/typed_authority/C1A_Canonical_Typed_Authority_Pack_v1.json")
SPHERE_TALENT_UI_SOURCE = Path("static/sphere_talent_logic.js")
SPHERE_TALENT_UI_RUNTIME = Path("Runtime/static/sphere_talent_logic.js")
GM_SCREEN_SOURCE = Path("gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip")
GM_SCREEN_RUNTIME = Path("Runtime/gm_screen/HF05ZUI_R2K3_HF3_W1_CoreStats_GMScreen.zip")
CATALOG_SPEC_MAPPING = '(str(ROOT / "catalog_authority" / "cat3" / "generated"), "catalog_authority/cat3/generated")'
GM_SCREEN_SPEC_MAPPING = '(str(ROOT / "gm_screen"), "gm_screen")'


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"SELF-CHECK FAILED: {message}")


def require_text(path: Path, fragments: tuple[str, ...]) -> None:
    text = path.read_text(encoding="utf-8")
    missing = [fragment for fragment in fragments if fragment not in text]
    if missing:
        fail(f"{path.name} is missing required desktop-window contract text: {missing}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source-root", type=Path, required=True)
    p.add_argument("--factory", type=Path, required=True)
    p.add_argument("--foundation", type=Path, required=True)
    p.add_argument("--portable-root", type=Path)
    args = p.parse_args()
    root = args.source_root.resolve()

    required_source = (
        "packaging/windows_portable/TianxiaFactory.spec",
        "packaging/windows_portable/portable_launcher.py",
        "packaging/windows_portable/requirements-build.txt",
        "packaging/windows_portable/Verify-WindowsPortable.ps1",
        "app/runtime.py",
        str(CATALOG_AUTHORITY_SOURCE),
        str(TYPED_AUTHORITY_SOURCE),
        str(SPHERE_TALENT_UI_SOURCE),
        str(GM_SCREEN_SOURCE),
        "static/index.html",
        "static/app.js",
        "static/combat_visuals/manifest.json",
        "combat/history_feed.py",
        "combat_gate1/generated/Battlefield.json",
        "combat_gate1/generated/Encounter.json",
        "combat_gate2/generated/Gate2_Executable_Mechanics_Lock.json",
        "combat_gate2/generated/Gate2_Universal_Combat_Defaults_Lock.json",
        "combat_gate4/policies/generic_fallback_policy.json",
        "non_sphere_authority/authority/NS1R_AUTHORITY_IDENTITIES.json",
        "projector/contracts/C2AR1_Stage2_v3_Projection_Contract.json",
        "authority/Tianxia_Core_Character_Baseline_Authority_Pack_R1.json",
    )
    for rel in required_source:
        if not (root / rel).is_file():
            fail(f"missing prepared source file: {rel}")

    require_text(
        root / "packaging/windows_portable/portable_launcher.py",
        (
            'APP_LABEL = "Tianxia Factory"',
            'WINDOW_HOST = "pywebview-edgechromium"',
            'sock.bind(("127.0.0.1", 0))',
            'gui="edgechromium"',
            'storage_path=str(self.paths.webview_data)',
            'webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False',
            'default_browser_launch_attempted": False',
        ),
    )
    require_text(
        root / "packaging/windows_portable/requirements-build.txt",
        ("pywebview==6.2.1", "pythonnet==3.0.5"),
    )
    require_text(
        root / "packaging/windows_portable/TianxiaFactory.spec",
        ('"webview.platforms.edgechromium"', '"webview.platforms.winforms"', 'console=False'),
    )
    require_text(
        root / "packaging/windows_portable/Verify-WindowsPortable.ps1",
        (
            "default-browser-observation.json",
            "windows-desktop-window-acceptance.json",
            "MainWindowTitle",
            "no_orphan_factory_process",
        ),
    )

    if digest(args.factory) != FACTORY_SHA:
        fail("Factory input identity mismatch")
    if digest(args.foundation) != FOUNDATION_SHA:
        fail("Foundation handoff identity mismatch")
    if os.name != "nt":
        fail("native Windows is required for executable build and acceptance")

    result: dict[str, object] = {
        "status": "PASS",
        "python": sys.version,
        "platform": sys.platform,
        "desktop_window_source_contract": "PASS",
    }

    if args.portable_root:
        portable = args.portable_root.resolve()
        required = [
            portable / "Tianxia Factory.exe",
            portable / "Runtime" / "PrivatePython" / "python.exe",
            portable / "Runtime" / "PrivatePython" / "python3.exe",
            portable / "BundledContent" / args.factory.name,
            portable / "BundledContent" / args.foundation.name,
            portable / "README_FIRST_RUN.txt",
            portable / "VERSION.json",
            portable / "UserData",
            portable / CATALOG_AUTHORITY_RUNTIME,
            portable / TYPED_AUTHORITY_RUNTIME,
            portable / "Runtime" / "character_sheet" / "contracts" / "Tianxia_Character_Sheet_Readiness_Profile_R1.json",
            portable / "Runtime" / "factory_authoring" / "contracts",
            portable / "Runtime" / "combat" / "character_authority",
            portable / "Runtime" / "combat" / "pre_encounter.py",
            portable / "Runtime" / "combat" / "character_runtime_adapter.py",
            portable / "Runtime" / "catalog_authority" / "cat1" / "data" / "canonical_spheres.v1.json",
            portable / "Runtime" / "non_sphere_authority" / "authority" / "NS1R_AUTHORITY_IDENTITIES.json",
            portable / "Runtime" / "non_sphere_authority" / "authority" / "open_ended_compatibility_resolver.py",
            portable / "Runtime" / "projector" / "contracts" / "C2AR1_Stage2_v3_Projection_Contract.json",
            portable / "Runtime" / "authority" / "Tianxia_Core_Character_Baseline_Authority_Pack_R1.json",
            portable / "Runtime" / "R6_6_9_2_C3B_STATUS.json",
            portable / "Runtime" / "BundledContent" / args.factory.name,
            portable / "Runtime" / "gm_export" / "exact_consumer_harness.py",
            portable / "Runtime" / "app" / "authorities.py",
            portable / "Runtime" / "app" / "core.py",
            portable / SPHERE_TALENT_UI_RUNTIME,
            portable / GM_SCREEN_RUNTIME,
            portable / "Runtime" / "static" / "combat_visuals" / "manifest.json",
            portable / "Runtime" / "combat_gate1" / "generated" / "Battlefield.json",
            portable / "Runtime" / "combat_gate1" / "generated" / "Encounter.json",
            portable / "Runtime" / "combat_gate2" / "generated" / "Gate2_Executable_Mechanics_Lock.json",
            portable / "Runtime" / "combat_gate2" / "generated" / "Gate2_Universal_Combat_Defaults_Lock.json",
            portable / "Runtime" / "combat_gate4" / "policies" / "generic_fallback_policy.json",
        ]
        missing = [str(x) for x in required if not x.exists()]
        if missing:
            fail("portable tree is incomplete: " + ", ".join(missing))

        excluded_visuals = [
            portable / "Runtime" / "static" / "combat_visuals" / name
            for name in (
                "heavenly_arena_r1.png",
                "an_eui_r1.png",
                "lee_jia_r1.png",
                "ling_qi_r1.png",
                "bai_meizhen_r1.png",
            )
        ]
        if any(path.exists() for path in excluded_visuals):
            fail("provenance-uncertain combat artwork was included in the portable tree")

        packaged_catalog = portable / CATALOG_AUTHORITY_RUNTIME
        source_catalog = root / CATALOG_AUTHORITY_SOURCE
        if digest(packaged_catalog) != digest(source_catalog):
            fail("packaged catalog authority identity differs from the sealed source")

        if digest(portable / TYPED_AUTHORITY_RUNTIME) != digest(root / TYPED_AUTHORITY_SOURCE):
            fail("packaged typed authority identity differs from the sealed source")

        if digest(portable / "Runtime" / "BundledContent" / args.factory.name) != digest(args.factory):
            fail("runtime canonical-authority corpus identity differs from the pinned Factory input")

        packaged_ui_logic = portable / SPHERE_TALENT_UI_RUNTIME
        source_ui_logic = root / SPHERE_TALENT_UI_SOURCE
        if digest(packaged_ui_logic) != digest(source_ui_logic):
            fail("packaged Sphere/Talent UI logic identity differs from the sealed source")

        packaged_gm_screen = portable / GM_SCREEN_RUNTIME
        source_gm_screen = root / GM_SCREEN_SOURCE
        if digest(packaged_gm_screen) != digest(source_gm_screen):
            fail("packaged GM Screen authority identity differs from the sealed source")

        names = {path.name.casefold() for path in portable.rglob("*") if path.is_file()}
        required_webview_files = {
            "microsoft.web.webview2.core.dll",
            "microsoft.web.webview2.winforms.dll",
            "python.runtime.dll",
        }
        missing_webview = sorted(required_webview_files - names)
        if missing_webview:
            fail("desktop WebView2 host runtime files are missing: " + ", ".join(missing_webview))

        forbidden = []
        for path in portable.rglob("*"):
            low = path.name.casefold()
            if low in {"tests", "reports", "__pycache__", ".pytest_cache"} or path.suffix in {".pyc", ".pyo"}:
                forbidden.append(str(path.relative_to(portable)))
        if forbidden:
            fail("development payload leaked into portable tree: " + ", ".join(forbidden[:20]))

        user_data_files = [str(path.relative_to(portable)) for path in (portable / "UserData").rglob("*") if path.is_file()]
        if user_data_files:
            fail("generated UserData was present before native acceptance: " + ", ".join(user_data_files[:20]))

        result.update(
            {
                "portable_tree": str(portable),
                "webview2_host_files": sorted(required_webview_files),
                "clean_initial_user_data": True,
            }
        )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
