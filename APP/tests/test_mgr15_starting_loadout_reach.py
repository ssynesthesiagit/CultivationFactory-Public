"""A sealed starting loadout stows spare weapons; a free Draw keeps every legal option reachable.

Main's compiled-fighter contract (7cb6537f, commit on main 2026-10-20) seals one ranked
primary in hand and carries the spares. MGR-T15's saber classification must not narrow
that generic weapon path: a stowed weapon is still possessed, is offered as a free Draw
(no Action, no turn flag), and its attacks and thrown modes appear the moment it is drawn.
These guards name the reachability the legacy Factory fixtures assume when they attack a
spare without drawing it; those fixtures predate the sealed loadout and are unchanged.
"""
from combat.gate2_engine import Gate2Engine
from combat.gate2_runtime_content import AN
from combat.ext.saber_learning import saber_action
from combat.weapon_delivery import available_weapons

from tests.test_factory_combat_compiler import ACTOR, ROOT, _weapons_of
from tests.test_typed_executor import _intent


def _duel(bundle, seed):
    engine = Gate2Engine(ROOT, match_seed=seed, typed_bundles=(bundle,),
                         roster_setup={"primary_actor_ids": [ACTOR, AN],
                                       "team_by_actor": {ACTOR: "team:a", AN: "team:b"}})
    me, foe = engine.state.actors[ACTOR], engine.state.actors[AN]
    me.position = me.position.model_copy(update={"x": 3, "y": 6})
    foe.position = foe.position.model_copy(update={"x": 4, "y": 6})
    engine.state.current_actor_id = ACTOR
    return engine, me


def _names(engine):
    return {c.display_name for c in engine.legal_candidates() if c.actor_id == ACTOR}


def test_a_stowed_spare_is_reachable_with_the_free_draw():
    bundle, _ = _weapons_of(["tianxia.mortal.weapon.dao", "tianxia.mortal.weapon.bi_shou"],
                            paths=("tianxia.path.body_refining",))
    plan = bundle["carrying"]["starting_loadout"]
    assert len(plan["weapons"]) == 1  # main seals the ranked primary; the spare stays carried
    assert plan["weapons"][0].endswith(".weapon.dao")
    engine, me = _duel(bundle, "SPARE-DRAW")
    before = _names(engine)
    assert "Dao (Saber / Broadsword) attack" in before and "Draw Bi Shou (Dagger) (uses 1 hand; no Action)" in before
    assert "Bi Shou (Dagger) attack" not in before and "Bi Shou (Dagger) thrown" not in before
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates()
                                       if c.display_name.startswith("Draw Bi Shou (Dagger)"))))
    after = _names(engine)
    assert {"Bi Shou (Dagger) attack", "Bi Shou (Dagger) thrown"} <= after
    assert me.action_available  # drawing is free, exactly as the loadout note promises


def test_a_saber_primary_does_not_hide_a_generic_spare():
    bundle, rows = _weapons_of(["tianxia.mortal.weapon.dao", "tianxia.mortal.weapon.bi_shou"],
                               paths=("tianxia.path.body_refining",))
    engine, _ = _duel(bundle, "SABER-SPARE")
    dao = engine.action_catalog[rows["dao"]["source_definition_id"]]
    knife = engine.action_catalog[rows["bi_shou"]["source_definition_id"]]
    assert saber_action(dao) is True and saber_action(knife) is False  # classification, not availability
    assert set(available_weapons(engine, engine.state.actors[ACTOR])) >= {dao.source_definition_id, knife.source_definition_id}
    engine.execute_intent(_intent(next(c for c in engine.legal_candidates()
                                       if c.display_name.startswith("Draw Bi Shou (Dagger)"))))
    names = _names(engine)
    assert any(n.startswith("Dao (Saber / Broadsword) attack") for n in names)
    assert any(n.startswith("Bi Shou (Dagger) attack") for n in names)
