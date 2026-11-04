"""Presentation ranking for a fighter's turn menu: tactical tier, then embedding fit.

Who uses it: ``TabletopService.state`` (combat/tabletop_service.py), at the one
marked seam after menu construction and decoration finish, and the AI-seat
bounded candidate list (agent_seats/runner.py's ``_builtin``). Nothing here
changes which candidates are legal or offered; it only orders the options a
group or the move list already has, and marks how many the quick bar shows
before "More...". Character sheets and ``act`` submissions are unaffected:
candidate ids are never dropped or renumbered, only reordered.

Perceived-only: every text given to the embedding service is built from the
acting creature's own state and from targets already present in its menu
(already filtered to legal, visible candidates upstream). No hidden creature,
zone or action ever reaches the query text, an option's text or the cache key.

Ordering contract: native AI effectiveness, when supplied, plus a bounded
semantic contribution for creative/Dao fit; otherwise tactical tier first.
Integer effectiveness differences dominate semantic fit. Ties retain source
order. Service failures preserve native-score/tier order without network wait.

Rate limit and circuit breaker (owner 2026-10-13, after an incident: a test
run flooded the live EmbeddingGemma service at ~40 requests/s and hung the
host GPU): the default production client is capped at ``_MAX_REQUESTS_PER_S``
real requests per second, and after ``_FAILURE_THRESHOLD`` consecutive
failures stops attempting the network for ``_COOLDOWN_S`` -- both checked
before a request is sent, never after a slow one is already in flight. Tests
and other callers that pass their own ``client`` are never rate limited or
breaker-tracked; they own their own fake transport and must never reach the
live service at all (see tests/conftest.py's socket-level block).
"""
from __future__ import annotations

import threading
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterable, Sequence
from collections import OrderedDict
from weakref import WeakKeyDictionary

from . import embedding_rank as er

QUICK_BAR_SIZE = 5
# One batch per menu, not one per ability group; shortlist at most 15 per slot.
MENU_BUDGET_S = 0.15
EMBED_CANDIDATES = 45

_MAX_REQUESTS_PER_S = 5.0
_FAILURE_THRESHOLD = 3
_COOLDOWN_S = 30.0

_guard_lock = threading.Lock()
_next_allowed_at = 0.0
_consecutive_failures = 0
_breaker_open_until = 0.0
_observed_batches = WeakKeyDictionary()
_observed_lock = threading.Lock()


def prefetch_next_actor(engine, actor_id, texts, *, client=None):
    """Warm the next actor's last issued perceived menu, never predict rules.

    Stores bounded immutable text snapshots per engine, not live state or
    fabricated future candidates. Cold actors warm on their first issued menu;
    later turns reuse these speculative vectors only when their hashes match.
    All CPU/network work belongs to the client's bounded background worker.
    """
    active = client or _CLIENT
    order = getattr(engine.state, "initiative_order", ())
    if actor_id not in order or len(order) < 2:
        return
    next_id = order[(order.index(actor_id) + 1) % len(order)]
    with _observed_lock:
        batches = _observed_batches.setdefault(engine, {})
        batches[actor_id] = tuple(texts)
        pending = batches.get(next_id)
    if pending:
        active.prefetch(pending, deferred=True)


# Which cached embeddings a menu ranking relied on, for whoever keeps a ranked menu between reads
# (combat/table_state_cache.py). Each row is (client, texts, used): ``used`` is True when the order
# blended the texts' cached vectors and False when it fell back to native/tier order.
_RANKING_RECORD: ContextVar[list | None] = ContextVar("menu_rank_ranking_record", default=None)


@contextmanager
def ranking_record():
    """Collect, for this thread's rankings inside the block, the embedding texts each asked for and whether it used them."""
    rows: list = []
    token = _RANKING_RECORD.set(rows)
    try:
        yield rows
    finally:
        _RANKING_RECORD.reset(token)


def _note_ranking(client, texts, used: bool) -> None:
    rows = _RANKING_RECORD.get()
    if rows is not None:
        rows.append((client, tuple(texts), used))


def ranking_current(rows) -> bool:
    """Whether ranking the recorded texts again would use cached vectors exactly as it did (the same order).

    A client that cannot say what it holds is never trusted to repeat an order.
    """
    for client, texts, used in rows or ():
        holds = getattr(client, "holds", None)
        if holds is None or holds(texts) != used:
            return False
    return True


def rewarm(rows) -> None:
    """Repeat a fresh ranking's side effect for texts it fell back on: ask the client to warm them in the background."""
    for client, texts, used in rows or ():
        if not used and getattr(client, "background", False):
            try:
                client.prefetch(texts)
            except Exception:  # noqa: BLE001 - warming is best effort; ordering stays the native/tier fallback
                pass


def _production_request_allowed() -> bool:
    return (_default_client_request_allowed(time.monotonic)
            and er.cpu_server_pid() is not None)


def _default_client_request_allowed(clock: Callable[[], float]) -> bool:
    """True at most _MAX_REQUESTS_PER_S times/second, and never while the
    breaker is open. Only guards the shared default client (see rank_ids)."""
    global _next_allowed_at
    with _guard_lock:
        now = clock()
        if now < _breaker_open_until or now < _next_allowed_at:
            return False
        _next_allowed_at = now + 1.0 / _MAX_REQUESTS_PER_S
        return True


def _record_default_client_result(ok: bool, clock: Callable[[], float]) -> None:
    global _consecutive_failures, _breaker_open_until
    with _guard_lock:
        if ok:
            _consecutive_failures = 0
            return
        _consecutive_failures += 1
        if _consecutive_failures >= _FAILURE_THRESHOLD:
            _breaker_open_until = clock() + _COOLDOWN_S


def default_client() -> er.EmbeddingClient:
    return _CLIENT


_CLIENT = er.EmbeddingClient(
    deadline_s=MENU_BUDGET_S,
    # HTTP completes in the single cache worker. Turn calls never wait; late
    # valid CPU responses populate the cache instead of becoming failures.
    transport=er._post,
    background=True,
    before_request=_production_request_allowed,
    request_result=lambda ok: _record_default_client_result(ok, time.monotonic),
)


def enabled() -> bool:
    """Presentation/seat seam can be disabled without changing native AI choices."""
    return os.environ.get("CF_EMBED_MENU", "1") != "0"


def goal_text(sheet: dict) -> str:
    """Only the character's own sheet guidance, never Composite Playbooks.

    Shared by the table and model seats. Use the same sphere-derived Dao as
    the owner sheet when an older installed sheet lacks character_dao.
    """
    built = sheet.get("character_dao") or {}
    if not built:
        from factory_authoring.sphere_dao import character_dao, sheet_sphere_talents
        built = character_dao(sheet_sphere_talents(sheet)) or {}
    surface = ((sheet.get("surfaces") or {}).get("dao_i_ching") or {}).get("data") or {}
    guidance = (sheet.get("dao_iching") or sheet.get("dao_i_ching")
                or (sheet.get("stats") or {}).get("dao_i_ching") or surface)
    if not isinstance(guidance, dict):
        guidance = {}
    guidance = guidance.get("dao_i_ching") or guidance
    parts = []
    def add(value):
        if isinstance(value, str) and value:
            parts.append(value[:240])
        elif isinstance(value, list):
            for item in value[:6]:
                add(item)
        elif isinstance(value, dict):
            for key in ("name", "display_name", "meaning", "image", "core_theme", "principles",
                        "tactical_expression", "roleplay_expression", "strengths", "risks", "change_rule"):
                add(value.get(key))
    add(built.get("primary_sphere"))
    add(built.get("dao_verbs"))
    for layer in (built.get("layers") or [])[:6]:
        add(layer.get("name"))
        add(layer.get("reality_principle"))
    add(built.get("hexagram"))
    for posture in (built.get("posture") or {}).values():
        add(posture)
    add(guidance.get("dao") or sheet.get("dao"))
    add(guidance.get("i_ching") or sheet.get("i_ching"))
    return "; ".join(parts)[:1800]


def sheet_goal(combat, actor_id: str) -> str:
    """Read only this fighter's existing installed sheet; absent guidance is neutral."""
    prefix = "actor:factory."
    if not actor_id.startswith(prefix):
        return ""
    try:
        import json
        import zipfile
        project_id = actor_id[len(prefix):]
        sheet = dict(combat._factory_owner_sheet(project_id))
        # Authored guidance is already a sheet surface, stored alongside the
        # owner sheet in its installed package. No Playbook reads or inference.
        try:
            package = combat.combatant_library.install_root / project_id / "current.zip"
            with zipfile.ZipFile(package) as archive:
                if "Dao_IChing_Combat_Profile.json" in archive.namelist():
                    sheet["dao_i_ching"] = json.loads(archive.read("Dao_IChing_Combat_Profile.json"))
        except (AttributeError, OSError, ValueError, zipfile.BadZipFile):
            pass  # older packages still have the sphere-derived sheet guidance
        return goal_text(sheet)
    except Exception:
        return ""


def slot_for(economy: str, *, moving: bool = False) -> str:
    from .action_economy import slot_for as economy_slot
    return economy_slot(economy, moving=moving)


def destination_order(moves: Sequence[dict], provider=None) -> list[dict]:
    """VISIONMOVE2 seam: provider(moves) -> {candidate_id: integer score}.

    Receives only the actor's issued destinations. Default uses known hazard
    exposure, never grants legality, and ties retain source order.
    """
    scores = provider(moves) if provider is not None else {}
    return sorted(moves, key=lambda row: (-scores.get(row["candidate_id"], 0),
                                         -tier_from_hazard_exposure(row.get("hazard_exposure"))))


def bounded_slots(ordered: Sequence[str], slots: dict[str, str], limit=QUICK_BAR_SIZE) -> dict[str, list[str]]:
    """The same top-five-per-slot ids for Assisted display and AI/model seats."""
    from .action_economy import LABELS
    result = {slot: [] for slot in dict.fromkeys(["Movement", *LABELS.values()])}
    for key in dict.fromkeys(ordered):
        slot = slots.get(key)
        if slot in result and len(result[slot]) < limit:
            result[slot].append(key)
    return result


def native_scores(combat, engine, known: set[str], *, session=None, candidate_ids=None) -> dict[str, int]:
    """Reuse the native controller's scoring without executing its chosen action.

    A bounded service-owned cache avoids rescoring on every table poll. The
    context is restricted to perceived creatures/zones and issued candidates.
    No engine function or saved state is replaced or modified.
    """
    from .gate4_context import build_decision_context
    from .canonical import canonical_sha256
    actor_id = engine.state.current_actor_id
    policy, _ = combat.policies.for_actor(actor_id)
    boundary = combat._state_key(session) if session is not None else None
    key = (boundary or (engine.state.match_id, engine.state.state_version), actor_id, tuple(sorted(known)),
           canonical_sha256(policy.model_dump(mode='json')),
           None if candidate_ids is None else tuple(sorted(candidate_ids)))
    cache = getattr(combat, "_menu_rank_scores", None)
    if cache is None:
        cache = combat._menu_rank_scores = OrderedDict()
    if boundary is not None and key in cache:
        cache.move_to_end(key)
        return dict(cache[key])
    # ai_veto=False: these scores order a person's own menu, so the built-in AI's restraint must not remove
    # rows from the context they are read from (gate4_context.build_decision_context).
    context = (combat.menu_ranking_context(session) if session is not None
               else build_decision_context(engine, policy, for_ai=True, ai_veto=False))
    context = context.model_copy(update={
        "actors": tuple(a for a in context.actors if a.entity_id in known),
        "zones": (), "recent_events": (),
        "legal_candidates": tuple(c for c in context.legal_candidates if set(c.target_ids) <= known),
        "team_behavior": context.team_behavior.model_copy(update={"focus_target_id": None}),
        # Table order keeps the incumbent scorer (452076b6): the AI tier profile
        # is never used for presentation scores, so a tier change cannot reorder
        # a human menu. Built-in AI turn selection still reads it from the
        # production context returned by menu_ranking_context.
        "tactics": {},
    })
    # Scoring concrete CELL choices that have no button cannot affect the table
    # order. Keep all candidates as tactical facts, and only project scores.
    requested = candidate_ids
    if requested is not None and not any(c.candidate_id in requested for c in context.legal_candidates):
        return {}  # a menu containing only picker roots has no concrete score
    from .gate4_controller import LocalDeterministicController
    controller = combat.controller
    if (type(controller) is LocalDeterministicController
            and getattr(controller.choose_primary_action, '__func__', None)
                is LocalDeterministicController.choose_primary_action):
        pick = controller.score_primary_projection(context, requested)
    else:
        # Public/custom choice adapters keep their existing scoring contract.
        # Never inject a new keyword into an overridden controller method.
        pick = controller.choose_primary_action(context)
    result = {row.candidate_id: row.total for row in pick.record.scored_alternatives}
    if boundary is not None:
        cache[key] = result
    while len(cache) > 64:
        cache.popitem(last=False)
    return dict(result)


def rank_menu(menu, engine, *, combat=None, known=None, destination_provider=None, session=None):
    """One presentation seam: preserve full menu, expose ranked slot ids.

    SUGGESTED is the engine's existing player-owned Assisted mode. No new
    controller enum, turn automation, legality, or saved-fight data is needed.
    destination_provider is the public VISIONMOVE2 hook (see destination_order).
    """
    if not menu or not menu.get("manual") or engine is None or not enabled():
        return
    actor_id = menu.get("actor_id")
    actor = engine.state.actors.get(actor_id)
    if known is None:
        from .target_knowledge import actors_for
        try:
            known = {a.entity_id for a in actors_for(engine, actor)}
        except (AttributeError, TypeError):
            known = {actor_id}  # incomplete perception must never reveal others
    known = set(known) | {actor_id}
    scores, goal = {}, ""
    if combat is not None:
        goal = sheet_goal(combat, actor_id)
    # Compact human grids deliberately omit movement candidates and tactical
    # context. Keep the existing prose/effect ranking fallback without rebuilding
    # the full AI menu behind the table's highlight query.
    if combat is not None and 'movement_grid' not in menu:
        try:
            issued = {row['candidate_id'] for group in menu.get('actions') or []
                      for row in group.get('options') or []}
            issued.update(row['candidate_id'] for row in menu.get('moves') or [])
            if menu.get('end_turn'):
                issued.add(menu['end_turn'])
            scores = native_scores(combat, engine, known, session=session, candidate_ids=issued)
        except (ValueError, AttributeError, KeyError):
            pass  # ordinary tier fallback for partial/unusual decision contexts
    names = []
    rows, slots, references = [], {}, {}
    for group in menu.get("actions") or []:
        if group.get('lazy'):
            # Source references are inspection handles, never candidate IDs.
            # Rank only availability prose here; targets stay unexpanded until
            # the player selects this source in either Assisted client.
            key = 'source:' + group['source_definition_id']
            slots[key] = slot_for(group.get('economy', 'ACTION'))
            text = perceived_text(group.get('label'), str(group.get('description') or '')[:200])
            for hidden_id, hidden in engine.state.actors.items():
                if hidden_id not in known:
                    for token in (hidden_id, getattr(hidden, 'display_name', '')):
                        if token:
                            text = text.replace(token, 'an unseen creature')
            rows.append((key, text, 0))
        for option in group.get("options") or []:
            key = option["candidate_id"]
            slots[key] = slot_for(group.get("economy", "ACTION"))
            references[key] = option
            if not set(option.get("target_ids") or []) <= known:
                continue
            names.extend(option.get("target_names") or [])
            text = perceived_text(group.get("label"), option.get("label"),
                                  ", ".join(option.get("target_names") or []),
                                  str(group.get("description") or "")[:200])
            # Prose can mention creatures outside target_ids. Redact those too.
            for hidden_id, hidden in engine.state.actors.items():
                if hidden_id not in known:
                    for token in (hidden_id, getattr(hidden, "display_name", "")):
                        if token:
                            text = text.replace(token, "an unseen creature")
            rows.append((key, text, tier_from_hostile_effect(option.get("expected_damage"),
                                                            bool(option.get("target_ids")))))
    query = situation_text(getattr(actor, "current_hp", None), getattr(actor, "maximum_hp", None), names, goal=goal)
    ordered = rank_ids(query, rows, scores=scores, slots=slots)
    # Speculative next-actor warming uses only previously issued own-view text.
    presorted = sorted(rows, key=lambda row: (-scores.get(row[0], row[2]), -row[2]))
    selection = bounded_slots([key for key, _, _ in presorted], slots, limit=15)
    selected_ids = {key for keys in selection.values() for key in keys}
    prefetch_next_actor(engine, actor_id, [query, *(text for key, text, _ in presorted if key in selected_ids)])
    position = {key: i for i, key in enumerate(ordered)}
    for group in menu.get("actions") or []:
        group["options"] = sorted(group.get("options") or [],
                                  key=lambda option: position.get(option["candidate_id"], len(position)))
        group["options_shown"] = min(QUICK_BAR_SIZE, len(group["options"]))
    menu["moves"] = destination_order(menu.get("moves") or [],
        destination_provider or (lambda moves: scores))
    menu["moves_shown"] = min(QUICK_BAR_SIZE, len(menu["moves"]))
    for move in menu["moves"]:
        slots[move["candidate_id"]] = "Movement"
    movement = [m['candidate_id'] for m in menu['moves']]
    if menu.get('movement_grid') and not movement:
        # The browser maps this source to compact quotes. A quote must pass
        # exact native preview before it can be offered for confirmation.
        movement = ['movement:compact']
        slots[movement[0]] = 'Movement'
    menu["ranked_slots"] = bounded_slots([*movement, *ordered], slots)
    menu["turn_mode"] = "Assisted" if menu.get("control_mode") == "SUGGESTED" else "Manual"


def tier_from_hostile_effect(expected_damage: int | None, has_target: bool) -> int:
    """Higher tier: this option visibly affects a hostile already in reach."""
    return 1 if has_target and (expected_damage or 0) > 0 else 0


def tier_from_hazard_exposure(hazard_exposure: bool | None) -> int:
    """Higher tier: this destination does not carry the hazard exposure flag."""
    return 0 if hazard_exposure else 1


def perceived_text(*parts: object) -> str:
    return " ".join(str(part) for part in parts if part)


def hp_bucket(current_hp: int | None, max_hp: int | None) -> str:
    if not max_hp:
        return "unknown condition"
    fraction = (current_hp or 0) / max_hp
    if fraction <= 0.25:
        return "critically hurt"
    if fraction <= 0.5:
        return "bloodied"
    if fraction < 1.0:
        return "lightly hurt"
    return "unhurt"


def situation_text(current_hp: int | None, max_hp: int | None, visible_target_names: Iterable[str], *, goal: str = "") -> str:
    """A short perceived-only summary: own condition plus already-legal targets."""
    parts = [f"you are {hp_bucket(current_hp, max_hp)}"]
    names = sorted(dict.fromkeys(name for name in visible_target_names if name))
    if names:
        parts.append("creatures you can act on nearby: " + ", ".join(names[:12]))
    if goal:
        parts.append("seek effective, creative choices that express your Dao and response to change: " + goal)
    return "; ".join(parts)


def rank_ids(query_text: str, rows: Sequence[tuple[str, str, int]], *,
             client: er.EmbeddingClient | None = None, scores: dict[str, int] | None = None,
             slots: dict[str, str] | None = None) -> list[str]:
    """Blend native integer scores (or tactical tiers) with 0..0.5 semantic fit.

    All failures keep the deterministic native/tier ordering. Embedding is
    bounded to 45 candidates, reserving 15 per slot when slot ids are supplied;
    every other id remains in the returned menu. Fake clients bypass default
    network guards; production guards actual requests, not cache hits.
    """
    if len(rows) < 2:
        return [row_id for row_id, _, _ in rows]
    started = time.monotonic()
    scores = scores or {}
    effective = {row_id: scores.get(row_id, tier) for row_id, _, tier in rows}
    tier_sorted = sorted(rows, key=lambda row: (-effective[row[0]], -row[2]))
    options = [(row_id, text) for row_id, text, _ in tier_sorted]
    tiers = {row_id: tier for row_id, _, tier in tier_sorted}
    original = [row_id for row_id, _ in options]
    active_client = client or _CLIENT
    try:
        if slots:
            selected = bounded_slots(original, slots, limit=15)
            selected_ids = {k for values in selected.values() for k in values}
            shortlist = [row for row in options if row[0] in selected_ids]
        else:
            shortlist = options[:EMBED_CANDIDATES]
        texts = [query_text, *(text for _, text in shortlist)]
        try:
            vectors = active_client.embed(texts)
        except Exception:
            _note_ranking(active_client, texts, False)
            raise
        if time.monotonic() - started > MENU_BUDGET_S:
            _note_ranking(active_client, texts, False)
            return original
        _note_ranking(active_client, texts, True)
        # Tier is a hard safety preference. Native effectiveness dominates;
        # semantic fit is a small, bounded creative/Dao contribution.
        fit = {row_id: 0.25 * (1 + er.cosine(vectors[0], vectors[i + 1]))
               for i, (row_id, _) in enumerate(shortlist)}
        ranked = sorted(enumerate(options), key=lambda item: (
            -(effective[item[1][0]] + fit.get(item[1][0], 0)),
            -tiers[item[1][0]], item[0]))
        return [row_id for _, (row_id, _) in ranked]
    except Exception:
        return original
