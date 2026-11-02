"""SQUAREPICK1 whole-record: Cultivate Blossom targets one creature, object, or unoccupied 5-foot space.

A willing object takes the Blossom automatically (no Cultivation Attack, no creature condition).
"""
from tests.test_a2_flowers import scene, ME
from tests.hunt12_support import reload

CRATE = 'object:squarepick1.crate'


def _crate(engine):
    from combat.gate2_runtime_models import RuntimeObjectState, Position
    engine._update_object(RuntimeObjectState(object_id=CRATE, object_kind='crate',
        position=Position(x=7, y=6), ac=10, current_hp=20, maximum_hp=20, unattended=False, flammable=False,
        component={'name': 'Crate', 'blocks': False}), 'test:squarepick1')


def test_cultivate_target_finds_object_on_its_square(tmp_path):
    from combat.gate2_runtime_models import Position
    from combat.ext.blossom import _object_at
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM'])
    engine = reload(tmp_path, mid)
    _crate(engine)
    assert _object_at(engine, Position(x=7, y=6)).object_id == CRATE
    assert _object_at(engine, Position(x=9, y=9)) is None


def test_cultivate_candidate_list_includes_willing_object_square(tmp_path):
    """SQUAREPICK1: the Cultivate candidate builder offers a willing object's square, even one that is blocked terrain.

    The crate square is made terrain-blocked, so only the object branch of blossom_candidates can offer it.
    Without that branch the square is refused. A square far outside the grid is refused.
    """
    from types import SimpleNamespace
    from combat.gate2_runtime_models import Position
    from combat.ext.blossom import blossom_candidates
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM'])
    engine = reload(tmp_path, mid)
    _crate(engine)
    owner = engine.state.actors[ME]
    action = next(a for a in engine.action_catalog.values()
                  if a.owner_id == ME and a.display_name == 'Cultivate Blossom')
    crate_cell = Position(x=7, y=6)
    engine.grid.blocked.add((crate_cell.x, crate_cell.y))
    offered = blossom_candidates(engine, owner, SimpleNamespace(destination=crate_cell), action)
    assert offered is True, 'a willing object square must be offered by the Cultivate candidate list'
    refused = blossom_candidates(engine, owner, SimpleNamespace(destination=Position(x=999, y=999)), action)
    assert refused is False, 'a square outside the grid is neither an object, a creature nor free space'


def test_cultivate_on_willing_object_plants_and_blooms_it(tmp_path):
    """SQUAREPICK1: _plant_and_bloom on an object square plants and blooms it.

    This calls the planting helper directly with the object as the bearer. It does not exercise
    cultivate() end to end; the table path is covered by the placement tests in test_squarepick1.py.
    The object is the bearer, so no Blossom condition lands on the owner.
    """
    from combat.gate2_runtime_models import Position
    from combat.ext import placed
    from combat.ext.blossom import _object_at, _kit, _plant_and_bloom
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM'])
    engine = reload(tmp_path, mid)
    _crate(engine)
    owner = engine.state.actors[ME]
    kit = _kit(engine, owner)
    assert kit is not None
    cell = Position(x=7, y=6)
    # Plant and bloom the object square — the object is the bearer, so no Blossom condition
    # lands on the owner.
    _plant_and_bloom(engine, owner, kit, 'action:test.squarepick1', cell, None, True, False, obj=_object_at(engine, cell))
    zones = [z for z in placed.at(engine, cell, 'blossom') if z.owner_id == owner.entity_id]
    assert len(zones) == 1, 'one blossom zone must exist on the object square'
    data = placed.data(zones[0])
    assert data.get('state') == 'dormant' and data.get('bearer') == CRATE and data.get('willing') is True
    # No creature carries it: the object is the bearer, so no Blossom condition lands on the owner.
    assert not any('blossom' in str(c.condition_id).lower() and (c.data or {}).get('zone_id') == zones[0].zone_id
                   for c in owner.conditions.values())


def test_trigger_text_handles_non_blossom_extension_choice(tmp_path):
    """SQUAREPICK1: an extension choice from another ability, with no 'moment' key, keeps its action text.

    Its trigger carries a prompt, so the early return is reached. The early return must not read a missing
    'moment' (the placement reading is only for a reaction_source CHOICE), so the result is the triggering
    action's text, never an empty string.
    """
    from combat.decision_text import trigger_text
    prompt = {"reactor": "Mei", "reaction": "Some Other Ability", "trigger": "some_other_ability"}
    context = {"extension_choice": True, "reactor_id": "actor:mei",
               "choice_trigger": {"actor_id": "actor:mei", "action_name": "Some Other Ability", "prompt": "x"}}
    result = trigger_text(context, prompt, {"actor:mei": "Mei"}, {})
    assert result.strip(), 'a non-placement extension choice must keep its action text, not an empty string'


def test_trigger_text_placement_choice_reads_its_moment(tmp_path):
    """SQUAREPICK1: a placement square choice (reaction_source CHOICE) for its own actor reads its moment text."""
    from combat.decision_text import trigger_text
    from combat.placement_menu import CHOICE
    prompt = {"reactor": "Mei", "moment": "Choose where the blossom blooms.", "reaction": "Cultivate Blossom"}
    context = {"extension_choice": True, "reactor_id": "actor:mei", "reaction_source_id": CHOICE,
               "choice_trigger": {"actor_id": "actor:mei", "action_name": "Cultivate Blossom", "prompt": "x"}}
    assert trigger_text(context, prompt, {"actor:mei": "Mei"}, {}) == "Choose where the blossom blooms."


def test_trigger_text_placement_marker_keeps_action_text_off_the_reactor_path(tmp_path):
    """SQUAREPICK1: the placement reading needs the reactor's own choice with no roll; otherwise the old path stays.

    The early return reads the moment text only when the actor is the reactor and the trigger has no roll_kind.
    With a roll, or with another creature as the actor, the placement marker must not change the text.
    """
    from combat.decision_text import trigger_text
    from combat.placement_menu import CHOICE
    prompt = {"reactor": "Mei", "moment": "Choose where the blossom blooms.", "reaction": "Cultivate Blossom"}
    actors = {"actor:mei": "Mei", "actor:foe": "Foe"}
    rolled = {"extension_choice": True, "reactor_id": "actor:mei", "reaction_source_id": CHOICE,
              "choice_trigger": {"actor_id": "actor:mei", "action_name": "Cultivate Blossom", "prompt": "x",
                                 "roll_kind": "attack"}}
    not_reactor = {"extension_choice": True, "reactor_id": "actor:mei", "reaction_source_id": CHOICE,
                   "choice_trigger": {"actor_id": "actor:foe", "action_name": "Cultivate Blossom", "prompt": "x"}}
    assert trigger_text(rolled, prompt, actors, {}) != "Choose where the blossom blooms."
    assert trigger_text(not_reactor, prompt, actors, {}) != "Choose where the blossom blooms."


def test_trigger_text_other_extension_choice_keeps_its_triggering_action(tmp_path):
    """SQUAREPICK1: the placement early return must not change other extension choices by the same reactor.

    Without the placement marker, a choice the reactor makes about its own action keeps the action-based text,
    not the choice's moment text.
    """
    from combat.decision_text import trigger_text
    prompt = {"reactor": "Mei", "moment": "Choose one result for Lightning Lash.", "reaction": "Lightning Lash"}
    context = {"extension_choice": True, "reactor_id": "actor:mei",
               "choice_trigger": {"actor_id": "actor:mei", "action_name": "Lightning Lash", "prompt": "x"}}
    result = trigger_text(context, prompt, {"actor:mei": "Mei", "actor:foe": "Foe"}, {})
    assert result != "Choose one result for Lightning Lash.", result
    assert "Mei" in result, result
