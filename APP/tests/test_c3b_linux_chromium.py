from pathlib import Path

from tests.c3b_browser_harness import run

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/M1/C1A_Clean_Fire_Qi_Proof_Character_Combat_Runtime_Ready.zip"


def test_c3b_linux_chromium_acceptance(tmp_path: Path):
    output = tmp_path / "C3B_LINUX_CHROMIUM_ACCEPTANCE.json"
    report = run(root=ROOT, character=FIXTURE, output=output, browser="/usr/bin/chromium")
    assert report["status"] == "PASS", report
