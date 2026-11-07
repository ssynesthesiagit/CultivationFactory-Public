"""Independent resolver parity, cache identity, and persisted table refreshes."""
import json
import os
import sys
from time import perf_counter

import pytest

from combat import factory_compiler, tabletop
from tests.h1_support import bundle
from tests.h48_table_support import fixture

CTE = "tianxia.path.body_refining.feature.core_tempering_expression"
PUPPET = "tianxia.talent.puppetry.long_silk_thread"
PULSE = "tianxia.talent.formations.harmonized_pulse"


@pytest.fixture(autouse=True)
def isolated_caches(monkeypatch):
    for name in ("_TOGGLE_OWNERS", "_OWNED_KEYS", "_MECHANIC_NAMES", "_AUTHORITY_INDEX"):
        monkeypatch.setattr(tabletop, name, {})


def uncached_owner(name, character, *, owned_ids=None):
    """Pre-PERF1 search over source files, independent of all presentation caches."""
    # Accept the refresh's optional ownership projection, but deliberately
    # rebuild it from the original bundle to verify that projection independently.
    feature, _, option = str(name).partition(":")
    if not option:
        return None
    wanted = " ".join(feature.lower().split())
    path = factory_compiler.TYPED_AUTHORITY
    records = json.loads(path.read_text())["mechanics"]
    rules = json.loads((path.parent / "typed_mechanics" / "rules_text.json").read_text())
    names = {key: " ".join(str(row.get("name") or "").lower().split())
             for key, row in records.items()}
    owned = {str(row.get("source_definition_id") or "").split(".", 2)[-1]
             for row in character.get("action_catalog") or []}
    owned.update(str(key) for key in character.get("owned_ids") or character.get("mechanic_ids") or [])
    def mine(key):
        return key in owned or any(own.startswith(key) for own in owned)
    matches = [key for key, value in names.items() if value == wanted]
    if not matches:
        matches = sorted((key for key, value in names.items() if f" {wanted} " in f" {value} "),
                         key=lambda key: len(names[key]))
    owner = next((key for key in matches if mine(key)), matches[0] if matches else None)
    if owner is not None:
        return owner
    for key in sorted(records):
        row = records[key]
        description = rules.get(key) or ("\n".join(map(str, row.get("description") or []))
                                        if isinstance(row.get("description"), list)
                                        else str(row.get("description") or ""))
        if mine(key) and wanted in " ".join(description.lower().split()):
            return key
    return None


def test_real_compiled_buttons_match_independent_search_across_characters():
    characters = [bundle(ids, actor_id=f"actor:perf{i}")
                  for i, ids in enumerate(([CTE], [CTE, PUPPET], [PUPPET], [PULSE], []))]
    labels = sorted({row["display_name"] for character in characters
                     for row in character["action_catalog"] if ":" in row["display_name"]})
    assert "Core Tempering Expression: Golden Bell Circulation" in labels
    assert "Thread the Object: move object" in labels
    assert "Harmonized Pulse: strengthen Suppressing Vein" in labels
    answers = []
    for character in characters:
        for label in labels:
            expected = uncached_owner(label, character)
            assert tabletop._toggle_owner(label, character) == expected, (label, character["actor_id"])
            answers.append(expected)
    assert CTE in answers and "PUPPETRY_BASE_THREAD_THE_OBJECT" in answers and PULSE in answers
    assert None in answers


class CountedRows(dict):
    """Count full resolver scans, rather than asserting elapsed time on a shared host."""
    scans = 0

    def items(self):
        self.scans += 1
        return super().items()

    def __iter__(self):
        self.scans += 1
        return super().__iter__()


def test_ownership_changes_same_button_and_character_and_reuses_answers(monkeypatch):
    names = CountedRows({"a": "shared feature", "b": "shared feature",
                         "c": "another feature"})
    index = CountedRows({"a": {"description": "Hidden selector"},
                         "b": {"description": "Hidden selector"}, "c": {"description": "Other"}})
    monkeypatch.setattr(tabletop, "_mechanic_names", lambda: names)
    monkeypatch.setattr(tabletop, "_authority_index", lambda: index)
    character = {"actor_id": "actor:same", "owned_ids": ["a"]}
    for owned, expected in ((["a"], "a"), (["b"], "b"), (["c"], None), ([], None), (["a", "b"], "a")):
        character["owned_ids"] = owned
        assert tabletop._toggle_owner("Hidden selector: pick", character) == expected
        scans = names.scans, index.scans
        for _ in range(3):
            assert tabletop._toggle_owner("Hidden selector: pick", character) == expected
        assert (names.scans, index.scans) == scans, "warm hits must skip resolver scans, including cached None"
    character["owned_ids"] = ["b.child"]
    assert tabletop._toggle_owner("Shared feature: pick", character) == "b"
    assert tabletop._toggle_owner("No such feature: pick", character) is None
    assert tabletop._toggle_owner("Plain button", character) is None


@pytest.mark.parametrize("changed_file", ["authority", "rules_text"])
def test_file_mtime_invalidates_owner_and_owned_subset(tmp_path, monkeypatch, changed_file):
    authority = tmp_path / "authority.json"
    rules = tmp_path / "typed_mechanics" / "rules_text.json"
    rules.parent.mkdir()
    authority.write_text(json.dumps({"mechanics": {"a": {"name": "Other"}, "b": {"name": "Other"}}}))
    rules.write_text(json.dumps({"a": "Hidden selector", "b": "No match"}))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", authority)
    character = {"owned_ids": ["a", "b"]}
    label = "Hidden selector: pick"
    assert tabletop._toggle_owner(label, character) == "a"
    assert uncached_owner(label, character) == "a"
    changed = authority if changed_file == "authority" else rules
    old_time = changed.stat().st_mtime_ns
    if changed_file == "authority":
        authority.write_text(json.dumps({"mechanics": {"b": {"name": "Hidden selector"}}}))
    else:
        rules.write_text(json.dumps({"a": "No match", "b": "Hidden selector"}))
    os.utime(changed, ns=(old_time + 1_000_000_000, old_time + 1_000_000_000))
    assert uncached_owner(label, character) == "b"
    assert tabletop._toggle_owner(label, character) == "b"
    assert tabletop._toggle_owner(label, character) == "b"
    if changed_file == "authority":
        assert all("a" not in keys for (_, stamp), keys in tabletop._OWNED_KEYS.items()
                   if stamp == tabletop._AUTHORITY_INDEX["mtime"])


def test_persisted_table_state_matches_uncached_cold_and_warm(tmp_path, monkeypatch):
    _, table, match_id, _, _ = fixture(tmp_path, [PUPPET], seed="perf1r1", path_features=(CTE,))
    # The shared formatter now supplies selector rules directly. Explicitly
    # exercise the missing-description fallback this cache test is about.
    describe = tabletop.engine_button_description
    monkeypatch.setattr(tabletop, "engine_button_description", lambda row:
                        "" if "Core Tempering Expression:" in row.get("display_name", "") else describe(row))
    with monkeypatch.context() as baseline_patch:
        baseline_patch.setattr(tabletop, "_toggle_owner", uncached_owner)
        baseline = table.state(match_id)
    tabletop._TOGGLE_OWNERS.clear()
    tabletop._OWNED_KEYS.clear()
    # Other presentation readers also iterate keys; count only resolver-owned subset work.
    class OwnedScans(dict):
        scans = 0
        def __iter__(self):
            if sys._getframe(1).f_code.co_name == "_toggle_owner":
                self.scans += 1
            return super().__iter__()
    rows = OwnedScans(tabletop._authority_index())
    tabletop._AUTHORITY_INDEX["rows"] = rows
    start = perf_counter()
    cold = table.state(match_id)
    cold_seconds = perf_counter() - start
    assert rows.scans > 0 and tabletop._TOGGLE_OWNERS
    scans = rows.scans
    start = perf_counter()
    warm = table.state(match_id)
    warm_seconds = perf_counter() - start
    assert rows.scans == scans, "warm refresh must not rebuild any owned-authority subset"
    assert baseline == cold == warm
    labels = {group["label"]: group["description"] for group in warm["menu"]["actions"]}
    for option in ("Golden Bell Circulation", "Blood-Furnace Circulation", "Mountain-Rending Pulse"):
        assert f"This button picks: {option}." in labels[f"Core Tempering Expression: {option}"]
    assert labels["Dodge"]
    print(f"PERF1r1 test-built table: cold={cold_seconds:.3f}s warm={warm_seconds:.3f}s; owned scans={scans}-> {rows.scans}")
