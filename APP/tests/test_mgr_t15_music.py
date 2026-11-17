"""MGR-T15 Music rows: real table transactions, rollback, cold reload and replay.

No model clients or browsers. The controller fixture selects an actual legal
primary action; automatic damage choices use the production choice policy.
"""
import pytest

from tests.test_a2_music_second_pass import (
    setup, engine, perform, _act_when, ME, ALLY, FOE, FOE2, M,
)


@pytest.mark.parametrize("slug,name", [
    ("dissonant_note", "Dissonant Note"),
    ("heartstring_severing_prelude", "Heartstring Severing Prelude"),
    ("soul_sundering_note", "Soul-Sundering Note"),
])
@pytest.mark.parametrize("recipient", [ME, ALLY, FOE])
def test_one_creature_notes_admit_self_allies_and_enemies(tmp_path, slug, name, recipient):
    root = tmp_path / "creature"
    combat, table, mid = setup(root, [M + slug], "mgr-t15-" + slug)
    perform(combat, table, mid, root, name, target=recipient)
    e = engine(combat, mid)
    saves = [ev for ev in e.events if ev.event_type == "SAVE_ROLLED"
             and M + slug in ev.source_definition_id and ev.actor_id == recipient]
    assert len(saves) == 1
    assert e.state.actors[ME].resources["resource:core.qi"] == 100 - (2 if slug == "dissonant_note" else 10)


@pytest.mark.parametrize("slug,name", [
    ("concerto_of_broken_breath", "Concerto of Broken Breath"),
    ("soul_sundering_note", "Soul-Sundering Note"),
])
@pytest.mark.parametrize("kind", ["PSYCHIC", "THUNDER"])
def test_damage_choice_is_one_transaction_for_full_and_half_damage(tmp_path, slug, name, kind):
    def transform(bundles):
        # One failed and one successful cone save exercises the shared choice
        # across recipients AND branches. A single note always fails its save.
        for b in bundles:
            b["actor_template"]["saving_throws"].update(CON=-100, WIS=-100)
        bundles[3]["actor_template"]["saving_throws"]["CON"] = 100

    root = tmp_path / "damage"
    combat, table, mid = setup(root, [M + slug], "mgr-t15-" + slug, bundle_transform=transform)
    prompts = []

    def choose(prompt):
        if prompt["context"].get("reaction_source_id") == "choice:needle.music_damage_type":
            prompts.append(prompt)
            assert {o["id"] for o in prompt["choice"]["options"]} == {"PSYCHIC", "THUNDER"}
            assert name in prompt["moment"]
            assert "Cultivation Points" in prompt["moment"]
            assert prompt["action"].startswith(name)
            return [kind]
        return None

    _act_when(combat, table, mid, root, lambda e, c: c.actor_id == ME
              and c.display_name.startswith(name)
              and (FOE in c.target_ids if slug == "soul_sundering_note"
                   else c.destination == e.state.actors[FOE].position), choose=choose)
    e = engine(combat, mid)
    damage = [ev for ev in e.events if ev.event_type == "DAMAGE_COMMITTED"
              and M + slug in ev.source_definition_id]
    assert len(prompts) == 1, "one choice for the entire activation"
    assert damage and {ev.payload["damage_type"] for ev in damage} == {kind}
    if slug == "concerto_of_broken_breath":
        saves = [ev for ev in e.events if ev.event_type == "SAVE_ROLLED"
                 and M + slug in ev.source_definition_id]
        assert {ev.payload["success"] for ev in saves} == {False, True}
        assert {FOE, FOE2}.issubset({t for ev in damage for t in ev.target_ids})


@pytest.mark.parametrize("slug,name,expected", [
    ("concerto_of_broken_breath", "Concerto of Broken Breath", "THUNDER"),
    ("soul_sundering_note", "Soul-Sundering Note", "PSYCHIC"),
])
def test_ai_keeps_both_types_legal_and_chooses_without_private_defenses(tmp_path, slug, name, expected):
    root = tmp_path / "automatic"
    combat, table, mid = setup(root, [M + slug], "mgr-t15-ai-" + slug,
                              automatic=True, ask_actors=())
    prompts = []
    _act_when(combat, table, mid, root, lambda e, c: c.actor_id == ME
              and c.display_name.startswith(name)
              and (FOE in c.target_ids if slug == "soul_sundering_note"
                   else c.destination == e.state.actors[FOE].position),
              choose=lambda p: prompts.append(p))
    assert not prompts, "AI choices must not ask the human"
    damage = [ev for ev in engine(combat, mid).events if ev.event_type == "DAMAGE_COMMITTED"
              and M + slug in ev.source_definition_id]
    assert damage and {ev.payload["damage_type"] for ev in damage} == {expected}
