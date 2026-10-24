"""Production JavaScript cancellation paths; no browser or live services."""
import subprocess
from pathlib import Path

from tests.test_esc_cancel_composed_choices import composed_choice, footwork_registration  # noqa: F401 (fixtures)


def test_prepare_fixture_works_without_shipped_footwork_registration(request, monkeypatch):
    from combat.typed_reactions import rules

    # Model the public snapshot without the optional glob-loaded registration.
    # The fixture must still compile the real hook and reach its checkpoint.
    monkeypatch.delitem(rules()["features"], "TAL_FENCING_FOOTWORK", raising=False)
    _combat, table, mid, payload, chosen = request.getfixturevalue("composed_choice")
    result = table.prepare_composition(mid, payload, chosen["candidate_id"])
    assert result["status"] == "REACTION_REQUIRED", result
    assert result["reaction"]["reaction"] == "Footwork"
    assert not table._pending_action_path(mid).exists()


def test_tabletop_esc_cancel_node():
    result = subprocess.run(
        ["node", "--test", "--test-reporter=tap", *[str(Path(__file__).with_name(name)) for name in (
            "tabletop_esc_cancel.test.mjs", "preset_queue.test.mjs", "walkable_roofs_movement_ui.test.mjs",
            "sol150_table_text.test.mjs", "commitspeed2_deferred.test.mjs",
        )]],
        text=True, capture_output=True, timeout=60,
    )
    output = result.stdout + result.stderr
    # Put the first failing TAP case first in the bounded public-CI diagnostic.
    failure = output.find("not ok")
    assert result.returncode == 0, output[failure if failure >= 0 else 0:].replace("\n", " | ")


def test_prepare_choices_leave_reload_plain_and_another_action_available(tmp_path, monkeypatch, footwork_registration):
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


def test_prepared_answers_commit_only_after_explicit_submit(tmp_path, monkeypatch, footwork_registration):
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
