"""Public synthetic parent admissions and committed Soulwake transactions.

No historical checkout, private fixture, model server or GUI is used here.
"""
import copy
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.source_acquisition import SourceAcquisitionStore, acquire_feature, acquired_feature_ids
from combat.ext import black_current_walker as bc
from tests.test_c2_review import table_fixture, until_turn, action, send, reload
from tests.test_riders_c2 import ME, ATK, ALLY

SPIRIT = "tianxia.path.spirit_awakening"
SPIKE = SPIRIT + ".feature.mind_spike"
ACCESS = {"kind": "restricted_spirit_tradition", "basis": "river_infiltrator_school", "record_id": "owner:synthetic-school-admission"}


def sheet(cl=10, *, effective=None, spirit=None, dc=100, resonance=30):
    identity = {"proficiency_bonus": 2, "cultivation_level": cl, "path": "Spirit Awakening", "key_ability": "WIS",
                "path_levels": {SPIRIT: cl if spirit is None else spirit}}
    if effective is not None:
        identity["effective_cultivation_level"] = effective
    return {"identity": identity, "path_and_subpath": {"path_record_ids": [SPIRIT], "path_feature_record_ids": [SPIKE]},
            "ability_scores_and_statistics": {
                "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
                "primary_resource": {"name": "Resonance", "maximum": resonance}, "armor_class": {"base_value": 14},
                "hit_points": {"maximum": 500}, "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 9}}


def acquired(tmp_path, document=None):
    document = document or sheet()
    store = SourceAcquisitionStore(tmp_path / "admission")
    store.acquire(document, bc.PARENT, actor_id=ME, occurrence_id="earned:black-current-parent", access_record=ACCESS)
    # Cold store read proves the owner/table access provenance is durable.
    fresh = SourceAcquisitionStore(tmp_path / "admission").load_into(document, actor_id=ME)
    assert fresh["combat_acquisitions"][0]["access_record"] == ACCESS
    return fresh


@pytest.mark.parametrize("spirit,effective,expected", [(3, 3, 1), (5, 5, 1), (6, 6, 2), (10, 5, 1), (18, 18, 5), (18, 2, 0)])
def test_parent_receipt_compiles_only_effective_spirit_progression(tmp_path, spirit, effective, expected):
    doc = acquired(tmp_path, sheet(18, spirit=spirit, effective=effective))
    ids = acquired_feature_ids(doc, actor_id=ME)
    assert len(ids) == expected
    assert ids == [bc.ENTER_THE_BLACK_CURRENT, bc.TURN, bc.RIVER_CUT, bc.NO_BANK, bc.PROCESSION][:expected]
    assert not set(ids) & set(doc["path_and_subpath"]["path_feature_record_ids"])
    pack = compile_character(doc, actor_id=ME)
    for row in pack["action_catalog"]:
        typed = row.get("parameters", {}).get("typed", {})
        if (typed.get("source") or typed.get("option_of") or "").startswith(bc.TRADITION):
            assert typed["numbers"]["cl"] == min(spirit, effective)


def test_parent_admission_rejects_missing_access_wrong_owner_and_unearned_path(tmp_path):
    with pytest.raises(ValueError, match="explicit owner/table access"):
        acquire_feature(sheet(), bc.PARENT, actor_id=ME, occurrence_id="bad")
    with pytest.raises(ValueError, match="owning Path"):
        acquire_feature(sheet(spirit=2), bc.PARENT, actor_id=ME, occurrence_id="bad", access_record=ACCESS)
    wrong_path = sheet()
    wrong_path["path_and_subpath"]["path_record_ids"] = ["tianxia.path.body_refining"]
    with pytest.raises(ValueError, match="owning Path"):
        acquire_feature(wrong_path, bc.PARENT, actor_id=ME, occurrence_id="bad", access_record=ACCESS)
    doc = acquired(tmp_path)
    with pytest.raises(ValueError, match="another creature"):
        compile_character(doc, actor_id=ATK)
    with pytest.raises(ValueError, match="printed feature requirement"):
        acquire_feature(sheet(), bc.PARENT, actor_id=ME, occurrence_id="bad", access_record={**ACCESS, "basis": "guessed_lineage"})


def test_parent_uses_canonical_source_identity_and_rejects_mismatched_index(monkeypatch):
    from combat import source_acquisition as admission

    sources = admission._sources()
    prose = {key: "Public presentation variant" for key in sources[0]}
    monkeypatch.setattr(admission, "_sources", lambda: (prose, sources[1]))
    acquired = acquire_feature(sheet(), bc.PARENT, actor_id=ME, occurrence_id="canonical", access_record=ACCESS)
    assert acquired_feature_ids(acquired, actor_id=ME) == [bc.ENTER_THE_BLACK_CURRENT, bc.TURN, bc.RIVER_CUT]
    original = admission._progression
    def mismatched(contract):
        parent = copy.deepcopy(original(contract))
        parent["feature_progression"][0]["source"]["section_sha256"] = "0" * 64
        return parent
    monkeypatch.setattr(admission, "_progression", mismatched)
    with pytest.raises(ValueError, match="active printed source"):
        acquire_feature(sheet(), bc.PARENT, actor_id=ME, occurrence_id="mismatch", access_record=ACCESS)


def test_complete_destination_transport_includes_the_49th_legal_cell(monkeypatch):
    from combat.ext import needle
    from combat.gate2_runtime_models import Position
    from types import SimpleNamespace

    start = Position(x=0, y=0)
    cells = [Position(x=x, y=y) for x in range(8) for y in range(8)]
    options = {cell: ((start, cell), 5) for cell in cells if cell != start}
    actor = SimpleNamespace(entity_id=ME, position=start)
    wanted = cells[-1]
    offered = []
    def ask(engine, intent, checkpoint, chooser, choice_id, ids, **kwargs):
        offered.extend(ids)
        return [needle.cell_id(wanted)]
    monkeypatch.setattr(needle, "ask", ask)
    monkeypatch.setattr(needle, "checkpoint_id", lambda *args: "synthetic-destination-checkpoint")
    assert bc.choose_route(None, actor, options, None, checkpoint="TEST", prompt="Choose a legal space", name="Black Current",
                           feature=bc.PROCESSION)[-1] == wanted
    assert len(offered) == 63 and needle.cell_id(wanted) in offered


def settle(table, mid, cid, choices=None):
    choices = choices or {}
    answers, prompts = [], []
    for _ in range(24):
        result = send(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        source = prompt["context"]["reaction_source_id"]
        picked = choices.get(source)
        answers.append({**prompt["context"], "selection": "USE" if picked else "DECLINE",
                        **({"option_ids": [picked]} if picked else {})})
    pytest.fail("unending Black Current choice transaction")


def fixture(tmp_path, *, cl=10, effective=None, resonance=30, dc=100, hazard=False, foe_at=(4, 6), foe_size="Medium"):
    def configure(packs):
        if hazard:
            pack = next(p for p in packs if p["actor_id"] == ATK)
            base = next(a for a in pack["action_catalog"] if a["display_name"] == "Mind Spike")
            trap = copy.deepcopy(base)
            trap.update(source_definition_id="action:test.black_current_hazard", display_name="Synthetic entry hold", target_kind="SELF", economy="NONE")
            trap["parameters"].update(free_primary=True)
            trap["parameters"]["typed"]["effects"] = [{"type": "zone"}]
            trap["parameters"]["typed"]["zone_spec"] = {"name": "Synthetic entry hold", "shape": "sphere", "size_ft": 0,
                "cells": [{"x": 2, "y": 6}], "duration": {"kind": "rounds", "amount": 10},
                "triggers": [{"id": "entered-hold", "on": ["enter"], "effects": [
                    {"type": "condition", "condition": "grappled", "applies_to": "target", "expires_on": "END_OF_CURRENT_TURN"}]}]}
            pack["action_catalog"].append(trap)
            pack["actor_template"]["action_ids"].append(trap["source_definition_id"])
        for pack in packs:
            pack.pop("bundle_sha256", None)
            pack["bundle_sha256"] = canonical_sha256(pack)
    other = sheet()
    other["identity"]["size"] = foe_size
    return table_fixture(tmp_path, {ME: acquired(tmp_path, sheet(cl, effective=effective, resonance=resonance, dc=dc)),
                                  ATK: other, ALLY: sheet()},
                         {ME: (3, 6), ATK: foe_at, ALLY: (10, 6)}, seed="BLACK-CURRENT-PARENT", configure=configure)


def create_wake(table, mid):
    until_turn(table, mid, ME)
    prompts = settle(table, mid, action(table, mid, "Mind Spike", ATK),
                     {"choice:needle.flow_after_the_strike": "cell:1,6"})
    assert any("Flow After the Strike" in p["reaction"] for p in prompts)


def test_real_flow_wake_caps_replaces_expires_and_cold_replays(tmp_path):
    _, table, mid = fixture(tmp_path)
    create_wake(table, mid)
    engine = reload(tmp_path, mid)
    assert bc.soulwake(engine.state.actors[ME]) == [(2, 6), (1, 6)]
    wakes = [c for c in engine.state.actors[ME].conditions.values() if c.condition_id == bc.WAKE]
    assert len(wakes) == 1 and wakes[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ME)
    assert not bc.soulwake(reload(tmp_path, mid).state.actors[ME])


def test_interrupted_flow_records_only_legally_entered_prefix(tmp_path):
    _, table, mid = fixture(tmp_path, hazard=True)
    until_turn(table, mid, ATK)
    settle(table, mid, action(table, mid, "Synthetic entry hold"))
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    create_wake(table, mid)
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (2, 6)
    assert bc.soulwake(engine.state.actors[ME]) == [(2, 6)], "the unvisited requested endpoint is not a wake cell"


@pytest.mark.parametrize("hazard", [False, True])
def test_river_cut_uses_actual_route_for_uncapped_wake_and_target_eligibility(tmp_path, hazard):
    _, table, mid = fixture(tmp_path, hazard=hazard, foe_at=(0, 7))
    if hazard:
        until_turn(table, mid, ATK)
        settle(table, mid, action(table, mid, "Synthetic entry hold"))
        settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ME)
    before = reload(tmp_path, mid)
    points = before.state.actors[ME].resources[bc.RESONANCE]
    candidate = next(c for c in before.legal_candidates() if "River-Cut Passage" in c.display_name
                     and c.destination is not None and c.destination.x == 0 and c.destination.y == 6)
    prompts = settle(table, mid, candidate.candidate_id)
    after = reload(tmp_path, mid)
    wake = bc.soulwake(after.state.actors[ME])
    assert len(wake) == (1 if hazard else 3)
    assert after.state.actors[ME].resources[bc.RESONANCE] == points - 5
    target_prompts = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.black_current.river_cut"]
    assert bool(target_prompts) is not hazard, "an unvisited part of the planned route grants no targets"


@pytest.mark.parametrize("decline,dc", [(False, 100), (False, -100), (True, 100)])
def test_native_entry_reaction_save_displacement_and_decline_replay(tmp_path, decline, dc):
    _, table, mid = fixture(tmp_path, dc=dc)
    create_wake(table, mid)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ATK)
    before = reload(tmp_path, mid)
    points = before.state.actors[ME].resources[bc.RESONANCE]
    move = next(c for c in before.legal_candidates() if c.display_name == "Move to 2,6")
    choices = {} if decline else {"choice:needle.black_current.pursuer_entry": "cell:1,6",
                                "choice:needle.pursuer_entry_to": "cell:2,5"}
    prompts = settle(table, mid, move.candidate_id, choices)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.black_current.pursuer_entry" for p in prompts)
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].resources[bc.RESONANCE] == points - (0 if decline else 2)
    assert after.state.actors[ME].reaction_available is decline
    resolved = [e for e in after.events if e.event_type == "REACTION_RESOLVED" and e.payload.get("checkpoint") == "SOULWAKE_ENTERED"]
    assert bool(resolved) is not decline
    if not decline:
        assert resolved[-1].payload["failed_save"] is (dc > 0)
        if dc > 0:
            assert any(c.condition_id == "condition:typed.reaction_denied" for c in after.state.actors[ATK].conditions.values())
            assert after.state.actors[ATK].position != move.destination
            settle(table, mid, table.state(mid)["menu"]["end_turn"])
            until_turn(table, mid, ME)
            assert not bc.st.can_react(reload(tmp_path, mid).state.actors[ATK])
            settle(table, mid, table.state(mid)["menu"]["end_turn"])
            until_turn(table, mid, ATK)
            assert bc.st.can_react(reload(tmp_path, mid).state.actors[ATK])
        else:
            assert after._effective_speed(after.state.actors[ATK]) == before._effective_speed(before.state.actors[ATK]) - 10
            settle(table, mid, table.state(mid)["menu"]["end_turn"])
            fresh = reload(tmp_path, mid)
            assert fresh._effective_speed(fresh.state.actors[ATK]) == before._effective_speed(before.state.actors[ATK])


@pytest.mark.parametrize("effective,resonance", [(5, 30), (10, 1)])
def test_wake_entry_requires_effective_feature_and_two_resonance(tmp_path, effective, resonance):
    _, table, mid = fixture(tmp_path, effective=effective, resonance=resonance)
    create_wake(table, mid)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ATK)
    before = reload(tmp_path, mid)
    points = before.state.actors[ME].resources[bc.RESONANCE]
    move = next(c for c in before.legal_candidates() if c.display_name == "Move to 2,6")
    prompts = settle(table, mid, move.candidate_id)
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.black_current.pursuer_entry" for p in prompts)
    assert reload(tmp_path, mid).state.actors[ME].resources[bc.RESONANCE] == points


def test_large_creature_enters_with_its_footprint_not_only_its_anchor(tmp_path):
    _, table, mid = fixture(tmp_path, foe_size="Large")
    create_wake(table, mid)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ATK)
    before = reload(tmp_path, mid)
    move = next(c for c in before.legal_candidates() if c.display_name == "Move to 2,5")
    assert (move.destination.x, move.destination.y) not in bc.soulwake(before.state.actors[ME])
    assert set(before._actor_cells(before.state.actors[ATK], move.destination)) & set(bc.soulwake(before.state.actors[ME]))
    prompts = settle(table, mid, move.candidate_id)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.black_current.pursuer_entry" for p in prompts)
    reload(tmp_path, mid)
