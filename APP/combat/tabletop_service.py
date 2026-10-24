"""Tabletop API behaviour on top of the combat service (owner 2026-09-25).

The table asks for one compact ``state`` (the presentation, the map's vectors and
the current fighter's action menu grouped into buttons), submits a chosen candidate
with ``act`` and polls ``events`` for what happened since the last event it saw,
including the dice each roll used.  Every rule is still decided by the engine: the
table only ever submits candidate IDs the engine issued for the current decision.
"""

from __future__ import annotations

import contextlib
import functools
import json
import threading
import uuid
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from app.core import FoundryError

from .commit_diagnostics import latest_commit_divergence
from . import ground_text
from . import journal_feed
from .history_feed import format_history_feed, concealed_condition_instances
from .status_text import printed_rules as _rules_texts
from .tabletop import (
    ButtonStore,
    TabletopError,
    auto_buttons,
    battlefield_as_map,
    dice_rows,
    journal_since,
    sheet_library,
    sheet_summary,
    table_section,
)

MANUAL_MODES = {"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"}
FACTORY_PREFIX = "actor:factory."
#: What a prompt says about a creature whose id no longer resolves to anyone in the fight. A player
#: reads a name or this, never an entity id like "actor:factory.summon:3" (change standard item 13).
_UNKNOWN_CREATURE = "a creature"


@functools.lru_cache(maxsize=1)
def _typed_mechanics_catalog(path: str, mtime_ns: int) -> dict[str, Any]:
    """Reuse the immutable typed catalog across Grow requests; invalidate on authority replacement."""
    return json.loads(Path(path).read_bytes())["mechanics"]


# One request at a time per fight in this server (owner 2026-09-30: "Another local process currently owns this match
# directory" when the table's poll, a state read and an AI step landed together): the fight's writer lock is taken
# non-blocking, so concurrent requests of the same server must queue here instead of racing for it.
_MATCH_LOCKS: dict[str, threading.RLock] = {}
_MATCH_LOCKS_GUARD = threading.Lock()
_MENU_BUILD_LOCKS: dict[str, threading.RLock] = {}


def _match_lock(match_id: str) -> threading.RLock:
    with _MATCH_LOCKS_GUARD:
        return _MATCH_LOCKS.setdefault(str(match_id), threading.RLock())


def _menu_build_lock(match_id: str) -> threading.RLock:
    """One compact build per fight; background work never takes the writer lock.

    State readers can join preparation already in progress instead of doing
    the same expensive pure enumeration simultaneously. The versioned combat
    cache still decides whether any completed result is reusable.
    """
    with _MATCH_LOCKS_GUARD:
        return _MENU_BUILD_LOCKS.setdefault(str(match_id), threading.RLock())


#: How long a table request waits for another one to finish before telling the player to try again. The fight's
#: writer lock is taken non-blocking, so two windows on the same table really do collide; queueing briefly turns
#: the ordinary double-click into two ordinary steps instead of a refusal.
TABLE_BUSY_WAIT_S = 3.0
_TABLE_BUSY_POLL_S = 0.05
#: What the player is told. Plain words, no code names: the same table is being used by someone else right now.
TABLE_BUSY_MESSAGE = "Another action on this table is still finishing. Wait a moment, then try again."


def _is_busy(exc: BaseException) -> bool:
    """Whether ``exc`` is the deliberate "someone else holds this table" refusal rather than a real failure.

    ``gate3_storage`` raises this for a non-blocking lock it could not take (MATCH_STORAGE_LOCKED). It is a
    correct guard, not a defect -- it just has to reach the player as a plain "try again" instead of a 500.
    """
    code = getattr(getattr(exc, "diagnostic", None), "code", None) or getattr(exc, "code", None)
    return code == "MATCH_STORAGE_LOCKED" or "currently owns this match directory" in str(exc)


@contextlib.contextmanager
def _table_action_lock(match_dir: Path, match_id: str, wait_s: float | None = None):
    """Hold the cross-process table-action lock, queueing while another window holds it.

    ``LocalMatchWriterLock`` takes its lock non-blocking and raises when it cannot, so a near-simultaneous second
    request used to fail outright. Retry until ``wait_s`` (:data:`TABLE_BUSY_WAIT_S`) is spent, then let the
    refusal through so the caller can turn it into a 409. Reuse the portable storage lock implementation on a
    separate table-only lock file, so the combat transaction remains responsible for its own writer lock.
    """
    from .gate3_storage import LocalMatchWriterLock

    wait_s = TABLE_BUSY_WAIT_S if wait_s is None else wait_s
    deadline = time.monotonic() + wait_s
    while True:
        stack = contextlib.ExitStack()
        try:
            stack.enter_context(LocalMatchWriterLock(match_dir / ".tabletop_action.lock", match_id))
        except Exception as exc:  # noqa: BLE001 - only the busy lock is retried; everything else propagates
            if not _is_busy(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(_TABLE_BUSY_POLL_S)
            continue
        with stack:
            yield
        return


def _one_at_a_time(method):
    """Run one table request at a time per fight, and never answer a busy table with a server error.

    The in-process queue above stops this server racing itself. A second *window* is a second request that can
    still find the fight's own writer lock held, and that refusal used to escape as HTTP 500, leaving the player
    with a broken table and nothing to act on. It is a deliberate guard, so it becomes a 409 with a plain
    "try again" the page can show and recover from.
    """
    @functools.wraps(method)
    def wrapper(self, match_id, *args, **kwargs):
        from .typed_executor import rules_snapshot
        from .tabletop import text_snapshot
        from .zones import terrain_snapshot

        with _match_lock(match_id), rules_snapshot(), text_snapshot(), terrain_snapshot():
            try:
                return method(self, match_id, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - only the busy table is translated; everything else is raised
                if not _is_busy(exc):
                    raise
                raise TabletopError("TABLETOP_BUSY", TABLE_BUSY_MESSAGE, 409) from exc
    return wrapper


def _pending_writer(method):
    """Reserve a table action across processes, from version check through publication.

    Reads and nested state/event responses do not acquire this lock; a request that cannot get it in time is
    answered by :func:`_one_at_a_time` with a 409 rather than a server error.
    """
    @functools.wraps(method)
    def wrapper(self, match_id, *args, **kwargs):
        with _table_action_lock(self._match_dir(match_id), match_id):
            return method(self, match_id, *args, **kwargs)
    return wrapper


def _rules_texts() -> dict[str, str]:
    """The owner's printed text per mechanic id (read once). Restored in round 19: tt/p6-tooltips removed it while
    tt/n1-prompts' decision text still calls it."""
    global _RULES_TEXTS
    if _RULES_TEXTS is None:
        path = Path(__file__).resolve().parents[1] / "authority" / "typed_mechanics" / "rules_text.json"
        _RULES_TEXTS = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return _RULES_TEXTS


_RULES_TEXTS: dict[str, str] | None = None


def _press_cost_label(action: Any, cost_text: Any) -> str:
    """What pressing this button costs, in the words the owner printed, for a player who knows only basic D&D.

    A general seam over one action's own economy, keyed on no ability: a Button that stores a choice (Hammer Rebuke,
    Crawling Fever, Hidden Strike, every ``setting_only`` selector) is economy ``NONE`` and costs no Action, so the table
    must not print a Bonus Action under it -- the fight's charge was always right (gate2_engine only spends the Bonus
    Action for ``EconomyKind.BONUS_ACTION``); only the caption lied. Ordinary Actions, Bonus Actions and Reactions keep
    the caption they always had, and a "No Action" ability that still costs a pool says so instead of "Free".
    """
    economy = str(getattr(action, "economy", "") or "")
    costs = getattr(action, "costs", None)
    pool = cost_text(list(costs)) if callable(cost_text) and costs else ""
    if economy == "NONE":
        return pool or "Free"
    caption = {"ACTION": "Action", "BONUS_ACTION": "Bonus", "REACTION": "Reaction"}.get(economy, "Action")
    return f"{caption}, {pool}" if pool else caption


def _acts_on_itself(affected: str, actor_name: str, affected_id: str, actor_id: str) -> bool:
    """Whether the creature an ability acted on is the creature acting.

    Identity is the creature's id, never its printed name: two owners can field two
    summons that print the same name ("Warhorse"), so equal names are no proof that
    nothing else was named, and a genuinely different creature then vanished from the
    sentence (OCF3 review). Names stay the comparison only when a packet carries no ids
    at all, which is every older saved fight.
    """
    left, right = str(affected_id or "").strip(), str(actor_id or "").strip()
    if left and right:
        return left == right
    affected, actor_name = str(affected or "").strip(), str(actor_name or "").strip()
    return bool(affected) and affected == actor_name


def _uses_phrase(action: str, affected: str, actor_name: str, preposition: str = "on",
                 *, affected_id: str = "", actor_id: str = "") -> str:
    """"uses <ability> [on <creature>]": the clause an Ask-me question uses to name what happened.

    A self-only ability has no second creature to name, and "Song Sheruo uses Stomping Step on
    Song Sheruo" read as if the ability landed on somebody else (OC13; Stomping Step, a mantles
    or teleport step choice, and any plug-in that records ``affected_id`` as the actor). The target
    is therefore named only when it is a creature other than the one acting, compared by the
    trigger's own ids (see :func:`_acts_on_itself`), never by the two printed names. The ability,
    the creature acting and the question's own option labels still say what is being chosen, so
    nothing a player needs is lost (change standard 9).
    """
    affected, actor_name = str(affected or "").strip(), str(actor_name or "").strip()
    if not affected or _acts_on_itself(affected, actor_name, affected_id, actor_id):
        return f"uses {action}"
    return f"uses {action} {preposition} {affected}"


def _notify_driver(method):
    """Optional server decision driver: called AFTER table locks are released.

    driver.observe(match_id, result) returns a public response and may schedule
    work, but must never do provider I/O on the request thread. None is inert.
    Used by model seats; any future server-owned controller can use this seam.
    before_action may defer a public request. guard_action runs under the writer
    lock with the checked decision/engine and prevents a concurrent seat change
    taking effect between that early check and commit; True defers the action.
    """
    @functools.wraps(method)
    def wrapper(self, match_id, *args, **kwargs):
        if kwargs.get("prepare_only"):
            # Preparation commits nothing, so no driver turn may start from it.
            return method(self, match_id, *args, **kwargs)
        depth = getattr(self._driver_depth, "value", 0)
        driver = self.decision_driver
        if driver is not None and depth == 0 and method.__name__ in {"act", "auto_step"}:
            deferred = driver.before_action(match_id)
            if deferred is not None:
                return deferred
        self._driver_depth.value = depth + 1
        try:
            result = method(self, match_id, *args, **kwargs)
        finally:
            self._driver_depth.value = depth
        return driver.observe(match_id, result) if driver is not None and depth == 0 else result
    return wrapper


class TabletopService:
    def __init__(self, combat: Any, data_root: Path):
        self.combat = combat
        self.decision_driver = None
        self.prewarm_menus = False
        self._warm_guard = threading.Lock()
        self._warm_requests = OrderedDict()
        self._warm_running = False
        self._driver_depth = threading.local()
        self._activity_lock = threading.Lock()
        self._last_requests: dict[str, float] = {}
        self.buttons = ButtonStore(Path(data_root) / "tabletop_buttons")
        self._names: dict[str, tuple[dict[str, str], dict[str, str]]] = {}
        # Geometry only: no engine, candidate ids or mutable menu rows retained.
        self._area_previews: OrderedDict[tuple, tuple[tuple[int, int], ...]] = OrderedDict()
        self._area_previews_lock = threading.Lock()
        # Creature ids each viewer has been shown (GHOSTMARK1BF9). Bounded to 256 viewers; in-process only, so a
        # restart forgets them and the browser then purges its unconfirmed marks (no state is written to disk).
        self._shown_ids_lock = threading.Lock()
        self._shown_ids: OrderedDict[tuple, frozenset[str]] = OrderedDict()
        # Derived fog only; bounded to eight matches and one saved version each.
        # Viewer rows are filled lazily so an own-view request does not build
        # perception for every fighter on the map.
        self._fog_cache: OrderedDict[str, tuple[int, dict[str, dict]]] = OrderedDict()
        # Read-only recorded rolls, bounded to eight matches and one state each.
        self._initiative_cache: OrderedDict[str, tuple[tuple[int, int], dict[str, int]]] = OrderedDict()
        self._summary_cache: OrderedDict[str, tuple[tuple[int, int], str]] = OrderedDict()
        # Built table states, reused only while every input is unchanged (combat/table_state_cache.py).
        from .table_state_cache import StateReuse
        self._state_reuse = StateReuse()

    def record_request(self, match_id: str) -> None:
        """Remember an HTTP request for an existing match, in process memory only."""
        if (self._match_dir(match_id) / "Manifest.json").is_file():
            with self._activity_lock:
                self._last_requests[match_id] = time.monotonic()

    def activity(self) -> list[dict[str, Any]]:
        """Read recent-request matches without loading, recovering or changing a fight.

        The published manifest uses the engine's terminal_result for fight end.
        Deleted matches have no manifest and are no longer deploy blockers.
        Reading this endpoint must not itself refresh request activity.
        """
        with self._activity_lock:
            requests = list(self._last_requests.items())
            now = time.monotonic()
        rows = []
        for match_id, last_request in requests:
            try:
                manifest = json.loads((self._match_dir(match_id) / "Manifest.json").read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            rows.append({"match_id": match_id, "seconds_since_request": now - last_request,
                         "finished": manifest.get("terminal_result") is not None})
        return rows

    def _schedule_menu(self, match_id, result):
        """Queue the exact committed boundary; the worker takes no writer lock.

        One daemon per table, latest request per match, bounded to eight fights.
        It never simulates turns or shares a mutable engine with a request.
        """
        pending = (result.get('state') or {}).get('menu_pending')
        if not self.prewarm_menus or not pending:
            return
        with self._warm_guard:
            self._warm_requests[match_id] = pending['state_version']
            self._warm_requests.move_to_end(match_id)
            while len(self._warm_requests) > 8:
                self._warm_requests.popitem(last=False)
            if self._warm_running:
                return
            self._warm_running = True
            try:
                threading.Thread(target=self._warm_menus, name='table-menu-warm', daemon=True).start()
            except RuntimeError:
                # Best-effort preparation must never turn a committed action
                # into an HTTP error when a worker cannot be started.
                self._warm_running = False

    def _prepare_committed_menu(self, match_id, engine):
        """Start preparation from a saved action, before any response projection.

        The response may include the client's complete menu_read projection.
        That choice must not suppress preparation or make ordinary reads warm.
        """
        if not engine.state.terminal_result:
            self._schedule_menu(match_id, {'state': {'menu_pending': {
                'state_version': engine.state.state_version}}})

    def _warm_menus(self):
        import logging
        from .movement_menu import capture
        from .lazy_menu import query
        from .typed_executor import rules_snapshot
        from .tabletop import text_snapshot
        from .zones import terrain_snapshot
        while True:
            with self._warm_guard:
                if not self._warm_requests:
                    self._warm_running = False
                    return
                match_id, version = self._warm_requests.popitem(last=False)
            try:
                with _menu_build_lock(match_id):
                    # Recheck after joining any foreground build. An older
                    # queued request must not evict the newer version's cache.
                    session = self.combat._load_session(match_id)
                    engine = session.engine
                    if engine.state.state_version != version or engine.state.terminal_result:
                        continue
                    actor_id = engine.state.current_actor_id
                    if not actor_id or self.combat._mode_for_actor(
                            self.combat._read_metadata(match_id, session), session, actor_id) not in MANUAL_MODES:
                        continue
                    # Full saved-state/input identity, including control modes.
                    # A later commit cannot consume these derived entries.
                    with rules_snapshot(), text_snapshot(), terrain_snapshot(), capture(), query():
                        self.combat.decision(match_id, session=session, table_header=True)
            except Exception:
                logging.getLogger(__name__).exception('Background menu preparation failed for %s', match_id)

    # ------------------------------------------------------------ helpers
    def _match_dir(self, match_id: str) -> Path:
        return Path(self.combat._match_dir(match_id))

    def _pending_action_path(self, match_id: str) -> Path:
        return self._match_dir(match_id) / "Tabletop_Pending_Action.json"

    def _divergence_diagnostic(self, match_id: str) -> dict[str, Any] | None:
        """The last recorded "this fight's result differed from the table's prediction" note, if any.

        Read from the saved fight's own directory (combat/commit_diagnostics.py), so the table still
        shows it after the service is reloaded or the fight is reopened on another day. The word
        ``notice`` is the line meant for a player; the hashes beside it are for whoever reads the file.
        """
        return (getattr(self.combat, "commit_divergence_notices", {}).get(match_id)
                or latest_commit_divergence(self._match_dir(match_id)))

    def _diagnostic_fields(self, match_id: str) -> dict[str, Any]:
        """Optional public table fields, absent for fights without a notice."""
        diagnostic = self._divergence_diagnostic(match_id)
        return {"divergence_diagnostic": diagnostic} if diagnostic is not None else {}

    def _pending_action(self, match_id: str, menu: dict[str, Any] | None) -> dict[str, Any] | None:
        try:
            value = json.loads(self._pending_action_path(match_id).read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("schema") not in {"TabletopPendingAction.v1", "TabletopPendingAction.v2"}:
            return None
        request = value.get("request") or {}
        if (not isinstance(request, dict) or value.get("method") not in {"act", "auto_step"}
                or not isinstance(value.get("reaction"), dict) or not isinstance(value.get("reactions"), list)):
            return None
        # The combat journal is authoritative. Even a crash after commit but before
        # unlink cannot resurrect a request from an earlier decision. Unbound v1
        # automatic records cannot be safely recovered; v1 manual records can.
        if (not menu or request.get("decision_id") != menu.get("decision_id")
                or request.get("state_version") != menu.get("state_version")):
            return None
        return value

    def _save_pending_action(self, match_id: str, value: dict[str, Any] | None) -> None:
        path = self._pending_action_path(match_id)
        if value is None:
            path.unlink(missing_ok=True)
            return
        # The table writer reservation isolates publication. Reuse storage's
        # portable same-directory atomic replace and file/directory flushes.
        from .gate3_storage import atomic_write_bytes

        atomic_write_bytes(path, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def _pending_response(self, match_id, pending, after):
        return {"status": "REACTION_REQUIRED", "reaction": pending["reaction"],
                "events": self.events(match_id, after), "state": self.state(match_id)}

    def _check_pending_request(self, match_id, menu, method, request, reactions, engine=None):
        """Reserve the action and answers; let a newly AI-owned chooser resolve.

        Control changes apply to every ability's pending choice. Replay the
        same request with its earlier answers when its chooser is now automatic;
        manual choosers retain the saved prompt until they answer it.
        """
        pending = self._pending_action(match_id, menu)
        if pending:
            original = pending["request"]
            options_changed = "option_ids" in original and original["option_ids"] != request.get("option_ids")
            if pending["method"] != method or options_changed or any(original.get(k) != v for k, v in request.items() if k != "after"):
                raise TabletopError("TABLETOP_PENDING", "Answer the saved choice before starting another action.", 409)
            prior = pending.get("reactions") or []
            if not reactions or reactions == prior:
                reactor = (pending["reaction"].get("context") or {}).get("reactor_id")
                actor = engine.state.actors.get(reactor) if engine is not None else None
                owner = (actor.owner_id if not actor.primary_combatant else None) if actor is not None else None
                mode = (getattr(engine, "typed_control_modes", {}) or {}).get(owner or reactor, "MANUAL")
                if mode not in MANUAL_MODES:
                    reactions[:] = prior
                    return None
                return self._pending_response(match_id, pending, request["after"])
            if reactions[:len(prior)] != prior:
                raise TabletopError("TABLETOP_PENDING", "Earlier answers must stay with the saved choice. Reopen the fight.", 409)
        return None

    def _names_for(self, match_id: str, engine: Any = None) -> tuple[dict[str, str], dict[str, str]]:
        """Actor and action display names for a match (fixed for its lifetime).  ``engine``: one the caller has loaded."""
        if match_id not in self._names:
            if engine is None:
                engine = self.combat._load_session(match_id).engine
            actors = {actor_id: actor.display_name for actor_id, actor in engine.state.actors.items()}
            definitions = {source_id: getattr(row, "display_name", source_id) for source_id, row in engine.action_catalog.items()}
            # Reactions and plug-in passives (including d20 rewrites) are not actions.
            # Keep their feature names available for the feed and decision prompts.
            for store in ("typed_reaction_rows", "typed_passive_rows"):
                for rows in getattr(engine, store, {}).values():
                    for row in rows:
                        if row.get("name"):
                            definitions.setdefault(row["feature_id"], row["name"])
                            for mode in row.get("reaction_modes") or []:
                                definitions.setdefault(f"{row['feature_id']}:mode:{mode['index']}",
                                    f"{row['name']} — {mode['label']}")
            self._names[match_id] = (actors, definitions)
            if len(self._names) > 64:
                self._names.pop(next(iter(self._names)))
        return self._names[match_id]

    def _map_section(self, match_id: str) -> dict[str, Any] | None:
        path = self._match_dir(match_id) / "Arena_Battlefield.json"
        if not path.is_file():
            return None
        arena = json.loads(path.read_text(encoding="utf-8"))
        tabletop = arena.get("tabletop")
        # Authored geometry is presentation-only and independent of surviving
        # engine objects. Expose every kind for contextual art (walls, props,
        # future renderers), without rewriting the sealed arena or fight state.
        objects = arena.get("map_objects") or []
        if tabletop:
            return {**tabletop, "objects": objects}
        return {**table_section(battlefield_as_map(arena)), "map_id": None, "objects": objects}

    @staticmethod
    def _last_sequence(match_dir: Path) -> int:
        journal = match_dir / "Journal.ndjson"
        last = 0
        if journal.is_file():
            with journal.open("rb") as stream:
                lines = stream.read().splitlines()
            for line in reversed(lines):
                if line.strip():
                    row = json.loads(line)
                    sequences = [int(event.get("sequence", 0)) for event in row.get("events") or []]
                    last = max(sequences or [0])
                    break
        return last

    @staticmethod
    def _menu(decision: dict[str, Any], names: dict[str, str], definitions: dict[str, str] | None = None,
              engine: Any | None = None, *, header_only: bool = False) -> dict[str, Any]:
        """Project the player menu, or the same automatic header without discarded rows.

        Conditional standing offers describe an ordinary-price fallback only
        when the acting creature has enough remaining movement to pay it.
        This is presentation of the shared standing quote, not a new decision.
        """
        context = decision["context"]
        if header_only and decision["control_mode"] not in MANUAL_MODES:
            return {"decision_id": context["decision_id"], "state_version": context["state_version"],
                    "actor_id": context["active_actor_id"], "control_mode": decision["control_mode"],
                    "manual": False}
        moves, groups, end_turn = [], {}, None
        roll_preview_cache = {}
        actor = (getattr(engine, "state", None).actors.get(context.get("active_actor_id"))
                 if engine is not None and getattr(engine, "state", None) is not None else None)
        for candidate in context["legal_candidates"]:
            kind = candidate["kind"]
            if kind == "MOVE":
                cost = candidate.get("movement_cost_ft")
                if isinstance(cost, int) and actor is not None and hasattr(engine, "_drag_multiplier"):
                    cost *= engine._drag_multiplier(actor)
                moves.append({"candidate_id": candidate["candidate_id"], "destination": candidate["destination"],
                              "cost_ft": cost, "path": candidate.get("canonical_path") or [],
                              "movement_mode": (candidate.get("metadata") or {}).get("movement_mode", "walk"),
                              # Already computed by the engine's own cell_candidate_metadata hook
                              # (combat/movement_routes.py); carried through for menu ranking only
                              # (_rank_menu below), same as expected_damage is for action options.
                              "hazard_exposure": bool((candidate.get("metadata") or {}).get("hazard_exposure")),
                              **({"can_jump_down": True} if (candidate.get("metadata") or {}).get("can_jump_down") else {})})
                continue
            if kind == "END_TURN":
                end_turn = candidate["candidate_id"]
                continue
            source = candidate["source_definition_id"]
            label = (definitions or {}).get(source) or str(candidate.get("display_name") or source).split(" at ")[0]
            group = groups.setdefault(source, {"source_definition_id": source, "kind": kind, "label": label, "options": []})
            if (candidate.get('metadata') or {}).get('lazy_action'):
                group['lazy'] = True
                continue
            if (candidate.get('metadata') or {}).get('placement_picker'):
                group['destination_choice'] = True
                group['placement_picker'] = True
            standing_cost = (candidate.get('metadata') or {}).get('standing_cost_ft')
            if standing_cost is not None:
                metadata = candidate.get('metadata') or {}
                ordinary_cost = metadata.get('standing_ordinary_cost_ft')
                if metadata.get('standing_discount_conditional'):
                    if actor is not None and ordinary_cost is not None and actor.movement_remaining_ft < ordinary_cost:
                        group['cost_label'] = (f'Movement only — {standing_cost} ft with the owner’s approval; '
                            f'you have {actor.movement_remaining_ft} ft left and cannot pay the ordinary '
                            f'{ordinary_cost} ft cost; no Action')
                    else:
                        group['cost_label'] = (f'Movement only — {standing_cost} ft if the offer is approved; '
                                               f'otherwise {ordinary_cost} ft after you confirm; no Action')
                else:
                    group['cost_label'] = f'Movement only — {standing_cost} ft; no Action'
            if (candidate.get("metadata") or {}).get("prepared"):
                group["prepared"] = candidate["metadata"]["prepared"]
            targets = list(candidate.get("target_ids") or [])
            area = candidate.get("area") or None
            previews = {}
            if engine is not None and actor is not None:
                from .roll_reasons import attack_preview
                action = engine.action_catalog.get(source)
                if action is not None:
                    for target_id in targets:
                        target = engine.state.actors.get(target_id)
                        if target is not None:
                            key = (source, target_id)
                            if key not in roll_preview_cache:
                                try:
                                    roll_preview_cache[key] = attack_preview(engine, actor, target, action)
                                except ValueError:
                                    # A broken extension still fails the actual
                                    # transaction. A forecast must not prevent
                                    # the player seeing or leaving the table.
                                    roll_preview_cache[key] = {'mode': None, 'mode_sources': [],
                                        'text': 'Roll mode preview unavailable. The action will validate its effects before rolling.'}
                            preview = roll_preview_cache[key]
                            if preview is not None:
                                previews[target_id] = preview
            group["options"].append({
                "candidate_id": candidate["candidate_id"], "target_ids": targets,
                "target_names": [names.get(target, target) for target in targets],
                "destination": candidate.get("destination"), "option_ids": candidate.get("option_ids") or [],
                **({'effect_origin': candidate['metadata']['effect_origin']}
                   if (candidate.get('metadata') or {}).get('effect_origin') else {}),
                "area": area, "label": (candidate.get('metadata') or {}).get('target_label') or candidate.get("display_name"),
                "expected_damage": (candidate.get("metadata") or {}).get("expected_damage"),
                "roll_previews": previews,
            })
        return {
            "decision_id": context["decision_id"], "state_version": context["state_version"],
            "actor_id": context["active_actor_id"], "control_mode": decision["control_mode"],
            "manual": decision["control_mode"] in MANUAL_MODES,
            "moves": moves, "actions": list(groups.values()), "end_turn": end_turn,
        }

    @staticmethod
    def _rank_menu(menu: dict[str, Any] | None, engine: Any, **ranking_inputs) -> None:
        """General presentation seam; ranking never changes execution authority.

        Optional combat/known/destination_provider inputs are documented in
        menu_rank.rank_menu. Menu construction stays separate for MENUSPEED.
        """
        from . import menu_rank
        menu_rank.rank_menu(menu, engine, **ranking_inputs)

    # ------------------------------------------------------------ API
    def _initiative_totals(self, match_id: str, engine: Any) -> dict[str, int]:
        """Recorded initiative only, reused across refreshes of the same saved state.

        Never rolls dice or writes fight data. The table's per-match lock and
        shared cache lock protect the bounded cache; callers only read its map.
        """
        if engine is None:
            return {}
        key = (engine.state.state_version, len(engine.events))
        with self._area_previews_lock:
            cached = self._initiative_cache.get(match_id)
            if cached is None or cached[0] != key:
                totals = {event.actor_id: event.payload["total"] for event in engine.events
                          if event.event_type == "INITIATIVE_ROLLED"}
                self._initiative_cache[match_id] = (key, totals)
            self._initiative_cache.move_to_end(match_id)
            while len(self._initiative_cache) > 8:
                self._initiative_cache.popitem(last=False)
            return self._initiative_cache[match_id][1]

    def _fight_summary(self, match_id: str, engine: Any) -> dict[str, Any]:
        """General read-only journal projection, bounded to eight saved matches.

        State version also invalidates final actor snapshots; event count avoids
        reaggregating an unchanged journal. Cache JSON so the C decoder returns
        isolated values without a Python deep-copy walk on every refresh. This
        does not add ability behaviour or saved-state fields.
        """
        from .fight_summary import build_summary

        key = (engine.state.state_version, len(engine.events))
        with self._area_previews_lock:
            cached = self._summary_cache.get(match_id)
            if cached is None or cached[0] != key:
                self._summary_cache[match_id] = (key, json.dumps(build_summary(engine, match_id), separators=(",", ":")))
            self._summary_cache.move_to_end(match_id)
            while len(self._summary_cache) > 8:
                self._summary_cache.popitem(last=False)
            return json.loads(self._summary_cache[match_id][1])

    @_one_at_a_time
    def summary(self, match_id: str) -> dict[str, Any]:
        """Read recorded statistics, including a partial summary before fight end."""
        session = self._load_state_session(match_id)
        return self._fight_summary(match_id, session.engine)

    def _load_state_session(self, match_id: str):
        """Retry one read that collided with another process's save; never retry a write."""
        try:
            return self.combat._load_session(match_id)
        except Exception as exc:
            if (getattr(exc, "status_code", None) != 409
                    or getattr(getattr(exc, "diagnostic", None), "code", None) != "COMBAT_CONTENT_NOT_READY"):
                raise
            time.sleep(0.15)
            return self.combat._load_session(match_id)

    def _remembered_in_match(self, match_id: str, engine: Any, fog: bool, fog_view: str | None,
                             fog_actor_ids: tuple[str, ...], presentation: dict[str, Any],
                             remembered_ids: tuple[str, ...] | None) -> list[str] | None:
        """Which of the browser's remembered creatures are still in the fight, for this viewer only.

        Under fog, "shown" is what this viewer perceives now (the same perception the fog answer uses: its own
        creatures and every creature its senses reach), accumulated per viewer so a creature that slips out of sight
        keeps its answer. Unfogged reads show everyone, so they answer for every id in the fight. An id the viewer was
        never shown gets no answer, so asking about a hidden fighter reveals nothing. Returns None when no ids were asked.
        """
        in_fight = {actor.entity_id for actor in engine.state.actors.values()}
        if not fog:
            return None if remembered_ids is None else sorted(set(remembered_ids) & in_fight)
        # Record what this viewer perceives on EVERY fog read, even one that asks about no ids, so a creature
        # seen on an earlier read keeps its answer after it slips out of sight.
        viewers = self._own_fog_viewers(engine, fog_actor_ids) if fog_view == 'own' else None
        perceived = self._fog_perception(match_id, engine, viewers)
        shown_now = set(perceived)
        for row in perceived.values():
            shown_now.update(row.get("creatures", []))
        key = (match_id, fog_view, tuple(sorted(fog_actor_ids)))
        with self._shown_ids_lock:
            shown = self._shown_ids.pop(key, frozenset()) | shown_now
            self._shown_ids[key] = shown
            while len(self._shown_ids) > 256:
                self._shown_ids.popitem(last=False)
        if remembered_ids is None:
            return None
        return sorted(set(remembered_ids) & shown & in_fight)

    @_notify_driver
    @_one_at_a_time
    def state(self, match_id: str, *, fog: bool = False, fog_view: str | None = None,
              fog_actor_ids: tuple[str, ...] = (), include_menu: bool = True, _session=None,
              compact_moves: bool = False, lazy: bool = False, remembered_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
        """Read the current snapshot; choices may be requested separately.

        ``include_menu=False`` performs no next-decision enumeration or ranking.
        It clears candidate-bearing presentation and returns a version stamp;
        clients must discard their old menu and read a fresh full state before
        choosing. The default preserves the complete API/clipboard projection.
        A repeated read whose inputs are all unchanged is answered with a copy of
        the last build (combat/table_state_cache.py); the answer is the same.
        """
        if lazy and include_menu:
            from .lazy_menu import query
            with query():
                return self.state(match_id, fog=fog, fog_view=fog_view, fog_actor_ids=fog_actor_ids,
                                  include_menu=include_menu, _session=_session, compact_moves=True)
        if compact_moves and include_menu:
            from .movement_menu import capture
            with _menu_build_lock(match_id), capture():
                return self.state(match_id, fog=fog, fog_view=fog_view, fog_actor_ids=fog_actor_ids,
                                  include_menu=include_menu, _session=_session, remembered_ids=remembered_ids)
        def build():
            return self._built_state(match_id, fog=fog, fog_view=fog_view, fog_actor_ids=fog_actor_ids,
                                     include_menu=include_menu, _session=_session, remembered_ids=remembered_ids)
        reuse = getattr(self, "_state_reuse", None)
        if _session is not None or reuse is None:  # a post-commit answer is built from the caller's engine, never kept
            return build()
        # Reuse the last answer to this exact request while nothing it depends on changed (combat/table_state_cache.py).
        # Below _notify_driver, so model seats still observe every read; keyed on the compact-move capture, not the
        # argument, because the compact read reaches here through the call above.
        from . import movement_menu
        key = (match_id, bool(fog), fog_view, tuple(fog_actor_ids), bool(include_menu), movement_menu.active(),
               None if remembered_ids is None else tuple(remembered_ids))
        return reuse.read(key, build, lambda: self._state_inputs(match_id))

    def _state_inputs(self, match_id: str) -> tuple:
        """Everything a table state is built from that can change while the server runs (combat/table_state_cache.py)."""
        from . import table_state_cache as inputs

        match_dir = self._match_dir(match_id)
        if not (match_dir / "FactoryIntegration.json").is_file():
            # A fight without saved metadata derives it (seats, visuals) on every read: never kept.
            raise LookupError("fight metadata is derived, not saved")
        data_root = self.buttons.root.parent
        library = getattr(self.combat, "combatant_library", None)
        notice = getattr(self.combat, "commit_divergence_notices", {}).get(match_id)
        return (self.combat._fingerprint(match_id),
                inputs.folder_files(match_dir, skip=("Journal.ndjson",)),
                inputs.folder_files(match_dir / "Snapshots", content=False),
                repr(notice),
                inputs.shared_inputs(),
                inputs.tree_files(data_root / "tabletop_tokens"),
                inputs.folder_files(self.buttons.root),
                inputs.project_files(getattr(library, "install_root", None)),
                inputs.switches(),
                inputs.code_identity(self, self.combat))

    def _built_state(self, match_id: str, *, fog: bool, fog_view: str | None, fog_actor_ids: tuple[str, ...],
                     include_menu: bool, _session, remembered_ids: tuple[str, ...] | None = None) -> dict[str, Any]:
        # The fight is loaded once for the whole answer (a big fight takes half a second to load) and read, never changed,
        # here; what depends only on its saved state (legal candidates, the menu) is worked out once per state.
        # Internal post-commit presentation seam. Never trust a caller's engine
        # without matching the exact journal/state and immutable input boundary.
        session = (self.combat.presentation_session(_session)
                   if _session is not None and _session.match_id == match_id else None)
        if session is None:
            session = self._load_state_session(match_id)
        engine = session.engine
        # The table streams its history feed from /events, so the live boundary's feed (a replay of the whole journal) is skipped.
        from . import lazy_menu
        lazy_query = lazy_menu.active(engine)
        presentation = self.combat.presentation(match_id, feed=False, session=session,
                                                include_candidates=include_menu and not lazy_query)
        if engine is not None:
            # Physical weapon copies still in this creature's possession (drawn or
            # stowed), so the sheet can show "Biao Qiang (Javelin) ×2" and drop to
            # ×1 after one is thrown. The table's menu stays per-copy.
            from .weapon_delivery import available_weapons
            copies = {actor.entity_id: sorted(key for key in available_weapons(engine, actor, include_busy=True)
                                               if ".weapon." in key)
                      for actor in engine.state.actors.values()}
            presentation = {**presentation, "actors": [
                {**row, "weapon_copies": copies[row["entity_id"]]}
                if row.get("entity_id") in copies else row
                for row in presentation.get("actors", [])]}
        initiative = self._initiative_totals(match_id, engine)
        for row in presentation.get("actors", []):
            actor = engine.state.actors.get(row["entity_id"]) if engine is not None else None
            # Only summons use their owner's slot; ordinary late joiners have no roll.
            owner = actor.owner_id if actor is not None and actor.summon is not None else None
            row["initiative"] = initiative.get(owner or row["entity_id"])
            if owner:
                row["initiative_from"] = owner
            if actor is not None:
                from .ai_tiers import effective_tier, tier_label
                row["ai_tier"] = effective_tier(actor, getattr(engine, "ai_tier_overrides", {}))
                row["ai_label"] = tier_label(row["ai_tier"])
        if engine is not None:
            from .display_values import effective_defenses, effective_movement

            live_values = {actor.entity_id: {**effective_defenses(engine, actor),
                                             "speed_ft": effective_movement(engine, actor) if actor.active else 0}
                           for actor in engine.state.actors.values()}
            from .posture import walking_extra, prone_conditions
            for row in presentation.get('actors', []):
                actor = engine.state.actors.get(row['entity_id'])
                if actor is not None and (prone_conditions(actor) or walking_extra(engine, actor)):
                    row['walking_distance_remaining_ft'] = actor.movement_remaining_ft // (1 + walking_extra(engine, actor))
            presentation = {**presentation, "actors": [
                {**row, "defenses": [
                    ({**defense, "value": live_values[row["entity_id"]]["armor_class"]}
                     if defense.get("defense_id") == "defense:armor_class" else defense)
                    for defense in row.get("defenses", [])],
                 "speed_ft": live_values[row["entity_id"]]["speed_ft"],
                 "movement_remaining_ft": row.get("movement_remaining_ft", 0) if row.get("active") else 0}
                if row.get("entity_id") in live_values else row
                for row in presentation.get("actors", [])]}
        actors, definitions = self._names_for(match_id, engine)
        # Read-only, generic AC provenance for the inspector and connected sheet.
        # Unnamed extension bonuses remain an explicit remainder, never guessed.
        if engine is not None:
            from . import typed_reactions

            for row in presentation.get("actors", []):
                actor = engine.state.actors.get(row["entity_id"])
                if actor is not None:
                    row["armor_base"] = int(actor.armor_class)
                    row["armor_modifiers"] = [
                        {"source": (definitions.get(mod.source_definition_id)
                                    if definitions.get(mod.source_definition_id) != mod.source_definition_id else None) or "Active effect",
                         "value": int(mod.value)}
                        for mod in actor.modifiers.values()
                        if mod.target_field == "armor_class" and mod.operation == "ADD"]
                    # The creature's current Resistances, Vulnerabilities and Immunities,
                    # read from the same defence rows damage resolution weighs
                    # (combat/typed_reactions.py defense_display), so the sheet's
                    # Defences card cannot disagree with the fight.
                    row["damage_defenses"] = typed_reactions.defense_display(engine, actor, definitions)
                    from .roll_reasons import standing
                    row['roll_effects'] = standing(engine, actor)
        if engine is not None and engine.state.objects:  # an object is aimed at by name, like a fighter
            from .object_rules import label

            actors = {**actors, **{object_id: label(obj) for object_id, obj in engine.state.objects.items()}}
        menu = None
        if include_menu and not presentation.get("terminal"):
            try:
                menu = self._menu(self.combat.decision(match_id, session=session, table_header=True),
                                  actors, definitions, engine, header_only=True)
            except Exception as exc:  # noqa: BLE001 - a table without a menu still shows the fight
                menu = {"error": str(getattr(exc, "message", exc))[:300]}
                from .table_state_cache import decline
                decline("menu")  # retried by the next read, never repeated from a kept answer
            if menu and not menu.get("manual"):
                menu = {key: menu[key] for key in ("decision_id", "state_version", "actor_id", "control_mode", "manual") if key in menu}
        carrying = self._carrying(match_id, menu, engine)
        # General presentation adapter; all reasons come from the public engine
        # seam and all movement permission still comes from issued candidates.
        from .movement_presentation import for_menu
        if menu and menu.get("manual"):
            if lazy_query:
                menu['lazy'] = True
                menu['movement_preview'] = 'Choose a square to check its route and any movement restrictions.'
            from . import movement_menu
            if movement_menu.active() and not menu['moves']:
                menu['movement_grid'] = getattr(engine, '_cf_menu_routes', ())
            menu["movement_explanation"] = for_menu(engine, menu, actors)
        layer_key = self.combat._state_key(session) if lazy_query and include_menu else None
        layers = self.combat._derived_get(layer_key, 'lazy_table_layers') if layer_key is not None else None
        if layers is not None:
            layers = json.loads(layers)
            menu, shapes = layers['menu'], layers['shapes']
        else:
            self._menu_descriptions(menu, engine)
            shapes = self._shapes(menu, engine)
            with self._area_previews_lock:
                self._round_areas(menu, engine, self._area_previews)
            if layer_key is not None:
                # Exact saved-state/control key, JSON copies for mutable callers.
                # Contains no viewer/fog data and no issued AI candidate cache.
                encoded = json.dumps({'menu': menu, 'shapes': shapes}, ensure_ascii=False)
                self.combat._derived_put(layer_key, 'lazy_table_layers', encoded)
                layers = json.loads(encoded)
                menu, shapes = layers['menu'], layers['shapes']
        # EMBEDMENU seam (owner 2026-10-13): presentation-only ranking/trimming of
        # whatever _menu already built above -- never changes which candidates are
        # offered. Menu CONSTRUCTION (how many groups/options exist per turn) is a
        # separate concern owned by MENUBLOAT (perf/menu-lazy-targets); this is the
        # one marked spot where the two lanes touch the same file.
        self._rank_menu(menu, engine, combat=self.combat, session=session)
        if engine is not None:
            # Named terrain painted on the map (owner 2026-09-28; combat/zones.py map_zones): read from the arena, not the
            # fight's state, so it is added here for the table to draw and describe like any other area.
            from .zones import _hooked_zones, map_zones

            # ... and auras worked out from where their owners stand (docket 2026-09-28, combat/ext/docket_terrain.py).
            # (A door or pillar that fills its square is a hooked wall zone for the engine only; the table draws it as an object.)
            painted = [zone.model_dump(mode="json") for zone in [*map_zones(engine), *_hooked_zones(engine)]
                       if not (zone.trigger_profile or {}).get("object")]
            if painted:
                presentation = {**presentation, "zones": [*(presentation.get("zones") or []), *painted]}
        presentation = self._label_zone_augments(presentation, engine)
        if engine is not None:
            from .status_text import explain_presentation

            from .spatial_areas import display_cells
            from .gate2_runtime_models import ZoneState
            presentation = {**presentation, 'zones': [
                {**row, 'affected_cells': [cell.model_dump(mode='json')
                    for cell in display_cells(engine, ZoneState.model_validate(row))]}
                for row in presentation.get('zones') or []]}
            presentation = explain_presentation(presentation, engine, actors, definitions, self.MARK_READINGS)
        if engine is not None:
            from .flight import profile, remaining
            spatial = {}
            for actor in engine.state.actors.values():
                capability = profile(engine, actor)
                spatial[actor.entity_id] = {"altitude_ft": actor.position.z * 5,
                    "fly_speed_ft": capability.speed_ft, "hover": capability.hover,
                    "flying_movement_remaining_ft": remaining(engine, actor, "fly")}
                roof_height = engine.grid.roof_height_at(actor.position.x, actor.position.y)
                if roof_height is not None:
                    spatial[actor.entity_id].update(roof_height_ft=roof_height,
                        on_roof=engine.grid.roof_supported(actor.position, engine._footprint(actor)))
                if actor.climbing:
                    spatial[actor.entity_id]["climbing"] = True
            presentation = {**presentation, "actors": [
                {**row, **spatial.get(row.get("entity_id"), {})} for row in presentation.get("actors", [])]}
        fog_viewers = self._own_fog_viewers(engine, fog_actor_ids) if fog and fog_view == 'own' else None
        fog_perception = self._fog_perception(match_id, engine, fog_viewers) if fog else {}
        # fog_actor_ids is the screen's explicit player binding. Map selection
        # never expands the private information audience to allies/chosen tokens.
        owned_observers = self._owned_observers(engine, fog_actor_ids)
        for aid, row in fog_perception.items():
            if aid not in owned_observers:
                # Fallen fighters may borrow allied eyes, never private facts.
                row.pop('information', None)
                row.pop('information_text', None)
        own_perception = self._fog_perception(match_id, engine,
            owned_observers) if fog_actor_ids else {}
        observer_information = {aid: {key: row[key] for key in ('information', 'information_text') if key in row}
                                for aid, row in own_perception.items()
                                if row.get('information') or row.get('information_text')}
        remembered = (self._remembered_in_match(match_id, engine, fog, fog_view, fog_actor_ids, presentation,
                                                remembered_ids) if engine is not None else None)
        return {
            "schema": "TianxiaTabletopState.v1",
            **self._diagnostic_fields(match_id),
            "match_id": match_id,
            "presentation": presentation,
            # Answers only for the ids the browser asks about (its remembered creatures) that THIS viewer has been
            # shown and that are still in the fight. Any other id, including a hidden fighter's, gets no answer.
            **({"remembered_in_match": remembered}
               if remembered is not None else {}),
            **({"summary": self._fight_summary(match_id, engine)} if presentation.get("terminal") else {}),
            "map": self._map_section(match_id),
            "terrain_occlusion_policy": engine.grid.occluder_policy if engine is not None else 'cell-v1',
            # What every ground material and named terrain is called and what it does, in plain
            # words (owner 2026-09-30: "hovering over the types of ground ... should bring up the type
            # of material and its effects on movement or anything else"; combat/ground_text.py). The
            # table reads a square's material out of "map" and looks its name-and-effect up here.
            "ground": ground_text.catalog(),
            "menu": menu,
            **({"menu_pending": {"state_version": engine.state.state_version,
                                  "actor_id": presentation.get("current_actor_id")}}
               if not include_menu and not presentation.get("terminal") else {}),
            "items": self._dropped_items(match_id, engine) if engine is not None else [],
            # Destructible objects and structures standing on the map (combat/ext/objects.py): what the table draws and
            # lets the fighter aim at, with their hit points and rules on hover.
            "objects": self._objects(engine),
            # What each Factory fighter carries now, and the fighter's Drop / Pick up choices (owner 2026-09-27;
            # combat/carry.py).
            "carrying": carrying,
            # The talents each fighter's next area of a kind will carry, and its choices (owner 2026-09-27: Numbing
            # Darkness, Pure Darkness with Pitch Black; combat/zones.py _shaped).
            "shapes": shapes,
            "button_states": self._button_states(engine, shapes),
            "unavailable_reasons": self._unavailable_reasons(engine, menu, presentation=presentation),
            # The rules decision used by the tabletop fog. The browser only unions the
            # selected viewers' answers; it does not infer sight from rendered zones.
            "fog_perception": fog_perception,
            **({'observer_information': observer_information} if observer_information else {}),
            "fog_geometry": self._fog_geometry(engine, fog_perception) if fog else None,
            # Retain the exact preview request for refresh recovery.
            "pending_action": self._pending_action(match_id, menu),
            # Each Factory character's circle token (owner 2026-09-27, combat/portraits.py), and one for each summoned
            # creature from its kind's pool.
            "tokens": {**(self._summon_tokens(match_id, engine) if engine is not None else {}),
                       **self._tokens_for([str(actor.get("entity_id")) for actor in (presentation.get("actors") or [])
                                           if isinstance(actor, dict)])},
            "last_sequence": self._last_sequence(self._match_dir(match_id)),
        }

    @_one_at_a_time
    def expand_action(self, match_id: str, source: str, decision_id: str, state_version: int) -> dict[str, Any]:
        """Version-bound human chooser; full native options for just one source.

        Compatible with option composition's action_candidates_for_sources seam.
        The result is read-only and cached only for this exact saved state and
        control mode. Commit still binds and validates through the native path.
        """
        from .lazy_menu import query
        from .gate2_runtime_models import CandidateKind
        from .turn_progress import narrow
        session = self._load_state_session(match_id)
        engine = session.engine
        actor = engine.state.actors.get(engine.state.current_actor_id)
        mode = self.combat._mode_for_actor(self.combat._read_metadata(match_id, session), session,
                                           actor.entity_id if actor else '')
        identity = (engine._candidate_identity(CandidateKind.END_TURN, actor, 'system:combat.turn', (), None)
                    if actor is not None else {})
        if (mode not in MANUAL_MODES or engine.state.pending_resolution is not None
                or engine.state.setup_tasks or engine.state.terminal_result
                or state_version != engine.state.state_version or identity.get('decision_id') != decision_id):
            raise TabletopError('TABLETOP_STALE', 'The fight moved on; refresh your choices.', 409)
        key = self.combat._state_key(session)
        name = ('lazy_action', source)
        cached = self.combat._derived_get(key, name) if key is not None else None
        if cached is not None:
            return json.loads(cached)
        with query(False):
            candidates = engine.action_candidates_for_sources((source,))
            candidates = narrow(session, candidates, verified_records=session.mechanical._records, for_ai=False)
        actors, definitions = self._names_for(match_id, engine)
        from .object_rules import label
        actors = {**actors, **{oid: label(obj) for oid, obj in engine.state.objects.items()}}
        menu = self._menu({'control_mode': mode, 'context': {
            'decision_id': decision_id, 'state_version': state_version, 'active_actor_id': actor.entity_id,
            'legal_candidates': [c.model_dump(mode='json') for c in candidates]}}, actors, definitions, engine)
        self._menu_descriptions(menu, engine)
        with self._area_previews_lock:
            self._round_areas(menu, engine, self._area_previews)
        result = {'decision_id': decision_id, 'state_version': state_version,
                  'source_definition_id': source, 'actions': menu['actions'],
                  'message': '' if candidates else 'This action has no legal targets or options right now.'}
        if key is not None:
            self.combat._derived_put(key, name, json.dumps(result, ensure_ascii=False))
        return result

    @staticmethod
    def _objects(engine: Any) -> list[dict[str, Any]]:
        """Project object state, including optional integer rotation and wall
        attachment metadata. Doors, gates and windows expose ``open`` regardless
        of attachment: explicit simple-door state wins, otherwise nonblocking
        means open, matching the map editor. These presentation fields never
        alter blocking; that remains the objects plug-in's evented state.
        """
        if engine is None:
            return []
        from . import object_rules

        rows = []
        for obj in sorted((*engine.state.objects.values(), *engine.state.map_images.values()), key=lambda row: row.object_id):
            if obj.destroyed:
                continue
            component = obj.component or {}
            # General opt-in for nonphysical map markers: retain native object
            # geometry/perception, without inventing damageable-object stats or
            # publishing private source/condition provenance to observers.
            if component.get("map_marker") == 1:
                rows.append({"id": obj.object_id, "x": obj.position.x, "y": obj.position.y,
                    "name": component.get("name") or "Image", "kind": obj.object_kind,
                    "altitude_ft": obj.position.z * 5, "height_ft": obj.height_ft,
                    "hp": None, "max_hp": None, "ac": None, "blocks": False,
                    "map_marker": 1, "detail": str(component.get("description") or ""), "footprint": "medium"})
                continue
            if obj.current_hp is None:
                continue
            facts = [f"AC {obj.ac}", (f"Damage Threshold {obj.damage_threshold}" if obj.damage_threshold else None),
                     ("immune to " + ", ".join(sorted(kind.lower() for kind in obj.damage_immunities))) if obj.damage_immunities else None,
                     ("vulnerable to " + ", ".join(sorted(kind.lower() for kind in component["vulnerable"]))) if component.get("vulnerable") else None,
                     (("blocks movement and sight while closed" if component.get('interaction') == 'simple_door'
                       else "fills its square until destroyed") if component.get("blocks") else None)]
            rows.append({"id": obj.object_id, "x": obj.position.x, "y": obj.position.y, "name": object_rules.label(obj), "kind": obj.object_kind,
                         "altitude_ft": obj.position.z * 5, "height_ft": obj.height_ft,
                         "hp": obj.current_hp, "max_hp": obj.maximum_hp, "ac": obj.ac, "blocks": bool(component.get("blocks")),
                         "material": component.get("material"), "detail": " · ".join(fact for fact in facts if fact)})
            rows[-1].update({key: component[key] for key in ('rotation', 'mount_axis', 'mount_line', 'nudge') if key in component})
            # How much of its square it covers, so the table can lay out objects sharing one (static/tabletop/object-arrange.js).
            rows[-1]["footprint"] = object_rules.footprint({"kind": obj.object_kind, "size": component.get("size"),
                                                            "mount_axis": component.get("mount_axis")})
            if component.get('interaction') == 'simple_door':
                rows[-1]['open'] = bool(component.get('door_open'))
                rows[-1]['interaction'] = 'simple_door'
                rows[-1]['door_locked'] = component.get('door_locked', 1)
                rows[-1]['door_jammed'] = component.get('door_jammed', 1)
                status = 'Open' if rows[-1]['open'] else 'Closed'
                if rows[-1]['door_locked']:
                    status += ' · Locked'
                if rows[-1]['door_jammed']:
                    status += ' · Stuck'
                rows[-1]['detail'] = status + ' · ' + rows[-1]['detail']
            elif obj.object_kind in {'door', 'gate', 'window'}:
                rows[-1]['open'] = not bool(component.get('blocks'))
        return rows

    @staticmethod
    def _round_areas(menu: dict[str, Any] | None, engine: Any, cache: OrderedDict | None = None) -> None:
        """Where an aimed area lands, in its own shape (owner 2026-09-27: "all the aoes are square"): the engine's preview
        is a square block around the aim point; a sphere is round, a line or cone runs from the user
        (combat/typed_executor.py in_area)."""
        if engine is None or not menu or not menu.get("actions"):
            return
        from .gate2_runtime_models import Position
        from .typed_executor import area_cells

        if cache is None:
            cache = OrderedDict()
        actor = engine.state.actors.get(menu.get("actor_id"))
        if actor is None:
            return
        grid = engine.grid
        geometry = (type(grid), grid.width, grid.height, grid.square_size_ft,
                    frozenset(getattr(grid, "blocked", ()) or ()), actor.position.x, actor.position.y, actor.position.z,
                    repr(grid.terrain_spans))
        for group in menu["actions"]:
            action = engine.action_catalog.get(group.get("source_definition_id"))
            area = ((getattr(action, "parameters", None) or {}).get("typed") or {}).get("area") or {}
            if not area.get("size_ft"):
                continue
            wall = area.get("shape") == "wall"
            from .zones import wall_plan

            shape = json.dumps(area, sort_keys=True, separators=(",", ":"))
            plan = tuple(wall_plan(actor)) if wall else ()
            for option in group.get("options") or []:
                preview, aim = option.get("area"), option.get("destination")
                if not preview or not aim:
                    continue
                key = (geometry, shape, plan, int(aim["x"]), int(aim["y"]), int(aim.get("z", 0)))
                points = cache.get(key)
                if points is None:
                    if wall:  # the wall it would raise there, through the points its user laid out (docket 2026-09-28)
                        from .zones import wall_cells_for

                        cells = wall_cells_for(engine, actor, Position.model_validate(aim), int(area["size_ft"]), int(area.get("thick_ft") or 5))
                    else:
                        cells = area_cells(engine, actor.position, Position.model_validate(aim), area)
                    points = tuple((cell.x, cell.y, cell.z) for cell in cells)
                    cache[key] = points
                    while len(cache) > 4096:
                        cache.popitem(last=False)
                cache.move_to_end(key)
                # Each option owns its JSON, even when its geometry is shared.
                preview["affected_cells"] = [{"x": x, "y": y, **({"z": z} if z else {})} for x, y, z in points]

    @staticmethod
    def _shapes(menu: dict[str, Any] | None, engine: Any) -> dict[str, Any]:
        """{actor id: [{"base", "zone", "name", "current", "options": [...], "augments": [...], "augments_label"}]} -- for each
        ability with choices, the talent its next area carries (owner 2026-09-27: Numbing Darkness; Pure Darkness with
        Pitch Black; combat/zones.py _shaped) and the augments its next use carries (any number; combat/loadout.py), with,
        on the fighter's own turn, the free candidates that change them. Each `choices` row's `activation` flag
        distinguishes a real family activation from a storage-only setting, even when its candidate is unavailable;
        clients may discover it here, but must obtain legal candidates from a fresh preview before use."""
        if engine is None:
            return {}
        from . import loadout, zones
        from . import ext
        from .ext.setting_choices import is_setting_action

        choices: dict[str, str] = {}
        for group in (menu or {}).get("actions") or []:
            parameters = getattr(engine.action_catalog.get(group.get("source_definition_id")), "parameters", None) or {}
            picker_of = parameters.get("menu_parent")  # a picker of an ability, listed in that ability's Options panel
            if (parameters.get("zone_shape") or parameters.get("augment_toggle") or picker_of) and group.get("options"):
                choices[group["source_definition_id"]] = group["options"][0]["candidate_id"]
                group["shape"] = parameters.get("shape_of") or parameters.get("augment_toggle") or picker_of  # listed in the Options panel
        out: dict[str, list[dict[str, Any]]] = {}

        def entry_for(owner: str, base: str) -> dict[str, Any]:
            rows = out.setdefault(owner, [])
            entry = next((row for row in rows if row["base"] == base), None)
            if entry is None:
                entry = {"base": base, "zone": None, "name": getattr(engine.action_catalog.get(base), "display_name", base), "current": None,
                         "options": [], "augments": [], "choices": [], "augments_label": None, "clear_candidate": None}
                rows.append(entry)
            return entry

        for action in engine.action_catalog.values():
            parameters = action.parameters or {}
            actor = engine.state.actors.get(action.owner_id)
            if actor is None:
                continue
            if parameters.get("zone_shape"):
                family = parameters["zone_shape"]
                entry = entry_for(action.owner_id, parameters.get("shape_of") or family)
                entry["zone"] = family
                picked = zones.shaping_of(actor, family)
                talents = list(parameters.get("shape_talents") or [])
                active = talents == picked if picked is not None else (
                    bool(parameters.get("shape_default")) if zones.uses_default_shape(engine, actor) else not talents)
                cost = " + ".join(f"{amount} {resource.split('.')[-1].replace('_', ' ').title()}" for resource, amount in (parameters.get("shape_costs") or {}).items())
                entry["options"].append({"label": parameters.get("shape_label"), "talents": talents, "cost": cost, "active": active,
                                         "button_id": f"act:{action.source_definition_id}",
                                         "candidate_id": choices.get(action.source_definition_id)})
                if active:
                    entry["current"] = parameters.get("shape_label")
            elif parameters.get("menu_parent"):
                entry = entry_for(action.owner_id, parameters["menu_parent"])
                selector = next(iter(ext.run("button_selection", parameters)), None)
                active = TabletopService._condition_selected(actor, selector) if selector else False
                entry["choices"].append({"label": action.display_name, "active": active, "cost": "",
                                         # A family's real activations remain discoverable when saved
                                         # settings make their current candidates unavailable. Clients
                                         # may aim them after drafting; preview still enforces legality.
                                         "activation": not is_setting_action(action),
                                         "button_id": f"act:{action.source_definition_id}",
                                         "candidate_id": choices.get(action.source_definition_id)})
                if active:
                    entry["current"] = action.display_name
            elif parameters.get("augment_toggle"):
                base = parameters["augment_toggle"]
                entry = entry_for(action.owner_id, base)
                if parameters.get("augment_key") is None:
                    entry["clear_candidate"] = choices.get(action.source_definition_id)
                    continue
                loadout_row = next((row for row in (engine.action_catalog[base].parameters.get("augment_loadout") or {}).get("augments") or []
                                    if row["key"] == parameters["augment_key"]), {})
                picked = loadout.chosen(actor, base) or []
                entry["augments"].append({"key": parameters["augment_key"], "name": parameters.get("augment_name"), "on": parameters["augment_key"] in picked,
                                          "button_id": f"act:{action.source_definition_id}",
                                          "cost": " + ".join(f"{amount} {str(resource).split('.')[-1].replace('_', ' ').title()}" for resource, amount in loadout_row.get("costs") or []),
                                          "candidate_id": choices.get(action.source_definition_id)})
        for owner, rows in out.items():
            actor = engine.state.actors.get(owner)
            for entry in rows:
                entry["options"].sort(key=lambda row: (len(row["talents"]), str(row["label"])))
                entry["augments"].sort(key=lambda row: str(row["name"]))
                entry["choices"].sort(key=lambda row: str(row["label"]))
                on = [row["name"] for row in entry["augments"] if row["on"]]
                entry["augments_label"] = " + ".join(on) or None
                # The ability's button casts the chosen combination (combat/loadout.py).
                family = next((row for fam, row in loadout.families(engine).get(owner, []) if fam == entry["base"]), None)
                active = loadout.active_action(entry["base"], family, loadout.chosen(actor, entry["base"])) if family and actor else None
                if active and active != entry["base"]:
                    for group in (menu or {}).get("actions") or []:
                        if group.get("source_definition_id") == active:
                            group["alias_of"] = entry["base"]
        from .ext.attack_modifiers import presentation as modifier_presentation
        modifier_presentation(menu, engine, out)
        if menu is not None:
            from .option_composition import manifest
            menu["composition"] = manifest(menu, engine)
        return out

    @staticmethod
    def _label_zone_augments(presentation: dict[str, Any], engine: Any) -> dict[str, Any]:
        """Older journaled zones get display labels from their bound action, without changing saved state."""
        if engine is None:
            return presentation
        labelled = []
        for zone in presentation.get("zones") or []:
            profile = zone.get("trigger_profile") or {}
            action = engine.action_catalog.get(zone.get("source_definition_id"))
            typed = ((action.parameters or {}).get("typed") or {}) if action else {}
            name = (typed.get("modifier") or {}).get("name")
            if "augments" not in profile and typed.get("augments") and name:
                zone = {**zone, "trigger_profile": {**profile, "augments": str(name).split(" + ")}}
            labelled.append(zone)
        return {**presentation, "zones": labelled}

    @staticmethod
    def _menu_descriptions(menu: dict[str, Any] | None, engine: Any) -> None:
        """Give every fight menu row the cost the compiled definition actually charges, for the button's cost tag.

        The row's ``kind`` only says which slot a candidate resolves in, and a free setting (an augment toggle, a
        stance, a setup pick) is offered as a free action, so a kind alone cannot tell a player it costs nothing.
        ``economy`` is read from the action's own compiled row and is display only: nothing here gates, prices or
        hashes a candidate, so saved fights, candidate ids and the AI's own choice are untouched.
        """
        from .tabletop import _cost_text, engine_button_description, engine_button_description_for_name, engine_button_layout, untyped_button_text

        if engine is not None:
            # Built once, and only if a group turns out to need it: the record ids a "Feature: option" toggle
            # belongs to, which is how a plug-in's button is matched back to its owning ability.
            owned: dict[str, list[dict[str, Any]]] | None = None
            owned_ids: frozenset[str] | None = None
            actor = engine.state.actors.get((menu or {}).get("actor_id") or "")
            for group in (menu or {}).get("actions") or []:
                source = group["source_definition_id"]
                action = engine.action_catalog.get(source)
                if action is not None:
                    row = action.model_dump(mode="json")
                    text = engine_button_description(row)
                    group["economy"] = str(action.economy)
                    group["cost_label"] = _press_cost_label(action, _cost_text)
                    if (action.parameters or {}).get("menu_parent"):
                        group["parent"] = action.parameters["menu_parent"]
                    from . import ext
                    if any(reply is True for reply in ext.run("action_destination_choice", engine, action)):
                        group["destination_choice"] = True
                    # The same description laid out once by the shared formatter
                    # (combat/hover_text.py), so an ability, a Path or a Foundation
                    # reaches the table as one labelled line per printed field
                    # instead of a run of prose. General presentation seam: no
                    # ability id is interpreted. ``description`` above is unchanged
                    # and is still what other surfaces and saved fights use, so
                    # nothing persisted here moves.
                elif group.get("prepared"):
                    from .decision_text import build_decision_text

                    prepared = group["prepared"]
                    actors = {key: actor.display_name for key, actor in engine.state.actors.items()}
                    details = build_decision_text(engine, {"reactor_id": menu["actor_id"],
                        "reaction_source_id": prepared["source_id"], "choice_trigger": {"prepared": prepared}},
                        {"reactor": actors[menu["actor_id"]], "reaction": prepared["label"], "moment": "Prepare this attack on your turn."},
                        actors, {}, _rules_texts())
                    group["description"] = (f"Action now to prepare; Reaction when the named trigger occurs. Expires at the start of your next turn.\n"
                                            f"{details['summary']}\n{details['rules']}")
                    continue
                else:
                    # An engine candidate that is not a catalog action (Hold position).
                    row = {"source_definition_id": source, "display_name": group.get("label")}
                    text = ""
                if not text.strip():
                    # A button with no rules entry of its own: the engine's built-in actions, a plug-in's
                    # "Feature: option" toggle or a standing choice. It used to reach the table with no rule
                    # text at all, and a Core Tempering Expression button silently applied a whole-fight
                    # condition (HUNT108). Same shared text the sheet's buttons already show.
                    if owned is None:
                        owned = {"action_catalog": [{"source_definition_id": key} for key in engine.action_catalog]}
                        owned_ids = frozenset(str(key).split(".", 2)[-1] for key in engine.action_catalog)
                    text = (untyped_button_text(row, owned, owned_ids=owned_ids)
                            or engine_button_description_for_name(group.get("label"), source, row.get("parameters")))
                # General standing-state presentation (combat/ext/__init__.py
                # "attack_state_rows"): an owned state that changes the
                # creature's Unarmed Strikes or natural weapons names itself on
                # the row and states its once-per-turn status. Inert without a
                # provider, so every other row keeps its exact text.
                from . import ext
                for reply in ext.run("attack_state_rows", engine, actor, row):
                    for state in (reply or ()):
                        if not isinstance(state, dict):
                            continue
                        suffix = str(state.get("label") or "").strip()
                        if suffix and f"({suffix})" not in group["label"]:
                            group["label"] = f"{group['label']} ({suffix})"
                        note = str(state.get("note") or "").strip()
                        if note and note not in text:
                            text = f"{text}\n{note}" if text.strip() else note
                group["description"] = text
                group["hover"] = engine_button_layout(row, fallback_text=text)

    @staticmethod
    def _button_states(engine: Any, shapes: dict[str, Any]) -> dict[str, Any]:
        """One presentation flag for each button, shared by the table and connected sheet.

        Standing choices keep their creating action in the plug-in's condition. Shapes
        and augments share conditions, so their flags use the selected option data.
        """
        if engine is None:
            return {}
        out: dict[str, Any] = {}
        from . import ext

        for action in engine.action_catalog.values():
            actor = engine.state.actors.get(action.owner_id)
            if actor is None:
                continue
            parameters = action.parameters or {}
            active = False
            entries = shapes.get(action.owner_id) or []
            if parameters.get("attack_modifier_setting"):
                spec = parameters["attack_modifier_setting"]
                from .ext.attack_modifiers import chosen
                selected = chosen(actor, spec["family"], spec["modifier"])
                active = bool(selected["on"]) if spec["field"] == "on" else selected.get(spec["field"]) == spec["value"]
                if spec["field"] == "on":
                    active = any(row["on"] for entry in entries for row in entry.get("modifiers") or []
                                 if row["button_id"] == f"act:{action.source_definition_id}")
            elif parameters.get("zone_shape"):
                entry = next((row for row in entries if row["base"] == (parameters.get("shape_of") or parameters["zone_shape"])), {})
                active = any(row["active"] for row in entry.get("options") or []
                             if row["talents"] == list(parameters.get("shape_talents") or []))
            elif parameters.get("augment_toggle"):
                entry = next((row for row in entries if row["base"] == parameters["augment_toggle"]), {})
                active = any(row["on"] for row in entry.get("augments") or [] if row["key"] == parameters.get("augment_key"))
            elif action.economy == "NONE" and action.target_kind == "SELF":
                # Derive selectors from existing effects; old saved bundles need no
                # new display fields or recompilation to show independent picks.
                selector = next(iter(ext.run("button_selection", parameters)), None)
                active = TabletopService._condition_selected(actor, selector) if selector else any(
                    condition.source_definition_id == action.source_definition_id
                    and condition.source_actor_id == actor.entity_id for condition in actor.conditions.values())
            entry = next((row for row in entries if row["base"] == action.source_definition_id), {})
            active = bool(active or any(row["active"] and row["talents"] for row in entry.get("options") or [])
                          or any(row["on"] for row in entry.get("augments") or []))
            out.setdefault(action.owner_id, {})[f"act:{action.source_definition_id}"] = {"active": active}
        return out

    @staticmethod
    def _unavailable_reasons(engine: Any, menu: dict[str, Any] | None, *, presentation=None) -> dict[str, str]:
        """Shared read-only button explanations; legality still comes from the engine."""
        if menu and menu.get('lazy'):
            # Only source-wide preconditions are known before expansion. In
            # particular, do not turn an unexpanded object's target into a
            # refusal or trigger a hidden complete-menu availability query.
            frame = getattr(engine, '_cf_availability', None)
            reasons = {f'act:{source}': answer['reason'] for source, answer in (frame[2] if frame else {}).items()
                       if not answer.get('available') and answer.get('reason')}
            # A lazy header is an offer to inspect an action, not a legal choice:
            # candidate-level vetoes run only when it is expanded. Ask each pure
            # source-wide check (combat/ext source_unavailable) so a header that
            # cannot expand at all still explains itself before a click.
            from . import ext
            actor = engine.state.actors.get(menu.get('actor_id')) if engine is not None else None
            if actor is not None:
                for group in menu.get('actions') or []:
                    source = group.get('source_definition_id')
                    key = f'act:{source}'
                    if not group.get('lazy') or not source or key in reasons:
                        continue
                    action = engine.action_catalog.get(source)
                    if action is None:
                        continue
                    reply = next((text for text in ext.run('source_unavailable', engine, actor, action)
                                  if isinstance(text, str) and text.strip()), None)
                    if reply:
                        reasons[key] = reply
            return reasons
        from .action_availability import describe

        return describe(engine, menu, presentation=presentation)

    @staticmethod
    def _condition_selected(actor: Any, selector: dict[str, Any]) -> bool:
        """Declarative selectors for plug-ins that retain several picks in one condition."""
        return any(condition.condition_id == selector["condition"] and condition.source_actor_id == actor.entity_id
                   and all(key in condition.data and condition.data[key] == value for key, value in (selector.get("equals") or {}).items())
                   and all(value in (condition.data.get(key) or []) for key, value in (selector.get("contains") or {}).items())
                   for condition in actor.conditions.values())


    # What a kind of mark means, where the rules define it (owner 2026-09-29: "Resonance doesn't show what it is doing").
    MARK_READINGS = {
        "resonance": "A Resonance Mark (Spirit Awakening, Player Path Chapter): an impression on the soul from the one who placed it; "
                     "only one per Awakener at a time, reapplying refreshes it; not a condition, invisible to ordinary sight; that "
                     "Awakener knows it remains while within 60 feet. Their techniques that read the mark use it.",
        "false_premise": "A False Premise (Illusion, Create Figment): the creature acted on the illusion as if it were real. Only one from a given "
                         "illusionist at a time; it ends when they trigger a Misdirection Response on this creature, when the creature "
                         "recognizes the illusion, or at the start of their next turn.",
        "star_mark": "A Star Mark (Star-Sovereign Core Imprint): the one who placed it marks this creature, point, omen or trace as a star "
                     "on their chart while they hold Old Light. One at a time by default (two in Star-Sovereign Core State); a new one "
                     "replaces the oldest, and it fades at the end of its placer's next turn. Their Sovereign Ray reads it.",
        "vow_mark": "A Vow Mark (Heartbinder): a willing creature the Heartbinder has bound by a vow, until the vow is ended; the Heartbinder may "
                    "hold a number equal to its Proficiency Bonus (a new one ends the oldest). Its Devotion, Stand Together, Heart's Rebuke, "
                    "Borrowed Courage, Chain of Devotion and Unbroken Vow read it.",
        "debt_imprint": "A Debt Imprint (Karma): the Karmic ledger of the one who placed it; a creature holds a combined number of that Karmic's "
                        "Imprints up to their Proficiency Bonus. Debt punishes: talents such as Return the Sting, Invoke the Ledger and "
                        "Settle Minor Account spend it, and Burden of Deeds and the Court of Cause and Effect read it. It is never used to bless.",
        "grace_imprint": "A Grace Imprint (Karma): the Karmic ledger of the one who placed it, for a selfless act; a creature holds a combined "
                         "number of that Karmic's Imprints up to their Proficiency Bonus. Grace protects: talents such as Grace Repaid, Invoke "
                         "the Ledger and Settle Minor Account spend it, and the Court of Cause and Effect reads it. It is never used to punish.",
    }

    def _explain_marks(self, presentation: dict[str, Any], engine: Any, actors: dict[str, str], definitions: dict[str, str]) -> dict[str, Any]:
        """Compatibility entry point; table state uses the shared status builder."""
        from .status_text import explain_marks_compat

        return explain_marks_compat(presentation, engine, actors, definitions, self.MARK_READINGS)


    @staticmethod
    def _owned_observers(engine: Any, owner_ids: tuple[str, ...]) -> set[str]:
        """Bound fighters and summons only; private facts never use ally fallback."""
        if engine is None or not owner_ids:
            return set()
        owned = set(owner_ids) & set(engine.state.actors)
        changed = True
        while changed:
            descendants = {actor.entity_id for actor in engine.state.actors.values()
                           if actor.owner_id in owned}
            changed = not descendants.issubset(owned)
            owned.update(descendants)
        return owned

    @staticmethod
    def _own_fog_viewers(engine: Any, owner_ids: tuple[str, ...]) -> set[str]:
        """Resolve a player's bound fighters and their summons into own-view eyes."""
        owned = TabletopService._owned_observers(engine, owner_ids)
        if not owned:
            return set()
        standing = {actor_id for actor_id in owned
                    if engine.state.actors[actor_id].active}
        if standing:
            return standing
        teams = {engine.state.actors[actor_id].team_id for actor_id in owned}
        return {actor.entity_id for actor in engine.state.actors.values()
                if actor.team_id in teams and actor.active}

    def _fog_perception(self, match_id: str, engine: Any,
                        viewer_ids: set[str] | None = None) -> dict[str, dict[str, list]]:
        """Opt-in presentation seam, cached for this match's saved state version.

        All policy lives in the public senses.perception API. No engine or live
        actor is retained; returns a copy so callers cannot corrupt the cache.
        The state request holds the per-match lock; the shared cache lock also
        serializes cache access between matches.
        """
        import copy
        from .senses import perception

        if engine is None:
            return {}
        with self._area_previews_lock:
            version = engine.state.state_version
            cached = self._fog_cache.get(match_id)
            if cached is None or cached[0] != version:
                self._fog_cache[match_id] = (version, {})
            result = self._fog_cache[match_id][1]
            eligible = (viewer for viewer in engine.state.actors.values()
                        if viewer.active and viewer.position is not None
                        and (viewer_ids is None or viewer.entity_id in viewer_ids))
            for viewer in eligible:
                if viewer.entity_id not in result:
                    result[viewer.entity_id] = perception(engine, viewer)
            self._fog_cache.move_to_end(match_id)
            while len(self._fog_cache) > 8:
                self._fog_cache.popitem(last=False)
            projected = copy.deepcopy({viewer_id: result[viewer_id] for viewer_id in
                                       (viewer_ids if viewer_ids is not None else result)
                                       if viewer_id in result})
            if viewer_ids is None:
                # The union-of-all-eyes fog view transports geometry only.
                # Private information needs an explicitly selected own viewer.
                for row in projected.values():
                    row.pop('information', None)
                    row.pop('information_text', None)
            return projected

    @staticmethod
    def _fog_geometry(engine, perception):
        """Derived, bound 3D scenery for the browser; never saved fight state."""
        from .terrain_occlusion import sight_geometry
        if engine is None:
            return None
        geometry = sight_geometry(engine.grid)
        limits = {aid: row['surface_limits'] for aid,row in perception.items() if row.get('surface_limits')}
        return {**geometry, **({'limits': limits} if limits else {})}

    def _carrying(self, match_id: str, menu: dict[str, Any] | None, engine: Any = None) -> dict[str, Any]:
        """{actor id: {"weight_lb", "capacity_lb", "over", "speed_ft", "items": [...]}} for the Factory fighters, each
        item with whether it is held and, for the fighter whose turn it is, the candidate that drops or picks it up."""
        from . import carry

        if engine is None:
            try:
                engine = self.combat._load_session(match_id).engine
            except Exception:  # noqa: BLE001 - the fight still shows without it
                return {}
        choices: dict[tuple[str, str], str] = {}
        for group in (menu or {}).get("actions") or []:
            parameters = getattr(engine.action_catalog.get(group.get("source_definition_id")), "parameters", None) or {}
            if parameters.get("item_action") and group.get("options"):
                choices[(parameters["item_action"], parameters["item_key"])] = group["options"][0]["candidate_id"]
                group["item"] = parameters["item_action"]  # the table lists it in the Items panel, not the action bar
            elif str(group.get("source_definition_id") or "").endswith(".pickup"):
                group["item"] = "weapon_pickup"
        out = {}
        for actor_id in getattr(engine, "typed_actor_ids", set()) or set():
            actor = engine.state.actors.get(actor_id)
            now = carry.status(engine, actor) if actor is not None else None
            if not now:
                continue
            items = []
            for item in (carry.carrying_of(engine, actor_id) or {}).get("items") or []:
                held = item.get("worn") or carry.holds(engine, actor, item["key"])
                items.append({"key": item["key"], "name": item["name"], "weight_lb": item["weight_lb"], "quantity": item.get("quantity", 1),
                              "worn": bool(item.get("worn")), "weapon": bool(item.get("weapon_action")), "held": bool(held),
                              "drop": choices.get(("drop", item["key"])) if actor_id == (menu or {}).get("actor_id") else None,
                              "pickup": choices.get(("pickup", item["key"])) if actor_id == (menu or {}).get("actor_id") else None})
            out[actor_id] = {**now, "items": items}
        return out

    def summon_token_root(self) -> Path:
        return self.buttons.root.parent / "tabletop_tokens" / "summons"

    def bundled_summon_token_root(self) -> Path:
        """The summon pictures that ship with the program, so a summon has a face on a fresh install.

        The owner's own art lives in ``summon_token_root()`` and always wins; this is the fallback
        pool. Owner 2026-10-03: "Lesser Corpse Servant doesnt have an image for its token" -- 15 of
        the 30 kinds in ``combat/rules/summons.json`` had no folder of pictures on disk, and the
        earlier ``if not root.is_dir(): return {}`` meant a fresh install gave *no* summon a face.
        """
        return Path(__file__).resolve().parents[1] / "static" / "tabletop" / "summon_tokens"

    # The last-resort pool. A kind with no art of its own still gets this creature silhouette rather
    # than bare initials. "generic" is not a creature kind in summons.json, so an owner's folder can
    # never shadow it by accident.
    GENERIC_SUMMON_KIND = "generic"

    def _summon_token_pool(self, kind: str) -> tuple[str, list[str]] | None:
        """The faces a creature ``kind`` may wear, as ``(pool folder, file names)``.

        A creature's own pictures beat a shared one. The pools are tried most-specific first:

        1. the owner's pictures for this exact creature kind,
        2. the pictures shipped with the program for this exact creature kind,
        3. the owner's shared ``generic`` pictures,
        4. the shared ``generic`` pictures that ship with the program.

        So a picture drawn *for this creature* is always used in preference to a catch-all
        silhouette, even when a ``generic`` folder exists in the owner's own art -- otherwise one
        shared file would flatten every creature that already has a face of its own (MMX91 review
        finding 1). Within each pair the owner's art still wins, which is how an owner replaces the
        face of a particular creature: put it in a folder named after that creature. ``None`` means
        even the generic pool is missing, and that creature is drawn with its initials as before.
        One seam every summon kind shares; no kind is named here.
        """
        owner_root, bundled_root = self.summon_token_root(), self.bundled_summon_token_root()
        for root, folder in (
            (owner_root, kind),
            (bundled_root, kind),
            (owner_root, self.GENERIC_SUMMON_KIND),
            (bundled_root, self.GENERIC_SUMMON_KIND),
        ):
            pool = sorted(path.name for path in (root / folder).glob("*.png")) if (root / folder).is_dir() else []
            if pool:
                return folder, pool
        return None

    def _summon_tokens(self, match_id: str, engine: Any = None) -> dict[str, str]:
        """A token for every summoned creature (owner 2026-09-27: "the token can load a random corpse servent token in its
        creation, same for all the other summons and companions"): one of its kind's pictures, picked by the creature's id
        so it keeps the same face all fight. Every kind resolves to a picture (owner 2026-10-03), so a summon is never
        left as bare initials."""
        import hashlib

        if engine is None:
            try:
                engine = self.combat._load_session(match_id).engine
            except Exception:  # noqa: BLE001 - the fight still shows without them
                return {}
        out = {}
        for actor in engine.state.actors.values():
            summon = getattr(actor, "summon", None) or {}
            group = str(summon.get("group") or "")
            if not group:
                continue
            kind = group.rsplit(".", 1)[-1]  # "mount.warhorse" / "beast0.wolf" -> creature kind
            found = self._summon_token_pool(kind)
            if not found:
                continue
            folder, pool = found
            pick = pool[int(hashlib.sha256(actor.entity_id.encode()).hexdigest()[:8], 16) % len(pool)]
            out[actor.entity_id] = f"/api/tabletop/summon-tokens/{folder}/{pick}"
        return out

    def summon_token_path(self, kind: str, name: str) -> Path:
        import re

        if not re.fullmatch(r"[a-z0-9_]{1,40}", kind or "") or not re.fullmatch(r"[a-z0-9_-]{1,40}\.png", name or ""):
            raise TabletopError("TABLETOP_TOKEN_NONE", "No such token.", 404)
        for root in (self.summon_token_root(), self.bundled_summon_token_root()):
            path = root / kind / name
            if path.is_file():
                return path
        raise TabletopError("TABLETOP_TOKEN_NONE", "No such token.", 404)

    def _dropped_items(self, match_id: str, engine: Any = None) -> list[dict[str, Any]]:
        """Weapons a Disarm knocked away, where they lie until picked up (owner 2026-09-26)."""
        if engine is None:
            try:
                engine = self.combat._load_session(match_id).engine
            except Exception:  # noqa: BLE001 - the fight still shows without them
                return []
        items = []
        for actor in engine.state.actors.values():
            for condition in actor.conditions.values():
                spot, weapon = condition.data.get("dropped_at"), condition.data.get("disables_action")
                if isinstance(spot, dict) and not weapon and condition.data.get("item_name"):
                    # Anything it dropped (owner 2026-09-27, combat/carry.py).
                    items.append({"id": f"item:{condition.instance_id}", "x": int(spot["x"]), "y": int(spot["y"]),
                                  "name": f"{condition.data['item_name']} (dropped by {actor.display_name})", "owner_id": actor.entity_id})
                    continue
                if isinstance(spot, dict) and weapon:
                    action = engine.action_catalog.get(weapon)
                    name = str(getattr(action, "display_name", "") or "Weapon").removesuffix(" attack")
                    items.append({"id": f"item:{condition.instance_id}", "x": int(spot["x"]), "y": int(spot["y"]),
                                  "name": f"{name} (dropped by {actor.display_name})", "owner_id": actor.entity_id})
        try:  # the Eyes, Nodes and Anchors of formation arrays (combat/ext/formations.py table_items)
            from .ext.formations import table_items
            items.extend(table_items(engine))
        except Exception:  # noqa: BLE001 - the fight still shows without them
            from .table_state_cache import decline
            decline("items")
        return items

    @_one_at_a_time
    def events(self, match_id: str, after: int, *, engine: Any = None) -> dict[str, Any]:
        """Read the journal feed; reuse the caller's current engine for names/profiles.

        Manual action responses already hold their post-commit engine (or the
        unchanged engine on a decision pause). Standalone polls load their own.
        The supplied engine is only read and is never retained between requests.
        """
        events, rolls, last, _commits = journal_since(self._match_dir(match_id), int(after))
        if engine is None:
            engine = self.combat._load_session(match_id).engine
        actors, definitions = self._names_for(match_id, engine)
        roll_ids = {str((event.get("payload") or {}).get("roll_id")) for event in events}
        # Completed checks journal their dice on the two sides, rather than
        # a top-level roll_id. Include those same recorded rolls in the feed.
        roll_ids.update(str(side['roll_id']) for event in events if event.get('event_type') == 'CHECK_ROLLED'
                        for side in ((event.get('payload') or {}).get('actor') or {},
                                     (event.get('payload') or {}).get('target') or {}) if side.get('roll_id'))
        own_rolls = [roll for roll in rolls if str(roll.get("roll_id")) in roll_ids or not roll_ids]
        profiles = {key: (row.parameters.get("typed") or {}) for key, row in engine.action_catalog.items()}
        economies = {key: getattr(row.economy, "value", str(row.economy)) for key, row in engine.action_catalog.items()}
        feed = format_history_feed(events, own_rolls, pre_state=None, post_state={}, actor_names=actors, definition_names=definitions,
                                   action_profiles=profiles, action_economies=economies,
                                   concealed_condition_instance_ids=concealed_condition_instances(engine.state.model_dump(mode="json")))
        for row in feed:  # the stream has no pre-move state; the table animates the path instead
            # Expose the journal cursor under both the canonical and display keys.
            # All writers (including model seats) share this committed sequence.
            row["sequence"] = row["event_sequence"]
            row["summary"] = str(row.get("summary") or "").replace(" moved from unknown cell to ", " moved to ")
        # Keep a check's anonymous presentation identity on its defending die
        # as well as its history line; raw journal actor IDs remain provenance.
        anonymous_rolls = {(event.get('payload', {}).get('target') or {}).get('roll_id'):
                           event['payload']['check_metadata']['opponent_display_name']
                           for event in events if event.get('event_type') == 'CHECK_ROLLED'
                           and (event.get('payload', {}).get('check_metadata') or {}).get('opponent_display_name')}
        dice = dice_rows(own_rolls, actors, definitions)
        for row in dice:
            if row['roll_id'] in anonymous_rolls:
                row['label'] = anonymous_rolls[row['roll_id']] + ' · ' + row['kind'].title()
        return {"events": feed, "dice": dice, "last_sequence": last,
                "state_version": engine.state.state_version,
                **self._diagnostic_fields(match_id)}

    @_one_at_a_time
    def preview_composition(self, match_id, payload):
        from .option_composition import preview
        try:
            return preview(self, match_id, payload)
        except ValueError as exc:
            raise TabletopError("TABLETOP_OPTION_INVALID", str(exc), 422) from exc

    @_one_at_a_time
    def prepare_composition(self, match_id, payload, candidate_id, option_ids=None, *, after=0, reactions=None):
        """Noncommitting check of a drafted action; saves no settings, reserves nothing."""
        from .option_composition import check
        try:
            return check(self, match_id, payload, candidate_id, option_ids, after, reactions)
        except ValueError as exc:
            raise TabletopError("TABLETOP_OPTION_INVALID", str(exc), 422) from exc

    @_notify_driver
    @_one_at_a_time
    @_pending_writer
    def commit_composition(self, match_id, payload, candidate_id, after, reactions=None, option_ids=None):
        from .option_composition import commit
        try:
            return commit(self, match_id, payload, candidate_id, after, reactions or [], option_ids)
        except ValueError as exc:
            raise TabletopError("TABLETOP_OPTION_INVALID", str(exc), 422) from exc

    @_notify_driver
    @_one_at_a_time
    @_pending_writer
    def save_settings(self, match_id, actor_id, sources, request_id):
        """Compact, journaled owned settings; independent of the combat UI busy flag."""
        from .settings_service import match_batch
        try:
            return match_batch(self, match_id, actor_id, sources, request_id)
        except ValueError as exc:
            raise TabletopError("TABLETOP_SETTING_INVALID", str(exc), 409) from exc

    @_one_at_a_time
    def save_project_settings(self, project_id, sources):
        from .settings_service import project_batch
        try:
            return project_batch(self, project_id, sources)
        except ValueError as exc:
            raise TabletopError("TABLETOP_SETTING_INVALID", str(exc), 422) from exc

    @_notify_driver
    @_one_at_a_time
    @_pending_writer
    def cancel_placement(self, match_id: str, candidate_id: str, decision_id: str, state_version: int,
                         pending_id: str | None = None) -> dict[str, Any]:
        """Discard only the active player's initial, uncommitted placement.

        Generic UI seam: a deferred CELL aim has paid/resolved nothing. Nested
        choices and automatic turns cannot use cancellation to undo a decision.
        The same writer reservation and decision binding as act prevent stale
        tabs from cancelling a newer request, and ``pending_id`` must quote the
        saved aim's own attempt id, so a Cancel captured from an earlier attempt
        of the same act request cannot discard a renewed aim. No engine state is
        edited.
        """
        from .placement_menu import CHOICE
        session = self.combat._load_session(match_id)
        decision = self.combat.decision(match_id, session=session)
        if self.decision_driver is not None and self.decision_driver.guard_action(match_id, decision, session.engine):
            raise TabletopError('TABLETOP_NOT_YOUR_TURN', 'The AI is choosing this action.', 409)
        menu = decision['context']
        pending = self._pending_action(match_id, menu)
        request = pending.get('request', {}) if pending else {}
        context = (pending.get('reaction') or {}).get('context', {}) if pending else {}
        if (decision['control_mode'] not in MANUAL_MODES or not pending
                or pending['method'] != 'act' or pending['reactions']
                or context.get('reaction_source_id') != CHOICE
                or context.get('reactor_id') != menu.get('active_actor_id')
                or any(request.get(key) != value for key, value in {
                    'candidate_id': candidate_id, 'decision_id': decision_id,
                    'state_version': state_version}.items())):
            raise TabletopError('TABLETOP_STALE', 'That placement is no longer waiting. Refresh the table.', 409)
        # Every saved aim records its own attempt id. A pre-attempt-id build saved none,
        # so only its payload (same shape) still matches those records.
        if (pending.get('pending_id') or '') != (pending_id or ''):
            raise TabletopError('TABLETOP_STALE', 'That placement is no longer waiting. Refresh the table.', 409)
        self._save_pending_action(match_id, None)
        return {'status': 'CANCELLED', 'state': self.state(match_id)}

    @_notify_driver
    @_one_at_a_time
    @_pending_writer
    def act(self, match_id: str, candidate_id: str, decision_id: str, state_version: int, after: int,
            reactions: list[dict[str, Any]] | None = None, *, movement_path=None, movement_mode='walk', actor_id=None,
            option_ids=None, defer_menu: bool = False, menu_read: dict[str, Any] | None = None,
            prepare_only: bool = False, _execution=None, _receipt=False) -> dict[str, Any]:
        return self._act_locked(match_id, candidate_id, decision_id, state_version, after, reactions,
            movement_path=movement_path, movement_mode=movement_mode, actor_id=actor_id,
            option_ids=option_ids, defer_menu=defer_menu, menu_read=menu_read, prepare_only=prepare_only,
            _execution=_execution, _receipt=_receipt)

    def _act_locked(self, match_id, candidate_id, decision_id, state_version, after, reactions=None, *,
                    movement_path=None, movement_mode='walk', actor_id=None, option_ids=None, defer_menu=False,
                    menu_read=None, prepare_only=False, _execution=None, _receipt=False):
        """Commit a current candidate, optionally selecting its typed choice options.

        Caller holds both table locks. Composition uses this after its validated
        settings transaction, without recursively acquiring the file lock.

        This general seam supports candidate pools (damage types, modifiers,
        movement modes, etc.). Omission retains existing candidate defaults;
        explicit selections are validated by CombatService under the writer lock.
        A pending explicit selection must be repeated unchanged on continuation.
        HTTP clients use ``defer_menu=True``: acknowledge the committed snapshot
        and feed before building another decision. Legacy in-process callers may
        still request their complete menu in this response.
        """
        if option_ids is not None and (not isinstance(option_ids, list)
                or any(not isinstance(o, str) for o in option_ids) or len(set(option_ids)) != len(option_ids)):
            raise TabletopError("TABLETOP_OPTION_INVALID", "Choose unique options from the current action menu.", 422)
        session = _execution.current() if _execution is not None else self.combat._load_session(match_id)
        from .movement_menu import capture
        with capture():
            decision = self.combat.decision(match_id, session=session, table_header=True)
        context = decision["context"]
        if self.decision_driver is not None and self.decision_driver.guard_action(match_id, decision, session.engine):
            return {"status": "MODEL_DECIDING", "state": self.state(match_id)}
        if decision["control_mode"] not in MANUAL_MODES:
            raise TabletopError("TABLETOP_NOT_YOUR_TURN", "The active fighter is controlled by the AI; use Auto Step.", 409)
        if context["decision_id"] != decision_id or int(context["state_version"]) != int(state_version):
            raise TabletopError("TABLETOP_STALE", "The fight moved on; the table has refreshed.", 409)
        request = {"candidate_id": candidate_id, "decision_id": decision_id, "state_version": int(state_version), "after": int(after)}
        if option_ids is not None:
            request["option_ids"] = list(option_ids)
        if movement_path is not None:
            request.update(movement_path=movement_path, movement_mode=movement_mode, actor_id=actor_id)
        reactions = list(reactions or [])
        pending_response = self._check_pending_request(match_id, context, "act", request, reactions, session.engine)
        if pending_response:
            return pending_response
        candidate = next((row for row in context["legal_candidates"] if row["candidate_id"] == candidate_id), None)
        if movement_path is not None:
            from .movement_routes import explicit_candidate, parse_waypoints
            try:
                route = explicit_candidate(session.engine, actor_id, parse_waypoints(movement_path), movement_mode)
            except ValueError as exc:
                raise TabletopError('TABLETOP_ROUTE_INVALID', str(exc), 422) from exc
            candidate = route.model_dump(mode='json') if route.candidate_id == candidate_id else None
        if candidate is None:
            # Exact legacy/clipboard cell IDs are still accepted. Ordinary
            # menus use the placeholder and the persisted square picker.
            candidate = next((c.model_dump(mode='json') for c in session.engine.legal_candidates()
                              if c.candidate_id == candidate_id and c.destination is not None), None)
        if candidate is None:
            raise TabletopError("TABLETOP_STALE", "That choice is no longer legal; the table has refreshed.", 409)
        intent = {key: candidate.get(key) for key in ("candidate_id", "decision_id", "state_version", "actor_id", "target_ids", "destination", "option_ids")}
        intent["target_ids"] = list(intent.get("target_ids") or [])
        intent["option_ids"] = list(intent.get("option_ids") or [])
        if option_ids is not None:
            intent["option_ids"] = list(option_ids)
        if movement_path is not None:
            intent.update(movement_path=movement_path, movement_mode=movement_mode)
        if prepare_only:
            return self._prepare_action(match_id, intent, after, reactions, engine=session.engine)
        try:
            self.combat.submit_intent(match_id, intent, list(reactions or []), None, session=session)
        except Exception as exc:  # noqa: BLE001 -- only the Ask me pause is handled here
            diagnostic = getattr(exc, "diagnostic", None)
            if getattr(diagnostic, "code", None) != "COMBAT_REACTION_DECISION_REQUIRED":
                raise
            # Step 16: a reaction of a character you play, set to Ask me, came up; nothing was committed.
            context = (getattr(diagnostic, "details", None) or {}).get("reaction_context") or {}
            reaction = self._reaction_prompt(match_id, context, engine=session.engine)
            from .placement_menu import CHOICE
            if (not reactions and context.get('reaction_source_id') == CHOICE
                    and context.get('reactor_id') == intent['actor_id']):
                # A renewed aim of this very request would rebuild the same
                # candidate/decision/version binding, so a Cancel captured from the
                # earlier attempt must not be able to discard this newer one: each
                # saved aim carries an attempt id the guarded cancel must quote.
                attempt_id = 'attempt:' + uuid.uuid4().hex
                reaction['cancel_action'] = {**{key: request[key] for key in
                                                ('candidate_id', 'decision_id', 'state_version')},
                                             'pending_id': attempt_id}
            self._save_pending_action(match_id, {"schema": "TabletopPendingAction.v2", "method": "act",
                "request": request,
                "reactions": list(reactions or []), "reaction": reaction, "reaction_context": context,
                "pending_id": attempt_id if reaction.get('cancel_action') else None})
            return {"status": "REACTION_REQUIRED", "reaction": reaction,
                    "events": self.events(match_id, after, engine=session.engine), "state": self.state(match_id)}
        self._save_pending_action(match_id, None)
        if _execution is not None:
            _execution.committed()
        if _receipt:
            return self._execution_receipt(session, "COMMITTED")
        if defer_menu:
            self._prepare_committed_menu(match_id, session.engine)
        # menu_read (the client's own state-read arguments) answers with that complete state, built from the
        # committed engine: a free choice that leaves the menu as it was then needs no second read.
        read = ({"fog": bool(menu_read.get("fog")), "fog_view": menu_read.get("fog_view"),
                 "fog_actor_ids": tuple(menu_read.get("fog_actor_ids") or ()),
                 "compact_moves": bool(menu_read.get("compact"))}
                if menu_read is not None else {"include_menu": not defer_menu, "fog": defer_menu})
        committed = {"status": "COMMITTED", "events": self.events(match_id, after, engine=session.engine),
                     "state": self.state(match_id, _session=session, **read)}
        # A fight that has never had a commit disagree with the table's prediction answers exactly as it
        # always has; the extra key appears only when there is a real diagnostic to show.
        divergence = self._divergence_diagnostic(match_id)
        if divergence is not None:
            committed["divergence_diagnostic"] = divergence
        return committed

    def _prepare_action(self, match_id, intent, after, reactions, *, engine, projected_engine=None):
        """Gather real choices for ordinary and composed actions without reserving one.

        ``engine`` is the live feed boundary; optional ``projected_engine`` is
        the validated disposable draft used for execution and prompt labels.
        Only a later explicit commit may save settings, answers or a pending action.
        """
        preview = self.combat.preview(match_id, intent, list(reactions or []), projected_engine=projected_engine)
        if preview["status"] == "REACTION_REQUIRED":
            reaction = self._reaction_prompt(match_id, preview["reaction_context"], engine=projected_engine or engine)
            return {"status": "REACTION_REQUIRED", "reaction": reaction,
                    "events": self.events(match_id, after, engine=engine)}
        return {"status": "PREPARED"}

    @_one_at_a_time
    def preview_destination(self, match_id, decision_id, state_version, actor_id, destination, movement_mode='walk'):
        """Resolve one native endpoint/mode; quotes confer no execution authority."""
        from types import SimpleNamespace
        from .gate2_runtime_models import Position
        from .read_queries import candidate_pass
        from . import ext, motion
        from .zones import sync_walls
        session = self.combat._load_session(match_id)
        engine = session.engine
        actor = engine.state.actors.get(actor_id)
        metadata = self.combat._read_metadata(match_id, session)
        if actor is None or self.combat._mode_for_actor(metadata, session, actor_id) not in MANUAL_MODES:
            raise TabletopError('TABLETOP_NOT_YOUR_TURN', 'Choose a destination for your active fighter.', 409)
        expected = f'decision:{engine.state.state_version}:{actor_id}:{engine.state.event_sequence}'
        if (decision_id != expected or state_version != engine.state.state_version
                or engine.state.current_actor_id != actor_id or engine.state.pending_resolution
                or engine.state.setup_tasks or engine.state.terminal_result):
            raise TabletopError('TABLETOP_STALE', 'The fight moved on; choose where to move again.', 409)
        try:
            point = Position.model_validate(destination)
            with candidate_pass(engine), motion.terrain_for(engine, actor):
                sync_walls(engine)
                candidates = engine._movement_candidates(actor, intent=SimpleNamespace(destination=point))
                chosen = next((c for c in candidates
                               if c.metadata.get('movement_mode', 'walk') == movement_mode
                               and not ext.any_false('candidate_allowed', engine, actor, c,
                                                     engine.action_catalog.get(c.source_definition_id))), None)
            if chosen is None:
                raise ValueError('That destination is no longer available in this movement mode.')
            from .movement_routes import explicit_candidate
            chosen = explicit_candidate(engine, actor_id, chosen.canonical_path, movement_mode)
        except ValueError as exc:
            raise TabletopError('TABLETOP_ROUTE_INVALID', str(exc), 422) from exc
        return {'status': 'ROUTE_PREVIEW', 'candidate': chosen.model_dump(mode='json'),
                'authoritative_state_unchanged': True}

    @_one_at_a_time
    def preview_move_path(self, match_id, decision_id, state_version, actor_id, waypoints, movement_mode='walk'):
        """Read-only route quote, with exact immutable decision/candidate binding."""
        from .movement_routes import explicit_candidate, parse_waypoints
        session = self.combat._load_session(match_id)
        decision = self.combat.decision(match_id, session=session)
        context = decision['context']
        if decision['control_mode'] not in MANUAL_MODES:
            raise TabletopError('TABLETOP_NOT_YOUR_TURN', 'The active fighter is controlled by the AI; use Auto Step.', 409)
        if context['decision_id'] != decision_id or context['state_version'] != state_version:
            raise TabletopError('TABLETOP_STALE', 'The fight moved on; choose your route again.', 409)
        try:
            candidate = explicit_candidate(session.engine, actor_id, parse_waypoints(waypoints), movement_mode)
        except ValueError as exc:
            raise TabletopError('TABLETOP_ROUTE_INVALID', str(exc), 422) from exc
        return {'status': 'ROUTE_PREVIEW', 'candidate': candidate.model_dump(mode='json'),
                'authoritative_state_unchanged': True}

    def commit_move_path(self, match_id, candidate_id, decision_id, state_version, actor_id,
                         waypoints, after=0, movement_mode='walk', reactions=None, *, defer_menu=False):
        """Normal table commit/reaction continuation for this exact waypoint route."""
        return self.act(match_id, candidate_id, decision_id, state_version, after, reactions,
                        movement_path=waypoints, movement_mode=movement_mode, actor_id=actor_id, defer_menu=defer_menu)

    @_one_at_a_time
    @_pending_writer
    def control(self, match_id, command, **kwargs):
        """Serialize input-only controller changes with retained decisions.

        The existing combat HTTP endpoints and seat editor use the same table
        reservation as actions. No mechanical event is invented for a control
        edit; the execution binding sees its changed durable input revision.
        """
        return {"controller": self.combat.set_controller_mode,
                "pause": self.combat.pause, "resume": self.combat.resume}[command](match_id, **kwargs)

    @_notify_driver
    @_one_at_a_time
    @_pending_writer
    def auto_step(self, match_id: str, after: int, reactions: list[dict[str, Any]] | None = None,
                  decision_id: str | None = None, state_version: int | None = None, *, defer_menu=False,
                  _execution=None, _receipt=False) -> dict[str, Any]:
        """One checked durable decision, optionally returning only an execution receipt.

        Internal execution ownership is separate from presentation. The same
        request binding, pending-input and transaction checks serve the ordinary
        transport and the session owner; no separate AI policy or commit path.
        """
        session = _execution.current() if _execution is not None else self.combat._load_session(match_id)
        decision = self.combat.decision(match_id, session=session, table_header=_receipt)
        context = decision["context"]
        if self.decision_driver is not None and self.decision_driver.guard_action(match_id, decision, session.engine):
            return {"status": "MODEL_DECIDING", "state": self.state(match_id)}
        pending = self._pending_action(match_id, context)
        # Legacy first-step callers are allowed. Answers without a saved request
        # or an explicit binding must never execute a later automatic decision.
        if ((decision_id is None) != (state_version is None)
                or (decision_id is not None and (decision_id != context["decision_id"] or state_version != context["state_version"]))
                or (reactions and decision_id is None and not pending)):
            raise TabletopError("TABLETOP_STALE", "The fight moved on; the table has refreshed.", 409)
        request = {"after": int(after), "decision_id": context["decision_id"], "state_version": context["state_version"]}
        reactions = list(reactions or [])
        pending_response = self._check_pending_request(match_id, context, "auto_step", request, reactions, session.engine)
        if pending_response:
            return pending_response
        # Local Auto already accepts a loaded session. Keep its choice/commit on
        # the decision checked above instead of reloading a later turn.
        result = (self.combat.local_step(match_id, list(reactions or []), session=session, include_match=not _receipt)
                  if decision["control_mode"] == "LOCAL_AUTO"
                  else self.combat.auto_step(match_id, list(reactions or [])))
        if result.get("status") == "AWAITING_REACTION":
            reaction = self._reaction_prompt(match_id, result.get("reaction_context") or {}, engine=session.engine)
            self._save_pending_action(match_id, {"schema": "TabletopPendingAction.v2", "method": "auto_step",
                "request": request, "reactions": list(reactions or []), "reaction": reaction,
                "reaction_context": result.get("reaction_context")})
            if _receipt:
                return self._execution_receipt(session, "REACTION_REQUIRED")
            return {"status": "REACTION_REQUIRED", "reaction": reaction,
                    "events": self.events(match_id, after), "state": self.state(match_id)}
        self._save_pending_action(match_id, None)
        if _execution is not None:
            _execution.committed()
        if _receipt:
            return self._execution_receipt(session, result.get("status"))
        # Local Auto committed the session loaded above. Use the same verified
        # presentation boundary as manual actions instead of replaying the full
        # fight once for event names and again for its post-action state. Other
        # controller paths own their own session and retain ordinary loading.
        committed = (self.combat.presentation_session(session)
                     if decision["control_mode"] == "LOCAL_AUTO" and result.get("status") == "COMMITTED"
                     else None)
        if defer_menu and result.get("status") == "COMMITTED":
            if committed is None:
                committed = self._load_state_session(match_id)
            self._prepare_committed_menu(match_id, committed.engine)
        return {"status": result.get("status"),
                "events": self.events(match_id, after, engine=committed.engine if committed is not None else None),
                "state": self.state(match_id, _session=committed,
                                    include_menu=not defer_menu, fog=defer_menu),
                **self._diagnostic_fields(match_id)}

    @staticmethod
    def _execution_receipt(session, status):
        """Durable decision status, not a view or candidate/menu authority.

        Audience-specific full views remain at the human/prompt boundary.
        Internal callers must never expose the mutable execution session.
        """
        state = session.engine.state
        return {"status": status, "state_version": state.state_version,
                "event_sequence": state.event_sequence,
                "terminal": state.terminal_result is not None}

    _ASK_MOMENTS = {"FOUNDATION_SPEND": "may spend its Foundation resource", "ATTACK_DECLARED": "is attacked", "ATTACK_HIT_BEFORE_DAMAGE": "is hit", "DAMAGE_APPLICATION": "takes damage",
                    "ATTACK_MISSED": "is missed", "ATTACK_RESOLVED": "after the attack", "SAVE_RESULT_BEFORE_DECLARED": "fails a save",
                    "LEAVE_REACH": "a foe leaves its reach", "TECHNIQUE_DECLARED": "a technique is used on it",
                    "BENEFIT_GAINED": "gained a temporary benefit",
                    "CONDITION_ABOUT_TO_APPLY": "a condition is about to land", "FORCED_MOVEMENT": "someone is pushed or pulled",
                    "D20_PENDING": "someone is about to roll",
                    "D20_REROLL_SAVE": "fails a saving throw (may reroll it)",
                    "D20_REROLL_ATTACK": "is hit (may make the attacker reroll)",
                    "D20_REROLL_CHECK": "fails a check (may reroll it)",
                    "D20_REROLL_ALLY": "a creature within reach has rolled a d20 (may have it reroll)",
                    "D20_REWRITE_ROLL": "a creature within reach has rolled a d20 (may rewrite it)",
                    "D20_ROLL_BONUS": "a creature has rolled (may add a bonus to the result)",
                    "D20_FOX_MISDIRECT": "makes an attack roll (may impose Disadvantage on it)",
                    "ALLY_CHECK_ROLLED": "an ally within 30 feet has rolled a check (Release)",
                    "WAR_DRUM_TEMP_HP": "may echo the Shout next turn: Temporary HP (War Drum Cadence, 1 Martial Focus)",
                    "WAR_DRUM_SPEED": "may echo the Shout next turn: +10 feet Speed (War Drum Cadence, 1 Martial Focus)",
                    "WAR_DRUM_ADVANTAGE": "may echo the Shout next turn: Advantage against Charmed or Frightened (War Drum Cadence, 1 Martial Focus)",
                    "COMMAND_STEP_START": "may call Step on My Count at the start of the ally's turn (1 Momentum Mark)",
                    "COMMAND_STEP_END": "may call Step on My Count at the end of the ally's turn (1 Momentum Mark)",
                    "COMMAND_STEP_MISSED": "may call Step on My Count after the ally's attack missed (1 Momentum Mark)",
                    "COMMAND_STRIKE": "may call Strike on My Count on the ally's hit (1 Momentum Mark)",
                    "COMMAND_BRACE": "may call Brace the Line for the ally (1 Momentum Mark)",
                    "COMMAND_REROLL": "may spend a Momentum Mark to let the ally reroll the failed save",
                    "COMMAND_RETREAT": "may spend a Momentum Mark to move an adjacent ally 10 feet (Ordered Retreat)",
                    "LEGION_UNENDING": "may give a Commanded ally Temporary HP before the blow (Legion Unending, 1 Momentum Mark)",
                    "MASTER_TEMP_HP": "may give a Commanded ally Temporary HP (Master's Presence)",
                    "MASTER_ADVANTAGE": "may give a Commanded ally Advantage against Charmed or Frightened (Master's Presence)",
                    "MASTER_REMOVE_FEAR": "may end a Commanded ally's Frightened condition (Master's Presence)",
                    "DAMAGE_SHARE": "may take part of the damage in the target's place (Take the Blow, Oath of Mutual Defense, Chain of Devotion, Divide the Blow / Pain)",
                    "STAND_TOGETHER": "may spend 1 Devotion to give a Vow-Marked ally Temporary HP (Stand Together)",
                    "CHAIN_REROLL": "may spend 1 Devotion and its Reaction to let a linked creature reroll the failed save (Chain of Devotion)",
                    "DEVOTION_SPEND": "may spend 1 Devotion to give the protected creature Advantage on its next saves against the attacker (Heart's Rebuke)"}

    @staticmethod
    def _roster_names(actors: dict[str, str], engine: Any) -> dict[str, str]:
        """The fight's creature display names, with the live roster's names on top.

        ``_names_for`` keeps a match's names for its lifetime, so a creature that joined after the
        cache was filled -- a summon -- is not in it, and a prompt that asks for that creature's name
        would show its actor id. The live engine's roster is the authority for who is in the fight
        right now, so it is read whenever the caller has the engine; the cache remains the answer
        when it does not.
        """
        if engine is None:
            return actors
        return {**actors, **{actor_id: actor.display_name
                             for actor_id, actor in engine.state.actors.items()}}

    def _reaction_prompt(self, match_id: str, context: dict[str, Any], *, engine: Any = None) -> dict[str, Any]:
        """One presentation builder for every decision; the answer contract remains untouched."""
        choices = context.get("reaction_choices") or []
        if choices:
            from .reaction_presentation import annotate_reactions
            if engine is None and hasattr(self, "combat"):
                engine = self.combat._load_session(match_id).engine
            prompts = [self._reaction_prompt(match_id, row, engine=engine) for row in choices]
            prompts = annotate_reactions(prompts, choices, engine)
            return {**prompts[0], "alternatives": prompts}
        from .decision_text import build_decision_text

        if engine is None and hasattr(self, "combat"):
            engine = self.combat._load_session(match_id).engine
        prompt = self._reaction_prompt_fields(match_id, context, engine=engine)
        actors, definitions = self._names_for(match_id)
        actors = self._roster_names(actors, engine)
        result = build_decision_text(engine, context, prompt, actors, definitions, _rules_texts())
        from .choice_presentation import space_choice
        result = space_choice(result, context, engine)
        if not result.get("choice"):
            result["moment"] = result["trigger"]
        return result

    def _reaction_prompt_fields(self, match_id: str, context: dict[str, Any], *, engine: Any = None) -> dict[str, Any]:
        """What the table shows for an Ask me reaction (step 16), with the exact context to answer."""
        # The live roster wins over the lifetime cache, so a creature that joined the fight after the
        # cache was filled is named rather than shown as an actor id (change standard item 13).
        cached, definitions = self._names_for(match_id)
        actors = self._roster_names(cached, engine)
        feature = str(context.get("reaction_source_id") or "").removeprefix("reaction:typed.")
        moment = str(context.get("checkpoint") or "").removeprefix("TYPED:").split("@")[0]
        prepared = (context.get("choice_trigger") or {}).get("prepared") or {}
        is_prepared = str(context.get("checkpoint") or "").startswith("READY:") and bool(prepared)
        # All prompts, including extension choices, share action enrichment.
        # Explicit plugin metadata identifies nested attacks rather than the outer turn.
        trigger = dict(context.get("choice_trigger") or {})
        # Needle extension choices carry explicit display provenance alongside
        # their legal-choice payload. Keep it in the shared renderer even when
        # there is no separate reaction trigger scope (for example, a nested
        # choice made during a resource-spend event).
        for key in ("source_definition_id", "action_name", "action_actor_id", "affected_id"):
            if key in context and context[key] not in (None, ""):
                trigger[key] = context[key]
        reactor_id = context.get("reactor_id")
        attacker_id = trigger.get("action_actor_id", trigger.get("actor_id") or context.get("attacking_actor_id"))
        recent = list(reversed(context.get("recent_events") or []))
        action = next((definitions[row["source_definition_id"]] for row in recent
                       if attacker_id and row.get("actor_id") == attacker_id and row.get("source_definition_id") in definitions), "")
        if "source_definition_id" in trigger or "source_id" in trigger or trigger.get("roll_kind"):
            # Explicit packet metadata may intentionally omit an unknown source;
            # do not substitute the outer intent or historical events in that case.
            attacker_id = trigger.get("action_actor_id", trigger.get("actor_id"))
            action = str(trigger.get("action_name") or definitions.get(trigger.get("source_definition_id") or trigger.get("source_id"), ""))
        # An Ask-me question must name the triggering creature, the ability and the creature it
        # lands on (change standard 9). The creature it lands on is read from the packet's
        # structured metadata only. Needle's target_id can route to the chooser without naming
        # an affected creature; affected_id explicitly distinguishes that unresolved case.
        # Free text is deliberately not a source: the question's wording and
        # its option labels name candidates the player may never choose (an arc offers several
        # creatures and records its centre separately), and a roster name can occur inside an
        # ability name ("Guard-Cutting Parry"). A packet that supplies no target, and one that
        # supplies several equally, stays unresolved rather than guessing, and provenance the
        # packet deliberately left unknown stays unknown (gilded context guard).
        _asked_id = str(trigger.get("affected_id") or "") if "affected_id" in trigger else str(
            (trigger.get("target_id") or "") if trigger.get("target_id") != reactor_id else "")
        asked_name = str(actors.get(_asked_id, ""))
        spec = context.get("extension_choice")
        if spec and not is_prepared:
            # A choice riding the reaction transport (Needle's Exploit, Footwork...): the options by name, not Use/Pass on a
            # raw id (owner 2026-09-30: "choice:needle.exploit — needle:exploit:861:actor:..." and Use did nothing).
            trigger = dict(context.get("choice_trigger") or {})
            for key in ("source_definition_id", "action_name", "action_actor_id", "affected_id"):
                if key in context and context[key] not in (None, ""):
                    trigger[key] = context[key]
            choice_cost = context.get("cost") or trigger.get("cost")
            paying_pool = context.get("paying_pool") or trigger.get("paying_pool")
            labels = trigger.get("labels") or {}
            # The suffix after ':' identifies a choice instance and may contain actor IDs.
            choice_id = str(context.get("reaction_source_id") or "").removeprefix("choice:").split(":", 1)[0]
            feature_id = str(trigger.get("feature_id") or choice_id)
            name = str(trigger.get("name") or definitions.get(feature_id)
                       or choice_id.split(".")[-1].replace("_", " ").title())
            affected_id = str(trigger.get("affected_id") or "") or str(_asked_id)
            affected = actors.get(trigger.get("affected_id"), trigger.get("affected_id")) or asked_name
            said = str(trigger.get("prompt") or f"choose {name}")
            # A choice riding this transport is the reactor's own decision about their own state, so the recent-event
            # `action` above is the OUTER turn's action and often another creature's: Lian Feng was told their Aspect
            # choice was caused by their warhorse's Disengage (HUNT108). Only the trigger's own named action describes
            # this question, so `action` and the clause below are re-derived from it and never from the outer turn.
            action = str(trigger.get("action_name") or definitions.get(trigger.get("source_definition_id") or trigger.get("source_id"), ""))
            if action and affected and attacker_id:
                said += (f" — {actors.get(attacker_id, attacker_id)} "
                         f"{_uses_phrase(action, affected, actors.get(attacker_id, attacker_id), affected_id=affected_id, actor_id=attacker_id)}.")
            return {
                "context": {key: context.get(key) for key in ("checkpoint", "reactor_id", "reaction_source_id")},
                "reactor": actors.get(context.get("reactor_id"), context.get("reactor_id")),
                "reaction": name, "moment": said,
                # "by" keeps its meaning for the page ("<ability> on <by>": the creature the choice is about); the triggering
                # creature travels separately and is named in "moment" (F4 review: the heading read as if it were the target).
                "by": affected or "",
                "trigger_actor": actors.get(attacker_id or "", "") if attacker_id else "",
                "action": action,
                "affected": affected or "",
                "choice": {"options": [{"id": option, "label": str(labels.get(option) or definitions.get(option) or option)} for option in spec.get("option_ids") or []],
                           "minimum": int(spec.get("minimum_selections", 1)), "maximum": int(spec.get("maximum_selections", 1)),
                           "allow_decline": bool(spec.get("allow_decline")), "preferred": list(spec.get("preferred_option_ids") or []),
                           **({"cost": choice_cost, "paying_pool": paying_pool} if choice_cost else {})},
                **({"cost": choice_cost, "paying_pool": paying_pool} if choice_cost else {}),
            }
        # Which action and how much damage the question is about (owner playtest 2026-09-30: a bare "takes damage"
        # prompt read as if it belonged to whatever the log showed next), from the probe's latest events.
        amount = context.get("pending_damage")
        damaged_id = context.get("damaged_target_id") or context.get("protected_target_id")
        if moment == "DAMAGE_APPLICATION":
            window = next((row for row in recent
                           if row.get("event_type") == "REACTION_WINDOW_OPENED"
                           and (row.get("payload") or {}).get("checkpoint") == "DAMAGE_APPLICATION"
                           and (not damaged_id or damaged_id in (row.get("target_ids") or []))), {})
            damaged_id = damaged_id or next(iter(window.get("target_ids") or []), reactor_id)
            if amount is None:
                amount = (window.get("payload") or {}).get("pending_damage")
        said = self._ASK_MOMENTS.get(moment, moment.replace("_", " ").lower())
        if trigger.get("roll_kind"):
            rolled_id = trigger.get("target_id")
            affected = actors.get(rolled_id, rolled_id)
            roll_name = {"save": "saving throw", "attack": "attack roll", "check": "ability check"}.get(trigger["roll_kind"], "d20")
            said = f"{affected} has rolled a {roll_name}"
            if trigger['roll_kind'] == 'reaction':
                action = trigger.get('action_name') or action or 'a Reaction'
                reacting_id = trigger.get('actor_id')
                reacted = actors.get(reacting_id, 'A creature')
                said = f"{reacted} {_uses_phrase(action, affected, reacted, 'against', affected_id=str(rolled_id or ''), actor_id=str(reacting_id or ''))}"
        if moment == "DAMAGE_APPLICATION" and isinstance(amount, int):
            said = f"takes {amount} damage"
        if moment == "DAMAGE_APPLICATION" and damaged_id != reactor_id:
            said = f"{actors.get(damaged_id, damaged_id)} {said}"
        # Change standard item 9: a prompt names the creature it is about, not only the one that acted.
        # This is the shared builder, so one resolution serves every reaction family -- hunt 90 found
        # 73 of 106 recorded prompts with no usable "affected" (absent in 50, blank in 23) across whole
        # families, because this return carried no such field at all. It is resolved from the same
        # trigger ids trigger_text reads (combat/decision_text.py), so the field and the sentence a
        # player reads name the same creature rather than two.
        # An explicit empty affected_id means the target has not been chosen yet;
        # do not replace it with the transport's chooser. Legacy packets retain
        # the LIVE structured-target fallback, without guessing from the attacker
        # or reactor when the packet does not record an affected creature.
        if "affected_id" in trigger:
            affected = actors.get(str(trigger.get("affected_id") or ""), "")
        else:
            affected_id = (trigger.get("target_id") or damaged_id
                           or context.get("protected_target_id"))
            affected = (actors.get(affected_id) or _UNKNOWN_CREATURE) if affected_id else ""
        return {
            "context": {key: context.get(key) for key in ("checkpoint", "reactor_id", "reaction_source_id")},
            "reactor": actors.get(reactor_id, reactor_id),
            "reaction": prepared.get("label") if is_prepared else "Opportunity Attack" if feature in ("opportunity_attack", "system:combat.opportunity_attack") else definitions.get(feature, feature),
            "moment": "your prepared trigger occurred" if is_prepared else said,
            "by": actors.get(attacker_id or "", ""),
            "trigger_actor": actors.get(attacker_id or "", "") if attacker_id else "",
            "action": action,
            "affected": affected or "",
        }

    @_one_at_a_time
    def delete_match(self, match_id: str) -> None:
        """Remove a saved fight (owner 2026-09-25: clear out test fights from the table's list)."""
        import shutil

        match_dir = self._match_dir(match_id).resolve()
        root = (Path(self.combat.userdata_root) / "Combat" / "Matches").resolve()
        if root not in match_dir.parents or not match_dir.is_dir():
            raise TabletopError("TABLETOP_MATCH_NOT_FOUND", "That fight does not exist.", 404)
        shutil.rmtree(match_dir)
        self._names.pop(match_id, None)
        journal_feed.forget(match_dir)  # the removed journal must not be read again

    # ------------------------------------------------------------ sheets and buttons
    def _bundle_and_summary(self, project_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        from factory_authoring.owner_items import OwnerItemStore

        from .factory_compiler import compile_character

        sheet = self.combat._factory_owner_sheet(project_id)
        # Portable packages preserve their authored text; reuse the Factory
        # sheet's view-time owner edits before building the pop-out library.
        from character_sheet.current_rules import overlay_owner_current_rules
        from factory_authoring.owner_text_edits import apply_edit

        edits_path = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/owner_text_edits.json"
        edits = (json.loads(edits_path.read_text(encoding="utf-8")).get("records") or {}) if edits_path.is_file() else {}
        sheet = overlay_owner_current_rules(sheet, edits=edits, apply_owner_edit=apply_edit,
            authenticated_rules_block=lambda _source, _root: ("", ""), factory_root=lambda: None)
        given = OwnerItemStore(self.combat.userdata_root / "owner_items")
        saved = self.buttons.get(project_id)
        # General sheet compilation cache: every authored input and rules-file
        # stamp participates. Return copies because view enrichers add metadata.
        # Preset values are intentionally separate from the compiled rules.
        import copy
        # Authored sheet metadata may contain decimal purchase budgets. This
        # view cache never stores those values in the integer-only fight log.
        from app.core import sha256_json
        items = given.items(project_id)
        compile_inputs = {key: saved.get(key) for key in ("powering", "reactions", "granted_spheres", "summons", "left_behind", "attuned")}
        rule_stamps = [(str(path.relative_to(self.combat.source_root)), path.stat().st_mtime_ns, path.stat().st_size)
                       for folder in ("authority/typed_mechanics", "combat/rules")
                       for path in sorted((self.combat.source_root / folder).glob("*.json"))]
        cache_key = sha256_json([sheet, items, compile_inputs, rule_stamps])
        cache = getattr(self, "_sheet_compile_cache", OrderedDict())
        cached = cache.get(project_id)
        if cached and cached[0] == cache_key:
            return sheet, copy.deepcopy(cached[1]), sheet_summary(sheet, bundle=cached[1])
        bundle = compile_character(sheet, actor_id=FACTORY_PREFIX + project_id, owner_items=items,
                                   powering=saved.get("powering") or {}, reaction_plan=saved.get("reactions") or None,
                                   granted_spheres=saved.get("granted_spheres") or None, summon_plan=saved.get("summons") or None,
                                   left_behind=saved.get("left_behind") or None,
                                   attuned=saved["attuned"] if isinstance(saved.get("attuned"), list) else None)
        cache[project_id] = (cache_key, copy.deepcopy(bundle))
        cache.move_to_end(project_id)
        while len(cache) > 16:
            cache.popitem(last=False)
        self._sheet_compile_cache = cache
        return sheet, bundle, sheet_summary(sheet, bundle=bundle)

    def sheet(self, project_id: str) -> dict[str, Any]:
        _sheet, bundle, summary = self._bundle_and_summary(project_id)
        from .settings_service import sheet_rows
        from .display_values import armor_class_display

        armor_display = armor_class_display(_sheet, bundle)
        from .tabletop import collapse_weapon_copies

        auto = collapse_weapon_copies(auto_buttons(bundle, summary))
        custom = self.buttons.get(project_id)
        passives = [row.get("feature_id") for row in bundle.get("typed_passives") or []]
        # A single ability can compile into several trigger/checkpoint rows. The
        # sheet lists owned abilities once, by source ID, not engine checkpoints.
        reactions = list(dict.fromkeys(row.get("feature_id") for row in bundle.get("typed_reactions") or []))
        skipped = (bundle.get("diagnostics") or {}).get("skipped") or {}
        automated = {value for value in passives + reactions if value}
        automated |= {row["id"] for row in bundle.get("modifiers") or [] if row.get("status") == "applied"}
        from .action_text import layout_action
        from .tabletop import engine_button_description, engine_button_layout

        # Enrich response copies only: compiled and saved button descriptions stay intact.
        rows = {row["source_definition_id"]: row for row in bundle.get("action_catalog") or []}
        presented = []
        for button in auto + list(custom.get("buttons") or []):
            row = rows.get((button.get("combat") or {}).get("source_definition_id"))
            if row and button.get("description") == engine_button_description(row):
                hover = engine_button_layout(row)
            else:
                hover = layout_action({"label": button.get("label"),
                    "parameters": {"description": button.get("description") or ""}})
                # A saved or edited button's own words are authoritative: no printed-record digest is attached,
                # so its card shows that text in full (SOL192 review).
            presented.append({**button, "hover": hover})
        library = sheet_library(_sheet, presented, automated,
                                {row["id"]: row for row in ((bundle.get("diagnostics") or {}).get("insights") or [])})
        from .tooltip_digest import digest_for

        def present_entry(item):
            item["hover"] = layout_action({"label": item.get("name"),
                "parameters": {"description": item.get("text") or item.get("summary") or ""}})
            # The library entry's id is its printed record: the reaction/passive rows use its compact card.
            digest = digest_for(str(item.get("id") or "").split("#", 1)[0], str(item.get("name") or ""))
            if digest is not None:
                item["hover"]["digest"] = digest
            for entry in item.get("entries") or []:
                present_entry(entry)
        for group in library.get("groups") or []:
            for item in (group.get("spheres") or []) + (group.get("entries") or []):
                present_entry(item)
        from .ai_tiers import tier_label
        return {
            "schema": "TianxiaTabletopSheet.v1",
            "library": library,
            "project_id": project_id,
            "actor_id": FACTORY_PREFIX + project_id,
            "attack_modifier_rows": sheet_rows(self, project_id, bundle),
            "summary": {**summary, "ai_label": tier_label(bundle["actor_template"].get("ai_tier")),
                        "armor_class": armor_display["value"], "armor_note": armor_display["tooltip"],
                        "armor_breakdown": armor_display["breakdown"],
                        "hit_points": {"maximum": bundle["actor_template"]["maximum_hp"]}},
            "buttons": presented,
            "layout": custom.get("layout") or {"hidden": [], "pinned": []},
            # Which Path pool pays each choosable ability (owner 2026-09-25, Q19); empty "choices" for
            # a single-Path character.
            "powering": bundle.get("powering") or {"pools": [], "choices": {}},
            # Which reactions the character uses and in what order (owner 2026-09-26): Auto or its own order.
            "reaction_plan": bundle.get("reaction_plan") or {"mode": "auto", "order": [], "off": [], "choices": []},
            # 2024 Carrying Capacity (owner 2026-09-26): what the kit weighs against 15 x Strength.
            "carrying": bundle.get("carrying"),
            # Summoned creatures and companions it brings (owner 2026-09-27, combat/summons.py).
            "summons": bundle.get("summon_options") or {"groups": [], "tamer": False},
            # Its circle token and the words last used to make one with Anima (owner 2026-09-27).
            "token_url": self._tokens_for([FACTORY_PREFIX + project_id]).get(FACTORY_PREFIX + project_id),
            "picture_url": self._picture_store().url(project_id),
            "token_look": custom.get("token_look") or "",
            # Everything the character owns, and what it leaves behind for fights (owner 2026-09-27, the Items tab).
            "equipment": self._equipment(_sheet, project_id, custom.get("left_behind") or [],
                                         custom["attuned"] if isinstance(custom.get("attuned"), list) else None),
            "token_circle": custom.get("token_circle"),
            "features": {
                "automated_passives": [value for value in passives if value],
                "automated_reactions": [value for value in reactions if value],
                "gm_passives": list(skipped.get("passive") or []),
                "gm_reactions": list(skipped.get("reaction") or []),
                # Choices made when the character was built, and what happens only outside fights (owner 2026-09-28).
                "build_features": list(skipped.get("build") or []),
                "outside_fights": list(skipped.get("outside") or []),
                "definitions": list(skipped.get("definition") or []),
                "table_limits": list(skipped.get("table") or []),
                # Talents that change other abilities (owner 2026-09-25) and what happened to each.
                "modifiers": [{key: row.get(key) for key in ("id", "name", "status", "optional", "when", "precondition", "targets",
                                                             "not_automated_targets", "applied")} | {"variants": len(row.get("variants") or [])}
                              for row in bundle.get("modifiers") or []],
            },
        }

    def save_buttons(self, project_id: str, document: dict[str, Any]) -> dict[str, Any]:
        _sheet, bundle, summary = self._bundle_and_summary(project_id)
        known = {row["id"] for row in auto_buttons(bundle, summary)}
        return self.buttons.save(project_id, document, known)

    def save_reactions(self, project_id: str, document: dict[str, Any]) -> dict[str, Any]:
        """The reaction order (owner 2026-09-26); applies to fights started after this is saved."""
        _sheet, bundle, _summary = self._bundle_and_summary(project_id)
        choices = (bundle.get("reaction_plan") or {}).get("choices") or []
        holdable = {row["id"] for row in choices}
        menus = {row["id"]: len(row["options"]) for row in choices if row.get("options")}
        return self.buttons.save_reactions(project_id, document, holdable, menus)

    def _equipment(self, sheet: dict[str, Any], project_id: str, left_behind: list[str], attuned: list[str] | None = None) -> dict[str, Any]:
        from factory_authoring.owner_items import OwnerItemStore

        from .factory_compiler import equipment_list

        listing = equipment_list(sheet, OwnerItemStore(self.combat.userdata_root / "owner_items").items(project_id), attuned)
        chosen = set(left_behind)
        return {**listing, "items": [{**item, "left_behind": item["key"] in chosen} for item in listing["items"]]}

    def save_attunement(self, project_id: str, keys: list[str] | None) -> dict[str, Any]:
        """Attune to these treasures (owner 2026-09-28): at most four slots; an unattuned treasure fights as its base
        item. None returns to the creation plan."""
        from factory_authoring.owner_items import OwnerItemStore
        from factory_authoring.treasure_catalog import ATTUNEMENT_SLOTS

        from .factory_compiler import equipment_list

        if keys is not None:
            sheet = self.combat._factory_owner_sheet(project_id)
            items = {item["key"]: item for item in equipment_list(sheet, OwnerItemStore(self.combat.userdata_root / "owner_items").items(project_id))["items"]}
            unknown = [key for key in keys if not (items.get(key) or {}).get("attunement_slots")]
            if unknown:
                raise TabletopError("TABLETOP_ATTUNEMENT_UNKNOWN", "That is not a treasure this character can attune to.", 400)
            used = sum(int(items[key]["attunement_slots"]) for key in set(keys))
            if used > ATTUNEMENT_SLOTS:
                raise TabletopError("TABLETOP_ATTUNEMENT_FULL", f"That needs {used} attunement slots; a character has {ATTUNEMENT_SLOTS}.", 409)
            keys = sorted(set(keys))
        self.buttons.save_attunement(project_id, keys)
        return self.sheet(project_id)

    def save_left_behind(self, project_id: str, keys: list[str]) -> dict[str, Any]:
        """What the character leaves behind for its next fights (owner 2026-09-27); worn armour stays on."""
        from factory_authoring.owner_items import OwnerItemStore

        from .factory_compiler import equipment_list

        sheet = self.combat._factory_owner_sheet(project_id)
        items = equipment_list(sheet, OwnerItemStore(self.combat.userdata_root / "owner_items").items(project_id))["items"]
        allowed = {item["key"] for item in items if not item.get("worn")}
        unknown = [key for key in keys if key not in allowed]
        if unknown:
            raise TabletopError("TABLETOP_ITEM_UNKNOWN", "That is not an item this character carries (worn armour stays on).", 400)
        self.buttons.save_left_behind(project_id, sorted(set(keys)))
        return self.sheet(project_id)

    def save_display_name(self, project_id: str, name: str | None) -> dict[str, Any]:
        """Rename a finished character for the table and combat (owner 2026-09-27)."""
        self.combat._factory_owner_sheet(project_id)  # the character must exist
        return self.buttons.save_display_name(project_id, name)

    # ------------------------------------------------------------ advancing a finished character (owner 2026-09-27)
    # "the character sheets be updated with new spheres etc so when the player is playing theres a way to interact
    # with the sheets"; rules-checked, with a GM override (combat/table_advance.py). app/api.py hands in the canonical
    # catalog.
    canonical_catalog: Any = None

    def _catalog_talents(self) -> list[dict[str, Any]]:
        if getattr(self, "_talents_cache", None) is None:
            if self.canonical_catalog is None:
                raise TabletopError("TABLETOP_CATALOG_UNAVAILABLE", "The rules catalog is not loaded.", 503)
            self._talents_cache = list(self.canonical_catalog.list_talents().get("records") or [])
        return self._talents_cache

    def _catalog_insights(self) -> list[dict[str, Any]]:
        if getattr(self, "_insights_cache", None) is None:
            self._insights_cache = (list(self.canonical_catalog.list_insights(include_full=True).get("records") or [])
                                    if self.canonical_catalog is not None else [])
        return self._insights_cache

    def _sphere_names(self) -> dict[str, str]:
        if getattr(self, "_spheres_cache", None) is None:
            if self.canonical_catalog is None:
                raise TabletopError("TABLETOP_CATALOG_UNAVAILABLE", "The rules catalog is not loaded.", 503)
            self._spheres_cache = {row["canonical_sphere_id"]: row["display_name"] for row in self.canonical_catalog.list_spheres().get("records") or []}
        return self._spheres_cache

    def table_manuals(self, project_id: str) -> list[dict[str, Any]]:
        """The manuals given at the table, as the owner sheet shows a Lineage Manual with its Recorded Arts (owner
        2026-09-29: Tabik's Clearsight manual is in his fights but was on no sheet). Display only: the sealed package is
        never rewritten, and combat reads the same record through table_advance.apply."""
        from . import table_advance
        from .factory_compiler import TYPED_AUTHORITY

        manuals = table_advance.normalized(self.buttons.get(project_id).get("advancement"))["manuals"]
        if not manuals:
            return []
        mechanics = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
        texts_path = TYPED_AUTHORITY.parent / "typed_mechanics" / "rules_text.json"
        texts = json.loads(texts_path.read_text(encoding="utf-8")) if texts_path.is_file() else {}
        rows = []
        for manual in manuals:
            manual_id = str(manual.get("id") or manual.get("name") or "table.manual")
            arts = [{"record_id": talent_id, "display_name": (mechanics.get(talent_id) or {}).get("name") or talent_id,
                     "parent_manual_record_id": manual_id, "content_type": "Recorded Art", "status": "Learned",
                     "full_description": texts.get(talent_id) or ""}
                    for talent_id in manual.get("talents") or []]
            given = str(manual.get("at") or "")[:10]
            rows.append({"record_id": manual_id, "display_name": str(manual.get("name") or manual_id), "content_type": "Lineage Manual",
                         "status": "Given at the table", "recorded_arts": arts,
                         "summary": f"Given at the table{' on ' + given if given else ''}; its Recorded Arts are learned: "
                                    f"{', '.join(art['display_name'] for art in arts)}."})
        return rows

    def advancement(self, project_id: str, *, primary_method_id: str = "") -> dict[str, Any]:
        """What this character may learn now, what the table has added, and the Forge's menu."""
        from character_creation.constructed_arts.forging_authority import (
            load_forging_authority, realm_at_least, realm_complexity_limit, realm_for_cl, recommended_maximum_spheres)

        from . import table_advance, table_levelup, table_method
        from .factory_compiler import TYPED_AUTHORITY

        sheet = self.combat._factory_owner_sheet(project_id)
        have = table_advance.known(sheet)
        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        names = self._sphere_names()
        talents = self._catalog_talents()
        by_id = {row.get("canonical_talent_id"): row for row in talents}
        from . import table_growth
        insights = [{"id": row["canonical_insight_id"], "name": row["display_name"],
                     "text": row["full_description"], **table_growth.insight_status(row, sheet)}
                    for row in self._catalog_insights()]
        scores = table_advance.current_scores(sheet)
        key_ability = str((sheet.get("identity") or {}).get("key_ability") or "")
        base = self.combat._factory_owner_sheet(project_id, apply_table=False)
        history = table_advance.validate_ability_history(base, saved)
        abilities = history["entries"]
        increase_rule = table_advance.level_increase_rule(sheet)
        spheres = [{"id": key, "name": value, **table_advance.sphere_status(key, have)}
                   for key, value in sorted(names.items(), key=lambda item: item[1]) if key not in have["spheres"]]
        from .ext import run_strict, transform
        for sphere in spheres:
            sphere["learning_choices"] = [choice for result in run_strict(
                "learning_choices", sheet, sphere["id"], talents) for choice in (result or [])]
        learnable = []
        for record in talents:
            talent_id, sphere_id = record.get("canonical_talent_id"), record.get("owning_canonical_sphere_id")
            if not talent_id or talent_id in have["talents"] or sphere_id not in have["spheres"] or record.get("background_only") or record.get("automatic_grant"):
                continue
            learnable.append({"id": talent_id, "name": record.get("display_name"), "sphere": names.get(sphere_id, sphere_id), "sphere_id": sphere_id,
                              "minimum_cl": record.get("minimum_cl"), "prerequisite": record.get("raw_prerequisite_text"),
                              "summary": str(record.get("short_description") or "")[:240], **table_advance.talent_status(record, have)})
        for talent in learnable:
            talent["learning_choices"] = [choice for result in run_strict(
                "learning_choices", sheet, talent["id"], talents) for choice in (result or [])]
        learnable.sort(key=lambda row: (not row["legal"], row["sphere"], int(row.get("minimum_cl") or 0), row["name"] or ""))
        mechanics = _typed_mechanics_catalog(str(TYPED_AUTHORITY), TYPED_AUTHORITY.stat().st_mtime_ns)
        authority = load_forging_authority(Path(__file__).resolve().parents[1])
        realm = realm_for_cl(have["cl"])
        forge_rules = __import__("combat.forged", fromlist=["rules"]).rules()
        forged_module = __import__("combat.forged", fromlist=["fit_table"])
        known_source_ids = set(have["talents"])
        for sphere_id in have["spheres"]:
            known_source_ids.update(table_advance.base_abilities(sphere_id, mechanics))
        sources = [{"id": source_id,
                    "name": (by_id.get(source_id) or {}).get("display_name") or mechanics[source_id].get("name") or mechanics[source_id].get("display_name"),
                    "sphere": names.get(mechanics[source_id].get("sphere_id"), mechanics[source_id].get("sphere_id")),
                    "sphere_id": mechanics[source_id].get("sphere_id"),
                    "kind": mechanics[source_id].get("kind")}
                   for source_id in sorted(known_source_ids) if source_id in mechanics and mechanics[source_id].get("effects")]
        # Fit is computed once here (Grow load), not per chip click: each Base Form x known talent, judged by the compiler.
        fit = forged_module.fit_table([row["id"] for row in sources], mechanics, forge_rules)
        result = {
            "schema": "TianxiaTableAdvancementOptions.v1", "project_id": project_id, "cl": have["cl"], "realm": realm,
            "paths": have["paths"], "spheres": spheres, "talents": learnable,
            "level_up": table_levelup.planning_menu(sheet, talents, saved, self._catalog_insights(),
                                                    primary_method_id=primary_method_id),
            "method_change": table_method.menu(sheet, saved, primary_method_id),
            "sources": ["campaign", "manual", "jade tablet"],
            "insights": insights, "immortal_art": table_growth.art_menu(sheet),
            "ability_panel": {"scores": scores, "key_ability": key_ability, "default_spread": table_advance.default_spread(key_ability),
                              "respec_bonuses": history["bonuses"],
                              "point_buy_budget": table_advance.POINT_BUY_BUDGET, "point_buy_cost": table_advance.POINT_BUY_COST,
                              "level_increase": {"cl": increase_rule.get("allowed_cls", []), "budget": increase_rule.get("budget", 2),
                                                 "deltas": increase_rule.get("allowed_deltas", []), "cap": increase_rule.get("cap", 20),
                                                 "recorded_cls": history["recorded_cls"]}},
            "added": {"abilities": abilities,
                      "insights": [{**row, "index": i} for i, row in enumerate(saved["insights"])],
                      "immortal_arts": [{**row, "id": row["art"]["art_id"]} for row in saved["immortal_arts"]],
                      "spheres": [{**row, "name": names.get(row.get("id"), row.get("id"))} for row in saved["spheres"]],
                      "talents": [{**row, "name": (by_id.get(row.get("id")) or {}).get("display_name") or row.get("id")} for row in saved["talents"]],
                      "forged": [{"technique_id": row["technique"].get("technique_id"), "name": row["technique"].get("name"), "gm": bool(row.get("gm")), "source": row.get("source"), "cl": row.get("cl"),
                                  "form": (row["technique"].get("base_form") or {}).get("display_name"), "cp": (row["technique"].get("cp_cost") or {}).get("final"),
                                  "complexity": (row["technique"].get("complexity") or {}).get("final") if isinstance(row["technique"].get("complexity"), dict) else row["technique"].get("complexity")}
                                 for row in saved["forged"]]},
            "forge": {"available": have["cl"] >= int(authority["access"]["minimum_cl"]), "minimum_cl": int(authority["access"]["minimum_cl"]),
                      "max_complexity": int(realm_complexity_limit(authority, realm)["maximum_complexity"]) if have["cl"] >= 5 else 0,
                      "max_spheres": recommended_maximum_spheres(authority, realm) if have["cl"] >= 5 else 0,
                      "known": len(have["forged"]), "limit": have["pb"],
                      "forms": [row for row in authority["base_forms"] if row.get("starting_cp") is not None],
                      "augments": [{**row, "legal": realm_at_least(realm, row["minimum_realm"])} for row in authority["augments"]],
                      "drawbacks": authority["drawbacks"], "sources": sources, "fit": fit,
                      "sphere_complexity": int(authority["secondary_sphere_effect"]["complexity_per_additional_sphere"]),
                      "choices": {key: forge_rules["augments"][key]["choices"] if isinstance(forge_rules["augments"][key]["choices"], list)
                                  else list(forge_rules["augments"][key]["choices"]) for key in ("minor_hindrance", "major_condition", "severe_hindrance")}},
        }
        return transform("advancement_options", result, sheet, talents)

    def learning_preview(self, project_id: str, sphere_id: str, draft: dict[str, str]) -> dict[str, Any]:
        """Re-evaluate later owner choices after an earlier planned free grant.

        No sheet, receipt, proficiency or ownership changes until acquisition.
        """
        from .ext import run_strict
        sheet = self.combat._factory_owner_sheet(project_id)
        return {"learning_choices": [choice for result in run_strict(
            "learning_choices", sheet, sphere_id, self._catalog_talents(), draft) for choice in (result or [])]}

    def add_advancement(self, project_id: str, kind: str, record_id: str, *, gm: bool = False, source: str = "campaign",
                        learning_choices: dict[str, str] | None = None) -> dict[str, Any]:
        with self.buttons.transaction(project_id):
            return self._add_advancement(project_id, kind, record_id, gm=gm, source=source, learning_choices=learning_choices)

    def _add_advancement(self, project_id: str, kind: str, record_id: str, *, gm: bool = False, source: str = "campaign",
                         learning_choices: dict[str, str] | None = None) -> dict[str, Any]:
        """Learn a Sphere or talent at the table; past the rules only with the GM override, and then marked so."""
        from . import table_advance

        sheet = self.combat._factory_owner_sheet(project_id)
        have = table_advance.known(sheet)
        if kind == "sphere":
            if record_id not in self._sphere_names():
                raise TabletopError("TABLETOP_SPHERE_UNKNOWN", "That is not a Sphere in the rules.", 400)
            status = table_advance.sphere_status(record_id, have)
        elif kind == "talent":
            record = next((row for row in self._catalog_talents() if row.get("canonical_talent_id") == record_id), None)
            if record is None:
                raise TabletopError("TABLETOP_TALENT_UNKNOWN", "That is not a talent in the rules.", 400)
            if record_id in have["talents"]:
                raise TabletopError("TABLETOP_ADVANCE_KNOWN", "The character already knows that talent.", 409)
            status = table_advance.talent_status(record, have)
        else:
            raise TabletopError("TABLETOP_ADVANCE_KIND", "Choose a Sphere or a talent.", 400)
        if not status["legal"] and not gm:
            raise TabletopError("TABLETOP_ADVANCE_NOT_LEGAL", "; ".join(status["reasons"]) or "Not legal for this character now.", 409)
        if source not in ("campaign", "manual", "jade tablet"):
            raise TabletopError("TABLETOP_ADVANCE_SOURCE", "Choose campaign, manual, or jade tablet as the learning source.", 400)
        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        rows = saved[f"{kind}s"]
        if not any(row.get("id") == record_id for row in rows):
            from .ext import run_strict
            if learning_choices:
                offered_keys = {choice["id"] for result in (run_strict(
                    "learning_choices", sheet, record_id, self._catalog_talents(), learning_choices))
                    for choice in (result or [])}
                if not set(learning_choices) <= offered_keys:
                    raise TabletopError("LEARNING_CHOICES_WRONG_OWNER", "These learning choices do not belong to this acquisition.", 422)
            receipts = run_strict("learning_receipt", sheet, kind, record_id,
                                  learning_choices or {}, self._catalog_talents())
            rows.append({"id": record_id, "source": source, "cl": have["cl"], "gm": not status["legal"], **({"reasons": status["reasons"]} if not status["legal"] else {}),
                         "at": table_advance.now(),
                         **({"learning_receipts": [r for r in receipts if r is not None]} if any(r is not None for r in receipts) else {})})
            self.buttons.save_advancement(project_id, saved)
        return self.advancement(project_id)

    def _require_method_downtime(self, project_id: str) -> None:
        """An unfinished fight containing this character blocks Method changes."""
        from .table_method import reject
        actor_id = FACTORY_PREFIX + project_id
        for match in self.combat.list_matches():
            if match.get("status") in ("COMPLETE", "UNSUPPORTED", "IDENTITY_INVALID"):
                continue
            state = self.combat.get_match(match["match_id"])["state"]
            if state.get("terminal_result") is None and any(a.get("entity_id") == actor_id for a in state.get("actors") or []):
                reject("Finish this character's fight before changing Primary Method.")

    def change_method(self, project_id: str, choices: dict[str, Any], *, primary_method_id: str = "") -> dict[str, Any]:
        """Preview or atomically save a source-backed Method lifecycle record."""
        from . import table_advance, table_method
        self._require_method_downtime(project_id)
        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        base = self.combat._factory_owner_sheet(project_id, apply_table=False)
        sheet = self.combat._factory_owner_sheet(project_id)
        proposed = table_method.prepare(sheet, saved, choices, primary_method_id)
        projected = table_advance.memorized(table_advance.apply(base, proposed))
        if not choices.get("save"):
            return {"method": projected["method"], "known_methods": projected["known_methods"],
                    "statistics": projected["ability_scores_and_statistics"],
                    "paths": projected.get("identity") or {}, "foundation": projected.get("foundation"),
                    "change": {k: v for k, v in proposed["method_changes"][-1].items() if k not in ("before", "after_key")}}
        self.buttons.save_advancement(project_id, proposed)
        return self.advancement(project_id, primary_method_id=primary_method_id)

    def undo_method(self, project_id: str, *, primary_method_id: str = "") -> dict[str, Any]:
        from . import table_advance, table_method
        self._require_method_downtime(project_id)
        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        proposed = table_method.undo(saved)
        restored_method_id = saved["method_changes"][-1]["from_method_id"]
        base = self.combat._factory_owner_sheet(project_id, apply_table=False)
        table_advance.apply(base, proposed)
        self.buttons.save_advancement(project_id, proposed)
        # The API supplied the pre-undo Primary Method. Do not let that stale
        # fallback override the restored creation Method in the response.
        return self.advancement(project_id, primary_method_id=restored_method_id)

    def level_up(self, project_id: str, choices: dict[str, Any], *, primary_method_id: str = "") -> dict[str, Any]:
        """Validate all choices and calculations before one growth-record commit."""
        from . import table_advance, table_levelup
        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        base = self.combat._factory_owner_sheet(project_id, apply_table=False)
        sheet = self.combat._factory_owner_sheet(project_id)
        proposed = saved
        levels = choices.get("levels") or [choices]
        if levels[0].get("cl") != choices.get("cl"):
            table_levelup.reject("The first level must match the level you reviewed.")
        for choice in levels:
            proposed = table_levelup.prepare(sheet, proposed, choice, self._catalog_talents(), self._catalog_insights(), primary_method_id=primary_method_id)
            sheet = table_advance.memorized(table_advance.apply(base, proposed))
        self.buttons.save_advancement(project_id, proposed)
        return self.advancement(project_id, primary_method_id=primary_method_id)

    def undo_level(self, project_id: str, *, primary_method_id: str = "") -> dict[str, Any]:
        from . import table_advance, table_levelup
        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        proposed = table_levelup.undo(saved)
        base = self.combat._factory_owner_sheet(project_id, apply_table=False)
        # A live source receipt may have been acquired at the removed level.
        # Reject the proposed projection before changing saved growth.
        self.combat._factory_admission_sheet(project_id, table_advance.apply(base, proposed))
        self.buttons.save_advancement(project_id, proposed)
        return self.advancement(project_id, primary_method_id=primary_method_id)

    def add_ability(self, project_id: str, entry: dict[str, Any], *, gm: bool = False,
                primary_method_id: str = "") -> dict[str, Any]:
        """Record an ability-score change: a GM respec (all six scores, point-buy legal) or a level increase (bounded
        deltas at CL 4+). Legal entries are stored as is; past the rules only with the GM override, marked as a GM grant."""
        from . import table_advance

        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        base = self.combat._factory_owner_sheet(project_id, apply_table=False)
        # Never trust a client-supplied persisted GM marker.
        saved["abilities"].append(table_advance.normalized({"abilities": [
            {**entry, "gm": False, "at": table_advance.now()}]})["abilities"][0])
        index = len(saved["abilities"]) - 1
        history = table_advance.validate_ability_history(base, saved, new_index=index)
        if gm and not history["entries"][index]["status"]["legal"]:
            saved["abilities"][index]["gm"] = True
            history = table_advance.validate_ability_history(base, saved, new_index=index)
        try:
            table_advance.require_ability_history(history)
        except FoundryError as exc:
            raise TabletopError(exc.code, exc.message, 409) from exc
        # Recalculate before committing: formula failures cannot leave a saved
        # score change that breaks every later read of this character.
        table_advance.apply(base, saved)
        self.buttons.save_advancement(project_id, saved)
        return self.advancement(project_id, primary_method_id=primary_method_id)

    def _save_campaign_growth(self, project_id: str, saved: dict[str, Any]) -> None:
        """Shared history gate before any campaign growth mutation. Non-level
        Insights award no scores and consume no level-selection opportunity."""
        from . import table_advance
        base = self.combat._factory_owner_sheet(project_id, apply_table=False)
        table_advance.require_ability_history(table_advance.validate_ability_history(base, saved))
        table_advance.apply(base, saved)
        self.buttons.save_advancement(project_id, saved)

    def add_insight(self, project_id: str, record_id: str, *, note: str, choice: str = "",
                    gm: bool = False) -> dict[str, Any]:
        from . import table_advance, table_growth
        note = table_growth.source_note(note)
        record = next((row for row in self._catalog_insights() if row["canonical_insight_id"] == record_id), None)
        if record is None:
            raise TabletopError("TABLETOP_INSIGHT_UNKNOWN", "Choose an Insight from the rules catalog.", 400)
        sheet = self.combat._factory_owner_sheet(project_id)
        status = table_growth.insight_status(record, sheet, choice=choice)
        # A GM can confirm a story prerequisite/choice, not erase a hard
        # prerequisite, uniqueness rule, or reference-only classification.
        if not status["legal"] and not (gm and status["gm"]):
            raise TabletopError("TABLETOP_ADVANCE_NOT_LEGAL", "; ".join(status["reasons"]), 409)
        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        saved["insights"].append({"id": record_id, "name": record["display_name"], "text": record["full_description"],
                                  "cl": table_advance.known(sheet)["cl"], "note": note, "choice": choice.strip(),
                                  "parameters": status["parameters"],
                                  "gm": bool(status["gm"]), "at": table_advance.now()})
        self._save_campaign_growth(project_id, saved)
        return self.advancement(project_id)

    def immortal_art(self, project_id: str, design: dict[str, Any], *, note: str = "",
                     proof: dict[str, Any] | None = None, save: bool = False) -> dict[str, Any]:
        """Check a custom Art, then record its completed campaign refinement.
        Construction inputs and source snapshots are always server-owned."""
        from . import table_advance, table_growth
        sheet = self.combat._factory_owner_sheet(project_id)
        art = table_growth.construct_art(sheet, design, project_id)
        name = str(design.get("name") or art["name"]).strip()
        if not name or len(name) > 80:
            raise TabletopError("TABLETOP_ART_NAME", "Give your Immortal Art a name of 1–80 characters.", 400)
        # Use the existing combat compiler's ordinary Art path for the preview,
        # not a second implementation of any Factor or source mechanic.
        from .factory_compiler import compile_character
        projected = dict(sheet)
        projected["immortal_arts"] = [*table_growth.arts_of(sheet), {**art, "name": name, "display_name": name}]
        bundle = compile_character(projected, actor_id=FACTORY_PREFIX + project_id)
        result = {"art": art, "name": name,
                  "required_research_hours": art["research_days"] * 8,
                  "required_materials_gp": art["material_cost_gp"],
                  "combat_note": "The fight uses the source action and supported upgrades; unautomated clauses remain for the Game Master.",
                  "skipped": bundle.get("diagnostics", {}).get("skipped", {})}
        if save:
            note = table_growth.source_note(note)
            completed = table_growth.refinement(art, proof or {})
            saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
            if any(row["art"]["art_id"] == art["art_id"] for row in saved["immortal_arts"]):
                raise TabletopError("TABLETOP_ART_KNOWN", "This Immortal Art is already recorded.", 409)
            saved["immortal_arts"].append({"art": art, "name": name, "note": note,
                                           "refinement": completed, "at": table_advance.now()})
            self._save_campaign_growth(project_id, saved)
            result["advancement"] = self.advancement(project_id)
        return result

    def remove_advancement(self, project_id: str, kind: str, record_id: str) -> dict[str, Any]:
        from . import table_advance

        saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
        if kind == "ability":
            index = int(record_id) if record_id.isdigit() else -1
            if 0 <= index < len(saved["abilities"]):
                if (saved["abilities"][index].get("reason") in ("level_increase", "insight_selection")
                        and saved["abilities"][index].get("cl") in {r["cl"] for r in saved["levels"]}):
                    raise TabletopError("TABLETOP_LEVEL_GAIN", "Use Undo last level to remove a level-up ability increase.", 409)
                del saved["abilities"][index]
                base = self.combat._factory_owner_sheet(project_id, apply_table=False)
                history = table_advance.validate_ability_history(base, saved)
                try:
                    table_advance.require_ability_history(history)
                except FoundryError as exc:
                    raise TabletopError(
                        exc.code, "Cannot remove this score change: " + exc.message
                        + ". Remove the dependent score change first.", 409,
                    ) from exc
                table_advance.apply(base, saved)
            self.buttons.save_advancement(project_id, saved)
            return self.advancement(project_id)
        if kind in {"insight", "immortal_art"}:
            if kind == "insight":
                index = int(record_id) if record_id.isdigit() else -1
                if not 0 <= index < len(saved["insights"]):
                    raise TabletopError("TABLETOP_INSIGHT_UNKNOWN", "That campaign Insight entry was not found.", 404)
                if saved["insights"][index].get("source") == "level":
                    raise TabletopError("TABLETOP_LEVEL_GAIN", "Use Undo last level to remove a level-up Insight.", 409)
                del saved["insights"][index]
            else:
                saved["immortal_arts"] = [row for row in saved["immortal_arts"] if row["art"]["art_id"] != record_id]
            self._save_campaign_growth(project_id, saved)
            return self.advancement(project_id)
        key = {"sphere": "spheres", "talent": "talents", "forged": "forged"}.get(kind)
        if key is None:
            raise TabletopError("TABLETOP_ADVANCE_KIND", "Choose a Sphere, a talent, a Forged Technique or an ability.", 400)
        if any(row.get("id") == record_id and row.get("source") == "level" for row in saved[key]):
            raise TabletopError("TABLETOP_LEVEL_GAIN", "Use Undo last level to remove a talent learned during level up.", 409)
        saved[key] = [row for row in saved[key] if (row.get("technique") or {}).get("technique_id", row.get("id")) != record_id]
        self.buttons.save_advancement(project_id, saved)
        return self.advancement(project_id)

    def forge(self, project_id: str, design: dict[str, Any], *, gm: bool = False, save: bool = False, source: str = "campaign") -> dict[str, Any]:
        """Build a Forged Technique from the owner's design (PHB ch. 18, checked by the Forge constructor) and show
        how it plays in combat; ``save`` adds it to the character."""
        from app.core import FoundryError
        from character_creation.constructed_arts.forged_technique import construct_forged_technique
        from character_creation.constructed_arts.forging_authority import load_forging_authority

        from . import forged, table_advance
        from .factory_compiler import TYPED_AUTHORITY

        if not isinstance(design, dict) or not design.get("primary_talent_id") or not design.get("base_form"):
            raise TabletopError("TABLETOP_FORGE_INCOMPLETE", "Choose a Base Form and a Primary Sphere Effect.", 400)
        sheet = self.combat._factory_owner_sheet(project_id)
        mechanics = _typed_mechanics_catalog(str(TYPED_AUTHORITY), TYPED_AUTHORITY.stat().st_mtime_ns)
        request = table_advance.forge_request(sheet, design, self._catalog_talents(), project_id=project_id, gm=gm, mechanics=mechanics)
        try:
            technique = construct_forged_technique(load_forging_authority(Path(__file__).resolve().parents[1]), request, generator_version=3)
        except FoundryError as exc:
            raise TabletopError(exc.code, exc.message, 409) from exc
        picks = design.get("choices") if isinstance(design.get("choices"), dict) else {}
        technique["table_choices"] = {key: str(picks[key]) for key in ("minor_hindrance", "major_condition", "severe_hindrance") if picks.get(key)}
        mechanic = forged.mechanic_for(technique, mechanics)
        result = {"technique": technique, "combat": _combat_preview(mechanic)}
        if source not in ("campaign", "manual", "jade tablet"):
            raise TabletopError("TABLETOP_ADVANCE_SOURCE", "Choose campaign, manual, or jade tablet as the learning source.", 400)
        if save:
            saved = table_advance.normalized(self.buttons.get(project_id).get("advancement"))
            if not any((row.get("technique") or {}).get("technique_id") == technique["technique_id"] for row in saved["forged"]):
                saved["forged"].append({"technique": technique, "gm": bool(gm), "source": source,
                                        "cl": table_advance.known(sheet)["cl"], "at": table_advance.now()})
                self.buttons.save_advancement(project_id, saved)
            result["advancement"] = self.advancement(project_id)
        return result

    # ------------------------------------------------------------ tokens (owner 2026-09-27, combat/portraits.py)
    def _token_store(self):
        from .portraits import TokenStore

        return TokenStore(self.buttons.root.parent / "tabletop_tokens")

    def _picture_store(self):
        from .portraits import TokenStore

        return TokenStore(self.buttons.root.parent / "tabletop_pictures", kind="picture")

    def picture_path(self, project_id: str) -> Path:
        path = self._picture_store().path(project_id)
        if not path.is_file():
            raise TabletopError("TABLETOP_TOKEN_NONE", "This character has no picture yet.", 404)
        return path

    def save_picture(self, project_id: str, data_base64: str) -> dict[str, Any]:
        """Keep the character's full picture (owner 2026-09-27); the token is cut from it by the dialog."""
        import base64
        import binascii

        self.combat._factory_owner_sheet(project_id)  # the character must exist
        text = str(data_base64 or "").split(",", 1)[-1].strip()
        try:
            raw = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise TabletopError("TABLETOP_TOKEN_INVALID", "The picture data is not valid.", 422) from exc
        return {"picture_url": self._picture_store().save(project_id, raw)}

    def delete_picture(self, project_id: str) -> dict[str, Any]:
        self._picture_store().delete(project_id)
        return {"picture_url": None}

    def token_path(self, project_id: str) -> Path:
        path = self._token_store().path(project_id)
        if not path.is_file():
            raise TabletopError("TABLETOP_TOKEN_NONE", "This character has no token yet.", 404)
        return path

    def save_token(self, project_id: str, data_base64: str, circle: dict[str, float] | None = None) -> dict[str, Any]:
        """Keep the circle token the dialog cut (a PNG), and where its circle sat on the picture."""
        import base64
        import binascii

        self.combat._factory_owner_sheet(project_id)  # the character must exist
        text = str(data_base64 or "").split(",", 1)[-1].strip()
        try:
            raw = base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise TabletopError("TABLETOP_TOKEN_INVALID", "The token image data is not valid.", 422) from exc
        url = self._token_store().save(project_id, raw)
        if circle is not None:
            spot = {key: round(float(circle[key]), 4) for key in ("x", "y", "r") if isinstance(circle.get(key), (int, float))}
            self.buttons.save_token_look(project_id, self.buttons.get(project_id).get("token_look") or "", circle=spot if len(spot) == 3 else None)
        return {"token_url": url}

    def delete_token(self, project_id: str) -> dict[str, Any]:
        self._token_store().delete(project_id)
        return {"token_url": None}

    def generate_token(self, project_id: str, look: str | None = None, seed: int | None = None, framing: str = "portrait") -> dict[str, Any]:
        """A picture from the owner's Anima Studio -- a head-and-shoulders portrait, or the character's full picture
        (upper or full body) -- for the dialog to keep and cut the token from; the words are kept for next time."""
        import base64
        import secrets

        from .portraits import anima_generate, portrait_prompt

        sheet = self.combat._factory_owner_sheet(project_id)
        cleaned = " ".join(str(look or "").split())[:300]
        self.buttons.save_token_look(project_id, cleaned)
        chosen = int(seed) if seed is not None else secrets.randbelow(2**31)
        framing = framing if framing in ("portrait", "upper", "full") else "portrait"
        prompt = portrait_prompt(sheet, cleaned, framing)
        image = anima_generate(prompt, chosen, framing=framing)
        return {"image": "data:image/png;base64," + base64.b64encode(image).decode("ascii"), "prompt": prompt, "seed": chosen,
                "framing": framing}

    def token_urls(self, project_ids: list[str]) -> dict[str, str]:
        """Each character's saved round token -- the picture its table token shows -- by project id (the fighter
        picker's cards, owner 2026-10-04).  Characters without one are left out."""
        urls = self._tokens_for([FACTORY_PREFIX + project_id for project_id in project_ids])
        return {actor_id[len(FACTORY_PREFIX):]: url for actor_id, url in urls.items()}

    def _tokens_for(self, actor_ids: list[str]) -> dict[str, str]:
        store, out = self._token_store(), {}
        for actor_id in actor_ids:
            project_id = actor_id[len(FACTORY_PREFIX):] if actor_id.startswith(FACTORY_PREFIX) else ""
            if project_id and "." not in project_id:
                try:
                    url = store.url(project_id)
                except TabletopError:
                    url = None
                if url:
                    out[actor_id] = url
        return out

    def save_summons(self, project_id: str, document: dict[str, Any]) -> dict[str, Any]:
        """Which creatures the character brings (owner 2026-09-27); applies to fights started after this is saved."""
        from .factory_compiler import compile_character

        sheet = self.combat._factory_owner_sheet(project_id)
        options = compile_character(sheet, actor_id=FACTORY_PREFIX + project_id).get("summon_options") or {}
        return self.buttons.save_summons(project_id, document, options)

    def save_granted_spheres(self, project_id: str, spheres: list[str]) -> dict[str, Any]:
        """Spheres granted for combat (owner 2026-09-26); applies to fights started after this is saved."""
        import json as _json

        from .factory_compiler import TYPED_AUTHORITY

        known = set((_json.loads(TYPED_AUTHORITY.read_bytes()).get("sphere_names") or {}))
        self._bundle_and_summary(project_id)  # the character must exist
        return self.buttons.save_granted_spheres(project_id, list(spheres), known)

    def save_powering(self, project_id: str, document: dict[str, Any]) -> dict[str, Any]:
        """Owner 2026-09-25 (Q19): which Path pool pays each choosable ability; applies to fights
        started after this is saved (a running fight keeps the bundle it was created with)."""
        _sheet, bundle, _summary = self._bundle_and_summary(project_id)
        powering = bundle.get("powering") or {"pools": [], "choices": {}}
        pools = [str(name).lower() for name in powering.get("pools") or []]
        choosable = {action_id: pools for action_id in (powering.get("choices") or {})}
        return self.buttons.save_powering(project_id, document, choosable)


def _combat_preview(mechanic: dict[str, Any] | None) -> dict[str, Any] | None:
    """How a Forged Technique plays in combat (combat/forged.py), in words for the Forge panel."""
    if not mechanic:
        return None

    def says(effects: list[Any], depth: int = 0) -> list[str]:
        out: list[str] = []
        for effect in effects or []:
            if not isinstance(effect, dict):
                continue
            kind = effect.get("type")
            if kind == "attack":
                out.append(f"{'weapon' if effect.get('attack_kind') == 'weapon' else 'technique'} attack; on a hit: " + "; ".join(says(effect.get("on_hit"), depth + 1)))
            elif kind == "save":
                fail = "; ".join(says(effect.get("on_fail"), depth + 1)) or "no effect"
                success = "; ".join(says(effect.get("on_success"), depth + 1))
                out.append(f"{str(effect.get('ability') or '').upper()} save: fail: {fail}" + (f"; success: {success}" if success else ""))
            elif kind in ("damage", "extra_damage"):
                dice = effect.get("dice") or {}
                amount = f"{dice.get('count')}d{dice.get('sides')}" if dice.get("count") else str(effect.get("formula") or effect.get("flat") or "")
                who = " to you" if effect.get("applies_to") == "self" else ""
                out.append(f"{amount} {'/'.join(effect.get('damage_types') or [])} damage{who}".strip())
            elif kind == "half_damage":
                out.append("half damage")
            elif kind == "condition":
                out.append(str(effect.get("condition") or "condition").replace("_", " ") + (" (repeats the save)" if effect.get("repeat_save") else ""))
            elif kind == "forced_movement":
                out.append(f"pushed {effect.get('distance_ft')} ft")
            elif kind == "movement":
                out.append(f"you move {effect.get('distance_ft')} ft" + (" without provoking" if effect.get("no_opportunity_attacks") else ""))
            elif kind == "temp_hp":
                out.append(f"temporary HP ({effect.get('formula')})")
            elif kind == "resistance":
                out.append(f"Resistance to {'/'.join(effect.get('damage_types') or [])}")
            elif kind == "speed":
                out.append(f"Speed {effect.get('flat')} ft")
            elif kind in ("suppress_resistance", "ignore_resistance"):
                out.append("ignores Resistance")
            elif kind:
                out.append(str(kind).replace("_", " "))
        return out

    area = mechanic.get("area") or {}
    reach = mechanic.get("range") or {}
    duration = mechanic.get("duration") or {}
    return {"form": mechanic.get("base_form"), "economy": (mechanic.get("activation") or {}).get("economy"),
            "range": "self" if reach.get("kind") == "self" else f"{reach.get('feet')} ft" if reach.get("feet") else None,
            "area": f"{area.get('size_ft')}-ft {area.get('shape')}" if area else None,
            "duration": ("Concentration, " if duration.get("concentration") else "") + f"{duration.get('amount') or ''} {duration.get('kind') or 'instant'}".strip(),
            "effects": says(mechanic.get("effects") or []), "gm": list(mechanic.get("riders") or []),
            "text": list(mechanic.get("description") or [])}
