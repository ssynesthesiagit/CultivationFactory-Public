"""Finding 1 regression (MGR-T15 Oath-Skin Frame review F11R): ButtonStore keeps its id guard.

The F11 branch once widened ButtonStore._path to accept any alphanumeric id to fix a
test fixture. That loosened a persistence guard. This file pins the strict rule:
only lowercase hex and dashes, 8-64 characters, so no path separator, dot segment or
upper-case id can reach the filesystem. Synthetic ids only; no owner data.
"""
import pytest

from combat.tabletop import ButtonStore, TabletopError

VALID = "0123abcd-4567-89ef"

UNSAFE = [
    "",
    "..",
    "../escape",
    "a/b",
    "0123abcd/../../x",
    "0123abcd\\x",
    "0123abcd.json",
    "0123abcd%2e%2e",
    "0123ABCD-4567-89EF",
    "short",
    "0123abcd" * 9,
]


def test_valid_hex_id_maps_inside_the_store_root(tmp_path):
    store = ButtonStore(tmp_path / "buttons")
    path = store._path(VALID)
    assert path == tmp_path / "buttons" / f"{VALID}.json"


@pytest.mark.parametrize("project_id", UNSAFE)
def test_unsafe_ids_are_refused_before_any_file_access(tmp_path, project_id):
    store = ButtonStore(tmp_path / "buttons")
    with pytest.raises(TabletopError) as refused:
        store.get(project_id)
    assert refused.value.code == "CHARACTER_UNKNOWN"
    assert refused.value.status_code == 404
    assert not (tmp_path / "buttons").exists()
