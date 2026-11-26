"""Short Swap requires both creatures to be able to teleport willingly."""
import pytest

from combat import placement_menu
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, NAMED, OWNER, fixture, reload, settle, turn

DREAM_ASCENSION = "tianxia.subpath.qi.dream_qi_cultivator.feature.dream_ascension"
SHORT_SWAP = "tianxia.talent.space.short_swap"
CONSENT = "choice:needle.space_swap_agree"


@pytest.mark.parametrize("burdened_role", ["caster", "target"])
def test_dream_burden_blocks_both_short_swap_roles_at_the_table(tmp_path, burdened_role):
    caster, target = (FOE, ALLY) if burdened_role == "caster" else (ALLY, FOE)
    foe_sheet = sheet([SHORT_SWAP] if caster == FOE else [], cl=20, name=NAMED[2])
    foe_sheet["ability_scores_and_statistics"]["hit_points"]["maximum"] = 400
    combat, table, match = fixture(
        tmp_path, [DREAM_ASCENSION], cl=20, owner_dc=100, named=True, foe_sheet=foe_sheet,
        ally_talents=[SHORT_SWAP] if caster == ALLY else [],
        team_overrides={ALLY: "team:opponents"},
        seed="DREAM-SHORT-SWAP",
        positions={OWNER: {"x": 3, "y": 5}, ALLY: {"x": 2, "y": 5}, FOE: {"x": 6, "y": 5}},
    )
    engine = combat._load_session(match).engine
    with placement_menu.query():
        dream = next(c for c in engine.legal_candidates()
                     if c.source_definition_id in engine.action_catalog
                     and engine.action_catalog[c.source_definition_id].display_name == "Dream Ascension")
    # The field starts at x=6: only FOE starts a turn inside it.
    settle(table, match, dream.candidate_id, picks={placement_menu.CHOICE: ["cell:12,5,0"]})
    for _ in engine.state.initiative_order:
        menu = table.state(match)["menu"]
        if menu["actor_id"] == FOE:
            break
        settle(table, match, menu["end_turn"],
               picks={"choice:needle.effect_choices": "No willing teleportation"})
    else:
        pytest.fail("The burdened creature did not get a turn")
    turn(table, match, caster)

    engine = reload(tmp_path, match)
    assert {
        aid for aid in (caster, target)
        if any(c.condition_id == "condition:typed.cannot_willingly_teleport"
               for c in engine.state.actors[aid].conditions.values())
    } == {FOE}
    before = {aid: engine.state.actors[aid].position for aid in (caster, target)}
    sequence = engine.state.event_sequence
    swap = next(c for c in engine.legal_candidates()
                if c.display_name == "Short Swap" and c.target_ids == (target,))
    # If asked, the target would agree, so a refusal cannot mask the bypass.
    prompts = settle(table, match, swap.candidate_id, picks={CONSENT: "first"})

    engine = reload(tmp_path, match)
    assert {aid: engine.state.actors[aid].position for aid in before} == before
    assert not any(p["context"]["reaction_source_id"] == CONSENT for p in prompts)
    events = [e for e in engine.events if e.sequence > sequence and e.source_definition_id == swap.source_definition_id]
    assert not any(e.event_type == "MOVEMENT_COMMITTED" for e in events)
    assert any(e.event_type == "GM_RIDER" and f"{NAMED[2]} cannot teleport willingly" in e.payload["rider"]
               for e in events)
