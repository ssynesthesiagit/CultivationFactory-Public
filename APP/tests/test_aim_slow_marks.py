"""Synthetic, offline table reproduction of multi-augment area aiming.

Timing is diagnostic only (the sweep may opt into a budget); legality is not
traded away to make aiming faster. No owner fight or live model is used.
"""
import cProfile
import io
import os
import pstats
import time
import warnings

import pytest

from tests.lighting_darkness_support import synthetic_darkness_rules
from tests.lighting_support import ambient_light, fight, light, map_document, OWNER


AUGMENTS = ["TAL_DARK_CLINGING_DARKNESS", "TAL_DARK_ETERNAL_DARKNESS", "TAL_DARK_GREATER_DARKNESS"]


def test_projected_pass_isolation_revision_and_exception_cleanup():
    from types import SimpleNamespace
    from combat import read_queries as q

    def engine():
        return SimpleNamespace(state=SimpleNamespace(state_version=1, event_sequence=1),
                               action_catalog={})
    real, view, other = engine(), engine(), engine()
    with q.candidate_pass(real):
        original = q.invariant_memo(real, "same-key", object)
        with q.projected_pass(real, view):
            first = q.invariant_memo(view, "same-key", object)
            assert first is not original
        with q.projected_pass(real, other):
            assert q.invariant_memo(other, "same-key", object) is not first
        with q.projected_pass(real, view):
            assert q.invariant_memo(view, "same-key", object) is first
            view.state.event_sequence += 1
            assert q.invariant_memo(view, "same-key", object) is not first
        with pytest.raises(RuntimeError, match="preview failed"):
            with q.projected_pass(real, view):
                raise RuntimeError("preview failed")
        assert q.invariant_memo(real, "same-key", object) is original
        assert q.enumeration_cache(view) is None
    with q.candidate_pass(real), q.projected_pass(real, view):
        assert q.invariant_memo(view, "same-key", object) is not first
    assert q.enumeration_cache(real) is q.enumeration_cache(view) is None


@pytest.mark.parametrize("chosen,legacy", [
    ((), False), ((0,), False), ((1,), False), ((2,), False),
    ((1, 2), False), ((0, 1), False), ((0, 1, 2), False),
    ((), True), ((2,), True),
])
def test_multi_augment_area_aiming(tmp_path, monkeypatch, chosen, legacy):
    from combat import factory_compiler
    from combat.ext.setting_choices import COMPOSITION_KIND, composition_spec
    from combat.settings_service import match_batch
    from combat import area_projection, loadout

    monkeypatch.setenv("CF_EMBED_MENU", "0")
    with synthetic_darkness_rules(tmp_path, monkeypatch):
        with monkeypatch.context() as patch:
            # Public CI redacts reference headings. Supply the same printed
            # classification, not a private fixture or an alternate implementation.
            patch.setattr(factory_compiler, "_RULES_TEXT_CACHE", {
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
            # Build and apply the chosen augment loadout before the synthetic rules
            # context closes, so every parameterized case really selects its rows.
            engine = combat._load_session(mid).engine
            base, family = next((base, row) for base, row in loadout.families(engine)[OWNER]
                                if engine.action_catalog[base].display_name == "Darkness")
            settings = [a.source_definition_id for a in engine.action_catalog.values()
                        if a.owner_id == OWNER and composition_spec(a)
                        and a.parameters.get("augment_toggle") == base
                        and a.parameters.get("augment_key") in [AUGMENTS[i] for i in chosen]]
            assert len(settings) == len(chosen), (chosen, settings)
            # A clear selection makes the zero-augment case explicit as well.
            clear = next(a.source_definition_id for a in engine.action_catalog.values()
                         if a.owner_id == OWNER and a.parameters.get("augment_toggle") == base
                         and a.parameters.get("augment_key") is None)
            match_batch(table, mid, OWNER, [clear, *settings], "aim-settings", kind=COMPOSITION_KIND)
    session = combat._load_session(mid)
    engine = session.engine
    if legacy:
        from combat import area_knowledge
        for event in engine.events:
            if event.event_type == "MATCH_CREATED":
                event.payload.pop(area_knowledge.STAMP, None)
        assert not area_knowledge.enabled(engine)
    source = loadout.active_action(base, family, loadout.chosen(engine.state.actors[OWNER], base))
    decision = f"decision:{engine.state.state_version}:{OWNER}:{engine.state.event_sequence}"
    validations = []
    original_index = area_projection._current_index
    def counted_index(*args, **kwargs):
        validations.append(args[0])
        return original_index(*args, **kwargs)
    monkeypatch.setattr(area_projection, "_current_index", counted_index)
    profile = cProfile.Profile()
    t0 = time.perf_counter()
    profile.enable()
    with monkeypatch.context() as scope:
        if legacy:
            # Exercise the table with the old creation event, not a newly loaded stamped fight.
            scope.setattr(table, "_load_state_session", lambda match_id: session)
        result = table.expand_action(mid, source, decision, engine.state.state_version)
    profile.disable()
    options_time = time.perf_counter() - t0
    options = [o for group in result["actions"] for o in group["options"]]
    assert options
    area_options = [o for o in options if o.get("area")]
    assert area_options
    assert all(o["area"]["center"] == o["destination"] for o in area_options)
    assert all(o["area"]["affected_cells"] for o in area_options)
    # Clinging requires an anchor; other augment combinations may aim at ground.
    if 0 in chosen:
        from combat.gate2_runtime_models import Position
        assert all(any(a.active and engine._footprint_intersects(
            a, (Position(**o["area"]["center"]),)) for a in engine.state.actors.values())
            for o in area_options)
    else:
        active_positions = {(a.position.x, a.position.y) for a in engine.state.actors.values() if a.active}
        assert any((o["area"]["center"]["x"], o["area"]["center"]["y"]) not in active_positions
                   for o in area_options), "area candidates omit every empty centre square"
        if legacy:
            # This legal centre is far from every creature, even with Greater
            # Darkness. A zone remains targetable on empty ground in old fights.
            assert any((o["area"]["center"]["x"], o["area"]["center"]["y"]) == (20, 18)
                       for o in area_options), "legacy menu omitted an unoccupied area"
    # The saved/knowledge grids are unchanged across all those aims. Validate
    # each projection once, not again for every recipient of every square.
    validation_count = len(validations)
    selected = area_options[len(area_options) // 2]
    t0 = time.perf_counter()
    prepared = table.act(mid, selected["candidate_id"], decision, engine.state.state_version,
                         0, [], prepare_only=True)
    prepare_time = time.perf_counter() - t0
    assert prepared["status"] in {"PREPARED", "REACTION_REQUIRED"}, prepared
    stream = io.StringIO()
    pstats.Stats(profile, stream=stream).sort_stats("cumtime").print_stats(18)
    warnings.warn(f"AIMSLOW1 augments={chosen} options={len(options)} "
                  f"options_s={options_time:.4f} prepare_s={prepare_time:.4f} "
                  f"grid_validations={validation_count}\n{stream.getvalue()}")
    assert validation_count <= 4, validation_count
    if os.environ.get("AIMSLOW_TIMING") == "1":
        assert options_time < 2 and prepare_time < 2
