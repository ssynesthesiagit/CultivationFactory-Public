from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import shutil
import struct
import threading
import time
import zipfile
from copy import copy
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_bytes, canonical_sha256, sha256_file
from .choice_authority import canonicalize_option_selection, validate_option_selection
from .commit_diagnostics import record_commit_divergence
from .diagnostics import CombatGate1Error
from .ext import ControllerPause, query as extension_hooks
from .gate2_runtime_content import ACTORS, AN, BAI, CUI
from .footprint_registry import resolve_actor_footprint
from .gate2_grid import SquareGrid
from .gate2_runtime_models import ActionIntent, CombatEvent, Position, ReactionDecision, RollRecord
from .gate3_reducer import canonical_state_sha256
from .gate3_storage import Gate3MatchStore
from .gate4_adapters import ManualControllerAdapter
from .gate4_context import build_decision_context, build_reaction_context
from .gate4_controller import LocalDeterministicController
from .gate4_engine import Gate4ControllerEngine
from .gate4_models import DecisionRecord, ReactionContext
from .gate4_persistence import Gate4Persistence, Gate4PersistentSession, _read_jsonl
from .saved_fight_format import UNSUPPORTED_CODE, UNSUPPORTED_MESSAGE
from .gate4_policy import PolicyLibrary
from .history_feed import format_history_feed, concealed_condition_instances
from .history_text import history_name
from .presentation import CombatPresentationProjector
from .pre_encounter import CombatantLibraryService
from .portable_runtime_authority import (
    PortableRuntimeAuthority, build_runtime_authority, runtime_actor_id,
    RUNTIME_AUTHORITY_FILE, SOURCE_PACKAGE_FILE,
)


CONTROL_MODES = ("MANUAL", "SUGGESTED", "LOCAL_AUTO", "API_AUTO", "MANUAL_AI_BRIDGE")
MANUAL_SUBMIT_MODES = frozenset({"MANUAL", "SUGGESTED", "MANUAL_AI_BRIDGE"})
READINESS_STATUSES = (
    "COMBAT_READY",
    "COMBAT_PROJECTION_INCOMPLETE",
    "UNSUPPORTED_MECHANICS",
    "REQUIRES_RECOMPILATION",
)
INTEGRATION_SCHEMA = "TianxiaFactoryCombatIntegration.v1"
# Finished Factory characters compiled to typed fighters (combat/factory_compiler.py).
FACTORY_ACTOR_PREFIX = "actor:factory."
# Owner-editable arenas for Factory test fights (combat/rules/arenas/*.json).
FACTORY_ARENA_DIR = "combat/rules/arenas"
DEFAULT_FACTORY_ARENA = "battlefield:map.builtin-sect-trial-platform"
AI_FRAME_SCHEMA = "TianxiaFactoryCombatAIDecisionFrame.v1"
AI_RESPONSE_SCHEMA = "TianxiaFactoryCombatAIIntent.v1"
MATCH_ID_RE = re.compile(r"^match:[a-f0-9]{24}$")
VISUAL_ASSET_FILE_RE = re.compile(r"^[a-f0-9]{64}\.(?:png|jpg|webp)$")
MAX_CUSTOM_VISUAL_BYTES = 12 * 1024 * 1024
VISUAL_PROFILE_SCHEMA = "TianxiaFactoryCombatVisualProfile.v1"
MATCH_VISUAL_SCHEMA = "TianxiaFactoryCombatMatchVisuals.v1"
COMBAT_PROVIDER_SYSTEM_MESSAGE = (
    "You are an untrusted Tianxia combat decision adapter. Return exactly one JSON object "
    "matching TianxiaFactoryCombatAIIntent.v1. Select only IDs and option combinations offered "
    "in the supplied Decision Frame. Do not invent mechanics, targets, destinations, IDs, rolls, "
    "statistics, tools, or instructions. The local deterministic combat runtime validates every "
    "field and remains the sole mechanical authority."
)

DIAGNOSTIC_CATALOG = {
    UNSUPPORTED_CODE: UNSUPPORTED_MESSAGE,
    "COMBAT_SERVICE_UNAVAILABLE": "The in-process CombatService could not initialize or answer.",
    "COMBAT_CONTENT_NOT_READY": "Required bound combat content is absent, unsupported, or not executable.",
    "COMBAT_MATCH_NOT_FOUND": "The requested persistent match does not exist or cannot be addressed safely.",
    "COMBAT_MATCH_ALREADY_COMPLETE": "The match is terminal and cannot accept another combat decision.",
    "COMBAT_MATCH_PAUSED": "A mutating auto-control operation was requested while the match is paused.",
    "COMBAT_CONTROL_MODE_INVALID": "A participant control mode is not one of the Gate 5 supported modes.",
    "COMBAT_CONTROLLER_MODE_MISMATCH": "The requested controller path does not own the active fighter at this decision boundary.",
    "COMBAT_DECISION_STALE": "The submitted decision does not bind the current immutable decision context.",
    "COMBAT_PREVIEW_MISMATCH": "Authoritative execution did not bind or reproduce the checked deterministic preview.",
    "COMBAT_REACTION_DECISION_REQUIRED": "An actual deterministic reaction checkpoint requires manual input.",
    "COMBAT_AI_INTENT_INVALID": "A pasted AI intent or reaction contains unknown, illegal, or invented values.",
    "COMBAT_EXPORT_FAILED": "The persistent match could not be exported to a checksummed local package.",
    "COMBAT_UI_DATA_INVALID": "Factory integration metadata or setup input is invalid.",
    "COMBAT_OPERATION_SLOW": "A measured local combat operation exceeded its practical responsiveness target.",
}


@dataclass(frozen=True)
class CombatServiceDiagnostic:
    code: str
    message: str
    subsystem: str
    retry_safe: bool
    recommended_action: str
    match_id: str | None = None
    actor_id: str | None = None
    decision_id: str | None = None
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "subsystem": self.subsystem,
            "retry_safe": self.retry_safe,
            "recommended_action": self.recommended_action,
            "match_id": self.match_id,
            "actor_id": self.actor_id,
            "decision_id": self.decision_id,
            "details": self.details or {},
        }


class CombatServiceError(Exception):
    def __init__(self, diagnostic: CombatServiceDiagnostic, *, status_code: int = 400):
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic
        self.status_code = status_code

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.diagnostic.as_dict()}


class _AnsweringController:
    """The local controller, answering the Ask me prompts a player already answered (step 16) with a manual record,
    so the committed action gets the same reactions as the probe that asked."""

    def __init__(self, base: Any, answers: dict[tuple[str, str, str], ReactionDecision]):
        self._base, self._answers = base, answers

    def choose_reaction(self, context: ReactionContext) -> Any:
        answer = self._answers.get((context.checkpoint, context.reactor_id, context.reaction_source_id))
        if answer is None:
            return self._base.choose_reaction(context)
        return ManualControllerAdapter(lambda _context: ("", ()), reaction_chooser=lambda _context: answer).choose_reaction(context)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


class _ReactionRequired(ControllerPause):
    """A player's reaction came up while an action runs on a throwaway probe copy (preview, or an AI step's
    ``_ask_during_ai_step``): the probe stops here and the table asks. A BaseException, not an error, so the
    engine's "a bad reaction row must never end a fight" guards (``except Exception`` in typed_reactions.py and the
    extension hooks) cannot mistake the pause for a broken row, log it, and let the probe run on. Owner playtest
    2026-09-30: the swallowed Flowing Response pause put one GM note into the probe's log, so the Stamina Guard
    prompt that followed was keyed one event later than the real action's damage and the player's Use never
    applied. Only probe engines raise it; the probe is discarded, so its skipped rollback does not matter."""

    def __init__(
        self,
        context: ReactionContext,
        suggestion: dict[str, Any] | None,
        *,
        resolved_reactions: tuple[ReactionDecision, ...] = (),
        reaction_records: tuple[dict[str, Any], ...] = (),
    ):
        super().__init__("COMBAT_REACTION_DECISION_REQUIRED")
        self.context = context
        self.suggestion = suggestion
        self.resolved_reactions = resolved_reactions
        self.reaction_records = reaction_records
        self.menu_contexts = ()

    def context_doc(self):
        doc = self.context.model_dump(mode="json", by_alias=True)
        checkpoint = self.context.checkpoint.split("@", 1)[0].removeprefix("TYPED:")
        if len(self.menu_contexts) > 1 or (self.menu_contexts and checkpoint in {
                "ATTACK_HIT_BEFORE_DAMAGE", "DAMAGE_APPLICATION"}):
            doc["reaction_choices"] = [c.model_dump(mode="json", by_alias=True) for c in self.menu_contexts]
        return doc


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_utc(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _epoch(value: Any) -> float | None:
    """Seconds since the epoch for an ISO timestamp string, or None when it is missing or unreadable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def sort_matches_newest_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Saved fights by last_played_at, newest first; fights with no usable time go last. Ties fall back to match id.

    Used by CombatService.list_matches, which the fight lobby (GET /api/combat/matches) shows in this order.
    """
    def key(row: dict[str, Any]) -> tuple[float, str]:
        when = _epoch(row.get("last_played_at"))
        return (when if when is not None else float("-inf"), str(row.get("match_id") or ""))
    return sorted(rows, key=key, reverse=True)


def _zone_row(zone: Any, engine: Any = None) -> dict[str, Any]:
    """One zone row as the table receives it, with any plug-in's drawing facts merged into its visual block.

    ``zone_visual`` (combat/ext/__init__.py) lets a plug-in say how an area of its own family should be drawn
    from that area's typed provenance. It is presentation only: nothing saved changes, and no sight, fog or
    obscuration rule reads what it returns. Takes the serialised row rather than the ZoneState so that a live
    boundary and a replayed historical one are drawn the same way. With no subscriber every area serialises
    exactly as before.
    """
    row = zone if isinstance(zone, dict) else zone.model_dump(mode="json")
    if engine is None or not isinstance(row, dict):
        return row
    from . import ext

    for facts in ext.run("zone_visual", engine, row) or []:
        if not isinstance(facts, dict) or not facts:
            continue
        profile = row.get("trigger_profile")
        if not isinstance(profile, dict):
            continue
        visual = profile.get("visual")
        row["trigger_profile"] = {**profile, "visual": {**(visual if isinstance(visual, dict) else {}), **facts}}
    return row


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(canonical_bytes(value) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_once_exact_json(path: Path, value: dict[str, Any]) -> None:
    payload = canonical_bytes(value) + b"\n"
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError(f"immutable artifact mismatch: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp.{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _safe_zip_name(path: Path, root: Path) -> str:
    return str(path.relative_to(root)).replace(os.sep, "/")


class CombatService:
    """Application-facing Gate 5 integration over the accepted Gate 2–Gate 4 stack."""

    def __init__(self, source_root: Path, userdata_root: Path, *, ai_provider: Any | None = None):
        from .terminal_summary_cache import TerminalSummaryCache

        self._terminal_summaries = TerminalSummaryCache()
        started = time.perf_counter()
        self.source_root = Path(source_root).resolve()
        self.userdata_root = Path(userdata_root).resolve()
        self.combatant_library = CombatantLibraryService(self.source_root, self.userdata_root)
        self.controller = LocalDeterministicController()
        self._dao_policies: dict[str, dict[str, Any] | None] = {}
        # What is worked out from one saved state of a fight (legal candidates, the decision menu); see _state_key.
        self._derived: OrderedDict[str, tuple[Any, dict[str, Any]]] = OrderedDict()
        self._derived_lock = threading.Lock()
        self.policies = PolicyLibrary(self.source_root, actor_policy=self._dao_policy_for_actor)
        self.persistence = Gate4Persistence(self.source_root, self.userdata_root,
            policy_library=self.policies, engine_inputs=self._reconstructed_inputs,
            recover_choice=self._recover_local_choice)
        self.presenter = CombatPresentationProjector(self.source_root)
        self.ai_provider = ai_provider
        self.combat_root = self.userdata_root / "Combat"
        self.matches_root = self.combat_root / "Matches"
        self.exports_root = self.combat_root / "Exports"
        self.performance_path = self.combat_root / "Performance.ndjson"
        self.visual_manifest_path = self.source_root / "static" / "combat_visuals" / "manifest.json"
        self.visual_profile_root = self.combat_root / "VisualProfile"
        self.visual_profile_assets_root = self.visual_profile_root / "Assets"
        self.visual_profile_path = self.visual_profile_root / "Profile.json"
        self._visual_manifest = self._load_visual_manifest()
        self._definition_names = self._load_definition_names()
        self.matches_root.mkdir(parents=True, exist_ok=True)
        self.exports_root.mkdir(parents=True, exist_ok=True)
        self._catalog_cache = self._load_catalog()
        self.startup_us = max(1, round((time.perf_counter() - started) * 1_000_000))
        self.startup_ms = max(1, round(self.startup_us / 1000))
        self._record_metric("service_startup", self.startup_us, threshold_ms=2000)

    # ------------------------------------------------------------------
    # Diagnostics and timing
    # ------------------------------------------------------------------

    @property
    def journeys(self):
        """Elapsed-time map travel; independent of match/turn persistence."""
        from .journey import JourneyStore
        return JourneyStore(self.combat_root / 'Journeys')

    def create_journey(self, *, project_ids, arena_id, positions, base_paces, control_modes=None, loaded_paces=None):
        bundles = [self.compile_factory_actor(pid) for pid in project_ids]
        return self.journeys.create(bundles, self.factory_arenas()[arena_id], positions, base_paces, control_modes, loaded_paces)

    def compile_factory_actor(self, project_id):
        """Public compiler preserving native equipment and player Ask settings."""
        from factory_authoring.owner_items import OwnerItemStore
        from .factory_compiler import compile_character
        from .tabletop import ButtonStore, TabletopError
        try:
            saved = ButtonStore(self.userdata_root / 'tabletop_buttons').get(project_id)
        except (TabletopError, OSError, ValueError) as exc:
            # Unreadable saved Ask settings fall back to defaults; log it rather than drop them silently.
            import logging
            logging.getLogger(__name__).warning("Saved Ask settings for %s unreadable, using defaults: %s", project_id, exc)
            saved = {}
        return compile_character(self._factory_owner_sheet(project_id), actor_id=FACTORY_ACTOR_PREFIX + project_id,
            owner_items=OwnerItemStore(self.userdata_root / 'owner_items').items(project_id),
            powering=saved.get('powering') or {}, reaction_plan=saved.get('reactions') or None,
            granted_spheres=saved.get('granted_spheres') or None, summon_plan=saved.get('summons') or None,
            left_behind=saved.get('left_behind') or None,
            attuned=saved.get('attuned') if isinstance(saved.get('attuned'), list) else None)

    def journey_state(self, journey_id, viewer_id=None):
        return self.journeys.view(self.journeys.load(journey_id).state, viewer_id)

    def journey_admit(self, journey_id, revision, actor_id, kind, payload, *, gm=False, reason=''):
        """Typed, revision-bound owner scene facts; never action success."""
        return self.journeys.admit(journey_id, revision, actor_id, kind, payload, gm=gm, reason=reason)

    def journey_replay(self, journey_id):
        """Read-only mechanical replay of committed non-combat map commands."""
        return self.journeys.replay(journey_id)

    def journey_menu(self, journey_id, actor_id):
        return self.journeys.load(journey_id).menu(actor_id)

    def journey_act(self, journey_id, revision, actor_id, kind, payload=None):
        return self.journeys.act(journey_id, revision, actor_id, kind, payload)

    def world_fact(self, match_id, state_version, payload):
        """Trusted table-owner source input using a durable versioned policy.

        Reuses fact_consent_admission from 1be03085. Fighter candidates cannot
        select this binding or declare consent/mechanical outcomes through it.
        """
        from .fact_consent_admission import WORLD_KIND, prepare_world
        from .journey import require
        from .canonical import canonical_sha256
        from .gate2_runtime_models import ActionIntent
        session = self._load_session(match_id)
        engine = session.engine
        require(type(state_version) is int and state_version == engine.state.state_version,
                'Refresh the fight before recording a source declaration.')
        require(not (session.store.match_dir / 'Tabletop_Pending_Action.json').exists(),
                'Finish the pending player decision before recording source facts.')
        prepared = prepare_world(engine, payload)
        binding = {'kind': WORLD_KIND, 'payload': payload}
        identity = canonical_sha256(binding)
        intent = ActionIntent(intent_id=f'world-fact:{state_version}:{identity[:16]}', decision_id='world-fact:v1',
            candidate_id=identity, state_version=state_version, actor_id=engine.state.current_actor_id)
        session.submit_intent(intent, primary_decision_record=None, reaction_provider=None, settings_binding=binding)
        return {'status': 'COMMITTED', 'state_version': engine.state.state_version,
                'receipt_id': prepared.state['fact_consent_admission'][-1]['receipt_id']}

    def journey_world_fact(self, journey_id, revision, payload):
        """Record trusted table-owner world facts in the active journey."""
        return self.journeys.record_world_fact(journey_id, revision, payload)

    def journey_end_scene(self,journey_id,revision,reason):
        """Native GM/table-owner input ending a meaningful scene, with replayable reason."""
        return self.journeys.end_scene(journey_id,revision,reason)

    def journey_auto_step(self, journey_id, revision, actor_id, option_id=None):
        """One local choice from the complete personally visible journey menu."""
        from .journey import require
        session = self.journeys.load(journey_id)
        actor = session.state['actors'][actor_id]
        require(actor['control_mode'] == 'LOCAL_AUTO', 'This creature is under manual travel control.')
        from .ext import query as journey_query
        if any(result is True for result in journey_query('journey_auto_blocked', session, actor_id)):
            require(revision == session.state['revision'], 'The journey changed; refresh before acting.')
            return self.journeys.view(session.state, actor_id)
        options = session.menu(actor_id)['options']
        if option_id is not None:
            # An explicit menu selection is authoritative; automatic policy is
            # only for callers that ask the service to choose on their behalf.
            offered = next((row for row in options if row['id'] == option_id), None)
            require(offered is not None, 'Choose a currently offered journey option.')
        else:
            # Mapped basic Actions are chosen and settled by their documented
            # automatic policy. A declared Action is always settled first, but
            # a new Action never jumps ahead of an owned travel action or a
            # player-owned consent prompt: it replaces only plain movement.
            from .map_actions import KINDS as mapped_kinds, auto_choice as mapped_auto_choice
            settling = mapped_auto_choice(session, actor_id, allow_declare=False)
            if settling is not None:
                return self.journey_act(journey_id, revision, actor_id, settling['kind'], settling['payload'])
            # All participants are the admitted travel party; no enemy or
            # hidden creature knowledge is supplied by this scene consumer.
            ranks = {'carry_reply': 0, 'activate': 1, 'request_carry': 2, 'move': 3, 'set_down': 4}
            offered = min((row for row in options if row.get('auto_select', 1)
                           and row['kind'] not in mapped_kinds),
                          key=lambda row: (ranks.get(row['kind'], 5), row['id']), default=None)
            if offered is not None and offered['kind'] == 'move':
                choice = mapped_auto_choice(session, actor_id)
                if choice is not None:
                    return self.journey_act(journey_id, revision, actor_id, choice['kind'], choice['payload'])
            if offered is None and options:
                require(revision == session.state['revision'], 'The journey changed; refresh before acting.')
                return self.journeys.view(session.state, actor_id)
            require(offered is not None, 'This creature has no automatic journey action.')
        return self.journey_act(journey_id, revision, actor_id, offered['kind'], offered['payload'])

    def journey_start_combat(self, journey_id, revision, teams, *, maximum_rounds=20, positions=None):
        """Bind a real match to this journey and carry its paid resource balances.

        No travel benefit becomes combat Speed. Explicit setup squares allow
        players to place a carried party rather than silently relocating anyone.
        """
        from .journey import require
        from .canonical import canonical_sha256
        from copy import deepcopy
        with self.journeys.locked(journey_id):
            session = self.journeys.load(journey_id)
            require(session.state['phase'] == 'travel' and revision == session.state['revision'],
                    'The journey changed or already entered combat; refresh before creating a fight.')
            actors = session.state['actors']
            require(set(teams) == set(actors) and len(set(teams.values())) >= 2, 'Choose a combat team for every journey creature.')
            setup_positions = positions or {aid: a['position'] for aid, a in actors.items()}
            require(set(setup_positions) == set(actors), 'Choose a combat setup square for every creature.')
            if any(a.get('carried_by') for a in actors.values()):
                require(positions is not None, 'Choose separate combat setup squares for the carrier and carried creature.')
            bundles = []
            for aid, actor in actors.items():
                bundle = deepcopy(actor['bundle'])
                from . import ext
                bundle=ext.transform('journey_combat_bundle',bundle,session,aid)
                if not isinstance(bundle,dict):raise ValueError('journey_combat_bundle must return a bundle mapping')
                for pool in bundle['actor_template']['resources']:
                    pool['initial'] = actor['resources'].get(pool['resource_id'], pool['initial'])
                bundle['journey_setup'] = {'incapacitated': actor['incapacitated'], 'exhaustion': actor['exhaustion']}
                # Explicit opt-in consumers may transfer persistent selections;
                # timed travel benefits remain local to their journey clocks.
                from . import ext
                for supplied in ext.run_strict('journey_combat_setup', session, aid):
                    if not isinstance(supplied, dict) or set(supplied).intersection(bundle['journey_setup']):
                        raise ValueError('journey_combat_setup requires unique setup fields')
                    bundle['journey_setup'].update(supplied)
                if 'encounter_snapshot' in actor:
                    bundle['journey_setup']['encounter_snapshot'] = actor['encounter_snapshot']
                from .ext import transform as journey_transform
                bundle = journey_transform('journey_combat_bundle', bundle, session, aid)
                bundle.pop('bundle_sha256', None)
                bundle['bundle_sha256'] = canonical_sha256(bundle)
                bundles.append(bundle)
            # Validate lifecycle mutations before creating any persisted match.
            # The cold session is only saved after match creation succeeds.
            session.command(next(iter(actors)), 'enter_combat', {})
            result = self._finish_factory_match(
                bundles, list(actors), teams, setup_positions,
                session.state['battlefield'], list(actors), [],
                control_modes={aid: a['control_mode'] for aid, a in actors.items()},
                match_seed='JOURNEY-' + journey_id + '-' + str(revision),
                display_name='Journey encounter', maximum_rounds=maximum_rounds)
            session.state['match_id'] = result['match_id']
            for aid, actor in actors.items():
                actor['position'] = dict(setup_positions[aid])
                actor.pop('carried_by', None)
            session.state['revision'] += 1
            self.journeys.save(session)
            return result

    def journey_resume(self, journey_id, revision, *, effect_resolutions=None):
        """Resume after the bound fight ends, importing its verified balances.

        This general checkpoint keeps ordinary resource recovery in the combat
        rules that already own it; a Long Rest use never implies free Focus.
        Optional actor_id -> nonempty reason records a GM adjudication that all
        untransferable encounter effects on that creature have ended. It never
        heals, recovers resources or changes the immutable terminal fight.
        """
        from .journey import require
        from .ext.forged_exhaustion import level
        with self.journeys.locked(journey_id):
            session = self.journeys.load(journey_id)
            require(session.state['phase'] == 'combat' and session.state.get('match_id')
                    and revision == session.state['revision'], 'Refresh the journey bound to this fight.')
            fight = self._load_session(session.state['match_id'])
            require(fight.engine.state.terminal_result is not None, 'Finish the bound combat before resuming travel.')
            resolutions = {} if effect_resolutions is None else effect_resolutions
            require(isinstance(resolutions, dict) and set(resolutions) <= set(session.state['actors'])
                    and all(isinstance(reason, str) and reason.strip() for reason in resolutions.values()),
                    'Choose journey creatures and give a nonempty GM reason for each resolved encounter effect.')
            from .ext.journey_setup import encounter_snapshot, encounter_incapacitated
            from . import ext
            for aid, actor in session.state['actors'].items():
                creature = fight.engine.state.actors[aid]
                from .ext import transform
                snapshot_actor = transform('journey_snapshot_actor', creature, session, aid, fight.engine)
                actor['encounter_snapshot'] = encounter_snapshot(snapshot_actor, effects_ended=aid in resolutions)
                if aid in resolutions:
                    session.emit('ENCOUNTER_EFFECTS_RESOLVED', aid, reason=resolutions[aid],
                                 previous_state=creature.model_dump_json(),
                                 text=f"GM confirms {creature.display_name}’s timed conditions, modifiers, concentration, "
                                 "transformation and maximum-HP adjustments have ended. Permanent conditions and "
                                 "death-save progress remain; no healing or resource recovery is granted.")
                actor['resources'] = {key: int(value) for key, value in creature.resources.items()}
                actor['position'] = creature.position.model_dump(mode='json')
                actor['exhaustion'] = level(creature)
                actor['incapacitated'] = int(encounter_incapacitated(actor['encounter_snapshot']))
                from .ext import run_strict
                run_strict('journey_encounter_settled', session, aid, fight.engine, creature,
                           effects_ended=aid in resolutions)
            session.state['phase'] = 'travel'
            session.state['revision'] += 1
            session.emit('TRAVEL_RESUMED', next(iter(session.state['actors'])), match_id=session.state['match_id'])
            self.journeys.save(session)
            # Every journey response is the same projected view the GET serves:
            # never the raw session, which still holds replay genesis, the
            # command journal and each provider's private actor inputs.
            return self.journeys.view(session.state)

    def _error(
        self,
        code: str,
        message: str,
        *,
        subsystem: str,
        retry_safe: bool,
        recommended_action: str,
        match_id: str | None = None,
        actor_id: str | None = None,
        decision_id: str | None = None,
        details: dict[str, Any] | None = None,
        status_code: int = 400,
    ) -> CombatServiceError:
        return CombatServiceError(
            CombatServiceDiagnostic(
                code=code,
                message=message,
                subsystem=subsystem,
                retry_safe=retry_safe,
                recommended_action=recommended_action,
                match_id=match_id,
                actor_id=actor_id,
                decision_id=decision_id,
                details=details,
            ),
            status_code=status_code,
        )

    def _record_metric(self, operation: str, duration_us: int, *, threshold_ms: int) -> None:
        row = {
            "schema": "TianxiaFactoryCombatPerformanceRecord.v1",
            "recorded_at": _utcnow(),
            "operation": operation,
            "duration_us": int(duration_us),
            "duration_ms": max(1, round(int(duration_us) / 1000)),
            "threshold_ms": threshold_ms,
            "slow": int(duration_us) > threshold_ms * 1000,
        }
        self.performance_path.parent.mkdir(parents=True, exist_ok=True)
        with self.performance_path.open("ab") as handle:
            handle.write(canonical_bytes(row) + b"\n")

    @contextmanager
    def _timed(self, operation: str, *, threshold_ms: int):
        started = time.perf_counter()
        box: dict[str, int] = {}
        try:
            yield box
        finally:
            box["duration_us"] = max(1, round((time.perf_counter() - started) * 1_000_000))
            box["duration_ms"] = max(1, round(box["duration_us"] / 1000))
            self._record_metric(operation, box["duration_us"], threshold_ms=threshold_ms)

    def performance(self, limit: int = 50) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        if self.performance_path.is_file():
            for line in self.performance_path.read_text(encoding="utf-8").splitlines()[-limit:]:
                if line.strip():
                    rows.append(json.loads(line))
        slow = [row for row in rows if row.get("slow")]
        return {
            "schema": "TianxiaFactoryCombatPerformanceStatus.v1",
            "service_startup_ms": self.startup_ms,
            "recent": rows,
            "slow_operations": slow,
            "diagnostic": (
                CombatServiceDiagnostic(
                    code="COMBAT_OPERATION_SLOW",
                    message="One or more measured combat operations exceeded the practical local target.",
                    subsystem="combat.gate5.performance",
                    retry_safe=True,
                    recommended_action="Inspect the named operation for repeated loading, serialization, or filesystem work before adding infrastructure.",
                    details={"count": len(slow)},
                ).as_dict()
                if slow else None
            ),
        }

    def _load_visual_manifest(self) -> dict[str, Any]:
        document = json.loads(self.visual_manifest_path.read_text(encoding="utf-8"))
        if document.get("schema") != "TianxiaFactoryBattleVisualAssets.v1":
            raise ValueError("unsupported battle visual asset manifest schema")
        visual_root = self.visual_manifest_path.parent.resolve()
        for row in [*document.get("maps", []), *document.get("tokens", [])]:
            relative = str(row.get("file") or "")
            candidate = (visual_root / relative).resolve()
            if not relative or candidate.parent != visual_root or not candidate.is_file():
                raise ValueError(f"unsafe or missing battle visual asset: {relative}")
            expected = row.get("sha256")
            actual = sha256_file(candidate)
            if expected != actual:
                raise ValueError(f"battle visual asset identity mismatch: {relative}")
        return document

    def _load_definition_names(self) -> dict[str, str]:
        path = self.source_root / "combat_gate2" / "generated" / "Gate2_Executable_Mechanics_Lock.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        names: dict[str, str] = {}

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                stable_id = value.get("source_definition_id")
                display_name = value.get("display_name")
                if isinstance(stable_id, str) and isinstance(display_name, str):
                    names.setdefault(stable_id, display_name)
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for nested in value:
                    visit(nested)

        visit(document)
        return names

    @staticmethod
    def _image_type(data: bytes) -> tuple[str, str]:
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if data.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            return "image/webp", "webp"
        raise ValueError("Only PNG, JPEG, and WebP images are accepted.")

    @staticmethod
    def _image_dimensions(data: bytes, media_type: str) -> tuple[int, int]:
        """Read dimensions without decoding pixels or adding a runtime dependency."""

        if media_type == "image/png":
            if len(data) < 24 or data[12:16] != b"IHDR":
                raise ValueError("The PNG header is incomplete.")
            width, height = struct.unpack(">II", data[16:24])
        elif media_type == "image/jpeg":
            index = 2
            width = height = 0
            sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
            while index + 4 <= len(data):
                if data[index] != 0xFF:
                    index += 1
                    continue
                while index < len(data) and data[index] == 0xFF:
                    index += 1
                if index >= len(data):
                    break
                marker = data[index]
                index += 1
                if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
                    continue
                if index + 2 > len(data):
                    break
                segment_length = int.from_bytes(data[index:index + 2], "big")
                if segment_length < 2 or index + segment_length > len(data):
                    break
                if marker in sof_markers:
                    if segment_length < 7:
                        break
                    height = int.from_bytes(data[index + 3:index + 5], "big")
                    width = int.from_bytes(data[index + 5:index + 7], "big")
                    break
                index += segment_length
            if not width or not height:
                raise ValueError("The JPEG dimensions could not be read safely.")
        elif media_type == "image/webp":
            if len(data) < 30:
                raise ValueError("The WebP header is incomplete.")
            chunk = data[12:16]
            if chunk == b"VP8X":
                width = 1 + int.from_bytes(data[24:27], "little")
                height = 1 + int.from_bytes(data[27:30], "little")
            elif chunk == b"VP8L":
                if data[20] != 0x2F:
                    raise ValueError("The lossless WebP header is invalid.")
                bits = int.from_bytes(data[21:25], "little")
                width = (bits & 0x3FFF) + 1
                height = ((bits >> 14) & 0x3FFF) + 1
            elif chunk == b"VP8 ":
                if data[23:26] != b"\x9d\x01\x2a":
                    raise ValueError("The lossy WebP frame header is invalid.")
                width = int.from_bytes(data[26:28], "little") & 0x3FFF
                height = int.from_bytes(data[28:30], "little") & 0x3FFF
            else:
                raise ValueError("The WebP image uses an unsupported frame header.")
        else:
            raise ValueError("Unsupported image type.")
        if not (1 <= width <= 100_000 and 1 <= height <= 100_000):
            raise ValueError("The image dimensions are outside the accepted range.")
        return width, height

    def _default_visual_profile(self) -> dict[str, Any]:
        return {
            "schema": VISUAL_PROFILE_SCHEMA,
            "version": "1.0.0",
            "background": None,
            "tokens": {},
            "updated_at": None,
        }

    def _read_visual_profile(self) -> dict[str, Any]:
        if not self.visual_profile_path.is_file():
            return self._default_visual_profile()
        try:
            document = json.loads(self.visual_profile_path.read_text(encoding="utf-8"))
            if document.get("schema") != VISUAL_PROFILE_SCHEMA:
                raise ValueError("visual profile schema mismatch")
            tokens = document.get("tokens")
            if not isinstance(tokens, dict):
                raise ValueError("visual profile token assignments are invalid")
            return document
        except Exception as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The saved combat visual profile is invalid.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Restore or remove only Combat/VisualProfile/Profile.json; saved matches and mechanics remain separate.",
                details={"reason": str(exc)},
                status_code=409,
            ) from exc

    def _write_visual_profile(self, document: dict[str, Any]) -> None:
        document = {**document, "schema": VISUAL_PROFILE_SCHEMA, "version": "1.0.0", "updated_at": _utcnow()}
        _atomic_json(self.visual_profile_path, document)

    def _custom_visual_row(self, assignment: dict[str, Any], *, actor_id: str | None = None) -> dict[str, Any]:
        stored_name = str(assignment["stored_name"])
        width_px = assignment.get("width_px")
        height_px = assignment.get("height_px")
        if not width_px or not height_px:
            # Backward-compatible read of a pre-E3 visual profile. This does not
            # rewrite owner data and does not upgrade decorative status to exact.
            try:
                source = self.visual_profile_asset_path(stored_name)
                raw = source.read_bytes()
                width_px, height_px = self._image_dimensions(raw, str(assignment["media_type"]))
            except (OSError, ValueError, KeyError):
                width_px = height_px = None
        row = {
            "asset_id": assignment["asset_id"],
            "file": stored_name,
            "public_url": f"/api/combat/setup-visuals/assets/{stored_name}",
            "sha256": assignment["sha256"],
            "media_type": assignment["media_type"],
            "source": "owner_upload",
            "original_filename": assignment.get("original_filename"),
            "storage_file": stored_name,
            "width_px": width_px,
            "height_px": height_px,
        }
        if actor_id is None:
            calibration = assignment.get("calibration")
            if isinstance(calibration, dict):
                row["calibration"] = json.loads(json.dumps(calibration))
            else:
                row["calibration"] = {
                    "schema": "TianxiaBattleMapCalibration.v1",
                    "fit_mode": "cover",
                    "position_x_percent": 50,
                    "position_y_percent": 50,
                    "scale_percent": 100,
                    "note": "Legacy owner-selected decorative background. Battlefield dimensions remain mechanically authoritative.",
                }
        else:
            row["stable_actor_ids"] = [actor_id]
        return row

    def _effective_visual_manifest(self, *, include_storage: bool = False) -> dict[str, Any]:
        document = json.loads(json.dumps(self._visual_manifest))
        for row in [*document.get("maps", []), *document.get("tokens", [])]:
            row["source"] = "built_in"
        profile = self._read_visual_profile()
        background = profile.get("background")
        if isinstance(background, dict):
            custom_map = self._custom_visual_row(background)
            document["maps"] = [custom_map, *document.get("maps", [])]
            document["default_map_asset_id"] = custom_map["asset_id"]
        custom_tokens = []
        assigned_ids = set()
        for actor_id, assignment in sorted(profile.get("tokens", {}).items()):
            if isinstance(assignment, dict):
                custom_tokens.append(self._custom_visual_row(assignment, actor_id=actor_id))
                assigned_ids.add(actor_id)
        built_in_tokens = [
            row for row in document.get("tokens", [])
            if not assigned_ids.intersection(row.get("stable_actor_ids") or [])
        ]
        document["tokens"] = [*custom_tokens, *built_in_tokens]
        document["profile"] = {
            "schema": VISUAL_PROFILE_SCHEMA,
            "updated_at": profile.get("updated_at"),
            "custom_background": isinstance(background, dict),
            "custom_token_actor_ids": sorted(assigned_ids),
        }
        if not include_storage:
            for row in [*document.get("maps", []), *document.get("tokens", [])]:
                row.pop("storage_file", None)
        return document

    def visual_assets(self) -> dict[str, Any]:
        from .roster_selection import retired
        document = self._effective_visual_manifest()
        document['tokens'] = [row for row in document.get('tokens', [])
                              if not any(retired(aid) for aid in row.get('stable_actor_ids', []))]
        document['profile']['custom_token_actor_ids'] = [aid for aid in document['profile']['custom_token_actor_ids'] if not retired(aid)]
        return document

    def save_visual_upload(
        self,
        *,
        kind: str,
        actor_id: str | None,
        original_filename: str,
        declared_media_type: str,
        data_base64: str,
        calibration_mode: str = "COVER_DECORATIVE",
        playable_rect_pixels: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        if kind not in {"background", "token"}:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The visual upload kind is invalid.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Upload a battlefield background or a fighter token.",
            )
        valid_actor_ids = {
            row["runtime_entity_id"]
            for row in self.catalog()["projections"]
            if row.get("primary_combatant")
        }
        if kind == "token" and actor_id not in valid_actor_ids:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The token was not assigned to a current combat-ready fighter.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Choose one of the fighter cards shown in Combat Setup.",
                details={"valid_actor_ids": sorted(valid_actor_ids)},
            )
        if kind == "background":
            actor_id = None
        try:
            encoded = str(data_base64 or "").strip()
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The uploaded image data is not valid base64.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Choose the image file again and retry.",
                status_code=422,
            ) from exc
        if not raw or len(raw) > MAX_CUSTOM_VISUAL_BYTES:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "Combat visual images must be between 1 byte and 12 MiB.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Use a PNG, JPEG, or WebP image no larger than 12 MiB.",
                details={"bytes": len(raw), "maximum_bytes": MAX_CUSTOM_VISUAL_BYTES},
                status_code=422,
            )
        try:
            media_type, extension = self._image_type(raw)
        except ValueError as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                str(exc),
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Use a PNG, JPEG, or WebP file.",
                status_code=422,
            ) from exc
        if declared_media_type and declared_media_type.lower() not in {media_type, "image/jpg" if media_type == "image/jpeg" else media_type}:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The image content does not match its declared media type.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Re-export the image as PNG, JPEG, or WebP and upload it again.",
                details={"declared": declared_media_type, "detected": media_type},
                status_code=422,
            )
        try:
            width_px, height_px = self._image_dimensions(raw, media_type)
        except ValueError as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                str(exc),
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Re-export the image as a standard PNG, JPEG, or WebP file.",
                status_code=422,
            ) from exc
        digest = hashlib.sha256(raw).hexdigest()
        stored_name = f"{digest}.{extension}"
        assignment = {
            "asset_id": f"{kind}:owner:{(actor_id or 'battlefield')}:{digest[:16]}",
            "stored_name": stored_name,
            "sha256": digest,
            "media_type": media_type,
            "original_filename": Path(original_filename or stored_name).name[:240],
            "width_px": width_px,
            "height_px": height_px,
        }
        if kind == "background":
            if calibration_mode not in {"EXACT_PLAYABLE_RECT", "COVER_DECORATIVE", "CONTAIN_DECORATIVE"}:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The requested battlefield-map calibration mode is unsupported.",
                    subsystem="combat.gate5.visual_profile",
                    retry_safe=True,
                    recommended_action="Choose Exact gridless map, Decorative cover, or Decorative contain.",
                    status_code=422,
                )
            rect = dict(playable_rect_pixels or {"x": 0, "y": 0, "width": width_px, "height": height_px})
            try:
                rect = {key: int(rect[key]) for key in ("x", "y", "width", "height")}
            except (KeyError, TypeError, ValueError) as exc:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The battlefield playable rectangle is incomplete.",
                    subsystem="combat.gate5.visual_profile",
                    retry_safe=True,
                    recommended_action="Use the full image or supply x, y, width, and height in source pixels.",
                    status_code=422,
                ) from exc
            if rect["x"] < 0 or rect["y"] < 0 or rect["width"] < 1 or rect["height"] < 1 or rect["x"] + rect["width"] > width_px or rect["y"] + rect["height"] > height_px:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The battlefield playable rectangle extends outside the uploaded image.",
                    subsystem="combat.gate5.visual_profile",
                    retry_safe=True,
                    recommended_action="Use a playable rectangle fully contained by the source image.",
                    status_code=422,
                )
            battlefield = self._catalog_cache["battlefields"][0]
            grid_width = int(battlefield["width_squares"])
            grid_height = int(battlefield["height_squares"])
            if calibration_mode == "EXACT_PLAYABLE_RECT":
                lhs = rect["width"] * grid_height
                rhs = rect["height"] * grid_width
                if abs(lhs - rhs) > max(lhs, rhs) * 0.001:
                    raise self._error(
                        "COMBAT_UI_DATA_INVALID",
                        "The exact gridless-map playable rectangle does not match the battlefield aspect ratio.",
                        subsystem="combat.gate5.visual_profile",
                        retry_safe=True,
                        recommended_action=f"Crop or export the playable map at the {grid_width}:{grid_height} battlefield ratio, then upload it as Exact.",
                        details={
                            "battlefield_ratio": f"{grid_width}:{grid_height}",
                            "playable_rect": rect,
                            "source_dimensions": {"width": width_px, "height": height_px},
                        },
                        status_code=422,
                    )
            assignment["calibration"] = {
                "schema": "TianxiaBattleMapCalibration.v2",
                "authority": "PRESENTATION_ONLY",
                "grid_width_squares": grid_width,
                "grid_height_squares": grid_height,
                "source_pixel_width": width_px,
                "source_pixel_height": height_px,
                "playable_rect_pixels": rect,
                "fit_mode": calibration_mode,
                "position_x_percent": 50,
                "position_y_percent": 50,
                "asset_sha256": digest,
            }
        self.visual_profile_assets_root.mkdir(parents=True, exist_ok=True)
        destination = self.visual_profile_assets_root / stored_name
        if not destination.exists():
            temporary = destination.with_name(destination.name + f".tmp.{os.getpid()}.{secrets.token_hex(4)}")
            with temporary.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        elif sha256_file(destination) != digest:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "A saved visual asset failed its content identity check.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Inspect only the Combat/VisualProfile asset directory before retrying.",
                status_code=409,
            )
        profile = self._read_visual_profile()
        if kind == "background":
            profile["background"] = assignment
        else:
            tokens = dict(profile.get("tokens") or {})
            tokens[str(actor_id)] = assignment
            profile["tokens"] = tokens
        self._write_visual_profile(profile)
        return self._effective_visual_manifest()

    def reset_visual_upload(self, *, kind: str, actor_id: str | None = None) -> dict[str, Any]:
        profile = self._read_visual_profile()
        if kind == "background":
            profile["background"] = None
        elif kind == "token":
            tokens = dict(profile.get("tokens") or {})
            tokens.pop(str(actor_id or ""), None)
            profile["tokens"] = tokens
        else:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The visual reset kind is invalid.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=True,
                recommended_action="Reset the battlefield background or one fighter token.",
            )
        self._write_visual_profile(profile)
        return self._effective_visual_manifest()

    def visual_profile_asset_path(self, stored_name: str) -> Path:
        if not VISUAL_ASSET_FILE_RE.fullmatch(stored_name):
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested combat visual asset is unavailable.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Use the image URL returned by the combat visual profile.",
                status_code=404,
            )
        path = self.visual_profile_assets_root / stored_name
        if not path.is_file() or path.parent.resolve() != self.visual_profile_assets_root.resolve():
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested combat visual asset is unavailable.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Upload the image again from Combat Setup.",
                status_code=404,
            )
        return path

    def _snapshot_match_visuals(self, match_id: str) -> dict[str, Any]:
        manifest = self._effective_visual_manifest(include_storage=True)
        match_dir = self._match_dir(match_id)
        visual_dir = match_dir / "VisualAssets"

        def snapshot_row(row: dict[str, Any], *, prefix: str) -> dict[str, Any]:
            result = json.loads(json.dumps(row))
            stored_name = result.pop("storage_file", None)
            if result.get("source") != "owner_upload" or not stored_name:
                return result
            source = self.visual_profile_asset_path(stored_name)
            visual_dir.mkdir(parents=True, exist_ok=True)
            destination_name = f"{prefix}_{stored_name}"
            destination = visual_dir / destination_name
            if not destination.exists():
                shutil.copyfile(source, destination)
            if sha256_file(destination) != result["sha256"]:
                raise ValueError(f"match visual snapshot identity mismatch: {destination_name}")
            result["file"] = destination_name
            result["public_url"] = f"/api/combat/matches/{match_id}/visual-assets/{destination_name}"
            result["source"] = "match_snapshot"
            return result

        maps = manifest.get("maps") or []
        selected_map = next(
            (row for row in maps if row.get("asset_id") == manifest.get("default_map_asset_id")),
            maps[0] if maps else None,
        )
        map_row = snapshot_row(selected_map, prefix="background") if selected_map else None
        tokens = {}
        for projection in self._catalog_cache["projections"]:
            if not projection.get("primary_combatant"):
                continue
            actor_id = projection["runtime_entity_id"]
            row = next((item for item in manifest.get("tokens", []) if actor_id in (item.get("stable_actor_ids") or [])), None)
            if row:
                tokens[actor_id] = snapshot_row(row, prefix=f"token_{actor_id}")
        return {
            "schema": MATCH_VISUAL_SCHEMA,
            "map": map_row,
            "tokens": tokens,
            "profile_updated_at": manifest.get("profile", {}).get("updated_at"),
            "mechanical_authority": False,
        }

    def match_visual_asset_path(self, match_id: str, filename: str) -> Path:
        if not re.fullmatch(r"(?:background|token_[A-Za-z0-9_.-]+)_[a-f0-9]{64}\.(?:png|jpg|webp)", filename):
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested match visual asset is unavailable.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Use the visual URL returned with the match.",
                match_id=match_id,
                status_code=404,
            )
        root = self._match_dir(match_id) / "VisualAssets"
        path = root / filename
        if not path.is_file() or path.parent.resolve() != root.resolve():
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested match visual asset is unavailable.",
                subsystem="combat.gate5.visual_profile",
                retry_safe=False,
                recommended_action="Use the visual URL returned with the match.",
                match_id=match_id,
                status_code=404,
            )
        return path

    # ------------------------------------------------------------------
    # Catalog and readiness
    # ------------------------------------------------------------------
    def _load_catalog(self) -> dict[str, Any]:
        with self._timed("catalog_load", threshold_ms=2000):
            battlefield = json.loads((self.source_root / "combat_gate1/generated/Battlefield.json").read_text(encoding="utf-8"))
            encounter = json.loads((self.source_root / "combat_gate1/generated/Encounter.json").read_text(encoding="utf-8"))
            team_by_registry_id: dict[str, dict[str, Any]] = {}
            teams = []
            for index, team in enumerate(encounter.get("teams") or []):
                team_id = str(team["team_id"])
                display_name = team_id.split(":", 1)[-1].replace("_", " ").title()
                team_row = {
                    "team_id": team_id,
                    "display_name": display_name,
                    "team_index": index,
                    "participant_ids": list(team.get("participant_ids") or []),
                }
                teams.append(team_row)
                for registry_id in team_row["participant_ids"]:
                    team_by_registry_id[registry_id] = team_row
            projections = []
            for path in sorted((self.source_root / "combat_gate1/generated/projections").glob("*.json")):
                wrapper = json.loads(path.read_text(encoding="utf-8"))
                projection = wrapper["projection"]
                registry_id = f"character_mapping:{projection['character_id']}"
                team = team_by_registry_id.get(registry_id) or {"team_id": "team:unassigned", "display_name": "Unassigned", "team_index": 99}
                projections.append({
                    "registry_id": registry_id,
                    "runtime_entity_id": projection["character_id"],
                    "display_name": projection["display_name"],
                    "cultivation_level": projection.get("cultivation_level"),
                    "realm": projection.get("realm"),
                    "projection_sha256": wrapper["projection_sha256"],
                    "readiness_status": "COMBAT_READY",
                    "readiness_reason": "Exact accepted Gate 1/Gate 2 runtime projection.",
                    "primary_combatant": True,
                    "team_id": team["team_id"],
                    "team_display_name": team["display_name"],
                    "team_index": team["team_index"],
                    "character_sheet_identity": registry_id,
                })
            projections.append({
                "registry_id": "creature:bai_cui",
                "runtime_entity_id": "bai_cui",
                "display_name": "Cui",
                "readiness_status": "COMBAT_READY",
                "readiness_reason": "First-class accepted companion controlled through Bai Meizhen's encounter projection.",
                "primary_combatant": False,
                "owner_registry_id": "character_mapping:bai_meizhen_early_outer_sect_cl5",
                "team_id": team_by_registry_id.get("character_mapping:bai_meizhen_early_outer_sect_cl5", {}).get("team_id", "team:unassigned"),
                "team_display_name": team_by_registry_id.get("character_mapping:bai_meizhen_early_outer_sect_cl5", {}).get("display_name", "Unassigned"),
                "team_index": team_by_registry_id.get("character_mapping:bai_meizhen_early_outer_sect_cl5", {}).get("team_index", 99),
            })
            return {
                "schema": "TianxiaFactoryCombatCatalog.v1",
                "readiness_statuses": list(READINESS_STATUSES),
                "projections": projections,
                "battlefields": [{**battlefield, "readiness_status": "COMBAT_READY"}],
                "encounters": [{**encounter, "readiness_status": "COMBAT_READY"}],
                "teams": teams,
                "supported_control_modes": list(CONTROL_MODES),
                "known_limitations": [
                    "Only the accepted CL5 2v2 encounter and Sect Training Court are executable in Gate 5.",
                    "Arbitrary Factory character compilation, roster construction, additional battlefields, tournaments, and direct AI provider transport are deferred.",
                    "The local controller is deterministic one-step heuristic control and does not search future turns.",
                ],
            }

    def status(self) -> dict[str, Any]:
        return {
            "schema": "TianxiaFactoryCombatServiceStatus.v1",
            "available": True,
            "service": "CombatService",
            "integration_gate": 5,
            "mechanical_authority": "GATE2_ENGINE",
            "persistence_authority": "GATE3_JOURNAL_AND_REDUCER",
            "controller_authority": "GATE4_CONTROLLER",
            "matches_directory": str(self.matches_root),
            "catalog_ready": bool(self._catalog_cache["encounters"]),
            "combat_ready_projection_count": sum(1 for p in self.catalog()["projections"] if p["readiness_status"] == "COMBAT_READY"),
            "api_auto": self.ai_provider.status() if self.ai_provider is not None else {"ready": False, "provider_id": None},
            "diagnostic_catalog": DIAGNOSTIC_CATALOG,
            "performance": self.performance(limit=20),
        }

    def _portable_catalog_rows(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, Any]]]:
        inventory = self.combatant_library.inventory()
        projections: list[dict[str, Any]] = []
        authority: dict[str, dict[str, Any]] = {}
        seen_runtime_ids: dict[str, str] = {}
        for entry in inventory.accepted_candidates:
            actor_id = runtime_actor_id(entry.character_project_id, entry.source_package_sha256)
            prior = seen_runtime_ids.get(actor_id)
            if prior is not None and prior != entry.source_package_sha256:
                raise self._error(
                    "C3D_RUNTIME_ACTOR_ID_COLLISION",
                    "Two different installed packages claim the same portable combat actor identity.",
                    subsystem="combat.c3d.catalog", retry_safe=False,
                    recommended_action="Remove the conflicting installed package and refresh the combat catalog.",
                    details={"runtime_actor_id": actor_id, "first": prior, "second": entry.source_package_sha256},
                    status_code=409,
                )
            seen_runtime_ids[actor_id] = entry.source_package_sha256
            projections.append({
                "registry_id": entry.entry_id,
                "runtime_entity_id": actor_id,
                "display_name": entry.display_name,
                "cultivation_level": None,
                "realm": None,
                "projection_sha256": entry.actor_template_commitment_sha256,
                "team_id": "team:unassigned",
                "team_display_name": "Owner Assigned",
                "team_index": 99,
                "primary_combatant": True,
                "owner_id": entry.character_project_id,
                "character_sheet_identity": entry.combat_sheet_id,
                "readiness_status": "COMBAT_READY",
                "owner_status": "Combat Ready",
                "installed_character": True,
                "candidate_entry_id": entry.entry_id,
                "source_package_sha256": entry.source_package_sha256,
                "project_id": entry.character_project_id,
                "project_revision": entry.project_revision,
                "event_head_hash": entry.event_head_hash,
                "replay_state_hash": entry.replay_state_hash,
                "content_lock_hash": entry.content_lock_hash,
                "combat_sheet_commitment_sha256": entry.combat_sheet_commitment_sha256,
                "mechanics_lock_sha256": entry.mechanics_lock_sha256,
                "primitive_registry_sha256": entry.primitive_registry_sha256,
                "runtime_adapter_id": entry.runtime_adapter_id,
                "runtime_adapter_version": entry.runtime_adapter_version,
                "runtime_engine_version": entry.runtime_engine_version,
                "actor_template_commitment_sha256": entry.actor_template_commitment_sha256,
            })
            authority[actor_id] = {
                "resources": {
                    "qi": {"resource_id": "resource:core.qi", "current": None, "maximum": entry.resource_maxima["resource:core.qi"], "required": True},
                    "martial_focus": {"resource_id": "resource:core.martial_focus", "current": None, "maximum": entry.resource_maxima["resource:core.martial_focus"], "required": True},
                },
                "placement": {"x": 2, "y": 12},
                "footprint": {**entry.footprint_contract, "editable": False},
                "token_asset_id": entry.combat_sheet_id,
                "supported_control_modes": list(CONTROL_MODES),
                "installed_character": True,
                "candidate_entry_id": entry.entry_id,
                "source_package_sha256": entry.source_package_sha256,
                "project_id": entry.character_project_id,
            }
        blocks = [row.model_dump(mode="json") for row in inventory.blocked_candidates]
        return projections, authority, blocks

    def catalog(self) -> dict[str, Any]:
        with self._timed("catalog_request", threshold_ms=2000):
            from .roster_selection import public_catalog, retired
            payload = public_catalog(json.loads(json.dumps(self._catalog_cache)))
            battlefield = payload["battlefields"][0]
            authority: dict[str, dict[str, Any]] = {}
            for actor_id, template in ACTORS.items():
                if not template.primary_combatant or retired(actor_id):
                    continue
                definition, _ = resolve_actor_footprint(actor_id)
                resources = {}
                for resource in template.resources:
                    for owner_name in ("stamina", "qi", "resonance"):
                        if resource.resource_id.endswith(f".{owner_name}"):
                            resources[owner_name] = {"resource_id": resource.resource_id, "current": resource.initial, "maximum": resource.maximum}
                projection = next(row for row in payload["projections"] if row["runtime_entity_id"] == actor_id)
                projection["installed_character"] = False
                projection["owner_status"] = "Combat Ready"
                authority[actor_id] = {
                    "resources": resources,
                    "placement": battlefield["starting_positions"][actor_id],
                    "footprint": {"footprint_id": definition.footprint_id, "width": definition.width_cells, "height": definition.height_cells, "editable": False},
                    "token_asset_id": projection["character_sheet_identity"],
                    "supported_control_modes": list(CONTROL_MODES),
                    "installed_character": False,
                }
            portable_rows, portable_authority, blocks = self._portable_catalog_rows()
            existing_ids = {row["runtime_entity_id"] for row in payload["projections"]}
            for row in portable_rows:
                if row["runtime_entity_id"] in existing_ids:
                    raise self._error(
                        "C3D_RUNTIME_ACTOR_ID_COLLISION",
                        "An installed Character collides with an existing combat actor identity.",
                        subsystem="combat.c3d.catalog", retry_safe=False,
                        recommended_action="Remove the conflicting installed package; built-in actor identities cannot be replaced.",
                        details={"runtime_actor_id": row["runtime_entity_id"]}, status_code=409,
                    )
                payload["projections"].append(row)
                existing_ids.add(row["runtime_entity_id"])
            payload["projections"] = sorted(payload["projections"], key=lambda row: row["runtime_entity_id"])
            authority.update(portable_authority)
            payload["c3c_p1_setup_authority"] = authority
            payload["c3c_p1_scope"] = "DYNAMIC_COMBAT_READY_TWO_TEAM_ROSTER"
            payload["installed_candidate_blocks"] = blocks
            payload["portable_candidate_count"] = len(portable_rows)
            return payload

    # ------------------------------------------------------------------
    # Integration metadata
    # ------------------------------------------------------------------
    def _match_dir(self, match_id: str) -> Path:
        if not MATCH_ID_RE.fullmatch(match_id):
            raise self._error(
                "COMBAT_MATCH_NOT_FOUND",
                "The requested combat match identifier is invalid or unavailable.",
                subsystem="combat.gate5.storage",
                retry_safe=False,
                recommended_action="Select a match returned by the combat match list.",
                match_id=match_id,
                status_code=404,
            )
        return Gate3MatchStore(self.userdata_root, match_id).match_dir

    def _metadata_path(self, match_id: str) -> Path:
        return self._match_dir(match_id) / "FactoryIntegration.json"

    def _write_metadata(self, match_id: str, metadata: dict[str, Any]) -> None:
        metadata = {**metadata, "updated_at": _utcnow()}
        _atomic_json(self._metadata_path(match_id), metadata)

    def _read_metadata(self, match_id: str, session: Gate4PersistentSession | None = None) -> dict[str, Any]:
        path = self._metadata_path(match_id)
        if path.exists() or path.is_symlink():
            try:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("saved integration metadata is not a regular file")
                doc = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(doc, dict) or doc.get("schema") != INTEGRATION_SCHEMA or doc.get("match_id") != match_id:
                    raise ValueError("metadata identity mismatch")
                modes = doc.get("participant_control_modes")
                if not isinstance(modes, dict) or any(not isinstance(key, str) or value not in CONTROL_MODES for key, value in modes.items()):
                    raise ValueError("saved participant control modes are invalid")
                return doc
            except Exception as exc:
                raise self._error(
                    UNSUPPORTED_CODE,
                    UNSUPPORTED_MESSAGE,
                    subsystem="combat.gate5.metadata",
                    retry_safe=False,
                    recommended_action="Start a new fight. You can delete this saved fight from the table.",
                    match_id=match_id,
                    details={"reason": str(exc)},
                    status_code=409,
                ) from exc
        if session is None:
            session = self._load_session(match_id)
        primary = [actor for actor in session.engine.state.actors.values() if actor.primary_combatant]
        doc = {
            "schema": INTEGRATION_SCHEMA,
            "integration_schema_version": "1.0.0",
            "match_id": match_id,
            "display_name": self._catalog_cache["encounters"][0]["display_name"],
            "encounter_id": self._catalog_cache["encounters"][0]["stable_id"],
            "battlefield_id": self._catalog_cache["battlefields"][0]["stable_id"],
            "participant_control_modes": {actor.entity_id: "MANUAL" for actor in primary},
            "paused": False,
            "local_auto_running": False,
            "ui_preferences": {},
            "visual_assets": {
                "schema": MATCH_VISUAL_SCHEMA,
                "map": next((row for row in self._effective_visual_manifest().get("maps", []) if row.get("asset_id") == self._effective_visual_manifest().get("default_map_asset_id")), None),
                "tokens": {
                    row["runtime_entity_id"]: next((item for item in self._effective_visual_manifest().get("tokens", []) if row["runtime_entity_id"] in (item.get("stable_actor_ids") or [])), None)
                    for row in self._catalog_cache["projections"] if row.get("primary_combatant")
                },
                "mechanical_authority": False,
            },
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        self._write_metadata(match_id, doc)
        return doc

    def _dao_policy_for_actor(self, actor_id: str) -> dict[str, Any] | None:
        """The combat AI policy for an installed Factory character, derived from its Dao.

        Owner 2026-09-24: the Daos of a character's Spheres decide how its
        built-in combat AI fights.  The Spheres and Talents come from the owner
        character sheet inside the installed portable package.
        """
        if actor_id in self._dao_policies:
            return self._dao_policies[actor_id]
        policy = None
        try:
            from factory_authoring.sphere_dao import character_dao, controller_policy, sheet_sphere_talents

            if actor_id.startswith(FACTORY_ACTOR_PREFIX):
                from .factory_compiler import primary_resource

                owner_sheet = self._factory_owner_sheet(actor_id[len(FACTORY_ACTOR_PREFIX):])
                dao = character_dao(sheet_sphere_talents(owner_sheet))
                policy = controller_policy(dao, actor_id, primary_resource=primary_resource(owner_sheet)) if dao else None
                if policy is not None:
                    from .ai_policy import enrich_policy
                    package = self.combatant_library.install_root / actor_id[len(FACTORY_ACTOR_PREFIX):] / 'current.zip'
                    policy = enrich_policy(policy, owner_sheet, package)
                self._dao_policies[actor_id] = policy
                return policy
            for entry in self.combatant_library.inventory().accepted_candidates:
                if runtime_actor_id(entry.character_project_id, entry.source_package_sha256) != actor_id:
                    continue
                with zipfile.ZipFile(self.combatant_library._package_for_entry(entry)) as archive:
                    owner_sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
                dao = character_dao(sheet_sphere_talents(owner_sheet))
                policy = controller_policy(dao, actor_id) if dao else None
                if policy is not None:
                    from .ai_policy import enrich_policy
                    policy = enrich_policy(policy, owner_sheet, self.combatant_library._package_for_entry(entry))
                break
        except Exception:
            policy = None
        self._dao_policies[actor_id] = policy
        return policy

    def _mode_for_actor(self, metadata: dict[str, Any], session: Gate4PersistentSession, actor_id: str) -> str:
        actor = session.engine.state.actors[actor_id]
        # Retain initiative slots and their recorded start/end events. A
        # defeated fighter needs only the automatic End Turn decision,
        # regardless of who normally controls it. Dying/Stable creatures remain
        # active: their own turns still carry death saves and printed choices.
        if not actor.active:
            return "LOCAL_AUTO"
        owner = actor.owner_id if not actor.primary_combatant else None
        mode = metadata["participant_control_modes"].get(owner or actor_id, "MANUAL")
        if mode not in CONTROL_MODES:
            raise self._error(
                "COMBAT_CONTROL_MODE_INVALID",
                "A participant has an unsupported combat control mode.",
                subsystem="combat.gate5.metadata",
                retry_safe=True,
                recommended_action="Choose Manual, Suggested, Local AI, API AI, or Manual AI Bridge.",
                match_id=session.match_id,
                actor_id=actor_id,
                details={"mode": mode},
                status_code=409,
            )
        from .turn_decisions import passes_without_decision
        if passes_without_decision(session.engine, actor_id):
            return "LOCAL_AUTO"  # one forced End Turn; never ask a player or API pilot for an empty decision
        return mode

    def _metadata_readonly(self, match_id: str, genesis_state: dict[str, Any]) -> dict[str, Any]:
        path = self._metadata_path(match_id)
        if path.is_file():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if doc.get("schema") != INTEGRATION_SCHEMA or doc.get("match_id") != match_id:
                    raise ValueError("metadata identity mismatch")
                return doc
            except Exception as exc:
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The match integration metadata is invalid.",
                    subsystem="combat.gate5.metadata",
                    retry_safe=False,
                    recommended_action="Restore or regenerate only FactoryIntegration.json; the mechanical journal remains authoritative.",
                    match_id=match_id,
                    details={"reason": str(exc)},
                    status_code=409,
                ) from exc
        actors = genesis_state.get("actors") or {}
        actor_rows = actors.values() if isinstance(actors, dict) else actors
        primary_ids = [row["entity_id"] for row in actor_rows if row.get("primary_combatant")]
        return {
            "schema": INTEGRATION_SCHEMA,
            "integration_schema_version": "1.0.0",
            "match_id": match_id,
            "display_name": self._catalog_cache["encounters"][0]["display_name"],
            "encounter_id": self._catalog_cache["encounters"][0]["stable_id"],
            "battlefield_id": self._catalog_cache["battlefields"][0]["stable_id"],
            "participant_control_modes": {actor_id: "MANUAL" for actor_id in primary_ids},
            "paused": False,
            "local_auto_running": False,
            "ui_preferences": {},
            "visual_assets": {
                "schema": MATCH_VISUAL_SCHEMA,
                "map": next((row for row in self._effective_visual_manifest().get("maps", []) if row.get("asset_id") == self._effective_visual_manifest().get("default_map_asset_id")), None),
                "tokens": {
                    row["runtime_entity_id"]: next((item for item in self._effective_visual_manifest().get("tokens", []) if row["runtime_entity_id"] in (item.get("stable_actor_ids") or [])), None)
                    for row in self._catalog_cache["projections"] if row.get("primary_combatant")
                },
                "mechanical_authority": False,
            },
            "read_only_default": True,
        }

    @staticmethod
    def _history_state_view(state: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        actors_source = state.get("actors") or {}
        actor_rows = list(actors_source.values()) if isinstance(actors_source, dict) else list(actors_source)
        initiative = list(state.get("initiative_order") or [])
        initiative_index = {actor_id: index for index, actor_id in enumerate(initiative)}
        actors = []
        for actor in sorted(actor_rows, key=lambda row: (initiative_index.get(row["entity_id"], len(initiative_index)), row["entity_id"])):
            owner = actor.get("owner_id") if not actor.get("primary_combatant") else None
            mode = metadata.get("participant_control_modes", {}).get(owner or actor["entity_id"], "MANUAL")
            conditions = actor.get("conditions") or {}
            actors.append({
                **actor,
                "control_mode": mode if mode in CONTROL_MODES else "MANUAL",
                "condition_ids": sorted(
                    row.get("condition_id", key) for key, row in conditions.items()
                ) if isinstance(conditions, dict) else [],
            })
        zones_source = state.get("zones") or {}
        zones = list(zones_source.values()) if isinstance(zones_source, dict) else list(zones_source)
        return {
            "match_seed": state.get("match_seed"),
            "round_number": state.get("round_number"),
            "current_slot_index": state.get("current_slot_index"),
            "current_actor_id": state.get("current_actor_id"),
            "initiative_order": initiative,
            "state_version": state.get("state_version"),
            "event_sequence": state.get("event_sequence"),
            "roll_counter": state.get("roll_counter"),
            "terminal_result": state.get("terminal_result"),
            "actors": actors,
            "zones": sorted(zones, key=lambda row: row.get("zone_id", "")),
            "pending_resolution": state.get("pending_resolution"),
        }

    def history(self, match_id: str) -> dict[str, Any]:
        try:
            history = self.persistence.history_boundaries(match_id)
        except CombatServiceError:
            raise
        except Exception as exc:
            if not self._match_dir(match_id).is_dir():
                raise self._error(
                    "COMBAT_MATCH_NOT_FOUND",
                    "The requested persistent match does not exist or cannot be addressed safely.",
                    subsystem="combat.gate5.history",
                    retry_safe=False,
                    recommended_action="Select a match returned by the combat match list.",
                    match_id=match_id,
                    status_code=404,
                ) from exc
            diagnostic = getattr(exc, "diagnostic", None)
            raise self._error(
                "COMBAT_CONTENT_NOT_READY",
                "The authoritative battle history could not be reconstructed read-only.",
                subsystem="combat.gate5.history",
                retry_safe=False,
                recommended_action="Verify the exact match journal and reducer before viewing history.",
                match_id=match_id,
                details={"diagnostic": diagnostic.model_dump(mode="json") if diagnostic else str(exc)},
                status_code=409,
            ) from exc

        raw_boundaries = history["boundaries"]
        metadata = self._metadata_readonly(match_id, raw_boundaries[0]["state"])
        actor_names = {
            row["runtime_entity_id"]: row["display_name"]
            for row in self._catalog_cache["projections"]
        }
        # Factory fighters: their typed action and character names come from the saved bundles.
        from .gate3_storage import load_typed_bundles

        definition_names = dict(self._definition_names)
        action_profiles = {}
        action_economies = {}
        for bundle in load_typed_bundles(self._match_dir(match_id)):
            actor_names[bundle["actor_id"]] = bundle["actor_template"]["display_name"]
            definition_names.update({row["source_definition_id"]: row["display_name"] for row in bundle["action_catalog"]})
            action_profiles.update({row["source_definition_id"]: row.get("parameters", {}).get("typed", {}) for row in bundle["action_catalog"]})
            action_economies.update({row["source_definition_id"]: str(row.get("economy") or "") for row in bundle["action_catalog"]})
            # Generic reactions (combat/typed_reactions.py) are not actions, so they are not in the
            # catalog above; without this the feed would fall back to the raw mechanic id (owner 2026-09-25).
            definition_names.update({row["feature_id"]: row["name"] for row in bundle.get("typed_reactions") or [] if row.get("name")})
        boundaries = []
        for index, boundary in enumerate(raw_boundaries):
            raw_state = boundary["state"]
            actor_source = raw_state.get("actors") or {}
            current_actor_id = raw_state.get("current_actor_id")
            if isinstance(actor_source, dict):
                actor_names.update({key: row.get("display_name", key) for key, row in actor_source.items()})
            state_view = self._history_state_view(raw_state, metadata)
            events = boundary["events"]
            source_id = next((
                event.get("source_definition_id")
                for event in events
                if event.get("source_definition_id") and not str(event.get("source_definition_id")).startswith("system:")
            ), None)
            action_label = (
                definition_names.get(source_id)
                if source_id else ("Match created" if index == 0 else "Committed decision")
            ) or history_name(source_id, definition_names)
            pre_state = raw_boundaries[index - 1]["state"] if index else None
            feed = format_history_feed(
                events,
                boundary["rolls"],
                pre_state=pre_state,
                post_state=raw_state,
                actor_names=actor_names,
                definition_names=definition_names,
                action_profiles=action_profiles,
                action_economies=action_economies,
                concealed_condition_instance_ids=concealed_condition_instances(raw_state),
            )
            boundaries.append({
                **{key: value for key, value in boundary.items() if key not in {"state", "events", "rolls"}},
                "state": state_view,
                "events": events,
                "rolls": boundary["rolls"],
                "feed": feed,
                "round_number": raw_state.get("round_number"),
                "current_actor_id": current_actor_id,
                "current_actor_name": actor_names.get(current_actor_id, current_actor_id),
                "action_label": action_label,
                "step_label": f"Step {index} · Round {raw_state.get('round_number', '?')} · {actor_names.get(current_actor_id, current_actor_id or 'System')} · {action_label}",
            })
        return {
            "schema": "TianxiaFactoryCombatHistoryView.v1",
            "match_id": match_id,
            "metadata": metadata,
            "reducer_version": history["reducer_version"],
            "journal_record_count": history["journal_record_count"],
            "commit_count": history["commit_count"],
            "boundaries": boundaries,
            "canonical_final_state_sha256": history["canonical_final_state_sha256"],
            "canonical_event_log_sha256": history["canonical_event_log_sha256"],
            "canonical_roll_log_sha256": history["canonical_roll_log_sha256"],
            "read_only": True,
            "diagnostics": history["diagnostics"],
        }

    def character_authority(self, character_sheet_identity: str) -> dict[str, Any]:
        """Return the exact accepted pre-combat authority projection for one stable identity."""
        projection = self.presenter.character_authority(character_sheet_identity)
        if projection is None:
            raise self._error(
                "COMBAT_CONTENT_NOT_READY",
                "The requested character authority projection is unavailable for that exact identity.",
                subsystem="combat.presentation.character_authority",
                retry_safe=False,
                recommended_action="Open a character identity supplied by the current match Combat Sheet; no display-name fallback is permitted.",
                details={"character_sheet_identity": character_sheet_identity},
                status_code=404,
            )
        return projection.model_dump(mode="json", by_alias=True)

    def presentation(
        self,
        match_id: str,
        boundary_index: int | None = None,
        *,
        feed: bool = True,
        session: Gate4PersistentSession | None = None,
        include_candidates: bool = True,
    ) -> dict[str, Any]:
        """Project one exact live or historical boundary without mutating match storage.

        ``feed=False`` leaves the live boundary's history feed empty instead of replaying the whole journal to build it
        (``history`` re-derives every boundary, so it grows with the fight); the tabletop streams its own feed from
        ``/events`` and never reads it. ``include_candidates=False`` projects
        committed actor/event facts without generating next-choice availability;
        those rows are empty until a full menu read. ``session`` is a verified
        loaded or post-commit presentation boundary, never client authority.
        """
        if session is None:
            session = self._load_session(match_id)
        live_raw = session.engine.state.model_dump(mode="json")
        metadata = self._metadata_readonly(match_id, live_raw)
        history = self.history(match_id) if (feed or boundary_index is not None) else {}

        if boundary_index is None:
            state = self._history_state_view(live_raw, metadata)
            state = {**state, "zones": [_zone_row(zone, session.engine) for zone in state.get("zones") or []]}
            candidates = (self._legal_candidates(session)
                          if include_candidates and state.get("terminal_result") is None else ())
            feed_rows = tuple(history["boundaries"][-1].get("feed") or []) if history.get("boundaries") else ()
            mode = "LIVE"
            boundary = None
        else:
            boundaries = history.get("boundaries") or []
            if boundary_index < 0 or boundary_index >= len(boundaries):
                raise self._error(
                    "COMBAT_UI_DATA_INVALID",
                    "The requested battle-history boundary is outside the authoritative replay range.",
                    subsystem="combat.presentation.history",
                    retry_safe=True,
                    recommended_action="Select a boundary returned by the battle-history endpoint.",
                    match_id=match_id,
                    details={"boundary_index": boundary_index, "boundary_count": len(boundaries)},
                    status_code=404,
                )
            selected = boundaries[boundary_index]
            state = {**selected["state"],
                     "zones": [_zone_row(zone, session.engine) for zone in selected["state"].get("zones") or []]}
            candidates = ()
            feed_rows = tuple(selected.get("feed") or [])
            mode = "HISTORY"
            boundary = {**selected, "boundary_index": boundary_index}

        catalog, typed_actions = self._catalog_with_factory_fighters(match_id)
        # Generic display-only condition hiding. Plug-ins may hide projected rows
        # without mutating the rules state or its event-sourced condition instances.
        from . import ext
        from .gate2_runtime_models import ActorState
        from .summons import never_entered_play
        for actor in state.get("actors") or []:
            if never_entered_play(actor):
                continue  # off the map until summoned: nothing of it is shown, so nothing is hidden
            actor_state = {key: value for key, value in actor.items() if key in ActorState.model_fields}
            projected_actor = ActorState.model_validate(actor_state)
            hidden_ids: set[str] = set()
            for answer in ext.run("presentation_hidden_conditions", session.engine, projected_actor):
                hidden_ids.update(answer or ())
            if hidden_ids:
                actor["presentation_hidden_condition_ids"] = sorted(hidden_ids)
        try:
            projection = self.presenter.project(
                match_id=match_id,
                metadata=metadata,
                state=state,
                catalog=catalog,
                mode=mode,
                candidates=candidates,
                feed=feed_rows,
                boundary=boundary,
                typed_actions=typed_actions,
            )
        except CombatServiceError:
            raise
        except Exception as exc:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The authoritative combat presentation projection could not be constructed.",
                subsystem="combat.presentation",
                retry_safe=False,
                recommended_action="Inspect the exact catalog, match lock, battlefield definition, and projection findings; do not substitute display-name joins.",
                match_id=match_id,
                details={"reason": str(exc), "boundary_index": boundary_index},
                status_code=409,
            ) from exc
        result = projection.model_dump(mode="json", by_alias=True)
        if not include_candidates:
            for actor in result['actors']:
                actor['action_availability'] = []
        return result

    # ------------------------------------------------------------------
    # Match lifecycle and views
    # ------------------------------------------------------------------
    # What the saved files of a fight say about its state, read *before* loading it: a later change to the fight (a commit
    # appends to the journal) changes it, so nothing derived from an older state is ever reused.  Content files that bind
    # the fight (its genesis, typed bundles, arena, locks) are included so a replaced fight is not mistaken for the old one.
    # The journal is append-only and hash-chained. Identify its authority by size, inode and last bytes (the last
    # record's hash), not metadata-only mtime changes; unchanged reads no longer touch an existing journal.
    _FINGERPRINT_FILES = ("GenesisState.json", "Typed_Character_Bundles.json", "Arena_Battlefield.json",
                          "MatchLock.json", RUNTIME_AUTHORITY_FILE, SOURCE_PACKAGE_FILE)
    _DERIVED_LIMIT = 8

    def _fingerprint(self, match_id: str) -> tuple[Any, ...]:
        """The journal's identity: size, inode and its last 512 bytes.

        Appends change the size and an atomic replace changes the inode, which is every write the engine makes. A
        same-size rewrite in place whose final 512 bytes stayed byte-identical would not show here (combat/table_state_cache.py).
        """
        match_dir = self._match_dir(match_id)
        parts: list[Any] = []
        try:
            with (match_dir / "Journal.ndjson").open("rb") as journal:
                size = os.fstat(journal.fileno()).st_size
                journal.seek(max(0, size - 512))
                parts.append((size, os.fstat(journal.fileno()).st_ino, journal.read(512)))
        except OSError:
            parts.append(None)
        for name in self._FINGERPRINT_FILES:
            try:
                stat = (match_dir / name).stat()
            except OSError:
                parts.append(None)
            else:
                parts.append((stat.st_size, stat.st_mtime_ns, stat.st_ino))
        return tuple(parts)

    def _state_key(self, session: Gate4PersistentSession) -> tuple[str, Any] | None:
        """The cache key of the state ``session`` was loaded at, or None when its engine has moved on since (a session
        that has run an action must not reuse, or feed, what was derived from the state it loaded)."""
        loaded = getattr(session.engine, "_cf_state_key", None)
        state = session.engine.state
        if loaded is None or tuple(loaded[1:]) != (state.state_version, state.event_sequence, state.roll_counter):
            return None
        if getattr(session.engine, '_cf_read_state_sha256', None) != canonical_state_sha256(state):
            return None  # unrecorded edits must not inherit a saved-state menu
        # Control mode changes the movement menu (manual jumps versus AI ground
        # movement) without advancing the journal. Keep those menus distinct.
        modes = tuple(sorted(getattr(session.engine, "typed_control_modes", {}).items()))
        viewers = tuple(sorted(getattr(session.engine, "typed_ask_reactors", ())))
        tiers = tuple(sorted(getattr(session.engine, "ai_tier_overrides", {}).items()))
        return session.match_id, (loaded[0], modes, viewers, tiers)

    def presentation_session(self, session: Gate4PersistentSession):
        """Reuse a just-committed engine only when it equals the saved boundary.

        Compare the exact canonical journal tail and complete post-state hash,
        plus every immutable input fingerprint and current control modes. A
        concurrent writer, incomplete transaction, replaced map/catalog or
        unrecorded engine edit falls back to ordinary verified load. This seam
        avoids replaying the action again solely to draw its committed result.
        It never reuses a session for a later action or stores a live engine.
        """
        engine = session.engine
        loaded = getattr(engine, '_cf_state_key', None)
        records = session.mechanical._records
        if loaded is None or not records or records[-1].get('record_type') not in {'COMMIT', 'MATCH_FINALIZED'}:
            return None
        fingerprint = self._fingerprint(session.match_id)
        if fingerprint[1:] != loaded[0][1:]:
            return None
        commits = (row for row in reversed(records) if row.get('record_type') == 'COMMIT')
        last_commit = next(commits, None)
        expected_hash = last_commit.get('post_state_sha256') if last_commit is not None else None
        if expected_hash != canonical_state_sha256(engine.state):
            return None
        tail = canonical_bytes(records[-1]) + b'\n'
        try:
            with (self._match_dir(session.match_id) / 'Journal.ndjson').open('rb') as journal:
                journal.seek(0, os.SEEK_END)
                if journal.tell() < len(tail):
                    return None
                journal.seek(-len(tail), os.SEEK_END)
                if journal.read() != tail:
                    return None
        except OSError:
            return None
        metadata = self._read_metadata(session.match_id, session)
        if dict(metadata.get('ai_tiers') or {}) != getattr(engine, 'ai_tier_overrides', {}):
            return None
        if dict(metadata.get('participant_control_modes') or {}) != engine.typed_control_modes:
            return None
        if self._fingerprint(session.match_id) != fingerprint:
            return None
        # Conditions/setup created by the commit can grant new player-owned
        # choices. Refresh this derived control set just as a cold load does.
        engine.typed_ask_reactors = self._ask_reactors(metadata, session)
        state = engine.state
        engine._cf_state_key = (fingerprint, state.state_version, state.event_sequence, state.roll_counter)
        engine._cf_read_state_sha256 = canonical_state_sha256(state)
        return session

    def _derived_get(self, key: tuple[str, Any], name: Any) -> Any:
        with self._derived_lock:
            entry = self._derived.get(key[0])
            if entry is None or entry[0] != key[1]:
                return None
            self._derived.move_to_end(key[0])
            return entry[1].get(name)

    def _derived_put(self, key: tuple[str, Any], name: Any, value: Any) -> None:
        with self._derived_lock:
            entry = self._derived.get(key[0])
            if entry is None or entry[0] != key[1]:
                entry = (key[1], {})
                self._derived[key[0]] = entry
            entry[1][name] = value
            self._derived.move_to_end(key[0])
            while len(self._derived) > self._DERIVED_LIMIT:
                self._derived.popitem(last=False)

    def _legal_candidates(self, session: Gate4PersistentSession, *, knowledge_only: bool = False,
                          progress_guard: bool = True) -> tuple[Any, ...]:
        """``session.engine.legal_candidates()``, worked out once per saved state (it costs about half a second in a
        big fight, and a table asks for it several times per action).

        Knowledge-only AI placement queries have a separate cache and availability
        record. Never feed the real-roster player menu back into AI generation;
        execution/binding and table menus retain the canonical default query.
        This seam applies to all area shapes and self-teleport abilities.
        ``progress_guard=False`` retains the full native query for suggestions
        and model ranking. Local Auto and player binding retain their existing
        failed-action guards. Both projections share one native generation.
        """
        key = self._state_key(session)
        candidate_key = 'observed_candidates' if knowledge_only else 'candidates'
        from . import movement_menu
        table_routes = movement_menu.active() and not knowledge_only
        if table_routes:
            candidate_key += '_table'
        from . import lazy_menu
        lazy = table_routes and lazy_menu.active(session.engine)
        if lazy:
            candidate_key += '_lazy'
        availability_key = 'observed_availability' if knowledge_only else 'availability'
        if table_routes:
            availability_key += '_table'
        if lazy:
            availability_key += '_lazy'
        if not progress_guard:
            candidate_key += '_native'
            availability_key += '_native'
        if key is not None:
            hit = self._derived_get(key, candidate_key)
            if hit is not None:
                if table_routes:
                    session.engine._cf_menu_routes = self._derived_get(key, 'table_routes_lazy' if lazy else 'table_routes') or ()
                session.engine._cf_availability = self._derived_get(key, availability_key)
                return hit
        from .action_legality import observe, remember
        from contextlib import nullcontext
        from .candidate_knowledge import query, roster
        query_key = 'observed_query' if knowledge_only else 'player_query'
        if table_routes:
            query_key += '_table'
        if lazy:
            query_key += '_lazy'
        prepared = self._derived_get(key, query_key) if key is not None else None
        if prepared is None:
            from .placement_menu import query as placement_query
            # Preserve path-based no-op suppression at rare failed-move
            # boundaries. Those use the existing full native representation.
            native_routes = table_routes and movement_menu.native_routes_required(session)
            with placement_query(), (query(session.engine) if knowledge_only else nullcontext()), observe(session.engine) as observations, (movement_menu.suspend() if native_routes else nullcontext()):
                native = tuple(session.engine.legal_candidates())
                if table_routes:
                    session.engine._cf_menu_routes = tuple(movement_menu.rows())
                known = tuple(a.model_copy(deep=True) for a in roster(session.engine)) if knowledge_only else None
            prepared = (native, observations, known)
            if key is not None:
                self._derived_put(key, query_key, prepared)
                if table_routes:
                    self._derived_put(key, 'table_routes_lazy' if lazy else 'table_routes', session.engine._cf_menu_routes)
        candidates, observations, known = prepared
        # Versioned candidate IDs alone cannot prevent a committed no-op loop.
        # This general, read-only seam uses a bounded tail of the mechanical
        # session's verified bindings/turn receipts, never another journal scan.
        # Fresh actions and recorded execution/replay keep native legality.
        from .turn_progress import narrow
        if progress_guard:
            candidates = narrow(session, candidates, verified_records=session.mechanical._records,
                                for_ai=knowledge_only)
        if not candidates and session.engine.state.terminal_result is None:
            # Candidate hooks are allowed to narrow a menu, but a faulty plug-in
            # must not strand a live table. Recover only the engine's system
            # bookkeeping candidate (setup or End Turn); never invent an action.
            from .ext.system_bookkeeping import recovery_candidates

            candidates = recovery_candidates(session.engine)
        availability = remember(session.engine, candidates, observations)
        if key is not None:
            self._derived_put(key, candidate_key, candidates)
            self._derived_put(key, availability_key, availability)
            if knowledge_only:
                self._derived_put(key, 'observed_roster', known)
        return candidates

    @contextmanager
    def _execution_candidates(self, engine: Gate4ControllerEngine, candidates: tuple[Any, ...], state_sha256: str):
        """Reuse the checked pre-state choices during preview/commit validation only.

        Execution can ask again after effects or reaction checkpoints change state.
        Hash the complete state on each read, including changes within a transaction
        that have not advanced state_version, and fall back to the real generator.
        """
        # Candidate generation also rebuilds wall geometry. A preview clone has
        # the saved zones but a fresh grid, so retain that preparation explicitly.
        from .zones import sync_walls

        sync_walls(engine)
        generate = engine.legal_candidates
        previous = engine.__dict__.get("legal_candidates")

        def for_current_state():
            if canonical_state_sha256(engine.state) == state_sha256:
                return candidates
            return generate()

        engine.legal_candidates = for_current_state
        try:
            yield
        finally:
            if previous is None:
                del engine.legal_candidates
            else:
                engine.legal_candidates = previous

    def _load_waiting_for_lock(self, match_id: str, wait_s: float = 6.0) -> Gate4PersistentSession:
        """Open a fight, waiting while another request of this server holds its writer lock for a moment (the table's poll,
        a state read and an action land together; the lock is taken non-blocking, so the second used to be refused with
        "Another local process currently owns this match directory" -- owner 2026-09-29)."""
        import time

        deadline = time.monotonic() + wait_s
        while True:
            try:
                return self.persistence.load_match(match_id, recover=True)
            except Exception as exc:  # noqa: BLE001 - only the busy lock is retried; everything else is raised unchanged
                code = getattr(getattr(exc, "diagnostic", None), "code", None) or getattr(exc, "code", None)
                busy = code == "MATCH_STORAGE_LOCKED" or "currently owns this match directory" in str(exc)
                if not busy or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)

    def _load_session(self, match_id: str) -> Gate4PersistentSession:
        fingerprint = self._fingerprint(match_id)
        # Validate existing display/control data before mechanical recovery can
        # write to this save. Missing metadata can still be derived on demand.
        metadata_path = self._metadata_path(match_id)
        metadata = self._read_metadata(match_id) if metadata_path.exists() or metadata_path.is_symlink() else None
        try:
            session = self._load_waiting_for_lock(match_id)
        except CombatServiceError:
            raise
        except (OSError, CombatGate1Error, ValueError, KeyError, TypeError) as exc:
            if not self._match_dir(match_id).is_dir():
                raise self._error(
                    "COMBAT_MATCH_NOT_FOUND", "That saved fight does not exist.",
                    subsystem="combat.persistence", retry_safe=False,
                    recommended_action="Choose a saved fight or start a new one.",
                    match_id=match_id, status_code=404,
                ) from exc
            underlying = getattr(getattr(exc, "diagnostic", None), "code", None)
            if underlying == "MATCH_STORAGE_LOCKED":
                raise self._error(
                    "COMBAT_CONTENT_NOT_READY", "The fight is being saved; try again in a moment.",
                    subsystem="combat.persistence", retry_safe=True,
                    recommended_action="Wait for the current save to finish.",
                    match_id=match_id, status_code=409,
                ) from exc
            raise self._error(
                UNSUPPORTED_CODE, UNSUPPORTED_MESSAGE,
                subsystem="combat.persistence", retry_safe=False,
                recommended_action="Start a new fight. You can delete this saved fight from the table.",
                match_id=match_id, details={"reason": getattr(exc, "reason", str(exc)),
                                          "saved_data_diagnostic": underlying},
                status_code=409,
            ) from exc
        state = session.engine.state
        session.engine._cf_state_key = (fingerprint, state.state_version, state.event_sequence, state.roll_counter)
        session.engine._cf_read_state_sha256 = canonical_state_sha256(state)
        self.refresh_execution_controls(session, metadata)
        return session

    def refresh_execution_controls(self, session: Gate4PersistentSession, metadata=None) -> None:
        """Refresh load-derived controls at an owned execution boundary.

        Used after verified acquisition and every durable action, for human,
        built-in and model decisions alike. The caller exclusively owns this
        session and holds the table command reservation; this grants no bypass
        of candidate, transaction or durable-tail validation.
        """
        state = session.engine.state
        # Area defaults depend on who controls the caster. Read existing metadata
        # directly: legacy metadata synthesis can write files during a load.
        session.engine.typed_control_modes = dict(metadata.get("participant_control_modes") or {}) if metadata else {}
        session.engine.ai_tier_overrides = dict(metadata.get("ai_tiers") or {}) if metadata else {}
        # Plain read-only policy data for a resolving placement's second stage;
        # no method replacement and no extra fight-state or execution authority.
        session.engine.placement_policies = {
            state.current_actor_id: self.policies.for_actor(state.current_actor_id)[0].model_dump(mode='json')
        } if state.current_actor_id in state.actors else {}
        session.engine.typed_ask_reactors = frozenset()
        from . import ext
        choice_reactors = {actor_id for ids in ext.run("choice_reactors", session.engine) for actor_id in ids}
        if metadata is not None and (
                state.setup_tasks or choice_reactors or any(row.get("ask") for rows in (getattr(session.engine, "typed_reaction_rows", {}) or {}).values() for row in rows)
                or any(row.get("choice_owner") for rows in (getattr(session.engine, "typed_passive_rows", {}) or {}).values() for row in rows)
                or any(self._condition_choice_owner(session.engine, actor, c)
                       for actor in session.engine.state.actors.values() for c in actor.conditions.values())):
            # Only a fight with an Ask me character reads its control modes here (reading a legacy match's metadata
            # writes it, and loading must stay read-only).
            session.engine.typed_ask_reactors = self._ask_reactors(metadata, session)

    def _reconstructed_inputs(self, engine):
        """Pure load/recovery inputs, without recursively opening persistence."""
        from types import SimpleNamespace
        session = SimpleNamespace(engine=engine, match_id=engine.state.match_id)
        path = self._metadata_path(session.match_id)
        metadata = self._read_metadata(session.match_id) if path.exists() or path.is_symlink() else None
        self.refresh_execution_controls(session, metadata)

    def _recover_local_choice(self, engine, records):
        """Recover with the live knowledge, progress guards, tier and Dao policy."""
        from types import SimpleNamespace
        from .gate3_storage import Gate3MatchStore
        session = SimpleNamespace(engine=engine, match_id=engine.state.match_id,
                                  store=Gate3MatchStore(self.userdata_root, engine.state.match_id),
                                  mechanical=SimpleNamespace(_records=records))
        return self._local_choice(session)[0]

    def _local_choice(self, session, candidates=None):
        """One primary-choice implementation for live execution AND recovery."""
        if candidates is None:
            candidates = self._legal_candidates(session, knowledge_only=True)
        context = self.ai_decision_context(session, progress_guard=True)
        choice = self.controller.choose_primary_action(context)
        from .ext.system_bookkeeping import recovery_provenance
        selected = next(c for c in candidates if c.candidate_id == choice.intent.candidate_id)
        recovery = recovery_provenance(session.engine, selected)
        if recovery is not None:
            choice = choice.model_copy(update={"record": choice.record.model_copy(
                update={"diagnostics": (*choice.record.diagnostics, recovery)})})
        return choice, candidates, recovery

    @staticmethod
    def _condition_choice_owner(engine: Any, actor: Any, condition: Any) -> bool:
        """Read-only ownership for persisted grants, including legacy plugin conditions."""
        return bool(condition.data.get("choice_owner")) or any(
            value is True for value in extension_hooks("condition_choice_owner", engine, actor, condition))

    def _ask_reactors(self, metadata: dict[str, Any], session: Gate4PersistentSession) -> frozenset[str]:
        """Owner 2026-09-26 (step 16): the Factory fighters set to Ask me that a player controls in this fight. Their
        reactions pause the fight for an answer (combat/typed_reactions.py _consent); an AI-controlled one reacts as
        Auto. Empty for every other fight, so AI steps there run once, as before."""
        rows = getattr(session.engine, "typed_reaction_rows", {}) or {}
        passives = getattr(session.engine, "typed_passive_rows", {}) or {}
        from . import ext
        choice_reactors = {actor_id for ids in ext.run("choice_reactors", session.engine) for actor_id in ids}
        return frozenset(actor_id for actor_id in session.engine.state.actors
                         if (actor_id in choice_reactors or any(task.actor_id == actor_id for task in session.engine.state.setup_tasks)
                             or any(row.get("ask") for row in rows.get(actor_id, []))
                             or any(row.get("choice_owner") for row in passives.get(actor_id, []))
                             or any(self._condition_choice_owner(session.engine, session.engine.state.actors[actor_id], c)
                                    for c in session.engine.state.actors[actor_id].conditions.values()))
                         and self._mode_for_actor(metadata, session, actor_id) in MANUAL_SUBMIT_MODES)


    def preflight_new_fight(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Read-only C3D-P1 preflight over built-in and verified installed combatants."""
        catalog = self.catalog()
        accepted = catalog["encounters"][0]
        battlefield = next((b for b in catalog["battlefields"] if b.get("stable_id") == payload.get("battlefield_id") and b.get("readiness_status", "COMBAT_READY") == "COMBAT_READY"), None)
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        if payload.get("encounter_id") != accepted["stable_id"]:
            blockers.append({"code": "C3C_ENCOUNTER_NOT_EXECUTABLE", "actual": payload.get("encounter_id")})
        if battlefield is None:
            blockers.append({"code": "C3C_BATTLEFIELD_NOT_EXECUTABLE", "actual": payload.get("battlefield_id")})
            battlefield = catalog["battlefields"][0]
        if payload.get("initiative_method") != "DETERMINISTIC_ACCEPTED":
            blockers.append({"code": "C3C_INITIATIVE_METHOD_UNSUPPORTED", "actual": payload.get("initiative_method")})
        seed = str(payload.get("match_seed") or "").strip()
        if not seed:
            warnings.append({"code": "C3C_SEED_WILL_BE_GENERATED", "message": "A deterministic seed will be generated only after owner confirmation."})
        elif len(seed) > 200:
            blockers.append({"code": "C3C_SEED_INVALID"})
        ready_rows = {r["runtime_entity_id"]: r for r in catalog["projections"] if r.get("primary_combatant") and r.get("readiness_status") == "COMBAT_READY"}
        companion_rows = {r["runtime_entity_id"]: r for r in catalog["projections"] if not r.get("primary_combatant")}
        participants = payload.get("participants") or []
        supplied_ids = [str(r.get("actor_id") or "") for r in participants]
        if len(supplied_ids) < 2:
            blockers.append({"code": "C3C_ROSTER_REQUIRES_TWO_PRIMARY_COMBATANTS"})
        if len(set(supplied_ids)) != len(supplied_ids):
            blockers.append({"code": "C3C_DUPLICATE_PRIMARY_COMBATANT", "actors": supplied_ids})
        for actor_id in supplied_ids:
            if actor_id in companion_rows:
                blockers.append({"code": "C3C_COMPANION_NOT_INDEPENDENTLY_SELECTABLE", "actor_id": actor_id})
            elif actor_id not in ready_rows:
                blockers.append({"code": "C3C_COMBATANT_NOT_READY", "actor_id": actor_id})
        team_ids = sorted({str(r.get("team_id") or "") for r in participants if str(r.get("team_id") or "")})
        from .relations import NEUTRAL_TEAM
        if len(set(team_ids) - {NEUTRAL_TEAM}) != 2:
            blockers.append({"code": "C3C_EXACTLY_TWO_NONEMPTY_TEAMS_REQUIRED", "team_ids": team_ids})
        team_names = {tid: str((payload.get("team_names") or {}).get(tid) or tid)[:120] for tid in team_ids}
        if NEUTRAL_TEAM in team_names:
            team_names[NEUTRAL_TEAM] = 'Neutral'
        grid = SquareGrid(battlefield)
        occupied: set[tuple[int, int]] = set()
        normalized: list[dict[str, Any]] = []
        portable_authorities: list[dict[str, Any]] = []
        control_modes: dict[str, str] = {}
        suffixes = {"stamina": ".stamina", "qi": ".qi", "resonance": ".resonance"}
        for index, row in enumerate(participants):
            actor_id = str(row.get("actor_id") or "")
            expected = ready_rows.get(actor_id)
            installed = bool(expected and expected.get("installed_character"))
            template = ACTORS.get(actor_id)
            mode = str(row.get("controller_mode") or "MANUAL")
            if mode not in CONTROL_MODES:
                blockers.append({"code": "C3C_CONTROLLER_MODE_UNSUPPORTED", "actor_id": actor_id, "actual": mode})
            control_modes[actor_id] = mode
            placement = row.get("placement")
            position = None
            if not isinstance(placement, dict) or not isinstance(placement.get("x"), int) or not isinstance(placement.get("y"), int):
                blockers.append({"code": "C3C_PLACEMENT_REQUIRED", "actor_id": actor_id})
            else:
                position = Position.model_validate(placement)
            if installed:
                from .footprints import standard_actor_footprint
                definition = standard_actor_footprint().model_copy(update={
                    "footprint_id": f"footprint:{actor_id}.1x1",
                    "source_definition_id": f"system:combat.actor_footprint:{actor_id}",
                })
            else:
                definition, _ = resolve_actor_footprint(actor_id if actor_id in ACTORS else "an_eui")
            if int(row.get("footprint_width") or 1) != definition.width_cells or int(row.get("footprint_height") or 1) != definition.height_cells:
                blockers.append({"code": "C3C_FOOTPRINT_UNSUPPORTED", "actor_id": actor_id})
            if position is not None:
                if not grid.placement_legal(position, footprint=definition, occupied_cells=occupied):
                    blockers.append({"code": "C3C_PLACEMENT_ILLEGAL", "actor_id": actor_id, "placement": placement})
                else:
                    occupied.update(grid.footprint_cells(position, definition))
            allowed_token = expected.get("character_sheet_identity") if expected else None
            token_id = row.get("token_asset_id") or allowed_token
            if expected and token_id != allowed_token:
                blockers.append({"code": "C3C_TOKEN_BINDING_UNSUPPORTED", "actor_id": actor_id})
            actual_resources: dict[str, int] = {}
            owner_resources: dict[str, int | None] = {}
            source_authority = None
            if installed and expected:
                qi_present = "qi_current" in row and row.get("qi_current") is not None
                mf_present = "martial_focus_current" in row and row.get("martial_focus_current") is not None
                if not qi_present or not mf_present:
                    blockers.append({"code": "C3D_CURRENT_RESOURCE_INITIALIZATION_REQUIRED", "actor_id": actor_id, "required": ["qi_current", "martial_focus_current"]})
                qi = row.get("qi_current")
                mf = row.get("martial_focus_current")
                try:
                    validation = self.combatant_library.validate_resource_initialization(
                        expected["candidate_entry_id"],
                        qi_current=int(qi) if qi_present else None,
                        martial_focus_current=int(mf) if mf_present else None,
                        provenance_kind="ENCOUNTER_AUTHORITY",
                        provenance_id=f"c3d-preflight:{seed or 'pending'}:{index}",
                    )
                except Exception as exc:
                    validation = None
                    blockers.append({"code": "C3D_RESOURCE_INITIALIZATION_INVALID", "actor_id": actor_id, "reason": str(exc)})
                if validation is not None and not validation.valid:
                    blockers.append({"code": "C3D_RESOURCE_INITIALIZATION_INVALID", "actor_id": actor_id, "details": list(validation.unresolved_requirements)})
                if validation is not None and validation.valid:
                    entry = self.combatant_library.candidate(expected["candidate_entry_id"])
                    package = self.combatant_library._package_for_entry(entry)
                    authority = build_runtime_authority(
                        entry, package, qi_current=int(qi), martial_focus_current=int(mf),
                        provenance_id=f"c3d-preflight:{seed or 'pending'}:{index}",
                    )
                    if authority.runtime_actor_id != actor_id:
                        blockers.append({"code": "C3D_RUNTIME_ACTOR_ID_MISMATCH", "actor_id": actor_id})
                    else:
                        portable_authorities.append(authority.model_dump(mode="json", by_alias=True))
                        actual_resources = {"resource:core.qi": int(qi), "resource:core.martial_focus": int(mf)}
                        owner_resources = {"qi": int(qi), "martial_focus": int(mf), "stamina": None, "resonance": None}
                        source_authority = {
                            "candidate_entry_id": entry.entry_id, "project_id": entry.character_project_id,
                            "package_sha256": entry.source_package_sha256, "project_revision": entry.project_revision,
                            "event_head_hash": entry.event_head_hash, "replay_state_hash": entry.replay_state_hash,
                            "content_lock_hash": entry.content_lock_hash, "combat_sheet_id": entry.combat_sheet_id,
                            "combat_sheet_commitment_sha256": entry.combat_sheet_commitment_sha256,
                            "mechanics_lock_sha256": entry.mechanics_lock_sha256,
                            "primitive_registry_sha256": entry.primitive_registry_sha256,
                            "runtime_adapter_id": entry.runtime_adapter_id,
                            "runtime_adapter_version": entry.runtime_adapter_version,
                            "runtime_engine_version": entry.runtime_engine_version,
                            "actor_template_commitment_sha256": entry.actor_template_commitment_sha256,
                        }
            else:
                template_resources = {r.resource_id: r for r in template.resources} if template else {}
                for owner_name, suffix in suffixes.items():
                    resource_id = next((rid for rid in template_resources if rid.endswith(suffix)), None)
                    requested = int(row.get(f"{owner_name}_current") or 0)
                    if resource_id is None:
                        if requested != 0:
                            blockers.append({"code": "C3C_RESOURCE_NOT_POSSESSED", "actor_id": actor_id, "resource": owner_name})
                        owner_resources[owner_name] = None
                    else:
                        maximum = int(template_resources[resource_id].maximum)
                        if requested < 0 or requested > maximum:
                            blockers.append({"code": "C3C_RESOURCE_OUT_OF_RANGE", "actor_id": actor_id, "resource": owner_name, "maximum": maximum, "actual": requested})
                        actual_resources[resource_id] = requested
                        owner_resources[owner_name] = requested
            normalized.append({
                "actor_id": actor_id, "participant_kind": "PRIMARY_COMBATANT",
                "display_name": expected.get("display_name") if expected else actor_id,
                "character_sheet_identity": allowed_token,
                "projection_sha256": expected.get("projection_sha256") if expected else None,
                "team_id": row.get("team_id"), "team_display_name": team_names.get(str(row.get("team_id")), str(row.get("team_id"))),
                "starting_resources": owner_resources, "actual_resources": {k: actual_resources[k] for k in sorted(actual_resources)},
                "controller_mode": mode, "token_asset_id": token_id,
                "footprint": {"footprint_id": definition.footprint_id, "width": definition.width_cells, "height": definition.height_cells},
                "placement": placement, "installed_character": installed, "source_authority": source_authority,
            })
        if len(portable_authorities) > 1:
            blockers.append({"code": "C3D_P1_SINGLE_PORTABLE_RUNTIME_CANDIDATE_ONLY"})
        if BAI in supplied_ids:
            owner = next(r for r in normalized if r["actor_id"] == BAI)
            actor_id = CUI; definition, _ = resolve_actor_footprint(actor_id)
            placement = battlefield["starting_positions"][actor_id]; pos = Position.model_validate(placement)
            if not grid.placement_legal(pos, footprint=definition, occupied_cells=occupied): blockers.append({"code": "C3C_COMPANION_PLACEMENT_ILLEGAL", "actor_id": actor_id})
            else: occupied.update(grid.footprint_cells(pos, definition))
            template = ACTORS[actor_id]
            normalized.append({"actor_id": actor_id, "participant_kind": "INCLUDED_COMPANION", "owner_actor_id": BAI, "display_name": "Cui", "character_sheet_identity": "creature:bai_cui", "projection_sha256": template.projection_sha256, "team_id": owner["team_id"], "team_display_name": owner["team_display_name"], "starting_resources": {}, "actual_resources": {r.resource_id:r.initial for r in template.resources}, "controller_mode": owner["controller_mode"], "token_asset_id": "creature:bai_cui", "footprint": {"footprint_id": definition.footprint_id, "width": definition.width_cells, "height": definition.height_cells}, "placement": placement, "installed_character": False, "source_authority": None})
        calibration = payload.get("grid_calibration") or {}
        expected_calibration = {"mode":"AUTHORITATIVE_GATE2_GRID","width":battlefield["width_squares"],"height":battlefield["height_squares"],"square_size_ft":battlefield["square_size_ft"],"centered_tokens":True}
        if calibration != expected_calibration: blockers.append({"code":"C3C_GRID_CALIBRATION_MISMATCH","expected":expected_calibration,"actual":calibration})
        # C3D fields are package-contract authority and therefore appear only when
        # at least one verified portable runtime participant is present.  Built-in
        # C3C-P3 fights retain their exact accepted preflight and setup surface.
        has_portable_runtime = bool(portable_authorities)
        if not has_portable_runtime:
            for participant in normalized:
                participant.pop("installed_character", None)
                participant.pop("source_authority", None)
        report = {
            "schema": "TianxiaFactory.C3DPreflight.v1" if has_portable_runtime else "TianxiaFactory.C3CPreflight.v3",
            "scope": "PORTABLE_CHARACTER_TO_DYNAMIC_LIVE_COMBAT" if has_portable_runtime else "DYNAMIC_COMBAT_READY_TWO_TEAM_ROSTER",
            "read_only":True,"writes_performed":0,"match_created":False,"controller_lock_created":False,"snapshot_created":False,"dice_rolls":0,"persisted_combat_events":0,
            "encounter":{"stable_id":accepted["stable_id"],"display_name":accepted["display_name"]},
            "battlefield":{"stable_id":battlefield["stable_id"],"content_sha256":canonical_sha256(battlefield)},
            "primary_actor_ids":sorted(supplied_ids),
            "included_companion_ids":sorted([r["actor_id"] for r in normalized if r["participant_kind"]=="INCLUDED_COMPANION"]),
            "teams":[{"team_id":tid,"display_name":team_names[tid]} for tid in team_ids],
            "participants":sorted(normalized,key=lambda x:x["actor_id"]),
            "grid_calibration":calibration,"initiative_method":payload.get("initiative_method"),"match_seed":seed or None,
            "maximum_rounds":int(payload.get("maximum_rounds") or 20),
            "control_modes":{k:control_modes[k] for k in sorted(control_modes)},
            "blockers":blockers,"warnings":warnings,"ready":not blockers,
        }
        if has_portable_runtime:
            report["portable_runtime_authorities"] = sorted(portable_authorities, key=lambda x:x["runtime_actor_id"])
        source={k:v for k,v in report.items() if k not in {"warnings","blockers","ready"}}
        report["preflight_commitment"]=canonical_sha256(source)
        return report

    def create_confirmed_fight(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("owner_confirmed") is not True:
            raise self._error(
                "C3C_OWNER_CONFIRMATION_REQUIRED",
                "Confirm Create Fight before persistent match records are written.",
                subsystem="combat.c3c.creation",
                retry_safe=True,
                recommended_action="Review the no-write preflight and explicitly confirm Create Fight.",
                status_code=409,
            )
        preflight = self.preflight_new_fight(payload)
        if not preflight["ready"]:
            raise self._error(
                "C3C_PREFLIGHT_BLOCKED",
                "The fight cannot be created until every preflight blocker is resolved.",
                subsystem="combat.c3c.preflight",
                retry_safe=True,
                recommended_action="Correct the listed team, placement, resource, battlefield, grid, or controller fields.",
                details={"blockers": preflight["blockers"]},
                status_code=409,
            )
        if payload.get("preflight_commitment") != preflight["preflight_commitment"]:
            raise self._error(
                "C3C_PREFLIGHT_STALE",
                "The confirmed setup no longer matches the reviewed preflight.",
                subsystem="combat.c3c.creation",
                retry_safe=True,
                recommended_action="Run the preflight again and confirm the unchanged setup.",
                status_code=409,
            )
        seed = str(payload.get("match_seed") or f"C3C-{secrets.token_hex(16)}").strip()
        setup_binding = {
            "schema": "TianxiaFactory.C3CMatchSetupBinding.v1",
            "preflight_commitment": preflight["preflight_commitment"],
            "participants": preflight["participants"],
            "primary_actor_ids": preflight["primary_actor_ids"],
            "included_companion_ids": preflight["included_companion_ids"],
            "teams": preflight["teams"],
            "battlefield": preflight["battlefield"],
            "grid_calibration": preflight["grid_calibration"],
            "initiative_method": preflight["initiative_method"],
            "maximum_rounds": preflight["maximum_rounds"],
        }
        if preflight.get("portable_runtime_authorities"):
            setup_binding["portable_runtime_authorities"] = preflight["portable_runtime_authorities"]
        try:
            return self.create_match(
                encounter_id=payload["encounter_id"],
                display_name=payload.get("display_name"),
                match_seed=seed,
                control_modes=preflight["control_modes"],
                maximum_rounds=preflight["maximum_rounds"],
                creation_key=str(payload["idempotency_key"]),
                setup_binding=setup_binding,
            )
        except CombatServiceError:
            raise
        except Exception as exc:
            raise self._error(
                "C3C_ATOMIC_CREATION_FAILED",
                "The fight could not be created; no partial match was retained.",
                subsystem="combat.c3c.creation",
                retry_safe=True,
                recommended_action="Review the setup and retry the same confirmed request.",
                details={"reason": str(exc)},
                status_code=409,
            ) from exc

    def create_match(
        self,
        *,
        encounter_id: str,
        display_name: str | None,
        match_seed: str | None,
        control_modes: dict[str, str],
        maximum_rounds: int = 20,
        creation_key: str | None = None,
        setup_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .roster_selection import retired, RETIRED_MESSAGE
        catalog = self.catalog()
        accepted = catalog["encounters"][0]
        participants = (setup_binding or {}).get("participants", [])
        if any(retired(aid) for aid in [*control_modes, *(row.get('actor_id', '') for row in participants)]):
            raise self._error("COMBAT_FIGHTER_RETIRED", RETIRED_MESSAGE, subsystem="combat.gate5.catalog",
                              retry_safe=True, recommended_action="Choose a finished character.", status_code=409)
        if encounter_id != accepted["stable_id"]:
            raise self._error(
                "COMBAT_CONTENT_NOT_READY",
                "This sample match is no longer available for new fights.",
                subsystem="combat.gate5.catalog",
                retry_safe=False,
                recommended_action="Choose a current match from the fight list or set up your own teams.",
                details={"requested": encounter_id, "accepted": accepted["stable_id"]},
                status_code=409,
            )
        seed = (match_seed or f"GATE5-{secrets.token_hex(16)}").strip()
        if not seed or len(seed) > 200:
            raise self._error(
                "COMBAT_UI_DATA_INVALID",
                "The match seed must contain 1–200 characters.",
                subsystem="combat.gate5.setup",
                retry_safe=True,
                recommended_action="Use the generated seed or enter a shorter explicit seed.",
            )
        valid_actor_ids = {p["runtime_entity_id"] for p in self.catalog()["projections"] if p.get("primary_combatant")}
        supplied = set(control_modes)
        if not supplied.issubset(valid_actor_ids) or any(mode not in CONTROL_MODES for mode in control_modes.values()):
            raise self._error(
                "COMBAT_CONTROL_MODE_INVALID",
                "One or more participant control-mode assignments are invalid.",
                subsystem="combat.gate5.setup",
                retry_safe=True,
                recommended_action="Assign only catalog primary combatants to supported control modes.",
                details={"valid_actor_ids": sorted(valid_actor_ids), "supported_modes": list(CONTROL_MODES)},
            )
        setup_sha = canonical_sha256(setup_binding or {})
        if creation_key:
            for existing in self.list_matches():
                try:
                    existing_metadata = self._read_metadata(existing["match_id"])
                except Exception:
                    continue
                if existing_metadata.get("c3c_creation_key") != creation_key:
                    continue
                if existing_metadata.get("c3c_setup_binding_sha256") != setup_sha:
                    raise self._error(
                        "C3C_IDEMPOTENCY_CONFLICT",
                        "That creation key was already used for a different fight setup.",
                        subsystem="combat.c3c.creation", retry_safe=False,
                        recommended_action="Use the existing match or a new idempotency key.", status_code=409,
                    )
                return self.get_match(existing["match_id"])
        with self._timed("match_creation", threshold_ms=3000):
            try:
                participants = (setup_binding or {}).get("participants", [])
                genesis_setup = {row["actor_id"]: {"placement": row["placement"], "resources": row.get("actual_resources") or {}} for row in participants}
                roster_setup = {
                    "primary_actor_ids": [row["actor_id"] for row in participants if row.get("participant_kind") == "PRIMARY_COMBATANT"],
                    "team_by_actor": {row["actor_id"]: row["team_id"] for row in participants},
                    "starting_positions": {row["actor_id"]: row["placement"] for row in participants},
                }
                if not participants:
                    rows = catalog['projections']
                    roster_setup = {
                        'primary_actor_ids': [row['runtime_entity_id'] for row in rows
                                              if row.get('primary_combatant') and not row.get('installed_character')],
                        'team_by_actor': {row['runtime_entity_id']: row['team_id'] for row in rows
                                          if not row.get('installed_character')},
                        'starting_positions': catalog['battlefields'][0]['starting_positions'],
                    }
                runtime_docs = list((setup_binding or {}).get("portable_runtime_authorities") or [])
                if len(runtime_docs) > 1:
                    raise ValueError("C3D_P1_SINGLE_PORTABLE_RUNTIME_CANDIDATE_ONLY")
                runtime_doc = runtime_docs[0] if runtime_docs else None
                source_package = None
                if runtime_doc is not None:
                    authority = PortableRuntimeAuthority.model_validate(runtime_doc)
                    entry = self.combatant_library.candidate(authority.candidate_entry_id)
                    if entry.source_package_sha256 != authority.package_sha256 or entry.character_project_id != authority.project_id:
                        raise ValueError("C3D_INSTALLED_PACKAGE_AUTHORITY_CHANGED")
                    source_package = self.combatant_library._package_for_entry(entry)
                    rebuilt = build_runtime_authority(
                        entry, source_package,
                        qi_current=authority.bundle.resource_initialization.qi_current,
                        martial_focus_current=authority.bundle.resource_initialization.martial_focus_current,
                        provenance_id=authority.bundle.resource_initialization.provenance_id,
                    )
                    if rebuilt.authority_sha256 != authority.authority_sha256:
                        raise ValueError("C3D_PREFLIGHT_RUNTIME_AUTHORITY_STALE")
                session = self.persistence.create_match(
                    match_seed=seed, maximum_rounds=maximum_rounds,
                    genesis_setup=genesis_setup or None, roster_setup={**roster_setup, "rules": {"zero_hp": "dying_2024", "finalized_turns": "skip_finalized_v1"}},
                    runtime_authority=runtime_doc, source_package=source_package,
                )
            except (FileExistsError, CombatGate1Error, ValueError) as exc:
                diagnostic = getattr(exc, "diagnostic", None)
                diagnostic_code = getattr(diagnostic, "code", None)
                duplicate = isinstance(exc, FileExistsError) or diagnostic_code in {
                    "MATCH_LOCK_HASH_MISMATCH",
                    "MATCH_GENESIS_HASH_MISMATCH",
                }
                if duplicate and creation_key:
                    for existing in self.list_matches():
                        try:
                            metadata = self._read_metadata(existing["match_id"])
                        except Exception:
                            continue
                        if metadata.get("c3c_creation_key") == creation_key:
                            if metadata.get("c3c_setup_binding_sha256") != canonical_sha256(setup_binding or {}):
                                raise self._error(
                                    "C3C_IDEMPOTENCY_CONFLICT",
                                    "That creation key was already used for a different fight setup.",
                                    subsystem="combat.c3c.creation",
                                    retry_safe=False,
                                    recommended_action="Use the existing match or a new idempotency key.",
                                    status_code=409,
                                )
                            return self.get_match(existing["match_id"])
                raise self._error(
                    "COMBAT_UI_DATA_INVALID" if duplicate else "COMBAT_CONTENT_NOT_READY",
                    (
                        "That deterministic seed already identifies an existing match directory."
                        if duplicate
                        else "The accepted combat match could not be created from the exact bound content."
                    ),
                    subsystem="combat.gate5.setup" if duplicate else "combat.gate5.persistence",
                    retry_safe=duplicate,
                    recommended_action=(
                        "Resume the existing match from the match list or generate a new seed."
                        if duplicate
                        else "Restore the exact Gate 5 source/content checkpoint and inspect the bound-content diagnostic."
                    ),
                    details={"seed": seed, "underlying_code": diagnostic_code, "reason": str(exc)},
                    status_code=409,
                ) from exc
            modes = {actor_id: control_modes.get(actor_id, "MANUAL") for actor_id in sorted(control_modes)}
            match_visuals = self._snapshot_match_visuals(session.match_id)
            metadata = {
                "schema": INTEGRATION_SCHEMA,
                "integration_schema_version": "1.0.0",
                "match_id": session.match_id,
                "display_name": (display_name or accepted["display_name"]).strip()[:240],
                "encounter_id": accepted["stable_id"],
                "battlefield_id": accepted["battlefield_id"],
                "participant_control_modes": modes,
                "paused": False,
                "local_auto_running": False,
                "ui_preferences": {},
                "visual_assets": match_visuals,
                "c3c_creation_key": creation_key,
                "c3c_setup_binding": setup_binding,
                "c3c_setup_binding_sha256": canonical_sha256(setup_binding or {}) if setup_binding is not None else None,
                "created_at": _utcnow(),
                "updated_at": _utcnow(),
            }
            if (setup_binding or {}).get("portable_runtime_authorities"):
                metadata["c3c_preflight_commitment"] = (setup_binding or {}).get("preflight_commitment")
            try:
                self._write_metadata(session.match_id, metadata)
                if setup_binding is not None:
                    self._verify_committed_setup(session, setup_binding)
            except Exception:
                shutil.rmtree(session.store.match_dir, ignore_errors=True)
                raise
        return self._match_view(session, metadata)

    def _catalog_with_factory_fighters(self, match_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """The combat catalog plus the Factory fighters saved with this match, for display."""
        from .gate2_runtime_models import ActionDefinition
        from .gate3_storage import load_arena, load_typed_bundles

        bundles = load_typed_bundles(self._match_dir(match_id))
        if not bundles:
            return self._catalog_cache, {}
        catalog = dict(self._catalog_cache)
        arena = load_arena(self._match_dir(match_id))
        if arena:
            catalog["battlefields"] = [arena, *(catalog.get("battlefields") or [])]
        try:
            factory_match = self._read_metadata(match_id).get("factory_match") or {}
        except Exception:
            factory_match = {}
        side_a = {FACTORY_ACTOR_PREFIX + pid for pid in factory_match.get("project_ids") or []}
        catalog["projections"] = list(catalog.get("projections") or []) + [
            {"runtime_entity_id": bundle["actor_id"], "display_name": bundle["actor_template"]["display_name"],
             **({"team_id": "team:factory", "team_display_name": "Your characters", "team_index": 0}
                if bundle["actor_id"] in side_a or not side_a else
                {"team_id": "team:opponents", "team_display_name": "Opponents", "team_index": 1}),
             "primary_combatant": True, "character_sheet_identity": f"character_mapping:{bundle['actor_id']}"}
            for bundle in bundles
        ]
        actions = {row["source_definition_id"]: ActionDefinition.model_validate(row) for bundle in bundles for row in bundle["action_catalog"]}
        return catalog, actions

    def acquire_source_feature(
        self, project_id: str, *, feature_id: str, occurrence_id: str,
        access_record: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record explicit owner access through the native admission store.

        Generic prerequisite for source-owned progressions and traditions. Only
        records with a source-backed feature_admission contract are eligible;
        this API neither infers access nor substitutes for a source procedure.
        The installed package is immutable. Subsequent native compilations read
        this overlay; already sealed journeys and fights keep their bundles and
        paid balances. Duplicate admissions fail before replacing the receipt.
        """
        from copy import deepcopy
        from .source_acquisition import FIELD, SourceAcquisitionStore

        actor_id = FACTORY_ACTOR_PREFIX + project_id
        admitted = SourceAcquisitionStore(self.userdata_root).acquire(
            self._factory_owner_sheet(project_id), feature_id,
            actor_id=actor_id, occurrence_id=occurrence_id, access_record=access_record,
        )
        return deepcopy(next(row for row in admitted[FIELD] if row["feature_id"] == feature_id))

    def _factory_admission_sheet(self, project_id: str, sheet: dict[str, Any]) -> dict[str, Any]:
        """Validate and overlay source admissions on a table-projected sheet.

        Native compilation and proposed level undo share the same owner,
        source, access and acquisition-level checks. The store is authoritative;
        an invalid live entitlement must fail before growth is committed.
        """
        from .source_acquisition import SourceAcquisitionStore

        return SourceAcquisitionStore(self.userdata_root).load_into(
            sheet, actor_id=FACTORY_ACTOR_PREFIX + project_id,
        )

    def _factory_owner_sheet(self, project_id: str, *, apply_table: bool = True) -> dict[str, Any]:
        """Return the table projection, or the installed base for growth replay.

        Admissions are always validated at the current projected level. With
        ``apply_table=False``, return the base without saved growth or external
        admissions so history callers can apply growth exactly once. Ordinary
        compilation receives both overlays; sealed journeys/fights are untouched.
        """
        package = self.combatant_library.install_root / project_id / "current.zip"
        if not package.is_file() or "/" in project_id or ".." in project_id:
            raise self._error(
                "COMBAT_CONTENT_NOT_READY", "That character is not installed on this machine.",
                subsystem="combat.factory", retry_safe=False,
                recommended_action="Finalize the character first; finished characters are installed automatically.",
                details={"project_id": project_id}, status_code=404,
            )
        with zipfile.ZipFile(package) as archive:
            sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
        renamed = self._table_name(project_id)
        if renamed:
            # The owner's name for it at the table (owner 2026-09-27); the sealed package is not rewritten.
            sheet["identity"] = {**(sheet.get("identity") or {}), "display_name": renamed, "name": renamed}
        advancement = self._table_advancement(project_id)
        projected = sheet
        if advancement:
            # Spheres, talents and Forged Techniques the table added (owner 2026-09-27, combat/table_advance.py).
            from . import table_advance

            projected = table_advance.apply(sheet, advancement)
        projected = self._factory_admission_sheet(project_id, projected)
        from .table_advance import memorized

        return memorized(projected if apply_table else sheet)

    def _table_overlay_key(self, project_id: str) -> str:
        from .table_advance import overlay_key

        return overlay_key(self._table_advancement(project_id))

    def _table_advancement(self, project_id: str) -> dict[str, Any] | None:
        from .tabletop import ButtonStore, TabletopError

        try:
            return ButtonStore(self.userdata_root / "tabletop_buttons").get(project_id).get("advancement") or None
        except (TabletopError, OSError, ValueError):
            return None

    def _table_name(self, project_id: str) -> str | None:
        from .tabletop import ButtonStore, TabletopError

        try:
            return ButtonStore(self.userdata_root / "tabletop_buttons").get(project_id).get("display_name") or None
        except (TabletopError, OSError, ValueError):
            return None

    def factory_characters(self) -> list[dict[str, Any]]:
        """Installed finished characters that can be compiled into fighters.

        Each owner sheet is several megabytes, so a row is remembered per
        installed package and re-read only when that package file changes.
        Rows also carry the fighter picker's read-only card fields (paths, path,
        subpath, spheres, edited_at; combat/fighter_picker.py).
        """
        from .fighter_picker import card_fields, edited_at

        cache = self.__dict__.setdefault("_factory_character_rows", {})
        rows = []
        for pointer in sorted(self.combatant_library.install_root.glob("*/current.zip")) if self.combatant_library.install_root.is_dir() else []:
            stat = pointer.stat()
            key = (stat.st_mtime_ns, stat.st_size, self._table_name(pointer.parent.name), self._table_overlay_key(pointer.parent.name))
            cached = cache.get(pointer)
            edited = edited_at(pointer, self.userdata_root / "tabletop_buttons" / f"{pointer.parent.name}.json")
            if cached and cached[0] == key:
                rows.append({**cached[1], "paths": list(cached[1]["paths"]), "edited_at": edited})
                continue
            try:
                sheet = self._factory_owner_sheet(pointer.parent.name)
            except Exception:
                continue
            identity = sheet.get("identity") or {}
            row = {"project_id": pointer.parent.name, "actor_id": FACTORY_ACTOR_PREFIX + pointer.parent.name,
                   "display_name": identity.get("display_name") or identity.get("name") or pointer.parent.name,
                   "cultivation_level": identity.get("cultivation_level"),
                   **card_fields(sheet)}
            cache[pointer] = (key, row)
            rows.append({**row, "paths": list(row["paths"]), "edited_at": edited})
        return rows

    def factory_arenas(self, *, include_retired: bool = False) -> dict[str, dict[str, Any]]:
        """Selectable arenas, re-read so owner edits apply to the next fight.

        Shipped rule arenas use the same ``retired: true`` listing policy as
        editor maps. ``include_retired`` exposes historical rule geometry for
        sealed-fixture writers only; player catalogs and new-fight creation
        always use the default. Retirement metadata is never sealed as rules.
        Existing saves load their own sealed battlefield, not this catalog.
        """
        arenas = {}
        for path in sorted((self.source_root / FACTORY_ARENA_DIR).glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.pop("retired", False) is True and not include_retired:
                continue
            arenas[document["stable_id"]] = document
        arenas.update(self.tabletop_maps.arenas())  # owner-drawn tabletop maps (combat/tabletop.py)
        return arenas

    @property
    def tabletop_maps(self):
        from .tabletop import TabletopMapStore

        return TabletopMapStore(self.userdata_root / "combat_maps", self.source_root / "combat" / "maps")

    def create_factory_match(
        self, *, project_ids: list[str], opponent_actor_ids: list[str] | None = None,
        neutral_actor_ids: list[str] | None = None,
        control_modes: dict[str, str] | None = None, match_seed: str | None = None,
        display_name: str | None = None, maximum_rounds: int = 20, arena_id: str | None = None,
        prefight: dict[str, list[str]] | None = None,
    ) -> dict[str, Any]:
        """A fight with finished Factory characters (owner 2026-09-24: playtest combat).

        Each character is compiled from its current data, so edits to talents,
        rules or equipment show up in the next fight.  The compiled bundles are
        saved with the match, so a resumed or replayed fight uses exactly them.
        Factory fighters default to the local AI driven by their Dao policy.
        """
        from .factory_compiler import compile_character
        from .tabletop import ButtonStore, TabletopError
        from .limits import MAX_FIGHTERS_PER_SIDE

        if not project_ids:
            raise self._error("COMBAT_UI_DATA_INVALID", "Choose at least one finished character.", subsystem="combat.factory",
                              retry_safe=True, recommended_action="Pick a character from the list.")
        if len(project_ids) > MAX_FIGHTERS_PER_SIDE or len(opponent_actor_ids or [AN]) > MAX_FIGHTERS_PER_SIDE:
            raise self._error("COMBAT_UI_DATA_INVALID", f"Each team can have at most {MAX_FIGHTERS_PER_SIDE} fighters.",
                              subsystem="combat.factory", retry_safe=True,
                              recommended_action=f"Choose no more than {MAX_FIGHTERS_PER_SIDE} fighters for each team.")
        from factory_authoring.owner_items import OwnerItemStore

        given = OwnerItemStore(self.userdata_root / "owner_items")  # items the owner gave (Items tab)
        # Which Path pool pays each choosable ability (owner 2026-09-25, Q19): the sheet's saved
        # choice, applied when the fight is compiled so a new fight uses it.
        buttons = ButtonStore(self.userdata_root / "tabletop_buttons")

        def powering_of(pid: str) -> dict[str, str]:
            try:
                return buttons.get(pid).get("powering") or {}
            except TabletopError:  # a project id the button store does not recognise: no saved choice
                return {}

        def grants_of(pid: str) -> list[str] | None:
            """Spheres the owner granted this finished character for combat (owner 2026-09-26)."""
            try:
                return buttons.get(pid).get("granted_spheres") or None
            except TabletopError:
                return None

        def summons_of(pid: str) -> dict[str, Any] | None:
            """Which summoned creatures the character brings (owner 2026-09-27); None is every one it can."""
            try:
                return buttons.get(pid).get("summons") or None
            except TabletopError:
                return None

        def left_behind_of(pid: str) -> list[str] | None:
            """What the owner leaves behind for this character's fights (owner 2026-09-27, the sheet's Items tab)."""
            try:
                return buttons.get(pid).get("left_behind") or None
            except TabletopError:
                return None

        def attuned_of(pid: str) -> list[str] | None:
            """The treasures the character is attuned to (owner 2026-09-28); None is the creation plan."""
            try:
                saved = buttons.get(pid).get("attuned")
            except TabletopError:
                return None
            return saved if isinstance(saved, list) else None

        def reactions_of(pid: str) -> dict[str, Any] | None:
            """The sheet's reaction order for this character (owner 2026-09-26); None is Auto."""
            try:
                return buttons.get(pid).get("reactions") or None
            except TabletopError:
                return None

        bundles = [compile_character(self._factory_owner_sheet(pid), actor_id=FACTORY_ACTOR_PREFIX + pid,
                                     owner_items=given.items(pid), powering=powering_of(pid), reaction_plan=reactions_of(pid),
                                     granted_spheres=grants_of(pid), summon_plan=summons_of(pid), left_behind=left_behind_of(pid), attuned=attuned_of(pid))
                   for pid in project_ids]
        factory_ids = [bundle["actor_id"] for bundle in bundles]
        opponents = list(opponent_actor_ids or [AN])
        neutrals = list(neutral_actor_ids or [])
        selected = factory_ids + opponents + neutrals
        if len(set(selected)) != len(selected):
            raise self._error("COMBAT_UI_DATA_INVALID", "Choose each fighter in only one group.", subsystem="combat.factory",
                              retry_safe=True, recommended_action="Remove the duplicate fighter from a group.")
        from .roster_selection import retired, RETIRED_MESSAGE
        if any(retired(aid) for aid in opponents + neutrals):
            raise self._error("COMBAT_FIGHTER_RETIRED", RETIRED_MESSAGE, subsystem="combat.factory",
                              retry_safe=True, recommended_action="Choose a finished character.", status_code=409)
        # Opponents may be fixture fighters or other finished Factory characters.
        factory_foes = [aid for aid in opponents if aid.startswith(FACTORY_ACTOR_PREFIX) and aid not in factory_ids]
        factory_neutrals = [aid for aid in neutrals if aid.startswith(FACTORY_ACTOR_PREFIX)]
        unknown = [aid for aid in opponents + neutrals if aid not in ACTORS and aid not in factory_foes + factory_neutrals]
        if unknown:
            raise self._error("COMBAT_UI_DATA_INVALID", "An opponent is not a known fighter.", subsystem="combat.factory",
                              retry_safe=True, recommended_action="Choose opponents from the combat catalog or your finished characters.",
                              details={"unknown": unknown})
        bundles += [compile_character(self._factory_owner_sheet(aid[len(FACTORY_ACTOR_PREFIX):]), actor_id=aid,
                                      owner_items=given.items(aid[len(FACTORY_ACTOR_PREFIX):]),
                                      powering=powering_of(aid[len(FACTORY_ACTOR_PREFIX):]),
                                      reaction_plan=reactions_of(aid[len(FACTORY_ACTOR_PREFIX):]),
                                      granted_spheres=grants_of(aid[len(FACTORY_ACTOR_PREFIX):]),
                                      summon_plan=summons_of(aid[len(FACTORY_ACTOR_PREFIX):]),
                                      left_behind=left_behind_of(aid[len(FACTORY_ACTOR_PREFIX):]), attuned=attuned_of(aid[len(FACTORY_ACTOR_PREFIX):])) for aid in factory_foes + factory_neutrals]
        if len(bundles) > 1:
            # A fighter can fight with a weapon it takes from another (owner 2026-09-26): a second pass compiles the
            # others' weapons into each bundle, offered only while it holds one.
            def with_held(bundle: dict[str, Any]) -> dict[str, Any]:
                pid = bundle["actor_id"][len(FACTORY_ACTOR_PREFIX):]
                others = [row for other in bundles if other is not bundle for row in other.get("weapons") or []]
                return compile_character(self._factory_owner_sheet(pid), actor_id=bundle["actor_id"], owner_items=given.items(pid),
                                         powering=powering_of(pid), reaction_plan=reactions_of(pid), held_weapons=others,
                                         granted_spheres=grants_of(pid), summon_plan=summons_of(pid), left_behind=left_behind_of(pid), attuned=attuned_of(pid))
            bundles = [with_held(bundle) for bundle in bundles]
        bundles = [self._with_prefight(bundle, prefight) for bundle in bundles]
        primary = factory_ids + opponents + neutrals
        from .relations import NEUTRAL_TEAM
        teams = {**{aid: "team:factory" for aid in factory_ids}, **{aid: "team:opponents" for aid in opponents},
                 **{aid: NEUTRAL_TEAM for aid in neutrals}}
        seed = (match_seed or f"FACTORY-{secrets.token_hex(12)}").strip()[:200]
        from .gate2_grid import SquareGrid

        arenas = self.factory_arenas()
        arena = arenas.get(arena_id or DEFAULT_FACTORY_ARENA)
        if arena is None:
            raise self._error("COMBAT_UI_DATA_INVALID", "That arena is not available.", subsystem="combat.factory",
                              retry_safe=True, recommended_action="Choose one of the listed arenas.", details={"arenas": sorted(arenas)})
        grid = SquareGrid(arena)
        team_starts = arena.get("team_starts")
        if team_starts:  # tabletop maps say where each side starts
            positions = {}
            taken: set[tuple[int, int]] = set()
            team1_spots = [(int(spot["x"]), int(spot["y"])) for spot in team_starts.get("team1") or []]
            team2_spots = [(int(spot["x"]), int(spot["y"])) for spot in team_starts.get("team2") or []]
            # Compare positions, not totals: owner maps may have unequal start counts.
            team1_x = sum(x for x, _ in team1_spots) / len(team1_spots) if team1_spots else 0
            team2_x = sum(x for x, _ in team2_spots) / len(team2_spots) if team2_spots else grid.width - 1
            team1_direction = "west" if team1_x <= team2_x else "east"
            for side, ids, spots, direction in (("team1", factory_ids, team1_spots, team1_direction),
                                                 ("team2", opponents, team2_spots,
                                                  "east" if team1_direction == "west" else "west"),
                                              ("neutral", neutrals, [(int(p["x"]), int(p["y"])) for p in team_starts.get("neutral") or []], "neutral")):
                # Extra fighters begin beside their side's printed spots, behind
                # its front spot, on open ground that fits their full footprint.
                front_x = (max(x for x, _ in spots) if direction == "west" else min(x for x, _ in spots)) if spots and side != "neutral" else None
                for index, aid in enumerate(ids):
                    bundle = next((bundle for bundle in bundles if bundle["actor_id"] == aid), None)
                    footprint = self._actor_footprint_size(aid, bundle)
                    wanted = spots[index] if index < len(spots) else None
                    spot = self._free_spot(grid, wanted, taken, footprint=footprint, team_spots=spots,
                                           side=direction, front_x=front_x if wanted is None else None)
                    if spot is None:
                        self._refuse_crowded_setup(arena, len(ids), 1 if side == "team1" else 2)
                    taken.update((spot[0] + dx, spot[1] + dy) for dx in range(footprint) for dy in range(footprint))
                    positions[aid] = {"x": spot[0], "y": spot[1]}
            return self._finish_factory_match(bundles, primary, teams, positions, arena, factory_ids, opponents,
                                              control_modes=control_modes, match_seed=match_seed, display_name=display_name,
                                              maximum_rounds=maximum_rounds)
        fixture_positions = {aid: (spot.x, spot.y) for aid, spot in grid.starting_positions.items() if aid in opponents}
        occupied: set[tuple[int, int]] = set()
        for aid, pos in fixture_positions.items():
            bundle = next((row for row in bundles if row["actor_id"] == aid), None)
            size = self._actor_footprint_size(aid, bundle)
            occupied.update((pos[0] + dx, pos[1] + dy) for dx in range(size) for dy in range(size))
        midpoint = grid.width // 2
        west_spots = [(spot.x, spot.y) for spot in grid.starting_positions.values() if spot.x < midpoint]
        east_spots = [(spot.x, spot.y) for spot in grid.starting_positions.values() if spot.x >= midpoint]
        foes_west = sum(x < midpoint for x, _ in fixture_positions.values())
        foes_east = len(fixture_positions) - foes_west
        team1_direction = "east" if foes_west > foes_east else "west"
        team1_spots, team2_spots = ((east_spots, west_spots) if team1_direction == "east" else (west_spots, east_spots))
        # Preserve the original sorted/farthest selection for printed starts.
        foes = [grid.starting_positions[aid] for aid in opponents if aid in grid.starting_positions]
        spare = [grid.starting_positions[aid] for aid in sorted(grid.starting_positions) if aid not in opponents]
        if foes:
            spare.sort(key=lambda spot: -min(abs(spot.x - foe.x) + abs(spot.y - foe.y) for foe in foes))
        else:
            spare.sort(key=lambda spot: (spot.x, spot.y))
        if len(factory_ids) + len(factory_foes) <= len(spare):
            team1_spots = [(spot.x, spot.y) for spot in spare[:len(factory_ids)]]
            team2_spots = [(spot.x, spot.y) for spot in reversed(spare[-len(factory_foes):])] if factory_foes else []
        else:
            team1_spots = [(spot.x, spot.y) for spot in spare if (spot.x, spot.y) in team1_spots]
            team2_spots = [(spot.x, spot.y) for spot in reversed(spare) if (spot.x, spot.y) in team2_spots]
        # Built-in arenas store a small set of example starts; additional fighters
        # use nearby legal squares behind their side's front-most example start.
        positions = {}
        for team_number, (side, ids, spots, front_x) in enumerate((
            (team1_direction, factory_ids, team1_spots,
             (min if team1_direction == "east" else max)((x for x, _ in team1_spots), default=None)),
            ("east" if team1_direction == "west" else "west", factory_foes, team2_spots,
             (min if team1_direction == "west" else max)((x for x, _ in team2_spots), default=None)),
        ), 1):
            for index, aid in enumerate(ids):
                size = self._bundle_footprint(next(row for row in bundles if row["actor_id"] == aid))
                wanted = spots[index] if index < len(spots) else None
                spot = self._free_spot(grid, wanted, occupied, footprint=size, team_spots=spots,
                                       side=side, front_x=front_x if wanted is None else None)
                if spot is None:
                    self._refuse_crowded_setup(arena, len(ids), team_number)
                occupied.update((spot[0] + dx, spot[1] + dy) for dx in range(size) for dy in range(size))
                positions[aid] = {"x": spot[0], "y": spot[1]}
        for aid in neutrals:
            bundle = next((row for row in bundles if row["actor_id"] == aid), None)
            size = self._actor_footprint_size(aid, bundle)
            spot = self._free_spot(grid, (grid.width // 2, grid.height // 2), occupied, footprint=size)
            if spot is None:
                raise ValueError('There is no free starting space for a neutral fighter.')
            occupied.update((spot[0] + dx, spot[1] + dy) for dx in range(size) for dy in range(size))
            positions[aid] = {'x': spot[0], 'y': spot[1]}
        return self._finish_factory_match(bundles, primary, teams, positions, arena, factory_ids, opponents,
                                          control_modes=control_modes, match_seed=match_seed, display_name=display_name,
                                          maximum_rounds=maximum_rounds)

    def _refuse_crowded_setup(self, arena: dict[str, Any], count: int, team_number: int) -> None:
        """Refuse incomplete setup before the engine or persistence sees it."""
        name = arena.get("display_name") or "this map"
        raise self._error("COMBAT_SETUP_NO_ROOM", f"Not enough room on {name} for {count} fighters on Team {team_number}",
                          subsystem="combat.factory", retry_safe=True, status_code=422,
                          recommended_action="Choose a larger map or fewer fighters.")

    @staticmethod
    def _free_spot(grid, wanted: tuple[int, int] | None, taken: set[tuple[int, int]], footprint: int = 1,
                   team_spots: list[tuple[int, int]] | None = None, side: str = "team1",
                   front_x: int | None = None) -> tuple[int, int] | None:
        """Pick a deterministic legal square beside a side's start spots."""
        def free(x: int, y: int) -> bool:
            occupied = {(x + dx, y + dy) for dx in range(footprint) for dy in range(footprint)}
            behind_front = front_x is None or (x + footprint - 1 <= front_x if side == "west" else x >= front_x)
            return behind_front and all(0 <= cx < grid.width and 0 <= cy < grid.height
                                        and (cx, cy) not in grid.blocked and (cx, cy) not in grid.qi_hazard
                                        and (cx, cy) not in taken for cx, cy in occupied)
        cells = [(x, y) for y in range(grid.height) for x in range(grid.width) if free(x, y)]
        if not cells:
            return None
        if wanted is None:
            anchors = team_spots or []
            return min(cells, key=lambda cell: (min((abs(cell[0] - sx) + abs(cell[1] - sy) for sx, sy in anchors), default=0), cell[1], cell[0]))
        return min(cells, key=lambda cell: (abs(cell[0] - wanted[0]) + abs(cell[1] - wanted[1]), cell[1], cell[0]))

    def _bundle_footprint(self, bundle: dict[str, Any]) -> int:
        """Return the square width needed by this compiled or catalog fighter."""
        return self._actor_footprint_size(str(bundle["actor_id"]), bundle)

    def _actor_footprint_size(self, actor_id: str, _bundle: dict[str, Any] | None = None) -> int:
        if actor_id.startswith(FACTORY_ACTOR_PREFIX):
            sheet = self._factory_owner_sheet(actor_id[len(FACTORY_ACTOR_PREFIX):])
            size = str((sheet.get("identity") or {}).get("size") or "").strip().lower()
            owner_size = {"large": 2, "huge": 3, "gargantuan": 4}.get(size)
            if owner_size:
                return owner_size
        definition, _ = resolve_actor_footprint(actor_id if actor_id in ACTORS else AN)
        return max(definition.width_cells, definition.height_cells)

    def _with_prefight(self, bundle: dict[str, Any], requested: dict[str, list[str]] | None) -> dict[str, Any]:
        """Its buffs cast before the fight (owner 2026-09-29, combat/prefight.py): the player's picks (by actor or project
        id), else the AI's best two. The Meld it would otherwise have started with gives way to the chosen ones."""
        from . import concentration, prefight, senses
        from .canonical import canonical_sha256

        offered = (bundle.get("prefight") or {}).get("options") or []
        # Match combat admission: sealed rules, or the original CL ceiling for
        # older bundles without a snapshot, independent of today's rules file.
        configured = concentration.rules_for_bundle(bundle)
        holds = concentration.selection_limit(int(bundle.get("cl") or 1), prefight.MAX_PICKS, configured)
        pid = bundle["actor_id"][len(FACTORY_ACTOR_PREFIX):]
        wanted = (requested or {}).get(bundle["actor_id"], (requested or {}).get(pid))
        has_request = wanted is not None
        wanted = list(wanted or [])
        setup_choices = {}
        setup_prefix = "setup-choice:"
        for item in wanted:
            if isinstance(item, str) and item.startswith(setup_prefix):
                key, separator, value = item[len(setup_prefix):].partition(":")
                if not separator or not key or key in setup_choices:
                    raise self._error("COMBAT_UI_DATA_INVALID", "A pre-fight setup choice is malformed or repeated.",
                                      subsystem="combat.factory", retry_safe=True,
                                      recommended_action="Choose each setup value once using the displayed controls.")
                setup_choices[key] = value
        wanted = [item for item in wanted if not (isinstance(item, str) and item.startswith(setup_prefix))]
        pools = prefight.starting_pools(bundle)
        if not has_request:
            picks = prefight.choose(offered, pools, list((senses.rules().get("melds") or {}).get("talents") or []), holds)
        else:
            try:
                picks = prefight.validate(list(wanted), offered, pools, holds)
            except ValueError as exc:
                name = (bundle.get("actor_template") or {}).get("display_name") or pid
                raise self._error("COMBAT_UI_DATA_INVALID", f"{name}: {exc}", subsystem="combat.factory", retry_safe=True,
                                  recommended_action="Choose at most two buffs the character can pay for and hold Concentration on.")
        from .ext import query as extension_query
        declarations = [row for result in extension_query("prefight_setup_choices", bundle) or []
                        for row in (result if isinstance(result, list) else [])]
        sealed_choices = {}
        valid_ids = set()
        for declaration in declarations:
            if not isinstance(declaration, dict) or declaration.get("kind") != "integer_range_list":
                raise ValueError("Invalid pre-fight setup choice declaration")
            key = declaration.get("id")
            count, minimum, maximum = (int(declaration.get(name)) for name in ("count", "minimum", "maximum"))
            if not isinstance(key, str) or not key or key in valid_ids or count < 0 or minimum > maximum:
                raise ValueError("Invalid pre-fight setup choice declaration")
            valid_ids.add(key)
            raw = setup_choices.pop(key, None)
            try:
                values = list(declaration.get("default") or []) if raw is None else ([int(value) for value in raw.split(",")] if raw else [])
            except ValueError:
                values = []
            if len(values) != count or any(value < minimum or value > maximum for value in values):
                label = declaration.get("label") or "this setup choice"
                raise self._error("COMBAT_UI_DATA_INVALID", f"Choose a valid value for {label}.",
                                  subsystem="combat.factory", retry_safe=True,
                                  recommended_action="Choose values within the displayed range.")
            sealed_choices[key] = values
        if setup_choices:
            raise self._error("COMBAT_UI_DATA_INVALID", "A pre-fight setup choice is not available for this fighter.",
                              subsystem="combat.factory", retry_safe=True,
                              recommended_action="Choose the fighter again to refresh the available setup choices.")
        out = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
        out["prefight"] = {**(bundle.get("prefight") or {"options": []}), "picks": picks, "chosen": True}
        if sealed_choices:
            out["prefight"]["setup_choices"] = sealed_choices
        if out.get("senses"):
            out["senses"] = {**out["senses"], "meld_start": None}
        out["bundle_sha256"] = canonical_sha256(out)
        return out

    def factory_prefight_options(self, project_id: str) -> dict[str, Any]:
        """What a character may start a fight with, and what the AI would pick (the fight setup's checklist)."""
        from factory_authoring.owner_items import OwnerItemStore

        from . import concentration, prefight, senses
        from .factory_compiler import compile_character
        from .tabletop import ButtonStore, TabletopError

        try:
            saved = ButtonStore(self.userdata_root / "tabletop_buttons").get(project_id)
        except (TabletopError, OSError, ValueError):
            saved = {}
        bundle = compile_character(self._factory_owner_sheet(project_id), actor_id=FACTORY_ACTOR_PREFIX + project_id,
                                   owner_items=OwnerItemStore(self.userdata_root / "owner_items").items(project_id),
                                   powering=saved.get("powering") or {}, reaction_plan=saved.get("reactions") or None,
                                   granted_spheres=saved.get("granted_spheres") or None, summon_plan=saved.get("summons") or None,
                                   left_behind=saved.get("left_behind") or None,
                                   attuned=saved.get("attuned") if isinstance(saved.get("attuned"), list) else None)
        offered = (bundle.get("prefight") or {}).get("options") or []
        holds = concentration.selection_limit(int(bundle.get("cl") or 1), prefight.MAX_PICKS,
                                              concentration.rules_for_bundle(bundle))
        from .ext import query as extension_query
        setup_choices = [row for result in extension_query("prefight_setup_choices", bundle) or []
                         for row in (result if isinstance(result, list) else [])]
        return {"project_id": project_id, "actor_id": bundle["actor_id"], "max": prefight.MAX_PICKS, "max_concentration": holds, "options": offered,
                "setup_choices": setup_choices,
                "picks": prefight.choose(offered, prefight.starting_pools(bundle), list((senses.rules().get("melds") or {}).get("talents") or []), holds),
                "pools": prefight.starting_pools(bundle)}

    def _finish_factory_match(self, bundles, primary, teams, positions, arena, factory_ids, opponents, *, control_modes,
                              match_seed, display_name, maximum_rounds) -> dict[str, Any]:
        from .settings_service import presets_for_roster
        presets = presets_for_roster(self, primary)
        seed = (match_seed or f"FACTORY-{secrets.token_hex(12)}").strip()[:200]
        session = self.persistence.create_match(
            match_seed=seed, maximum_rounds=maximum_rounds,
            roster_setup={"primary_actor_ids": primary, "team_by_actor": teams, "starting_positions": positions,
                          **({"settings_presets_v1": presets} if presets else {}),
                          "rules": {"zero_hp": "dying_2024", "finalized_turns": "skip_finalized_v1"},
                          "participant_control_modes": {aid: (control_modes or {}).get(aid, "LOCAL_AUTO") for aid in primary}},
            typed_bundles=tuple(bundles), battlefield=arena,
        )
        modes = {aid: (control_modes or {}).get(aid, "LOCAL_AUTO") for aid in primary}
        if any(mode not in CONTROL_MODES for mode in modes.values()):
            raise self._error("COMBAT_CONTROL_MODE_INVALID", "A control mode is not supported.", subsystem="combat.factory",
                              retry_safe=True, recommended_action="Use one of the supported control modes.", details={"supported": list(CONTROL_MODES)})
        accepted = self._catalog_cache["encounters"][0]
        names = [bundle["actor_template"]["display_name"] for bundle in bundles]
        metadata = {
            "schema": INTEGRATION_SCHEMA,
            "integration_schema_version": "1.0.0",
            "match_id": session.match_id,
            "display_name": (display_name or f"{' & '.join(names)} — test fight").strip()[:240],
            "encounter_id": accepted["stable_id"],
            "battlefield_id": arena["stable_id"],
            "participant_control_modes": modes,
            "paused": False,
            "local_auto_running": False,
            "ui_preferences": {},
            "visual_assets": self._snapshot_match_visuals(session.match_id),
            "factory_match": {
                "project_ids": [aid[len(FACTORY_ACTOR_PREFIX):] for aid in factory_ids],
                "bundles": [{"actor_id": b["actor_id"], "bundle_sha256": b["bundle_sha256"],
                             "typed_authority_sha256": b["typed_authority_sha256"], "diagnostics": b["diagnostics"]} for b in bundles],
            },
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
        }
        try:
            self._write_metadata(session.match_id, metadata)
        except Exception:
            shutil.rmtree(session.store.match_dir, ignore_errors=True)
            raise
        return self._match_view(session, metadata)

    def _verify_committed_setup(self, session: Gate4PersistentSession, setup_binding: dict[str, Any]) -> None:
        for row in setup_binding.get("participants", []):
            actor = session.engine.state.actors[row["actor_id"]]
            if actor.position.model_dump(mode="json") != row["placement"]:
                raise ValueError(f"C3C_GENESIS_COMMITMENT_MISMATCH:{actor.entity_id}:placement")
            for resource_id, expected in (row.get("actual_resources") or {}).items():
                if actor.resources.get(resource_id) != expected:
                    raise ValueError(f"C3C_GENESIS_COMMITMENT_MISMATCH:{actor.entity_id}:{resource_id}")
        battlefield = self._catalog_cache["battlefields"][0]
        if setup_binding.get("battlefield", {}).get("stable_id") != battlefield["stable_id"]:
            raise ValueError("C3C_GENESIS_COMMITMENT_MISMATCH:battlefield")
        expected_calibration = {"mode": "AUTHORITATIVE_GATE2_GRID", "width": battlefield["width_squares"], "height": battlefield["height_squares"], "square_size_ft": battlefield["square_size_ft"], "centered_tokens": True}
        if setup_binding.get("grid_calibration") != expected_calibration:
            raise ValueError("C3C_GENESIS_COMMITMENT_MISMATCH:grid_calibration")
        for row in setup_binding.get("participants", []):
            if row.get("installed_character"):
                from .footprints import standard_actor_footprint
                definition = standard_actor_footprint().model_copy(update={
                    "footprint_id": f"footprint:{row['actor_id']}.1x1",
                    "source_definition_id": f"system:combat.actor_footprint:{row['actor_id']}",
                })
            else:
                definition, _ = resolve_actor_footprint(row["actor_id"])
            expected_fp = {"footprint_id": definition.footprint_id, "width": definition.width_cells, "height": definition.height_cells}
            if row.get("footprint") != expected_fp:
                raise ValueError(f"C3C_GENESIS_COMMITMENT_MISMATCH:{row['actor_id']}:footprint")
            if row.get("token_asset_id") != row.get("character_sheet_identity"):
                raise ValueError(f"C3C_GENESIS_COMMITMENT_MISMATCH:{row['actor_id']}:token")
        metadata = self._read_metadata(session.match_id, session)
        if metadata.get("c3c_setup_binding_sha256") != canonical_sha256(setup_binding):
            raise ValueError("C3C_GENESIS_COMMITMENT_MISMATCH:metadata")

    def _unreadable_save_name(self, match_id: str) -> str:
        """A plain name for a saved fight that cannot be opened; never its internal ID."""
        saved = self._saved_metadata_display_name(match_id)
        if saved:
            return saved
        date = self._saved_match_date(match_id)
        return f"Unreadable older fight (saved {date})" if date else "Unreadable older fight"

    def _saved_metadata_display_name(self, match_id: str) -> str | None:
        """The saved fight's own name from its integration metadata, if readable."""
        try:
            path = self._metadata_path(match_id)
            if not path.is_file() or path.is_symlink():
                return None
            document = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        name = document.get("display_name") if isinstance(document, dict) else None
        name = name.strip() if isinstance(name, str) else ""
        if name and name != match_id and not name.startswith("match:"):
            return name
        return None

    def _saved_match_date(self, match_id: str) -> str | None:
        """A plain saved date (YYYY-MM-DD) for a fight that cannot be opened, or None."""
        try:
            path = self._metadata_path(match_id)
            if path.is_file() and not path.is_symlink():
                document = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(document, dict):
                    for key in ("created_at", "updated_at"):
                        value = document.get(key)
                        if isinstance(value, str) and len(value) >= 10:
                            return value[:10]
        except Exception:
            pass
        try:
            return datetime.fromtimestamp(self._match_dir(match_id).stat().st_mtime, timezone.utc).date().isoformat()
        except Exception:
            return None

    def list_matches(self) -> list[dict[str, Any]]:
        rows = []
        for row in self.persistence.list_matches():
            try:
                metadata = ({} if row.get("status") == "UNSUPPORTED"
                            else self._read_metadata(row["match_id"]))
            except CombatServiceError as exc:
                metadata = {"paused": False, "diagnostic": exc.diagnostic.as_dict()}
                if exc.diagnostic.code == UNSUPPORTED_CODE:
                    row = {**row, "status": "UNSUPPORTED", "unavailable_message": UNSUPPORTED_MESSAGE}
            if row.get("status") == "UNSUPPORTED":
                # A save the player cannot open is still theirs to keep or delete;
                # name it plainly instead of exposing the internal logical ID.
                metadata.setdefault("display_name", self._unreadable_save_name(row["match_id"]))
            else:
                metadata.setdefault("display_name", row["match_id"])
            rows.append({**row, **{k: metadata.get(k) for k in ("display_name", "encounter_id", "paused", "participant_control_modes",
                                                                       "created_at", "updated_at")}, "last_played_at": self._last_played_at(row["match_id"], metadata)})
        return sort_matches_newest_first(rows)

    def _last_played_at(self, match_id: str, metadata: dict[str, Any]) -> str | None:
        """When the fight was last played: the newest journal write (one stat each, no parse), else updated_at, else created_at."""
        stamps: list[float] = []
        try:
            match_dir = self._match_dir(match_id)
        except CombatServiceError:
            match_dir = None
        for name in ("Journal.ndjson", "ControllerJournal.ndjson") if match_dir is not None else ():
            path = match_dir / name
            try:
                if path.is_file() and not path.is_symlink():
                    stamps.append(path.stat().st_mtime)
            except OSError:
                continue
        if stamps:
            return _iso_utc(max(stamps))
        return metadata.get("updated_at") or metadata.get("created_at")

    def get_match(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        metadata = self._read_metadata(match_id, session)
        return self._match_view(session, metadata)

    def _controller_rows(self, session: Gate4PersistentSession, limit: int = 12) -> list[dict[str, Any]]:
        from .journal_reads import read_tail

        return read_tail(session.controller_journal_path, limit)

    def _match_view(self, session: Gate4PersistentSession, metadata: dict[str, Any]) -> dict[str, Any]:
        from .ai_tiers import effective_tier
        from .zones import on_current_map
        state = session.engine.state
        actors = []
        initiative_index = {actor_id: index for index, actor_id in enumerate(state.initiative_order)}
        for actor in sorted(
            state.actors.values(),
            key=lambda row: (initiative_index.get(row.entity_id, len(initiative_index)), row.entity_id),
        ):
            actors.append({
                **actor.model_dump(mode="json"),
                "control_mode": self._mode_for_actor(metadata, session, actor.entity_id),
                "ai_tier": effective_tier(actor, metadata.get("ai_tiers")),
                "condition_ids": sorted(condition.condition_id for condition in actor.conditions.values()),
            })
        return {
            "schema": "TianxiaFactoryCombatMatchView.v1",
            "match_id": session.match_id,
            "metadata": metadata,
            "state": {
                "match_seed": state.match_seed,
                "round_number": state.round_number,
                "current_slot_index": state.current_slot_index,
                "current_actor_id": state.current_actor_id,
                "initiative_order": list(state.initiative_order),
                "state_version": state.state_version,
                "event_sequence": state.event_sequence,
                "roll_counter": state.roll_counter,
                "terminal_result": state.terminal_result.model_dump(mode="json") if state.terminal_result else None,
                "actors": actors,
                "zones": [_zone_row(zone, session.engine)
                          for zone in sorted(state.zones.values(), key=lambda z: z.zone_id)
                          if on_current_map(session.engine, zone)],
                "pending_resolution": state.pending_resolution.model_dump(mode="json") if state.pending_resolution else None,
            },
            "recent_events": [event.model_dump(mode="json") for event in session.engine.events[-40:]],
            "controller_records": self._controller_rows(session),
            "final_summary": self.final_summary(session.match_id, session=session) if state.terminal_result is not None else None,
            "diagnostics": session.diagnostics,
        }

    def set_controller_mode(self, match_id: str, *, actor_id: str, controller_mode: str, ai_tier: str | None = None) -> dict[str, Any]:
        from .ai_tiers import TIERS
        if ai_tier is not None and ai_tier not in TIERS:
            raise ValueError("Choose Tricky or Mastermind AI.")
        if controller_mode not in CONTROL_MODES:
            raise self._error("COMBAT_CONTROL_MODE_INVALID", "The requested controller mode is unsupported.", subsystem="combat.gate5.controller", retry_safe=True, recommended_action="Choose a supported controller mode.")
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error("COMBAT_MATCH_ALREADY_COMPLETE", "Controller modes cannot be changed after the fight is complete.", subsystem="combat.gate5.controller", retry_safe=False, recommended_action="Inspect the final summary, verify, replay, or export.", match_id=match_id, status_code=409)
        if actor_id not in session.engine.state.actors or not session.engine.state.actors[actor_id].primary_combatant:
            raise self._error("COMBAT_CONTROL_MODE_INVALID", "The requested fighter cannot receive an owner controller assignment.", subsystem="combat.gate5.controller", retry_safe=True, recommended_action="Choose one of the primary fighters in this fight.")
        metadata = self._read_metadata(match_id, session)
        modes = dict(metadata.get("participant_control_modes") or {})
        modes[actor_id] = controller_mode
        if ai_tier is not None:
            metadata["ai_tiers"] = {**metadata.get("ai_tiers", {}), actor_id: ai_tier}
        metadata["participant_control_modes"] = modes
        metadata["updated_at"] = _utcnow()
        # Disk first: a failed write must not leave this session's engine ahead of the saved metadata.
        self._write_metadata(match_id, metadata)
        if ai_tier is not None:
            session.engine.ai_tier_overrides = dict(metadata["ai_tiers"])
        session.engine.typed_control_modes = dict(modes)
        return self._match_view(session, metadata)

    def pause(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error("COMBAT_MATCH_ALREADY_COMPLETE", "A completed fight is read-only and cannot be paused.", subsystem="combat.gate5.persistence", retry_safe=False, recommended_action="Inspect the final summary, verify, replay, or export.", match_id=match_id, status_code=409)
        metadata = self._read_metadata(match_id, session)
        metadata.update({"paused": True, "local_auto_running": False})
        self._write_metadata(match_id, metadata)
        return self._match_view(session, metadata)

    def resume(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error("COMBAT_MATCH_ALREADY_COMPLETE", "A completed fight is read-only and cannot be resumed.", subsystem="combat.gate5.persistence", retry_safe=False, recommended_action="Inspect the final summary, verify, replay, snapshot, or export.", match_id=match_id, status_code=409)
        metadata = self._read_metadata(match_id, session)
        metadata.update({"paused": False, "local_auto_running": False})
        self._write_metadata(match_id, metadata)
        return self._match_view(session, metadata)

    # ------------------------------------------------------------------
    # Decision and validation
    # ------------------------------------------------------------------
    def _decision_model(self, session: Gate4PersistentSession, *, candidates=None, policy=None):
        """Build the server's typed player context without a JSON round-trip.

        Shared by menu, preview and commit. This uses the existing read-only
        candidate scope; native execution still validates legality. The model
        is call-local, while public responses retain their detached JSON copies.
        No client context or newly persisted authority is accepted here.
        """
        if session.engine.state.terminal_result is not None:
            raise self._error(
                "COMBAT_MATCH_ALREADY_COMPLETE",
                "The combat match is complete and has no further decision context.",
                subsystem="combat.gate5.decision", retry_safe=False,
                recommended_action="Use verify, replay, or export for the completed match.",
                match_id=session.match_id, status_code=409,
            )
        if candidates is None:
            candidates = self._legal_candidates(session)
        if not candidates:
            raise self._error(
                "COMBAT_CONTENT_NOT_READY", "The engine produced no legal decision candidates.",
                subsystem="combat.gate5.decision", retry_safe=False,
                recommended_action="Inspect the exact match state and Gate 2 legality diagnostics.",
                match_id=session.match_id, status_code=409,
            )
        if policy is None:
            policy, _ = self.policies.for_actor(candidates[0].actor_id)
        return build_decision_context(session.engine, policy, include_item_actions=True,
                                      prepared_candidates=candidates)

    def ai_decision_context(self, session: Gate4PersistentSession, *, progress_guard: bool = False):
        """Detached complete AI context, shared by ranking, suggestions and Auto.

        The saved-state fingerprint binds geometry, catalog and journal; control
        modes, viewer and policy bind this projection. Player and observed
        generation stay separate because remembered area placements can differ.
        A moved/unbound session computes afresh. No runtime method replacement,
        no truncated menu and no cached execution authority.
        ``progress_guard=True`` is Local Auto's existing failed-action policy;
        suggestions/model ranking preserve their full native context instead.
        """
        actor_id = (session.engine.state.pending_resolution.actor_id
                    if session.engine.state.pending_resolution else session.engine.state.current_actor_id)
        policy, _ = self.policies.for_actor(actor_id)
        name = ('ai_context', actor_id, progress_guard, canonical_sha256(policy.model_dump(mode='json')))
        key = self._state_key(session)
        hit = self._derived_get(key, name) if key is not None else None
        if hit is not None:
            return hit.model_copy(deep=True)
        candidates = self._legal_candidates(session, knowledge_only=True, progress_guard=progress_guard)
        known = self._derived_get(key, 'observed_roster') if key is not None else None
        context = build_decision_context(session.engine, policy, for_ai=True,
                                         prepared_candidates=candidates, known_actors=known)
        if key is not None:
            self._derived_put(key, name, context.model_copy(deep=True))
        return context

    def menu_ranking_context(self, session: Gate4PersistentSession):
        """The production observed decision context for table scores, once per boundary.

        Table scores must come from exactly the context a built-in AI decision
        uses, so the two can never disagree about a candidate, a score or an
        option. That includes the engine's lazy square-picker roots: the table
        offers the same picker, and its concrete cells stay reachable through
        cells()/exact() as before. A cold boundary therefore builds the same
        query the AI path does; a warm one reuses the already generated
        observed query without reopening it. The complete fingerprint
        invalidates on journal, geometry, catalog, control or unversioned state
        changes. Returns a detached model; never accepts pre-commit choices as
        authority.
        """
        key = self._state_key(session)
        policy, _ = self.policies.for_actor(session.engine.state.current_actor_id)
        name = ('menu_ranking_context', canonical_sha256(policy.model_dump(mode='json')))
        hit = self._derived_get(key, name) if key is not None else None
        if hit is not None:
            return hit.model_copy(deep=True)
        prepared = self._derived_get(key, 'observed_query') if key is not None else None
        if prepared is None:
            from .candidate_knowledge import query
            from .placement_menu import query as placement_query
            with query(session.engine), placement_query():
                candidates = tuple(session.engine.legal_candidates())
        else:
            candidates = prepared[0]
        context = build_decision_context(session.engine, policy, for_ai=True,
                                         prepared_candidates=candidates)
        # Human menus keep their established ordering; difficulty tiers change
        # built-in turn selection, not the option a player reaches by name.
        context = context.model_copy(update={"tactics": {}})
        if key is not None:
            self._derived_put(key, name, context.model_copy(deep=True))
        return context

    def decision(self, match_id: str, *, session: Gate4PersistentSession | None = None,
                 table_header: bool = False) -> dict[str, Any]:
        """Return the full player context, or an automatic table's read-only header.

        ``session`` is the caller's unchanged loaded session. ``table_header``
        projects only an ordinary nonmanual menu with one native actor/decision
        identity and an issued End Turn. Native enumeration still runs for
        availability and the next AI step; no legality work moves out of the
        turn. Manual, setup, pending and unusual menus keep the full context.
        This projection issues no candidates or execution authority.
        """
        with self._timed("decision_context", threshold_ms=2000):
            if session is None:
                session = self._load_session(match_id)
            if session.engine.state.terminal_result is not None:
                raise self._error(
                    "COMBAT_MATCH_ALREADY_COMPLETE",
                    "The combat match is complete and has no further decision context.",
                    subsystem="combat.gate5.decision",
                    retry_safe=False,
                    recommended_action="Use verify, replay, or export for the completed match.",
                    match_id=match_id,
                    status_code=409,
                )
            candidates = self._legal_candidates(session)
            if not candidates:
                raise self._error(
                    "COMBAT_CONTENT_NOT_READY",
                    "The engine produced no legal decision candidates.",
                    subsystem="combat.gate5.decision",
                    retry_safe=False,
                    recommended_action="Inspect the exact match state and Gate 2 legality diagnostics.",
                    match_id=match_id,
                    status_code=409,
                )
            actor_id = candidates[0].actor_id
            policy, fallback = self.policies.for_actor(actor_id)
            # The player's menu, also read by an API or clipboard AI pilot: it may drop and pick up items (owner 2026-09-27).
            # The built-in AI's contexts (for_ai) never offer them: "the default in game ai doesnt need it".
            key = self._state_key(session)
            from . import movement_menu
            context_key = 'decision_context_table' if movement_menu.active() else 'decision_context'
            from . import lazy_menu
            if movement_menu.active() and lazy_menu.active(session.engine):
                context_key += '_lazy'
            cached = self._derived_get(key, context_key) if key is not None else None
            metadata = self._read_metadata(match_id, session) if table_header else None
            control_mode = self._mode_for_actor(metadata, session, actor_id) if metadata is not None else None
            first = candidates[0]
            compact = (table_header and control_mode not in MANUAL_SUBMIT_MODES
                       and actor_id in session.engine.state.actors
                       and not session.engine.state.setup_tasks
                       and session.engine.state.pending_resolution is None
                       and any(row.kind == "END_TURN" for row in candidates)
                       and all((row.actor_id, row.decision_id, row.state_version)
                               == (first.actor_id, first.decision_id, session.engine.state.state_version)
                               for row in candidates))
            if compact:
                context_doc = {"decision_id": first.decision_id,
                               "state_version": session.engine.state.state_version,
                               "active_actor_id": actor_id}
            elif cached is not None:
                context_doc = json.loads(cached)  # a fresh copy: callers edit it (the table rounds each area's cells)
            elif movement_menu.active() and table_header:
                # The table consumes identity and action rows, not AI policy,
                # perception and per-candidate tactical context.
                context_doc = {'decision_id': first.decision_id,
                               'state_version': session.engine.state.state_version,
                               'active_actor_id': actor_id,
                               'legal_candidates': [row.model_dump(mode='json') for row in candidates]}
            else:
                context = self._decision_model(session, candidates=candidates, policy=policy)
                context_doc = context.model_dump(mode="json", by_alias=True)
                if key is not None:
                    self._derived_put(key, context_key, json.dumps(context_doc, ensure_ascii=False))
            if metadata is None:
                metadata = self._read_metadata(match_id, session)
                control_mode = self._mode_for_actor(metadata, session, actor_id)
            return {
                "context": context_doc,
                "control_mode": control_mode,
                "manual_submit_allowed": control_mode in MANUAL_SUBMIT_MODES,
                "manual_submit_reason": (
                    "ACTIVE_ACTOR_ACCEPTS_OWNER_INTENT"
                    if control_mode in MANUAL_SUBMIT_MODES
                    else f"ACTIVE_ACTOR_CONTROLLED_BY_{control_mode}"
                ),
                "fallback_policy_used": fallback,
            }

    def _intent_from_payload(self, context, payload: dict[str, Any], *, reactions: Iterable[ReactionDecision] = ()) -> ActionIntent:
        candidate = next((row for row in context.legal_candidates if row.candidate_id == payload.get("candidate_id")), None)
        if candidate is None:
            raise self._error(
                "COMBAT_DECISION_STALE",
                "The selected candidate is not legal in the current decision context.",
                subsystem="combat.gate5.intent",
                retry_safe=True,
                recommended_action="Refresh the decision context and choose one of its current candidate IDs.",
                match_id=context.match_id,
                actor_id=context.active_actor_id,
                decision_id=context.decision_id,
                status_code=409,
            )
        if payload.get("decision_id") != context.decision_id or int(payload.get("state_version", -1)) != context.state_version:
            raise self._error(
                "COMBAT_DECISION_STALE",
                "The submitted decision ID or state version is stale.",
                subsystem="combat.gate5.intent",
                retry_safe=True,
                recommended_action="Refresh the match and submit against the newest immutable DecisionContext.",
                match_id=context.match_id,
                actor_id=context.active_actor_id,
                decision_id=payload.get("decision_id"),
                details={"current_decision_id": context.decision_id, "current_state_version": context.state_version},
                status_code=409,
            )
        supplied_actor = payload.get("actor_id")
        supplied_targets = tuple(payload.get("target_ids") or ())
        supplied_destination = Position.model_validate(payload["destination"]) if payload.get("destination") is not None else None
        if payload.get('placement_destination') is not None and not candidate.metadata.get('placement_picker'):
            raise ValueError('A placement aim requires a square-placement menu choice')
        option_ids = tuple(payload.get("option_ids") or ())
        choice_findings = validate_option_selection(candidate, option_ids)
        if not choice_findings:
            option_ids = canonicalize_option_selection(candidate, option_ids)
        if (
            supplied_actor != candidate.actor_id
            or supplied_targets != candidate.target_ids
            or supplied_destination != candidate.destination
            or choice_findings
        ):
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "The intent does not exactly match the selected engine-issued candidate and legal options.",
                subsystem="combat.gate5.intent",
                retry_safe=True,
                recommended_action="Use the actor, targets, destination, and option IDs exactly as listed in the current DecisionContext.",
                match_id=context.match_id,
                actor_id=context.active_actor_id,
                decision_id=context.decision_id,
                details={"candidate": candidate.model_dump(mode="json"), "choice_findings": list(choice_findings)},
                status_code=422,
            )
        identity = {
            "match_id": context.match_id,
            "decision_id": context.decision_id,
            "candidate_id": candidate.candidate_id,
            "options": option_ids,
            "reactions": [row.model_dump(mode="json") for row in reactions],
        }
        if payload.get('placement_destination') is not None:
            identity['placement_destination'] = Position.model_validate(payload['placement_destination']).model_dump(mode='json')
        return ActionIntent(
            intent_id=f"intent:gate5:{canonical_sha256(identity)[:24]}",
            decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id,
            state_version=candidate.state_version,
            actor_id=candidate.actor_id,
            target_ids=candidate.target_ids,
            destination=candidate.destination,
            placement_destination=(Position.model_validate(payload['placement_destination'])
                                   if payload.get('placement_destination') is not None else None),
            option_ids=option_ids,
            reaction_decisions=tuple(reactions),
            movement_path=tuple(Position.model_validate(p) for p in payload['movement_path']) if payload.get('movement_path') is not None else None,
            movement_mode=(payload.get('movement_mode') or 'walk') if payload.get('movement_path') is not None else None,
        )

    def _manual_record(self, context, intent: ActionIntent) -> DecisionRecord:
        adapter = ManualControllerAdapter(lambda _context: (intent.candidate_id, intent.option_ids))
        choice = adapter.choose_primary_action(context)
        return choice.record

    def _require_manual_submit_mode(
        self,
        match_id: str,
        session: Gate4PersistentSession,
        metadata: dict[str, Any],
    ) -> str:
        if session.engine.state.terminal_result is not None:
            raise self._error(
                "COMBAT_MATCH_ALREADY_COMPLETE",
                "The completed match is read-only and cannot accept an owner-submitted intent or reaction.",
                subsystem="combat.gate5.manual_control",
                retry_safe=False,
                recommended_action="Inspect the final summary, verify, replay, or export.",
                match_id=match_id,
                status_code=409,
            )
        candidates = self._legal_candidates(session)
        actor_id = candidates[0].actor_id
        mode = self._mode_for_actor(metadata, session, actor_id)
        if mode not in MANUAL_SUBMIT_MODES:
            raise self._error(
                "COMBAT_CONTROLLER_MODE_MISMATCH",
                "The active fighter is assigned to an automatic controller and cannot accept an owner-submitted intent.",
                subsystem="combat.gate5.manual_control",
                retry_safe=True,
                recommended_action="Use the assigned automatic controller, or create a new match with Manual, Suggested, or Manual AI Bridge control for this fighter.",
                match_id=match_id,
                actor_id=actor_id,
                details={"control_mode": mode, "allowed_manual_modes": sorted(MANUAL_SUBMIT_MODES)},
                status_code=409,
            )
        return mode

    @staticmethod
    def _clone_engine(source_root: Path, engine: Gate4ControllerEngine) -> Gate4ControllerEngine:
        runtime_authority = (
            engine.runtime_authority.model_dump(mode="json")
            if getattr(engine, "runtime_authority", None) is not None
            else None
        )
        clone = Gate4ControllerEngine(
            source_root,
            match_seed=engine.state.match_seed,
            maximum_rounds=engine.state.maximum_rounds,
            runtime_authority=runtime_authority,
            typed_bundles=tuple(getattr(engine, "typed_bundle_documents", ()) or ()),
            battlefield=getattr(engine, "battlefield_document", None),
            # Preserve the shared geometry contract for every size-sensitive
            # save, forced movement and path query; previews must match execution.
            actor_footprints=engine.actor_footprints,
        )
        clone.state = engine.state.model_copy(deep=True)
        # Logs are already validated models. Deep copies detach mutable event
        # payloads without serializing and validating every historical row again.
        clone.events = [row.model_copy(deep=True) for row in engine.events]
        clone.rolls = [row.model_copy(deep=True) for row in engine.rolls]
        clone.roller.counter = engine.state.roll_counter
        clone._transaction_id = None
        clone._transaction_result_version = engine.state.state_version
        clone._active_intent_id = "system:gate5-preview"
        clone._active_intent = None
        clone._commanded_cui_this_turn = bool(engine._commanded_cui_this_turn)
        clone.typed_ask_reactors = getattr(engine, "typed_ask_reactors", frozenset())
        clone.typed_control_modes = dict(getattr(engine, "typed_control_modes", {}) or {})
        clone.placement_policies = dict(getattr(engine, 'placement_policies', {}) or {})
        return clone

    def _validate_reaction(self, context: ReactionContext, decision: ReactionDecision) -> None:
        if (
            decision.checkpoint != context.checkpoint
            or decision.reactor_id != context.reactor_id
            or decision.reaction_source_id not in context.legal_reaction_ids
        ):
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "The reaction decision belongs to another checkpoint, reactor, or reaction.",
                subsystem="combat.gate5.reaction",
                retry_safe=True,
                recommended_action="Use the exact IDs in the current ReactionContext.",
                match_id=context.match_id,
                actor_id=context.reactor_id,
                decision_id=context.decision_id,
                status_code=422,
            )
        if decision.selection == "DECLINE":
            if decision.spend != 0 or decision.option_ids:
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "A declined reaction cannot spend resources or select options.",
                    subsystem="combat.gate5.reaction",
                    retry_safe=True,
                    recommended_action="Return DECLINE with spend 0 and no option IDs.",
                    match_id=context.match_id,
                    actor_id=context.reactor_id,
                    decision_id=context.decision_id,
                    status_code=422,
                )
            return
        if context.reaction_source_id == "reaction:core.stamina_guard":
            if decision.spend not in context.spend_options:
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "The Stamina Guard spend is not legal at this actual damage checkpoint.",
                    subsystem="combat.gate5.reaction",
                    retry_safe=True,
                    recommended_action="Choose one of the spend values in the ReactionContext.",
                    match_id=context.match_id,
                    actor_id=context.reactor_id,
                    decision_id=context.decision_id,
                    details={"spend_options": list(context.spend_options)},
                    status_code=422,
                )
        elif decision.spend != 0:
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "This reaction does not accept a variable spend.",
                subsystem="combat.gate5.reaction",
                retry_safe=True,
                recommended_action="Use spend 0 for this reaction.",
                match_id=context.match_id,
                actor_id=context.reactor_id,
                decision_id=context.decision_id,
                status_code=422,
            )
        legal_options = set(context.legal_option_ids)
        if context.extension_choice is not None:
            from .choice_checkpoints import validate
            validate(decision, context.extension_choice)
        if any(option not in legal_options for option in decision.option_ids):
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "The reaction contains an option not supported by its exact mechanic.",
                subsystem="combat.gate5.reaction",
                retry_safe=True,
                recommended_action="Use only option IDs exposed for this reaction, or no options.",
                match_id=context.match_id,
                actor_id=context.reactor_id,
                decision_id=context.decision_id,
                status_code=422,
            )

    def _run_preview(
        self,
        session: Gate4PersistentSession,
        metadata: dict[str, Any],
        base_intent: ActionIntent,
        supplied_reactions: tuple[ReactionDecision, ...],
        *, reject_unused_reactions: bool = False, _menu_probe=None,
    ) -> dict[str, Any]:
        probe = self._clone_engine(self.source_root, session.engine)
        supplied: dict[tuple[str, str, str], ReactionDecision] = {}
        for decision in supplied_reactions:
            key = (decision.checkpoint, decision.reactor_id, decision.reaction_source_id)
            if key in supplied:
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "A reaction decision was supplied more than once.",
                    subsystem="combat.gate5.reaction",
                    retry_safe=True,
                    recommended_action="Provide at most one decision for each checkpoint/reactor/reaction tuple.",
                    match_id=session.match_id,
                    status_code=422,
                )
            supplied[key] = decision
        resolved: list[ReactionDecision] = []
        records: list[dict[str, Any]] = []

        def provider(request: dict[str, Any]):
            from .reaction_trigger import contextual_request

            request = contextual_request(probe, request)
            policy, _ = self.policies.for_actor(str(request["reactor_id"]))
            context = build_reaction_context(probe, policy, request)
            key = (context.checkpoint, context.reactor_id, context.reaction_source_id)
            mode = self._mode_for_actor(metadata, session, context.reactor_id)
            if key in supplied:
                decision = supplied[key]
                self._validate_reaction(context, decision)
                resolved.append(decision)
                record = ManualControllerAdapter(lambda _ctx: ("", ()), reaction_chooser=lambda _ctx: decision).choose_reaction(context).record
                record_doc = record.model_dump(mode="json", by_alias=True)
                records.append(record_doc)
                return decision, record_doc
            needs_gm = bool((request.get('choice_trigger') or {}).get('gm_adjudication'))
            if _menu_probe is not None and (mode not in {"LOCAL_AUTO", "API_AUTO"} or needs_gm):
                return _menu_probe.answer(context, probe), None
            if mode in {"LOCAL_AUTO", "API_AUTO"} and not needs_gm:
                choice = self.controller.choose_reaction(context)
                self._validate_reaction(context, choice.decision)
                resolved.append(choice.decision)
                record_doc = choice.record.model_dump(mode="json", by_alias=True)
                records.append(record_doc)
                return choice.decision, record_doc
            suggestion = self.controller.choose_reaction(context)
            raise _ReactionRequired(
                context,
                {
                    "decision": suggestion.decision.model_dump(mode="json"),
                    "record": suggestion.record.model_dump(mode="json", by_alias=True),
                },
                resolved_reactions=tuple(resolved),
                reaction_records=tuple(records),
            )

        probe.set_reaction_provider(provider)
        event_start = len(probe.events)
        roll_start = len(probe.rolls)
        try:
            candidates = probe.candidates_for_intent(base_intent) if base_intent.movement_path is not None or base_intent.destination is not None else self._legal_candidates(session)
            with self._execution_candidates(probe, candidates, canonical_state_sha256(session.engine.state)):
                probe.execute_intent(base_intent.model_copy(update={"reaction_decisions": ()}))
        except _ReactionRequired as needed:
            if _menu_probe is None:
                from .reaction_menu import ReactionMenuProbe, MenuBoundary
                from .ext import OptionalFollowupTargetConflict
                discovery = ReactionMenuProbe(needed.context)
                try:
                    self._run_preview(session, metadata, base_intent, supplied_reactions, _menu_probe=discovery)
                except MenuBoundary:
                    pass
                except OptionalFollowupTargetConflict:
                    # Discovery runs on a throwaway clone and answers every prompt
                    # with a synthetic decline only to enumerate the menu. A second
                    # consumer of the optional follow-up target seam can look like
                    # the only owner after that decline; that rejection must not
                    # turn the real manual prompt into a rejected action, because
                    # the prompt below is the authoritative outcome and the real
                    # answer is validated by the ordinary preview. Any other error
                    # still surfaces, so a broken discovery never ships a partial
                    # menu silently. Keep the contexts found so far.
                    pass
                needed.menu_contexts = tuple(discovery.contexts)
            raise
        finally:
            probe.set_reaction_provider(None)
        if reject_unused_reactions and set(supplied) - {(r.checkpoint, r.reactor_id, r.reaction_source_id) for r in resolved}:
            raise self._error('COMBAT_AI_INTENT_INVALID', 'A reaction answer no longer applies to this action.',
                subsystem='combat.gate5.reaction', retry_safe=True,
                recommended_action='Answer the current reaction prompt and try again.', match_id=session.match_id, status_code=409)
        final_intent = base_intent.model_copy(update={"reaction_decisions": tuple(resolved)})
        result = {
            "match_id": session.match_id,
            "pre_state_version": session.engine.state.state_version,
            "pre_state_sha256": canonical_state_sha256(session.engine.state),
            "intent": final_intent.model_dump(mode="json"),
            "resolved_reactions": [row.model_dump(mode="json") for row in resolved],
            "reaction_records": records,
            "post_state_version": probe.state.state_version,
            "post_state_sha256": canonical_state_sha256(probe.state),
            "roll_counter_end": probe.state.roll_counter,
            "events": [row.model_dump(mode="json") for row in probe.events[event_start:]],
            "rolls": [row.model_dump(mode="json") for row in probe.rolls[roll_start:]],
        }
        result["preview_id"] = f"preview:{canonical_sha256(result)[:32]}"
        return result

    def preview(self, match_id: str, payload: dict[str, Any], reaction_rows: list[dict[str, Any]], *,
                controller_preview: bool = False, projected_engine: Gate4ControllerEngine | None = None) -> dict[str, Any]:
        """Noncommitting legality/reaction preview for browser and server drivers.

        controller_preview permits inspection of an automatic controller's exact
        intent, e.g. restoring an old reaction pause or comparing controller
        proposals. It grants no submission authority; commits retain their mode
        and decision/version checks. The default browser contract is unchanged.

        ``projected_engine`` is a server-created disposable projection, already
        validated by the caller (e.g. drafted settings or targeting variants).
        It uses the same exact intent validation and reaction preview as a live
        action. Only the call-local session view changes; the cached session,
        saved settings and journals are never replaced or written by preview.
        This is not client-supplied engine/context authority or a commit seam.
        """
        with self._timed("manual_preview", threshold_ms=3000):
            session = self._load_session(match_id)
            if projected_engine is not None:
                session = copy(session)
                session.engine = projected_engine
            metadata = self._read_metadata(match_id, session)
            if not controller_preview:
                self._require_manual_submit_mode(match_id, session, metadata)
            context = self._decision_model(session)
            from .movement_routes import context_for_payload
            context = context_for_payload(session.engine, context, payload)
            from .placement_menu import context_for_payload as placement_context
            context = placement_context(session.engine, context, payload)
            reactions = tuple(ReactionDecision.model_validate(row) for row in reaction_rows)
            base_intent = self._intent_from_payload(context, payload)
            try:
                result = self._run_preview(session, metadata, base_intent, reactions)
            except _ReactionRequired as needed:
                return {
                    "schema": "TianxiaFactoryCombatPreview.v1",
                    "status": "REACTION_REQUIRED",
                    "diagnostic": CombatServiceDiagnostic(
                        code="COMBAT_REACTION_DECISION_REQUIRED",
                        message="An actual deterministic reaction checkpoint requires a manual decision.",
                        subsystem="combat.gate5.preview",
                        retry_safe=True,
                        recommended_action="Choose Use or Decline using only the exact ReactionContext values, then preview again.",
                        match_id=match_id,
                        actor_id=needed.context.reactor_id,
                        decision_id=needed.context.decision_id,
                    ).as_dict(),
                    "reaction_context": needed.context_doc(),
                    "reaction_context_fingerprint": f"reaction-context:{canonical_sha256(needed.context.model_dump(mode='json', by_alias=True))[:32]}",
                    "reaction_step_number": len(needed.resolved_reactions) + 1,
                    "resolved_reactions_before_prompt": [row.model_dump(mode="json") for row in needed.resolved_reactions],
                    "reaction_records_before_prompt": list(needed.reaction_records),
                    "reaction_controller_mode": self._mode_for_actor(metadata, session, needed.context.reactor_id),
                    "manual_response_required": True,
                    "local_suggestion": needed.suggestion,
                    "authoritative_state_unchanged": True,
                }
            except (CombatGate1Error, ValueError) as exc:
                diagnostic = getattr(exc, "diagnostic", None)
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    "The selected action or option combination was rejected by the exact combat runtime.",
                    subsystem="combat.gate5.preview",
                    retry_safe=True,
                    recommended_action="Refresh the legal candidates and choose only the target, destination, and option combination exposed by the current decision.",
                    match_id=match_id,
                    actor_id=context.active_actor_id,
                    decision_id=context.decision_id,
                    details={
                        "underlying_code": getattr(diagnostic, "code", None),
                        "reason": str(exc),
                    },
                    status_code=422,
                ) from exc
            return {
                "schema": "TianxiaFactoryCombatPreview.v1",
                "status": "PREVIEW_COMPLETE",
                **result,
                "authoritative_state_unchanged": True,
            }

    def _commit_previewed(
        self,
        match_id: str,
        payload: dict[str, Any],
        reaction_rows: list[dict[str, Any]],
        preview_id: str | None,
        *,
        primary_record: DecisionRecord | None = None,
        session: Gate4PersistentSession | None = None,
        metadata: dict[str, Any] | None = None,
        reject_unused_reactions: bool = False,
    ) -> dict[str, Any]:
        """``session`` and ``metadata``: the caller's own just-loaded ones (``submit_intent``), so the fight is loaded and
        its menu worked out once, not again for each step of the commit."""
        with self._timed("authoritative_action_commit", threshold_ms=3000):
            if session is None:
                session = self._load_session(match_id)
            if metadata is None:
                metadata = self._read_metadata(match_id, session)
            context = self._decision_model(session)
            from .movement_routes import context_for_payload
            context = context_for_payload(session.engine, context, payload)
            from .placement_menu import context_for_payload as placement_context
            context = placement_context(session.engine, context, payload)
            reactions = tuple(ReactionDecision.model_validate(row) for row in reaction_rows)
            base_intent = self._intent_from_payload(context, payload)
            try:
                preview = self._run_preview(session, metadata, base_intent, reactions,
                                            reject_unused_reactions=reject_unused_reactions)
            except _ReactionRequired as needed:
                raise self._error(
                    "COMBAT_REACTION_DECISION_REQUIRED",
                    "The action reached an unresolved manual reaction checkpoint.",
                    subsystem="combat.gate5.commit",
                    retry_safe=True,
                    recommended_action="Use the preview endpoint, resolve the returned ReactionContext, and submit the exact completed preview.",
                    match_id=match_id,
                    actor_id=needed.context.reactor_id,
                    decision_id=needed.context.decision_id,
                    details={"reaction_context": needed.context_doc()},
                    status_code=409,
                ) from needed
            except (CombatGate1Error, ValueError) as exc:
                diagnostic = getattr(exc, "diagnostic", None)
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    (str(exc) if getattr(diagnostic, "code", None) == "GATE2_PAYMENT_DECLINED" else
                     "The completed intent was rejected by the exact combat runtime."),
                    subsystem="combat.gate5.commit",
                    retry_safe=True,
                    recommended_action="Refresh the match and preview a currently legal option combination before committing.",
                    match_id=match_id,
                    actor_id=context.active_actor_id,
                    decision_id=context.decision_id,
                    details={
                        "underlying_code": getattr(diagnostic, "code", None),
                        "reason": str(exc),
                    },
                    status_code=422,
                ) from exc
            if preview_id is not None and preview_id != preview["preview_id"]:
                raise self._error(
                    "COMBAT_PREVIEW_MISMATCH",
                    "The authoritative pre-state or completed preview no longer matches the checked preview.",
                    subsystem="combat.gate5.commit",
                    retry_safe=True,
                    recommended_action="Refresh the match and preview the action again before committing.",
                    match_id=match_id,
                    actor_id=context.active_actor_id,
                    decision_id=context.decision_id,
                    details={"expected_preview_id": preview["preview_id"], "supplied_preview_id": preview_id},
                    status_code=409,
                )
            final_intent = ActionIntent.model_validate(preview["intent"])
            record = primary_record or self._manual_record(context, final_intent)
            candidates = session.engine.candidates_for_intent(final_intent) if final_intent.movement_path is not None or final_intent.destination is not None else self._legal_candidates(session)
            from .ext.system_bookkeeping import recovery_provenance

            selected = next(candidate for candidate in candidates if candidate.candidate_id == final_intent.candidate_id)
            recovery = recovery_provenance(session.engine, selected)
            if recovery is not None:
                record = record.model_copy(update={"diagnostics": (*record.diagnostics, recovery)})
            with self._execution_candidates(session.engine, candidates, canonical_state_sha256(session.engine.state)):
                session.submit_intent(final_intent, primary_decision_record=record, reaction_provider=None)
            actual = canonical_state_sha256(session.engine.state)
            divergence = None
            if actual != preview["post_state_sha256"]:
                # The authoritative engine is the rules, and by this line it has already applied this action
                # to the live state and committed it to the journal. Refusing the commit here used to throw
                # away a legal, fully played turn and answer with a non-retryable 500 telling the owner to
                # abandon a match that is in fact consistent and still playable (hunt 90: an offered button
                # could not be committed and the fight was left unusable). Keep the authoritative result --
                # it is the one the saved fight, its journal and its replay now all agree with -- and write
                # the disagreement down beside it, so the disagreement stays visible through a reload
                # instead of dying with the response that carried it.
                divergence = record_commit_divergence(
                    self._match_dir(match_id),
                    match_id=match_id,
                    actor_id=context.active_actor_id,
                    decision_id=context.decision_id,
                    state_version=context.state_version,
                    preview_id=preview["preview_id"],
                    preview_post_state_sha256=preview["post_state_sha256"],
                    authoritative_post_state_sha256=actual,
                )
                # A failed sidecar write must still be visible for this service's
                # lifetime, without changing journals or saved mechanical state.
                if "persistence_error" in divergence:
                    if not hasattr(self, "commit_divergence_notices"):
                        self.commit_divergence_notices = {}
                    self.commit_divergence_notices[match_id] = divergence
                else:
                    getattr(self, "commit_divergence_notices", {}).pop(match_id, None)
            result = {"preview_id": preview["preview_id"], "match": self._match_view(session, metadata)}
            if divergence is not None:
                result["preview_divergence"] = divergence
            return result

    def change_relations(self, match_id: str, *, change: dict[str, Any], expected_state_version: int) -> dict[str, Any]:
        """Owner/GM-only service command for the table and future role-play.

        change={kind: ACTOR_SIDE, subject: actor_id, other: team_id} joins a side.
        TEAM_RELATION or ACTOR_RELATION additionally needs relation=ALLY/ENEMY/NEUTRAL.
        No automatic retaliation or actor/AI authorization is implied. The table
        endpoint calling this method must use its ordinary owner session guard.
        Commands cost no action and are accepted only between complete decisions.
        """
        from .relations import command_intent
        session = self._load_session(match_id)
        try:
            intent = command_intent(session.engine, change, expected_state_version=expected_state_version)
        except ValueError as exc:
            raise self._error('COMBAT_UI_DATA_INVALID', str(exc), subsystem='combat.relations',
                              retry_safe=True, recommended_action='Refresh the fight and choose its current creatures or teams.',
                              match_id=match_id, status_code=409) from exc
        session.submit_intent(intent, primary_decision_record=None, reaction_provider=None)
        return self.get_match(match_id)

    def submit_intent(
        self,
        match_id: str,
        payload: dict[str, Any],
        reaction_rows: list[dict[str, Any]],
        preview_id: str | None,
        *,
        session: Gate4PersistentSession | None = None,
    ) -> dict[str, Any]:
        """``session``: one the caller has just loaded (and only read) at the current state; it is committed on."""
        if session is None:
            session = self._load_session(match_id)
        metadata = self._read_metadata(match_id, session)
        self._require_manual_submit_mode(match_id, session, metadata)
        return self._commit_previewed(match_id, payload, reaction_rows, preview_id, session=session, metadata=metadata)

    def suggest(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error(
                "COMBAT_MATCH_ALREADY_COMPLETE",
                "The completed match has no action suggestion.",
                subsystem="combat.gate5.controller",
                retry_safe=False,
                recommended_action="Use replay or export.",
                match_id=match_id,
                status_code=409,
            )
        context = self.ai_decision_context(session)
        actor_id = context.active_actor_id
        policy, fallback = self.policies.for_actor(actor_id)
        choice = self.controller.choose_primary_action(context)
        return {
            "schema": "TianxiaFactoryCombatSuggestion.v1",
            "intent": choice.intent.model_dump(mode="json"),
            "record": choice.record.model_dump(mode="json", by_alias=True),
            "fallback_policy_used": fallback,
        }

    def _append_dao_iching_audit(self, match_id: str, *, path: str, actor_id: str, record: dict[str, Any]) -> dict[str, Any]:
        policy, _ = self.policies.for_actor(actor_id)
        policy_doc = policy.model_dump(mode="json") if hasattr(policy, "model_dump") else {}
        legal_count = len(record.get("legal_candidate_ids") or record.get("ranked_candidate_ids") or [])
        row = {
            "schema": "TianxiaFactory.C3CDaoIChingChoiceAudit.v1",
            "recorded_at": _utcnow(),
            "match_id": match_id,
            "choice_path": path,
            "actor_id": actor_id,
            "decision_id": record.get("decision_id"),
            "selected_candidate_id": record.get("selected_candidate_id") or record.get("candidate_id"),
            "dao_profile": policy_doc.get("dao") or policy_doc.get("dao_profile"),
            "iching_profile": policy_doc.get("i_ching") or policy_doc.get("iching_profile"),
            "limited_legal_action_options": legal_count <= 1 if legal_count else False,
            "tactical_planning_weakness": False,
            "weak_dao_expression": False,
            "inappropriate_risk_tolerance": False,
            "mechanically_reasonable_but_character_incongruent": False,
            "assessment": "Choice follows the existing deterministic policy; no contradictory Dao or I Ching signal was identified at this decision boundary.",
        }
        audit_path = self._match_dir(match_id) / "DaoIChingChoiceAudit.ndjson"
        with audit_path.open("ab") as handle:
            handle.write(canonical_bytes(row) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        return row

    def post_round_dao_iching_audit(self, match_id: str) -> dict[str, Any]:
        """Produce one bounded post-round tactical audit per primary combatant."""
        session = self._load_session(match_id)
        genesis = json.loads(session.store.genesis_path.read_text(encoding="utf-8"))["state"]
        initial = {row["entity_id"]: row for row in genesis["actors"].values()} if isinstance(genesis.get("actors"), dict) else {row["entity_id"]: row for row in genesis.get("actors", [])}
        journal = self._controller_rows(session, limit=1000)
        rows = []
        for actor_id in sorted(a.entity_id for a in session.engine.state.actors.values() if a.primary_combatant):
            actor = session.engine.state.actors[actor_id]
            actor_records = [row for row in journal if row.get("actor_id") == actor_id or row.get("primary_decision_record", {}).get("actor_id") == actor_id]
            selected = []
            for row in actor_records:
                rec = row.get("primary_decision_record") or row
                candidate = rec.get("selected_candidate_id") or rec.get("candidate_id")
                if candidate: selected.append(candidate)
            policy, _ = self.policies.for_actor(actor_id)
            policy_doc = policy.model_dump(mode="json") if hasattr(policy, "model_dump") else {}
            dao = policy_doc.get("dao") or policy_doc.get("dao_profile") or "PROFILE_NOT_AVAILABLE"
            iching = policy_doc.get("i_ching") or policy_doc.get("iching_profile") or "PROFILE_NOT_AVAILABLE"
            before = initial.get(actor_id, {})
            resource_changes = {rid: {"before": before.get("resources", {}).get(rid), "after": value} for rid, value in sorted(actor.resources.items()) if before.get("resources", {}).get(rid) != value}
            moved = before.get("position") != actor.position.model_dump(mode="json")
            limited = any(len((row.get("primary_decision_record") or row).get("legal_candidate_ids") or []) <= 1 for row in actor_records) if actor_records else True
            tactical = "No committed choice was available for audit." if not selected else f"Committed sequence: {', '.join(selected)}."
            rows.append({
                "actor_id": actor_id, "display_name": actor.display_name,
                "action_sequencing": tactical,
                "resource_use": resource_changes or "No tracked resource change during the round.",
                "positioning": {"moved": moved, "before": before.get("position"), "after": actor.position.model_dump(mode="json")},
                "risk_tolerance": "High immediate risk" if actor.current_hp * 2 < actor.maximum_hp else "Within normal tactical risk",
                "dao_profile": dao, "dao_expression": "PROFILE_NOT_AVAILABLE" if dao == "PROFILE_NOT_AVAILABLE" else "Compared against the existing profile; no forced controller behavior was added.",
                "iching_profile": iching, "iching_expression": "PROFILE_NOT_AVAILABLE" if iching == "PROFILE_NOT_AVAILABLE" else "Compared against the existing profile and committed sequence.",
                "limited_legal_action_options": limited,
                "tactical_planning_failure": False,
                "weak_dao_expression": False if dao != "PROFILE_NOT_AVAILABLE" else None,
                "mechanically_reasonable_but_character_incongruent": False if dao != "PROFILE_NOT_AVAILABLE" or iching != "PROFILE_NOT_AVAILABLE" else None,
            })
        report = {"schema": "TianxiaFactory.C3CPostRoundDaoIChingAudit.v1", "match_id": match_id, "round_boundary": session.engine.state.round_number, "combatants": rows}
        path = session.store.match_dir / "C3C_Post_Round_Dao_IChing_Audit.json"
        path.write_bytes(canonical_bytes(report) + b"\n")
        return report

    def local_step(self, match_id: str, reactions: list[dict[str, Any]] | None = None, *,
                   session: Gate4PersistentSession | None = None, include_match: bool = True) -> dict[str, Any]:
        """Advance through the ordinary policy and durable transaction path.

        A supplied session is freshly loaded or checked by ExecutionSession at
        the current reserved boundary. include_match=False returns execution
        status without constructing a full match view after every decision.
        """
        with self._timed("local_auto_step", threshold_ms=3000):
            if session is None:
                session = self._load_session(match_id)
            metadata = self._read_metadata(match_id, session)
            if metadata.get("paused"):
                raise self._error(
                    "COMBAT_MATCH_PAUSED",
                    "Local Auto is paused for this match.",
                    subsystem="combat.gate5.controller",
                    retry_safe=True,
                    recommended_action="Resume the match before requesting another Local Auto step.",
                    match_id=match_id,
                    status_code=409,
                )
            if session.engine.state.terminal_result is not None:
                raise self._error(
                    "COMBAT_MATCH_ALREADY_COMPLETE",
                    "The combat match is already complete.",
                    subsystem="combat.gate5.controller",
                    retry_safe=False,
                    recommended_action="Use verify, replay, or export.",
                    match_id=match_id,
                    status_code=409,
                )
            candidates = self._legal_candidates(session, knowledge_only=True)
            actor_id = candidates[0].actor_id
            mode = self._mode_for_actor(metadata, session, actor_id)
            if mode != "LOCAL_AUTO":
                return {
                    "schema": "TianxiaFactoryCombatLocalStep.v1",
                    "status": "AWAITING_NON_AUTO_CONTROL",
                    "actor_id": actor_id,
                    "control_mode": mode,
                    "match": self._match_view(session, metadata) if include_match else None,
                }
            choice, candidates, recovery = self._local_choice(session, candidates)
            selected = next(candidate for candidate in candidates if candidate.candidate_id == choice.intent.candidate_id)
            controller = self.controller
            selected_action = session.engine.action_catalog.get(selected.source_definition_id)
            needs_gm = bool(selected_action and ((selected_action.parameters or {}).get('typed') or {}).get('gm_adjudication'))
            if getattr(session.engine, "typed_ask_reactors", None) or needs_gm:
                answers = {(row.checkpoint, row.reactor_id, row.reaction_source_id): row
                           for row in (ReactionDecision.model_validate(item) for item in reactions or [])}
                needed = self._ask_during_ai_step(session, choice, answers,
                                                  candidates=candidates if recovery is not None else None)
                if needed is not None:
                    # A player's Ask me reaction came up (step 16): nothing is committed; the table asks and steps again
                    # with the answer, and the AI, deterministic from this state, makes the same choice.
                    return {
                        "schema": "TianxiaFactoryCombatLocalStep.v1",
                        "status": "AWAITING_REACTION",
                        "actor_id": actor_id,
                        "reaction_context": needed.context_doc(),
                        "match": self._match_view(session, metadata) if include_match else None,
                    }
                controller = _AnsweringController(self.controller, answers)
            try:
                if recovery is not None:
                    with self._execution_candidates(session.engine, candidates, canonical_state_sha256(session.engine.state)):
                        session.execute_controller_choice(choice, controller=controller, policy_library=self.policies)
                else:
                    # Internally generated observed candidates already validate
                    # this exact state. Reuse them only for acceptance, with a
                    # full-state hash guard; execution keeps its real roster.
                    from .candidate_knowledge import prepared_binding
                    with prepared_binding(session.engine, candidates):
                        session.execute_controller_choice(choice, controller=controller, policy_library=self.policies)
            except CombatGate1Error as refused:
                if (refused.diagnostic.phase != "INTENT_VALIDATION"
                        or refused.diagnostic.recovery != "RETRY"):
                    raise
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID",
                    f"{session.engine.state.actors[actor_id].display_name} cannot complete this action: {refused}",
                    subsystem="combat.gate5.local_step", retry_safe=True,
                    recommended_action="Refresh the table. You can switch this fighter to manual control and choose another action.",
                    match_id=match_id, actor_id=actor_id, status_code=422,
                    details={"underlying_code": refused.diagnostic.code},
                ) from refused
            record = choice.record.model_dump(mode="json", by_alias=True)
            audit = self._append_dao_iching_audit(match_id, path="LOCAL_AUTO", actor_id=actor_id, record=record)
            return {
                "schema": "TianxiaFactoryCombatLocalStep.v1",
                "status": "COMMITTED",
                "record": record,
                "dao_iching_audit": audit,
                "match": self._match_view(session, metadata) if include_match else None,
            }

    def _ask_during_ai_step(self, session: Gate4PersistentSession, choice: Any,
                            answers: dict[tuple[str, str, str], ReactionDecision], *,
                            candidates: tuple[Any, ...] | None = None, _menu_probe=None) -> "_ReactionRequired | None":
        """Run the AI's action on a copy (step 16): the first Ask me prompt it reaches that ``answers`` does not
        cover, or None when every one is answered."""
        probe = self._clone_engine(self.source_root, session.engine)

        def provider(request: dict[str, Any]):
            from .reaction_trigger import contextual_request

            request = contextual_request(probe, request)
            policy, _ = self.policies.for_actor(str(request["reactor_id"]))
            context = build_reaction_context(probe, policy, request)
            key = (context.checkpoint, context.reactor_id, context.reaction_source_id)
            if key in answers:
                self._validate_reaction(context, answers[key])
                return answers[key], None
            # Ownership applies to plug-in choices and prepared triggers as well as typed reactions.
            if context.reactor_id in probe.typed_ask_reactors or (request.get('choice_trigger') or {}).get('gm_adjudication'):
                if _menu_probe is not None:
                    return _menu_probe.answer(context, probe), None
                raise _ReactionRequired(context, None)
            return self.controller.choose_reaction(context).decision, None

        probe.set_reaction_provider(provider)
        try:
            if candidates is not None:
                with self._execution_candidates(probe, candidates, canonical_state_sha256(session.engine.state)):
                    probe.execute_intent(choice.intent)
            else:
                probe.execute_intent(choice.intent)
        except _ReactionRequired as needed:
            if _menu_probe is None:
                from .reaction_menu import ReactionMenuProbe, MenuBoundary
                from .ext import OptionalFollowupTargetConflict
                discovery = ReactionMenuProbe(needed.context)
                try:
                    self._ask_during_ai_step(session, choice, answers, candidates=candidates, _menu_probe=discovery)
                except MenuBoundary:
                    pass
                except OptionalFollowupTargetConflict:
                    # Best-effort enumeration on a throwaway clone (see _run_preview):
                    # only the synthetic decline's one-owner rejection is ignored;
                    # a real discovery error still surfaces.
                    pass
                needed.menu_contexts = tuple(discovery.contexts)
            return needed
        except CombatGate1Error as refused:
            # This copy only discovers prompts. A retryable intent refusal is
            # not a player decision; let the real executor handle it instead.
            if (refused.diagnostic.phase != "INTENT_VALIDATION"
                    or refused.diagnostic.recovery != "RETRY"):
                raise
            return None
        finally:
            probe.set_reaction_provider(None)
        return None

    def _append_provider_audit(self, match_id: str, row: dict[str, Any]) -> None:
        path = self._match_dir(match_id) / "ProviderController.ndjson"
        document = {
            "schema": "TianxiaFactoryCombatProviderAudit.v1",
            "recorded_at": _utcnow(),
            "match_id": match_id,
            **row,
        }
        with path.open("ab") as handle:
            handle.write(canonical_bytes(document) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _resume_provider_decision(self, session, metadata, pending, reactions):
        """Resume the checked choice with an offered answer prefix, including after restart."""
        match_id = session.match_id
        if pending['state_sha256'] != canonical_state_sha256(session.engine.state):
            metadata.pop('pending_provider_decision', None)
            self._write_metadata(match_id, metadata)
            raise self._error('COMBAT_AI_INTENT_INVALID', 'The fight changed while this AI decision was waiting.',
                subsystem='combat.gate5.api_auto', retry_safe=True,
                recommended_action='Refresh the fight and request its next AI action.', match_id=match_id, status_code=409)
        answers = list(pending.get('reactions') or [])
        keyed = {(r['checkpoint'], r['reactor_id'], r['reaction_source_id']): r for r in answers}
        # One card can offer a prefix spanning hit and damage checkpoints.
        # Bind new answers to that exact server-offered order, then let the
        # transactional preview validate every option and reject unused answers.
        # Old single-prompt continuations retain their original binding.
        offered = pending.get('offered_reactions') or [pending.get('waiting_reaction') or []]
        offered_index = 0
        for value in reactions or []:
            row = ReactionDecision.model_validate(value).model_dump(mode='json')
            key = (row['checkpoint'], row['reactor_id'], row['reaction_source_id'])
            if key in keyed and keyed[key] != row:
                raise self._error('COMBAT_AI_INTENT_INVALID', 'This reaction already has a different answer.',
                    subsystem='combat.gate5.api_auto', retry_safe=True,
                    recommended_action='Continue with the answers already submitted for this action.', match_id=match_id, status_code=409)
            if key not in keyed:
                if offered_index >= len(offered) or key != tuple(offered[offered_index]):
                    raise self._error('COMBAT_AI_INTENT_INVALID', 'This answer does not match the waiting reaction.',
                        subsystem='combat.gate5.api_auto', retry_safe=True,
                        recommended_action='Answer the reaction currently shown by the fight.', match_id=match_id, status_code=409)
                keyed[key] = row
                answers.append(row)
                offered_index += 1
        result = self.ai_execute(match_id, pending['payload'], pending['validation_token'], pending.get('rationale'), reactions=answers,
                                 _resuming_provider=True)
        if result.get('status') == 'AWAITING_REACTION':
            context = result['reaction_context']
            metadata['pending_provider_decision'] = {**pending, 'reactions': answers,
                'waiting_reaction': [context[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')],
                'offered_reactions': [[c[k] for k in ('checkpoint', 'reactor_id', 'reaction_source_id')]
                                      for c in context.get('reaction_choices') or [context]]}
            self._write_metadata(match_id, metadata)
        else:
            metadata.pop('pending_provider_decision', None)
            self._write_metadata(match_id, metadata)
            self._append_provider_audit(match_id, {'status': 'COMMITTED', 'actor_id': pending['payload']['actor_id'],
                'decision_id': pending['payload'].get('decision_id'), 'candidate_id': pending['payload'].get('candidate_id'),
                'rationale': pending.get('rationale'), **pending['provider']})
        return {'schema': 'TianxiaFactoryCombatProviderStep.v1', 'status': result['status'],
                'actor_id': pending['payload']['actor_id'], 'provider': pending['provider'],
                **({'reaction_context': result['reaction_context']} if result['status'] == 'AWAITING_REACTION' else {}),
                **({'preview_id': result['preview_id']} if 'preview_id' in result else {}),
                'match': result['match']}

    def provider_step(self, match_id: str, reactions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        with self._timed("api_auto_step", threshold_ms=130000):
            session = self._load_session(match_id)
            metadata = self._read_metadata(match_id, session)
            if metadata.get("paused"):
                raise self._error(
                    "COMBAT_MATCH_PAUSED",
                    "API Auto is paused for this match.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=True,
                    recommended_action="Resume the match before requesting another API step.",
                    match_id=match_id,
                    status_code=409,
                )
            if session.engine.state.terminal_result is not None:
                raise self._error(
                    "COMBAT_MATCH_ALREADY_COMPLETE",
                    "The combat match is already complete.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=False,
                    recommended_action="Use verify, replay, or export.",
                    match_id=match_id,
                    status_code=409,
                )
            candidates = session.engine.legal_candidates()
            actor_id = candidates[0].actor_id
            mode = self._mode_for_actor(metadata, session, actor_id)
            pending = metadata.get('pending_provider_decision')
            if pending is not None and pending['state_sha256'] != canonical_state_sha256(session.engine.state):
                return self._resume_provider_decision(session, metadata, pending, reactions)
            if mode != "API_AUTO":
                if reactions:
                    raise self._error('COMBAT_AI_INTENT_INVALID', 'This fighter is no longer waiting for an API-controlled action.',
                        subsystem='combat.gate5.api_auto', retry_safe=True,
                        recommended_action='Refresh the fight and use its current controls.', match_id=match_id, status_code=409)
                return {
                    "schema": "TianxiaFactoryCombatProviderStep.v1",
                    "status": "AWAITING_OTHER_CONTROL",
                    "actor_id": actor_id,
                    "control_mode": mode,
                    "match": self._match_view(session, metadata),
                }
            if pending is not None:
                return self._resume_provider_decision(session, metadata, pending, reactions)
            if reactions:
                raise self._error('COMBAT_AI_INTENT_INVALID', 'There is no waiting AI action for these reaction answers.',
                    subsystem='combat.gate5.api_auto', retry_safe=True,
                    recommended_action='Refresh the fight and answer only its current prompt.', match_id=match_id, status_code=409)
            if self.ai_provider is None:
                raise self._error(
                    "COMBAT_SERVICE_UNAVAILABLE",
                    "No optional AI provider service is attached to Combat.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=True,
                    recommended_action="Use Local AI or configure the optional API provider in Settings.",
                    match_id=match_id,
                    actor_id=actor_id,
                    status_code=409,
                )
            provider_status = self.ai_provider.status()
            if not provider_status.get("ready"):
                raise self._error(
                    "COMBAT_SERVICE_UNAVAILABLE",
                    "The optional API provider is not configured and ready.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=True,
                    recommended_action="Configure the provider, acknowledge transmission, and save an API key—or switch this fighter to Local AI.",
                    match_id=match_id,
                    actor_id=actor_id,
                    details={"provider": provider_status},
                    status_code=409,
                )
            frame = self.ai_frame(match_id)
            try:
                provider = self.ai_provider.complete_json(
                    prompt_text=frame["frame_text"],
                    system_message=COMBAT_PROVIDER_SYSTEM_MESSAGE,
                    purpose="combat_decision",
                )
                value = provider.get("value")
                if not isinstance(value, dict) or value.get("schema") != AI_RESPONSE_SCHEMA:
                    raise ValueError(f"response schema must be {AI_RESPONSE_SCHEMA}")
                payload = value.get("action_intent")
                if not isinstance(payload, dict):
                    raise ValueError("action_intent is missing")
                # A deferred CELL row chooses the ability first. Ask this same
                # provider for its square from the complete observed legal set,
                # rather than letting a local reaction policy choose its aim.
                selected = next((c for c in frame['frame']['legal_candidates']
                                 if c['candidate_id'] == payload.get('candidate_id')), None)
                if (selected is not None and selected.get('metadata', {}).get('placement_picker')
                        and payload.get('placement_destination') is None):
                    from .placement_menu import cells
                    from .candidate_knowledge import query as observed
                    from .gate2_runtime_models import LegalCandidate
                    with observed(session.engine):
                        placements = list(cells(session.engine, LegalCandidate.model_validate({
                            **selected, 'decision_id': frame['frame']['decision_id'],
                            'state_version': frame['frame']['state_version']})))
                    square_frame = {'schema': 'TianxiaCombatPlacementFrame.v1',
                        'decision_context': frame['frame'],
                        'action_intent': payload,
                        'legal_placements': [{'placement_destination': c.destination.model_dump(mode='json'),
                                              'label': c.display_name, 'area': c.area.model_dump(mode='json') if c.area else None,
                                              'safety': c.metadata} for c in placements],
                        'response_schema': {'schema': AI_RESPONSE_SCHEMA,
                            'action_intent': {**payload, 'placement_destination': 'COPY_ONE_LISTED_PLACEMENT_DESTINATION'}}}
                    provider = self.ai_provider.complete_json(
                        prompt_text='Choose the square for the selected ability. Return JSON only; copy the action_intent unchanged '
                                    'and add placement_destination from any listed legal placement.\n\n' + json.dumps(square_frame),
                        system_message=COMBAT_PROVIDER_SYSTEM_MESSAGE, purpose='combat_placement')
                    value = provider.get('value')
                    aimed = value.get('action_intent') if isinstance(value, dict) else None
                    if (not isinstance(aimed, dict) or value.get('schema') != AI_RESPONSE_SCHEMA
                            or any(aimed.get(k) != v for k, v in payload.items() if k != 'placement_destination')
                            or aimed.get('placement_destination') not in
                               [p['placement_destination'] for p in square_frame['legal_placements']]):
                        raise ValueError('placement response must preserve the selected action and choose a listed legal square')
                    payload = aimed
                rationale = value.get("rationale") if isinstance(value.get("rationale"), str) else None
                checked = self.ai_validate(match_id, payload, rationale)
                pending = {'payload': payload, 'validation_token': checked['validation_token'], 'rationale': rationale,
                    'state_sha256': canonical_state_sha256(session.engine.state), 'reactions': [],
                    'provider': {key: provider.get(key) for key in ('provider_id', 'model', 'request_sha256', 'response_sha256', 'completion_sha256', 'usage')}}
                metadata['pending_provider_decision'] = pending
                self._write_metadata(match_id, metadata)
                return self._resume_provider_decision(session, metadata, pending, reactions)
            except CombatServiceError:
                raise
            except Exception as exc:
                code = getattr(exc, "code", None)
                message = getattr(exc, "message", None) or str(exc)
                details = getattr(exc, "details", None)
                self._append_provider_audit(match_id, {
                    "status": "REJECTED",
                    "actor_id": actor_id,
                    "error_code": code or type(exc).__name__,
                    "error_message": message[:500],
                })
                raise self._error(
                    "COMBAT_AI_INTENT_INVALID" if not str(code or "").startswith("AI_PROVIDER_") else "COMBAT_SERVICE_UNAVAILABLE",
                    "The API-controlled decision was not accepted.",
                    subsystem="combat.gate5.api_auto",
                    retry_safe=True,
                    recommended_action="Retry once, inspect the provider configuration, or switch the fighter to Local AI.",
                    match_id=match_id,
                    actor_id=actor_id,
                    details={"provider_code": code, "reason": message, "provider_details": details},
                    status_code=getattr(exc, "status_code", 422),
                ) from exc

    def auto_step(self, match_id: str, reactions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        session = self._load_session(match_id)
        metadata = self._read_metadata(match_id, session)
        if session.engine.state.terminal_result is not None:
            raise self._error(
                "COMBAT_MATCH_ALREADY_COMPLETE",
                "The combat match is already complete.",
                subsystem="combat.gate5.controller",
                retry_safe=False,
                recommended_action="Use verify, replay, or export.",
                match_id=match_id,
                status_code=409,
            )
        actor_id = self._legal_candidates(session)[0].actor_id
        mode = self._mode_for_actor(metadata, session, actor_id)
        if mode == "LOCAL_AUTO":
            return self.local_step(match_id, reactions, session=session)
        if mode == "API_AUTO":
            return self.provider_step(match_id, reactions)
        return {
            "schema": "TianxiaFactoryCombatAutoStep.v1",
            "status": "AWAITING_NON_AUTO_CONTROL",
            "actor_id": actor_id,
            "control_mode": mode,
            "match": self._match_view(session, metadata),
        }

    def local_run(self, match_id: str, *, maximum_steps: int = 20) -> dict[str, Any]:
        session = self._load_session(match_id)
        if session.engine.state.terminal_result is not None:
            raise self._error("COMBAT_MATCH_ALREADY_COMPLETE", "The combat match is already complete.", subsystem="combat.gate5.controller", retry_safe=False, recommended_action="Use verify, replay, or export.", match_id=match_id, status_code=409)
        metadata = self._read_metadata(match_id, session)
        if metadata.get("paused"):
            raise self._error(
                "COMBAT_MATCH_PAUSED",
                "Local Auto is paused for this match.",
                subsystem="combat.gate5.controller",
                retry_safe=True,
                recommended_action="Resume the match before running Local Auto.",
                match_id=match_id,
                status_code=409,
            )
        metadata["local_auto_running"] = True
        self._write_metadata(match_id, metadata)
        rows = []
        try:
            for _ in range(maximum_steps):
                result = self.local_step(match_id)
                row = {k: result.get(k) for k in ("status", "actor_id", "control_mode")}
                record = result.get("record")
                if record:
                    selected = next(
                        (item for item in record.get("scored_alternatives", []) if item.get("candidate_id") == record.get("selected_candidate_id")),
                        None,
                    )
                    row["record"] = {
                        "decision_id": record.get("decision_id"),
                        "state_version": record.get("state_version"),
                        "actor_id": record.get("actor_id"),
                        "selected_candidate_id": record.get("selected_candidate_id"),
                        "selected_option_ids": record.get("selected_option_ids", []),
                        "selected_score": selected.get("total") if selected else None,
                        "score_components": [
                            component
                            for component in (selected or {}).get("components", [])
                            if component.get("value")
                        ][:6],
                        "explanation": record.get("explanation"),
                    }
                rows.append(row)
                if result["status"] != "COMMITTED" or result["match"]["state"]["terminal_result"] is not None:
                    break
        finally:
            metadata = self._read_metadata(match_id)
            metadata["local_auto_running"] = False
            self._write_metadata(match_id, metadata)
        return {"schema": "TianxiaFactoryCombatLocalRun.v1", "steps": rows, "match": self.get_match(match_id)}

    def final_summary(self, match_id: str, *, session: Any = None) -> dict[str, Any]:
        """Verify once per exact terminal input set; file changes invalidate reuse.

        A view may pass its already loaded session to avoid a second disk replay.
        Every independent request still loads and validates the saved match.
        """
        from .terminal_summary_cache import identity, without_summary

        session = session if session is not None else self._load_session(match_id)
        if session.match_id != match_id:
            raise ValueError("summary session belongs to another match")
        if session.engine.state.terminal_result is None:
            return self._build_final_summary(match_id, session)
        before = identity(session.store.match_dir)
        key = (before, canonical_state_sha256(session.engine.state))
        cached = self._terminal_summaries.get(match_id, key)
        if cached is not None:
            return cached
        summary = self._build_final_summary(match_id, session)
        after = identity(session.store.match_dir)
        summary_hash = hashlib.sha256(canonical_bytes(summary) + b"\n").hexdigest()
        if (without_summary(before) == without_summary(after)
                and dict(after).get("FinalSummary.json") == summary_hash):
            self._terminal_summaries.put(match_id, (after, key[1]), summary)
        return summary

    def _build_final_summary(self, match_id: str, session: Any) -> dict[str, Any]:
        """The original complete replay, controller verification and byte check."""
        state = session.engine.state
        if state.terminal_result is None:
            raise self._error("COMBAT_MATCH_NOT_COMPLETE", "A final summary is available only after the fight is complete.", subsystem="combat.gate5.summary", retry_safe=True, recommended_action="Continue the fight to an authoritative terminal result.", match_id=match_id, status_code=409)
        store = session.store
        metadata = self._read_metadata(match_id, session)
        genesis_doc = json.loads(store.genesis_path.read_text(encoding="utf-8"))
        genesis_state = genesis_doc.get("state") or {}
        initial_actors = genesis_state.get("actors") or {}
        if isinstance(initial_actors, list): initial_actors = {row["entity_id"]: row for row in initial_actors}
        journal = _read_jsonl(store.journal_path)
        commits = [row for row in journal if row.get("record_type") == "COMMIT"]
        finalized = [row for row in journal if row.get("record_type") == "MATCH_FINALIZED"]
        verification = session.verify()
        # Verification already validates transactions, replays every commit and
        # compares that result with the loaded state. The summary uses only
        # these three replay fields; constructing the unused full replay repeats
        # the expensive reduction. Reuse the verified result, never a cache or
        # a saved PASS flag.
        replay = {key: verification[key] for key in ("status", "canonical_state_sha256", "terminal_result")}
        controller_rows = _read_jsonl(session.controller_journal_path)
        # The verified genesis/journal is the event authority for every ability.
        # A just-committed session still holds raw events from its last action;
        # persistence enriches copies with replay fields, visible after reload.
        # Project the durable documents so terminal reads have identical bytes.
        summary_events = list(genesis_doc.get("initial_events") or [])
        summary_events.extend(event for commit in commits for event in commit["events"])
        reaction_events = [event for event in summary_events if "REACTION" in event["event_type"]
                           or event["event_type"] == "DAMAGE_APPLICATION" and event.get("payload", {}).get("reaction")]
        setup = metadata.get("c3c_setup_binding") or genesis_doc.get("c3c_setup_binding") or {}
        portable_authority = None
        runtime_path = store.match_dir / RUNTIME_AUTHORITY_FILE
        source_package_path = store.match_dir / SOURCE_PACKAGE_FILE
        if runtime_path.is_file():
            authority = PortableRuntimeAuthority.model_validate_json(runtime_path.read_text(encoding="utf-8"))
            if not source_package_path.is_file() or sha256_file(source_package_path) != authority.package_sha256:
                raise self._error(
                    "COMBAT_SOURCE_PACKAGE_IDENTITY_MISMATCH",
                    "The match-local source Character package no longer matches the bound runtime authority.",
                    subsystem="combat.c3d.summary", retry_safe=False,
                    recommended_action="Restore the exact completed match directory before summary or export.",
                    match_id=match_id, status_code=409,
                )
            portable_authority = {
                "runtime_actor_id": authority.runtime_actor_id,
                "project_id": authority.project_id,
                "project_revision": authority.project_revision,
                "package_sha256": authority.package_sha256,
                "event_head_hash": authority.event_head_hash,
                "replay_state_hash": authority.replay_state_hash,
                "content_lock_hash": authority.content_lock_hash,
                "combat_sheet_id": authority.combat_sheet_id,
                "combat_sheet_commitment_sha256": authority.combat_sheet_commitment_sha256,
                "mechanics_lock_sha256": authority.mechanics_lock_sha256,
                "primitive_registry_sha256": authority.primitive_registry_sha256,
                "runtime_adapter_id": authority.runtime_adapter_id,
                "runtime_adapter_version": authority.runtime_adapter_version,
                "runtime_engine_version": authority.runtime_engine_version,
                "actor_template_commitment_sha256": authority.actor_template_commitment_sha256,
                "authority_sha256": authority.authority_sha256,
                "source_package_relative_path": SOURCE_PACKAGE_FILE,
                "source_package_mutated": False,
                "display_prose_parsed": False,
            }
        actors=[]; defeated=[]
        mode_history={}
        for row in controller_rows:
            aid=row.get("actor_id") or (row.get("primary_decision_record") or {}).get("actor_id")
            if aid:
                mode=row.get("controller_mode") or row.get("control_mode") or row.get("choice_path") or "LOCAL_AUTO"
                mode_history.setdefault(aid,[])
                if mode not in mode_history[aid]: mode_history[aid].append(mode)
        for actor in sorted(state.actors.values(), key=lambda a:a.entity_id):
            before=initial_actors.get(actor.entity_id,{})
            initial_resources=before.get("resources") or {}
            spent={k:max(0,int(initial_resources.get(k,0))-int(v)) for k,v in sorted(actor.resources.items())}
            status="ACTIVE" if actor.active else ("DEFEATED" if actor.current_hp<=0 else "INACTIVE")
            if status=="DEFEATED": defeated.append(actor.entity_id)
            actors.append({
                "entity_id":actor.entity_id,"display_name":actor.display_name,"team_id":actor.team_id,
                "primary_combatant":actor.primary_combatant,"owner_id":actor.owner_id,"status":status,
                "final_hp":{"current":actor.current_hp,"maximum":actor.maximum_hp},
                "resources_remaining":dict(sorted(actor.resources.items())),"resources_spent":spent,
                "conditions":sorted(c.condition_id for c in actor.conditions.values()),
                "position":actor.position.model_dump(mode="json"),
                "controller_modes_used":mode_history.get(actor.owner_id or actor.entity_id, [metadata.get("participant_control_modes",{}).get(actor.owner_id or actor.entity_id,"MANUAL")]),
            })
        term=state.terminal_result.model_dump(mode="json")
        # Preserve the accepted C3C-P3 summary byte contract for built-in
        # matches.  C3D setup and team projections are package-only extensions.
        if portable_authority is None:
            setup_commitment = metadata.get("c3c_preflight_commitment")
            battlefield_id = setup.get("battlefield_id")
            teams = setup.get("team_names") or metadata.get("team_names") or {}
        else:
            setup_commitment = metadata.get("c3c_preflight_commitment") or setup.get("preflight_commitment")
            battlefield_id = (setup.get("battlefield") or {}).get("stable_id") or setup.get("battlefield_id") or metadata.get("battlefield_id")
            teams = {row.get("team_id"): row.get("display_name") for row in setup.get("teams", [])} or setup.get("team_names") or metadata.get("team_names") or {}
        summary={
            "schema":"TianxiaFactoryCombatFinalSummary.v1","match_id":match_id,
            "setup_commitment":setup_commitment,
            "setup_binding_sha256":metadata.get("c3c_setup_binding_sha256"),
            "battlefield_id":battlefield_id,
            "grid_calibration":setup.get("grid_calibration"),
            "dynamic_roster":[r.get("actor_id") for r in setup.get("participants",[])],
            "teams":teams,
            "companion_ownership":[{"entity_id":a.entity_id,"owner_id":a.owner_id,"team_id":a.team_id} for a in state.actors.values() if not a.primary_combatant],
            "terminal_result":term,"final_state_sha256":canonical_state_sha256(state),
            "rounds":state.round_number,"actors":actors,"defeated_entities":sorted(defeated),
            "reactions_recorded":reaction_events,
            "controller_mode_history":{k:v for k,v in sorted(mode_history.items())},
            "counts":{"events":len(session.engine.events),"rolls":len(session.engine.rolls),"commits":len(commits),"controller_records":len(controller_rows),"finalization_records":len(finalized)},
            "verification":{"status":verification.get("status"),"canonical_state_sha256":verification.get("canonical_state_sha256") or verification.get("state_sha256")},
            "replay":{"status":replay.get("status"),"canonical_state_sha256":replay.get("canonical_state_sha256"),"terminal_result":replay.get("terminal_result")},
            "dao_iching_audit_references":[name for name in ("DaoIChingChoiceAudit.ndjson","C3C_Post_Round_Dao_IChing_Audit.json") if (store.match_dir/name).is_file()],
            "source_mutation":"No Character Package or Factory project was mutated.",
        }
        if portable_authority is not None:
            summary["portable_character_authority"] = portable_authority
        path=store.match_dir/"FinalSummary.json"
        payload=canonical_bytes(summary)+b"\n"
        if path.exists():
            existing=path.read_bytes()
            if existing!=payload:
                raise self._error("COMBAT_FINAL_SUMMARY_MISMATCH","The stored final summary does not match the authoritative terminal state.",subsystem="combat.gate5.summary",retry_safe=False,recommended_action="Verify the match and restore the exact terminal files.",match_id=match_id,status_code=409)
        else:
            _atomic_json(path,summary)
        return summary

    # ------------------------------------------------------------------
    # Persistence, replay, export
    # ------------------------------------------------------------------
    def snapshot(self, match_id: str) -> dict[str, Any]:
        session = self._load_session(match_id)
        path = session.mechanical.explicit_snapshot()
        return {"schema": "TianxiaFactoryCombatSnapshot.v1", "match_id": match_id, "relative_path": str(path.relative_to(session.store.match_dir)), "sha256": sha256_file(path)}

    def verify(self, match_id: str) -> dict[str, Any]:
        return self._load_session(match_id).verify()

    def replay(self, match_id: str) -> dict[str, Any]:
        return self._load_session(match_id).mechanical.replay()

    def export(self, match_id: str) -> Path:
        session = self._load_session(match_id)
        try:
            # Preserve the accepted C3C-P3 export contract for built-in matches.
            # Portable-character matches have the stricter C3D legal-final gate below.
            if getattr(session.engine, "runtime_authority", None) is None:
                session.mechanical.export()
                destination = self.exports_root / f"Tianxia_Factory_Combat_{match_id.replace(':', '_')}.zip"
                root = session.store.match_dir
                files = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".writer.lock"]
                hashes = {_safe_zip_name(path, root): sha256_file(path) for path in files}
                checksum_text = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))
                temporary = destination.with_suffix(".zip.tmp")
                with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                    for path in files:
                        archive.write(path, _safe_zip_name(path, root))
                    archive.writestr("SHA256SUMS.txt", checksum_text)
                os.replace(temporary, destination)
                return destination
            if session.engine.state.terminal_result is None:
                raise self._error(
                    "COMBAT_MATCH_NOT_COMPLETE",
                    "Only an authoritative terminal match can be exported as a final combat package.",
                    subsystem="combat.c3d.export", retry_safe=True,
                    recommended_action="Complete and finalize the fight before exporting.",
                    match_id=match_id, status_code=409,
                )
            summary = self.final_summary(match_id)
            verification = session.verify()
            replay = session.mechanical.replay()
            final_state_sha = summary["final_state_sha256"]
            if (
                verification.get("status") != "PASS"
                or replay.get("status") != "PASS"
                or verification.get("canonical_state_sha256") != final_state_sha
                or replay.get("canonical_state_sha256") != final_state_sha
                or replay.get("terminal_result") != summary.get("terminal_result")
            ):
                raise ValueError("C3D_FINAL_VERIFICATION_OR_REPLAY_MISMATCH")
            journal = _read_jsonl(session.store.journal_path)
            finalization_count = sum(1 for row in journal if row.get("record_type") == "MATCH_FINALIZED")
            if finalization_count != 1:
                raise ValueError(f"C3D_FINALIZATION_COUNT_INVALID:{finalization_count}")
            session.mechanical.export()
            portable = summary.get("portable_character_authority")
            final_verification = {
                "schema": "TianxiaFactoryCombatFinalVerification.v1",
                "match_id": match_id,
                "status": "PASS",
                "canonical_state_sha256": final_state_sha,
                "canonical_event_log_sha256": replay.get("canonical_event_log_sha256"),
                "canonical_roll_log_sha256": replay.get("canonical_roll_log_sha256"),
                "terminal_result": summary.get("terminal_result"),
                "finalization_record_count": finalization_count,
                "final_summary_sha256": canonical_sha256(summary),
                "verification": {k: verification.get(k) for k in ("status", "canonical_state_sha256", "event_count", "roll_count", "state_version")},
                "replay": {k: replay.get(k) for k in ("status", "canonical_state_sha256", "canonical_event_log_sha256", "canonical_roll_log_sha256", "terminal_result")},
                "portable_character_authority_sha256": portable.get("authority_sha256") if portable else None,
            }
            export_authority = {
                "schema": "TianxiaFactoryCombatFinalExportAuthority.v1",
                "match_id": match_id,
                "status": "LEGAL_FINAL_COMBAT_EXPORT",
                "source_package": portable,
                "setup_commitment": summary.get("setup_commitment"),
                "setup_binding_sha256": summary.get("setup_binding_sha256"),
                "final_summary_sha256": canonical_sha256(summary),
                "final_verification_sha256": canonical_sha256(final_verification),
                "journal_sha256": sha256_file(session.store.journal_path),
                "controller_journal_sha256": sha256_file(session.controller_journal_path) if session.controller_journal_path.is_file() else None,
                "canonical_event_log_sha256": replay.get("canonical_event_log_sha256"),
                "canonical_roll_log_sha256": replay.get("canonical_roll_log_sha256"),
                "terminal_result": summary.get("terminal_result"),
                "finalization_record_count": finalization_count,
                "character_package_mutated": False,
                "factory_project_mutated": False,
                "contains_character_advancement": False,
                "contains_rewards": False,
                "contains_injuries": False,
                "contains_loot": False,
                "contains_narrative": False,
                "native_windows_acceptance_claimed": False,
            }
            _write_once_exact_json(session.store.match_dir / "FinalVerification.json", final_verification)
            _write_once_exact_json(session.store.match_dir / "ExportAuthority.json", export_authority)
            destination = self.exports_root / f"Tianxia_Factory_Combat_{match_id.replace(':', '_')}.zip"
            root = session.store.match_dir
            files = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name != ".writer.lock"]
            hashes = {_safe_zip_name(path, root): sha256_file(path) for path in files}
            checksum_text = "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items()))
            temporary = destination.with_suffix(".zip.tmp")
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path in files:
                    archive.write(path, _safe_zip_name(path, root))
                archive.writestr("SHA256SUMS.txt", checksum_text)
            os.replace(temporary, destination)
            return destination
        except CombatServiceError:
            raise
        except Exception as exc:
            raise self._error(
                "COMBAT_EXPORT_FAILED",
                "The persistent combat match could not be exported.",
                subsystem="combat.gate5.export",
                retry_safe=True,
                recommended_action="Verify the terminal match, confirm the local export directory is writable, and retry.",
                match_id=match_id,
                details={"reason": str(exc)},
                status_code=500,
            ) from exc

    # ------------------------------------------------------------------
    # Manual AI clipboard bridge
    # ------------------------------------------------------------------
    def ai_frame(self, match_id: str) -> dict[str, Any]:
        decision = self.decision(match_id)
        context = decision["context"]
        compact_candidates = [
            {
                "candidate_id": row["candidate_id"],
                "source_definition_id": row["source_definition_id"],
                "display_name": row["display_name"],
                "kind": row["kind"],
                "actor_id": row["actor_id"],
                "target_ids": row["target_ids"],
                "destination": row["destination"],
                "option_ids": row["option_ids"],
                "metadata": row.get("metadata", {}),
            }
            for row in context["legal_candidates"]
        ]
        frame = {
            "schema": AI_FRAME_SCHEMA,
            "match_id": match_id,
            "decision_id": context["decision_id"],
            "state_version": context["state_version"],
            "round_number": context["round_number"],
            "active_actor_id": context["active_actor_id"],
            "actors": context["actors"],
            "zones": context["zones"],
            "legal_candidates": compact_candidates,
            "policy_context": {
                "policy_id": context["policy"]["policy_id"],
                "role": context["policy"]["role"],
                "team_behavior": context["team_behavior"],
            },
            "recent_events": context["recent_events"][-8:],
            "response_schema": {
                "schema": AI_RESPONSE_SCHEMA,
                "action_intent": {
                    "decision_id": context["decision_id"],
                    "state_version": context["state_version"],
                    "candidate_id": "COPY_ONE_LISTED_CANDIDATE_ID",
                    "actor_id": context["active_actor_id"],
                    "target_ids": "COPY_EXACT_LISTED_TARGET_IDS",
                    "destination": "COPY_EXACT_LISTED_DESTINATION_OR_NULL",
                    "option_ids": "LISTED_OPTION_IDS_ONLY",
                    "placement_destination": "For placement_picker rows, omit to receive a second frame containing EVERY legal square; then copy one listed placement_destination.",
                },
                "rationale": "optional short explanation",
            },
        }
        text = (
            "Choose exactly one legal Tianxia combat candidate. Return JSON only. "
            "Do not invent mechanics, rolls, targets, options, positions, resources, conditions, HP changes, or state mutations.\n\n"
            + json.dumps(frame, ensure_ascii=False, indent=2)
        )
        return {"schema": AI_FRAME_SCHEMA, "frame": frame, "frame_text": text}

    def ai_validate(self, match_id: str, payload: dict[str, Any], rationale: str | None = None) -> dict[str, Any]:
        from .gate4_models import DecisionContext
        session = self._load_session(match_id)
        context = DecisionContext.model_validate(self.decision(match_id, session=session)["context"])
        from .placement_menu import context_for_payload
        context = context_for_payload(session.engine, context, payload)
        intent = self._intent_from_payload(context, payload)
        token_payload = {
            "match_id": match_id,
            "decision_id": intent.decision_id,
            "state_version": intent.state_version,
            "intent": intent.model_dump(mode="json"),
        }
        return {
            "schema": "TianxiaFactoryCombatAIIntentValidation.v1",
            "status": "VALID",
            "validation_token": f"checked:{canonical_sha256(token_payload)[:32]}",
            "intent": intent.model_dump(mode="json"),
            "rationale": (rationale or "")[:1000],
            "legality": {
                "match_id": match_id,
                "decision_id": intent.decision_id,
                "state_version": intent.state_version,
                "candidate_id": intent.candidate_id,
                "targets": list(intent.target_ids),
                "destination": intent.destination.model_dump(mode="json") if intent.destination else None,
                "options": list(intent.option_ids),
            },
        }

    def ai_execute(self, match_id: str, payload: dict[str, Any], validation_token: str, rationale: str | None = None,
                   *, reactions: list[dict[str, Any]] | None = None, _resuming_provider: bool = False) -> dict[str, Any]:
        validated = self.ai_validate(match_id, payload, rationale)
        if validation_token != validated["validation_token"]:
            raise self._error(
                "COMBAT_AI_INTENT_INVALID",
                "The checked AI decision token does not match the exact current intent.",
                subsystem="combat.gate5.ai_bridge",
                retry_safe=True,
                recommended_action="Check the pasted decision again against the current match before execution.",
                match_id=match_id,
                decision_id=payload.get("decision_id"),
                status_code=409,
            )
        if not _resuming_provider:
            session = self._load_session(match_id)
            metadata = self._read_metadata(match_id, session)
            pending = metadata.get('pending_provider_decision')
            if pending is not None and pending['validation_token'] == validation_token:
                return self._resume_provider_decision(session, metadata, pending, reactions)
        try:
            result = self._commit_previewed(match_id, payload, list(reactions or []), None, reject_unused_reactions=True)
        except CombatServiceError as error:
            if error.diagnostic.code != 'COMBAT_REACTION_DECISION_REQUIRED':
                raise
            session = self._load_session(match_id)
            return {'status': 'AWAITING_REACTION', 'reaction_context': error.diagnostic.details['reaction_context'],
                    'match': self._match_view(session, self._read_metadata(match_id, session))}
        return {'status': 'COMMITTED', **result}
