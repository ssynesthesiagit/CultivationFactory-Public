"""Opt-in sweep of every setting produced by the read-only hunt roster.

Character archives are never checked into the repository. Settings are played
through manual table calls, committed, reloaded and their persisted pills read.
"""
import json
import os
from pathlib import Path
import shutil
import zipfile

import pytest
from combat.factory_compiler import compile_character
from combat.ext.setting_choices import is_setting_action
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt15_support import ROOT, act
from tests.h1_support import sheet
from tests.test_carry import KIT


def test_every_roster_setting_status_has_rule_text_after_reload(tmp_path):
    inputs = os.environ.get("HUNT15_CHARACTER_INPUTS")
    if not inputs:
        pytest.skip("opt in with HUNT15_CHARACTER_INPUTS; no private fixtures in repository")
    count = unavailable = catalogue = 0
    conditions = set()
    covered = set()
    for index, archive in enumerate(sorted(Path(inputs).glob("*/current.zip"))):
        with zipfile.ZipFile(archive) as z:
            document = json.loads(z.read("Tianxia_Owner_Character_Sheet_v1.json"))
        aid = "actor:factory." + archive.parent.name
        bundle = compile_character(document, actor_id=aid)
        settings = [a for a in bundle["action_catalog"] if is_setting_action(a)]
        catalogue += len(settings)
        # Variants share their status writer. Sweep each distinct writer through
        # a real table rather than replay every on/off/talent permutation.
        def writer(a):
            return tuple(e.get("type") for e in a["parameters"]["typed"]["effects"])
        settings = [a for a in settings if writer(a) not in covered]
        if not settings:
            continue
        user = tmp_path / str(index)
        dest = user / "portable_characters" / archive.parent.name
        dest.mkdir(parents=True)
        shutil.copy2(archive, dest / "current.zip")
        foe = "actor:factory.h15-neutral"
        combat = CombatService(ROOT, user)
        mid = combat._finish_factory_match([bundle, compile_character(sheet([], kit={"starting_kit": KIT}), actor_id=foe)],
            [aid, foe], {aid: "team:factory", foe: "team:opponents"},
            {aid: {"x": 3, "y": 6}, foe: {"x": 6, "y": 6}},
            combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [aid], [foe],
            control_modes={aid: "MANUAL", foe: "MANUAL"}, match_seed=f"H15-SETTINGS-{index}",
            display_name="Settings sweep", maximum_rounds=10)["match_id"]
        table = TabletopService(combat, user)
        from tests.hunt15_support import turn
        turn(table, mid, aid)
        for setting in settings:
            if writer(setting) in covered:
                continue
            # Already-selected or prerequisite-gated choices are intentionally
            # absent from the live menu; do not forge a candidate for them.
            menu = table.state(mid)["menu"]
            if not any(g["source_definition_id"] == setting["source_definition_id"] for g in menu["actions"]):
                unavailable += 1
                continue
            assert act(table, mid, setting["display_name"])["status"] == "COMMITTED"
            count += 1
            loaded = CombatService(ROOT, user)._load_session(mid)
            assert loaded.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
            shown = TabletopService(CombatService(ROOT, user), user).state(mid)
            for actor in shown["presentation"]["actors"]:
                for row in actor["conditions"]:
                    source = loaded.engine.action_catalog.get(row.get("source_definition_id"))
                    if source and is_setting_action(source):
                        conditions.add(row["condition_id"])
                        if source.source_definition_id == setting["source_definition_id"]:
                            covered.add(writer(setting))
                        assert row["rule_text"], (setting["display_name"], row["condition_id"])
                        assert "Rule description unavailable" not in row["detail"]
        assert loaded.mechanical.replay()["status"] == "PASS"
    assert catalogue > 500 and count > 20 and len(conditions) > 15
    print(f"settings sweep: {catalogue} catalogue choices; {count} committed selections; {len(conditions)} distinct persisted setting conditions; {len(covered)} writers; {unavailable} unavailable choices")
