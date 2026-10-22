"""A2R03F32: option listings and refusal for the shared Foundation seams.

The branch changes three shared seams (combat/ext/__init__.py contracts for the
A2R03 foundation):

* ``compile_maximum_hp`` -- the max-HP submission (no player option; covered
  by test_a2r03_f23_marrow_frame.py and the Foundation compile below);
* ``damage_reduction_bonus`` paid settlement -- the REACTION_RESOLVED receipt
  is published only after a paid settlement, so a refusal spends nothing and
  publishes none;
* ``granted_moves.choose`` -- the full observed destination pool is offered to
  human and computer seats alike and declining moves nobody;

and ``combat/typed_executor.py`` now passes an opposed check's hazards to both
d20 scopes as ``named`` pressure tags as well. That scope offers no player
option; the regressions below pin the tags and the bonus the printed Frame
clause is missing without them.

Every choice-bearing assertion lists the offered options and the refusal path,
so a later change that hides or truncates a legal option fails here.

The Marrow Pack Guard reaction compiles from printed trigger text, so on the
public snapshot (pseudoword prose) its row is absent; that one case carries
``requires_private_prose`` like the rest of the guard coverage.
"""
from types import SimpleNamespace

import pytest

from combat import granted_movement
from combat.ext import granted_moves, needle
from combat.factory_compiler import compile_character
from combat.typed_executor import Context, run_effects
from tests.public_snapshot import requires_private_prose
from tests.test_a2r03_fix_round import _play_picked, _prepare_pressure
from tests.test_a2r03_review_f19_echo_hits import _prior_damage
from tests.test_a2r03_review_round5 import _take_owner_turn
from tests.test_lock_choices import install
from tests import test_a2r11_foundations as f

METHOD = f.METHOD
FRAME = f.FRAME


# --------------------------------------------------------- opposed-check d20 scopes


def _probe_contest(monkeypatch, hazards):
    engine = f._duel([FRAME], f._sacred("Awakened"))
    actor, target = engine.state.actors[f.ME], engine.state.actors[f.FOE]
    action = next(iter(engine.action_catalog.values()))
    frames = []
    install(monkeypatch, "roll_context_end", lambda _engine, frame: frames.append(dict(frame)))
    effect = {"type": "contest_against", "harmful": True, "applies_to": "target",
              "actor_check": {"kind": "check", "ability": "STR", "skill": "Athletics",
                              "hazards": hazards},
              "target_check": {"kind": "dc", "dc": 30}, "on_success": [], "on_fail": []}
    f.script(engine, [8])
    run_effects(Context(engine, actor, action, None,
                        {"source": "test:frame", "effects": [effect]}, [target], target), [effect])
    return engine, actor, frames


@pytest.mark.parametrize("hazards", [[], ["poisoned"]])
def test_opposed_check_carries_hazards_and_named_pressure_in_both_d20_scopes(monkeypatch, hazards):
    engine, actor, frames = _probe_contest(monkeypatch, hazards)
    scopes = [frame for frame in frames if frame.get("kind") == "check"]
    # Both d20 scopes of one opposed check: the pre-draw check scope and the
    # post-draw adjustment scope.
    assert len(scopes) == 2
    assert [[scope["hazards"], scope["named"]] for scope in scopes] == [[hazards, hazards]] * 2
    roll = next(event for event in engine.events if event.event_type == "CHECK_ROLLED")
    # STR +2, plus Saint-Body Frame's printed PB (+4) only when the check names
    # the body-pressure hazard. An empty specification stays unscoped.
    assert roll.payload["actor"]["modifier"] == (6 if hazards else 2)
    clock = actor.turn_flags.get("pressure_round_clock") or {}
    assert (f"save_bonus:{FRAME}" in clock) is bool(hazards)


# ------------------------------------------------------------ granted move listing


def test_pressure_becomes_method_move_lists_every_legal_destination_and_refuses(tmp_path, monkeypatch):
    """Pressure Becomes Method's move offers the whole observed destination
    pool (granted_moves.choose); declining it leaves the fighter where it
    stood and spends nothing."""
    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._sacred(), f.SACRED_BARE,
        prepare=_prepare_pressure("CON", 16, "poisoned"))
    live = f._engine(combat, mid)
    fighter = live.state.actors[f.FIGHTER]
    expected = set(granted_movement.candidates(
        live, fighter, 10, SimpleNamespace(decision_id="probe", state_version=0,
                                           actor_id=f.FIGHTER), METHOD))
    assert len(expected) > 1
    start = fighter.position.model_dump()

    offered = []
    def pick(prompt):
        options = [row["id"] for row in (prompt.get("choice") or {}).get("options") or ()]
        moment = str(prompt.get("moment") or "")
        if moment.startswith("Pressure Becomes Method: after "):
            offered.extend(options)
            return "DECLINE"
        return "move" if "move" in options else "DECLINE"

    _, prompts = _play_picked(table, mid, f._candidate(table, mid, "Body pressure", f.FIGHTER), pick)
    assert sum(1 for prompt in prompts if prompt["reaction"] == "Pressure Becomes Method") == 2
    assert set(offered) == expected  # every legal destination, none truncated
    assert len(offered) == len(set(offered))
    cold = f._engine(combat, mid)
    owner = cold.state.actors[f.FIGHTER]
    assert owner.position.model_dump() == start
    assert not any(event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == f.FIGHTER
                   for event in cold.events)
    assert owner.resources[f.PULSE] == 1  # the save generated it; the refusal spent nothing


def test_granted_move_offers_every_legal_destination_to_a_computer_seat(monkeypatch):
    """A model/AI seat is asked with the same full pool: no automatic subset
    and no truncation, plus a working refusal."""
    engine = f._duel([f.M_PREDATOR], f._marrow())
    engine.typed_control_modes = {f.ME: "LOCAL_AUTO"}
    mover = engine.state.actors[f.ME]
    intent = SimpleNamespace(decision_id="decision:test", state_version=1, actor_id=f.ME)
    expected = set(granted_movement.candidates(engine, mover, 10, intent, "test:grant"))
    assert len(expected) > 1
    seen = {}

    def ask(_engine, _intent, _checkpoint, _chooser, choice_id, options, **kwargs):
        seen.update(choice_id=choice_id, options=list(options), kwargs=kwargs)
        return []

    monkeypatch.setattr(needle, "ask", ask)
    start = mover.position.model_dump()
    assert granted_moves.choose(engine, mover, 10, "test:grant", "Test Grant", intent=intent) == 0
    assert seen["choice_id"] == "choice:needle.granted_destination"
    assert set(seen["options"]) == expected
    assert "automatic_options" not in seen["kwargs"]
    assert seen["kwargs"]["allow_decline"] is True
    assert seen["kwargs"]["preferred"] and set(seen["kwargs"]["preferred"]) <= expected
    assert "Test Grant" in seen["kwargs"]["prompt"] and "up to 10 feet" in seen["kwargs"]["prompt"]
    assert all(label.startswith(f"Move {mover.display_name} to ")
               for label in seen["kwargs"]["labels"].values())
    assert mover.position.model_dump() == start


# ------------------------------------------------- damage reduction paid settlement


@requires_private_prose
def test_marrow_pack_guard_refusal_lists_the_reaction_and_leaves_no_receipt(tmp_path, monkeypatch):
    """The paid damage-reduction settlement publishes its REACTION_RESOLVED
    receipt only after payment: the printed reaction is offered by name, and
    a refusal spends no Echo, keeps the Reaction and publishes no receipt."""
    combat, table, mid = f._service_fight(
        tmp_path, monkeypatch, f._marrow("Awakened"), f.MARROW_BARE,
        foe_creature_types=("Humanoid",), prepare=lambda bundles: _prior_damage(bundles, "hp"))
    _take_owner_turn(table, mid)
    f._play(table, mid, f._candidate(table, mid, "Establish link", f.SERVICE_FOE))
    f._play(table, mid, table.state(mid)["menu"]["end_turn"])
    f._until(table, mid, f.SERVICE_FOE, answer="DECLINE")
    before = f._engine(combat, mid).state.actors[f.FIGHTER]
    assert before.resources[f.ECHO] == 1
    _, prompts = _play_picked(
        table, mid, f._candidate(table, mid, "Incoming technique", f.FIGHTER),
        lambda prompt: "DECLINE")
    offered = [prompt for prompt in prompts if prompt["reaction"] == "Marrow Pack Guard"]
    assert len(offered) == 1
    assert "Incoming technique" in offered[0]["moment"]
    cold = f._engine(combat, mid)
    owner = cold.state.actors[f.FIGHTER]
    assert owner.resources[f.ECHO] == 1
    assert owner.reaction_available is True
    assert owner.current_hp == before.current_hp - 10  # full damage, no reduction
    assert not any(event.event_type == "REACTION_RESOLVED" for event in cold.events)


# --------------------------------------------------- Pack Echo single delivery owner


def test_generate_pack_echo_claims_the_generic_reaction_out_of_the_compile():
    """The plug-in row owns the whole generate trigger (``trigger_owner``), so
    the compiled generic own-hit reaction is omitted. Restoring the generic
    row alongside the plug-in would generate twice and fails the first assert."""
    result = compile_character(f._doc([f._first_feature(f.MARROW_BARE)], "fighter",
                                      foundation=f._marrow()), actor_id=f.FIGHTER)
    owned = [row for row in result["typed_passives"] if row.get("feature_id") == f.M_GENERATE]
    assert [row.get("trigger_owner") for row in owned] == ["beast_echo_marrow"]
    assert not any(row.get("feature_id") == f.M_GENERATE for row in result["typed_reactions"])

    stranger = compile_character(f._doc([], "stranger"), actor_id=f.SERVICE_FOE)
    assert not any(row.get("feature_id") == f.M_GENERATE for row in stranger["typed_passives"])
    assert not any(row.get("feature_id") == f.M_GENERATE for row in stranger["typed_reactions"])


@requires_private_prose
def test_the_claim_out_does_not_also_drop_the_guards_own_generic_reaction():
    """The claim is exactly the generate trigger, not the whole foundation: the
    guard's compiled generic reaction still stands beside its plug-in row.
    (Its row compiles from printed trigger prose, absent on the public
    snapshot, so this case stays private like the rest of the guard coverage.)"""
    result = compile_character(f._doc([f._first_feature(f.MARROW_BARE)], "fighter",
                                      foundation=f._marrow()), actor_id=f.FIGHTER)
    assert any(row.get("block") == "generic" and row.get("feature_id") == f.M_GUARD
               for row in result["typed_reactions"])
