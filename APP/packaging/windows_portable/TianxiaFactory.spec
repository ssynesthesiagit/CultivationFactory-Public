# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]

datas = [
    (str(ROOT / "static"), "static"),
    (str(ROOT / "schemas"), "schemas"),
    (str(ROOT / "contracts"), "contracts"),
    (str(ROOT / "migrations"), "migrations"),
    (str(ROOT / "catalog"), "catalog"),
    (str(ROOT / "character_sheet" / "contracts"), "character_sheet/contracts"),
    (str(ROOT / "factory_authoring" / "contracts"), "factory_authoring/contracts"),
    (str(ROOT / "combat" / "character_authority"), "combat/character_authority"),
    (str(ROOT / "combat" / "pre_encounter.py"), "combat"),
    (str(ROOT / "combat" / "character_runtime_adapter.py"), "combat"),
    (str(ROOT / "catalog_authority" / "cat3" / "generated"), "catalog_authority/cat3/generated"),
    (str(ROOT / "catalog_authority" / "cat1" / "data"), "catalog_authority/cat1/data"),
    (str(ROOT / "non_sphere_authority" / "authority"), "non_sphere_authority/authority"),
    (str(ROOT / "projector" / "contracts"), "projector/contracts"),
    (str(ROOT / "authority"), "authority"),
    (str(ROOT / "R6_6_9_2_C3B_STATUS.json"), "."),
    (str(ROOT / "gm_export" / "exact_consumer_harness.py"), "gm_export"),
    (str(ROOT / "app" / "__init__.py"), "app"),
    (str(ROOT / "app" / "authorities.py"), "app"),
    (str(ROOT / "app" / "core.py"), "app"),
    (str(ROOT / "gm_screen"), "gm_screen"),
    (str(ROOT / "content_packs" / "trusted_publishers.json"), "content_packs"),
    (str(ROOT / "vendor_adapter" / "runtime_shims"), "vendor_adapter/runtime_shims"),
    (str(ROOT / "combat_gate1" / "generated"), "combat_gate1/generated"),
    (str(ROOT / "combat_gate2" / "generated"), "combat_gate2/generated"),
    (str(ROOT / "combat_gate4" / "policies"), "combat_gate4/policies"),
]

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "clr",
    "pythonnet",
]

a = Analysis(
    [str(ROOT / "packaging" / "windows_portable" / "portable_launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["pytest", "playwright", "tests", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Tianxia Factory",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    contents_directory="Runtime",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Tianxia Factory",
)
