"""CAICLANLOCK1 CI guard: changed supplement content needs a pack_version bump.

Each supplement pack's computed content hash must match the checked-in record
catalog/supplement_pack_hashes.json for its pack_version. Regenerate the record with
`python -m catalog.supplement_hashes --factory-root <Factory> --owner-root <APP> --write`
after bumping a pack_version. The core pack is covered by its pinned pack hashes.
"""
import json
import shutil
from pathlib import Path

from catalog.supplement_hashes import (
    RECORD_PATH,
    current_supplement_hashes,
    load_record,
    version_problems,
)

ROOT = Path(__file__).resolve().parents[1]
OWNER_DIR = "non_sphere_authority/authority/owner_subpaths.d"


def test_checked_in_supplement_hashes_match_shipped_content(factory_environment):
    current = current_supplement_hashes(factory_environment["root"], ROOT)
    problems = version_problems(current, load_record(RECORD_PATH))
    assert not problems, "\n".join(problem["message"] for problem in problems)


def test_owner_content_change_without_version_bump_fails_guard(factory_environment, tmp_path):
    owner = tmp_path / "owner"
    shutil.copytree(ROOT / OWNER_DIR, owner / OWNER_DIR)
    recorded = load_record(RECORD_PATH)
    document_path = next((owner / OWNER_DIR).glob("*.json"))
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["entries"][0]["display_name"] = document["entries"][0]["display_name"] + " (edited)"
    document_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    current = current_supplement_hashes(factory_environment["root"], owner)
    problems = version_problems(current, recorded)
    assert problems, "changed owner content must not pass without a pack_version bump"
    assert any("bump the pack_version" in problem["message"] for problem in problems)
    assert all(problem["pack_version"] == document["pack_version"] for problem in problems)


def test_new_pack_version_without_checked_in_record_fails_guard(factory_environment, tmp_path):
    owner = tmp_path / "owner"
    shutil.copytree(ROOT / OWNER_DIR, owner / OWNER_DIR)
    document_path = next((owner / OWNER_DIR).glob("*.json"))
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["pack_version"] = "99.0.0"
    document_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    problems = version_problems(current_supplement_hashes(factory_environment["root"], owner), load_record(RECORD_PATH))
    assert any(problem["pack_version"] == "99.0.0" and "bump the pack_version" in problem["message"] for problem in problems)
