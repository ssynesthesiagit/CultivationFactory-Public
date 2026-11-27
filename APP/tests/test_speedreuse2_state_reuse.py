"""SPEEDREUSE2: a built table state is reused between reads only while nothing it depends on changed.

Synthetic fights only (tests/hunt36_support.py, tests/test_summon_lifetime_saves_and_geometry.py); no owner data, no
live model server (menu ranking uses fake clients or the socket-blocked default).
"""
import json
from types import SimpleNamespace

import pytest

from combat import menu_rank, table_state_cache
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt36_support import LEFT, RIGHT, ROOT, fight, turn
from tests.test_sol157_presets import NULL, sources

BROWSER = dict(fog=True, fog_view="own", fog_actor_ids=(LEFT,), compact_moves=True)


def _bytes(state):
    return json.dumps(state, separators=(",", ":"), ensure_ascii=False)


def _types(value):
    """The Python shape of a value: a reused answer must have the same types as a fresh one (tuples stay tuples)."""
    if isinstance(value, dict):
        return {key: _types(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [type(value).__name__, [_types(item) for item in value]]
    return type(value).__name__


@pytest.fixture
def table_fight(tmp_path, monkeypatch):
    # The owner-editable trees are identified by a test-owned folder here, so a rules edit can be made without
    # touching the program's own files; the production list is checked separately below.
    rules = tmp_path / "editable-rules"
    rules.mkdir()
    (rules / "rules.json").write_text("{}")
    monkeypatch.setattr(table_state_cache, "SHARED_TREES", (rules,))
    combat, table, mid = fight(tmp_path, [NULL], seed="SPEEDREUSE2", primary="Stamina", cl=5)
    turn(combat, table, mid)
    return SimpleNamespace(combat=combat, table=table, mid=mid, rules=rules, root=tmp_path)


def _read(t, kwargs=None):
    return t.table.state(t.mid, **(BROWSER if kwargs is None else kwargs))


def _rebuilt(t, kwargs=None):
    """The next read, asserting it was built rather than reused."""
    misses = t.table._state_reuse.misses
    state = _read(t, kwargs)
    assert t.table._state_reuse.misses == misses + 1, "the change must not be answered from the kept state"
    return state


def test_repeated_reads_are_one_build_and_byte_identical_to_an_uncached_read(table_fight):
    t = table_fight
    for kwargs in (BROWSER, {}, {"include_menu": False, "fog": True}):
        first = _read(t, kwargs)
        hits = t.table._state_reuse.hits
        second = _read(t, kwargs)
        assert t.table._state_reuse.hits == hits + 1
        fresh = TabletopService(CombatService(ROOT, t.root), t.root).state(t.mid, **kwargs)
        assert _bytes(second) == _bytes(first) == _bytes(fresh)
        assert _types(second) == _types(first) == _types(fresh)
        # A reader's change to its copy never reaches the next reader.
        second["presentation"]["actors"].clear()
        if second.get("menu"):
            second["menu"]["actions"] = []
        assert _bytes(_read(t, kwargs)) == _bytes(first)


def test_the_remembered_creature_list_is_part_of_the_request(table_fight):
    """A read that asks about a browser's remembered creatures is a different request from one that asks about none."""
    t = table_fight
    assert _read(t, {"remembered_ids": (LEFT,)})["remembered_in_match"] == [LEFT]
    hits = t.table._state_reuse.hits
    assert _read(t, {"remembered_ids": (LEFT,)})["remembered_in_match"] == [LEFT]
    assert t.table._state_reuse.hits == hits + 1  # the same request is answered from the kept state
    assert _rebuilt(t, {"remembered_ids": ()})["remembered_in_match"] == []


def test_each_kind_of_change_shows_on_the_next_read(table_fight, monkeypatch):
    t = table_fight
    combat, table, mid = t.combat, t.table, t.mid
    state = _read(t)
    assert _read(t)["menu"]["decision_id"] == state["menu"]["decision_id"]

    # A free toggle (a button press in the Options panel) is a commit.
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g.get("shape"))
    pressed = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"], menu["state_version"],
                        state["last_sequence"], defer_menu=True)
    assert pressed["status"] == "COMMITTED"
    toggled = _rebuilt(t)
    assert toggled["menu"]["state_version"] > menu["state_version"]
    assert toggled["button_states"] != state["button_states"] or toggled["shapes"] != state["shapes"]
    _read(t)

    # A saved setting (the sheet's settings batch) is journaled.
    engine = combat._load_session(mid).engine
    reply = table.save_settings(mid, LEFT, sources(engine)[:1], "speedreuse2")
    settled = _rebuilt(t)
    assert settled["menu"]["state_version"] == reply["state_version"] > toggled["menu"]["state_version"]
    _read(t)

    # A saved Ask-me prompt (no journal change) appears, and goes again.
    menu = settled["menu"]
    table._save_pending_action(mid, {"schema": "TabletopPendingAction.v2", "method": "act", "reactions": [],
        "request": {"candidate_id": menu["end_turn"], "decision_id": menu["decision_id"],
                    "state_version": menu["state_version"], "after": 0},
        "reaction": {"prompt": "Use your reaction?"}, "reaction_context": {}})
    assert _rebuilt(t)["pending_action"]["reaction"] == {"prompt": "Use your reaction?"}
    table._save_pending_action(mid, None)
    assert _rebuilt(t)["pending_action"] is None

    # A seat change and a pause rewrite the fight's metadata only.
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    actor = next(a for a in _rebuilt(t)["presentation"]["actors"] if a["entity_id"] == RIGHT)
    assert actor["controller"] == "LOCAL_AUTO"
    combat.pause(mid)
    assert _rebuilt(t)["presentation"]["paused"] is True
    combat.resume(mid)
    assert _rebuilt(t)["presentation"]["paused"] is False

    # A round token saved for a character, and a divergence note held in memory.
    tokens = t.root / "tabletop_tokens"
    tokens.mkdir(exist_ok=True)
    (tokens / f"{LEFT.removeprefix('actor:factory.')}.png").write_bytes(b"test token")
    assert _rebuilt(t)["tokens"][LEFT].startswith("/api/tabletop/characters/")
    combat.commit_divergence_notices = {mid: {"notice": "This result differed from the table's prediction."}}
    assert _rebuilt(t)["divergence_diagnostic"]["notice"].startswith("This result differed")
    combat.commit_divergence_notices = {}
    _rebuilt(t)

    # An owner rules edit, a saved character button file and a CF_ switch each rebuild.
    (t.rules / "rules.json").write_text('{"edited": true}')
    _rebuilt(t)
    table.buttons.root.mkdir(parents=True, exist_ok=True)
    (table.buttons.root / "36000009.json").write_text("{}")  # another character's: nothing here reads it
    _rebuilt(t)
    monkeypatch.setenv("CF_SPEEDREUSE2_TEST_SWITCH", "1")
    _rebuilt(t)

    # A commit (End turn) moves the turn on.
    menu = _read(t)["menu"]
    last = _read(t)["last_sequence"]
    assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], last)["status"] == "COMMITTED"
    assert _rebuilt(t)["menu"]["state_version"] > menu["state_version"]


def test_reuse_switch_and_unidentifiable_inputs_build_every_time(table_fight, monkeypatch):
    t = table_fight
    hits = t.table._state_reuse.hits
    monkeypatch.setenv("CF_TABLE_STATE_REUSE", "0")
    _read(t)
    _read(t)
    assert t.table._state_reuse.hits == hits
    monkeypatch.delenv("CF_TABLE_STATE_REUSE")
    monkeypatch.setattr(t.table, "_state_inputs", lambda match_id: (_ for _ in ()).throw(OSError("unreadable")))
    _read(t)
    _read(t)
    assert t.table._state_reuse.hits == hits


def test_a_failed_menu_is_never_kept(table_fight, monkeypatch):
    t = table_fight
    original = t.combat.decision
    # A menu that cannot be worked out right now (the save is mid-write, content not ready) shows no choices.
    monkeypatch.setattr(t.combat, "decision", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("not ready")))
    failed = _read(t)["menu"]
    assert "decision_id" not in failed
    monkeypatch.setattr(t.combat, "decision", original)
    # That answer was not kept; even with the replaced seam put back the next read builds and has choices.
    misses = t.table._state_reuse.misses
    assert _read(t)["menu"]["decision_id"] and t.table._state_reuse.misses == misses + 1
    # And a kept answer is never one that declined itself.
    reuse = table_state_cache.StateReuse()
    def degraded():
        table_state_cache.decline("menu")
        return {"menu": {}}
    reuse.read(("m",), degraded, lambda: 1)
    assert not reuse._entries


class _Client:
    """Fake embedding client: which texts it holds is set by the test."""

    background = True

    def __init__(self):
        self.held, self.warmed = False, []

    def holds(self, texts):
        return self.held

    def prefetch(self, texts, **kwargs):
        self.warmed.append(tuple(texts))


def test_menu_order_from_embeddings_is_reused_only_while_the_client_still_answers_the_same():
    reuse, client, builds = table_state_cache.StateReuse(), _Client(), []

    def build():
        builds.append(1)
        menu_rank._note_ranking(client, ["query", "option"], client.held)
        return {"menu": {"ranked": client.held}}

    assert reuse.read(("m",), build, lambda: 1) == {"menu": {"ranked": False}}
    assert reuse.read(("m",), build, lambda: 1) == {"menu": {"ranked": False}}
    assert len(builds) == 1 and client.warmed == [("query", "option")]  # a reuse warms the texts as a build would
    client.held = True  # the vectors arrived: a fresh build would now blend them
    assert reuse.read(("m",), build, lambda: 1) == {"menu": {"ranked": True}}
    assert reuse.read(("m",), build, lambda: 1) == {"menu": {"ranked": True}} and len(builds) == 2
    client.held = False  # evicted: a fresh build would fall back
    assert reuse.read(("m",), build, lambda: 1) == {"menu": {"ranked": False}} and len(builds) == 3
    # A client that cannot say what it holds is never trusted to repeat an order.
    plain = SimpleNamespace(embed=lambda texts: [[1.0] for _ in texts])
    def plain_build():
        builds.append(1)
        menu_rank._note_ranking(plain, ["query"], True)
        return {}
    reuse.read(("p",), plain_build, lambda: 1)
    reuse.read(("p",), plain_build, lambda: 1)
    assert len(builds) == 5


def test_inputs_that_move_during_a_build_are_not_kept_and_the_store_is_bounded():
    reuse, stamps = table_state_cache.StateReuse(per_match=2, total_bytes=10_000), iter(range(100))
    reuse.read(("m", 1), lambda: {"n": 1}, lambda: next(stamps))  # inputs differ before/after: returned, not kept
    assert not reuse._entries
    for variant in range(4):
        reuse.read(("m", variant), lambda: {"n": variant}, lambda: "same")
    assert [key for key in reuse._entries] == [("m", 2), ("m", 3)]
    reuse.read(("other", 0), lambda: {"blob": "x" * 20_000}, lambda: "same")
    assert ("other", 0) not in reuse._entries and reuse._bytes <= 10_000


def test_production_inputs_cover_every_file_a_table_read_opens(table_fight, monkeypatch):
    """Every file an uncached read opens or lists lies inside an identified input (future readers included)."""
    import sys
    import threading
    t = table_fight
    monkeypatch.undo()  # the real SHARED_TREES
    opened, thread = set(), threading.get_ident()
    recording = [False]

    import os

    def hook(event, args):
        if not (recording[0] and threading.get_ident() == thread and event in ("open", "os.scandir", "os.listdir") and args):
            return
        if event == "open" and len(args) >= 3:
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                    mode is None and isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT)):
                return  # written, not read: a lock, a log or a saved file is an output of the read
        path = args[0]
        if isinstance(path, (str, bytes)) or hasattr(path, "__fspath__"):
            opened.add(os.fsdecode(path))
    sys.addaudithook(hook)
    # What every read opens again (one-time loads of a new service are not inputs that can change under it).
    fresh = TabletopService(CombatService(ROOT, t.root), t.root)
    fresh.state(t.mid, **BROWSER)
    monkeypatch.setenv("CF_TABLE_STATE_REUSE", "0")
    recording[0] = True
    try:
        fresh.state(t.mid, **BROWSER)
    finally:
        recording[0] = False
    from pathlib import Path
    roots = [*table_state_cache.SHARED_TREES, t.combat._match_dir(t.mid), t.table.buttons.root,
             t.root / "tabletop_tokens", t.combat.combatant_library.install_root]
    python = {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}

    # Listing the fights folder is resolving this fight's folder, which the reuse inputs run again on every read.
    matches_root = t.combat._match_dir(t.mid).parent.resolve()

    def covered(path):
        resolved = Path(path).resolve()
        return resolved == matches_root or any(resolved == root.resolve() or root.resolve() in resolved.parents
                                               for root in roots)

    def code(path):
        resolved = Path(path).resolve()
        return (path.endswith((".py", ".pyc", ".so")) or "__pycache__" in path or "site-packages" in path
                or any(root in resolved.parents for root in python) or path.startswith(("/proc", "/dev", "/sys", "/etc")))
    journal = t.combat._load_session(t.mid).store.journal_path
    assert str(journal) in opened, "the audit saw the read load its fight"
    uncovered = sorted(path for path in opened if not covered(path) and not code(path))
    assert not uncovered, f"files a table read opens that no reuse input identifies: {uncovered}"
