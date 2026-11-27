"""On 2026-11-14 every legal candidate ran all 417 candidate_allowed hooks:
8.8 million calls in 16 AI steps, about 30% of AI time; 387 never answered.
Hooks now declare the fight fact they check first. A wrong declaration would
silently drop a rule, so compare dropped providers with their actual replies.
Only shipped characters and compiled built-in catalog rows are used.
"""
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from time import perf_counter

import pytest

from combat import ext
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import ACTORS, AN, BAI, LEE, LING
from combat.gate2_runtime_models import ActionDefinition, CandidateKind, LegalCandidate
from combat.gate4_engine import Gate4ControllerEngine
from combat.read_queries import candidate_pass
from combat.typed_numbers import authority_mechanics

ROOT = Path(__file__).resolve().parents[1]
POINT = "candidate_allowed"
RECORDS = ("TAL_SHADOW_SHADOW_STEP", "TAL_ATHLETICS_FLASH_STEP",
           "BRUTE_BASE_BRUTAL_SHOVE")
DECLARED = {
    "combat.ext.shadow.shadow_step_spaces",
    "combat.ext.athletics.flash_step_needs_focus",
    "combat.ext.brute_shove.too_large",
}


def _sheet(left, records=(), spheres=("tianxia.sphere.shadow", "tianxia.sphere.athletics",
                                      "tianxia.sphere.brute")):
    template = ACTORS[left]
    sheet = {
        "identity": {"name": template.display_name, "cultivation_level": 5,
                     "proficiency_bonus": template.proficiency_bonus,
                     "path": "Qi Cultivation", "key_ability": "CON"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": name, "score": 14, "modifier": 2}
                          for name in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": "Qi", "maximum": 30},
            "armor_class": {"base_value": template.armor_class},
            "hit_points": {"maximum": template.maximum_hp},
            "speed": {"walking_ft": template.speed_ft},
            "technique_save_dc": 14, "technique_attack_bonus": 6},
        "spheres_and_talents": {
            "sphere_record_ids": list(spheres),
            "learned_talent_record_ids": list(records),
            "automatic_sphere_component_record_ids": []},
    }
    return sheet


def _fight(left, right, records=()):
    engine = Gate4ControllerEngine(
        ROOT, match_seed=f"hook-presence:{left}:{right}",
        roster_setup={"primary_actor_ids": [left, right],
                      "team_by_actor": {left: "team:left", right: "team:right"}})
    if records:
        # Give a shipped fighter real compiled catalog abilities, without a
        # private character sheet, proposal store or synthetic mechanic.
        bundle = compile_character(_sheet(left, records), actor_id=left)
        added = []
        for row in bundle["action_catalog"]:
            action = ActionDefinition.model_validate(row)
            assert action.source_definition_id not in engine.action_catalog
            engine.action_catalog[action.source_definition_id] = action
            added.append(action.source_definition_id)
        actor = engine.state.actors[left]
        actor.action_ids = (*actor.action_ids, *added)
        engine.typed_actor_ids.add(left)
        engine.typed_passive_rows[left] = bundle.get("typed_passives") or []
        engine.typed_reaction_rows[left] = bundle.get("typed_reactions") or []
    return engine


@pytest.mark.parametrize("pair", list(combinations((AN, LEE, LING, BAI), 2)))
def test_dropped_hooks_are_neutral_and_present_rules_are_kept(pair):
    engine = _fight(*pair, records=RECORDS if pair[0] == AN else ())
    candidates = engine.legal_candidates()
    assert candidates
    ext._load()
    hooks = tuple(ext._HOOKS[POINT])
    with candidate_pass(engine):
        selected = tuple(ext._selected(POINT, (engine,)))
        dropped = set(hooks) - set(selected)
        assert len(dropped) >= 200  # three old opt-ins alone do not fix fan-out
        if pair[0] == AN:
            kept = {f"{fn.__module__}.{fn.__name__}" for fn in selected
                    if (POINT, fn) in ext._HOOK_PRESENT}
            assert DECLARED <= kept
        for candidate in candidates:
            actor = engine.state.actors[candidate.actor_id]
            action = engine.action_catalog.get(candidate.source_definition_id)
            for function in dropped:
                assert function(engine, actor, candidate, action) is None, (
                    function.__module__, function.__name__, candidate)
            if pair == (AN, LEE):
                # No engine switch/monkeypatch: directly run EVERY subscriber,
                # without short-circuiting, including those ordinarily dropped.
                replies = [fn(engine, actor, candidate, action) for fn in hooks]
                assert ext.any_false(POINT, engine, actor, candidate, action) == any(
                    result is False for result in replies)


def test_presence_index_is_revision_scoped_not_saved_or_per_candidate():
    engine = _fight(AN, LEE, RECORDS)
    original_state = engine.state.model_dump(mode="json")
    original_catalog = engine.action_catalog
    with candidate_pass(engine):
        first = ext.fight_presence(engine)
        assert ext.fight_presence(engine) is first
        assert set(RECORDS) <= first["features"]
        # A recorded revision must see changed catalog input, even if its
        # dictionary identity is unchanged.
        removed = {key: action for key, action in original_catalog.items()
                   if (action.parameters or {}).get("typed")}
        for key in removed:
            del original_catalog[key]
        engine.state.event_sequence += 1
        second = ext.fight_presence(engine)
        assert second is not first
        assert not set(RECORDS) & second["features"]
        original_catalog.update(removed)
        engine.action_catalog = dict(original_catalog)
        third = ext.fight_presence(engine)
        assert third is not second
        assert set(RECORDS) <= third["features"]
    engine.state.event_sequence -= 1
    with candidate_pass(engine):
        assert ext.fight_presence(engine) is not third
    assert engine.state.model_dump(mode="json") == original_state


def test_catalog_actions_alone_leave_dropped_hooks_neutral(capsys):
    """Prove absence per compiled action, not just per built-in loadout.

    Compile every shipped record in its content family so compiler plug-ins,
    options and modifiers participate. Then remove its siblings: a different
    action's token must never conceal an incomplete declaration.
    """
    started = perf_counter()
    engine = _fight(AN, LEE)
    ext._load()
    declared = [(fn, ext._HOOK_PRESENT[POINT, fn])
                for fn in ext._HOOKS[POINT] if (POINT, fn) in ext._HOOK_PRESENT]
    families = defaultdict(list)
    mechanics = authority_mechanics()
    for source, record in mechanics.items():
        family = (record.get("sphere_id") or record.get("path_id")
                  or source.rsplit(".feature.", 1)[0].rsplit(".", 1)[0])
        families[family].append(source)
    actor = engine.state.actors[AN]
    failures = []
    checked = calls = 0
    for sources in families.values():
        spheres = sorted({mechanics[source]["sphere_id"] for source in sources
                          if mechanics[source].get("sphere_id")})
        sheet = _sheet(AN, sources, spheres)
        sheet["identity"].update(cultivation_level=20, proficiency_bonus=6)
        bundle = compile_character(sheet, actor_id=AN)
        for row in bundle["action_catalog"]:
            action = ActionDefinition.model_validate(row)
            # Plain built-in fight; only the action under proof contributes
            # catalog tokens. Do not install the family's passive/condition rows.
            engine.action_catalog = {action.source_definition_id: action}
            actor.action_ids = (action.source_definition_id,)
            candidate = LegalCandidate(
                candidate_id="presence-proof", decision_id="presence-proof",
                state_version=engine.state.state_version, kind=CandidateKind.ACTION,
                actor_id=AN, source_definition_id=action.source_definition_id,
                display_name=action.display_name, target_ids=(LEE,),
                destination=engine.state.actors[LEE].position)
            tokens = ext.action_presence([action])
            with candidate_pass(engine):
                assert ext.fight_presence(engine) == tokens
                for function, predicate in declared:
                    if predicate(engine) is False:
                        reply = function(engine, actor, candidate, action)
                        calls += 1
                        if reply is not None:
                            failures.append((function.__module__, function.__name__,
                                             action.source_definition_id, action.display_name,
                                             reply))
            checked += 1
            elapsed = perf_counter() - started
            assert elapsed <= 120, f"catalog sweep too slow {elapsed:.2f} seconds"
    with capsys.disabled():
        print(f"hook-presence catalog sweep: {checked} actions, {calls} dropped-hook "
              f"calls in {perf_counter() - started:.2f}s")
    assert checked and calls
    assert not failures, failures
