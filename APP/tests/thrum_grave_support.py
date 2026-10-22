"""Shared Thrum of the Grave / Spirit Awakening fight harness for the C8 rider tests and the burial-drum tests.

Needs no repository history: the current authority is read from disk. Tests that need the base commit's authority register a
loader in OLD_AUTHORITY_LOADER (see tests/test_riders_c8.py, C8_OLD_TYPING=1).
"""

import json
import os
from functools import lru_cache
from pathlib import Path

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, RollRecord
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.c8"
ALLY = "actor:factory.c8_ally"
FOE = AN
MIND_SPIKE = "tianxia.path.spirit_awakening.feature.mind_spike"
OLD = os.environ.get("C8_OLD_TYPING") == "1"
RES = "resource:core.resonance"

# Set by a test module that needs the base commit's authority (only used when old=True).
OLD_AUTHORITY_LOADER = None


# ------------------------------------------------------------------------------------------------------- harness
@lru_cache(maxsize=2)
def authority(old: bool = OLD):
    if old:
        if OLD_AUTHORITY_LOADER is None:
            raise RuntimeError("no base-commit authority loader registered")
        return OLD_AUTHORITY_LOADER()
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())


def sheet(ids, *, cl=18, pb=6, wis=4, dc=17, resonance=60, items=(), weapon_training=False):
    mods = {"STR": 1, "DEX": 2, "CON": 2, "INT": 1, "WIS": wis, "CHA": 1}
    return {
        **({"equipment": [{"starting_kit": {"items": [{"item_id": item} for item in items]}}]} if items else {}),
        "identity": {"proficiency_bonus": pb, "cultivation_level": cl, "path": "Spirit Awakening", "key_ability": "WIS"},
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": 10 + 2 * m, "modifier": m} for a, m in mods.items()],
            "primary_resource": {"name": "Resonance", "maximum": resonance}, "armor_class": {"base_value": 14},
            "hit_points": {"maximum": 90}, "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 9},
        "path_and_subpath": {"path_record_ids": (["tianxia.path.spirit_awakening"] if weapon_training else []),
                             "path_feature_record_ids": list(ids)},
    }


def bundle(ids, actor_id=ME, **kw):
    return compile_character(sheet(ids, **kw), actor_id=actor_id, typed_authority=authority())


TYPED_FOE = "actor:factory.c8_foe"


def fight(ids, *, ally_ids=None, foe_at=(4, 6), seed="C8", foe_ids=None, **kw):
    """ME owns ``ids``; ALLY (optional) owns ``ally_ids``; the foe is the Gate 2 sparring partner, or a Factory character owning
    ``foe_ids`` (TYPED_FOE) when given."""
    if foe_ids is not None:
        engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(bundle(ids, **kw), bundle(foe_ids, actor_id=TYPED_FOE, cl=5, pb=3)),
                                       roster_setup={"primary_actor_ids": [ME, TYPED_FOE], "team_by_actor": {ME: "team:a", TYPED_FOE: "team:b"},
                                                     "starting_positions": {ME: {"x": 3, "y": 6}, TYPED_FOE: {"x": foe_at[0], "y": foe_at[1]}}})
        turn(engine, ME)
        return engine
    bundles = [bundle(ids, **kw)]
    order, teams, spots = [ME], {ME: "team:a"}, {ME: {"x": 3, "y": 6}}
    if ally_ids is not None:
        bundles.append(bundle(ally_ids, actor_id=ALLY, cl=5, pb=3))
        order.append(ALLY)
        teams[ALLY] = "team:a"
        spots[ALLY] = {"x": 3, "y": 7}
    order.append(FOE)
    teams[FOE] = "team:b"
    spots[FOE] = {"x": foe_at[0], "y": foe_at[1]}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles),
                                   roster_setup={"primary_actor_ids": order, "team_by_actor": teams, "starting_positions": spots})
    turn(engine, ME)
    return engine


def turn(engine, actor_id):
    engine.state.current_slot_index = engine.state.initiative_order.index(actor_id)
    engine.state.current_actor_id = actor_id
    engine._system_start_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = actor.reaction_available = True
    return actor


def legal(engine):
    return {c.display_name for c in engine.legal_candidates()}


def use(engine, name, target=None, actor_id=ME):
    # Reviewed hands change c18f4990: carried spare weapons are stowed.
    from tests.equipment_readiness import ready_weapon
    ready_weapon(engine, name, actor_id)
    matches = [c for c in engine.legal_candidates() if c.display_name == name and (target is None or target in (c.target_ids or ()))]
    assert matches, f"{name!r} is not legal; legal: {sorted(legal(engine))}"
    candidate = matches[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"c8-{name}-{len(engine.events)}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=actor_id,
                                       target_ids=(target,) if target else (candidate.target_ids or ()), destination=candidate.destination))
    return engine.events[before:]


def payloads(events, kind):
    return [getattr(e, "payload", None) or {} for e in events if e.event_type == kind]


def held(actor, condition_id, source_actor=None):
    return [c for c in actor.conditions.values() if c.condition_id == condition_id and (source_actor is None or c.source_actor_id == source_actor)]


def fixed_d20(engine, natural):
    """Every d20 the engine rolls next comes up ``natural``."""
    count = [0]

    def d20(**kw):
        count[0] += 1
        return RollRecord(roll_id=f"c8-fixed-{count[0]}", counter_start=count[0], counter_end=count[0] + 1,
                          expression=f"1d20{kw['modifier']:+d}", actor_id=kw["actor_id"], reason=kw["reason"], dice=(natural,),
                          modifier=kw["modifier"], total=natural + kw["modifier"], natural_result=natural)
    engine.roller.d20 = d20


def mark_resonance(engine, subject_id, owner=ME):
    engine._apply_condition(engine.state.actors[subject_id], typed_executor.mark_condition_id("Resonance", owner), "test", owner,
                            expires_on="UNTIL_REMOVED")


def answers(engine, table):
    """A player answering this lane's choices: ``table`` maps the end of a choice id ("black_current.wake_mark") to the option ids
    to pick (a tuple), None to decline, or a function of the request's option ids. Unlisted choices take their default."""
    from combat.gate2_runtime_models import ReactionDecision

    seen = []

    def provider(request):
        spec = request.get("extension_choice")
        if spec is None:
            return None, None
        seen.append(request)
        source = request["reaction_source_id"]
        key = next((k for k in table if source.endswith(k)), None)
        if key is None:
            pick = (spec.get("preferred_option_ids") or spec["option_ids"])[:max(1, spec["minimum_selections"])]
        else:
            pick = table[key]
            pick = pick(list(spec["option_ids"])) if callable(pick) else pick
        base = {k: request[k] for k in ("checkpoint", "reactor_id", "reaction_source_id")}
        if pick is None:
            return ReactionDecision(**base, selection="DECLINE", option_ids=()), None
        return ReactionDecision(**base, selection="USE", option_ids=tuple(pick)), None

    engine.set_reaction_provider(provider)
    return seen


def cell(x, y):
    return f"cell:{x},{y}"


def use_to(engine, name, x, y, actor_id=ME):
    candidate = next(c for c in engine.legal_candidates() if c.display_name.startswith(name) and c.destination is not None
                     and (c.destination.x, c.destination.y) == (x, y))
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"c8-{name}-{before}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=candidate.target_ids or (), destination=candidate.destination))
    return engine.events[before:]


# ============================================================================================ 31 Thrum of the Grave
TG = "tianxia.tradition.spirit.thrum_of_the_grave.feature."
TG_ALL = [MIND_SPIKE] + [TG + k for k in ("gravebeat", "dead_march", "burial_drum", "call_the_unquiet", "the_earth_beats_once")]
BEATS = "resource:named.gravebeat"


def heal(engine, subject_id, amount=20):
    from combat.ext import spirit_traditions as st

    subject = engine.state.actors[subject_id]
    ctx = st.context(engine, subject, st.feature_action(engine, subject, "test:healing"), [subject], {"pb": 3, "save_dc": 10, "cl": 5})
    typed_executor.run_effects(ctx, [{"type": "healing", "applies_to": "target", "flat": amount, "evidence": "regains Hit Points"}])
