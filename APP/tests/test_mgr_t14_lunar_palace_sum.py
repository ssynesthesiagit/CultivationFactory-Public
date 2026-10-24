"""MGR-T14-ling-lunar-palace-sum-1: Perfected True Moon Yin Palace activation temp HP.

The printed clause "You gain temporary Hit Points equal to your Cultivation Level + your
Path key ability modifier" is one signed aggregate (CL5 with a -1 key modifier gives 4),
granted once per activation -- not one grant per typed row.
"""
import pytest
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.worker2_support import OWNER, fixture, candidate, settle, turn, reload

PALACE = "foundation.taiyin_lunar_body_v0_2B.perfected_true_moon_yin_palace"
PALACE_NAME = "Perfected — True Moon Yin Palace"
FOUNDATION = "taiyin_lunar_body_v0_2B"


def palace_bundle(cl=5, key_score=8, stage="Perfected", actor_id=OWNER):
    """A Perfected Taiyin Lunar Body character: CL ``cl``, CON ``key_score`` (8 -> -1)."""
    doc = sheet([PALACE], cl=cl, key="CON", score=key_score, foundation={
        "foundation_id": FOUNDATION, "stage": stage})
    return compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True})


def setup(tmp_path, cl=5, key_score=8, hold_temp_hp=False):
    bundle = palace_bundle(cl, key_score)
    if hold_temp_hp:
        # An independent, larger Temporary HP pool the palace's smaller signed
        # aggregate must not replace (Temporary HP does not stack).
        from tests.cw2_service_support import add_action

        add_action(bundle, "Moonlit Vigil", [{"type": "temp_hp", "applies_to": "self", "flat": 9}],
                   target="SELF")
    return fixture(tmp_path, [], seed="MGRT14LPS1",
                   owner_bundle=bundle, bundle_transform=lambda bundles: None)


def use(combat, table, mid, name, target=None):
    settle(table, mid, candidate(combat, mid, name, target=target).candidate_id)


def grants(engine, actor=OWNER):
    return [e for e in engine.events if e.event_type == "TEMP_HP_GRANTED"
            and e.actor_id == actor]


def palace_grants(engine):
    return [e for e in grants(engine)
            if "perfected_true_moon_yin_palace" in e.source_definition_id]


@pytest.mark.parametrize("cl,key_score,expected", [
    (5, 8, 4),    # CL5 + (-1): the signed aggregate acceptance case
    (5, 14, 7),   # positive control: CL5 + (+2)
    (11, 16, 14), # independent higher temp-HP control: CL11 + (+3)
])
def test_palace_activation_grants_signed_aggregate_once(tmp_path, cl, key_score, expected):
    combat, table, mid = setup(tmp_path, cl, key_score)
    use(combat, table, mid, PALACE_NAME, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.temporary_hp == expected
    rows = palace_grants(engine)
    assert len(rows) == 1, [(e.source_definition_id, e.payload) for e in grants(engine)]
    assert rows[0].payload["offered"] == expected


def test_palace_activation_is_once_per_long_rest(tmp_path):
    combat, table, mid = setup(tmp_path, 5, 8)
    use(combat, table, mid, PALACE_NAME, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp == 4
    # Once per long rest: the activation is no longer a legal candidate.
    assert not [c for c in engine.legal_candidates()
                if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == PALACE_NAME]
    assert [e.payload["offered"] for e in palace_grants(engine)] == [4]


def test_independent_higher_temp_hp_is_preserved(tmp_path):
    combat, table, mid = setup(tmp_path, 5, 8, hold_temp_hp=True)
    use(combat, table, mid, "Moonlit Vigil", OWNER)
    use(combat, table, mid, PALACE_NAME, OWNER)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    # Normal max replacement keeps the larger independent pool; the palace's
    # signed aggregate (CL5 + (-1) = 4) is offered once and does not replace it.
    assert actor.temporary_hp == 9
    rows = palace_grants(engine)
    assert len(rows) == 1, [(e.source_definition_id, e.payload) for e in grants(engine)]
    assert rows[0].payload["offered"] == 4
    assert rows[0].payload["before"] == 9
    assert rows[0].payload["after"] == 9
