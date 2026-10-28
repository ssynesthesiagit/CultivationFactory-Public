"""Publication privacy and browser-free GM sheet fixture contracts."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest


TESTS = Path(__file__).resolve().parent
FIXTURES = TESTS / "fixtures" / "gm_sheet"


def test_scratch_fixtures_use_only_synthetic_installation_identifiers():
    library = json.loads((FIXTURES / "scratch_library_rows.fixture.json").read_text())
    # Fixture ids are decimal-counted (..000000000010 is row 10), not hex (..00000000000a).
    expected_ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 11)]
    assert [row["project_id"] for row in library["rows"]] == expected_ids
    for name in ("scratch_library_rows.fixture.json", "scratch_owner_sheet_snapshot.fixture.json"):
        text = (FIXTURES / name).read_text()
        comment = json.loads(text)["_comment"]
        assert "persisted owner" not in comment.lower()
        assert not re.search(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", comment)
        assert not re.search(r"/home/|/Users/|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b20\d{2}-\d{2}-\d{2}", text)
        assert set(re.findall(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", text)) <= set(expected_ids)


@pytest.mark.parametrize("script", ["gm_sheet_renderer_dom.test.mjs", "gm_sheet_view_model.test.mjs"])
def test_scratch_gm_sheet_node_contracts(script):
    node = shutil.which("node")
    assert node is not None, "Node is required to verify the public Scratch sheet contracts"
    subprocess.run([node, "--test", str(TESTS / script)], cwd=TESTS.parent, check=True)
