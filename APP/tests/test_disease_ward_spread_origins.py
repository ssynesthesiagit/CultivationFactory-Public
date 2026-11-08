"""Native reaction and summon paths retain token ownership but use the spreading creature."""
import pytest

from combat.ext import disease, rider_choices
from combat.gate2_runtime_models import Position
from tests.test_disease_quarantine_ward import (
    OWNER, SELECTED, UNSELECTED, OUTSIDE, _fight, _raise_ward, _fresh,
)


@pytest.mark.parametrize("event", ["DAMAGE_COMMITTED", "ENTITY_DEFEATED", "token_effect"])
@pytest.mark.parametrize("allow", [False, True])
def test_living_plague_crosses_from_summon_not_summoner(tmp_path, monkeypatch, event, allow):
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    engine = _fresh(combat, mid).engine
    summoner = engine.state.actors[OUTSIDE]
    plague = engine.state.actors[SELECTED]
    target = engine.state.actors[UNSELECTED]
    plague.summon = {"group": "living_plague", "owner": OUTSIDE}
    plague.position = Position(x=7, y=5)
    target.position = Position(x=8, y=5)
    target.team_id = "team:healthy"
    target.saving_throws["CON"] = -100
    prompts = []

    def choose(_engine, owner, _key, name, options, **kwargs):
        assert owner.entity_id == OWNER
        assert name == "Quarantine Ward"
        prompts.append(kwargs["subject"].entity_id)
        return ["allow" if allow else "contain"]

    monkeypatch.setattr(rider_choices, "pick", choose)
    if event == "token_effect":
        from combat.typed_executor import Context
        action = engine.action_catalog[plague.action_ids[0]]
        disease.token_effect(Context(engine, plague, action, None, {}, [target], target, {}), {"count": 1})
    else:
        disease.living_plague(engine, event, {
            "actor_id": SELECTED, "target_ids": [UNSELECTED], "payload": {"hp_damage": 1}})
    assert prompts == [UNSELECTED]
    assert disease.tokens(engine, summoner, target) == int(allow)
    assert disease.tokens(engine, plague, target) == 0


def test_spreading_infection_passes_infected_bearer_as_origin(tmp_path, monkeypatch):
    combat, table, mid = _fight(tmp_path)
    _raise_ward(combat, table, mid)
    engine = _fresh(combat, mid).engine
    owner, bearer = engine.state.actors[OUTSIDE], engine.state.actors[SELECTED]
    engine.typed_passive_rows[OUTSIDE].append({"feature_id": disease.SPREADING})
    owner.reaction_available = True
    from combat.ext import stacking_marks
    stacking_marks.add(engine, owner, bearer, disease.TOKEN, 1, "test:seed")
    from combat import typed_executor
    captured = []

    def run(ctx, effects):
        captured.append(effects[0]["on_fail"][0])

    monkeypatch.setattr(typed_executor, "run_effects", run)
    monkeypatch.setattr(rider_choices, "pick", lambda *args, **kwargs: [UNSELECTED])
    disease._spreading(engine, bearer)
    assert captured == [{"type": "disease_tokens", "applies_to": "target", "count": 1,
                         "spread_origin_id": SELECTED}]
