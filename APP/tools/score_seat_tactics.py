"""Read-only offline menu reconstruction; no provider, service or save writes.

Usage: python tools/score_seat_tactics.py CAPTURE_ROOT [--live MATCH_COPY]
Scores the three 36-fight short-list captures, using historical TURN/STEP
boundaries. Printed metrics are menu availability, never inferred model wins.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_seats.choices import build_prompt, turn_options
from agent_seats.tactics import tactical_moves
from agent_seats.runner import SeatRunner
from agent_seats.snapshots import project_map
from combat import senses, zones
from combat.gate2_runtime_models import MatchState, CombatEvent, RollRecord
from combat.gate3_reducer import Gate3EventReducer, canonical_state_sha256
from combat.gate4_context import build_decision_context
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate4_policy import PolicyLibrary
from combat.tabletop import battlefield_as_map, table_section
from combat.tabletop_service import TabletopService

ROOT = Path(__file__).resolve().parents[1]


def capture_menus(path):
    """Yield historical own-view menus, verifying every replayed state hash.

    Each TURN is paired with its next STEP, so continuation steps aren't
    mistaken for new model menus. Sight memory comes only from earlier views.
    """
    def read(name):
        return json.loads((path / name).read_text())
    pending, boundaries = {}, {}
    for line in (path / "Agent_Decisions.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["kind"] == "TURN":
            pending[row["actor_id"]] = row
        elif row["kind"] == "STEP" and row["actor_id"] in pending:
            boundaries[row["state_version"]] = pending.pop(row["actor_id"])
    genesis = read("GenesisState.json")
    arena = read("Arena_Battlefield.json")
    state = MatchState.model_validate(genesis["state"])
    engine = Gate4ControllerEngine(ROOT, match_seed=state.match_seed,
        typed_bundles=tuple(read("Typed_Character_Bundles.json")), battlefield=arena,
        roster_setup={"actor_ids": list(genesis["state"]["actors"])})
    events, rolls = list(genesis["initial_events"]), list(genesis["initial_rolls"])
    memory = defaultdict(dict)
    policy = PolicyLibrary(ROOT).fallback()
    source = arena.get("tabletop") or table_section(battlefield_as_map(arena))
    for line in (path / "Journal.ndjson").read_text().splitlines():
        record = json.loads(line)
        if record["record_type"] == "COMMIT":
            state = Gate3EventReducer().apply_events(state, record["events"])
            state.state_version = record["post_state_version"]
            state.roll_counter = record["roll_counter_end"]
            assert canonical_state_sha256(state) == record["post_state_sha256"]
            events.extend(record["events"])
            rolls.extend(record["rolls"])
            continue
        if record["record_type"] != "PREPARE":
            continue
        row = boundaries.pop(record["pre_state_version"], None)
        if row is None:
            continue
        engine.state = state.model_copy(deep=True)
        engine.events = [CombatEvent.model_validate(e) for e in events]
        engine.rolls = [RollRecord.model_validate(r) for r in rolls]
        engine.roller.counter = state.roll_counter
        zones.sync_walls(engine)
        actor = engine.state.actors[row["actor_id"]]
        seen = senses.perception(engine, actor)
        known = set(seen["creatures"])
        actors = [{"entity_id": a.entity_id, "display_name": a.display_name,
                   "team_id": a.team_id, "position": a.position.model_dump(),
                   "hit_points": {"current": a.current_hp, "maximum": a.maximum_hp},
                   "movement_remaining_ft": a.movement_remaining_ft}
                  for a in engine.state.actors.values() if a.entity_id in known]
        previous = memory[actor.entity_id]
        last_seen = [m for key, m in previous.items() if key not in known
                     and m["team_id"] != actor.team_id]
        for a in actors:
            previous[a["entity_id"]] = {"position": a["position"], "team_id": a["team_id"],
                                        "hostile": int(a["team_id"] != actor.team_id)}
        view = {"fighter": actor.entity_id, "actors": actors, "objects": [],
                "last_seen": last_seen, "visible_cells": seen["cells"],
                "dao": {"role": list(policy.role)},
                "map": project_map(source, seen["cells"], engine.grid.width, engine.grid.height, [])}
        context = build_decision_context(engine, policy, include_item_actions=True)
        names = {i: a.display_name for i, a in engine.state.actors.items()}
        definitions = {i: a.display_name for i, a in engine.action_catalog.items()}
        menu = TabletopService._menu({"context": context.model_dump(mode="json"),
                                     "control_mode": "MANUAL"}, names, definitions, engine)
        TabletopService._menu_descriptions(menu, engine)
        options = SeatRunner._menu(None, {"menu": menu}, known)
        legal = {k: v["description"] for k, v in options.items()}
        yield view, legal, row
    assert not boundaries, "Some model boundaries were not reconstructed"


def score(path):
    stats = Counter()
    for view, legal, row in capture_menus(path):
        stats["menus"] += 1
        movement = any(r["action"] == "Move" for r in legal.values())
        tactical_keys = set(dict(tactical_moves(view, legal)))
        stats["movement_legal"] += movement
        builtin = row["built_in_pick"]
        if builtin not in legal:
            stats["builtin_changed"] += 1
            continue
        for budget, maximum in [(800, 6), (2400, 10), (2400, 12)]:
            tag = f"{budget}/{maximum}"
            try:
                options = turn_options(view, legal, builtin, limit=3,
                                       choices_bytes=budget, max_options=maximum)
                prompt, offered = build_prompt(view, options, "TURN", legal,
                                               choices_bytes=budget, max_options=maximum)
                assert len(prompt.encode()) <= budget
                stats[tag + "_options"] += len(offered)
                has_move = any(any(legal[k]["action"] == "Move" for k in a["plan"])
                               for a in offered.values())
                stats[tag + "_movement_offered"] += movement and has_move
                has_tactical = any(any(k in tactical_keys for k in a["plan"]) for a in offered.values())
                stats[tag + "_tactical_move_offered"] += movement and has_tactical
                stats[tag + "_packed"] += 1
            except ValueError:
                stats[tag + "_overflow"] += 1
    return stats


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captures", type=Path)
    parser.add_argument("--live", type=Path)
    args = parser.parse_args()
    for name in ("long-qwen9b", "long-haiku55-choices", "long-luna-choices"):
        total = Counter()
        paths = sorted((args.captures / name).rglob("Agent_Decisions.jsonl"))
        for path in paths:
            try:
                total.update(score(path.parent))
            except Exception as exc:
                print(json.dumps({"capture": str(path), "error": type(exc).__name__, "message": str(exc)}), flush=True)
                raise
            print(json.dumps({"progress": name, "completed": str(path.parent), "stats": total}), flush=True)
        print(json.dumps({"summary": name, "fights": len(paths), "stats": total}), flush=True)
    if args.live:
        for view, legal, row in capture_menus(args.live):
            for variant in ("observed", "no-visible-enemy"):
                if variant == "no-visible-enemy":
                    own = next(a for a in view["actors"] if a["entity_id"] == view["fighter"])
                    view = dict(view, actors=[a for a in view["actors"] if a["team_id"] == own["team_id"]], last_seen=[])
                    known = {a["entity_id"] for a in view["actors"]}
                    legal = {k: r for k, r in legal.items() if set(r.get("targets", [])) <= known}
                options = turn_options(view, legal, row["built_in_pick"], limit=3, choices_bytes=2400, max_options=12)
                prompt, offered = build_prompt(view, options, "TURN", legal, choices_bytes=2400, max_options=12)
                assert any(any(legal[k]["action"] == "Move" for k in a["plan"]) for a in offered.values())
                print(json.dumps({"live": variant, "fighter": view["fighter"], "prompt": prompt}), flush=True)


if __name__ == "__main__":
    main()
