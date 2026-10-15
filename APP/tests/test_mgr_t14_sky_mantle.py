"""Sky Mantle's extra CP choice uses the balance after the base action cost.

These tests acquire Weather through a real sheet, compile its automatic base
grants, and commit choices through TabletopService with cold reload and replay.
Sign acquisition and ambient-weather attestation remain separate open producers;
an active-sign answer here exercises the existing human table path only.
"""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.weather_mantle import MANTLE, SIGN_CHOICE
from tests.h1_support import ROOT, sheet
from tests.test_hunt27_table import ME, FOE, action, commit, owner_turn


def arena(tmp_path, cp, *, weather=True):
    # Foundation Weather Field requires CL 5 and the sphere's Gather Weather.
    # A real Weather purchase grants that base ability automatically.
    docs = [sheet(["TAL_WEATHER_FOUNDATION_WEATHER_FIELD"] if weather else [], cl=5), sheet([], cl=5)]
    for aid, doc in zip((ME, FOE), docs):
        doc["identity"]["display_name"] = "Mantle owner" if aid == ME else "Other creature"
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = cp
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
               for aid, doc in zip((ME, FOE), docs)]
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [ME], [FOE], control_modes={ME: "MANUAL", FOE: "MANUAL"},
        match_seed="MGR-T14-sky-mantle-budget", maximum_rounds=4,
        display_name="Sky Mantle budget regression")["match_id"]
    table = TabletopService(combat, tmp_path)
    owner_turn(combat, table, mid, tmp_path, idle=True)
    return combat, table, mid


@pytest.mark.parametrize("refresh", [False, True])
@pytest.mark.parametrize("extra_cp", [0, 1])
def test_force_choice_requires_remaining_cp_after_base_cost(tmp_path, refresh, extra_cp):
    initial = 1 + int(refresh) + extra_cp
    combat, table, mid = arena(tmp_path, initial)
    if refresh:
        commit(combat, table, mid, tmp_path, action(combat, mid, "Sky Mantle"),
               choose=lambda prompt: ["wind:active"])
    before = CombatService(ROOT, tmp_path)._load_session(mid).engine
    held = next((c for c in before.state.actors[ME].conditions.values() if c.condition_id == MANTLE), None)
    original = held.model_dump(mode="json") if held else None
    prompts = []

    def choose(prompt):
        assert prompt["context"]["reaction_source_id"] == SIGN_CHOICE
        prompts.append(prompt)
        options = {option["id"] for option in prompt["choice"]["options"]}
        signs = ("wind", "rain", "cold", "heat", "dry", "thunder")
        assert {f"{sign}:active" for sign in signs} <= options
        assert {f"{sign}:force" for sign in signs} & options == (
            {f"{sign}:force" for sign in signs} if extra_cp else set())
        assert "Mantle" in prompt["moment"] and "Mantle owner" in prompt["moment"]
        return [f"heat:{'force' if extra_cp else 'active'}"]

    name = "Refresh Mantle" if refresh else "Sky Mantle"
    commit(combat, table, mid, tmp_path, action(combat, mid, name), choose=choose)
    assert len(prompts) == 1
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert engine.state.actors[ME].resources["resource:core.qi"] == 0
    mantle = next(c for c in engine.state.actors[ME].conditions.values() if c.condition_id == MANTLE)
    assert mantle.data["sign"] == "heat"
    assert mantle.data["forced"] == extra_cp
    assert engine.state.actors[ME].concentration is not None
    if original:
        assert mantle.instance_id == original["instance_id"]
        assert mantle.data["expiry_round"] == original["data"]["expiry_round"]
        assert mantle.data["expiry_slot"] == original["data"]["expiry_slot"]


def test_sky_mantle_options_require_weather_acquisition(tmp_path):
    combat, table, mid = arena(tmp_path, 3, weather=False)
    engine = CombatService(ROOT, tmp_path)._load_session(mid).engine
    assert not any(a.display_name in {"Sky Mantle", "Refresh Mantle"}
                   for a in engine.action_catalog.values())
