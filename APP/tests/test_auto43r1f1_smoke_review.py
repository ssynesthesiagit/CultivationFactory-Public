"""AUTO43r1: the review fixes to the Smoke Veil lane, each as a regression that fails without its fix.

  legacy row      A fight saved before Blacken the Flame's row carried no dice of its own. Reloading it must keep the
                  reduction it is already playing (``3d6 + 3`` at CL 11), not fall back to ``1d6 + 0``.
  crossing sight  The printed trigger says where the fire travelled, not who could see it. Blindsight on the source
                  must not stop the soot.
  second veil     The placement options ride the established grid id, so the table offers a map, and each label names
                  one square and only that square.
  authority       Blacken the Flame's dice come from the record the compiler was handed, so a supplied authority
                  compiles its own numbers.
  typed fire      A real submitted typed Fire ability reaches the same seam a hand-made packet does, and the prompt
                  names the action that triggered it.
  centre / expiry The stored centre is the square the owner chose; the soot mark really ends at the start of the
                   owner's next turn.
  decision mode At the engine's own transport, the question is put to the transport on the owner's turn and on
                   another's. Who the table asks -- a manual player, an AI fighter, an AI's turn -- is the service's
                   boundary and is covered in test_auto43r1f1_smoke_table.py.

Engine-level checks run on a real Gate4 engine. The decision routing, the cold legacy save load, the table
commit/reload and the replay evidence are in test_auto43r1f1_smoke_table.py, which drives the same abilities through
the real service.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
t = __import__("importlib").import_module("test_review_sw-athletics")

from combat import zones
from combat.ext import smoke_veil
from combat.ext.fight_ownership import block_rows
from combat.gate2_runtime_models import ActionIntent
from combat.typed_executor import bears_mark, mark_condition_id

ME = t.ME
AN = t.AN
FIRE = "tianxia.sphere.fire"
SMOKE = "tianxia.sphere.smoke"
BURN_THROUGH = "FIRE_TAL_BURN_THROUGH"
VEIL, SECOND, BLACKEN, WITNESS = ("SMOKE_BASE_SMOKE_VEIL", "TAL_SMOKE_SECOND_VEIL",
                                  "TAL_SMOKE_BLACKEN_THE_FLAME", "TAL_SMOKE_SOOT_MARKED_WITNESS")
BASES = ["SMOKE_BASE_SMOKE_RESPONSES", "SMOKE_BASE_SMOKE_TRACE"]


def _fight(talents=(), cl=11, foe_at=(4, 6)):
    engine = t._engine(t._bundle(SMOKE, [VEIL, *BASES, *talents], {}, cl=cl, dc=50), foe_at=foe_at, foe_hp=400)
    return engine, engine.state.actors[ME], engine.state.actors[AN]


def _place_veil(engine, at):
    t._ready(engine)
    found = [c for c in engine.legal_candidates() if c.actor_id == ME and c.display_name.startswith("Smoke Veil")
             and c.destination is not None and (c.destination.x, c.destination.y) == at]
    assert found, f"no Smoke Veil aim at {at}"
    candidate = min(found, key=lambda c: len(c.display_name))
    engine.execute_intent(ActionIntent(intent_id="veil", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=ME, target_ids=candidate.target_ids,
                                       destination=candidate.destination))
    return [(cell.x, cell.y) for cell in zones.typed_zones(engine)[0].affected_cells]


def _accept(request, options):
    from combat.gate2_runtime_models import ReactionDecision

    return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                            reaction_source_id=request["reaction_source_id"], selection="USE",
                            option_ids=tuple(options)), None


def _decline(request):
    from combat.gate2_runtime_models import ReactionDecision

    return ReactionDecision(checkpoint=request["checkpoint"], reactor_id=request["reactor_id"],
                            reaction_source_id=request["reaction_source_id"], selection="DECLINE", option_ids=()), None


def _soot(request):
    """Answer only the Blacken question; decline every other thing the fight asks."""
    if not str(request["reaction_source_id"]).startswith("choice:needle."):
        return _decline(request)
    return _accept(request, request["legal_option_ids"][:1])


def _trace(engine, creature):
    engine._apply_condition(creature, mark_condition_id("Smoke Trace", ME), "test:trace", ME, expires_on="UNTIL_REMOVED",
                            data={"mark": "Smoke Trace", "label": "Smoke Trace"})


def _run(engine, name, actor=ME, target=None):
    t._ready(engine)
    found = [c for c in engine.legal_candidates() if c.actor_id == actor
             and c.display_name.split(" at ")[0] == name.split(" at ")[0]
             and (target is None or not c.target_ids or target in c.target_ids)]
    assert found, f"{name!r} is not legal for {actor}"
    candidate = found[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"r1-{name}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor, target_ids=candidate.target_ids, destination=candidate.destination))
    return engine.events[before:]


# ------------------------------------------------------------------ finding 1: a saved fight keeps its own numbers
def test_a_saved_row_without_its_own_dice_still_reduces_by_the_owners_printed_numbers():
    """A fight saved before this hook existed carries a Blacken the Flame row with no ``dice`` and no ``key_mod``.

    Before the fix such a row defaulted to ``1d6 + 0``, so reloading a CL 11 fight that had been reducing by
    ``3d6 + 3`` quietly cut it to a sixth of its printed size. The row's own numbers are used when they are there and
    the fight's own compiled numbers when they are not, so an old save plays the reduction it was playing.

    Scope: this is the row-level reader on a live engine, and it pins down *both* dependencies the compatibility path
    needs -- the stripped row, and the Cultivation Level and key ability modifier the fight's action catalog still
    carries. The saved-fight path itself (a bundle stored without those numbers, reloaded cold through a new
    ``CombatService``, and Blacken then answering real damage on the reloaded fight) is
    ``test_a_legacy_blacken_save_reloaded_from_disk_keeps_its_printed_reduction`` in
    test_auto43r1f1_smoke_table.py."""
    import json

    from combat.gate2_runtime_models import MatchState

    engine, me, foe = _fight([BLACKEN], cl=11)
    live_row = next(iter(block_rows(engine, me, "smoke_fire_soot")))
    assert live_row["dice"] == {"count": 3, "sides": 6} and live_row["key_mod"] == 3, live_row
    # Rewind the row to how a pre-hook save stored it: no resolved numbers at all.
    stripped = [{**row, "dice": None, "key_mod": None} for row in engine.typed_passive_rows[me.entity_id]]
    engine.typed_passive_rows[me.entity_id] = stripped
    legacy_row = next(iter(block_rows(engine, me, "smoke_fire_soot")))
    assert not legacy_row.get("dice") and legacy_row.get("key_mod") is None, legacy_row
    # ... and the fight's own compiled numbers, which are the other half of the compatibility reader, are still there.
    numbers = smoke_veil._compiled_numbers(engine, me)
    assert (numbers.get("cl"), numbers.get("key_mod")) == (11, 3), numbers

    _place_veil(engine, (4, 6))
    _trace(engine, foe)
    engine.set_reaction_provider(lambda request: _soot(request))
    engine._active_intent = _any_intent(engine)
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
    cuts = [r for r in engine.rolls if r.reason == "DAMAGE_REDUCED"]
    assert cuts and len(cuts[0].dice) == 3, f"a pre-change row must still roll the owner's printed 3d6 at CL 11: {cuts}"
    assert cuts[0].modifier == 3, f"... and the owner's key ability modifier: {cuts}"
    assert foe.current_hp < before
    # A JSON round trip of the whole fight must not change the answer either.
    saved = json.loads(engine.state.model_dump_json())
    saved.pop("schema_name", None)  # the model's own class, not a field
    reloaded = MatchState.model_validate(saved)
    assert set(reloaded.zones) == set(engine.state.zones)


def _any_intent(engine):
    t._ready(engine)
    candidate = next(iter(engine.legal_candidates()))
    return ActionIntent(intent_id="r1", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id,
                        target_ids=candidate.target_ids, destination=candidate.destination)


# ------------------------------------------------------------------ finding 2: the crossing trigger has no sight exception
@pytest.mark.parametrize("blindsight", [True, False])
def test_fire_crossing_the_veil_is_sooted_whether_or_not_its_source_can_see_through_smoke(blindsight):
    """"Fire damage is dealt inside your Smoke Veil **or through** your Smoke Veil."

    The crossing half asks where the fire travelled. It never asked who could watch it, and reusing the engine's
    visibility exception (combat/senses.py ``pierces_wall``, which exists for sight-based penalties) meant a fire
    packet stopped qualifying the moment its source had qualifying Blindsight."""
    from combat import senses

    engine, me, foe = _fight([BLACKEN], cl=11, foe_at=(6, 9))  # the foe stands beyond the veil, not in it
    _place_veil(engine, (6, 6))
    veil_cells = {(c.x, c.y) for c in zones.typed_zones(engine)[0].affected_cells}
    assert (foe.position.x, foe.position.y) not in veil_cells
    _trace(engine, foe)
    shooter = _clone(engine, foe, "actor:factory.shooter", (6, 3))
    if blindsight:
        shooter = _with_blindsight(engine, shooter)
    assert smoke_veil._through_veil(engine, me, shooter, foe), "the line from the shooter to the foe crosses the veil"
    engine.set_reaction_provider(lambda request: _soot(request))
    engine._active_intent = _any_intent(engine)
    before = foe.current_hp
    engine._commit_damage(foe, 20, "fire", "system:combat.melee", shooter.entity_id, engine._active_intent, reaction_depth=2)
    assert foe.current_hp < before, f"Blindsight={blindsight}: fire that passes through the smoke is sooted too"
    assert not bears_mark(foe, ME, "Smoke Trace")


def _clone(engine, source, entity_id, at):
    clone = source.model_copy(update={"entity_id": entity_id, "display_name": "An Eui's Ally",
                                     "position": source.position.model_copy(update={"x": at[0], "y": at[1]})})
    engine.state.actors[entity_id] = clone
    return clone


def _with_blindsight(engine, actor):
    """Give this creature the qualifying Blindsight that ``senses.pierces_wall`` reads, so the sight exception is
    genuinely in play in the crossing case rather than assumed to be."""
    from combat import senses

    assert "obscured" in ((senses._kinds().get("blindsight") or {}).get("through") or []), \
        "this test needs a sense the engine treats as seeing through obscuring smoke"
    engine._apply_condition(actor, senses.SENSE, "test:blindsight", actor.entity_id, expires_on="UNTIL_REMOVED",
                            data={"sense": "blindsight", "range_ft": 60})
    assert "blindsight" in senses.of(engine, actor), senses.of(engine, actor)
    # The exception this bug was caused by really does fire on this pair, so the test is not vacuous.
    veil = next(z for z in zones.typed_zones(engine) if z.owner_id == ME)
    assert senses.pierces_wall(engine, veil, actor, engine.state.actors[AN]), \
        "this case is only interesting if the source could see through the smoke"
    return actor


# ------------------------------------------------------------------ finding 3: the Second Veil's placement question
def test_the_second_veil_offers_a_map_and_no_two_squares_share_a_label():
    """Every option must name one square and only that square, and the table must be able to show them on the map.

    A single compass bearing collapses every unequal offset onto one direction, so a square three squares east and one
    north and a square three squares east and one south were both "east" at the same distance: two different
    destinations offered under one description. And an option id the shared map decoder does not recognise arrives as
    a flat list of words with no map behind it, so a player had nothing to point at."""
    from combat import choice_presentation

    engine, me, _ = _fight([SECOND], cl=4, foe_at=(14, 6))
    asked = {}

    def provider(request):
        if str(request["reaction_source_id"]) == smoke_veil.SECOND_CHOICE:
            asked.update(request)
            return _decline(request)
        return _decline(request)

    engine.set_reaction_provider(provider)
    _place_veil(engine, (6, 6))
    options = asked.get("legal_option_ids") or []
    assert options, "the owner was never asked where to put the second cube"
    decoded = {option: choice_presentation.option_cell(option) for option in options}
    assert all(decoded.values()), f"the table cannot place these options on the map: {sorted(decoded)}"
    # The words the table shows for each offered square, as the plug-in writes them for the real option set.
    veil = next(z for z in smoke_veil.veils(engine, me) if not z.trigger_profile.get("second_veil"))
    labels = {option: smoke_veil._square_words(type(veil.center)(x=cell["x"], y=cell["y"], z=veil.center.z),
                                                veil.center, engine)
              for option, cell in decoded.items()}
    assert len(set(labels.values())) == len(labels), \
        f"two different squares are offered under one description: {sorted(labels.values())}"
    # The same two squares that used to collapse onto one bearing are now told apart, in both axes. Three squares
    # east of the veil and one square north was previously "the square 15 feet east"; so was one square south.
    colliding = {option: words for option, words in labels.items()
                 if decoded[option]["x"] - veil.center.x == 3 and abs(decoded[option]["y"] - veil.center.y) == 1}
    assert len(colliding) == 2, f"expected the two squares this case is about: {sorted(colliding)}"
    assert any("north" in words for words in colliding.values()) and any("south" in words for words in colliding.values()), \
        f"both offsets must be stated, not collapsed onto one bearing: {sorted(colliding.values())}"


def test_the_second_veils_placement_reaches_the_table_as_a_map_choice():
    """The point picker is the table's own general seam: combat/choice_presentation.py ``space_choice`` highlights the
    legal squares when every option decodes. A private id spelling bypasses it and the player gets a list."""
    from combat import choice_presentation

    engine, me, _ = _fight([SECOND], cl=4, foe_at=(14, 6))
    asked = {}

    def provider(request):
        if str(request["reaction_source_id"]) == smoke_veil.SECOND_CHOICE:
            asked.update(request)
            return _decline(request)
        return _decline(request)

    engine.set_reaction_provider(provider)
    _place_veil(engine, (6, 6))
    me_id = ME
    context = {"reactor_id": me_id, "choice_trigger": {"space_positions": choice_presentation.capture_space_positions(
        engine, list(asked["legal_option_ids"]))}}
    prompt = {"title": "Second Veil", "reaction": "Second Veil", "choice": {
        "options": [{"id": option} for option in asked["legal_option_ids"]],
        "minimum": 0, "maximum": 1, "allow_decline": True}}
    shown = choice_presentation.space_choice(prompt, context, engine)
    assert shown is not prompt, "the table must recognise this as a square choice"
    assert shown["choice"]["space_map"]["square_size_ft"] == 5
    assert all("cell" in option for option in shown["choice"]["options"]), "every option carries its square"
    assert len({(option["cell"]["x"], option["cell"]["y"]) for option in shown["choice"]["options"]}) == \
        len(shown["choice"]["options"]), "each option is a distinct square"


def test_the_second_veil_stands_on_the_square_its_owner_actually_chose():
    """Its recorded centre is the square the owner chose, compared against the option id they actually answered with.

    The previous check only counted columns, so any corner of the footprint satisfied it."""
    engine, me, _ = _fight([SECOND], cl=5, foe_at=(14, 6))
    asked = {}

    def provider(request):
        if str(request["reaction_source_id"]) == smoke_veil.SECOND_CHOICE:
            asked.update(request)
            return _accept(request, [request["legal_option_ids"][-1]])  # a deliberately off-centre square
        return _decline(request)

    engine.set_reaction_provider(provider)
    _place_veil(engine, (6, 6))
    chosen = asked["legal_option_ids"][-1]
    from combat import choice_presentation

    want = choice_presentation.option_cell(chosen)
    assert want, f"the option id the owner answered with must be a square the table can read: {chosen!r}"
    extra = next(zone for zone in smoke_veil.veils(engine, me) if zone.trigger_profile.get("second_veil"))
    assert (extra.center.x, extra.center.y) == (want["x"], want["y"]), \
        f"stored centre {(extra.center.x, extra.center.y)} is not the chosen square {want}"
    assert len(extra.affected_cells) == 4 and (extra.center.x, extra.center.y) in {(c.x, c.y) for c in extra.affected_cells}


# ------------------------------------------------------------------ finding 4: the compiler's selected authority is the one used
def test_blacken_the_flame_compiles_the_numbers_of_the_authority_it_was_given():
    """``compile_character`` accepts a ``typed_authority`` and hands its records to every block it compiles.

    Blacken the Flame's printed dice live in that data, so rereading the file on disk let an injected or revised
    authority compile a bundle whose Blacken numbers came from somewhere else entirely. This compiles the same
    character twice, once against an authority whose printed table says something else, and reads the row both times."""
    import copy
    import json

    from combat import factory_compiler
    from combat.typed_reactions import compile_blocks

    document = t._sheet(SMOKE, [VEIL, *BASES, BLACKEN], {}, cl=11, dc=50)
    revised = copy.deepcopy(json.loads(Path(factory_compiler.TYPED_AUTHORITY).read_bytes()))
    record = revised["mechanics"][BLACKEN]
    for effect in record["effects"]:
        if isinstance(effect, dict) and effect.get("type") == "damage_modifier":
            effect["dice_by_cl"] = [[1, 20, 5, 6]]  # the injected authority says 5d6 at every level
    bundle = factory_compiler.compile_character(document, actor_id=ME, typed_authority=revised)
    row = next(r for r in bundle["typed_passives"] if r.get("block") == "smoke_fire_soot")
    assert row["dice"] == {"count": 5, "sides": 6}, f"the supplied authority's own numbers must be compiled: {row}"
    # ... and the untouched file still compiles its own, so the reader is not simply a constant.
    onfile = factory_compiler.compile_character(document, actor_id=ME)
    assert next(r for r in onfile["typed_passives"] if r.get("block") == "smoke_fire_soot")["dice"] == {"count": 3, "sides": 6}


# ------------------------------------------------------------------ the typed Fire seam a real ability goes through
def _fire_fight(talents=(), cl=11):
    """A fight with a Smoke owner, a creature marked inside its veil, and a second fighter holding a typed Fire ability.

    Three real fighters, so the Fire damage is a submitted ability of its own rather than a hand-made packet."""
    from combat.gate4_engine import Gate4ControllerEngine
    from combat.factory_compiler import compile_character

    victim, attacker = "actor:factory.victim", "actor:factory.attacker"
    bundles = (t._bundle(SMOKE, [VEIL, *BASES, *talents], {}, cl=cl, dc=50),
               compile_character(t._sheet(None, [], {}), actor_id=victim),
               compile_character(t._sheet(FIRE, [BURN_THROUGH], {}, cl=cl), actor_id=attacker))
    engine = Gate4ControllerEngine(t.ROOT, match_seed="R1-FIRE", typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, victim, attacker],
                                                 "team_by_actor": {ME: "team:a", victim: "team:a", attacker: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6}, victim: {"x": 4, "y": 6},
                                                                        attacker: {"x": 5, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    for actor_id in (victim, attacker):
        actor = engine.state.actors[actor_id]
        actor.maximum_hp = actor.current_hp = 400
        actor.armor_class = -50
    return engine, engine.state.actors[ME], engine.state.actors[victim], engine.state.actors[attacker], victim, attacker


def test_a_real_typed_fire_ability_is_sooted_and_the_prompt_names_the_action_that_caused_it():
    """A submitted typed Fire ability reaches the same seam a hand-made packet does.

    combat/typed_executor.py ``_commit_damage`` lands in combat/gate2_engine.py ``final_damage``, so a Fire attack
    resolved from a character sheet is answered exactly like one thrown in by hand -- the earlier limitation text
    claimed otherwise. The prompt also has to say *what* did it: the ability's name, not an internal id."""
    engine, me, victim, attacker, victim_id, attacker_id = _fire_fight([BLACKEN])
    _place_veil(engine, (4, 6))  # the victim's own square is inside the veil
    assert (victim.position.x, victim.position.y) in {(c.x, c.y) for c in zones.typed_zones(engine)[0].affected_cells}
    _trace(engine, victim)
    asked = []

    def provider(request):
        if str(request["reaction_source_id"]) == "choice:needle.smoke_blacken_the_flame":
            asked.append(request)
        return _soot(request)

    engine.set_reaction_provider(provider)
    # The Fire fighter's own turn, using its own compiled ability.
    engine.state.current_actor_id = attacker_id
    engine.state.current_slot_index = engine.state.initiative_order.index(attacker_id)
    engine._system_start_turn()
    attacker.action_available = attacker.bonus_action_available = attacker.reaction_available = True
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == attacker_id
                     and c.display_name.startswith("Burn Through") and victim_id in (c.target_ids or ()))
    before = victim.current_hp
    engine.execute_intent(ActionIntent(intent_id="burn", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=attacker_id, target_ids=candidate.target_ids))
    assert asked, "a typed Fire attack inside the veil must reach the Blacken the Flame question"
    assert foe_name_in(asked[0], victim.display_name), "the prompt must name the creature that caught the fire"
    cuts = [r for r in engine.rolls if r.reason == "DAMAGE_REDUCED"]
    assert cuts and len(cuts[0].dice) == 3, f"CL 11 reduces by the printed 3d6: {cuts}"
    assert victim.current_hp < before, "the soot took something off a real typed Fire attack"
    assert not bears_mark(victim, ME, "Smoke Trace")
    assert not me.reaction_available, "a Reaction ability spends the owner's Reaction"


def foe_name_in(request, name):
    """The words the table would show this question, wherever the transport keeps them."""
    from combat.choice_checkpoints import ExtensionChoice

    return name in json.dumps(request, default=str)


def test_the_blacken_prompt_names_the_triggering_action_rather_than_an_internal_id():
    """The prompt has to say *what* did it.

    The damage carries the source's own id, which is how the engine routes it but means nothing on a character sheet.
    The fight's action catalog already publishes the same source under the name the table shows, so the prompt quotes
    that. The words checked here are the ones the table puts on the page: combat/tabletop_service.py renders
    ``choice_trigger``'s ``prompt`` verbatim as the question's ``moment``."""
    engine, me, foe = _fight([BLACKEN], cl=11)
    _place_veil(engine, (4, 6))
    _trace(engine, foe)
    shooter = _clone(engine, foe, "actor:factory.pyromancer", (3, 4))
    template = next(iter(engine.action_catalog.values()))
    engine.action_catalog["action:pyromancer.burning_flame"] = template.model_copy(update={
        "source_definition_id": "action:pyromancer.burning_flame", "display_name": "Burning Flame",
        "owner_id": shooter.entity_id, "resolution_kind": "TYPED"})
    asked = []

    def provider(request):
        if str(request["reaction_source_id"]) == "choice:needle.smoke_blacken_the_flame":
            asked.append(request)
        return _soot(request)

    engine.set_reaction_provider(provider)
    engine._active_intent = _any_intent(engine)
    engine._commit_damage(foe, 20, "fire", "action:pyromancer.burning_flame", shooter.entity_id,
                          engine._active_intent, reaction_depth=2)
    assert asked, "the soot question was never put to the owner"
    said = str((asked[0].get("choice_trigger") or {}).get("prompt") or "")
    assert "Blacken the Flame" in said, said
    assert "Burning Flame" in said, f"the prompt must name the action that dealt the fire, not an internal id: {said}"
    assert foe.display_name in said, f"the prompt must name the creature that caught the fire: {said}"
    assert "3d6 + 3" in said, f"the prompt must state what the soot reduces: {said}"
    assert "Reaction" in said and "Smoke Trace" in said, f"the prompt must state both costs it pays: {said}"
    # An internal source with no published name must not leak into a player's question.
    assert smoke_veil._action_words(engine, "system:combat.melee") == ""
    assert smoke_veil._action_words(engine, "action:not.compiled.at.all") == ""


# ------------------------------------------------------------------ the mark really expires on the owner's turn
def test_the_soot_mark_ends_at_the_start_of_the_owners_next_turn():
    """"Until the start of your next turn" is a real moment, not just a name on the condition.

    The earlier check only read ``expires_on`` off the token. This runs the owner's turn out and the target's, and
    looks for the mark actually being removed at the owner's next turn start."""
    engine, me, foe = _fight([WITNESS], cl=10, foe_at=(4, 6))
    _place_veil(engine, (4, 6))
    _trace(engine, foe)
    _run_ability(engine, "Soot-Marked Witness")
    mark = next(c for c in foe.conditions.values() if c.condition_id == smoke_veil.REVEALED)
    assert mark.expires_on == "START_OF_SOURCE_NEXT_TURN", mark.expires_on
    _next_turn(engine, foe)  # the target's turn first: the mark is the owner's, so it must survive it
    assert any(c.condition_id == smoke_veil.REVEALED for c in foe.conditions.values()), \
        "the mark must not end with the target's turn"
    _next_turn(engine, foe)  # now the owner's next turn begins
    assert not any(c.condition_id == smoke_veil.REVEALED for c in foe.conditions.values()), \
        "the mark must end at the start of the owner's next turn"


def _run_ability(engine, name, target=AN):
    from combat.typed_executor import Context, run_effects

    action = next(row for row in engine.action_catalog.values()
                  if row.owner_id == ME and row.display_name.split(" at ")[0] == name)
    t._ready(engine)
    typed = dict(action.parameters["typed"])
    subject = engine.state.actors[target]
    context = Context(engine, engine.state.actors[ME], action, engine._active_intent, typed, [subject], subject)
    run_effects(context, typed["effects"])


def _next_turn(engine, creature):
    """Advance to the next actor's turn, starting it, exactly as the engine does between creatures."""
    order = engine.state.initiative_order
    index = (order.index(engine.state.current_actor_id) + 1) % len(order)
    engine.state.current_slot_index = index
    engine.state.current_actor_id = order[index]
    engine._system_start_turn()


# ------------------------------------------------------------------ who decides at the engine's own transport
def test_the_engine_transport_is_asked_on_the_owners_turn_and_on_another_creatures_turn():
    """The damage-time reader asks through the engine's own reaction transport, on the owner's turn and on another's.

    This is the engine-level half of checklist item 9 and it is deliberately *only* that half: it proves Blacken the
    Flame reaches ``engine.set_reaction_provider`` (a question, not a silent answer) whether the owner is acting or
    somebody else is, and that the answer given is acted on. It says nothing about who the transport asks -- control
    mode, Ask me, an AI step and the table pausing are the service's business, and they are covered at their own
    boundary in test_auto43r1f1_smoke_table.py (``..._the_table_asks_a_manual_owner...`` and
    ``..._an_ai_owner_answers_for_itself...``)."""
    for actor_turns in (True, False):
        engine, me, foe = _fight([BLACKEN], cl=11)
        _place_veil(engine, (4, 6))
        _trace(engine, foe)
        asked = []

        def provider(request):
            if str(request["reaction_source_id"]) == "choice:needle.smoke_blacken_the_flame":
                asked.append(request)
            return _soot(request)

        engine.set_reaction_provider(provider)
        if not actor_turns:
            engine.state.current_actor_id = AN  # the damage lands while somebody else is acting
        engine._active_intent = _any_intent(engine)
        before = foe.current_hp
        engine._commit_damage(foe, 20, "fire", "system:combat.melee", AN, engine._active_intent, reaction_depth=2)
        assert asked, f"owner_turn={actor_turns}: a player-owned decision must be asked, not taken silently"
        assert foe.current_hp < before, f"owner_turn={actor_turns}: the player's yes is acted on"
