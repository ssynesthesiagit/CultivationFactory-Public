from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_saved_draft_resume_visibility():
    subprocess.run(["node", "--test", "tests/resumecancel1_library.test.mjs"], cwd=ROOT, check=True)
