"""Public synthetic parent admissions and committed Soulwake transactions.

No historical checkout, private fixture, model server or GUI is used here.
"""
import copy
from pathlib import Path
import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.source_acquisition import SourceAcquisitionStore, acquire_feature, acquired_feature_ids
from combat.ext import black_current_walker as bc
from tests.test_c2_review import until_turn, action as table_action, send, reload
from tests.test_riders_c2 import ME, ATK, ALLY

SPIRIT = "tianxia.path.spirit_awakening"
SPIKE = SPIRIT + ".feature.mind_spike"
ACCESS = {"kind": "restricted_spirit_tradition", "basis": "river_infiltrator_school", "record_id": "owner:synthetic-school-admission"}
ROOT = Path(__file__).resolve().parents[1]


def action(table, mid, name, target=None):
    """Select the unbound River-Cut intent when the test answers its chooser.

    Native menus also expose ranked destination-bound siblings. Their accepted
    destination must win over unrelated route-choice answers, so choosing the
    first ranked option would exercise a different route than these tests ask.
    """
    if name.startswith("River-Cut Passage:"):
        menu = table.state(mid)["menu"]
        return next(o["candidate_id"] for group in menu["actions"] if group["label"] == name
                    for o in group["options"] if o.get("destination") is None)
    return table_action(table, mid, name, target)


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
    choices = dict(choices or {})
    choices.setdefault("choice:needle.black_current.domain_current", "north")
    # These synthetic encounters explicitly represent real opposition. Supply
    # the new event-scoped table testimony; exclusion tests override it below.
    choices.setdefault("choice:needle.black_current.qualifying_event", "real")
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
                        **({"option_ids": picked if isinstance(picked, list) else [picked]} if picked else {})})
    pytest.fail("unending Black Current choice transaction")


def fixture(tmp_path, *, cl=10, effective=None, resonance=30, dc=100, hazard=False, foe_at=(4, 6), foe_size="Medium",
            ally_at=(10, 6), owner_at=(3, 6), elevated=False, senses=False, vertical_wall=False,
            controls=None, ally_team="team:a", teleport_dc=None, grapple_dc=None, seal=False,
            surface=None, surface_height=5, owner_size="Medium", ally_summons=False, shove_dc=None, wide_dock=False):
    def configure(packs):
        if shove_dc is not None:
            foe = next(p for p in packs if p["actor_id"] == ATK)
            shove = next(a for a in foe["action_catalog"] if a["display_name"] == "Shove: Prone")
            shove["parameters"]["typed"]["numbers"]["save_dc"] = shove_dc
        if seal:
            pack = next(p for p in packs if p["actor_id"] == ATK)
            base = next(a for a in pack["action_catalog"] if a["display_name"] == "Mind Spike")
            ward = copy.deepcopy(base)
            ward.update(source_definition_id="action:test.black_current_seal", display_name="Synthetic sealed segment",
                        target_kind="SELF", economy="NONE")
            ward["parameters"].update(free_primary=True)
            ward["parameters"]["typed"].update(effects=[{"type": "zone"}], zone_spec={
                "name": "Synthetic sealed segment", "shape": "sphere", "size_ft": 0,
                "cells": [{"x": 2, "y": 6}], "sealed": True, "duration": {"kind": "rounds", "amount": 10}, "triggers": []})
            pack["action_catalog"].append(ward)
            pack["actor_template"]["action_ids"].append(ward["source_definition_id"])
        if grapple_dc is not None:
            foe = next(p for p in packs if p["actor_id"] == ATK)
            grapple = next(a for a in foe["action_catalog"] if a["display_name"] == "Grapple")
            # Synthetic opposed numbers retain native Grapple delivery, source
            # classification and part allocation; there is no hand-placed hold.
            grapple["parameters"]["typed"]["numbers"]["save_dc"] = grapple_dc
            owner = next(p for p in packs if p["actor_id"] == ME)
            owner["actor_template"]["saving_throws"].update(STR=-100, DEX=-100)
        if teleport_dc is not None:
            pack = next(p for p in packs if p["actor_id"] == ATK)
            base = next(a for a in pack["action_catalog"] if a["display_name"] == "Mind Spike")
            teleport = copy.deepcopy(base)
            teleport.update(source_definition_id="action:test.black_current_teleport", display_name="Synthetic higher-authority teleport",
                            target_kind="SELF", range_ft=30, costs=[])
            teleport["parameters"]["typed"].update(source="test:black_current_teleport", effects=[
                {"type": "movement", "mode": "teleport", "applies_to": "self", "distance_ft": 30}],
                numbers={"cl": 20, "pb": 6, "key_mod": 4, "save_dc": teleport_dc})
            pack["action_catalog"].append(teleport)
            pack["actor_template"]["action_ids"].append(teleport["source_definition_id"])
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
    owner = sheet(cl, effective=effective, resonance=resonance, dc=dc)
    owner["identity"]["size"] = owner_size
    documents = {ME: acquired(tmp_path, owner), ATK: other, ALLY: sheet()}
    if ally_summons:
        documents[ALLY]["spheres_and_talents"] = {"learned_talent_record_ids": ["TAL_DEATH_CORPSE_SERVANT"]}
    if senses:
        documents[ME]["path_and_subpath"]["path_feature_record_ids"].append(SPIRIT + ".feature.spiritual_sense")
    packs = [compile_character(document, actor_id=actor, reaction_plan={"ask": True}) for actor, document in documents.items()]
    configure(packs)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    # Explicit public geometry, not guessed free cells in the retired Pillar
    # Arena. The required Qi hazard is outside every route exercised here.
    arena = {"stable_id": "battlefield:black_current_synthetic", "kind": "BATTLEFIELD", "display_name": "Synthetic open court",
             "source": "Synthetic Black Current regression", "battlefield_version": "1.0.0", "width_squares": 20,
             "height_squares": 14, "square_size_ft": 5, "information_model": "FULLY_VISIBLE", "starting_positions": {},
             "victory_boundary": "NONLETHAL_WARDED_COURT", "terrain_regions": [
                 {"region_id": "hazard.synthetic_remote", "terrain_type": "QI_HAZARD", "movement_cost": 2,
                  "description": "Remote synthetic hazard", "cells": [{"x": 19, "y": 13}]}]}
    places = {ME: {"x": 3, "y": 6}, ATK: {"x": foe_at[0], "y": foe_at[1]}, ALLY: {"x": 10, "y": 6}}
    for aid, cell in ((ME, owner_at), (ATK, foe_at), (ALLY, ally_at)):
        places[aid] = dict(zip(("x", "y", "z"), cell))
    if elevated:
        arena["roof_surfaces"] = [{"id": "synthetic platform", "height_ft": 15,
                                   "cells": [{"x": x, "y": y} for x in range(20) for y in range(14)]}]
    if vertical_wall:
        arena["terrain_regions"].append({"region_id": "synthetic_wall", "terrain_type": "BLOCKED", "movement_cost": 1,
                                         "height_ft": 10, "cells": [{"x": 2, "y": 5}]})
        arena["roof_surfaces"] = [{"id": "wall top", "height_ft": 10, "cells": [{"x": 2, "y": 5}]}]
    if surface:
        # A real stable embarkation platform beside finite authored matter.
        # No floor/roof is invented over the destination surface.
        dock = [{"x": 3, "y": 6}, *([{"x": 4, "y": 6}] if wide_dock else [])]
        arena["roof_surfaces"] = [{"id": "embarkation", "height_ft": surface_height, "cells": dock}]
        arena["terrain_regions"].append({"region_id": "synthetic_surface", "terrain_type": "OPEN", "movement_cost": 1,
            "material": surface, "material_only": True, "height_ft": surface_height,
            "cells": [{"x": x, "y": 6} for x in (1, 2, 18, 19)]})
    teams = {ME: "team:a", ATK: "team:b", ALLY: ally_team}
    mid = combat._finish_factory_match(packs, list(documents), teams, places,
        arena, [aid for aid in documents if teams[aid] == "team:a"], [aid for aid in documents if teams[aid] == "team:b"],
        control_modes=controls or {actor: "MANUAL" for actor in documents}, match_seed="BLACK-CURRENT-PARENT",
        display_name="Black Current parent regression", maximum_rounds=20)["match_id"]
    return combat, table, mid


def create_wake(table, mid):
    until_turn(table, mid, ME)
    prompts = settle(table, mid, action(table, mid, "Mind Spike", ATK),
                     {"choice:needle.flow_after_the_strike": "cell:1,6"})
    assert any("Flow After the Strike" in p["reaction"] for p in prompts)


def test_real_flow_wake_caps_replaces_expires_and_cold_replays(tmp_path):
    _, table, mid = fixture(tmp_path)
    create_wake(table, mid)
    engine = reload(tmp_path, mid)
    assert bc.soulwake(engine.state.actors[ME]) == [(2, 6, 0), (1, 6, 0)]
    wakes = [c for c in engine.state.actors[ME].conditions.values() if c.condition_id == bc.WAKE]
    assert len(wakes) == 1 and wakes[0].expires_on == "START_OF_SOURCE_NEXT_TURN"
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    until_turn(table, mid, ME)
    assert not bc.soulwake(reload(tmp_path, mid).state.actors[ME])


def test_bound_river_cut_uses_accepted_destination_without_an_unbound_choice(tmp_path):
    from combat.gate2_runtime_models import Position
    _, table, mid = fixture(tmp_path)
    until_turn(table, mid, ME)
    before = reload(tmp_path, mid)
    candidate = next(c for c in before.legal_candidates() if c.kind == "ACTION"
                     and c.destination == Position(x=1, y=6)
                     and before.action_catalog[c.source_definition_id].display_name == "River-Cut Passage: Psychic")
    prompts = settle(table, mid, candidate.candidate_id)
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.river_cut_route" for p in prompts)
    after = reload(tmp_path, mid)
    assert after.state.actors[ME].position == Position(x=1, y=6)
    assert bc.soulwake(after.state.actors[ME]) == [(2, 6, 0), (1, 6, 0)]


@pytest.mark.parametrize("circumstances", ["real", "staged", "harmless", "willing", "captive", "allied_summon",
                                            "unchanged", "refunded", "loop", "unknown", None])
def test_flow_requires_actual_event_testimony_and_every_r7_exclusion(tmp_path, circumstances):
    _, table, mid = fixture(tmp_path, cl=3)
    until_turn(table, mid, ME)
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, action(table, mid, "Mind Spike", ATK), {
        "choice:needle.black_current.qualifying_event": circumstances,
        "choice:needle.flow_after_the_strike": "cell:1,6",
    })
    assert any(p["context"]["reaction_source_id"] == "choice:needle.black_current.qualifying_event" for p in prompts)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.flow_after_the_strike" for p in prompts) is (circumstances == "real")
    after = reload(tmp_path, mid)
    assert bool(bc.soulwake(after.state.actors[ME])) is (circumstances == "real")
    receipts = [e for e in after.events[len(before.events):] if e.payload.get("black_current_qualifying_event")]
    assert len(receipts) == 1 and receipts[0].actor_id == ME and receipts[0].target_ids == (ATK,)
    packet = next(e for e in after.events if e.sequence == receipts[0].payload["event_sequence"])
    assert packet.event_type == "DAMAGE_COMMITTED" and packet.actor_id == ME and packet.target_ids == (ATK,)
    assert packet.payload["black_current_target_active"] == 1
    assert receipts[0].payload["circumstances"] == (circumstances or "unknown")
    assert after.state.actors[ME].resources[bc.RESONANCE] == before.state.actors[ME].resources[bc.RESONANCE]


@pytest.mark.parametrize("human_witness", [True, False])
def test_automatic_flow_uses_actual_human_witness_or_unknown(tmp_path, human_witness):
    from tests.test_c2_review import auto_send
    combat, table, mid = fixture(tmp_path, cl=3)
    until_turn(table, mid, ME)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    if not human_witness:
        for aid in (ATK, ALLY):
            combat.set_controller_mode(mid, actor_id=aid, controller_mode="LOCAL_AUTO")
    cid = action(table, mid, "Mind Spike", ATK)
    answers, prompts = [], []
    for _ in range(24):
        result = auto_send(combat, table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        prompts.append(p)
        fact = p["context"]["reaction_source_id"] == "choice:needle.black_current.qualifying_event"
        if fact:
            assert human_witness and p["context"]["reactor_id"] in (ATK, ALLY)
        answers.append({**p["context"], "selection": "USE" if fact else "DECLINE",
                        **({"option_ids": ["real"]} if fact else {})})
    else:
        pytest.fail("unending automatic Flow transaction")
    after = reload(tmp_path, mid)
    receipts = [e for e in after.events if e.payload.get("black_current_qualifying_event")]
    assert len(receipts) == 1
    assert receipts[0].payload["circumstances"] == ("real" if human_witness else "unknown")
    assert any(p["context"]["reaction_source_id"] == "choice:needle.black_current.qualifying_event" for p in prompts) is human_witness


def test_qualifying_event_is_inert_below_owned_parent_level(tmp_path):
    _, table, mid = fixture(tmp_path, effective=2)
    until_turn(table, mid, ME)
    prompts = settle(table, mid, action(table, mid, "Mind Spike", ATK))
    after = reload(tmp_path, mid)
    assert not any(p["context"]["reaction_source_id"] == "choice:needle.black_current.qualifying_event" for p in prompts)
    assert not any(e.payload.get("black_current_qualifying_event") for e in after.events)
    assert not bc.soulwake(after.state.actors[ME])


def test_r7_allied_summon_exclusion_uses_actual_summon_owner_despite_hostile_relation(tmp_path):
    from combat import summons
    combat, table, mid = fixture(tmp_path, cl=3, ally_at=(7, 6), ally_summons=True)
    engine = reload(tmp_path, mid)
    servant = summons.owned_by(engine, ALLY)[0]
    assert servant.active and servant.summon["owner"] == ALLY
    combat.change_relations(mid, change={"kind": "ACTOR_RELATION", "subject": ME, "other": servant.entity_id,
                                       "relation": "ENEMY"}, expected_state_version=engine.state.state_version)
    until_turn(table, mid, ME)
    before = reload(tmp_path, mid)
    prompts = settle(table, mid, action(table, mid, "Mind Spike", servant.entity_id), {
        "choice:needle.black_current.qualifying_event": "real",
        "choice:needle.flow_after_the_strike": "cell:1,6",
    })
    after = reload(tmp_path, mid)
    damage = [e for e in after.events[len(before.events):] if e.event_type == "DAMAGE_COMMITTED"
              and servant.entity_id in e.target_ids]
    assert damage and damage[-1].payload["black_current_allied_summon"] == 1
    assert not any(p["context"]["reaction_source_id"] in (
        "choice:needle.black_current.qualifying_event", "choice:needle.flow_after_the_strike") for p in prompts)
    assert not bc.soulwake(after.state.actors[ME])


def test_interrupted_flow_records_only_legally_entered_prefix(tmp_path):
    _, table, mid = fixture(tmp_path, hazard=True)
    until_turn(table, mid, ATK)
    settle(table, mid, action(table, mid, "Synthetic entry hold"))
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    create_wake(table, mid)
    engine = reload(tmp_path, mid)
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (2, 6)
    assert bc.soulwake(engine.state.actors[ME]) == [(2, 6, 0)], "the unvisited requested endpoint is not a wake cell"


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
    candidate = next(c for c in before.legal_candidates() if c.display_name == "River-Cut Passage: Psychic")
    prompts = settle(table, mid, candidate.candidate_id, {"choice:needle.river_cut_route": "cell:0,6"})
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
    assert (move.destination.x, move.destination.y, move.destination.z) not in bc.soulwake(before.state.actors[ME])
    assert {(x, y, move.destination.z) for x, y in before._actor_cells(before.state.actors[ATK], move.destination)} & set(bc.soulwake(before.state.actors[ME]))
    prompts = settle(table, mid, move.candidate_id)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.black_current.pursuer_entry" for p in prompts)
    reload(tmp_path, mid)
