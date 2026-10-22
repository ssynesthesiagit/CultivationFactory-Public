"""Shared harness for the d20-rewrite ability tests (automation lane H1): a real Factory character that owns exactly the named
mechanics is compiled and put in a duel, the dice are scripted, and the roll under test is forced through the engine's own save,
attack or check code -- so what runs is the shipped ability, not a stand-in."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import combat.factory_compiler as factory_compiler
from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, DiceSpec
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.h1"
ALLY = "actor:factory.h1_ally"
FOE = AN


@lru_cache(maxsize=4)
def _load_mechanics(path):
    return json.loads(Path(path).read_bytes())["mechanics"]


def mechanics():
    return _load_mechanics(str(factory_compiler.TYPED_AUTHORITY))


def sheet(mids, *, cl=10, dc=16, primary="Qi", key="CON", score=14, foundation=None, kit=None, name=None):
    """A character owning exactly ``mids`` (talents, sphere base abilities, path/subpath/tradition features, foundation features)."""
    mids = [mids] if isinstance(mids, str) else list(mids)
    mods = mechanics()
    spheres, talents, features, found = [], [], [], None
    for mid in mids:
        mech = mods[mid]
        if mech.get("sphere_id"):
            if mech["sphere_id"] not in spheres:
                spheres.append(mech["sphere_id"])
            talents.append(mid)
        elif mech["kind"] in ("path_feature", "subpath_feature"):
            features.append(mid)
        elif mech["kind"] == "foundation_feature":
            found = foundation or {"foundation_id": mech["foundation_id"], "stage": mech.get("stage") or "Perfected"}
    modifier = (score - 10) // 2
    identity = {"proficiency_bonus": 4, "cultivation_level": cl, "path": "Qi Cultivation", "key_ability": key}
    # A sheet may name its creature. Without one the compiler falls back to a single
    # shared placeholder for every actor, which makes a prompt's creature names
    # indistinguishable: a test asserting "the striker is named" passes even when the
    # names are reversed, because every comparison is the same string.
    if name:
        identity["name"] = name
    out = {
        "identity": identity,
        "ability_scores_and_statistics": {
            "abilities": [{"ability": a, "score": score, "modifier": modifier} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
            "primary_resource": {"name": primary, "maximum": 30}, "armor_class": {"base_value": 14}, "hit_points": {"maximum": 60},
            "speed": {"walking_ft": 30}, "technique_save_dc": dc, "technique_attack_bonus": 8,
        },
    }
    if spheres:
        bases = [k for k, m in mods.items() if m.get("sphere_id") in spheres and m.get("kind") == "base_ability"]
        out["spheres_and_talents"] = {"sphere_record_ids": spheres, "learned_talent_record_ids": talents, "automatic_sphere_component_record_ids": bases}
    if kit:
        out["equipment"] = [kit]
    if features:
        out["path_and_subpath"] = {"path_feature_record_ids": features}
    if found:
        out["foundation"] = found
    return out


def bundle(mids, actor_id=ME, **kw):
    return compile_character(sheet(mids, **kw), actor_id=actor_id)


def duel(mids, *, allies=(), foe_team_size=1, seed="H1", primary="Qi", cl=10, ally_mids=None, **kw):
    """ME owns ``mids``; ALLY (optional) owns ``ally_mids``; the Gate 2 sparring foe stands next to ME. Returns the engine, ME's turn open."""
    bundles = [bundle(mids, primary=primary, cl=cl, **kw)]
    if ally_mids is not None:
        bundles.append(bundle(ally_mids, actor_id=ALLY, primary=primary, cl=cl))
    ids = [b["actor_id"] for b in bundles]
    engine = Gate4ControllerEngine(
        ROOT, match_seed=seed, typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [*ids, FOE], "team_by_actor": {**{i: "team:a" for i in ids}, FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, **({ALLY: {"x": 3, "y": 7}} if ALLY in ids else {}), FOE: {"x": 4, "y": 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    engine.state.actors[FOE].armor_class = 10
    ready(engine)
    return engine


def ready(engine):
    me = engine.state.actors[ME]
    engine.state.current_actor_id = ME
    me.action_available, me.bonus_action_available, me.reaction_available = True, True, True
    return me


def give(engine, actor_id, **pools):
    """Set resource pools by the cost names the rules use (focus, stamina, rebirth_ember ...)."""
    from combat.ext.d20_rewrite import pool_id

    actor = engine.state.actors[actor_id]
    for name, amount in pools.items():
        resource = pool_id(actor, name) or f"resource:named.{name}"
        actor.resource_maximums.setdefault(resource, 99)
        actor.resources[resource] = amount


def amount(engine, actor_id, name):
    from combat.ext.d20_rewrite import pool_id

    actor = engine.state.actors[actor_id]
    return actor.resources.get(pool_id(actor, name) or f"resource:named.{name}", 0)


def script(engine, values):
    """The next dice this engine rolls (of any size, in the order rolled) come from ``values``; then the seeded roller carries on."""
    queue = list(values)
    roller = engine.roller
    original = roller._die

    def _die(sides):
        if queue:
            counter = roller.counter
            roller.counter += 1
            return min(int(queue.pop(0)), sides), counter
        return original(sides)

    roller._die = _die
    return queue


def events(engine, event_type, start=0):
    return [e for e in engine.events[start:] if e.event_type == event_type]


def rewrites(engine, start=0):
    return events(engine, "D20_REWRITTEN", start)


def force_save(engine, target_id, ability, *, dc=16, source_id="test:effect", typed=False, condition=None, forcer=FOE, on_fail=None):
    """``target_id`` rolls a saving throw. typed=True goes through the typed executor's own save (with what a failure imposes and
    who forces it); otherwise the engine's `_roll_save`. Returns the roll the caller reads."""
    target = engine.state.actors[target_id]
    if not typed:
        return engine._roll_save(target, ability, dc, source_id)
    action = next(iter(engine.action_catalog.values()))
    actor = engine.state.actors[forcer]
    ctx = typed_executor.Context(engine, actor, action, None, {"numbers": {"pb": 4, "save_dc": dc}}, [target], target, {})
    fail = on_fail or ([{"type": "condition", "condition": condition, "applies_to": "target"}] if condition else [])
    typed_executor.block_save(ctx, {"type": "save", "ability": ability.lower(), "on_fail": fail, "on_success": []})
    return next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED")


def attack(engine, attacker_id, target_id, *, bonus=0, source_id="test:attack", index=1, ac=None):
    """``attacker_id`` makes one attack roll against ``target_id`` (through the engine's own attack resolution); returns whether it hit."""
    attacker, target = engine.state.actors[attacker_id], engine.state.actors[target_id]
    if ac is not None:
        target.armor_class = ac
    spec = {"attack_bonus": bonus, "damage": DiceSpec(count=1, sides=4, modifier=0), "damage_type": "SLASHING", "reach_ft": 5}
    intent = ActionIntent(intent_id="i-h1", decision_id="d-h1", candidate_id="c-h1", state_version=engine.state.state_version, actor_id=attacker_id,
                          target_ids=(target_id,))
    return engine._resolve_attack_spec(attacker, target, spec, intent, source_definition_id=source_id, attack_index=index)


def last(engine, event_type):
    return next(e for e in reversed(engine.events) if e.event_type == event_type)


def use(engine, name, target=None, actor_id=ME):
    """The fighter takes the named legal action (a menu button); returns the events it wrote."""
    matches = [c for c in engine.legal_candidates() if c.display_name == name and c.actor_id == actor_id and (target is None or tuple(c.target_ids) == (target,))]
    assert matches, f"{name!r} is not legal; legal: {sorted({c.display_name for c in engine.legal_candidates() if not c.display_name.startswith('Move')})}"
    candidate = matches[0]
    targets = (target,) if target else (candidate.target_ids or ())
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                                       state_version=candidate.state_version, actor_id=actor_id, target_ids=targets, destination=candidate.destination))
    return engine.events[before:]


def held(actor, prefix):
    return [c for c in actor.conditions.values() if c.condition_id.startswith(prefix)]
