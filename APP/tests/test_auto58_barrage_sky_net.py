"""AUTO58: Sky-Net Suppression's printed choice for the creature that walks into the net.

"A hostile creature that enters the area for the first time on a turn or starts its turn inside chooses: Slow Down
... Push Through ...". The typing applied both branches to every hostile creature in the area, so each one lost 10 feet
of Speed and attacked at -2 whether it chose or not, and the printed choice was left to the GM.

combat/ext/barrage_sky_net.py puts the printed question to the creature's controller and runs only the branch it
answers; combat/ext/ammunition.py's sibling change and the zone's own per-turn clock give "for the first time on a turn"
and "once per turn".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from combat.ext import barrage_sky_net
from combat.gate2_runtime_content import AN

_spec = importlib.util.spec_from_file_location("sweep_athletics_helpers", Path(__file__).with_name("test_review_sw-athletics.py"))
helpers = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(helpers)

ME, FOE = helpers.ME, AN
SKY_NET = "TAL_BARRAGE_SKY_NET_SUPPRESSION"
BOW_KIT = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "name": "Gong Jian", "quantity": 1},
                                      {"item_id": "tianxia.mortal.gear.arrows_20", "name": "Arrows (20)", "quantity": 1}]}}


def _fight(*talents, foe_at=(4, 6)):
    return helpers._engine(helpers._bundle(helpers.BARRAGE, list(talents), BOW_KIT, cl=17, dc=helpers.FAIL),
                           foe_hp=800, foe_at=foe_at)


def _answer(monkeypatch, choice):
    """Answer the printed Sky-Net question with ``choice`` (the creature's side of the table)."""
    from combat.ext import needle

    original = needle.ask
    seen: list[str] = []

    def record(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        answer = [choice] if choice_id.endswith("sky_net") and choice in options else original(
            engine, intent, checkpoint, chooser, choice_id, options, **kwargs)
        seen.append(f"{choice_id} chooser={chooser.entity_id} -> {list(answer)}")
        return answer

    monkeypatch.setattr(needle, "ask", record)
    return seen


def _fire(engine, base="Sky-Net Suppression", at="4,6"):
    from combat.gate2_runtime_models import ActionIntent
    from tests.equipment_readiness import ready_weapon

    ready_weapon(engine, base, ME)
    candidates = [c for c in engine.legal_candidates() if c.display_name.split(" \u2014 ")[0].startswith(base)]
    assert candidates, f"{base!r} is not offered; legal: {sorted(c.display_name for c in engine.legal_candidates())[:20]}"
    chosen = next((c for c in candidates if f" at {at}" in c.display_name), candidates[0])
    engine.execute_intent(ActionIntent(intent_id=f"i-{base}", decision_id=chosen.decision_id, candidate_id=chosen.candidate_id,
                                       state_version=chosen.state_version, actor_id=ME, target_ids=chosen.target_ids,
                                       destination=chosen.destination))
    return engine


def _zone(engine):
    from combat import zones

    mine = barrage_sky_net._zones(engine, engine.state.actors[ME])
    assert mine, "Sky-Net Suppression placed no area"
    return mine[0]


def _enter(engine):
    """A hostile creature entering the area: the zone module's own public moment dispatcher."""
    from combat import zones

    before = len(engine.events)
    zones.fire_trigger(engine, _zone(engine), _foe(engine), "enter")
    return engine.events[before:]


def _foe(engine):
    return engine.state.actors[FOE]


def _conditions(actor):
    return {row.condition_id for row in actor.conditions.values()}


def _modifiers(actor):
    return {(row.target_field, row.value) for row in actor.modifiers.values()}


def _speed_modifiers(actor):
    return [row for row in actor.modifiers.values() if row.target_field == "speed_ft"]


# ------------------------------------------------------------------------------------------------ the typing


def test_the_both_branches_typing_is_replaced_by_the_printed_choice():
    """"attacks have a -2 penalty" and "reduce Speed by 10 feet" are the two branches, not one creature's fate."""
    effects = helpers._mechanics()[SKY_NET]["effects"]
    assert [effect.get("type") for effect in effects] == ["zone"]
    zone = effects[0]
    assert zone["triggers"] == [{"id": "sky_net_choice", "name": "Sky-Net Suppression", "on": ["enter", "start"],
                                 "who": "hostile",
                                 "effects": [{"type": "barrage_sky_net",
                                              "evidence": "A hostile creature that enters the area for the first time "
                                                          "on a turn or starts its turn inside chooses: Slow Down or "
                                                          "Push Through."}]}]
    assert helpers._mechanics()[SKY_NET]["riders"] == []


# ------------------------------------------------------------------------------------------------ the printed choice


def test_the_creature_chooses_and_only_push_through_happens(monkeypatch):
    seen = _answer(monkeypatch, "push_through")
    engine = _fight(SKY_NET)
    _fire(engine)
    _enter(engine)
    assert any(line.startswith("choice:needle.sky_net chooser=" + FOE) for line in seen), seen
    assert barrage_sky_net.SLOW not in _conditions(_foe(engine))      # Slow Down did not happen


def test_the_creature_choosing_slow_down_loses_its_speed_and_cannot_dash_through_the_net(monkeypatch):
    _answer(monkeypatch, "slow_down")
    engine = _fight(SKY_NET)
    _fire(engine)
    _enter(engine)
    assert barrage_sky_net.SLOW in _conditions(_foe(engine))
    # "movement costs 2 feet for every 1 foot traveled": each 5-foot step costs one square more.
    assert barrage_sky_net.slowed_movement(engine, _foe(engine), "walk") == engine.grid.square_size_ft
    assert barrage_sky_net.slowed_movement(engine, _foe(engine), "fly") == engine.grid.square_size_ft
    # The other branch's Speed loss did not happen.
    assert _speed_modifiers(_foe(engine)) == []


def test_the_surcharge_is_inert_for_every_creature_without_the_printed_condition():
    engine = _fight(SKY_NET)
    me = engine.state.actors[ME]
    assert barrage_sky_net.slowed_movement(engine, me, "walk") is None


def test_nothing_happens_once_the_area_is_gone(monkeypatch):
    """"A hostile creature that enters the area" -- with no Sky-Net area up, the effect has no subject."""
    _answer(monkeypatch, "push_through")
    engine = _fight()  # the talent is not owned, so no area is ever made
    assert barrage_sky_net._zones(engine, engine.state.actors[ME]) == []
    from combat.typed_executor import Context
    actor, target = engine.state.actors[ME], _foe(engine)
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME)
    before = engine.state.model_dump(mode="json"), len(engine.events)
    barrage_sky_net.sky_net(Context(engine, actor, action, None, {}, [target], target), {"type": "barrage_sky_net"})
    assert (engine.state.model_dump(mode="json"), len(engine.events)) == before


@pytest.mark.parametrize("path", ["stock", "compiled_native", "typed"])
def test_slow_down_penalizes_real_attacks_once_and_expires_after_cold_reload(tmp_path, path):
    """The same accepted attack is unpenalized, slowed, then unpenalized after expiry.

    Stock An and a sealed native character attack use Gate2; the compiled
    weapon attack uses block_attack. Every step commits
    through the table/session execute_intent path and reloads from disk.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.worker2_support import sealed_native_attack, settle, turn

    root = Path(__file__).resolve().parents[1]
    owner = helpers._bundle(helpers.BARRAGE, [SKY_NET], BOW_KIT, cl=17)
    foe_id = AN if path == "stock" else helpers.FOE
    bundles = [owner]
    if path != "stock":
        foe = helpers._bundle(None, [], BOW_KIT, cl=17, actor_id=foe_id)
        if path == "compiled_native":
            sealed_native_attack(foe, "Native regression shot", attack_bonus=8)
        bundles.append(foe)
    combat = CombatService(root, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, foe_id], {ME: "team:a", foe_id: "team:b"},
        {ME: {"x": 3, "y": 6}, foe_id: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [b["actor_id"] for b in bundles], [foe_id],
        control_modes={ME: "MANUAL", foe_id: "MANUAL"}, match_seed="SKY-NET-ATTACK",
        display_name="Sky-Net attack regression", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)

    def loaded():
        return CombatService(root, tmp_path)._load_session(mid)

    def attack(source=None):
        session = loaded()
        engine = session.engine
        choices = [c for c in engine.legal_candidates() if c.target_ids == (ME,)
                   and engine.action_catalog[c.source_definition_id].resolution_kind
                   in ({"TYPED"} if path == "typed" else {"ATTACK", "MULTI_ATTACK"})
                   and (source is None or c.source_definition_id == source)]
        if path == "typed":
            choices = [c for c in choices if "gong_jian" in c.source_definition_id]
        assert choices, [(c.display_name, c.source_definition_id) for c in engine.legal_candidates()]
        chosen = choices[0]
        before = len(engine.events)
        settle(table, mid, chosen.candidate_id)
        session = loaded()
        rolls = [e for e in session.engine.events[before:] if e.event_type == "ATTACK_ROLLED"
                 and e.actor_id == foe_id and e.source_definition_id == chosen.source_definition_id]
        assert rolls
        assert session.mechanical.replay()["status"] == "PASS"
        return chosen.source_definition_id, [e.payload["modifier"] for e in rolls]

    turn(table, mid, foe_id)
    source, normal = attack()  # unaffected control creature, before any condition exists
    turn(table, mid, ME)
    engine = loaded().engine
    net = next(c for c in engine.legal_candidates() if SKY_NET in c.source_definition_id
               and c.destination and (c.destination.x, c.destination.y) == (4, 6))
    settle(table, mid, net.candidate_id)
    # The foe's turn starts in the zone and chooses Slow Down through the table prompt.
    while table.state(mid)["menu"]["actor_id"] != foe_id:
        settle(table, mid, table.state(mid)["menu"]["end_turn"],
               picks={"choice:needle.sky_net": "slow_down"})
    assert barrage_sky_net.SLOW in _conditions(loaded().engine.state.actors[foe_id])
    _, slowed = attack(source)
    assert slowed == [value - 2 for value in normal]
    turn(table, mid, ME)
    turn(table, mid, foe_id)
    assert barrage_sky_net.SLOW not in _conditions(loaded().engine.state.actors[foe_id])
    _, expired = attack(source)
    assert expired == normal


@pytest.mark.parametrize("slowed", [False, True])
def test_portable_runtime_attack_uses_the_same_penalty(monkeypatch, slowed):
    """The portable adapter's unindexed ATTACK reason also reaches the native seam."""
    from combat.character_runtime_adapter import CharacterCombatRuntimeEngine
    from combat.gate2_runtime_models import ActionIntent

    _answer(monkeypatch, "slow_down")
    engine = _fight(SKY_NET)
    _fire(engine)
    if slowed:
        _enter(engine)
    before = len(engine.rolls)
    CharacterCombatRuntimeEngine._resolve_character_attack(
        engine, _foe(engine), engine.state.actors[ME], source_id="test:portable.sky_net",
        attack_bonus=8, damage=None, fixed_damage=2, damage_type="BLUDGEONING", ranged=False,
        intent=ActionIntent(intent_id="portable-sky-net", decision_id="test", candidate_id="test",
                            state_version=engine.state.state_version, actor_id=FOE, target_ids=(ME,)))
    rolls = [r for r in engine.rolls[before:] if r.reason == "ATTACK:test:portable.sky_net"]
    assert len(rolls) == 1
    assert rolls[0].modifier == (6 if slowed else 8)


def test_native_roll_from_a_typed_effect_still_takes_the_penalty(monkeypatch):
    """A trap/ray can call the native resolver under a typed catalogue source."""
    _answer(monkeypatch, "slow_down")
    engine = _fight(SKY_NET)
    _fire(engine)
    _enter(engine)
    source = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.owner_id == ME and a.resolution_kind == "TYPED")
    before = len(engine.rolls)
    engine._resolve_attack_spec(_foe(engine), engine.state.actors[ME],
                               {"attack_bonus": 8, "reach_ft": 5, "damage": None}, None,
                               source_definition_id=source)
    rolls = [r for r in engine.rolls[before:] if r.reason == f"ATTACK:{source}:1"]
    assert len(rolls) == 1 and rolls[0].modifier == 6
