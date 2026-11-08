"""Music Echoing Step's selected creature survives a real commit and cold reload."""
import pytest

from tests.test_a2_music_second_pass import setup, engine, _act_when, table_next, ME, ALLY, FOE, FOE2, M
from combat.ext import run_strict
from combat.ext.echoing_step import CREATURE


@pytest.mark.parametrize("automatic", [False, True])
def test_echoing_step_selects_one_perceiving_creature_for_this_turn(tmp_path, automatic):
    root = tmp_path / "echo"
    combat, table, mid = setup(root, [M + "echoing_step"], "mgr-t15-echo",
                              automatic=automatic, ask_actors=() if automatic else (ME,))
    prompts = []
    chosen = FOE if automatic else FOE2

    def choose(prompt):
        if prompt["context"].get("reaction_source_id") == "choice:needle.echoing_step_creature":
            prompts.append(prompt)
            options = {o["id"] for o in prompt["choice"]["options"]}
            assert options == {ALLY, FOE, FOE2}, "all legal recipients remain reachable"
            assert "Echoing Step" in prompt["moment"] and "this turn" in prompt["moment"]
            return [FOE2]
        return None

    _act_when(combat, table, mid, root, lambda e, c: c.actor_id == ME and c.display_name.startswith("Echoing Step"),
              choose=choose)
    e = engine(combat, mid)
    actor = e.state.actors[ME]
    assert actor.turn_flags[CREATURE] == chosen
    assert len(prompts) == (0 if automatic else 1)
    assert False in run_strict("opportunity_allowed", e, e.state.actors[chosen], actor)
    other = FOE2 if automatic else FOE
    assert False not in run_strict("opportunity_allowed", e, e.state.actors[other], actor)
    table_next(combat, table, mid, root)
    e = engine(combat, mid)
    assert False not in run_strict("opportunity_allowed", e, e.state.actors[chosen], e.state.actors[ME])


@pytest.mark.parametrize("hearing_only", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
def test_echoing_step_known_unseen_and_hearing_only_recipient(tmp_path, hearing_only, automatic):
    from tests.test_auto72_music import _add_test_action
    from combat import senses, target_knowledge

    root = tmp_path / "unseen"

    def transform(bundles):
        effects = [{"type": "condition", "condition": "invisible", "applies_to": "target",
                    "expires_on": "UNTIL_REMOVED"}]
        if hearing_only:
            effects.append({"type": "condition", "condition": "blinded", "applies_to": "target",
                            "expires_on": "UNTIL_REMOVED"})
        _add_test_action(bundles[0], name="Prepare unseen listener", source_id="action:test.echo_listener",
                         target_kind="HOSTILE_ENTITY", range_ft=30, effects=effects)

    combat, table, mid = setup(root, [M + "echoing_step"], "echo-listener",
                              automatic=automatic, ask_actors=() if automatic else (ME,),
                              bundle_transform=transform)
    _act_when(combat, table, mid, root,
              lambda e, c: c.actor_id == ME and c.source_definition_id == "action:test.echo_listener"
              and FOE in c.target_ids)
    e = engine(combat, mid)
    actor, listener = e.state.actors[ME], e.state.actors[FOE]
    assert not target_knowledge.located(e, actor, listener)
    assert target_knowledge.knowledge(e, actor, listener).mode == "LAST_OBSERVED"
    assert senses.perceives(e, listener, actor) is (not hearing_only)
    prompts = []

    def choose(prompt):
        if prompt["context"].get("reaction_source_id") == "choice:needle.echoing_step_creature":
            prompts.append(prompt)
            assert {o["id"] for o in prompt["choice"]["options"]} == {ALLY, FOE, FOE2}
            return [FOE]
        return None

    _act_when(combat, table, mid, root,
              lambda e, c: c.actor_id == ME and c.display_name.startswith("Echoing Step"), choose=choose)
    e = engine(combat, mid)
    assert e.state.actors[ME].turn_flags[CREATURE] == FOE
    assert len(prompts) == (0 if automatic else 1)
    assert False in run_strict("opportunity_allowed", e, e.state.actors[FOE], e.state.actors[ME])
    assert False not in run_strict("opportunity_allowed", e, e.state.actors[FOE2], e.state.actors[ME])
    # Commit movement while the protection is active; the helper cold-loads and
    # mechanically replays both the ability and this movement transaction.
    sequence = len(e.events)
    assert e.state.actors[FOE].reaction_available
    _act_when(combat, table, mid, root, lambda e, c: c.actor_id == ME and c.kind.value == "MOVE"
              and c.destination is not None and c.destination.x < 3, choose=choose)
    e = engine(combat, mid)
    assert e.state.actors[ME].turn_flags[CREATURE] == FOE
    assert e.state.actors[ME].position.x < 3
    assert e.state.actors[FOE].reaction_available
    from combat.gate2_engine import SYSTEM_OPPORTUNITY
    assert not any(ev.source_definition_id == SYSTEM_OPPORTUNITY and ev.actor_id == FOE
                   for ev in e.events[sequence:])


def test_echoing_step_recipient_knowledge_sound_paths_and_observed_ranking(tmp_path, monkeypatch):
    from combat import ext, speech
    from combat.ext.echoing_step import recipients

    combat, table, mid = setup(tmp_path / "boundaries", [M + "echoing_step"], "echo-boundaries")
    e = engine(combat, mid)
    actor, near, far = (e.state.actors[aid] for aid in (ME, FOE, FOE2))
    # Both enemies were observed at creation. Concealment must not erase the
    # choice, or let AI rank a remembered enemy by its new hidden location.
    for other in (near, far):
        e._apply_condition(other, "condition:typed.invisible", "test:echo", ME, expires_on="UNTIL_REMOVED")
    near.position = near.position.model_copy(update={"x": 10})
    assert [a.entity_id for a in recipients(e, actor)] == [FOE, FOE2, ALLY]
    e.state.observations[actor.team_id].pop(FOE)
    assert FOE not in {a.entity_id for a in recipients(e, actor)}, "hearing by an unknown enemy cannot reveal it"
    e._apply_condition(far, "condition:typed.blinded", "test:echo", ME, expires_on="UNTIL_REMOVED")
    assert FOE2 in {a.entity_id for a in recipients(e, actor)}
    original = ext.run_strict

    def blocked(name, *args, **kwargs):
        if name == "sound_path_allowed":
            assert args[1] is actor and args[3] == M + "echoing_step"
            return [False]
        return original(name, *args, **kwargs)

    # Exercise native can_hear_from dispatch, including providers that block
    # transmission; no fake replacement of the hearing decision itself.
    monkeypatch.setattr(ext, "run_strict", blocked)
    assert not speech.can_hear_from(e, actor, far, M + "echoing_step")
    assert FOE2 not in {a.entity_id for a in recipients(e, actor)}
    assert ALLY in {a.entity_id for a in recipients(e, actor)}, "visual perception survives a blocked sound path"
    monkeypatch.setattr(ext, "run_strict", original)
    e._apply_condition(far, "condition:typed.deafened", "test:echo", ME, expires_on="UNTIL_REMOVED")
    assert FOE2 not in {a.entity_id for a in recipients(e, actor)}
