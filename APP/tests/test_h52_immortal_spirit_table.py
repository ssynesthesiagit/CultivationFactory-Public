"""Immortal Spirit Source CL regression through real TabletopService actions."""
from __future__ import annotations

from h52_identity_support import committed_state, fight, roster


def test_immortal_spirit_blocks_real_lower_cl_iron_voice_after_failed_save(tmp_path):
    fighters = roster()
    owner = next(row for row in fighters if row["name"] == "Ye Yi")
    source = next(row for row in fighters if row["name"] == "Lingfeng Ironclad")
    friends = [row for row in fighters if row not in (owner, source) and row["cl"] <= 10]
    assert owner["cl"] == 20 and source["cl"] == 10
    assert any(value.endswith("immortal_spirit") for value in owner["features"])
    characters = [owner, friends[0], source, friends[1]]
    _user, service, table, mid, owner_entity = fight(
        tmp_path, characters, "H52-L43-IMMORTAL-SPIRIT", tuple(row['pid'] for row in characters))
    source_entity = "actor:factory." + source["pid"]
    state = table.state(mid)
    for _step in range(220):
        if state["presentation"].get("terminal"):
            break
        if state["menu"].get("manual"):
            engine = service._load_session(mid).engine
            if engine.state.current_actor_id == owner_entity:
                # This retained sheet starts Astral Projection before combat.
                # Return to its body through the legal table action so Iron
                # Voice tests Immortal Spirit rather than unseen targeting.
                group = next((row for row in state['menu']['actions'] if 'Dismiss Astral Projection' in row['label']), None)
                option = next(iter((group or {}).get('options', [])), None)
            elif engine.state.current_actor_id == source_entity:
                group = next((row for row in state["menu"]["actions"] if "Iron Voice" in row["label"]), None)
                option = next((candidate for candidate in (group or {}).get("options", [])
                               if owner_entity in candidate.get("target_ids", [])), None)
            else:
                option = None
            candidate_id = option["candidate_id"] if option else state["menu"]["end_turn"]
            response = table.act(mid, candidate_id, state["menu"]["decision_id"],
                                 state["menu"]["state_version"], state["last_sequence"], [])
        else:
            response = table.auto_step(mid, state["last_sequence"], [])
        answers = []
        while response["status"] == "REACTION_REQUIRED":
            prompt = response["reaction"]
            answer = {**prompt["context"], "selection": "DECLINE"}
            choice = prompt.get("choice")
            if choice and not choice.get('allow_decline'):
                answer['selection'] = 'USE'
                answer["option_ids"] = ([owner_entity] if prompt['context']['reaction_source_id'] == 'choice:needle.area_recipients'
                                        else [choice["options"][0]["id"]])
            answers.append(answer)
            if state['menu'].get('manual'):
                response = table.act(mid, candidate_id, state['menu']['decision_id'], state['menu']['state_version'], state['last_sequence'], answers)
            else:
                response = table.auto_step(mid, state["last_sequence"], answers)
        assert response["status"] == "COMMITTED", response
        state = response["state"]
        current = service._load_session(mid).engine
        if any(e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith("iron_voice")
               and e.actor_id == owner_entity and (e.payload or {}).get("success") is False for e in current.events):
            break
    final = committed_state(service, mid)
    events = service._load_session(mid).engine.events
    assert any(e.event_type == "SAVE_ROLLED" and e.source_definition_id.endswith("iron_voice")
               and e.actor_id == owner_entity and (e.payload or {}).get("success") is False for e in events), \
        "natural Iron Voice attack did not produce the failed-save regression case"
    assert not any(e.event_type == "CONDITION_APPLIED" and owner_entity in e.target_ids
                   and (e.payload or {}).get("condition_id") == "condition:typed.frightened" for e in events)
    assert owner_entity in final["actors"]


# ------------------------------------------------------------------------------------------- in-repo characters
# Sovereign Identity (rules_text immortal_spirit): "An ordinary effect and any effect with lower Source CL cannot, against
# your will: Charm or Frighten you ... Equal- or higher-authority effects use their printed procedure."
import pytest  # noqa: E402

from h52_identity_support import (CLOSE_STARTS, IMMORTAL_SPIRIT, IRON_VOICE, TEARS, character, commit,  # noqa: E402
                                  option, turn_of)

FRIGHTENED, CHARMED = "condition:typed.frightened", "condition:typed.charmed"


def _applied(events, target, condition_id):
    return [e for e in events if e.event_type == "CONDITION_APPLIED" and target in e.target_ids
            and (e.payload or {}).get("condition_id") == condition_id]


def _failed_saves(events, target, source_suffix):
    return [e for e in events if e.event_type == "SAVE_ROLLED" and e.actor_id == target
            and e.source_definition_id.endswith(source_suffix) and (e.payload or {}).get("success") is False]


@pytest.mark.parametrize(("source_cl", "refused"), [(19, True), (20, False)])
def test_sovereign_identity_compares_each_effects_source_cl_at_the_table(tmp_path, source_cl, refused):
    """CL20 owner vs a CL19 source (one lower: refused) and a CL20 source (equal: its failed save applies normally);
    a CL20 ally without Immortal Spirit takes the same lower-CL effects normally (plug-in inert)."""
    owner = character("52a00001", "Sovereign Owner", [IMMORTAL_SPIRIT], cl=20)
    plain = character("52a00002", "Plain Ally", [], cl=20)
    roarer = character("52a00003", "Roarer", [IRON_VOICE], cl=source_cl, primary="Stamina", dc=40)
    charmer = character("52a00004", "Charmer", [TEARS], cl=source_cl, dc=40)
    rows = [owner, plain, roarer, charmer]
    _user, service, table, mid, owner_id = fight(tmp_path, rows, f"H52-SOVEREIGN-{source_cl}",
                                                 tuple(row["pid"] for row in rows), starts=CLOSE_STARTS)
    plain_id, roarer_id, charmer_id = ("actor:factory." + row["pid"] for row in (plain, roarer, charmer))
    for source_id, label, target in ((roarer_id, "Iron Voice", owner_id), (charmer_id, "Tears Like Pearls", owner_id),
                                     (roarer_id, "Iron Voice", plain_id), (charmer_id, "Tears Like Pearls", plain_id)):
        commit(table, mid, option(turn_of(table, mid, source_id), label, target))
    committed_state(service, mid)
    events = service._load_session(mid).engine.events
    assert len(_failed_saves(events, owner_id, "iron_voice")) == 1
    assert len(_failed_saves(events, owner_id, "tears_like_pearls")) == 1
    assert bool(_applied(events, owner_id, FRIGHTENED)) is not refused
    assert bool(_applied(events, owner_id, CHARMED)) is not refused
    # Inert for a character without the feature, whatever the source's CL.
    assert _failed_saves(events, plain_id, "iron_voice") and _applied(events, plain_id, FRIGHTENED)
    assert _failed_saves(events, plain_id, "tears_like_pearls") and _applied(events, plain_id, CHARMED)
