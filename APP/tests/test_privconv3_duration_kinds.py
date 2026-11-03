"""Duration consumers read the lifetime name from either form.

The reviewed authority stores every effect duration as a typed ``{"kind", "anchor"}``
dict; hand-written rows still carry the plain string. Each consumer below used to
compare the raw value to a string, so the dict form silently fell out of the
attack-only, Bell, Sand burial and minutes branches.
"""
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from combat import concentration
from combat.ext import effect_durations, music, sand_burial
from combat import typed_executor, typed_reactions

TRIGGER = {"kind": "triggering_attack", "anchor": "current"}
CONCENTRATION = {"kind": "concentration", "anchor": "current"}


def test_kind_of_reads_both_forms():
    assert effect_durations.kind_of("triggering_attack") == "triggering_attack"
    assert effect_durations.kind_of(TRIGGER) == "triggering_attack"
    assert effect_durations.kind_of({"kind": "Concentration"}) == "concentration"
    assert effect_durations.kind_of(None) == ""
    assert effect_durations.kind_of("") == ""


def test_attack_only_ac_is_recognised_in_dict_form():
    # Shield / Defensive Teamwork: the dict-form AC row must stay out of the ordinary sum.
    assert typed_reactions._attack_only({"type": "ac_bonus", "flat": 2, "duration": TRIGGER})
    assert typed_reactions._attack_only({"type": "ac_bonus", "flat": 2, "duration": "triggering_attack"})
    assert not typed_reactions._attack_only({"type": "ac_bonus", "flat": 2, "duration": {"kind": "instant"}})


@dataclass
class _Engine:
    pass


@dataclass
class _Ctx:
    source: Any
    actor: Any
    typed: dict = field(default_factory=dict)
    engine: Any = field(default_factory=_Engine)


def test_bell_initiative_leaves_the_dict_form_row_alone(monkeypatch):
    # Bell of Warning rung on Initiative: no attack to add AC to, so the row is refused
    # and the plain line is written. A dict-form row used to fall through and get applied.
    notes = []
    monkeypatch.setattr(music, "note", lambda *args: notes.append(args))
    row = {"type": "ac_bonus", "flat": 2, "duration": TRIGGER}
    ctx = _Ctx(source=music.BELL, actor="ally", typed={"reaction_checkpoint": "initiative"})
    result = music.bell_ac_needs_an_attack(ctx, row)
    assert result is False
    assert notes and notes[0][2] == "ally" and notes[0][3] == music.BELL_INITIATIVE_TRIGGER


def test_bell_on_a_real_attack_checkpoint_keeps_its_ac_even_without_a_spec(monkeypatch):
    # Regression (PRIVCONV3RB4 F1): the denial used to key on a missing triggering_attack_spec, so any attack
    # checkpoint that ran the row without the spec wrongly refused the +2 AC against the attack it answers.
    # Only the Initiative checkpoint has no attack. A real attack checkpoint is allowed through.
    monkeypatch.setattr(music, "note", lambda *args: (_ for _ in ()).throw(AssertionError("noted")))
    row = {"type": "ac_bonus", "flat": 2, "duration": TRIGGER}
    for checkpoint in ("attacked", "hit", "missed"):
        ctx = _Ctx(source=music.BELL, actor="ally", typed={"reaction_checkpoint": checkpoint})
        assert music.bell_ac_needs_an_attack(ctx, row) is None, checkpoint
    assert music.bell_ac_needs_an_attack(_Ctx(source=music.BELL, actor="ally", typed={}), row) is None


def test_every_real_attack_checkpoint_hands_its_spec_to_the_effects():
    # Regression (PRIVCONV3RB4 F1): on_attack_resolved, _offer_ally_missed and on_attack_missed ran their
    # generic effects with no triggering_attack_spec, so a spec-bound AC row had nothing to attach to.
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(typed_reactions))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("on_attack_resolved", "_offer_ally_missed", "on_attack_missed"):
        calls = [node for node in ast.walk(functions[name])
                 if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_run_generic_effects"]
        assert calls, name
        for call in calls:
            assert any(kw.arg == "attack_spec" for kw in call.keywords), (name, call.lineno)


def test_own_checkpoint_labels_the_initiative_ring():
    # on_own_event passes its kind through, so the Initiative ring is the one checkpoint that denies the AC.
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(typed_reactions))
    fn = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "on_own_event")
    calls = [node for node in ast.walk(fn) if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_run_generic_effects"]
    assert calls and all(any(kw.arg == "checkpoint" for kw in call.keywords) for call in calls)


def test_bell_leaves_other_sources_and_durations_alone(monkeypatch):
    monkeypatch.setattr(music, "note", lambda *args: (_ for _ in ()).throw(AssertionError("noted")))
    row = {"type": "ac_bonus", "flat": 2, "duration": TRIGGER}
    assert music.bell_ac_needs_an_attack(_Ctx(source="other.source", actor="ally"), row) is None
    assert music.bell_ac_needs_an_attack(
        _Ctx(source=music.BELL, actor="ally"), {"type": "ac_bonus", "duration": {"kind": "rounds"}}) is None


@dataclass
class _Subject:
    entity_id: str = "actor:factory.target"
    active: bool = True


@dataclass
class _SandCtx:
    actor: Any
    source: Any
    target: Any = None
    targets: Any = None


def test_concentration_linked_burial_ends_with_concentration(monkeypatch):
    # Devouring Dune Mouth's Buried is "a Concentration" duration while the user concentrates.
    # Without the dict-form read, the copy got the fallback expiry instead of CONCENTRATION_END.
    captured = []
    subject = _Subject()
    monkeypatch.setattr(concentration, "concentrating_on", lambda actor, source: True)
    monkeypatch.setattr(sand_burial, "buried", lambda actor: [])
    monkeypatch.setattr(typed_executor, "_default_subject", lambda ctx, row, harmful: [subject])
    monkeypatch.setattr(typed_executor, "block_condition",
                        lambda ctx, row: captured.append(dict(row)))
    row = {"type": "sand_bury", "applies_to": "target", "duration": CONCENTRATION,
           "condition_data": {}}
    sand_burial.sand_bury(_SandCtx(actor=SimpleNamespace(entity_id="actor:factory.me"), source="SRC"), row)
    assert captured and captured[0]["expires_on"] == "CONCENTRATION_END"


def test_concentration_linked_burial_keeps_the_stored_expiry(monkeypatch):
    captured = []
    subject = _Subject()
    monkeypatch.setattr(concentration, "concentrating_on", lambda actor, source: True)
    monkeypatch.setattr(sand_burial, "buried", lambda actor: [])
    monkeypatch.setattr(typed_executor, "_default_subject", lambda ctx, row, harmful: [subject])
    monkeypatch.setattr(typed_executor, "block_condition",
                        lambda ctx, row: captured.append(dict(row)))
    row = {"type": "sand_bury", "applies_to": "target", "duration": CONCENTRATION,
           "condition_data": {}, "expires_on": "START_OF_SOURCE_NEXT_TURN"}
    sand_burial.sand_bury(_SandCtx(actor=SimpleNamespace(entity_id="actor:factory.me"), source="SRC"), row)
    assert captured[0]["expires_on"] == "START_OF_SOURCE_NEXT_TURN"
