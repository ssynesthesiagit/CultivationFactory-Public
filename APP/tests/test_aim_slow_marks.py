"""Synthetic, offline table reproduction of multi-augment area aiming.

Timing is diagnostic only (the sweep may opt into a budget); legality is not
traded away to make aiming faster. No owner fight or live model is used.
"""
import cProfile
import io
import json
import os
import pstats
import time
import warnings

import pytest

from tests.lighting_darkness_support import synthetic_darkness_rules
from tests.lighting_support import ambient_light, fight, light, map_document, OWNER


AUGMENTS = ["TAL_DARK_CLINGING_DARKNESS", "TAL_DARK_ETERNAL_DARKNESS", "TAL_DARK_GREATER_DARKNESS"]


@pytest.mark.parametrize("count", range(4))
def test_multi_augment_area_aiming(tmp_path, monkeypatch, count):
    from combat import factory_compiler
    from combat.ext.setting_choices import composition_spec
    from combat.settings_service import match_batch
    from combat import loadout

    monkeypatch.setenv("CF_EMBED_MENU", "0")
    with synthetic_darkness_rules(tmp_path, monkeypatch):
        # Public CI redacts reference headings. Supply the same printed
        # classification, not a private fixture or an alternate implementation.
        monkeypatch.setattr(factory_compiler, "_RULES_TEXT_CACHE", {
            **factory_compiler._rules_text(),
            **{key: "### " + name + " - Augment\n" + text for key, name, text in [
                (AUGMENTS[0], "Clinging Darkness", "Center Darkness on a creature or object."),
                (AUGMENTS[1], "Eternal Darkness", "Your Darkness becomes permanent until dispelled."),
                (AUGMENTS[2], "Greater Darkness", "Increase the radius of your Darkness to 30 feet."),
            ]},
        })
        combat, table, mid = fight(tmp_path, map_document(
            width=32, height=24, ambient=ambient_light("day"),
            lights=[light(12, 8)]), talents=AUGMENTS, seed="AIMSLOW1")
    engine = combat._load_session(mid).engine
    base, family = next((base, row) for base, row in loadout.families(engine)[OWNER]
                        if engine.action_catalog[base].display_name == "Darkness")
    settings = [a.source_definition_id for a in engine.action_catalog.values()
                if a.owner_id == OWNER and composition_spec(a)
                and a.parameters.get("augment_toggle") == base
                and a.parameters.get("augment_key") in AUGMENTS[:count]]
    # A clear selection makes the zero-augment case explicit as well.
    clear = next(a.source_definition_id for a in engine.action_catalog.values()
                 if a.owner_id == OWNER and a.parameters.get("augment_toggle") == base
                 and a.parameters.get("augment_key") is None)
    match_batch(table, mid, OWNER, [clear, *settings], "aim-settings")
    engine = combat._load_session(mid).engine
    source = loadout.active_action(base, family, loadout.chosen(engine.state.actors[OWNER], base))
    decision = f"decision:{engine.state.state_version}:{OWNER}:{engine.state.event_sequence}"
    profile = cProfile.Profile()
    t0 = time.perf_counter()
    profile.enable()
    result = table.expand_action(mid, source, decision, engine.state.state_version)
    profile.disable()
    options_time = time.perf_counter() - t0
    options = [o for group in result["actions"] for o in group["options"]]
    assert options
    area_options = [o for o in options if o.get("area")]
    assert area_options
    selected = area_options[len(area_options) // 2]
    t0 = time.perf_counter()
    prepared = table.act(mid, selected["candidate_id"], decision, engine.state.state_version,
                         0, [], prepare_only=True)
    prepare_time = time.perf_counter() - t0
    assert prepared["status"] in {"PREPARED", "REACTION_REQUIRED", "READY"}, prepared
    stream = io.StringIO()
    pstats.Stats(profile, stream=stream).sort_stats("cumtime").print_stats(18)
    warnings.warn(f"AIMSLOW1 augments={count} options={len(options)} "
                  f"options_s={options_time:.4f} prepare_s={prepare_time:.4f}\n{stream.getvalue()}")
    if os.environ.get("AIMSLOW_TIMING") == "1":
        assert options_time < 2 and prepare_time < 2
