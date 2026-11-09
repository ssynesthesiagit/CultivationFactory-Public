"""MGR-T14-ling-crane-crossing-sum-1: Perfected Cloud-Crane Crossing activation temp HP.

The printed clause "gain temporary Hit Points equal to your Cultivation Level + your
Path key ability modifier" is one signed aggregate (CL5 with a -1 key modifier gives 4),
granted once per activation -- not one grant per typed row.
"""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, fixture, candidate, settle, turn, reload

CRANE = "foundation.white_crane_cloud_step_v0_2B.perfected_cloud_crane_crossing"
CRANE_NAME = "Perfected: Cloud-Crane Crossing"
FOUNDATION = "white_crane_cloud_step_v0_2B"


def crane_bundle(cl=5, key_score=8, stage="Perfected", actor_id=OWNER):
    """A Perfected White Crane Cloud-Step character: CL ``cl``, CON ``key_score`` (8 -> -1)."""
    doc = sheet([CRANE], cl=cl, key="CON", score=key_score, foundation={
        "foundation_id": FOUNDATION, "stage": stage})
    return compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True})


def setup(tmp_path, cl=5, key_score=8):
    return fixture(tmp_path, [], seed="MGRT14CCS1",
                   owner_bundle=crane_bundle(cl, key_score), bundle_transform=lambda bundles: None)


def use(combat, table, mid, name, target=None):
    settle(table, mid, candidate(combat, mid, name, target=target).candidate_id)


def grants(engine, actor=OWNER):
    return [e for e in engine.events if e.event_type == "TEMP_HP_GRANTED"
            and e.actor_id == actor]


@pytest.mark.parametrize("cl,key_score,expected", [
    (5, 8, 4),    # CL5 + (-1): the signed aggregate acceptance case
    (5, 14, 7),   # positive control: CL5 + (+2)
    (11, 16, 14), # higher-level positive control: CL11 + (+3)
])
def test_crane_crossing_activation_grants_signed_aggregate_once(tmp_path, cl, key_score, expected):
    combat, table, mid = setup(tmp_path, cl, key_score)
    use(combat, table, mid, CRANE_NAME, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.temporary_hp == expected
    rows = grants(engine)
    assert len(rows) == 1, [(e.payload) for e in rows]
    assert rows[0].payload["offered"] == expected


def test_crane_crossing_activation_grants_signed_amount_on_table(tmp_path):
    combat, table, mid = setup(tmp_path, 5, 8)
    use(combat, table, mid, CRANE_NAME, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 4
    # This test certifies the activation amount and single grant only; the
    # Bonus Action has already been spent, so it does not certify rest limits.
    assert [e.payload["offered"] for e in grants(engine)] == [4]
