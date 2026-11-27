"""Saved Fate round limits and exact Temporary HP provenance."""
import pytest

from combat.ext import fate_riders as F
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_r9i_fate_persistence import fixture, PLAYER, ALLY, FOE, attack_id, pass_twist
from tests.test_r9i_karma_persistence import act, end_turn


def test_undo_table_preview_commit_reload(tmp_path, monkeypatch):
    from tests.sol109_support import accurate_attacks
    accurate_attacks(monkeypatch, FOE)
    combat, table, mid = fixture(tmp_path, F.UNDO)
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        end_turn(table, mid)
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Undo Harm Edict" for o in g["options"])
    assert act(table, mid, cid)["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != FOE:
        end_turn(table, mid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    cid = attack_id(table, mid)
    first = act(table, mid, cid)
    assert first["status"] == "REACTION_REQUIRED"
    assert act(table, mid, cid)["reaction"] == first["reaction"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert pass_twist(lambda answers: act(table, mid, cid, answers))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    engine = loaded.engine
    assert loaded.mechanical.replay()["status"] == "PASS"
    ally = engine.state.actors[ALLY]
    assert ally.temporary_hp > 0
    held = F._held(ally, F.C + "undo_hp")
    assert len(held) == 1
    zone = engine.state.zones[held[0].data["zone"]]
    for e in (engine, CombatService._clone_engine(ROOT, engine)):
        assert not F._once_a_round(e, ("undo", zone.zone_id, ALLY))
        e.state.zones[zone.zone_id].active = False
        F._undo_vanish(e)
        assert e.state.actors[ALLY].temporary_hp == 0
        assert not F._held(e.state.actors[ALLY], F.C + "undo_hp")
    # Independently exercise aura exit through an actual table movement commit.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    while table.state(mid)["menu"]["actor_id"] != ALLY:
        end_turn(table, mid)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    zone = engine.state.zones[F._held(ally, F.C + "undo_hp")[0].data["zone"]]
    move = next(c for c in engine.legal_candidates() if str(c.kind) == "MOVE" and c.destination
                and not F._inside(engine, ally.model_copy(update={"position": c.destination}), zone))
    # The round19 path can provoke an opportunity attack while leaving the
    # aura. Decline the player's ordinary Twist of Fate prompt as above; the
    # preview must still leave the saved aura and Temporary HP untouched.
    before_move = engine.state.model_dump(mode="json")
    preview = act(table, mid, move.candidate_id)
    assert preview["status"] == "REACTION_REQUIRED"
    assert preview["reaction"]["context"]["reaction_source_id"] == "reaction:typed.TAL_FATE_TWIST_OF_FATE"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before_move
    assert pass_twist(lambda answers: act(table, mid, move.candidate_id, answers))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ALLY].temporary_hp == 0
    assert not F._held(loaded.engine.state.actors[ALLY], F.C + "undo_hp")
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("kind", ["court", "serendipity", "consequence", "purity", "chain", "jinx"])
def test_all_round_marks_survive_clone_and_state_reconstruction(kind):
    from tests.test_riders_lane9 import _fate_fight

    e = _fate_fight([])
    key = (kind, "instance:a", "creature:a")
    assert F._once_a_round(e, key)
    clone = CombatService._clone_engine(ROOT, e)
    assert not F._once_a_round(clone, key)
    assert F._once_a_round(clone, (kind, "instance:b", "creature:a"))
    clone.state.round_number += 1
    assert F._once_a_round(clone, key)
    # A newly inserted summon that sorts first cannot reopen a paid use.
    new = next(iter(clone.state.actors.values())).model_copy(deep=True)
    new.entity_id = "actor:000-new-summon"
    new.turn_flags = {}
    clone.state.actors[new.entity_id] = new
    assert not F._once_a_round(clone, key)


def test_undo_does_not_claim_existing_or_replacement_temp_hp():
    from tests.test_riders_lane9 import _fate_fight, _act, ME, ALLY as A

    e = _fate_fight(["UNDO_HARM_EDICT"])
    _act(e, "Undo Harm Edict")
    ally = e.state.actors[A]
    e._grant_temp_hp(ally, 50, "other", ME)
    F.undo_harm(e, ally, 1, "attack", ME)
    assert not F._held(ally, F.C + "undo_hp")
    e.state.round_number += 1
    ally.temporary_hp = 0
    F.undo_harm(e, ally, 1, "attack", ME)
    assert F._held(ally, F.C + "undo_hp")
    e._grant_temp_hp(ally, 100, "other", ME)
    assert not F._held(ally, F.C + "undo_hp")
    for z in e.state.zones.values():
        z.active = False
    F._undo_vanish(e)
    assert ally.temporary_hp == 100
