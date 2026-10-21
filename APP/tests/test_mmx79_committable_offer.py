"""Hunt 90 / MMX79: an offered button must always be committable, and a commit that
disagrees with the table's prediction must leave the fight playable and traceable.

The combat service predicts a post-state on a clone of the live engine, then executes the
same intent on the live engine and used to answer COMBAT_PREVIEW_MISMATCH (retry_safe=False,
"Stop using the match") whenever the two hashes differed. That answer came AFTER the action
had already been applied to the live state and committed to the journal, so a player who
picked a button the table had just offered lost the turn's feedback and was told to abandon
a save that was in fact consistent and playable.

The authoritative engine is the rules: its result is what the state, the journal and the
replay now all agree with, so it stands. The disagreement is written down beside it, in the
saved fight's own directory, so it is still there when the fight is reloaded.

Table level, through TabletopService.act exactly as the tabletop client drives it.
"""
import pytest

from combat.commit_diagnostics import diagnostic_path, latest_commit_divergence
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.hunt19_support import fight


@pytest.fixture
def yard(tmp_path):
    """A real fight, driven to Left's first turn."""
    return fight(tmp_path, [])


def _first_action(table, mid):
    """The candidate for a real (non End Turn) button in the current menu."""
    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["options"])
    return state, menu, group["options"][0]["candidate_id"]


def _commit_first_action(table, mid):
    state, menu, candidate_id = _first_action(table, mid)
    return table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"])


def _diverging_preview(monkeypatch):
    """Make the table's prediction disagree with the authoritative result.

    Test-local: the preview reports a post-state hash the commit cannot reproduce, which is
    exactly the condition the old code turned into a fatal, non-retryable error.
    """
    real = CombatService._run_preview

    def sabotaged(self, session, metadata, base_intent, supplied_reactions, **kwargs):
        result = real(self, session, metadata, base_intent, supplied_reactions, **kwargs)
        return {**result, "post_state_sha256": "0" * 64, "preview_id": "preview:" + "0" * 32}

    monkeypatch.setattr(CombatService, "_run_preview", sabotaged)


def _assert_the_prediction_was_agreed(combat, mid, response):
    """The ordinary path, asserted where a disagreement would actually show.

    The table's answer used to drop the service's ``preview_divergence`` field, so asserting
    only on the response would pass even for a commit that really did disagree. This looks at
    the durable record the table now carries and the saved fight's own file as well, so a
    mismatch cannot slip past. ``test_the_agreement_check_fails_on_a_real_mismatch`` proves
    that by running these very assertions against a commit that does disagree.
    """
    assert "divergence_diagnostic" not in response
    assert "preview_divergence" not in response
    assert latest_commit_divergence(combat._match_dir(mid)) is None
    assert not diagnostic_path(combat._match_dir(mid)).exists(), "a fight that agreed must leave no trace file"


def test_an_offered_button_whose_result_differs_from_the_prediction_is_still_committed(yard, monkeypatch):
    """The chosen action stands: the table accepts it instead of raising a fatal error."""
    combat, table, mid = yard
    _diverging_preview(monkeypatch)

    assert _commit_first_action(table, mid)["status"] == "COMMITTED"


def test_the_service_reports_the_divergence_beside_the_authoritative_result(yard, monkeypatch):
    """The disagreement is not swallowed either: the commit names both post-states."""
    combat, table, mid = yard
    session = combat._load_session(mid)
    context = combat.decision(mid, session=session)["context"]
    candidate = next(c for c in combat._legal_candidates(session)
                     if c.candidate_id in {o["candidate_id"] for g in
                                           table.state(mid)["menu"]["actions"] for o in g["options"]})
    payload = {k: getattr(candidate, k, None) for k in
               ("candidate_id", "decision_id", "state_version", "actor_id",
                "target_ids", "destination", "option_ids")}
    payload["target_ids"] = list(payload["target_ids"] or [])
    payload["option_ids"] = list(payload["option_ids"] or [])
    _diverging_preview(monkeypatch)

    committed = combat._commit_previewed(mid, payload, [], None)

    assert committed["preview_divergence"]["preview_post_state_sha256"] == "0" * 64
    assert committed["preview_divergence"]["authoritative_post_state_sha256"] != "0" * 64
    assert committed["match"]["match_id"] == mid


def test_the_table_shows_the_divergence_it_committed(yard, monkeypatch):
    """The table is not the last place the disagreement is lost: its answer carries it."""
    combat, table, mid = yard
    _diverging_preview(monkeypatch)

    diagnostic = _commit_first_action(table, mid)["divergence_diagnostic"]

    assert diagnostic["code"] == "COMBAT_PREVIEW_MISMATCH"
    assert diagnostic["preview_post_state_sha256"] == "0" * 64
    assert diagnostic["authoritative_post_state_sha256"] != "0" * 64
    assert diagnostic["outcome"] == "COMMITTED", "the action was applied; the note must not read as a failure"
    # item 13: what a player reads is the plain sentence, with no hashes or ids in it.
    assert "sha" not in diagnostic["notice"].lower()
    assert "0" * 64 not in diagnostic["notice"]


def test_a_divergence_survives_a_reload_of_the_saved_fight(yard, monkeypatch, tmp_path):
    """Persistence: the note is still there for a service that has to read the fight from disk again."""
    combat, table, mid = yard
    _diverging_preview(monkeypatch)
    committed = _commit_first_action(table, mid)["divergence_diagnostic"]

    reopened = _diagnostic_after_reload(ROOT, tmp_path, mid)

    assert reopened == committed, "a reloaded fight must show the same note, hash for hash"
    assert latest_commit_divergence(combat._match_dir(mid)) == committed


def _diagnostic_after_reload(root, tmp_path, mid):
    """A brand new table service over the same saved fight: nothing carried over in memory."""
    from combat.tabletop_service import TabletopService

    table = TabletopService(CombatService(root, tmp_path), tmp_path)
    diagnostic = table.state(mid)["divergence_diagnostic"]
    assert table.events(mid, 0)["divergence_diagnostic"] == diagnostic
    return diagnostic


def test_a_commit_that_diverged_leaves_the_fight_playable(yard, monkeypatch):
    """The saved fight is still a table: a new turn is offered and the fight carries on."""
    combat, table, mid = yard
    _diverging_preview(monkeypatch)
    _commit_first_action(table, mid)

    after = table.state(mid)
    assert not (after["presentation"] or {}).get("terminal")
    assert after["menu"]["decision_id"], "the table must offer the next turn"
    # and the fight keeps taking actions
    following = table.state(mid)
    options = [o for g in following["menu"]["actions"] for o in g["options"]]
    if options:
        assert table.act(mid, options[0]["candidate_id"], following["menu"]["decision_id"],
                         following["menu"]["state_version"], following["last_sequence"])["status"] == "COMMITTED"
    else:
        assert table.act(mid, following["menu"]["end_turn"], following["menu"]["decision_id"],
                         following["menu"]["state_version"], following["last_sequence"])["status"] == "COMMITTED"


def test_a_fight_whose_commit_diverged_reloads_and_replays(yard, monkeypatch, tmp_path):
    """The recorded note is a side file: the journal and the replay are exactly as before it."""
    combat, table, mid = yard
    _diverging_preview(monkeypatch)
    _commit_first_action(table, mid)

    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.mechanical.replay()["status"] == "PASS"


def test_the_ordinary_path_reports_no_divergence_when_the_prediction_agrees(yard):
    """A commit that reproduces the prediction is unchanged by the fix: no note, no extra key."""
    combat, table, mid = yard

    response = _commit_first_action(table, mid)

    assert response["status"] == "COMMITTED"
    _assert_the_prediction_was_agreed(combat, mid, response)


def test_the_agreement_check_fails_on_a_real_mismatch(yard, monkeypatch):
    """Negative control: the assertion above is not vacuous. A commit that really did disagree
    is caught by the very same three lines, so the ordinary-path test is proving something."""
    combat, table, mid = yard
    _diverging_preview(monkeypatch)

    response = _commit_first_action(table, mid)

    with pytest.raises(AssertionError):
        _assert_the_prediction_was_agreed(combat, mid, response)


@pytest.mark.parametrize("failure", ["mkdir", "open", "write", "fsync", "close"])
def test_diagnostic_io_failure_keeps_commit_notice_and_continuation(yard, monkeypatch, tmp_path, failure):
    from combat import commit_diagnostics
    from pathlib import Path

    combat, table, mid = yard
    _diverging_preview(monkeypatch)
    with monkeypatch.context() as io_patch:
        def fail(*args, **kwargs):
            raise OSError("injected diagnostic I/O failure")

        # Target only this helper's I/O; never break the actual journal writer.
        if failure == "mkdir":
            class FailingPath(type(Path())):
                def mkdir(self, *args, **kwargs):
                    fail()
            io_patch.setattr(commit_diagnostics, "diagnostic_path",
                             lambda folder: FailingPath(folder / commit_diagnostics.COMMIT_DIAGNOSTIC_FILE))
        else:
            from types import SimpleNamespace
            operations = {name: getattr(commit_diagnostics.os, name)
                          for name in ("open", "write", "fsync", "close", "O_WRONLY", "O_CREAT", "O_APPEND")}
            if failure == "close":
                real_close = operations["close"]
                def close(fd):
                    real_close(fd)
                    fail()
                operations["close"] = close
            else:
                operations[failure] = fail
            io_patch.setattr(commit_diagnostics, "os", SimpleNamespace(**operations))
        response = _commit_first_action(table, mid)

    assert response["status"] == "COMMITTED"
    notice = response["divergence_diagnostic"]
    assert notice["outcome"] == "COMMITTED"
    assert notice["persistence_error"] == "COMMIT_DIAGNOSTIC_WRITE_FAILED"
    assert "action was saved" in notice["persistence_notice"]
    assert table.state(mid)["divergence_diagnostic"] == notice
    assert table.events(mid, 0)["divergence_diagnostic"] == notice
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
    state = table.state(mid)
    menu = state["menu"]
    assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"],
                     state["last_sequence"])["status"] == "COMMITTED"


def test_invalid_utf8_sidecar_cannot_break_a_committed_table_response(yard, tmp_path):
    from combat.tabletop_service import TabletopService

    combat, table, mid = yard
    path = diagnostic_path(combat._match_dir(mid))
    path.write_bytes(b"\xff\xfe\n")
    response = _commit_first_action(table, mid)
    assert response["status"] == "COMMITTED"
    assert "divergence_diagnostic" not in response
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert "divergence_diagnostic" not in reopened.state(mid)
    assert "divergence_diagnostic" not in reopened.events(mid, 0)
    assert reopened.combat._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_valid_notice_survives_invalid_utf8_rows_and_automatic_turn(yard, monkeypatch, tmp_path):
    from combat.tabletop_service import TabletopService

    combat, table, mid = yard
    _diverging_preview(monkeypatch)
    notice = _commit_first_action(table, mid)["divergence_diagnostic"]
    with diagnostic_path(combat._match_dir(mid)).open("ab") as stream:
        stream.write(b"\xff\xfe\n")
    reopened_combat = CombatService(ROOT, tmp_path)
    reopened = TabletopService(reopened_combat, tmp_path)
    state = reopened.state(mid)
    assert state["divergence_diagnostic"] == notice
    assert reopened.events(mid, 0)["divergence_diagnostic"] == notice
    reopened_combat.set_controller_mode(mid, actor_id=state["menu"]["actor_id"], controller_mode="LOCAL_AUTO")
    response = reopened.auto_step(mid, state["last_sequence"])
    assert response["status"] == "COMMITTED"
    assert response["divergence_diagnostic"] == notice
    assert response["state"]["divergence_diagnostic"] == notice
    assert response["events"]["divergence_diagnostic"] == notice
    assert CombatService(ROOT, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"
