"""Recorded wall/exemption crossing and automatic stock replay evidence.

Uses public synthetic sheets rather than unavailable private character archives.
Legal casts/moves go through the persistent session; the documented event hook
reads committed paths without replacing engine methods. No gameplay import.
AUTO_APP=<APP> AUTO_TMP=<scratch> python <tool> out.json wall|stock - seed [rounds]
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def failures(result, mode):
    """Missing evidence must fail the command, not just print a counter."""
    errors = []
    if result.get("crash"):
        errors.append("captured crash")
    if result.get("observer_errors"):
        errors.append("movement observer failed")
    if result.get("replay") != "PASS":
        errors.append("mechanical replay did not pass")
    if mode == "wall":
        if result.get("commit_reload") != "PASS":
            errors.append("crossing commit/reload did not pass")
        for name in ("Gather Sand", "Dune Wall"):
            if not any(c.get("ability") == name and c.get("status") == "EXECUTED"
                       for c in result.get("forced_casts", [])):
                errors.append(f"required cast failed or absent: {name}")
        crossings = [p for p in result.get("move_probe", []) if p.get("wall_exempt_entered")]
        if not crossings:
            errors.append("no committed wall/exemption crossing")
        for p in crossings:
            if (type(p.get("cost_ft")) is not int or p["cost_ft"] <= 0
                    or p.get("expected_cost_ft") != p.get("cost_ft") or p.get("planned_cost_ft") != p.get("cost_ft")):
                errors.append("crossing quote/commit/expected cost mismatch")
        budget = result.get("movement_budget", {})
        spent = sum(p.get("cost_ft", 0) for p in crossings)
        if (type(budget.get("before_ft")) is not int or type(budget.get("after_ft")) is not int
                or budget["before_ft"] - budget["after_ft"] != spent or budget["after_ft"] < 0):
            errors.append("crossing movement budget mismatch")
    return errors


def movement_probe(engine, kwargs):
    """Sum entered-footprint prices for this static, ordinary-walking fixture.

    The fixture has no extra movement costs or dynamic terrain during a move.
    Sand Step excuses the ground, but Dune Wall retains its printed x4 price.
    """
    from combat import motion
    actor = engine.state.actors[kwargs["actor_id"]]
    payload = kwargs.get("payload") or {}
    path = payload.get("path") or []
    wall = engine.grid.wall_traversal_cost
    exempt = motion.exempt_cells(engine, actor)
    footprint = engine.actor_footprints[actor.entity_id]
    steps = []
    for before, after in zip(path, path[1:]):
        old = set(engine.grid.footprint_cells((before["x"], before["y"]), footprint))
        new = set(engine.grid.footprint_cells((after["x"], after["y"]), footprint))
        entered = new - old or new
        prices = {c: (wall.get(c, 1) if c in exempt else engine.grid.base_movement_cost.get(c, 1)) for c in entered}
        steps.append({"entered": sorted(entered), "wall_entered": sorted(entered & wall.keys()),
                      "wall_exempt_entered": sorted(entered & wall.keys() & exempt),
                      "cost_ft": engine.grid.square_size_ft * max(prices.values(), default=1)})
    return {"actor": actor.entity_id, "round": engine.state.round_number,
            "sequence": kwargs["originating_event"].sequence, "path": path, "steps": steps,
            "wall_exempt_entered": [c for s in steps for c in s["wall_exempt_entered"]],
            "wall_prices": [[*c, wall[c]] for c in sorted(wall)], "exempt_cells": sorted(exempt),
            "expected_cost_ft": sum(s["cost_ft"] for s in steps),
            "cost_ft": payload.get("cost_ft"), "planned_cost_ft": payload.get("planned_cost_ft")}


def capture(app, scratch, mode, seed, rounds=3):
    from combat import ext
    from combat.factory_compiler import compile_character
    from combat.gate2_runtime_models import ActionIntent
    from combat.gate3_reducer import canonical_state_document
    from combat.gate5_service import CombatService
    from tests.h1_support import sheet

    probe, casts = [], []
    result = {"mode": mode, "seed": seed,
              "fixture": "public synthetic sheets" if mode == "wall" else "native stock roster"}
    observing = False

    @ext.hook("event")
    def observe(engine, event_type, kwargs):
        if observing and event_type == "MOVEMENT_COMMITTED":
            try:
                probe.append(movement_probe(engine, kwargs))
            except Exception as exc:
                # Event hooks isolate subscriber errors; retain them explicitly
                # so a successful replay can never mask a failed observer.
                result.setdefault("observer_errors", []).append(repr(exc))

    try:
        svc = CombatService(app, scratch)
        if mode == "wall":
            ids = ("actor:factory.sand_probe", "actor:factory.stock_probe")
            talents = ["TAL_SAND_SAND_STEP", "TAL_SAND_DUNE_WALL"]
            bundles = tuple(compile_character(sheet(talents if i == 0 else [], cl=10), actor_id=aid)
                            for i, aid in enumerate(ids))
            session = svc.persistence.create_match(match_seed=seed, typed_bundles=bundles, roster_setup={
                "primary_actor_ids": list(ids), "team_by_actor": {ids[0]: "team:a", ids[1]: "team:b"},
                "starting_positions": {ids[0]: {"x": 3, "y": 6}, ids[1]: {"x": 10, "y": 6}}})

            def submit(candidate):
                session.submit_intent(ActionIntent(intent_id=f"probe:{len(session.engine.events)}",
                    decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                    state_version=candidate.state_version, actor_id=candidate.actor_id,
                    target_ids=candidate.target_ids or (), destination=candidate.destination),
                    primary_decision_record=None, reaction_provider=None)

            def end_turn():
                submit(next(c for c in session.engine.legal_candidates() if c.kind.value == "END_TURN"))

            def turn_to(aid):
                for _ in range(8):
                    if session.engine.state.current_actor_id == aid:
                        return
                    end_turn()
                raise AssertionError("required actor turn not reached")

            turn_to(ids[0])
            for name in ("Gather Sand", "Dune Wall"):
                candidate = next(c for c in session.engine.legal_candidates() if c.display_name.startswith(name)
                                 and c.destination and (c.destination.x, c.destination.y) == (3, 7))
                submit(candidate)
                casts.append({"ability": name, "status": "EXECUTED", "destination": {"x": 3, "y": 7}})
                if name == "Gather Sand":
                    end_turn()
                    turn_to(ids[0])
            candidate = next(c for c in session.engine.legal_candidates() if c.kind.value == "MOVE"
                             and c.destination and (c.destination.x, c.destination.y) == (3, 7)
                             and c.metadata.get("movement_mode", "walk") == "walk")
            observing = True
            budget = session.engine.state.actors[ids[0]].movement_remaining_ft
            submit(candidate)
            observing = False
            result["movement_budget"] = {"before_ft": budget,
                "after_ft": session.engine.state.actors[ids[0]].movement_remaining_ft}
            before = canonical_state_document(session.engine.state)
            session = svc.persistence.load_match(session.match_id)
            if canonical_state_document(session.engine.state) != before:
                raise AssertionError("commit/reload changed crossing state")
            result["commit_reload"] = "PASS"
        else:
            # Native stock roster, automatic choices only, no lane abilities.
            session = svc.persistence.create_match(match_seed=seed)
            for actor_id in session.engine.state.actors:
                if session.engine.state.actors[actor_id].primary_combatant:
                    svc.set_controller_mode(session.match_id, actor_id=actor_id, controller_mode="LOCAL_AUTO")
            for _ in range(100):
                if session.engine.state.terminal_result or session.engine.state.round_number > rounds:
                    break
                step = svc.local_step(session.match_id)
                if str(step.get("status", "")).startswith("AWAITING"):
                    raise AssertionError(f"stock control stalled: {step['status']}")
                session = svc.persistence.load_match(session.match_id)
            else:
                raise AssertionError("stock control exceeded step limit")
        engine = session.engine
        document = {"state": canonical_state_document(engine.state),
                    "events": [e.model_dump(mode="json") for e in engine.events],
                    "rolls": [r.model_dump(mode="json") for r in engine.rolls]}
        result.update(replay=session.mechanical.replay().get("status"), document=document,
                      sha256=hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    except Exception:
        import traceback
        result["crash"] = traceback.format_exc()
    finally:
        observing = False
    result.update(move_probe=probe, forced_casts=casts)
    result["failures"] = failures(result, mode)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("mode", choices=("wall", "stock"))
    parser.add_argument("arena", nargs="?", choices=("-",), default="-")
    parser.add_argument("seed", nargs="?", default="SOLFAUTO22r6")
    parser.add_argument("rounds", nargs="?", type=int, default=3)
    args = parser.parse_args()
    app = Path(os.environ["AUTO_APP"])
    sys.path.insert(0, str(app))
    scratch = Path(tempfile.mkdtemp(prefix="wall-replay-", dir=os.environ["AUTO_TMP"]))
    try:
        result = capture(app, scratch, args.mode, args.seed, args.rounds)
        args.out.write_text(json.dumps(result, indent=1, sort_keys=True))
        print(json.dumps({k: v for k, v in result.items() if k != "document"}, sort_keys=True))
        return 1 if result["failures"] else 0
    finally:
        shutil.rmtree(scratch)


if __name__ == "__main__":
    sys.exit(main())
