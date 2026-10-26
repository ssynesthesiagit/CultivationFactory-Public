"""Refresh optimizations preserve live text inputs and persisted table output."""
from copy import deepcopy
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from combat import action_text, factory_compiler, player_text, status_text, tabletop
from tests.h48_table_support import fixture, assert_reload_verify_replay


@pytest.fixture(autouse=True)
def empty_caches(monkeypatch):
    for function in (player_text._clean_string, player_text._plain_string, action_text._layout_resolved):
        function.cache_clear()
    for name in ("_MECHANIC_NAMES", "_AUTHORITY_INDEX", "_OWNED_KEYS", "_TOGGLE_OWNERS"):
        monkeypatch.setattr(tabletop, name, {})


def test_cleanup_keys_the_entire_rendered_input_and_accepts_mutable_values():
    inputs = [None, False, 0, [], {}, "**Cost:** None\nDeal 1d6 damage.",
              "**Cost:** 2 CP\nDeal 2d6 damage.", ["mutable"]]
    for value in inputs:
        text = str(value or "")
        assert player_text.clean(value) == player_text._clean_string.__wrapped__(text)
        assert player_text.plain(value) == " ".join(player_text._clean_string.__wrapped__(text).split())
    hits = player_text._clean_string.cache_info().hits
    player_text.clean(inputs[-1])
    assert player_text._clean_string.cache_info().hits == hits + 1
    inputs[-1].append("changed")
    assert "changed" in player_text.clean(inputs[-1])
    # Card/log modes must not share the suppression of printed damage bands.
    bands = "Damage: CL 1-4: 1d8. CL 5-10: 2d8."
    assert "1d8" in player_text.clean(bands)
    assert "1d8" not in player_text.log_text(bands)


def test_layout_cache_keeps_subject_markup_and_every_extra_and_returns_fresh_lists():
    original = action_text._layout_resolved("First", "Cost: 1 Qi\nEffect: Deal damage.", ("Once per turn.",))
    for subject, markup, extra in (
        ("Second", "Cost: 1 Qi\nEffect: Deal damage.", ("Once per turn.",)),
        ("First", "Cost: 2 Qi\nEffect: Deal damage.", ("Once per turn.",)),
        ("First", "Cost: 1 Qi\nEffect: Deal damage.", ("Once per round.",)),
    ):
        result = action_text._layout_resolved(subject, markup, extra)
        assert result == action_text._layout_resolved.__wrapped__(subject, markup, extra)
        assert result != original
    row = {"display_name": "First", "parameters": {"description": "Effect: Deal damage."}}
    expected = action_text.layout_action(row, extra=["Once per turn."])
    broken = action_text.layout_action(row, extra=["Once per turn."])
    broken["fields"][0]["value"] = "poisoned"
    broken["body"].append("poisoned")
    assert action_text.layout_action(row, extra=["Once per turn."]) == expected


def test_resolution_is_live_before_cached_formatting(monkeypatch):
    from combat import ext
    hook_text = ["Effect: Push 5 feet."]
    monkeypatch.setattr(ext, "run", lambda point, row: list(hook_text) if point == "button_description" else [])
    row = {"display_name": "Choice", "parameters": {}}
    first = action_text.layout_action(row)
    assert action_text.layout_action(row) == first
    hook_text[0] = "Effect: Push 10 feet."
    assert "10 feet" in action_text.layout_action(row)["text"]
    row["parameters"]["description"] = "Cost: 1 CP\nEffect: Heal 5 hit points."
    monkeypatch.setattr(ext, "run", lambda *args: [])
    assert "Heal 5" in action_text.layout_action(row)["text"]
    del row["parameters"]["description"]
    fallback = ["Effect: Restore 1 hit point."]
    assert "Restore 1" in action_text.layout_action(row, fallback=lambda _: fallback[0])["text"]
    fallback[0] = "Effect: Restore 2 hit points."
    assert "Restore 2" in action_text.layout_action(row, fallback=lambda _: fallback[0])["text"]
    texts = {"one": "Effect: First source.", "two": "Effect: Second source."}
    monkeypatch.setattr(status_text, "printed_rules", lambda: texts)
    row["parameters"]["typed"] = {"source": "one"}
    assert "First source" in action_text.layout_action(row)["text"]
    row["parameters"]["typed"]["source"] = "two"
    assert "Second source" in action_text.layout_action(row)["text"]
    texts["two"] = "Effect: Revised source."
    assert "Revised source" in action_text.layout_action(row)["text"]


def test_usage_names_projection_reads_only_requested_keys_and_current_values():
    class NoScan(dict):
        def items(self):
            raise AssertionError("must not scan the authority for one modifier")
    rows = NoScan({"a": {"name": "First"}, "b": {"name": None}})
    view = tabletop._AuthorityNames(rows)
    assert view.get("a") == "First"
    assert view.get("b") is None and view.get("missing") is None
    rows["a"]["name"] = "Changed"
    assert view.get("a") == "Changed"


def test_unscoped_name_lookup_keeps_the_rows_returned_before_a_concurrent_reload(monkeypatch):
    old = {"a": "shared", "b": "shared"}
    monkeypatch.setattr(tabletop, "_mechanic_names", lambda: old)
    tabletop._MECHANIC_NAMES.update(rows={"b": "shared"}, first={"shared": "b"})
    assert tabletop._mechanic_key("shared") == "a"


def test_prepared_ownership_keeps_empty_and_changed_sets_distinct(monkeypatch):
    monkeypatch.setattr(tabletop, "_mechanic_names", lambda: {"a": "shared", "b": "shared"})
    monkeypatch.setattr(tabletop, "_authority_index", lambda: {
        "a": {"description": "First"}, "b": {"description": "Second"}})
    for ids in (frozenset(), frozenset({"a"}), frozenset({"b"}), frozenset({"b.child"})):
        expected = tabletop._toggle_owner("Shared: choose", {"owned_ids": list(ids)})
        assert tabletop._toggle_owner("Shared: choose", {}, owned_ids=ids) == expected


def test_single_condition_reader_matches_catalog_and_tracks_reading_and_rule_edits(monkeypatch):
    from combat import condition_text
    table = condition_text.all_conditions()
    for key, row in table.items():
        assert condition_text.condition_reading(key) == (row["name"], row["reading"])
    key = "sol135_test_reading"
    assert condition_text.condition_reading(key) is None
    monkeypatch.setitem(condition_text.READING, key, "Cannot move.")
    assert condition_text.condition_reading(key)[1] == "Cannot move."
    monkeypatch.setitem(condition_text.READING, key, "Cannot speak.")
    assert condition_text.condition_reading(key)[1] == "Cannot speak."
    source = condition_text.rules()
    changed = {**source, "conditions": {**source.get("conditions", {}), "sol135_test_rule": {"_rule": "Cannot move."}}}
    monkeypatch.setattr(condition_text, "rules", lambda: changed)
    assert condition_text.condition_reading("sol135_test_rule")[1] == "Cannot move."
    monkeypatch.setattr(condition_text, "rules", lambda: source)
    assert condition_text.condition_reading("sol135_test_rule") is None


def test_attack_modifier_description_uses_single_readings_without_catalog_copies(monkeypatch):
    from combat import condition_text
    from combat.ext import attack_modifiers
    options = [{"effects": [{"type": "condition", "condition": "prone"}]}]
    expected = attack_modifiers.description(options)
    monkeypatch.setattr(condition_text, "all_conditions", lambda: pytest.fail("must not copy the complete catalog"))
    assert attack_modifiers.description(options) == expected
    monkeypatch.setitem(condition_text.READING, "prone", "A revised condition explanation.")
    assert "A revised condition explanation" in attack_modifiers.description(options)


@pytest.mark.parametrize("change", ["name", "rules", "replace", "switch"])
def test_authority_indexes_invalidate_even_when_mtime_is_preserved(tmp_path, monkeypatch, change):
    root = tmp_path / "first"
    root.mkdir()
    authority = root / "authority.json"
    rules = root / "typed_mechanics" / "rules_text.json"
    rules.parent.mkdir()
    authority.write_text(json.dumps({"mechanics": {"a": {"name": "Same"}, "b": {"name": "Same"}}}))
    rules.write_text(json.dumps({"a": "Old rule", "b": "Other rule"}))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", authority)
    assert tabletop._mechanic_key("same") == "a"  # first duplicate stays first
    row = {"display_name": "Same", "source_definition_id": "action:unknown"}
    assert tabletop._compiled_description(row) == "Old rule"
    old_stamp = authority.stat().st_mtime_ns
    if change == "rules":
        stamp = rules.stat().st_mtime_ns
        rules.write_text(json.dumps({"a": "New rule", "b": "Other rule"}))
        os.utime(rules, ns=(stamp, stamp))
        assert tabletop._compiled_description(row) == "New rule"
        return
    new = json.dumps({"mechanics": {"b": {"name": "Same"}, "a": {"name": "Gone"}}})
    if change == "replace":
        replacement = root / "replacement.json"
        replacement.write_text(new)
        os.utime(replacement, ns=(old_stamp, old_stamp))
        replacement.replace(authority)
    elif change == "switch":
        other = tmp_path / "second"
        other.mkdir()
        authority = other / "authority.json"
        authority.write_text(new)
        (other / "typed_mechanics").mkdir()
        (other / "typed_mechanics" / "rules_text.json").write_text(rules.read_text())
        monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", authority)
    else:
        authority.write_text(new)
    os.utime(authority, ns=(old_stamp, old_stamp))
    assert tabletop._mechanic_key("same") == "b"
    assert tabletop._compiled_description(row) == "Other rule"


def test_dot_prefix_resolution_matches_original_longest_scan(tmp_path, monkeypatch):
    index = {"abc": {"description": "Short"}, "abc.def": {"description": "Long"}}
    monkeypatch.setattr(tabletop, "_authority_index", lambda: index)
    monkeypatch.setattr(tabletop, "_mechanic_key", lambda name: None)
    for suffix in ("abc.def.option", "abc.other", "abcde.option", "abc.def", "unknown"):
        row = {"source_definition_id": "action:typed.test." + suffix}
        key = suffix if suffix in index else next((k for k in sorted(index, key=len, reverse=True)
                                                   if suffix.startswith(k + ".")), None)
        assert tabletop._compiled_description(row) == (index.get(key) or {}).get("description", "")


def test_request_snapshot_reuses_assets_and_keeps_concurrent_versions_separate(tmp_path, monkeypatch):
    authority = tmp_path / "authority.json"
    rules = tmp_path / "typed_mechanics" / "rules_text.json"
    rules.parent.mkdir()
    authority.write_text(json.dumps({"mechanics": {"a": {"name": "Hidden"}, "b": {"name": "Other"}}}))
    rules.write_text(json.dumps({"a": "Old rule", "b": "New rule"}))
    monkeypatch.setattr(factory_compiler, "TYPED_AUTHORITY", authority)
    identities = []
    identity = tabletop._text_file_identity
    def counted(path):
        identities.append(path)
        return identity(path)
    monkeypatch.setattr(tabletop, "_text_file_identity", counted)
    character = {"owned_ids": ["a", "b"]}
    def read():
        with tabletop.text_snapshot():
            return tabletop._toggle_description("Hidden: choose", character)
    with tabletop.text_snapshot():
        old = tabletop._toggle_description("Hidden: choose", character)
        checks = len(identities)
        with tabletop.text_snapshot():
            assert tabletop._toggle_description("Hidden: choose", character) == old
        assert len(identities) == checks
        authority.write_text(json.dumps({"mechanics": {"a": {"name": "Other"}, "b": {"name": "Hidden"}}}))
        # A second request loads the new version without replacing this request's
        # retained rows or giving its old answer the second request's cache key.
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert "New rule" in pool.submit(read).result()
        assert tabletop._toggle_description("Hidden: choose", character) == old
    assert "New rule" in read()
    with pytest.raises(RuntimeError):
        with tabletop.text_snapshot():
            raise RuntimeError("read failed")
    assert tabletop._TEXT_SNAPSHOT.get() is None


def test_persisted_table_cold_warm_and_after_action_match_uncached_text(tmp_path, monkeypatch):
    combat, table, mid, _, commit = fixture(tmp_path, [], seed="SOL135", path_features=(
        "tianxia.path.body_refining.feature.core_tempering_expression",))
    def uncached():
        with monkeypatch.context() as patch:
            for module, name in ((player_text, "_clean_string"), (player_text, "_plain_string"),
                                 (action_text, "_layout_resolved")):
                patch.setattr(module, name, getattr(module, name).__wrapped__)
            return table.state(mid)
    before = uncached()
    owner_sets = []
    # Native selectors now resolve through action_text before this fallback.
    # Observe ownership preparation where the service actually needs it, even
    # when the remaining fallback is a built-in rather than a legacy selector.
    resolve_owner = tabletop.untyped_button_text
    def observe_owner(row, bundle=None, *, owned_ids=None):
        owner_sets.append(owned_ids)
        return resolve_owner(row, bundle, owned_ids=owned_ids)
    monkeypatch.setattr(tabletop, "untyped_button_text", observe_owner)
    assert table.state(mid) == table.state(mid) == before
    assert owner_sets and all(isinstance(ids, frozenset) for ids in owner_sets)
    assert action_text._layout_resolved.cache_info().hits > 0
    session = combat._load_session(mid)
    row = next(a.model_dump(mode="json") for a in session.engine.action_catalog.values() if a.costs)
    original = tabletop.engine_button_layout(row)
    changed = deepcopy(row)
    changed["costs"][0][1] += 1
    changed["parameters"]["description"] = "Cost: 1 CP\nEffect: Deal damage."
    first = tabletop.engine_button_layout(changed)
    changed["costs"][0][1] += 1
    assert tabletop.engine_button_layout(changed) != first
    changed["parameters"]["typed"] = {"once_per_turn": True}
    assert "Once per turn" in tabletop.engine_button_layout(changed)["text"]
    changed["parameters"]["typed"] = {"once": "round"}
    assert "Once per round" in tabletop.engine_button_layout(changed)["text"]
    assert tabletop.engine_button_layout(row) == original
    commit(before["menu"]["end_turn"])
    assert table.state(mid) == uncached()
    assert_reload_verify_replay(combat, mid, tmp_path)
