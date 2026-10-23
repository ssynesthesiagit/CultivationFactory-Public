"""preview(projected_engine=...) reads only the disposable projection, never the saved fight."""
from combat.gate3_reducer import canonical_state_sha256
from combat.gate4_models import DecisionContext
from tests.ai_tiers_native_support import fight


def _end_turn_payload(combat, match_id, session):
    context = DecisionContext.model_validate(combat.decision(match_id, session=session)["context"])
    end = next(c for c in context.legal_candidates if c.kind.value == "END_TURN")
    return dict(intent_id="projected:preview", candidate_id=end.candidate_id,
                decision_id=context.decision_id, state_version=context.state_version,
                actor_id=end.actor_id, target_ids=list(end.target_ids),
                destination=None, option_ids=[])


def test_preview_reads_the_projection_and_leaves_the_saved_fight_untouched(tmp_path):
    combat, match_id, session = fight(tmp_path)
    payload = _end_turn_payload(combat, match_id, session)
    live_before = canonical_state_sha256(session.engine.state)

    probe = combat._clone_engine(combat.source_root, session.engine)
    probe.state.round_number += 1
    projected = combat.preview(match_id, payload, [], projected_engine=probe)
    assert projected["status"] == "PREVIEW_COMPLETE"
    assert projected["pre_state_sha256"] == canonical_state_sha256(probe.state)
    assert projected["pre_state_sha256"] != live_before

    live = combat.preview(match_id, payload, [])
    assert live["status"] == "PREVIEW_COMPLETE"
    assert live["pre_state_sha256"] == live_before
    assert canonical_state_sha256(combat._load_session(match_id).engine.state) == live_before
