"""Circuit Scholar: the printed identification bonus reaches every table check that identifies magic.

The printed clause is "When you make an Intelligence check to identify a spell, sphere technique,
talisman effect, or Active Qi Pattern, add your Proficiency Bonus if you are not already proficient.
If you are proficient, add double your Proficiency Bonus."

Besides Read the Script and Study an illusion, two Illusion holds grant their own Study check
(Phantom Prison and Substantial Phantasm) and Dreamweaver's World of One offers an Intelligence
(Investigation) check "to identify ... the governing dream-symbol". All three roll through the
shared escape/check resolvers, so without the documented marker no check_bonus subscriber reaches
them. Each test runs the same real table transaction with and without the insight and compares the
committed check modifier; removing the marker or the reviewed authority entry loses the difference.
"""
import pytest

from combat.gate2_rolls import DeterministicRollAuthority
from tests.h1_support import sheet
from tests.worker2_support import FOE, OWNER, candidate, fixture, reload, settle, turn

CIRCUIT_SCHOLAR = "insight.circuit-scholar"
QIWEAVING = "TAL_QIWEAVING_MINOR_QI_ARTS"
PRISON = "tianxia.talent.illusion.phantom_prison"
SUBSTANTIAL = "tianxia.talent.illusion.substantial_phantasm"
WORLD = "tianxia.tradition.spirit.dreamweaver.feature.world_of_one"
STUDY_FIGMENT = "Create Figment + Substantial Phantasm (3 CP; Grappled)"


def _reader(insight):
    """The held creature's sheet: Qiweaving plus, when asked, the Circuit Scholar insight."""
    doc = sheet([QIWEAVING], cl=15)
    fields = doc.setdefault("spheres_and_talents", {})
    fields["cultivation_insight_record_ids"] = [CIRCUIT_SCHOLAR] if insight else []
    return doc


@pytest.fixture
def failed_foe_saves(monkeypatch):
    """Force only the held creature's saving throws to fail; every check roll stays real."""
    real = DeterministicRollAuthority.d20

    def dice(roller, **kwargs):
        wanted = 1 if kwargs.get("actor_id") == FOE and kwargs.get("reason", "").startswith("SAVE:") else None
        while True:
            roll = real(roller, **kwargs)
            if wanted is None or roll.natural_result == wanted:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", dice)


def _check(engine):
    event, = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.actor_id == FOE]
    return event


def _insight_rows(engine):
    return bool([row for row in engine.typed_passive_rows.get(FOE, [])
                 if row.get("feature_id") == CIRCUIT_SCHOLAR])


def _phantom_prison(tmp_path, root, insight):
    combat, table, mid = fixture(tmp_path / root, [PRISON], foe_sheet=_reader(insight),
                                 owner_dc=16, seed="CSPRISON")
    settle(table, mid, candidate(combat, mid, "Phantom Prison", target=FOE).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Break free").candidate_id)
    engine = reload(tmp_path / root, mid)
    assert _insight_rows(engine) == insight
    event = _check(engine)
    assert event.payload["check"] == "Study Phantom Prison: Intelligence (Investigation)"
    return engine.state.actors[FOE].proficiency_bonus, event


def test_study_phantom_prison_pays_printed_identification_bonus(tmp_path, failed_foe_saves):
    pb, owner = _phantom_prison(tmp_path, "insight", insight=True)
    control_pb, plain = _phantom_prison(tmp_path, "control", insight=False)
    assert pb == control_pb and pb > 0
    assert owner.payload["actor"]["modifier"] == plain.payload["actor"]["modifier"] + pb


def _substantial(tmp_path, root, insight):
    combat, table, mid = fixture(
        tmp_path / root, [SUBSTANTIAL], foe_sheet=_reader(insight), owner_dc=16,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 6, "y": 6}}, seed="CSPHANTASM")
    cid = candidate(combat, mid, STUDY_FIGMENT, at=(6, 6)).candidate_id
    settle(table, mid, cid, choices={"choice:needle.substantial_phantasm": FOE})
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Break free").candidate_id)
    engine = reload(tmp_path / root, mid)
    assert _insight_rows(engine) == insight
    event = _check(engine)
    assert event.payload["check"] == ("Substantial Phantasm (Study the illusion): "
                                      "Intelligence (Investigation)")
    return engine.state.actors[FOE].proficiency_bonus, event


def test_study_substantial_phantasm_pays_printed_identification_bonus(tmp_path, failed_foe_saves):
    pb, owner = _substantial(tmp_path, "insight", insight=True)
    control_pb, plain = _substantial(tmp_path, "control", insight=False)
    assert pb == control_pb and pb > 0
    assert owner.payload["actor"]["modifier"] == plain.payload["actor"]["modifier"] + pb


def _world_of_one(tmp_path, root, insight):
    combat, table, mid = fixture(tmp_path / root, [], owner_features=[WORLD],
                                 foe_sheet=_reader(insight), primary="Resonance", owner_dc=16,
                                 seed="CSWORLD")
    settle(table, mid, candidate(combat, mid, "World of One", target=FOE).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, table.state(mid)["menu"]["end_turn"],
           choices={"choice:needle.dreamweaver.world_escape": "investigation"})
    engine = reload(tmp_path / root, mid)
    assert _insight_rows(engine) == insight
    event = _check(engine)
    assert event.payload["check"] == "INT (Investigation)"
    return engine.state.actors[FOE].proficiency_bonus, event


def test_world_of_one_identify_the_dream_symbol_pays_printed_bonus(tmp_path, failed_foe_saves):
    pb, owner = _world_of_one(tmp_path, "insight", insight=True)
    control_pb, plain = _world_of_one(tmp_path, "control", insight=False)
    assert pb == control_pb and pb > 0
    assert owner.payload["actor"]["modifier"] == plain.payload["actor"]["modifier"] + pb
