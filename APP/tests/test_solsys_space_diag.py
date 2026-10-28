"""TEMPORARY diagnostics for SOLSYS-SPACE1F2 (not for commit)."""
import pytest

from tests.test_hunt32_edge import OWNER, FOE, match, reload
from tests.test_solsys_space import candidates, commit

REACH = "tianxia.talent.space.folded_reach"
LINE = "tianxia.talent.space.folded_weapon_line"
DISPLACE = "tianxia.talent.space.spatial_displacement"


@pytest.mark.parametrize("flat", [-100, 100])
def test_diag_setup_candidate(tmp_path, flat):
    combat, table, mid = match(tmp_path, [REACH, LINE], positions={
        OWNER: {"x": 3, "y": 6}, FOE: {"x": 9, "y": 6}}, setup_actions=[{
            "name": "AC", "target": "ANY_CREATURE",
            "effects": [{"type": "ac_bonus", "flat": flat, "applies_to": "target",
                         "expires_on": "UNTIL_REMOVED"}]}])
    engine = combat._load_session(mid).engine
    print("CURRENT", engine.state.current_actor_id, "ROUND", engine.state.round_number)
    for c in engine.legal_candidates():
        print("CAND", c.kind, c.source_definition_id, c.target_ids, c.display_name)


def test_diag_nested_save(tmp_path):
    teleport = {"type": "teleport", "applies_to": "target",
                "choose_subject_destination": True, "distance_ft": 20,
                "destination_must_be_safe": True, "unsafe_on_failure_margin": 100}
    combat, table, mid = match(tmp_path, [DISPLACE], map_terrain=[{
        "terrain": "fire terrain", "cells": [[7, 6]], "pb": 3, "save_dc": 1000}],
        setup_actions=[{"name": "Strong nested save", "target": "ANY_CREATURE",
            "effects": [{"type": "save_bonus", "amount": 1000, "abilities": ["WIS"],
                         "applies_to": "target", "expires_on": "UNTIL_REMOVED"}]},
            {"name": "Nested saves and displacement", "target": "ANY_CREATURE",
            "typed": {"numbers": {"save_dc": 100}},
            "effects": [{"type": "save", "ability": "cha", "on_fail": [
                {"type": "save", "ability": "wis", "dc": "technique_save_dc",
                 "on_fail": [], "on_success": []}, teleport]}]}])
    engine = reload(combat, tmp_path, mid)
    choices = candidates(combat, mid, "test:h32.setup")
    for c in choices:
        print("SETUPCAND", c.source_definition_id, c.target_ids)
    bonus = next(c for c in choices if FOE in c.target_ids and c.source_definition_id.endswith(".0"))
    prompts = commit(table, mid, bonus)
    for p in prompts:
        print("PROMPT", p.get("reaction"), p.get("context"))
    engine = reload(combat, tmp_path, mid)
    for actor_id, actor in engine.state.actors.items():
        for key, cond in actor.conditions.items():
            print("COND", actor_id, key, cond.condition_id, cond.data)
    action = next(c for c in candidates(combat, mid, "test:h32.setup") if FOE in c.target_ids
                  and engine.action_catalog[c.source_definition_id].parameters["typed"]["effects"][0]["type"] == "save")
    prompts = commit(table, mid, action)
    for p in prompts:
        print("PROMPT2", p.get("reaction"), p.get("context"),
              [o["id"] for o in (p.get("choice") or {}).get("options", [])][:5])
    engine = reload(combat, tmp_path, mid)
    for e in engine.events:
        if e.event_type in {"SAVE_ROLLED", "CONDITION_APPLIED", "ATTACK_ROLLED", "DAMAGE_COMMITTED"}:
            print("EV", e.event_type, e.actor_id, e.target_ids, e.payload)
