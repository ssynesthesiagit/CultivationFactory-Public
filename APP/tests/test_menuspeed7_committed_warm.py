"""Only saved deferred actions start preparation, including compact menu_read."""
import socket
from types import SimpleNamespace

import pytest

from combat import menu_rank
from tests.worker2_support import ALLY, FOE, OWNER, fixture


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("CF_EMBED_MENU", "0")
    monkeypatch.setattr(menu_rank, "_CLIENT", SimpleNamespace(
        embed=lambda *a, **k: pytest.fail("No live embedding"),
        prefetch=lambda *a, **k: None))
    monkeypatch.setattr(socket.socket, "connect",
                        lambda *a, **k: pytest.fail("No live network"))


def watch(table, combat, monkeypatch):
    order = []
    monkeypatch.setattr(table, "_schedule_menu", lambda mid, result:
                        order.append(("prepare", result["state"]["menu_pending"]["state_version"])))
    present = combat.presentation
    def presentation(*args, **kwargs):
        order.append(("present", kwargs["session"].engine.state.state_version))
        return present(*args, **kwargs)
    monkeypatch.setattr(combat, "presentation", presentation)
    return order


@pytest.mark.parametrize("read", [None, {"fog": True, "compact": True, "fog_actor_ids": [OWNER]}])
@pytest.mark.parametrize("defer", [False, True])
def test_committed_act_prepares_before_presentation_with_or_without_menu_read(
        tmp_path, monkeypatch, read, defer):
    combat, table, mid = fixture(tmp_path, [], ask=False, seed="MENU-WARM-READ")
    before = table.state(mid, compact_moves=True)
    menu = before["menu"]
    order = watch(table, combat, monkeypatch)
    result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                       before["last_sequence"], defer_menu=defer, menu_read=read)
    assert result["status"] == "COMMITTED"
    version = combat._load_session(mid).engine.state.state_version
    assert version > menu["state_version"]
    assert order == ([("prepare", version)] if defer else []) + [("present", version)]
    if read is not None:
        assert result["state"]["menu"]["state_version"] == version
    elif defer:
        assert result["state"]["menu"] is None
        assert result["state"]["menu_pending"]["state_version"] == version


def test_deferred_local_auto_prepares_the_committed_boundary(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [], ask=False, seed="MENU-WARM-AUTO")
    for actor in (OWNER, ALLY, FOE):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")
    version = combat._load_session(mid).engine.state.state_version
    order = watch(table, combat, monkeypatch)
    result = table.auto_step(mid, 0, defer_menu=True)
    assert result["status"] == "COMMITTED"
    committed = result["state"]["menu_pending"]["state_version"]
    assert committed > version
    assert order == [("prepare", committed), ("present", committed)]


def test_read_only_snapshot_never_starts_preparation(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [], ask=False, seed="MENU-WARM-READONLY")
    session = combat._load_session(mid)
    order = watch(table, combat, monkeypatch)
    table.state(mid, include_menu=False, _session=session)
    assert order == [("present", session.engine.state.state_version)]


def test_prepare_only_does_not_start_next_menu(tmp_path, monkeypatch):
    combat, table, mid = fixture(tmp_path, [], ask=False, seed="MENU-WARM-PREVIEW")
    before = table.state(mid)
    menu = before["menu"]
    order = watch(table, combat, monkeypatch)
    result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                       before["last_sequence"], defer_menu=True,
                       menu_read={"compact": True}, prepare_only=True)
    assert result["status"] != "COMMITTED"
    assert not any(kind == "prepare" for kind, _ in order)
    assert combat._load_session(mid).engine.state.state_version == menu["state_version"]
