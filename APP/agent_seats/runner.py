"""Table-service decision driver, seat persistence and actor-scoped prompts.

Provider work runs without a table lock. Every commit uses fresh engine-issued
candidate ids and decision/version bindings through TabletopService. Plans store
stable menu descriptions, never saved engine objects or future candidate ids.
The table callback is scheduling-only; callers can use drive() in deterministic
tests. render_png(view) receives ONLY the same redacted view sent to the model.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import os
from pathlib import Path
import queue
import threading
import time
import uuid

from combat.gate4_models import ReactionContext
from combat.tabletop import TabletopError
from combat.tabletop_service import MANUAL_MODES, _match_lock, _table_action_lock
from .choices import decision_payload
from .decision_records import append as append_decision
from .providers import ProviderRegistry, complete
from .snapshots import SnapshotRenderer, project_map
from .protocol import VERSION, build_prompt, parse_reply, validate_answer

# A model seat may override its provider's prompt profile: "choices" (pick from a short list, for small models)
# or "full" (plan the whole turn). None keeps the provider's own setting.
SEAT_STYLES = {None, "choices", "full"}


def failure_detail(exc, stage, provider):
    """Bound local diagnostics, excluding the configured provider credential.

    This is decision-log metadata only; never send transport errors or raw
    replies back to the model. Validation exceptions use our fixed messages.
    """
    message = str(exc)
    credential = os.environ.get(provider.get("key_env") or "")
    if credential:
        message = message.replace(credential, "[redacted]")
    message = " ".join("".join(c for c in message if c.isprintable() or c.isspace()).split())[:240]
    return {"stage": stage, "exception": type(exc).__name__, "message": message}


def _offered_menu(profile, prompt, legal, kind):
    """The menu a non-choice prompt offered, keyed as the prompt showed it.

    Compact/tiny show a bounded subset in the prompt's own legal_menu, so the
    menu is read from the prompt rather than from every legal key. A turn key
    maps to its plan step. A reaction maps to its whole canonical answer
    (selection, option_ids, spend), so declines, optionless uses and spend
    amounts stay distinct.
    """
    if profile in {"compact", "tiny"}:
        menu = json.loads(prompt.split("\n", 1)[1])["legal_menu"]
    else:
        menu = legal
    if kind == "TURN":
        return {key: {"plan": [key]} for key in menu}
    # A reaction is one structured prompt menu, not a mapping of action IDs.
    # Keep its ability, choice options and legal spends together for recording.
    if kind == "REACTION":
        return {"reaction": copy.deepcopy(menu)}
    return {}


def _chosen_key(answers, answer, kind):
    """The offered key a chosen answer maps to; a turn plan maps by its first step.

    A reaction maps by its selected offered id. Declines and optionless uses have
    no selected id, so they map to None here; the full answer is still kept in
    the record's chosen field.
    """
    if kind == "TURN":
        first = (answer.get("plan") or [None])[0]
        return first if first in (answers or {}) else None
    ids = answer.get("option_ids") or []
    return ids[0] if ids and ids[0] in (answers or {}) else None



def _safe_error_text(exc, limit=240):
    """Exception text for the log: no URLs, keys or tokens, and bounded in length."""
    text = re.sub(r"https?://\S+", "[url]", str(exc))
    text = re.sub(r"(?i)(api[_-]?key|token|secret|authorization|bearer)([\s:=]+(?:bearer\s+)?)\S+", r"\1 [redacted]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[redacted]", text)
    text = " ".join(text.split())
    return text[:limit]

class SeatRunner:
    def __init__(self, table, *, registry=None, provider=complete, render_png=None, background=True):
        self.table = table
        self.registry = registry or ProviderRegistry()
        self.provider = provider
        self.render_png = render_png if render_png is not None else SnapshotRenderer()
        self.background = background
        self._local = threading.local()
        self._guard = threading.Lock()
        self._running = {}
        self._status = {}
        self._plans = {}
        self._dao = {}
        # Timed-out transports cannot create an unbounded queue of live threads.
        self._calls = threading.BoundedSemaphore(4)
        table.decision_driver = self

    def _path(self, mid):
        return self.table._match_dir(mid) / "Agent_Seats.json"

    def seats(self, mid):
        path = self._path(mid)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def playback(self, mid):
        """Persist playback beside seats, without changing legacy seat rows.

        The revision fences replies prepared before a Pause/Play transition.
        Both fields are integers; no engine state or live transport is saved.
        """
        path = self.table._match_dir(mid) / "Agent_Playback.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"paused": 0, "revision": 0}

    def set_paused(self, mid, paused):
        with _match_lock(mid), _table_action_lock(self.table._match_dir(mid), mid):
            self.table.combat._load_session(mid)  # validate the fight before writing
            self._write_playback(mid, paused)
            self._plans.pop(mid, None)
        # Observe outside the writer lock. Human actions can still need a model reaction.
        self.table.state(mid)
        return self.status(mid)

    def _write_playback(self, mid, paused):
        """Write under the table writer lock, fencing pre-transition replies."""
        prior = self.playback(mid)
        value = {"paused": int(paused), "revision": prior["revision"] + 1}
        path = self.table._match_dir(mid) / "Agent_Playback.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value) + "\n", encoding="utf-8")
        temporary.replace(path)

    def set_seat(self, mid, actor_id, control, provider_id=None, style=None):
        if control not in {"MANUAL", "AI", "MODEL"}:
            raise TabletopError("SEAT_INVALID", "Choose manual control, built-in AI, or a model.", 422)
        if style not in SEAT_STYLES:
            raise TabletopError("SEAT_INVALID", "Choose a short list of options or whole-turn planning.", 422)
        if control != "MODEL" and style is not None:
            raise TabletopError("SEAT_INVALID", "Only a model seat has a play style.", 422)
        if control == "MODEL" and provider_id not in self.registry.load():
            raise TabletopError("SEAT_PROVIDER_INVALID", "Choose an installed model provider.", 422)
        if control != "MODEL" and provider_id is not None:
            raise TabletopError("SEAT_INVALID", "Only a model seat needs a provider.", 422)
        with _match_lock(mid), _table_action_lock(self.table._match_dir(mid), mid):
            rows = self.seats(mid)
            self.table.combat.set_controller_mode(mid, actor_id=actor_id,
                controller_mode="LOCAL_AUTO" if control == "AI" else "MANUAL")
            rows[actor_id] = {"control": control, **({"provider_id": provider_id} if control == "MODEL" else {}),
                              **({"style": style} if style else {})}
            path = self._path(mid)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
            temporary.replace(path)
            # Without model seats the browser owns Play/Pause again. Do not
            # leave its Auto Step writes fenced by an unreachable server pause.
            if not any(row["control"] == "MODEL" for row in rows.values()) and self.playback(mid)["paused"]:
                self._write_playback(mid, False)
            self._plans.pop(mid, None)
        # No model I/O here, even when enabling a seat during a pending reaction.
        self.table.state(mid)
        return {"actor_id": actor_id, **rows[actor_id]}

    def status(self, mid):
        with self._guard:
            return {"seats": self.seats(mid), "paused": bool(self.playback(mid)["paused"]),
                    **self._status.get(mid, {"status": "IDLE", "text": ""})}

    def decisions(self, mid, limit=30):
        path = self.table._match_dir(mid) / "Agent_Decisions.jsonl"
        if not path.exists():
            return []
        # Tail only: polling never reads a whole long fight's decision history.
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 65536))
            raw = stream.read().splitlines()
        result = []
        for line in raw:
            try:
                result.append(json.loads(line))
            except ValueError:
                continue
        return result[-max(1, min(int(limit), 100)):]

    def _log(self, mid, row):
        with (self.table._match_dir(mid) / "Agent_Decisions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"recorded_at": int(time.time()), **row}, ensure_ascii=False) + "\n")

    @staticmethod
    def _owner(state, actor_id):
        actor = next((a for a in state["presentation"]["actors"] if a["entity_id"] == actor_id), {})
        return actor.get("owner_id") or actor_id

    def _model_owner(self, rows, state, actor_id):
        # Defeated initiative slots belong to the engine's automatic End turn,
        # even when the fighter's saved seat still belongs to a model. Dying
        # fighters remain active and retain their normal decisions.
        actor = next((a for a in state["presentation"]["actors"] if a["entity_id"] == actor_id), {})
        if actor.get("active") is False:
            return None
        owner = self._owner(state, actor_id)
        return owner if rows.get(owner, {}).get("control") == "MODEL" else None

    def observe(self, mid, result):
        if getattr(self._local, "active", False):
            return result
        rows = self.seats(mid)
        if not any(row["control"] == "MODEL" for row in rows.values()):
            return result
        state = result.get("state", result)
        pending = state.get("pending_action")
        reactor = ((pending or {}).get("reaction", {}).get("context") or {}).get("reactor_id")
        model_reaction = reactor and self._model_owner(rows, state, reactor)
        menu = state.get("menu") or {}
        scheduling_menu = menu
        if not menu and state.get('menu_pending'):
            # Scheduling needs only committed control/actor facts. It grants
            # no candidate authority; drive builds a fresh bound menu when it
            # needs choices. Never make a human response await that work.
            actor_id = state['menu_pending']['actor_id']
            actor = next((a for a in state['presentation']['actors'] if a['entity_id'] == actor_id), {})
            scheduling_menu = {'actor_id': actor_id,
                'manual': actor.get('active') is not False and actor.get('controller') in MANUAL_MODES}
        human_action = bool(scheduling_menu.get("manual") and not self._model_owner(rows, state, scheduling_menu.get("actor_id")))
        paused = self.playback(mid)["paused"]
        should_run = model_reaction or (not pending and scheduling_menu and (
            self._model_owner(rows, state, scheduling_menu["actor_id"]) or not scheduling_menu.get("manual")))
        should_run = should_run and (not paused or (model_reaction and human_action))
        if should_run and self.background:
            self.kick(mid)
        # A model-owned prompt must never become a human modal, including reload.
        if model_reaction:
            result = copy.deepcopy(result)
            public_state = result.get("state", result)
            public_state["pending_action"] = None
            public_state["model_deciding"] = True
            if result.get("status") == "REACTION_REQUIRED":
                result["status"] = "MODEL_DECIDING"
                result.pop("reaction", None)
        if menu and self._model_owner(rows, state, menu["actor_id"]):
            if "state" not in result:
                result = dict(result)
            else:
                result = {**result, "state": dict(result["state"])}
            public_state = result.get("state", result)
            public_state["menu"] = {k: menu[k] for k in ("actor_id", "decision_id", "state_version")}
            public_state["menu"].update(control_mode="MODEL", manual=False)
        return result

    def before_action(self, mid):
        """Public requests cannot steal a model turn or answer its reaction."""
        if getattr(self._local, "active", False) or not any(s["control"] == "MODEL" for s in self.seats(mid).values()):
            return None
        self._local.active = True
        try:
            state = self.table.state(mid)
        finally:
            self._local.active = False
        rows = self.seats(mid)
        pending = state.get("pending_action")
        actor = ((pending or {}).get("reaction", {}).get("context") or {}).get("reactor_id") if pending else (state.get("menu") or {}).get("actor_id")
        if actor and self._model_owner(rows, state, actor):
            return self.observe(mid, {"status": "MODEL_DECIDING", "state": state})
        return None

    def guard_action(self, mid, decision, engine):
        """Under-writer-lock check; seat edits and combat writes share this lock."""
        rows = self.seats(mid)
        active_id = decision["context"]["active_actor_id"]
        active = engine.state.actors.get(active_id)
        active_owner = (active.owner_id if active is not None and not active.primary_combatant else None) or active_id
        human_action = (decision["control_mode"] in MANUAL_MODES
                        and rows.get(active_owner, {}).get("control") != "MODEL"
                        and (active is None or active.active))
        playback = self.playback(mid)
        if playback["paused"] and not human_action:
            raise TabletopError("TABLETOP_PAUSED", "Paused. Press Play AI turns to continue.", 409)
        if getattr(self._local, "active", False):
            expected = getattr(self._local, "expected_seats", None)
            if expected is not None and rows != expected:
                raise TabletopError("TABLETOP_STALE", "The fighter's control changed; the table has refreshed.", 409)
            expected_playback = getattr(self._local, "expected_playback", None)
            if not human_action and expected_playback is not None and playback != expected_playback:
                raise TabletopError("TABLETOP_STALE", "AI playback changed; the table has refreshed.", 409)
            return False
        pending = self.table._pending_action(mid, decision["context"])
        actor_id = pending["reaction"]["context"]["reactor_id"] if pending else decision["context"]["active_actor_id"]
        actor = engine.state.actors.get(actor_id)
        if actor is not None and not actor.active:
            return False
        owner = (actor.owner_id if actor is not None and not actor.primary_combatant else None) or actor_id
        return rows.get(owner, {}).get("control") == "MODEL"

    def kick(self, mid):
        with self._guard:
            if mid in self._running or len(self._running) >= 4:
                return
            thread = threading.Thread(target=self._work, args=(mid,), daemon=True, name="model-seat")
            self._running[mid] = thread
            thread.start()

    def _work(self, mid):
        try:
            self.drive(mid)
        except Exception as exc:
            # Exception text may contain a provider's URL/key; keep only its type.
            self._log(mid, {"kind": "ERROR", "error": type(exc).__name__,
                            "text": "Model control stopped (%s: %s). Reopen the table to try again."
                                    % (type(exc).__name__, _safe_error_text(exc))})
        finally:
            with self._guard:
                self._running.pop(mid, None)
                self._status[mid] = {"status": "IDLE", "text": ""}

    def _ask(self, provider, prompt, view):
        # Enforce the selected profile at the final dispatch boundary too,
        # including the very first prompt and any repair/replan.
        from .compact import PROMPT_BUDGET, TINY_PROMPT_BUDGET
        from .providers import choices_settings
        profile = provider.get("prompt_profile", "full")
        cap = {"compact": PROMPT_BUDGET, "tiny": TINY_PROMPT_BUDGET}.get(profile)
        if (cap and len(prompt) > cap) or (profile == "choices" and len(prompt.encode("utf-8")) > choices_settings(provider)[0]):
            raise ValueError("Selected profile exceeds prompt budget")
        if not self._calls.acquire(blocking=False):
            raise TimeoutError("Provider capacity exhausted")
        answers = queue.Queue(maxsize=1)
        def call():
            try:
                png = self.render_png(view) if self.render_png and provider.get("vision") else None
                answers.put((True, self.provider(provider, prompt, png)))
            except Exception as exc:
                answers.put((False, exc))
            finally:
                self._calls.release()
        threading.Thread(target=call, daemon=True, name="model-provider").start()
        try:
            ok, answer = answers.get(timeout=provider["timeout_s"])
        except queue.Empty:
            raise TimeoutError("Model deadline exceeded") from None
        if not ok:
            raise answer
        reply, usage = answer
        return reply, usage

    def own_view(self, mid, state, actor_id, session):
        from combat.senses import perception
        seen = perception(session.engine, session.engine.state.actors[actor_id])
        known = set(seen["creatures"])
        cells = {tuple(cell) for cell in seen["cells"]}
        objects = [{k: obj.get(k) for k in ("id", "x", "y", "name", "kind", "hp", "max_hp", "detail")}
                   for obj in state.get("objects", []) if (obj["x"], obj["y"]) in cells]
        known.update(obj["id"] for obj in objects)
        actors = [{**{key: a.get(key) for key in ("entity_id", "display_name", "team_id", "position",
                    "hit_points", "active", "movement_remaining_ft")},
                   "conditions": [c.get("display_name") or c.get("condition_id") for c in a.get("conditions", [])]}
                  for a in state["presentation"]["actors"] if a["entity_id"] in known]
        visible_rows = {a["entity_id"]: a for a in state["presentation"]["actors"] if a["entity_id"] in known}
        for actor in actors:
            public = visible_rows[actor["entity_id"]]
            if actor.get("position") and public.get("altitude_ft"):
                actor["position"] = {**actor["position"], "z": public["altitude_ft"] // 5}
            # Catalogue sides can group installed characters together; the
            # public runtime side is the current combat relationship.
            actor["team_id"] = public.get("runtime_team_id") or actor.get("team_id")
        own = next((a for a in actors if a["entity_id"] == actor_id), None)
        if own is not None:
            actor = session.engine.state.actors[actor_id]
            own.update(resources=dict(actor.resources), action_available=actor.action_available,
                       bonus_action_available=actor.bonus_action_available, reaction_available=actor.reaction_available)
        policy, _ = self.table.combat.policies.for_actor(actor_id)
        # Roles and posture labels are already expressed in plain Dao language,
        # derived by sphere_dao.controller_policy from the fighter's owner sheet.
        from .dao import dao_view
        dao = dao_view(policy, self.table.combat.source_root)
        from combat.gate5_service import FACTORY_ACTOR_PREFIX, CombatServiceError
        if actor_id.startswith(FACTORY_ACTOR_PREFIX):
            from factory_authoring.sphere_dao import character_dao, sheet_sphere_talents
            try:
                if actor_id not in self._dao:
                    sheet = self.table.combat._factory_owner_sheet(actor_id.removeprefix(FACTORY_ACTOR_PREFIX))
                    self._dao[actor_id] = character_dao(sheet_sphere_talents(sheet))
                profile = self._dao[actor_id]
                if profile:
                    dao = dao_view(policy, self.table.combat.source_root, profile)
            except (FileNotFoundError, ValueError, KeyError, CombatServiceError):
                pass  # Native/saved-only fighters still have their policy role.
        # Sight memory records only observations, never hidden current positions.
        # It is separate from sealed engine state and survives service reloads.
        # Match the table writer's shared thread/cross-process lock order.
        # Independent runners must serialize the entire read/update/replace.
        # Rendering and provider work happen after these locks release.
        with _match_lock(mid), _table_action_lock(self.table._match_dir(mid), mid):
            path = self.table._match_dir(mid) / "Agent_Sight.json"
            memory = json.loads(path.read_text()) if path.exists() else {}
            prior = memory.setdefault(actor_id, {})
            for actor in actors:
                # Observed defeat invalidates the old search anchor. Keep the
                # actor in this view for actions that can target downed bodies.
                if actor.get("active") is False:
                    prior.pop(actor["entity_id"], None)
                    continue
                if actor.get("position"):
                    prior[actor["entity_id"]] = {"position": dict(actor["position"]),
                                               "round": session.engine.state.round_number,
                                               "hostile": int(actor.get("team_id") != own.get("team_id"))}
            last_seen = [row for entity_id, row in sorted(prior.items()) if entity_id not in known]
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(memory, sort_keys=True) + "\n")
            temporary.replace(path)
        view = {"fighter": actor_id, "round": session.engine.state.round_number,
                "match_id": mid, "state_version": session.engine.state.state_version,
                "map": project_map(state.get("map"), seen["cells"], session.engine.grid.width,
                                   session.engine.grid.height, state["presentation"].get("zones") or []),
                "last_seen": last_seen,
                "actors": actors, "objects": objects, "visible_cells": seen["cells"], "dao": dao}
        if seen.get('information_text'):
            view['information'] = list(seen['information_text'])
        return self.redact(view, session, known), known

    def _menu(self, state, known):
        menu = state.get("menu") or {}
        result = {}
        def add(label, option, source, details=None):
            if any(t not in known for t in option.get("target_ids", [])):
                return
            description = {"action": label, "source": source,
                           "targets": option.get("target_ids", []),
                           "destination": option.get("destination"), "options": option.get("option_ids", [])}
            origin = option.get('effect_origin')
            if origin:
                point = origin['position']
                height = f", {point['z'] * 5} feet above ground" if point.get('z') else ''
                description['action'] += f" from {origin['label']} at square {point['x']}, {point['y']}{height}"
            identity = {**description, **({'effect_origin_id': origin['id']} if origin else {})}
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
            result[key] = {"description": {**description, **(details or {})}, "candidate_id": option["candidate_id"]}
        for group in menu.get("actions", []):
            details = {k: group[k] for k in ("description", "cost_label", "economy") if k in group}
            hover = group.get("hover") or {}
            fields = hover.get("fields") or []
            printed_range = next((f.get("value") for f in fields if f.get("label") == "Range"), None)
            if printed_range:
                details["range_label"] = printed_range
            # Structured public prose avoids repeating action economy, range,
            # target eligibility and cost already enforced by the legal row.
            # Keep every other field (including saves, duration and effects).
            if any(f.get("label") == "Effect" for f in fields):
                details["choice_description"] = " ".join(
                    [f["value"] if f["label"] == "Effect" else f["label"] + ": " + f["value"]
                     for f in fields if f["label"] not in {"Action", "Range", "Target", "Cost"}]
                    + list(hover.get("body") or []) + [hover.get("footer") or ""])
            for option in group["options"]:
                add(group["label"], option, group["source_definition_id"],
                    {**details, "expected_damage": option.get("expected_damage")})
        for option in menu.get("moves", []):
            add("Move", option, "Move")
        if menu.get("end_turn"):
            add("End turn", {"candidate_id": menu["end_turn"]}, "End turn")
        return result

    def _builtin(self, mid, session, known, options, cells, ranked_keys=None, scores=None, ranked_slots=None):
        context = self.table.combat.ai_decision_context(session)
        ids = {row["candidate_id"] for row in options.values()}
        visible_cells = {tuple(cell) for cell in cells}
        context = context.model_copy(update={
            "actors": tuple(a for a in context.actors if a.entity_id in known),
            "zones": tuple(z for z in context.zones if z.owner_id in known and (z.center.x, z.center.y) in visible_cells),
            "recent_events": (),
            # Difficulty belongs to built-in AI seats, not model prompt ranking.
            # Retain the incumbent exhaustive scorer for model-seat suggestions.
            "tactics": {},
            "legal_candidates": tuple(c for c in context.legal_candidates if c.candidate_id in ids),
            "team_behavior": context.team_behavior.model_copy(update={"focus_target_id": None})})
        pick = self.table.combat.controller.choose_primary_action(context)
        matches = [(k, v) for k, v in options.items() if v["candidate_id"] == pick.intent.candidate_id]
        key = next((k for k, v in matches if tuple(v["description"]["options"]) == tuple(pick.intent.option_ids)), matches[0][0])
        if ranked_keys is not None:
            by_candidate = {v["candidate_id"]: k for k, v in options.items()}
            ranked_seen = set(ranked_keys)
            # The controller's public record is already ordered by score/tie-break.
            for score in pick.record.scored_alternatives:
                candidate_key = by_candidate.get(score.candidate_id)
                if candidate_key is not None and candidate_key not in ranked_seen:
                    ranked_keys.append(candidate_key)
                    ranked_seen.add(candidate_key)
                if scores is not None and candidate_key is not None and candidate_key not in scores:
                    # Numeric components only: raw scoring prose can contain
                    # source ids or details unsuitable for player options.
                    scores[candidate_key] = {"components": [
                        {"component": c.component, "value": c.value} for c in score.components]}
            # EMBEDMENU presentation seam: native choice remains authoritative;
            # only the bounded candidates offered to model seats are blended.
            from combat import menu_rank
            if menu_rank.enabled() and ranked_slots is not None:
                from .menu_pages import slot_candidate_keys
                # Reuse the table's exact lists, not a second embedding request
                # with different text/perception. Native execution is unchanged.
                ranked_keys[:] = list(dict.fromkeys([key, *slot_candidate_keys(ranked_slots, options, key)]))
                return key, pick.record.explanation
            if menu_rank.enabled():
                actor = session.engine.state.actors.get(session.engine.state.current_actor_id)
                names = [a.display_name for a in context.actors if a.entity_id in known]
                query = menu_rank.situation_text(getattr(actor, "current_hp", None),
                    getattr(actor, "maximum_hp", None), names,
                    goal=menu_rank.sheet_goal(self.table.combat, actor.entity_id))
                totals = {row.candidate_id: row.total for row in pick.record.scored_alternatives}
                rows, slot_ids, numeric = [], {}, {}
                for k, option in options.items():
                    desc = self.redact(option["description"], session, known)
                    if desc.get("action") == "End turn" or not set(desc.get("targets") or []) <= known:
                        continue
                    slot_ids[k] = menu_rank.slot_for(desc.get("economy", "ACTION"), moving=desc.get("action") == "Move")
                    numeric[k] = totals.get(option["candidate_id"], 0)
                    rows.append((k, menu_rank.perceived_text(desc.get("action"), desc.get("choice_description")),
                        menu_rank.tier_from_hostile_effect(desc.get("expected_damage"), bool(desc.get("targets")))))
                blended = menu_rank.rank_ids(query, rows, scores=numeric, slots=slot_ids)
                slots = menu_rank.bounded_slots(blended, slot_ids)
                # Same five-per-slot contract as the table; provider packing
                # can further reduce it to max_options. Keep native fallback.
                # Interleave slots so a small provider cap still sees a move,
                # an Action and a Bonus action rather than only five moves.
                packed = [values[i] for i in range(menu_rank.QUICK_BAR_SIZE)
                          for values in slots.values() if i < len(values)]
                ranked_keys[:] = list(dict.fromkeys([key, *packed]))
        return key, pick.record.explanation

    @staticmethod
    def redact(value, session, known):
        """Remove hidden names/ids even from ability and reaction prose."""
        hidden = [a for a in session.engine.state.actors.values() if a.entity_id not in known]
        replacements = [(a.entity_id, "an unseen creature") for a in hidden]
        replacements += [(a.display_name, "an unseen creature") for a in hidden if a.display_name]
        def clean(item):
            if isinstance(item, str):
                for old, new in sorted(replacements, key=lambda pair: len(pair[0]), reverse=True):
                    item = item.replace(old, new)
                return item
            if isinstance(item, list):
                return [clean(i) for i in item]
            if isinstance(item, dict):
                return {k: clean(v) for k, v in item.items()}
            return item
        return clean(value)

    def _decide(self, mid, actor_id, seat, view, legal, builtin, reason, kind, ranked_keys=(), scores=None,
                dao_policy_top2=None, continuation=None, decision_id=None, slot_ranked=False):
        provider = {"id": seat["provider_id"], "model": "unavailable"}
        name = next((a["display_name"] for a in view["actors"] if a["entity_id"] == actor_id), "The fighter")
        with self._guard:
            self._status[mid] = {"status": "DECIDING", "actor_id": actor_id, "text": f"{name} is deciding…"}
        started = time.monotonic()
        fallback, usage, fallback_error = None, None, None
        decision_menu = None
        seen_prompt, seen_answers, seen_profile = None, None, None
        ranked_frames = []
        capture_id = uuid.uuid4().hex
        plan_record_id = decision_id or capture_id

        def remember_frame(selected, record_type="step"):
            """Keep the actual response binding before staging rewrites its plan.

            Only ranked prompts use this protocol. Navigation and steps have
            separate identities; the assembled executable plan is not a label
            offered by any one frame. Instrumentation never changes execution.
            """
            try:
                ranked_frames.append(copy.deepcopy({
                    "prompt": seen_prompt, "profile": seen_profile, "answers": seen_answers,
                    "selected": selected, "reply": reply, "record_type": record_type,
                    "attempt": attempts, "decision": (used or {}).get("decision")
                    if isinstance(used, dict) else None,
                    "latency_ms": int((time.monotonic() - started) * 1000)}))
            except Exception:
                pass
        stage = "registry"
        attempts, invalid_replies, prompt_chars = 0, 0, 0
        try:
            provider = self.registry.load()[seat["provider_id"]]
            if seat.get("style"):
                # The seat's chosen style overrides the provider's default for every prompt and repair.
                provider = dict(provider, prompt_profile=seat["style"])
            if provider["kind"] == "d1":
                provider = dict(provider, prompt_profile="choices", vision=False)
            deadline = started + provider["timeout_s"]
            limit = provider.get("max_plan_length", 32)
            profile = provider.get("prompt_profile", "full")
            from combat import menu_rank
            pages = None
            # Small letter prompts page observer findings losslessly rather
            # than dropping them or spending the entire budget on the situation.
            # RankedPages retains every legal key, including unranked tails.
            if kind == "TURN" and ((slot_ranked and ranked_keys and menu_rank.enabled())
                                   or (profile == 'choices' and view.get('information'))):
                from .providers import choices_settings
                from .menu_pages import RankedPages, MORE_KEY, MORE_LINE
                _, slot_cap = choices_settings(provider)
                pages = RankedPages(legal, ranked_keys, builtin, slot_cap - 2)
                if profile == "choices":
                    pages.cap = 1
                    pages.first = pages.first[:1]
            selected_steps = []
            if profile in {"compact", "tiny", "choices"}:
                limit = min(limit, 3)
                # Compact is text-only, avoiding image token/prefill overhead.
                provider = dict(provider, vision=False)
            if profile == "choices":
                if continuation is not None and kind == "TURN":
                    # Keys for newly granted movement don't exist yet. After
                    # executing this plan, ask before its implicit End if a
                    # Move first becomes legal. Never override explicit End.
                    continuation["movement"] = not any(r["action"] == "Move" for r in legal.values())
                stage = "options"
                from .providers import choices_settings
                choices_bytes, max_options = choices_settings(provider)
                from .choices import turn_options, reaction_options, build_prompt as choice_prompt, parse_letter, action_signatures
                if continuation is not None and kind == "TURN":
                    continuation["actions"] = action_signatures(legal)
                options = ([] if pages is not None else turn_options(view, legal, builtin, ranked_keys, scores, limit,
                                       choices_bytes, max_options) if kind == "TURN"
                           else reaction_options(legal, builtin))
                if provider["kind"] != "cli":
                    provider = dict(provider, request_options={**provider.get("request_options", {}), "max_tokens": 5})
            repair = None
            # Navigation is deadline-bounded, with no retries or action execution.
            # At most one page per legal key plus the ordinary repair allowance.
            for attempt in range((len(legal) + 2) * (limit + 1) + sum(len(str(r)) for r in legal.values()) if pages is not None else 2):
                stage = "deadline"
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Model deadline exceeded")
                stage = "prompt"
                page_legal = pages.menu() if pages is not None else legal
                if pages is not None and profile != "choices":
                    page_legal = pages.display_menu()
                if profile == "choices":
                    page_options = options
                    if pages is not None:
                        from .menu_pages import choice_frame
                        prompt, offered_choices, offered_keys = choice_frame(
                            view, pages, choices_bytes, selected_steps, repair)
                    else:
                        prompt, offered_choices = choice_prompt(view, page_options, kind, page_legal, repair,
                            choices_bytes, max_options)
                        offered_keys = {key for answer in offered_choices.values() for key in answer.get("plan", [])}
                elif profile in {"compact", "tiny"}:
                    page_builtin = builtin if kind != "TURN" or builtin in page_legal else next(iter(page_legal))
                    prompt = build_prompt(view, page_legal, page_builtin, reason, kind, limit, repair, profile, ranked_keys)
                    offered_keys = set(json.loads(prompt.split("\n", 1)[1])["legal_menu"])
                else:
                    page_builtin = builtin if kind != "TURN" or builtin in page_legal else next(iter(page_legal))
                    prompt = build_prompt(view, page_legal, page_builtin, reason, kind, limit, repair)
                    offered_keys = set(page_legal) if kind == "TURN" else set()
                if pages is not None and profile != "choices" and pages.has_more(offered_keys):
                    first_line, body = prompt.split("\n", 1)
                    prompt = first_line + " Reply MORE to browse remaining legal options without acting.\n" + body
                if pages is not None and profile != "choices":
                    first_line, body = prompt.split("\n", 1)
                    # HTTP providers receive standalone prompts: staged steps
                    # must be explicit, rather than relying on page memory.
                    prompt = (first_line + " You may reply with active steps without End to build a plan; "
                              "choose End explicitly to finish. Steps already chosen: "
                              + json.dumps(selected_steps) + ". Reply DETAILS followed by a current menu key "
                              "to read its next full rules page without acting.\n" + body)
                prompt_chars += len(prompt)
                seen_prompt, seen_profile = prompt, profile
                try:
                    seen_answers = dict(offered_choices) if profile == "choices" else _offered_menu(
                        profile, prompt, page_legal, kind)
                except Exception:
                    # Record capture is observational and cannot affect a seat's decision.
                    seen_answers = None
                # General self-play/instrumentation seam (not tied to any ability):
                # the exact offered letter->payload binding and the controller's own
                # pick for this attempt, so an in-process provider that wants to
                # reproduce the built-in controller's own choice -- rather than guess
                # a fixed letter -- can read it here. A real model provider only ever
                # receives `prompt`; this attribute is never sent over any transport.
                self._last_choice_binding = ({"answers": dict(offered_choices), "builtin": builtin, "kind": kind}
                                             if profile == "choices" else None)
                if provider["kind"] == "d1":
                    decision_menu = decision_payload(prompt)["options"]
                # Building a large prompt (including a repair) consumes the same
                # decision budget. Never dispatch with the pre-build allowance.
                stage = "deadline"
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Model deadline exceeded")
                attempts += 1
                stage = "provider"
                reply, used = self._ask(dict(provider, timeout_s=remaining), prompt, view)
                if isinstance(used, dict):
                    usage = usage or {}
                    if isinstance(used.get("decision"), dict):
                        usage["decision"] = used["decision"]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = used.get(key)
                        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                            usage[key] = usage.get(key, 0) + value
                try:
                    stage = "validation"
                    if profile == "choices":
                        # Legacy plans carry implicit End; ranked choices
                        # compose next steps and require explicit End.
                        parsed = parse_letter(reply, offered_choices)
                        if pages is not None:
                            frame_answer = copy.deepcopy(parsed)
                        if pages is not None and parsed.get("plan") == [MORE_KEY]:
                            remember_frame(parsed, "navigation")
                            pages.advance(offered_keys)
                            repair = None
                            continue
                        if pages is not None:
                            from .menu_pages import DETAIL_KEY, BACK_KEY, SITUATION_KEY, RankedPages
                            if parsed.get("plan") == [BACK_KEY]:
                                remember_frame(parsed, "navigation")
                                pages.back()
                                repair = None
                                continue
                            if parsed.get("plan") == [SITUATION_KEY]:
                                remember_frame(parsed, "navigation")
                                pages.situation_offset = pages.next_situation_offset
                                repair = None
                                continue
                            if parsed.get("plan") == [DETAIL_KEY]:
                                remember_frame(parsed, "navigation")
                                pages.detail_offset = pages.next_detail_offset
                                continue
                            key = parsed["plan"][0]
                            if key not in pages.ends and pages.ends:
                                remember_frame(parsed)
                                selected_steps.append(key)
                                pages = RankedPages(legal, ranked_keys, builtin, 1)
                                if len(selected_steps) >= limit:
                                    pages.remaining = {}
                                    pages.first = []
                                repair = None
                                continue
                            else:
                                parsed = {"plan": [*selected_steps, key]}
                        answer = validate_answer(parsed, legal, kind, limit + 1)
                    else:
                        if pages is not None and str(reply).strip().startswith("DETAILS "):
                            detail_key = str(reply).strip().split(" ", 1)[1]
                            if detail_key not in page_legal:
                                raise ValueError("Details must use a current menu key.")
                            remember_frame({"plan": ["DETAILS " + detail_key]}, "navigation")
                            pages.more_rules(detail_key)
                            continue
                        if pages is not None and str(reply).strip().upper() == "MORE" and pages.has_more(offered_keys):
                            remember_frame({"plan": ["MORE"]}, "navigation")
                            pages.advance(offered_keys)
                            repair = None
                            continue
                        offered = json.loads(prompt.split("\n", 1)[1])["legal_menu"] if profile in {"compact", "tiny"} else page_legal
                        parsed = parse_reply(reply)
                        if pages is not None:
                            frame_answer = copy.deepcopy(parsed)
                            from .menu_pages import RankedPages
                            plan = parsed.get("plan") if isinstance(parsed, dict) else None
                            if (isinstance(plan, list) and plan and all(isinstance(k, str) and k in legal for k in plan)
                                    and plan[-1] not in pages.ends and pages.ends):
                                if set(parsed) - {"plan", "why"} or len(selected_steps) + len(plan) >= limit:
                                    raise ValueError("Leave one plan step for End turn.")
                                remember_frame(parsed)
                                selected_steps.extend(plan)
                                pages = RankedPages(legal, ranked_keys, builtin, pages.cap)
                                if len(selected_steps) == limit - 1:
                                    pages.remaining = {}
                                    pages.first = []
                                repair = None
                                continue
                            if isinstance(plan, list):
                                parsed = {**parsed, "plan": [*selected_steps, *plan]}
                        answer = validate_answer(parsed, legal if pages is not None else offered, kind, limit)
                    if pages is not None:
                        remember_frame(frame_answer)
                    break
                except ValueError as exc:
                    invalid_replies += 1
                    if invalid_replies >= 2:
                        raise
                    # Only our bounded validation message is sent back. Never
                    # include raw replies, parser excerpts or transport errors.
                    repair = str(exc)
            else:
                raise ValueError("Menu navigation did not produce an executable choice.")
        except Exception as exc:
            fallback = "timeout" if isinstance(exc, TimeoutError) else "provider or invalid reply"
            fallback_error = failure_detail(exc, stage, provider)
            answer = {"plan": [builtin]} if kind == "TURN" else dict(builtin)
        row = {"actor_id": actor_id, "kind": kind, "provider_id": seat["provider_id"], "decision_id": decision_id,
               "model": provider.get("model", provider["id"]), "latency_ms": int((time.monotonic() - started) * 1000),
               "tokens": {k: v for k, v in (usage if isinstance(usage, dict) else {}).items() if k in {"prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(v, int)},
               "chosen": answer.get("plan", answer), "built_in_pick": builtin, "fallback": fallback,
               "dao_policy_top2": (list(dict.fromkeys([builtin, *ranked_keys]))[:2] if kind == "TURN"
                                   else dao_policy_top2 if dao_policy_top2 is not None else [builtin]),
               "protocol": VERSION, "attempts": attempts, "invalid_replies": invalid_replies,
               "prompt_chars": prompt_chars, "fallback_error": fallback_error,
               "text": f"{name}: model took too long; built-in AI chose instead." if fallback == "timeout" else
                       f"{name}: built-in AI chose because the model could not answer." if fallback else
                       f"{name}: model chose its next move."}
        if isinstance(usage, dict) and "decision" in usage:
            row["decision"] = usage["decision"]
        if decision_menu is not None:
            row["decision_menu"] = decision_menu
        staged_recording = bool(ranked_frames) and (len(ranked_frames) > 1 or bool(selected_steps))
        if staged_recording:
            # The turn log describes execution, not a choice from the final
            # End menu. Per-frame D1 labels/probabilities belong to the records.
            row.pop("decision", None)
            row.pop("decision_menu", None)
            row["decision_records"] = [f"{capture_id}:frame:{frame['attempt']}" for frame in ranked_frames]
        if kind == "TURN":
            def summary(option):
                return {k: v for k, v in option.items() if k not in {"description", "choice_description"}}
            row["chosen_menu"] = [summary(legal[k]) for k in answer["plan"]]
            row["built_in_menu"] = summary(legal[builtin])
            if not fallback:
                row["text"] = f"{name} plans: " + ", then ".join(legal[k]["action"] for k in answer["plan"]) + "."
        elif not fallback:
            verb = "uses" if answer["selection"] == "USE" else "declines"
            row["text"] = f"{name}: model {verb} {legal['ability']}."
        self._log(mid, row)
        if staged_recording:
            for frame, record_id in zip(ranked_frames, row["decision_records"]):
                frame_row = dict(row, chosen=frame["selected"].get("plan", frame["selected"]),
                                 fallback=None, latency_ms=frame["latency_ms"])
                if frame["decision"] is not None:
                    frame_row["decision"] = frame["decision"]
                self._record(mid, frame_row, kind, record_id, frame["prompt"], frame["profile"],
                             frame["answers"], legal, frame["selected"], builtin,
                             metadata={"plan_decision_id": plan_record_id, "record_type": frame["record_type"],
                                       "reply": frame["reply"], "attempt": frame["attempt"],
                                       "assembled_plan": row["chosen"], "plan_fallback": bool(fallback)})
        else:
            self._record(mid, row, kind, decision_id, seen_prompt, seen_profile, seen_answers, legal, answer, builtin)
        if kind == "TURN":
            answer["fallback"] = bool(fallback)
        return answer

    def _record(self, mid, row, kind, decision_id, prompt, profile, answers, legal, answer, builtin, *, metadata=None):
        """Training record of what the seat saw and chose; never affects the fight.

        Choice-letter prompts record letter -> label and letter -> answer. Other
        prompts record the legal menu's keys and labels, and the chosen plan.
        Ranked responses record their own binding and raw reply, with a parent
        plan id and assembled execution stored separately from the chosen step.
        """
        if prompt is None:
            return
        try:
            data_dir = self.table.combat.userdata_root
            if profile == "choices":
                options = decision_payload(prompt)["options"]
            elif kind == "REACTION":
                options = copy.deepcopy(answers or {})
            else:
                options = {k: (legal[k]["action"] if kind == "TURN" else answers[k])
                           for k in (answers or {}) if k in legal}
                if metadata and metadata["record_type"] == "navigation":
                    # JSON-profile navigation controls are prose instructions,
                    # not combat keys. Give their actual replies a local binding.
                    navigation = str(metadata["reply"]).strip()
                    answers = {**(answers or {}), navigation: answer}
                    options = {**options, navigation: navigation}
            def offered_id(target):
                return next((k for k, v in (answers or {}).items() if v == target), None)
            def built_in_offer():
                # A turn plan is offered as a whole; the built-in pick is its first step.
                if kind != "TURN":
                    return offered_id(builtin)
                return next((k for k, v in (answers or {}).items() if v.get("plan", [None])[0] == builtin), None)
            if profile == "choices":
                chosen_id = offered_id(answer) or (built_in_offer() if row["fallback"] else None)
            else:
                chosen_id = (offered_id(answer) if metadata and metadata["record_type"] == "navigation"
                             else _chosen_key(answers, answer, kind))
            record = {"ts": int(time.time()), "match_id": mid, "decision_id": decision_id,
                      "actor_id": row["actor_id"], "provider_id": row["provider_id"], "kind": kind,
                      "prompt_profile": profile, "prompt": prompt, "options": options,
                      "answers": answers, "chosen_id": chosen_id, "chosen": row["chosen"],
                      "built_in_id": built_in_offer(), "built_in_pick": builtin,
                      "fallback": bool(row["fallback"]), "latency_ms": row["latency_ms"]}
            if "decision" in row:
                record["probabilities"] = row["decision"].get("probabilities")
            if metadata:
                record.update(metadata)
            append_decision(data_dir, record)
        except Exception:
            # A record that cannot be built is dropped, never raised into the fight.
            return

    def _reaction(self, mid, state, pending, session, rows):
        prompt = pending["reaction"]
        actor_id = prompt["context"]["reactor_id"]
        owner = self._model_owner(rows, state, actor_id)
        if not owner:
            return False
        view, known = self.own_view(mid, state, actor_id, session)
        raw = pending.get("reaction_context")
        if not raw:
            automatic = pending["method"] == "auto_step"
            if pending["method"] == "act":
                # Existing manual pauses can acquire a full context through the
                # public noncommitting preview; never guess a reaction packet.
                candidates = self.table.combat.decision(mid, session=session)["context"]["legal_candidates"]
                candidate = next(c for c in candidates if c["candidate_id"] == pending["request"]["candidate_id"])
                payload = {k: candidate.get(k) for k in ("candidate_id", "decision_id", "state_version",
                           "actor_id", "target_ids", "destination", "option_ids")}
            else:
                metadata = self.table.combat._read_metadata(mid, session)
                provider_pending = metadata.get("pending_provider_decision")
                if provider_pending:
                    payload = provider_pending["payload"]
                else:
                    from combat.gate4_context import build_decision_context
                    policy, _ = self.table.combat.policies.for_actor(session.engine.state.current_actor_id)
                    primary = build_decision_context(session.engine, policy, for_ai=True)
                    payload = self.table.combat.controller.choose_primary_action(primary).intent.model_dump(mode="json")
            preview = self.table.combat.preview(mid, payload, pending.get("reactions", []), controller_preview=automatic)
            raw = preview.get("reaction_context")
            if raw and any(raw.get(k) != v for k, v in prompt["context"].items()):
                raise TabletopError("TABLETOP_STALE", "The fight moved on; the table has refreshed.", 409)
            if not raw:
                raise TabletopError("TABLETOP_STALE", "The saved choice has changed. Reopen the table.", 409)
        # reaction_choices lists alternative menu contexts for the table's prompt; the
        # primary context is the only one the answer contract validates against.
        context = ReactionContext.model_validate({k: v for k, v in raw.items() if k != "reaction_choices"})
        context = context.model_copy(update={"recent_events": (), "choice_trigger": None,
            **{k: getattr(context, k) if getattr(context, k) in known else None
               for k in ("attacking_actor_id", "protected_target_id", "damaged_target_id")}})
        choice = self.table.combat.controller.choose_reaction(context)
        builtin = {k: v for k, v in choice.decision.model_dump(mode="json").items()
                   if k in {"selection", "option_ids", "spend"}}
        # Presentation text can name a hidden attacker: never send those fields.
        legal = {"ability": prompt["reaction"],
                 **{k: prompt[k] for k in ("action", "affected", "trigger", "summary", "rules", "moment") if k in prompt},
                 "choice": copy.deepcopy(prompt.get("choice")),
                 "spend_options": list(context.spend_options) or [0]}
        ids, inverse = {}, {}
        if legal["choice"]:
            # Entity option IDs still identify targets here. Use only the
            # current own-view projection, before replacing IDs for transport.
            labels = [o.get("label") for o in legal["choice"]["options"]]
            visible = {a["entity_id"]: a for a in view["actors"]}
            for option in legal["choice"]["options"]:
                target = visible.get(option["id"])
                if labels.count(option.get("label")) > 1 and target and target.get("position"):
                    p = target["position"]
                    option["label"] += f" (at {p['x']},{p['y']})"
            ids = {f"option:{i}": option["id"] for i, option in enumerate(legal["choice"]["options"], 1)}
            inverse = {v: k for k, v in ids.items()}
            for option in legal["choice"]["options"]:
                option["id"] = inverse[option["id"]]
            legal["choice"]["preferred"] = [inverse[i] for i in legal["choice"].get("preferred", []) if i in inverse]
            builtin["option_ids"] = [inverse[i] for i in builtin["option_ids"] if i in inverse]
        elif context.legal_option_ids:
            ids = {f"option:{i}": oid for i, oid in enumerate(context.legal_option_ids, 1)}
            inverse = {v: k for k, v in ids.items()}
            legal["choice"] = {"options": [{"id": k, "label": v} for k, v in ids.items()],
                               "minimum": 0, "maximum": len(ids), "allow_decline": True}
            builtin["option_ids"] = [inverse[i] for i in builtin["option_ids"] if i in inverse]
        legal = self.redact(legal, session, known)
        reason = self.redact(choice.record.explanation, session, known)
        # Reaction records score USE versus DECLINE, not alternate targets.
        # Retain only ranked, executable responses; never invent target scores.
        ranking = [builtin]
        for score in sorted(choice.record.scored_alternatives, key=lambda s: -s.total):
            selection = score.candidate_id.rsplit(":", 1)[-1]
            spec = context.extension_choice
            ordered = ((*spec.preferred_option_ids, *(o for o in spec.option_ids
                        if o not in spec.preferred_option_ids)) if spec else context.legal_option_ids)
            candidate = {"selection": selection, "option_ids": [inverse[i] for i in
                         (ordered[:spec.maximum_selections] if spec else ordered) if i in inverse]
                         if selection == "USE" else [],
                         "spend": (int(score.option_ids[0]) if score.option_ids else 0)
                         if selection == "USE" and not spec else 0}
            try:
                candidate = validate_answer(candidate, legal, "REACTION")
            except ValueError:
                continue
            if candidate not in ranking:
                ranking.append(candidate)
            if len(ranking) == 2:
                break
        answer = self._decide(mid, actor_id, rows[owner], view, legal, builtin, reason, "REACTION",
                              dao_policy_top2=ranking, decision_id=context.decision_id)
        row = {**prompt["context"], "selection": answer["selection"],
               "option_ids": [ids[i] for i in answer.get("option_ids", [])], "spend": answer.get("spend", 0)}
        if self.seats(mid) != rows:
            return False
        getattr(self.table, pending["method"])(mid, **pending["request"],
            reactions=[*pending.get("reactions", []), row], defer_menu=True)
        return True

    def drive(self, mid, *, max_steps=64):
        """Bounded server work; stop at a human decision or completed/paused fight.

        No network while locked. A stale table binding is never replayed blindly;
        clear the plan and rebuild the menu. Refresh schedules the next chunk.
        """
        self._local.active = True
        count = 0
        try:
            for _ in range(max_steps):
                rows = self.seats(mid)
                self._local.expected_seats = rows
                self._local.expected_playback = self.playback(mid)
                if not any(s["control"] == "MODEL" for s in rows.values()):
                    break
                # The table verifies this exact loaded boundary before reusing
                # it for presentation. A changed journal falls back to a cold
                # read; the existing menu-version check then rejects our old
                # session. Provider replies still face normal commit validation.
                session = self.table.combat._load_session(mid)
                state = self.table.state(mid, _session=session)
                if state["presentation"].get("terminal"):
                    break
                menu_version = (state.get("menu") or {}).get("state_version")
                if menu_version is not None and menu_version != session.engine.state.state_version:
                    self._plans.pop(mid, None)
                    continue
                if self.table.combat._read_metadata(mid, session).get("paused"):
                    break
                pending = state.get("pending_action")
                menu = state.get("menu") or {}
                human_action = bool(menu.get("manual") and not self._model_owner(rows, state, menu.get("actor_id")))
                if self.playback(mid)["paused"] and not (pending and human_action):
                    break
                try:
                    if pending:
                        if not self._reaction(mid, state, pending, session, rows):
                            break
                    else:
                        menu = state.get("menu") or {}
                        actor_id = menu.get("actor_id")
                        owner = self._model_owner(rows, state, actor_id)
                        if not owner:
                            self._plans.pop(mid, None)
                            if menu and not menu.get("manual"):
                                self.table.auto_step(mid, state["last_sequence"], [], menu["decision_id"],
                                                     menu["state_version"], defer_menu=True)
                            else:
                                break
                        else:
                            view, known = self.own_view(mid, state, actor_id, session)
                            options = self._menu(state, known)
                            from .action_options import expand_menu
                            options = expand_menu(options, session.engine, view,
                                                  candidates=self.table.combat._legal_candidates(session))
                            if not options:
                                break
                            identity = (actor_id, session.engine.state.round_number, session.engine.state.current_slot_index)
                            saved = self._plans.get(mid)
                            plan = list(saved[1]) if saved and saved[0] == identity else []
                            automatic = bool(saved and saved[0] == identity and saved[2])
                            follow_up = bool(saved and saved[0] == identity and len(saved) > 3 and saved[3])
                            previous_actions = saved[4] if saved and saved[0] == identity and len(saved) > 4 else None
                            newly_available_action = False
                            if previous_actions is not None:
                                from .choices import action_signatures
                                newly_available_action = bool(action_signatures({k: r["description"] for k, r in options.items()}) - previous_actions)
                            if (not automatic and plan and plan[0] in options
                                    and options[plan[0]]["description"]["action"] == "End turn"
                                    and (newly_available_action or (follow_up and
                                         any(r["description"]["action"] == "Move" for r in options.values())))):
                                plan = []
                                follow_up = False
                                previous_actions = None
                            if not plan or plan[0] not in options:
                                ranked_keys, scores = [], {}
                                builtin, reason = self._builtin(mid, session, known, options, view["visible_cells"], ranked_keys, scores,
                                                               ranked_slots=menu.get("ranked_slots"))
                                legal = self.redact({k: v["description"] for k, v in options.items()}, session, known)
                                reason = self.redact(reason, session, known)
                                if automatic:
                                    plan = [builtin]
                                else:
                                    continuation = {}
                                    answer = self._decide(mid, actor_id, rows[owner], view, legal, builtin, reason, "TURN", ranked_keys, scores,
                                                          continuation=continuation, decision_id=menu["decision_id"], slot_ranked=True)
                                    plan, automatic = answer["plan"], answer["fallback"]
                                    follow_up = bool(not automatic and continuation.get("movement")
                                                     and legal[plan[0]]["action"] != "End turn")
                                    previous_actions = (continuation.get("actions") if not automatic
                                                        and any(legal[k]["action"] == "Move" for k in plan) else None)
                            if self.seats(mid) != rows:
                                break
                            first = options[plan.pop(0)]
                            if first["description"]["action"] == "Move":
                                follow_up = False
                            chosen = first["candidate_id"]
                            self._plans[mid] = (identity, plan, automatic, follow_up, previous_actions)
                            response = self.table.act(mid, chosen, menu["decision_id"], menu["state_version"], state["last_sequence"], [],
                                                      option_ids=first["description"]["options"], defer_menu=True)
                            self._log(mid, {"kind": "STEP", "actor_id": actor_id, "provider_id": rows[owner]["provider_id"],
                                "decision_id": menu["decision_id"], "state_version": menu["state_version"],
                                "candidate_id": chosen, "status": response["status"], "dao_policy_top2": []})
                    count += 1
                except TabletopError as exc:
                    self._plans.pop(mid, None)
                    if exc.code == "TABLETOP_PAUSED":
                        break
                    if exc.code != "TABLETOP_STALE":
                        raise
            return count
        finally:
            self._local.active = False
            self._local.expected_seats = None
            self._local.expected_playback = None
            with self._guard:
                self._status[mid] = {"status": "IDLE", "text": ""}
