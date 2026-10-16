"""ESCCANCEL1 production JavaScript cancellation paths; no browser or live services."""
import subprocess
from pathlib import Path


def test_prepare_fixture_includes_shipped_footwork_registration():
    import json
    from combat.typed_reactions import rules

    # Explicit runtime dependency: the public exporter cannot infer the
    # feature_blocks.d glob. Omitting this shipped row silently removes Footwork
    # from the compiled fixture and makes preparation appear choice-free.
    path = Path(__file__).resolve().parents[1] / "combat/rules/feature_blocks.d/needle.json"
    shipped = json.loads(path.read_text())["features"]["TAL_FENCING_FOOTWORK"]
    assert shipped["block"] == "needle" and shipped["kind"] == "footwork"
    assert rules()["features"]["TAL_FENCING_FOOTWORK"] == shipped


def test_tabletop_esc_cancel_node():
    subprocess.run(
        ["node", "--test", *[str(Path(__file__).with_name(name)) for name in (
            "tabletop_esc_cancel.test.mjs", "preset_queue.test.mjs", "walkable_roofs_movement_ui.test.mjs",
        )]],
        check=True, timeout=60,
    )


def test_prepare_choices_leave_reload_plain_and_another_action_available(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from combat import menu_rank
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT
    from tests.test_hunt5_player_choices import fixture

    monkeypatch.setattr(menu_rank, "_CLIENT", SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **kw: None))
    combat, table, mid, cid, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    before = table.state(mid)
    menu = before["menu"]
    journal = (table._match_dir(mid) / "Journal.ndjson").read_bytes()
    args = (mid, cid, menu["decision_id"], menu["state_version"], 0)
    prepared = table.act(*args, prepare_only=True)
    assert prepared["status"] == "REACTION_REQUIRED"
    assert not table._pending_action_path(mid).exists()
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    state = reopened.state(mid)
    assert state["pending_action"] is None
    assert state["menu"]["decision_id"] == menu["decision_id"]
    assert (table._match_dir(mid) / "Journal.ndjson").read_bytes() == journal
    # Cancelling a preview requires no cleanup call and cannot reserve the turn.
    assert reopened.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"


def test_prepared_answers_commit_only_after_explicit_submit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from combat import menu_rank
    from tests.test_hunt5_player_choices import fixture

    monkeypatch.setattr(menu_rank, "_CLIENT", SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **kw: None))
    combat, table, mid, cid, _ = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    menu = table.state(mid)["menu"]
    args = (mid, cid, menu["decision_id"], menu["state_version"], 0)
    prepared = table.act(*args, prepare_only=True)
    prompt = prepared["reaction"]
    stay = next(row["id"] for row in prompt["choice"]["options"] if "Stay put" in row["label"])
    answers = [{**prompt["context"], "selection": "USE", "option_ids": [stay]}]
    assert table.act(*args, answers, prepare_only=True)["status"] == "PREPARED"
    assert table.state(mid)["menu"]["state_version"] == menu["state_version"]
    assert table.state(mid)["pending_action"] is None
    assert table.act(*args, answers)["status"] == "COMMITTED"
    assert combat._load_session(mid).verify()["status"] == "PASS"
