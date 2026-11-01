"""SOLFSOL118: printed sight requirements through accepted table actions."""
import pytest

from combat import ext, senses
from combat.gate2_runtime_models import Position
from combat.target_knowledge import can_see
from tests.test_cai_clan_subpath import _fight, _loaded, _use
from tests.test_tabletop_hunt6 import LEFT, ALLY, RIGHT, HOLD, act, on_hold


def _conceal(engine, actor_id, condition="hidden"):
    engine._apply_condition(engine.state.actors[actor_id], f"condition:typed.{condition}",
                            "test:solfsol118.conceal", actor_id, expires_on="UNTIL_REMOVED")


def _saber_table(tmp_path, monkeypatch, court):
    combat, table, mid = _fight(tmp_path, 18 if court else 15)
    name = "Judgment Saber"
    if court:
        _use(table, mid, "Court Beneath the Colorless Star", [LEFT])
        name += " — Colorless Court"
        with monkeypatch.context() as patch:
            on_hold(patch, lambda e: setattr(e.state.actors[RIGHT], "position", Position(x=6, y=4)))
            assert act(table, mid, HOLD)["status"] == "COMMITTED"
    assert any(g["label"] == name for g in table.state(mid)["menu"]["actions"])
    return combat, table, mid, name


@pytest.mark.parametrize("court", [False, True])
@pytest.mark.parametrize("condition", ["hidden", "invisible"])
def test_saber_table_offers_unseen_remembered_square_under_owner_rule(monkeypatch, tmp_path, court, condition):
    combat, table, mid, name = _saber_table(tmp_path, monkeypatch, court)
    with monkeypatch.context() as patch:
        on_hold(patch, lambda e: _conceal(e, RIGHT, condition))
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = _loaded(combat, mid)
    engine = loaded.engine
    assert RIGHT in engine.state.observations[engine.state.actors[LEFT].team_id]
    assert not can_see(engine, engine.state.actors[LEFT], engine.state.actors[RIGHT])
    choices = [option for group in table.state(mid)['menu']['actions'] if group['label'] == name
               for option in group['options'] if RIGHT in option.get('target_ids', [])]
    assert choices and all(option['destination'] == engine.state.actors[RIGHT].position.model_dump(mode='json')
                           for option in choices)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("blinded,sense,x,visible", [
    (False, None, 4, True),
    (True, None, 4, False),
    (True, "blindsight", 4, True),
    (True, "blindsight", 5, False),
    (True, "tremorsense", 4, False),
    (True, "spiritual_sense", 4, False),
])
def test_white_sun_table_requires_visible_point(monkeypatch, tmp_path, blinded, sense, x, visible):
    combat, table, mid = _fight(tmp_path)
    destination = {"x": x, "y": 4}

    def setup(engine):
        if blinded:
            _conceal(engine, LEFT, "blinded")
        if sense:
            engine._apply_condition(engine.state.actors[LEFT], senses.SENSE, "test:solfsol118r2.sense", LEFT,
                                    expires_on="UNTIL_REMOVED", data={"sense": sense, "range_ft": 5})

    with monkeypatch.context() as patch:
        on_hold(patch, setup)
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    before = _loaded(combat, mid).engine
    qi = before.state.actors[LEFT].resources["resource:core.qi"]
    start = before.state.event_sequence
    options = [option for group in table.state(mid)["menu"]["actions"]
               if group["label"] == "White Sun Judgment" for option in group["options"]]
    assert any(option.get("destination") == destination for option in options) is visible
    if blinded and sense != "blindsight":
        assert options == []
    if blinded and sense == "blindsight":
        assert any(option.get("destination") == {"x": 4, "y": 4} for option in options)
        assert not any(option.get("destination") == {"x": 5, "y": 4} for option in options)
    if visible:
        _use(table, mid, "White Sun Judgment", destination=destination)
    else:
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    loaded = _loaded(combat, mid)
    events = [e for e in loaded.engine.events if e.sequence > start]
    assert loaded.engine.state.actors[LEFT].resources["resource:core.qi"] == qi - (4 if visible else 0)
    assert (loaded.engine.state.actors[RIGHT].current_hp < 300) is visible
    assert any(e.event_type == "SAVE_ROLLED" and "white_sun_judgment" in e.source_definition_id
               for e in events) is visible
    assert any(c.condition_id.endswith("reaction_denied")
               for c in loaded.engine.state.actors[RIGHT].conditions.values()) is visible
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("court", [False, True])
def test_saber_table_lost_sight_after_selection_uses_attack_roll(monkeypatch, tmp_path, court):
    combat, table, mid, name = _saber_table(tmp_path, monkeypatch, court)
    before = _loaded(combat, mid).engine
    start = before.state.event_sequence
    qi = before.state.actors[LEFT].resources["resource:core.qi"]

    def lose_sight(engine, attacker, defender, intent, context):
        if attacker.entity_id == LEFT and defender.entity_id == RIGHT:
            _conceal(engine, RIGHT)
            from tests.h1_support import script
            script(engine, [1, 1])  # Miss the real attack d20 with Disadvantage.
        return None

    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "before_attack", [*ext._HOOKS.get("before_attack", []), lose_sight])
    _use(table, mid, name, target=RIGHT)
    loaded = _loaded(combat, mid)
    events = [e for e in loaded.engine.events if e.sequence > start]
    assert not any('miss_chance_percent' in e.payload for e in events)
    assert any(e.event_type == 'ATTACK_ROLLED' for e in events)
    assert not any(e.event_type == 'DAMAGE_COMMITTED' for e in events)
    assert loaded.engine.state.actors[RIGHT].current_hp == 300
    assert not any(c.condition_id.endswith("cai_censure")
                   for c in loaded.engine.state.actors[RIGHT].conditions.values())
    assert loaded.engine.state.actors[LEFT].resources["resource:core.qi"] == qi - 1
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("court", [False, True])
@pytest.mark.parametrize("sense,visible", [(None, False), ("tremorsense", False), ("blindsight", True)])
def test_investment_table_choices_require_sight_of_hidden_ally(monkeypatch, tmp_path, court, sense, visible):
    combat, table, mid = _fight(tmp_path, 18 if court else 15)

    def setup(engine):
        _conceal(engine, ALLY)
        _conceal(engine, LEFT)  # The explicit self exception must remain available.
        if sense:
            engine._apply_condition(engine.state.actors[LEFT], senses.SENSE, "test:solfsol118.sense", LEFT,
                                    expires_on="UNTIL_REMOVED", data={"sense": sense, "range_ft": 30})

    with monkeypatch.context() as patch:
        on_hold(patch, setup)
        assert act(table, mid, HOLD)["status"] == "COMMITTED"
    name = "Court Beneath the Colorless Star" if court else "Empyreal Layer"
    prompts, _ = _use(table, mid, name, [ALLY] if visible else [LEFT])
    options = {o["id"] for o in prompts[0]["choice"]["options"]}
    assert options == ({LEFT, ALLY} if visible else {LEFT})
    loaded = _loaded(combat, mid)
    recipients = {a.entity_id for a in loaded.engine.state.actors.values()
                  if any(c.condition_id.endswith("cai_empyreal_layer") for c in a.conditions.values())}
    assert recipients == ({ALLY} if visible else {LEFT})
    assert loaded.mechanical.replay()["status"] == "PASS"
