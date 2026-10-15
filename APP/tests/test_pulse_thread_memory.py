"""Pulse-Thread Memory: native reads, settled attacks, private facts and replay.

No injected seals, damage receipts, passive ownership, or live model clients.
"""
import json
from hashlib import sha256
from pathlib import Path

import pytest

from combat.ext.pulse_thread_memory import FEATURE as PULSE_MEMORY
from combat.ext.mind_hidden_eye import LEARNED, recorded_knowledge_status
from combat.history_feed import concealed_condition_instances
from tests.h1_support import sheet
from tests.worker2_support import OWNER, ALLY, FOE, candidate, fixture, reload, settle, turn

READ = "LIFE_BASE_READ_THE_PULSE"
CHOICE = "choice:needle.pulse_memory"


def fight(tmp_path, *, owned=True, ask=True, ally_life=False):
    return fixture(tmp_path, [READ], owner_insights=[PULSE_MEMORY] if owned else [],
                   ally_talents=[READ] if ally_life else [], ask=ask, named=True,
                   foe_sheet=sheet([], score=20),
                   positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}},
                   seed="PULSE-MEMORY")


def read(combat, table, mid, *, remote=False, accept=True):
    return settle(table, mid, candidate(combat, mid, "Read the Pulse (Pulse Seal)" if remote else "Read the Pulse",
                                      target=ALLY).candidate_id,
                  {CHOICE: "learn" if accept else None})


def facts(engine):
    return [c for c in engine.state.actors[ALLY].conditions.values()
            if c.condition_id == LEARNED and c.source_definition_id == PULSE_MEMORY]


def next_owner(combat, table, mid):
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    turn(table, mid, OWNER)


@pytest.mark.parametrize("owned,accept,expected", [(True, True, True), (True, False, False), (False, True, False)])
@pytest.mark.parametrize("remote", [False, True])
def test_native_read_is_optional_owned_private_and_replayable(tmp_path, owned, accept, expected, remote):
    combat, table, mid = fight(tmp_path, owned=owned)
    # First recorded turn has no previous turn: unknown must not become No.
    assert not any(p["context"]["reaction_source_id"] == CHOICE for p in read(combat, table, mid))
    assert not facts(reload(tmp_path, mid))
    next_owner(combat, table, mid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    for _ in range(2):
        table.state(mid)
        candidate(combat, mid, "Read the Pulse (Pulse Seal)" if remote else "Read the Pulse", target=ALLY)
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    prompts = read(combat, table, mid, remote=remote, accept=accept)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts) == owned
    engine = reload(tmp_path, mid)
    assert bool(facts(engine)) == expected
    if expected:
        fact = facts(engine)[-1]
        assert fact.source_actor_id == OWNER
        assert fact.data["value"] == "Took no damage"
        public = recorded_knowledge_status(engine, engine.state.actors[ALLY], fact.model_dump(), fact.data)
        assert public["conceal_source"]
        assert "Took no damage" not in json.dumps(public)
        assert OWNER not in json.dumps(public)
        assert all("Took no damage" not in str(event.payload.get("log", "")) for event in engine.events)
        assert fact.instance_id in concealed_condition_instances(engine.state.model_dump(mode="json"))
        result = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE + "_result")
        assert result["context"]["reactor_id"] == OWNER
        assert "has taken no damage" in json.dumps(result)
    else:
        assert not any(p["context"]["reaction_source_id"] == CHOICE + "_result" for p in prompts)


@pytest.mark.parametrize("temporary_hp", [False, True])
def test_settled_native_attack_is_seen_then_ages_out(tmp_path, temporary_hp):
    combat, table, mid = fight(tmp_path)
    read(combat, table, mid)
    if temporary_hp:
        # Borrowed Breath requires a genuinely injured patient. Wound them
        # with a native attack before applying the native temporary vitality.
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, "Unarmed Strike", target=ALLY).candidate_id)
        turn(table, mid, OWNER)
        settle(table, mid, candidate(combat, mid, "Borrowed Breath", target=ALLY).candidate_id)
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Unarmed Strike", target=ALLY).candidate_id)
    damaged = reload(tmp_path, mid)
    assert any(e.event_type == "DAMAGE_COMMITTED" and ALLY in e.target_ids
               and int(e.payload.get("temporary_hp_absorbed" if temporary_hp else "hp_damage", 0)) > 0
               for e in damaged.events)
    turn(table, mid, OWNER)
    prompts = read(combat, table, mid, remote=True)
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts)
    engine = reload(tmp_path, mid)
    assert facts(engine)[-1].data["value"] == "Took damage"
    next_owner(combat, table, mid)
    read(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert [f.data["value"] for f in facts(engine)] == ["Took damage", "Took no damage"]


def test_ai_reader_resolves_automatically_without_a_human_prompt(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = fight(tmp_path, ask=False)
    read(combat, table, mid)
    next_owner(combat, table, mid)
    cid = candidate(combat, mid, "Read the Pulse", target=ALLY).candidate_id
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    real = combat.controller
    combat.controller = ManualControllerAdapter(lambda context: (cid, ()),
        reaction_chooser=lambda context: real.choose_reaction(context).decision)
    assert settle(table, mid, cid, auto=True) == []
    assert facts(reload(tmp_path, mid))[-1].data["value"] == "Took no damage"


@pytest.mark.parametrize("ability", ["WIS", "CON", "CHA"])
def test_actual_source_build_contract_offers_each_printed_increase_and_caps_it(ability):
    from stage2.insight_authority import compile_insight_stage2_authority
    from tests import test_insights_are_chosen as levels
    from tests.test_sol200_insight_choice import _production_shaped
    from character_creation.creative_controller.linear_menus import (
        build_insight_occurrence_menu, _effective_ability_scores,
    )
    from character_creation.creative_controller.linear_walk import commit_option
    root = Path(__file__).resolve().parents[1]
    catalogue = json.loads((root / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    row = next(r for r in catalogue["insights"] if r.get("canonical_insight_id") == PULSE_MEMORY)
    authority = compile_insight_stage2_authority(row, row["record_id"])
    assert authority["ability_change"]["allowed_abilities"] == ["WIS", "CON", "CHA"]
    assert authority["ability_change"]["amount"] == 1
    assert authority["typed_prerequisites"] == [{"kind": "sphere", "operator": "requires", "target_id": "tianxia.sphere.life"}]
    request, envelope = _production_shaped(5, extra=((PULSE_MEMORY, "Pulse-Thread Memory", ["WIS", "CON", "CHA"], row["prerequisites"]),))
    envelope["typed_choice_authority_by_slot"]["insight_priorities"]["stage2_authority_by_choice"][PULSE_MEMORY] = authority
    milestone = levels._milestone_id(4)
    state = levels._starting_state(5)
    initial = build_insight_occurrence_menu(request, envelope, state, milestone_id=milestone)
    assert initial is None or not any(PULSE_MEMORY in o.choice_ids for o in initial.options)
    state = state.with_pair("tianxia.sphere.life", READ)
    initial = build_insight_occurrence_menu(request, envelope, state, milestone_id=milestone)
    option = next(o for o in initial.options if o.choice_ids == (PULSE_MEMORY,))
    state = commit_option(initial, option.option_id, state)
    menu = build_insight_occurrence_menu(request, envelope, state, milestone_id=milestone)
    assert {o.choice_ids[0] for o in menu.options if o.choice_ids} == {"WIS", "CON", "CHA"}
    scores = dict(state.bounded["ability_scores"])
    scores[ability] = authority["ability_change"]["cap"]
    capped = build_insight_occurrence_menu(request, envelope, state.with_ability_scores(scores), milestone_id=milestone)
    assert not any(o.choice_ids == (ability,) for o in capped.options)
    picked = next(o for o in menu.options if o.choice_ids == (ability,))
    after = commit_option(menu, picked.option_id, state)
    assert _effective_ability_scores(after, request, envelope)[ability] == state.bounded["ability_scores"][ability] + 1


def test_real_compiled_source_and_no_combat_asi_reapplication():
    from combat.factory_compiler import compile_character
    from factory_authoring.insight_sources import current_insight_sources
    root = Path(__file__).resolve().parents[1]
    source = current_insight_sources(root)[PULSE_MEMORY]
    assert sha256(source["text"].encode()).hexdigest() == "17eb22468ae78dcef683e9836b77ce7989683a1ed89c069e2f7be5c52024b536"
    document = sheet([READ])
    baseline = compile_character(document, actor_id=OWNER)
    document["spheres_and_talents"]["cultivation_insight_record_ids"] = [PULSE_MEMORY]
    compiled = compile_character(document, actor_id=OWNER)
    assert sum(r.get("kind") == PULSE_MEMORY for r in compiled["typed_passives"]) == 1
    for key in ("strength_score", "dexterity_score", "maximum_hp", "saving_throws", "resources"):
        assert compiled["actor_template"][key] == baseline["actor_template"][key]
