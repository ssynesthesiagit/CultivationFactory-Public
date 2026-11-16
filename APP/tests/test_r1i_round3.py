"""Compiled table regressions for Arc geometry, pre-hit Charges and allied menus.

riders/c13 (14cd285f, approved C13r3.review.md) replaces hostile Gather
Charge setups with real Charge hits; all Chains/Arc assertions are retained.
"""
import pytest

from combat import typed_executor as te
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, charge_setup, commit_charge, OWNER, FOE, SECOND, THIRD
from tests.test_r1i_service_chains import links


def resolve(combat, mid, send, cid, picks, *, auto=False):
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(16):
        result = send(cid, answers, auto=auto)
        if result["status"] == "COMMITTED":
            return before, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        prompts.append(p)
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert send(cid, answers, auto=auto)["reaction"] == p
        picked = picks.get(p["context"]["reaction_source_id"])
        if picked == "$first":
            picked = p["choice"]["options"][0]["id"]
        answer = {**p["context"], "selection": "USE" if picked else "DECLINE"}
        if picked:
            assert picked in [o["id"] for o in p["choice"]["options"]], p
            answer["option_ids"] = [picked]
        answers.append(answer)
    raise AssertionError("too many prompts")


def reload(tmp_path, mid):
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


@pytest.mark.parametrize("outside_caster", [False, True])
def test_chain_bolt_footwork_revalidates_secondary_origin_table(tmp_path, outside_caster):
    positions = {OWNER: {"x": 0, "y": 0}, FOE: {"x": 18, "y": 0}, SECOND: {"x": 19, "y": 1}} if outside_caster else {
        OWNER: {"x": 3, "y": 0}, FOE: {"x": 4, "y": 0}, SECOND: {"x": 7, "y": 0}}
    destination = "cell:19,1" if outside_caster else "cell:8,0"
    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_LIGHTNING_CHAIN_BOLT"], positions=positions,
        second_talents=["TAL_FENCING_FOOTWORK"])
    cid = candidate(table, mid, "Chain Bolt", FOE)
    before, prompts = resolve(combat, mid, send, cid, {
        "choice:needle.arc": SECOND, "choice:needle.footwork": destination})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.footwork" for p in prompts)
    engine = reload(tmp_path, mid)
    subject = engine.state.actors[SECOND]
    assert subject.position.model_dump(mode="json") == ({"x": 19, "y": 1} if outside_caster else {"x": 8, "y": 0})
    assert (subject.current_hp < before["actors"][SECOND]["current_hp"]) == outside_caster
    assert te.bears_mark(subject, OWNER, "Charged") == outside_caster
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == SECOND for e in engine.events) == outside_caster


@pytest.mark.parametrize("charged", [False, True])
@pytest.mark.parametrize("rider", ["Charge", "Jolt", "Flash", "Arc"])
def test_chains_needs_charge_before_hit_across_lash_riders_table(tmp_path, charged, rider):
    combat, table, mid, send, commit = fixture(tmp_path, ["TAL_LIGHTNING_LIGHTNING_CHAINS"], bundle_transform=charge_setup)
    if charged:
        commit_charge(table, mid, send, FOE)
    cid = candidate(table, mid, f"Lightning Lash: {rider} + Lightning Chains", FOE)
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.arc": SECOND})
    engine = reload(tmp_path, mid)
    assert bool(links(engine, FOE)) == charged
    assert bool(links(engine, SECOND)) == charged
    assert any(p["context"]["reaction_source_id"] == "choice:needle.arc" for p in prompts) == charged
    assert te.bears_mark(engine.state.actors[FOE], OWNER, "Charged") == (charged or rider == "Charge")


@pytest.mark.parametrize("ability", ["lash", "primer", "bolt", "chains"])
@pytest.mark.parametrize("ai_owner", [False, True])
def test_arc_allied_recipients_manual_menu_and_ai_hostile_preference(tmp_path, ability, ai_owner):
    talent, label = {
        "lash": ("TAL_LIGHTNING_LIGHTNING_LASH", "Lightning Lash: Arc"),
        "primer": ("TAL_LIGHTNING_ARC_PRIMER", "Lightning Lash: Arc"),
        "bolt": ("TAL_LIGHTNING_CHAIN_BOLT", "Chain Bolt"),
        "chains": ("TAL_LIGHTNING_LIGHTNING_CHAINS", "Lightning Lash: Jolt + Lightning Chains"),
    }[ability]
    talents = [talent, "TAL_LIGHTNING_CONDUCTIVE_FIELD"] if ability in ("lash", "primer") else [talent]
    combat, table, mid, send, commit = fixture(tmp_path, talents, allies=[SECOND], extra_foe=True, bundle_transform=charge_setup,
        positions={OWNER: {"x": 2, "y": 0}, FOE: {"x": 4, "y": 0},
                   SECOND: {"x": 5, "y": 0}, THIRD: {"x": 4, "y": 1}})
    if ability in ("lash", "primer"):
        # A real field makes the allied creature Conductive without relying on
        # Gather Charge, which accepts willing creatures (riders/c13).
        cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
                   if "Conductive Field" in g["label"] for o in g["options"]
                   if o.get("destination") == {"x": 4, "y": 0})
        commit(cid)
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            commit(table.state(mid)["menu"]["end_turn"])
    if ability == "chains":
        commit_charge(table, mid, send, FOE)
    cid = candidate(table, mid, label, FOE)
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
    before, prompts = resolve(combat, mid, send, cid, {"choice:needle.arc": SECOND}, auto=ai_owner)
    if not ai_owner:
        p = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.arc")
        assert {SECOND, THIRD} <= {o["id"] for o in p["choice"]["options"]}
        assert p["choice"]["preferred"] == [THIRD]
    engine = reload(tmp_path, mid)
    for who in (SECOND, THIRD):
        assert (engine.state.actors[who].current_hp < before["actors"][who]["current_hp"]) == (who == (THIRD if ai_owner else SECOND))
    if ability == "chains":
        assert links(engine, FOE)[0].data["with"] == (THIRD if ai_owner else SECOND)
    if ability == "primer":
        assert te.bears_mark(engine.state.actors[THIRD if ai_owner else SECOND], OWNER, "Charged")
