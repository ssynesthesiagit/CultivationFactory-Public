"""MGR-T14-ling-heartfire-mandala-sum-1: Perfected Nine-Bitter Heartfire Mandala temp HP.

The printed clause "You gain temporary Hit Points equal to your Cultivation Level + your
Path key ability modifier" is one signed aggregate (CL5 with a -1 key modifier gives 4),
granted once per activation -- not one grant per typed row.
"""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, fixture, candidate, settle, turn, reload

MANDALA = "foundation.nine_bitter_heartfire_v0_2B.perfected_nine_bitter_heartfire_mandala"
MANDALA_NAME = "Perfected: Nine-Bitter Heartfire Mandala"
FOUNDATION = "nine_bitter_heartfire_v0_2B"


def mandala_bundle(cl=5, key_score=8, stage="Perfected", actor_id=OWNER):
    """A Perfected Nine-Bitter Heartfire character: CL ``cl``, CON ``key_score`` (8 -> -1)."""
    doc = sheet([MANDALA], cl=cl, key="CON", score=key_score, foundation={
        "foundation_id": FOUNDATION, "stage": stage})
    return compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True})


def setup(tmp_path, cl=5, key_score=8, hold_temp_hp=False):
    bundle = mandala_bundle(cl, key_score)
    if hold_temp_hp:
        # An independent, larger Temporary HP pool the mandala's smaller signed
        # aggregate must not replace (Temporary HP does not stack).
        from tests.cw2_service_support import add_action

        add_action(bundle, "Heartfire Vigil", [{"type": "temp_hp", "applies_to": "self", "flat": 9}],
                   target="SELF")
    return fixture(tmp_path, [], seed="MGRT14HFS1",
                   owner_bundle=bundle, bundle_transform=lambda bundles: None)


def use(combat, table, mid, name, target=None):
    settle(table, mid, candidate(combat, mid, name, target=target).candidate_id)


def grants(engine, actor=OWNER):
    return [e for e in engine.events if e.event_type == "TEMP_HP_GRANTED"
            and e.actor_id == actor]


def mandala_grants(engine):
    return [e for e in grants(engine)
            if "perfected_nine_bitter_heartfire_mandala" in e.source_definition_id]


@pytest.mark.parametrize("cl,key_score,expected", [
    (5, 8, 4),    # CL5 + (-1): the signed aggregate acceptance case
    (5, 14, 7),   # positive control: CL5 + (+2)
    (11, 16, 14), # independent higher temp-HP control: CL11 + (+3)
])
def test_mandala_activation_grants_signed_aggregate_once(tmp_path, cl, key_score, expected):
    combat, table, mid = setup(tmp_path, cl, key_score)
    row = candidate(combat, mid, MANDALA_NAME, target=OWNER)
    # The legitimately compiled Perfected activation: a Bonus Action, once per
    # long rest, owned by the reviewed record itself, and paid by its use limit.
    action = combat._load_session(mid).engine.action_catalog.get(row.source_definition_id)
    assert row.source_definition_id.endswith(MANDALA)
    assert action.economy == "BONUS_ACTION"
    assert action.resolution_kind == "TYPED"
    assert [cost for cost in action.costs if str(cost[0]).startswith("resource:uses.")]
    settle(table, mid, row.candidate_id)
    engine = reload(tmp_path, mid)  # commit and cold replay
    actor = engine.state.actors[OWNER]
    assert actor.temporary_hp == expected
    rows = mandala_grants(engine)
    assert len(rows) == 1, [(e.source_definition_id, e.payload) for e in grants(engine)]
    assert rows[0].source_definition_id.endswith(MANDALA)
    assert rows[0].payload["offered"] == expected


def test_mandala_activation_is_once_per_long_rest(tmp_path):
    combat, table, mid = setup(tmp_path, 5, 8)
    use(combat, table, mid, MANDALA_NAME, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 4
    # Once per long rest: the activation is no longer a legal candidate, and no
    # later restatement of the Cultivation Level term restores a second grant.
    assert not [c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == MANDALA_NAME]
    assert [e.payload["offered"] for e in mandala_grants(engine)] == [4]


def test_independent_higher_temp_hp_is_preserved(tmp_path):
    combat, table, mid = setup(tmp_path, 5, 8, hold_temp_hp=True)
    use(combat, table, mid, "Heartfire Vigil", OWNER)
    use(combat, table, mid, MANDALA_NAME, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    # Normal max replacement keeps the larger independent pool; the mandala's
    # signed aggregate (CL5 + (-1) = 4) is offered once and does not replace it.
    assert actor.temporary_hp == 9
    rows = mandala_grants(engine)
    assert len(rows) == 1, [(e.source_definition_id, e.payload) for e in grants(engine)]
    assert rows[0].payload["offered"] == 4
    assert rows[0].payload["before"] == 9
    assert rows[0].payload["after"] == 9
