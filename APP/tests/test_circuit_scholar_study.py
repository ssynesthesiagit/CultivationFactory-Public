"""Circuit Scholar's bonus reaches Study an illusion through a committed table check."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import figment, placed
from tests.test_auto2_talismans import take
from tests.test_auto41_illusion import answer, cell_action
from tests.worker2_support import ALLY, OWNER, fixture, reload, turn

CIRCUIT_SCHOLAR = "insight.circuit-scholar"
QIWEAVING = "TAL_QIWEAVING_MINOR_QI_ARTS"


def _study(tmp_path, *, insight, proficient):
    def seal_proficiency(bundles):
        bundle = bundles[0]
        bundle["skill_proficiency"] = {
            **(bundle.get("skill_proficiency") or {}), "Investigation": int(proficient)}
        bundle["bundle_sha256"] = canonical_sha256(
            {k: v for k, v in bundle.items() if k != "bundle_sha256"})

    combat, table, mid = fixture(
        tmp_path, [QIWEAVING], ally_talents=[figment.MINOR],
        owner_insights=(CIRCUIT_SCHOLAR,) if insight else (),
        bundle_transform=seal_proficiency)
    turn(table, mid, ALLY)
    result = cell_action(table, mid, "Minor Illusion", (4, 7))
    assert result["status"] == "REACTION_REQUIRED", result
    assert cell_action(table, mid, "Minor Illusion", (4, 7),
                       [answer(result, ["image"])])["status"] == "COMMITTED"
    zone, = placed.of(reload(tmp_path, mid), "figment")
    assert placed.data(zone)["creator"] == ALLY
    turn(table, mid, OWNER)
    take(combat, table, mid, "Study an illusion",
         choices={"choice:needle.study_figment": zone.zone_id})
    engine = reload(tmp_path, mid)
    events = [e for e in engine.events if e.event_type == "CHECK_ROLLED"
              and e.actor_id == OWNER and e.payload.get("check") == "Study an illusion"]
    event, = events
    assert event.payload["ability"] == "INT"
    assert event.payload["skill"] == "Investigation"
    roll, = [r for r in engine.rolls if r.actor_id == OWNER
             and r.reason == f"CHECK:{event.source_definition_id}"]
    assert not engine.state.actors[OWNER].action_available
    assert bool([r for r in engine.typed_passive_rows.get(OWNER, [])
                 if r.get("feature_id") == CIRCUIT_SCHOLAR]) == insight
    return engine.state.actors[OWNER].proficiency_bonus, roll


@pytest.mark.parametrize("proficient", [False, True], ids=["untrained", "proficient"])
def test_study_an_illusion_pays_printed_identification_bonus(tmp_path, proficient):
    """Removing identifying(...) at the Study producer must lose PB (or twice PB)."""
    pb, owner = _study(tmp_path / "scholar", insight=True, proficient=proficient)
    control_pb, plain = _study(tmp_path / "control", insight=False, proficient=proficient)
    assert pb == control_pb and pb > 0
    assert owner.modifier == plain.modifier + pb * (2 if proficient else 1)
