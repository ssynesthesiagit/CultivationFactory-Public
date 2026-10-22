"""Height-label formatting never changes a candidate or hides an option."""
from combat.destination_labels import distinguish_teleport_heights
from combat.gate2_runtime_models import CandidateKind, LegalCandidate, Position


def test_only_ambiguous_teleports_change_and_candidate_identity_is_preserved():
    def candidate(source, z, *, teleport=True):
        return LegalCandidate(
            candidate_id=f"candidate:{source}:{z}", decision_id="decision:test",
            state_version=1, kind=CandidateKind.ACTION, actor_id="actor:test",
            source_definition_id=source, display_name="Step to 2,3",
            target_ids=("actor:test",), destination=Position(x=2, y=3, z=z),
            metadata={"teleport": teleport, "expected_damage": 0})
    rows = (candidate("step", 0), candidate("step", 2), candidate("other", 2),
            candidate("walk", 0, teleport=False), candidate("walk", 2, teleport=False))
    before = [row.model_dump(mode="json") for row in rows]
    result = distinguish_teleport_heights(rows, square_size_ft=10)
    assert [row.display_name for row in result] == [
        "Step to 2,3 — ground", "Step to 2,3 — 20 ft up", "Step to 2,3",
        "Step to 2,3", "Step to 2,3"]
    assert [row.model_dump(mode="json") for row in rows] == before
    for old, new in zip(rows, result):
        assert new.model_dump(exclude={"display_name"}) == old.model_dump(exclude={"display_name"})
