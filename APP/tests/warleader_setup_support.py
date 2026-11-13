"""Warleader combat setup shared by resource and sheet resistance tests."""
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_lane1 import ROOT, ALLY, ME, _ally_bundle, _bundle, _ready, _sheet

WL = "tianxia.talent.warleader."
ALLY2 = "actor:factory.lane1_ally2"
TFOE = "actor:factory.typed_foe"
MOMENTUM = "resource:named.momentum_mark"
COURT_ACTION = "Warleader Domain: Court of Moving Banners"

def _wl(*talents, actor_id=ME, cl=10, weapon=("tianxia.mortal.weapon.dao", "Dao")):
    """A Warleader who knows ``talents`` (slugs of tianxia.talent.warleader.*) and carries a Dao (or the ``weapon`` given)."""
    sheet = _sheet("WARLEADER_BASE_SET_THE_STANDARD", cl=cl)
    sheet["spheres_and_talents"]["learned_talent_record_ids"] = [WL + slug for slug in talents]
    sheet["equipment"] = [{"starting_kit": {"items": [{"item_id": weapon[0], "name": weapon[1], "quantity": 1}]}}]
    return compile_character(sheet, actor_id=actor_id)


def _field(*talents, cl=10, allies=1, foes=1, friends=None, enemies=None):
    """The leader at (3,6) with ``allies`` behind it (or the ``friends`` bundles given) and ``foes`` typed hostile Warleaders (their attacks are
    typed, so plug-ins read them) from (4,6). Its Martial Focus is 1. ``enemies`` supplies the hostile bundles outright (a bow-armed
    foe, whose ranged reach is what Reactive Position has to read)."""
    friends = friends or [_ally_bundle(), *[_bundle("TAL_ALCHEMY_CALMING_HEART_PILL", actor_id=ALLY2)]][:allies]
    enemies = enemies if enemies is not None else [_wl(actor_id=TFOE if row == 0 else f"{TFOE}{row}", cl=cl) for row in range(foes)]
    leader = _wl(*talents, cl=cl)
    ids = [ME, *(b["actor_id"] for b in friends), *(b["actor_id"] for b in enemies)]
    engine = Gate4ControllerEngine(
        ROOT, match_seed="LANE1", typed_bundles=(leader, *friends, *enemies),
        roster_setup={"primary_actor_ids": ids,
                      "team_by_actor": {ME: "team:a", **{b["actor_id"]: "team:a" for b in friends}, **{b["actor_id"]: "team:b" for b in enemies}},
                      "starting_positions": {ME: {"x": 3, "y": 6}, **{b["actor_id"]: {"x": 3, "y": 7 + row} for row, b in enumerate(friends)},
                                             **{b["actor_id"]: {"x": 4, "y": 6 + row} for row, b in enumerate(enemies)}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    _ready(engine)
    return engine


def _act(engine, actor_id, name, target=None):
    """``actor_id`` takes the action called ``name`` (against ``target`` if it names one), with its action, bonus action and reaction fresh."""
    actor = engine.state.actors[actor_id]
    engine.state.current_actor_id = actor_id
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    matches = [c for c in engine.legal_candidates() if c.display_name == name]
    assert matches, f"{name!r} is not legal for {actor_id}; legal: {sorted({c.display_name for c in engine.legal_candidates() if c.kind.value != 'MOVE'})}"
    chosen = next((c for c in matches if target in (c.target_ids or ())), matches[0])
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{actor_id}-{name}-{before}", decision_id=chosen.decision_id, candidate_id=chosen.candidate_id,
                                       state_version=chosen.state_version, actor_id=actor_id, target_ids=(target,) if target else (chosen.target_ids or ()),
                                       destination=chosen.destination))
    return engine.events[before:]


def _command(*talents, standard=None, marks=2, friends=None, **kw):
    """A leader holding ``marks`` Momentum Marks and its Standard (the base one unless ``standard`` names another), an ally that wields
    a Dao at (3,7) (or the ``friends`` given), and a typed foe at (4,6)."""
    engine = _field(*talents, friends=friends or [_wl(actor_id=ALLY)], **kw)
    me = engine.state.actors[ME]
    if marks:
        engine._gain_resource(me, MOMENTUM, marks, "test")
    if standard is not False:
        _act(engine, ME, standard or "Set the Standard")
    return engine


