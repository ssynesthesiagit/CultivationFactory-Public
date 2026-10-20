"""Native Pole delivery controls and an intentionally failing legal-subject handoff.

No effects, ownership rows or movement receipts are injected. Characters acquire
the exact source feature in their portable sheet; all writes use table intents.
"""
import json
import zipfile

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import cast_sender, commit
from tests.test_hidden_targeting import turn
from tests.test_lock9_passage_review import checked

FEATURE = "tianxia.tradition.spirit.compass_breaking_hand.feature.three_bearing_footwork"
MIND = "tianxia.path.spirit_awakening.feature.mind_spike"
OWNER = "actor:factory.aaaaaaaa"
ALLY = "actor:factory.bbbbbbbb"
FOE = "actor:factory.ffffffff"
POLE = "condition:typed.compass_pole"


def native_table(tmp_path, *, owned=True):
    for pid in ("aaaaaaaa", "bbbbbbbb", "ffffffff"):
        ids = [MIND, *([FEATURE] if owned and pid == "aaaaaaaa" else [])]
        document = sheet(ids, cl=3, primary="Resonance", key="WIS", name=pid)
        document["identity"]["path"] = "Spirit Awakening"
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({
        "display_name": "Bearing verification hall", "width_squares": 12,
        "height_squares": 14, "walls": [],
        "starts": {"team1": [[1, 6], [2, 6]], "team2": [[6, 6]]},
    })
    mid = service.create_factory_match(
        project_ids=["aaaaaaaa", "bbbbbbbb"], opponent_actor_ids=[FOE],
        control_modes={actor: "MANUAL" for actor in (OWNER, ALLY, FOE)},
        arena_id="battlefield:map.bearing-verification-hall",
        match_seed="MGR-T14-BEARING-FOOTWORK",
    )["match_id"]
    ui = TabletopService(service, tmp_path)
    turn(ui, mid, OWNER)
    return service, ui, mid


@pytest.mark.parametrize("owned", [True, False])
def test_native_pole_acquisition_commit_cold_reload_and_replay(tmp_path, owned):
    service, ui, mid = native_table(tmp_path, owned=owned)
    engine = service._load_session(mid).engine
    rows = [row for row in engine.typed_passive_rows.get(OWNER, ())
            if row.get("kind") == "three_bearing_footwork"]
    assert [row["feature_id"] for row in rows] == ([FEATURE] if owned else [])
    candidates = [c for c in engine.legal_candidates() if c.display_name == "Choose Pole"]
    if not owned:
        assert not candidates
        assert not any(c.condition_id == POLE for c in checked(tmp_path, mid).state.actors[OWNER].conditions.values())
        return
    assert any(c.target_ids == (FOE,) for c in candidates)
    actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    resonance, hp, position = actor.resources["resource:core.resonance"], target.current_hp, target.position
    target_conditions = target.conditions.copy()
    commit(cast_sender(service, ui, mid, "Choose Pole", target=FOE))
    engine = checked(tmp_path, mid)
    actor, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    poles = [c for c in actor.conditions.values() if c.condition_id == POLE]
    assert len(poles) == 1 and poles[0].data["pole"] == FOE
    assert poles[0].source_actor_id == OWNER
    assert actor.resources["resource:core.resonance"] == resonance - 1
    assert not actor.bonus_action_available
    assert target.current_hp == hp and target.position == position
    assert target.conditions == target_conditions


@pytest.mark.xfail(strict=True, reason="Known source gap: Pole acquisition currently excludes perceived allies")
def test_native_perceived_ally_is_a_legal_pole(tmp_path):
    """Printed Pole permits a companion; hostile benefits must be gated separately."""
    service, ui, mid = native_table(tmp_path)
    engine = service._load_session(mid).engine
    assert engine.state.actors[OWNER].team_id == engine.state.actors[ALLY].team_id
    assert any(c.display_name == "Choose Pole" and c.target_ids == (ALLY,)
               for c in engine.legal_candidates()), "Pole must allow a perceived ally, not only hostiles"
    commit(cast_sender(service, ui, mid, "Choose Pole", target=ALLY))
    actor = checked(tmp_path, mid).state.actors[OWNER]
    assert any(c.condition_id == POLE and c.data.get("pole") == ALLY for c in actor.conditions.values())
