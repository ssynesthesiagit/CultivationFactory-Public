from pathlib import Path

from app.core import Database, Settings
from portable_character.service import PortableCharacterPackageService
from product_bootstrap import ProductBootstrapService
from tests.c3br1_browser_harness import run

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/M1/C1A_Clean_Fire_Qi_Proof_Character_Combat_Runtime_Ready.zip"


def test_c3br1_linux_chromium_clean_root_owner_flow(tmp_path: Path):
    data = tmp_path / "clean root browser data"
    settings = Settings.from_env(ROOT, data)
    ProductBootstrapService(settings).run()
    PortableCharacterPackageService(Database(settings)).import_into_factory(FIXTURE)
    report = run(root=ROOT, data=data, output=tmp_path / "C3BR1_LINUX_CHROMIUM_ACCEPTANCE.json", browser="/usr/bin/chromium")
    assert report["status"] == "PASS", report
