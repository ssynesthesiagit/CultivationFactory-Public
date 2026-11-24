"""An Ask-the-GM selection is not an explicitly confirmed learned fact."""
from combat.ext.mind_hidden_eye import FOCUS, analyzed_by
from tests.h1_support import sheet
from tests.worker2_support import OWNER, FOE, fixture, turn, candidate, settle, reload
from tests.test_a2_hidden_eye_fix_round import BASE, TALENT, CHOICE, APPROACH, LEARN, named_bundles, notice, card


def test_unconfirmed_narrative_selection_does_not_invent_a_notice(tmp_path):
    combat, table, mid = fixture(tmp_path, [BASE, TALENT], cl=5, seed="A2-NOTICE",
                                bundle_transform=named_bundles, foe_sheet=sheet([BASE], cl=5))
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, FOE)
    before = combat._load_session(mid).engine.state.actors[OWNER].resources[FOCUS]
    chosen = candidate(combat, mid, "Analyze", target=OWNER)
    prompts = settle(table, mid, chosen.candidate_id,
                     picks={APPROACH: "Investigation", LEARN: "GM information 1", CHOICE: None})
    engine = reload(tmp_path, mid)
    assert analyzed_by(engine.state.actors[OWNER], FOE)
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    assert notice(engine) is None and card(tmp_path, mid) is None
    assert engine.state.actors[OWNER].resources[FOCUS] == before
    assert any(e.event_type == "GM_RIDER" and "narrative" in str(e.payload) for e in engine.events)
