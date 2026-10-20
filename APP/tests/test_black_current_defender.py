"""Native Grapple, recipient-controller consent and altitude through cold tables."""
import pytest

from combat.ext import black_current_walker as bc
from tests.test_black_current_parent import fixture, settle, create_wake
from tests.test_c2_review import until_turn, action, reload
from tests.test_riders_c2 import ME, ATK, ALLY


@pytest.mark.parametrize("destination,resonance", [("cell:1,6", 30), ("cell:3,6", 30), (None, 30), (None, 1)])
def test_native_grapple_defender_checkpoint_scoped_save_and_replay(tmp_path, destination, resonance):
    _, table, mid = fixture(tmp_path, cl=6, resonance=resonance)
    until_turn(table, mid, ATK)
    before = reload(tmp_path, mid)
    points = before.state.actors[ME].resources[bc.RESONANCE]
    prompts = settle(table, mid, action(table, mid, "Grapple", ME),
                     {"choice:needle.black_current.pursuer_grapple": destination})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.black_current.pursuer_grapple" for p in prompts) is (resonance >= 2)
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].resources[bc.RESONANCE] == points - (2 if destination else 0)
    replies = [e for e in after.events if e.event_type == "REACTION_RESOLVED" and e.payload.get("checkpoint") == "GRAPPLE_DECLARED"]
    assert bool(replies) is bool(destination)
    saves = [e for e in after.events[len(before.events):] if e.event_type == "SAVE_ROLLED" and e.actor_id == ME]
    if destination == "cell:1,6":
        assert replies[-1].payload["cancelled"] is True and not saves
        assert not any(c.condition_id.endswith(".grappled") for c in after.state.actors[ME].conditions.values())
    elif destination:
        assert replies[-1].payload["advantage"] is True and len(saves) == 1
        assert "ADVANTAGE" in str(saves[-1].payload)
    assert not any("grapple_guard" in c.condition_id for c in after.state.actors[ME].conditions.values())


@pytest.mark.parametrize("recipient,answer", [(ALLY, "accept"), (ALLY, "refuse"), (ATK, "accept"), (ATK, "refuse")])
def test_carry_the_reed_recipient_decides_before_extra_payment(tmp_path, recipient, answer):
    _, table, mid = fixture(tmp_path, cl=6, ally_at=(3, 5))
    until_turn(table, mid, ATK)
    before = reload(tmp_path, mid)
    origin = before.state.actors[recipient].position
    destination = "cell:3,6"
    prompts = settle(table, mid, action(table, mid, "Grapple", ME), {
        "choice:needle.black_current.pursuer_grapple": "cell:1,6",
        "choice:needle.black_current.carry_the_reed": recipient,
        "choice:needle.carry_the_reed_to": destination,
        "choice:willing.consent": answer,
    })
    consent = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent"]
    assert len(consent) == 1 and consent[0]["context"]["reactor_id"] == recipient
    after = reload(tmp_path, mid)
    assert (after.state.actors[recipient].position != origin) is (answer == "accept")
    assert after.state.actors[ME].resources[bc.RESONANCE] == before.state.actors[ME].resources[bc.RESONANCE] - 2 - (answer == "accept")


@pytest.mark.parametrize("walker_height,mover_height", [(0, 3), (3, 0), (3, 3)])
def test_elevated_and_ground_wakes_do_not_create_phantom_entry(tmp_path, walker_height, mover_height):
    _, table, mid = fixture(tmp_path, owner_at=(3, 6, walker_height), foe_at=(4, 6, mover_height), elevated=True)
    until_turn(table, mid, ME)
    flow = f"cell:1,6" + (f",{walker_height}" if walker_height else "")
    settle(table, mid, action(table, mid, "River-Cut Passage: Psychic"), {"choice:needle.river_cut_route": flow})
    wake = bc.soulwake(reload(tmp_path, mid).state.actors[ME])
    assert wake == [(2, 6, walker_height), (1, 6, walker_height)]
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ATK)
    engine = reload(tmp_path, mid)
    candidate = next(c for c in engine.legal_candidates() if c.kind == "MOVE" and c.destination.x == 2
                     and c.destination.y == 6 and c.destination.z == mover_height)
    prompts = settle(table, mid, candidate.candidate_id)
    entry = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.black_current.pursuer_entry"]
    assert bool(entry) is (walker_height == mover_height)
    reload(tmp_path, mid)


@pytest.mark.parametrize("ally_team,accepted", [("team:a", True), ("team:b", False)])
def test_ai_recipient_uses_its_own_consent_policy(tmp_path, ally_team, accepted):
    _, table, mid = fixture(tmp_path, cl=6, ally_at=(3, 5), ally_team=ally_team,
                            controls={ME: "MANUAL", ATK: "MANUAL", ALLY: "LOCAL_AUTO"})
    until_turn(table, mid, ATK)
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, action(table, mid, "Grapple", ME), {
        "choice:needle.black_current.pursuer_grapple": "cell:1,6",
        "choice:needle.black_current.carry_the_reed": ALLY,
        "choice:needle.carry_the_reed_to": "cell:3,6",
    })
    assert not any(p["context"]["reaction_source_id"] == "choice:willing.consent" for p in prompts)
    after = reload(tmp_path, mid)
    assert (after.state.actors[ALLY].position != before.state.actors[ALLY].position) is accepted


def test_vertical_source_route_and_private_sense_projection_cold_replay(tmp_path):
    from combat.senses import perception
    _, table, mid = fixture(tmp_path, vertical_wall=True, senses=True)
    until_turn(table, mid, ME)
    from combat.gate2_runtime_models import Position
    before = reload(tmp_path, mid)
    source = next(a for a in before.action_catalog.values() if a.display_name == "River-Cut Passage: Psychic" and a.owner_id == ME)
    offered = bc.river_cut_spaces(before, before.state.actors[ME], source, 30)
    assert Position(x=2, y=5, z=2) in offered, {
        "count": len(offered), "speed": before._effective_speed(before.state.actors[ME]),
        "rows": before.typed_passive_rows.get(ME), "roofs": str(before.grid.roof_surfaces),
    }
    prompts = settle(table, mid, action(table, mid, "River-Cut Passage: Psychic"),
                     {"choice:needle.river_cut_route": "cell:2,5,2"})
    assert any("cell:2,5,2" in str(p) for p in prompts)
    after = reload(tmp_path, mid)
    wake = bc.soulwake(after.state.actors[ME])
    assert wake[-1] == (2, 5, 2) and len(wake) >= 2
    assert all(max(abs(a[i]-b[i]) for i in range(3)) == 1 for a,b in zip(wake,wake[1:]))
    own_facts = perception(after, after.state.actors[ME])["information"]
    assert any(f.get("kind") == "spatial_trace" and f["spaces"][-1] == {"x": 2, "y": 5, "z": 2} for f in own_facts)
    other_facts = perception(after, after.state.actors[ATK]).get("information", [])
    assert not any(f.get("kind") == "spatial_trace" for f in other_facts)


def test_current_without_footing_falls_when_turn_ends_without_phantom_wake(tmp_path):
    _, table, mid = fixture(tmp_path, cl=3, vertical_wall=True)
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "Mind Spike", ATK),
                     {"choice:needle.flow_after_the_strike": "cell:3,5,1"})
    elevated = reload(tmp_path, mid)
    assert elevated.state.actors[ME].position.z == 1
    wake = bc.soulwake(elevated.state.actors[ME])
    assert wake[-1] == (3, 5, 1)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    fallen = reload(tmp_path, mid)
    assert fallen.state.actors[ME].position.z == 0
    assert bc.soulwake(fallen.state.actors[ME]) == wake, "falling is not another entered spiritual-step cell"


@pytest.mark.parametrize("route_dc,arrives", [(1, True), (100, False)])
def test_higher_authority_undertow_records_real_route_and_pays_failed_attempt(tmp_path, route_dc, arrives):
    _, table, mid = fixture(tmp_path, cl=14, teleport_dc=route_dc)
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "Mind Spike", ATK))
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ATK)
    before = reload(tmp_path, mid)
    teleport = next(c for c in before.legal_candidates() if c.source_definition_id == "action:test.black_current_teleport"
                    and c.destination is not None and (c.destination.x, c.destination.y) == (8, 6))
    settle(table, mid, teleport.candidate_id, {
        "choice:needle.teleport_destination": "cell:8,6",
        "choice:needle.black_current.undertow_relocated": "pursue",
        "choice:needle.undertow_pursuit": "cell:6,6",
    })
    after = reload(tmp_path, mid)
    receipts = [e for e in after.events[len(before.events):] if e.event_type == "PASSIVE_TRIGGERED" and e.payload.get("black_current_pursuit")]
    assert receipts and receipts[-1].payload["movement_type"] == "teleport"
    assert receipts[-1].payload["origin"] == {"x": 4, "y": 6}
    assert receipts[-1].payload["destination"] == {"x": 8, "y": 6}
    assert receipts[-1].payload["route_source_cl"] == 20
    assert (after.state.actors[ME].position != before.state.actors[ME].position) is arrives
    assert after.state.actors[ME].resources[bc.RESONANCE] == before.state.actors[ME].resources[bc.RESONANCE] - 4


def test_river_cut_passage_wake_mark_blocks_only_attacks_of_opportunity_against_walker(tmp_path):
    _, table, mid = fixture(tmp_path)
    until_turn(table, mid, ME)
    before = reload(tmp_path, mid)
    settle(table, mid, action(table, mid, "River-Cut Passage: Psychic"), {
        "choice:needle.river_cut_route": "cell:5,6",
        "choice:needle.black_current.wake_mark": "mark",
    })
    after = reload(tmp_path, mid)
    walker, foe, other = (after.state.actors[aid] for aid in (ME, ATK, ALLY))
    assert bc._te().bears_mark(foe, ME, "Resonance")
    assert bc.st.can_react(foe), "Wake Mark does not deny other Reactions"
    assert bc.wake_mark_opportunity(after, foe, walker) is False
    assert bc.wake_mark_opportunity(after, foe, other) is None
    assert walker.resources[bc.RESONANCE] == before.state.actors[ME].resources[bc.RESONANCE] - 6


@pytest.mark.parametrize("hold_dc,escapes", [(1, True), (100, False)])
def test_no_bank_escapes_actual_native_hold_only_after_route_choice(tmp_path, hold_dc, escapes):
    _, table, mid = fixture(tmp_path, cl=14, grapple_dc=hold_dc)
    until_turn(table, mid, ATK)
    settle(table, mid, action(table, mid, "Grapple", ME))
    held = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.grappled" for c in held.state.actors[ME].conditions.values())
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ME)
    before = reload(tmp_path, mid)
    settle(table, mid, action(table, mid, "River-Cut Passage: Psychic"), {"choice:needle.river_cut_route": "cell:1,6"})
    after = reload(tmp_path, mid)
    assert (after.state.actors[ME].position != before.state.actors[ME].position) is escapes
    assert any(c.condition_id == "condition:typed.grappled" for c in after.state.actors[ME].conditions.values()) is not escapes
    checks = [e for e in after.events[len(before.events):] if e.event_type == "CHECK_ROLLED"]
    assert checks and checks[-1].payload["dc"] == hold_dc


def test_ordered_wake_routes_cannot_skip_a_newly_sealed_segment(tmp_path):
    from combat.gate2_runtime_models import Position
    _, table, mid = fixture(tmp_path, ally_at=(3, 5), seal=True)
    until_turn(table, mid, ME)
    settle(table, mid, action(table, mid, "River-Cut Passage: Psychic"), {"choice:needle.river_cut_route": "cell:0,6"})
    before = reload(tmp_path, mid)
    end = Position(x=1, y=6)
    assert end in bc.wake_routes(before, before.state.actors[ME], before.state.actors[ALLY], 10)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ATK)
    settle(table, mid, action(table, mid, "Synthetic sealed segment"))
    after = reload(tmp_path, mid)
    assert bc.soulwake(after.state.actors[ME]) == bc.soulwake(before.state.actors[ME])
    assert end not in bc.wake_routes(after, after.state.actors[ME], after.state.actors[ALLY], 10)
