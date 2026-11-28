"""A CL1 fighter can commit one concentrated prefight buff and replace it in battle."""
import copy
import json
import zipfile

import pytest

from combat import concentration
from combat.gate5_service import CombatService, CombatServiceError, FACTORY_ACTOR_PREFIX
from combat.gate2_runtime_content import AN
from combat.tabletop_service import TabletopService
from tests.test_prefight import ROOT, SHEET


def test_cl1_prefight_concentration_limit_and_in_combat_replacement(tmp_path):
    sheet = copy.deepcopy(SHEET)
    sheet["identity"]["cultivation_level"] = 1
    folder = tmp_path / "portable_characters" / "left"
    folder.mkdir(parents=True)
    with zipfile.ZipFile(folder / "current.zip", "w") as archive:
        archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(sheet))
    combat = CombatService(ROOT, tmp_path)
    options = combat.factory_prefight_options("left")
    # The Bible gives Mortal fighters one Concentration slot, not one total buff pick.
    assert options["max_concentration"] == 1 and options["max"] == 2
    darkvision, clearsight = (next(o["action_id"] for o in options["options"] if o["name"] == name)
                             for name in ("Meld: Darkvision", "Meld: Clearsight"))
    owner = FACTORY_ACTOR_PREFIX + "left"
    setup = dict(project_ids=["left"], opponent_actor_ids=[AN],
                 control_modes={owner: "MANUAL", AN: "MANUAL"}, match_seed="R13-PREFIGHT")
    with pytest.raises(CombatServiceError, match="At most one of them may use Concentration"):
        combat.create_factory_match(**setup, prefight={owner: [darkvision, clearsight]})
    mid = combat.create_factory_match(**setup, prefight={owner: [darkvision]})["match_id"]
    table = TabletopService(combat, tmp_path)

    def take(candidate_id):
        state = table.state(mid)
        menu = state["menu"]
        result = table.act(mid, candidate_id, menu["decision_id"], menu["state_version"], state["last_sequence"])
        assert result["status"] == "COMMITTED", result

    menu = table.state(mid)["menu"]
    if menu["actor_id"] != owner:
        take(menu["end_turn"])
    before = CombatService(ROOT, tmp_path)._load_session(mid)
    assert concentration.sources(before.engine.state.actors[owner]) == [darkvision]

    # At the limit, a new cast in battle ends the oldest (the prefight Meld).
    candidate = next(c for c in before.engine.legal_candidates()
                     if c.source_definition_id == clearsight and owner in c.target_ids)
    take(candidate.candidate_id)
    after = CombatService(ROOT, tmp_path)._load_session(mid)
    assert concentration.sources(after.engine.state.actors[owner]) == [clearsight]
    assert any(e.event_type == "CONCENTRATION_ENDED" and e.actor_id == owner
               and e.source_definition_id == darkvision and e.payload["reason"] == "REPLACED"
               for e in after.engine.events)
    assert after.mechanical.replay()["status"] == "PASS"
