"""Deterministic Factory DM controller and persistence/replay authority."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from threading import RLock
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .domain import (
    Ability,
    CampaignIdentity,
    CanonClaim,
    CanonEntry,
    CanonStatus,
    Character,
    CharacterBrief,
    CharacterKind,
    CombatActionRecord,
    CombatState,
    CombatStatus,
    Combatant,
    DeterministicClock,
    DomainError,
    Faction,
    GameState,
    KnowledgeFact,
    Location,
    NarrativeThread,
    Provenance,
    Relationship,
    Resource,
    SceneIntention,
    SceneLine,
    SceneState,
    SourceKind,
    StatusEffect,
    ThreadStatus,
    Trait,
    WorldFact,
    _ability_from,
    _brief_from,
    _campaign_from,
    _canon_from,
    _claim_from,
    _character_from,
    _combat_from,
    _faction_from,
    _intention_from,
    _line_from,
    _location_from,
    _primitive,
    _provenance_from,
    _record_from,
    _scene_from,
    _thread_from,
    _world_fact_from,
    _bool,
    _id,
    _int,
    _text,
    empty_state,
    replace_canon_entries,
    replace_character,
    replace_scene,
    replace_thread,
    state_digest,
    state_from_dict,
    state_to_dict,
    validate_state,
)


class EngineError(DomainError):
    """A rejected command or invalid persisted record."""

    def __init__(self, message: str, *, code: str = "invalid_command", field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EngineError("value is not canonical JSON", code="invalid_canonical_value") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _exact(data: Any, keys: set[str], field: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise EngineError(f"{field} must be an object", field=field)
    if set(data) != keys:
        raise EngineError(f"{field} keys are not exact", field=field)
    return data


def _find(items: Sequence[Any], attribute: str, value: str, field: str) -> Any:
    for item in items:
        if getattr(item, attribute) == value:
            return item
    raise EngineError(f"unknown {field}: {value}", code="unknown_reference", field=field)


def _replace_by_id(items: Sequence[Any], attribute: str, replacement: Any) -> tuple[Any, ...]:
    return tuple(replacement if getattr(item, attribute) == getattr(replacement, attribute) else item for item in items)


def _write_create_once(path: Path, content: bytes) -> None:
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise EngineError(f"persistence target already exists: {path.name}", code="create_once_collision")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor != -1:
            os.close(descriptor)


def _read_regular(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise EngineError(f"{label} must be a regular non-symlink file", code="unsafe_persistence_input")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EngineError(f"{label} could not be read", code="persistence_read_failed") from exc


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_json(content: bytes, label: str) -> Any:
    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise EngineError(f"{label} is not strict UTF-8 JSON", code="malformed_persistence") from exc


@dataclass(frozen=True)
class Event:
    schema_version: int
    event_id: str
    sequence: int
    operation: str
    payload: dict[str, Any]
    pre_state_digest: str
    post_state_digest: str
    previous_event_hash: str
    clock_tick: int
    event_hash: str

    def unsigned(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "sequence": self.sequence,
            "operation": self.operation,
            "payload": self.payload,
            "pre_state_digest": self.pre_state_digest,
            "post_state_digest": self.post_state_digest,
            "previous_event_hash": self.previous_event_hash,
            "clock_tick": self.clock_tick,
        }

    def as_dict(self) -> dict[str, Any]:
        return {**self.unsigned(), "event_hash": self.event_hash}

    @classmethod
    def from_dict(cls, value: Any) -> "Event":
        data = _exact(value, {"schema_version", "event_id", "sequence", "operation", "payload", "pre_state_digest", "post_state_digest", "previous_event_hash", "clock_tick", "event_hash"}, "event")
        fields = {
            "schema_version": data["schema_version"],
            "event_id": data["event_id"],
            "sequence": data["sequence"],
            "operation": data["operation"],
            "payload": data["payload"],
            "pre_state_digest": data["pre_state_digest"],
            "post_state_digest": data["post_state_digest"],
            "previous_event_hash": data["previous_event_hash"],
            "clock_tick": data["clock_tick"],
        }
        expected_schema = 2 if fields["operation"] in {"gameplay_bind", "gameplay_command"} else 1
        if type(fields["schema_version"]) is not int or fields["schema_version"] != expected_schema:
            raise EngineError("event schema version is invalid", code="event_schema_invalid")
        if not isinstance(fields["event_id"], str) or not fields["event_id"].startswith("event-"):
            raise EngineError("event id is invalid", code="event_schema_invalid")
        if not isinstance(fields["sequence"], int) or isinstance(fields["sequence"], bool) or fields["sequence"] < 1:
            raise EngineError("event sequence is invalid", code="event_schema_invalid")
        if not isinstance(fields["operation"], str) or not fields["operation"]:
            raise EngineError("event operation is invalid", code="event_schema_invalid")
        if not isinstance(fields["payload"], Mapping):
            raise EngineError("event payload is invalid", code="event_schema_invalid")
        for name in ("pre_state_digest", "post_state_digest", "previous_event_hash", "event_hash"):
            value_text = data[name]
            if not isinstance(value_text, str) or len(value_text) != 64 or any(char not in "0123456789abcdef" for char in value_text):
                raise EngineError(f"event {name} is not a lowercase SHA-256 digest", code="event_schema_invalid")
        if not isinstance(fields["clock_tick"], int) or isinstance(fields["clock_tick"], bool) or fields["clock_tick"] < 0:
            raise EngineError("event clock tick is invalid", code="event_schema_invalid")
        candidate = cls(event_hash=data["event_hash"], **fields)
        if _digest(candidate.unsigned()) != candidate.event_hash:
            raise EngineError("event hash does not match event bytes", code="event_hash_mismatch")
        return candidate


class CampaignController:
    """The sole mutation authority for one deterministic campaign."""

    def __init__(self) -> None:
        self._state = empty_state()
        self._events: list[Event] = []
        self._lock = RLock()

    @classmethod
    def new(cls) -> "CampaignController":
        return cls()

    def state_digest(self) -> str:
        return state_digest(self._state)

    def event_count(self) -> int:
        return len(self._events)

    def campaign_id(self) -> str | None:
        return None if self._state.campaign is None else self._state.campaign.campaign_id

    def view(self) -> dict[str, Any]:
        """Return a detached deep copy; no live mutable state is exposed."""

        return copy.deepcopy(state_to_dict(self._state))

    def events_view(self) -> list[dict[str, Any]]:
        return copy.deepcopy([event.as_dict() for event in self._events])

    def _advance_clock(self, state: GameState) -> GameState:
        if state.campaign is None:
            raise EngineError("campaign is not created", code="campaign_required")
        return replace(state, campaign=replace(state.campaign, clock=state.campaign.clock.advance()))

    def _commit(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            return self._commit_locked(operation, payload)

    def _commit_locked(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        payload_copy = copy.deepcopy(dict(payload))
        pre_digest = state_digest(self._state)
        staged = copy.deepcopy(self._state)
        staged = self._apply_operation(staged, operation, payload_copy)
        if operation != "create_campaign":
            staged = self._advance_clock(staged)
        validate_state(staged)
        post_digest = state_digest(staged)
        sequence = len(self._events) + 1
        previous = self._events[-1].event_hash if self._events else "0" * 64
        clock_tick = staged.campaign.clock.tick if staged.campaign is not None else 0
        unsigned = {
            "schema_version": 2 if operation in {"gameplay_bind", "gameplay_command"} else 1,
            "event_id": f"event-{sequence:06d}",
            "sequence": sequence,
            "operation": operation,
            "payload": payload_copy,
            "pre_state_digest": pre_digest,
            "post_state_digest": post_digest,
            "previous_event_hash": previous,
            "clock_tick": clock_tick,
        }
        event = Event(**unsigned, event_hash=_digest(unsigned))
        # State and event are assigned only after every validation above passes.
        self._state = staged
        self._events.append(event)
        return {
            "accepted": True,
            "event_id": event.event_id,
            "event_hash": event.event_hash,
            "state_digest": post_digest,
            "event_count": len(self._events),
        }

    def _apply_operation(self, state: GameState, operation: str, payload: Mapping[str, Any]) -> GameState:
        if operation in {"gameplay_bind", "gameplay_command"}:
            from .gameplay.integration import bind, apply_record
            try:
                if state.campaign is None:
                    raise EngineError("campaign required", code="campaign_required")
                if operation == "gameplay_bind":
                    parent = payload["parent"]
                    if (parent["event_count"] != len(self._events)
                            or parent["event_hash"] != (self._events[-1].event_hash if self._events else "0" * 64)):
                        raise EngineError("migration parent event mismatch", code="migration_parent_mismatch")
                    return bind(state, payload)
                command = payload["command"]
                self._validate_gameplay_request(command, replay=True)
                return apply_record(state, payload)
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                if isinstance(exc, EngineError):
                    raise
                raise EngineError(str(exc), code=getattr(exc, "code", "invalid_gameplay")) from exc
        if state.gameplay is not None and operation in {"start_combat", "combat_action"}:
            raise EngineError("gameplay combat mapping is not admitted", code="gameplay_combat_unsupported")
        if operation == "create_campaign":
            data = _exact(payload, {"identity"}, "create_campaign")
            if state.campaign is not None:
                raise EngineError("campaign already exists", code="campaign_already_exists")
            identity = _campaign_from(data["identity"])
            assert identity is not None
            return replace(state, campaign=identity)
        if state.campaign is None:
            raise EngineError("campaign must be created first", code="campaign_required")
        if operation == "add_location":
            data = _exact(payload, {"location"}, operation)
            location = _location_from(data["location"])
            if any(item.location_id == location.location_id for item in state.locations):
                raise EngineError("location id already exists", code="duplicate_id", field="location_id")
            return replace(state, locations=(*state.locations, location))
        if operation == "add_faction":
            data = _exact(payload, {"faction"}, operation)
            faction = _faction_from(data["faction"])
            if any(item.faction_id == faction.faction_id for item in state.factions):
                raise EngineError("faction id already exists", code="duplicate_id", field="faction_id")
            return replace(state, factions=(*state.factions, faction))
        if operation == "add_world_fact":
            data = _exact(payload, {"fact"}, operation)
            fact = _world_fact_from(data["fact"])
            if any(item.fact_id == fact.fact_id for item in state.world_facts):
                raise EngineError("world fact id already exists", code="duplicate_id", field="fact_id")
            return replace(state, world_facts=(*state.world_facts, fact))
        if operation == "create_character":
            data = _exact(payload, {"character"}, operation)
            character = _character_from(data["character"])
            if character.kind is CharacterKind.PLAYER:
                raise EngineError("player characters require an external CharacterBrief", code="brief_required")
            self._validate_character_constraints(state, character)
            if any(item.character_id == character.character_id for item in state.characters):
                raise EngineError("character id already exists", code="duplicate_id", field="character_id")
            return replace(state, characters=(*state.characters, character))
        if operation == "create_character_from_brief":
            data = _exact(payload, {"character", "brief"}, operation)
            character = _character_from(data["character"])
            brief = _brief_from(data["brief"])
            self._validate_character_against_brief(state, character, brief)
            if any(item.character_id == character.character_id for item in state.characters):
                raise EngineError("character id already exists", code="duplicate_id", field="character_id")
            return replace(state, characters=(*state.characters, character))
        if operation == "grant_knowledge":
            data = _exact(payload, {"character_id", "knowledge"}, operation)
            character = _find(state.characters, "character_id", _id(data["character_id"], "character_id"), "character")
            knowledge_data = _exact(data["knowledge"], {"fact_id", "source", "confidence"}, "knowledge")
            knowledge = KnowledgeFact(knowledge_data["fact_id"], knowledge_data["source"], knowledge_data["confidence"])
            if knowledge.fact_id not in {item.fact_id for item in state.world_facts} and knowledge.fact_id not in {item.entry_id for item in state.canon}:
                raise EngineError("knowledge references an unknown fact", code="unknown_reference", field="knowledge.fact_id")
            if knowledge.fact_id in {item.fact_id for item in character.knowledge}:
                raise EngineError("character already knows this fact", code="duplicate_knowledge")
            updated = replace(character, knowledge=(*character.knowledge, knowledge))
            return replace_character(state, updated)
        if operation == "open_scene":
            data = _exact(payload, {"scene"}, operation)
            scene = _scene_from(data["scene"])
            if any(item.scene_id == scene.scene_id for item in state.scenes):
                raise EngineError("scene id already exists", code="duplicate_id", field="scene_id")
            _find(state.locations, "location_id", scene.location_id, "location")
            for participant in scene.participants:
                character = _find(state.characters, "character_id", participant, "participant")
                if character.location_id != scene.location_id:
                    raise EngineError("all scene participants must be at the scene location", code="scene_authorization")
            facts = {item.fact_id: item for item in state.world_facts}
            if any(item not in facts or not facts[item].public for item in scene.public_facts):
                raise EngineError("scene public facts must reference public world facts", code="scene_public_fact_invalid")
            for line in scene.lines:
                if line.actor_id not in scene.participants:
                    raise EngineError("scene line actor is not a participant", code="scene_authorization")
                self._validate_knowledge_claims(state, scene, line.actor_id, line.knowledge_claims)
                self._validate_mention_guard(state, scene, line.actor_id, line.text, line.knowledge_claims, field="line.text")
            for intention in scene.intentions:
                if intention.actor_id not in scene.participants:
                    raise EngineError("scene intention actor is not a participant", code="scene_authorization")
                self._validate_knowledge_claims(state, scene, intention.actor_id, intention.knowledge_claims)
                self._validate_mention_guard(state, scene, intention.actor_id, intention.text, intention.knowledge_claims, field="intention.text")
            return replace(state, scenes=(*state.scenes, scene))
        if operation == "scene_line":
            data = _exact(payload, {"line", "scene_id"}, operation)
            scene = _find(state.scenes, "scene_id", _id(data["scene_id"], "scene_id"), "scene")
            if not scene.open:
                raise EngineError("scene is closed", code="scene_closed")
            line = _line_from(data["line"])
            if line.actor_id not in scene.participants:
                raise EngineError("actor is not authorized for this scene", code="scene_authorization")
            self._validate_knowledge_claims(state, scene, line.actor_id, line.knowledge_claims)
            self._validate_mention_guard(state, scene, line.actor_id, line.text, line.knowledge_claims, field="line.text")
            if any(item.line_id == line.line_id for item in scene.lines):
                raise EngineError("scene line id already exists", code="duplicate_id")
            return replace_scene(state, replace(scene, lines=(*scene.lines, line)))
        if operation == "scene_intention":
            data = _exact(payload, {"scene_id", "intention"}, operation)
            scene = _find(state.scenes, "scene_id", _id(data["scene_id"], "scene_id"), "scene")
            intention = _intention_from(data["intention"])
            if intention.actor_id not in scene.participants:
                raise EngineError("actor is not authorized for this scene", code="scene_authorization")
            self._validate_knowledge_claims(state, scene, intention.actor_id, intention.knowledge_claims)
            self._validate_mention_guard(state, scene, intention.actor_id, intention.text, intention.knowledge_claims, field="intention.text")
            if any(item.intention_id == intention.intention_id for item in scene.intentions):
                raise EngineError("scene intention id already exists", code="duplicate_id")
            return replace_scene(state, replace(scene, intentions=(*scene.intentions, intention)))
        if operation == "start_combat":
            data = _exact(payload, {"combat"}, operation)
            if state.combat is not None and state.combat.status is CombatStatus.ACTIVE:
                raise EngineError("another combat is active", code="combat_already_active")
            combat = _combat_from(data["combat"])
            scene = _find(state.scenes, "scene_id", combat.scene_id, "scene")
            if not scene.open:
                raise EngineError("combat scene is closed", code="scene_closed")
            expected_order = tuple(sorted(combat.combatants, key=lambda item: (-item.initiative, item.character_id)))
            if combat.status is not CombatStatus.ACTIVE or combat.round != 1 or combat.turn_index != 0 or combat.records:
                raise EngineError("new combat must start active at turn zero with no records", code="combat_initial_state")
            # Normalize caller order at the authority boundary.  Initiative and
            # identifier tie-breaking, rather than input order, define the
            # deterministic first turn.
            combat = replace(combat, combatants=expected_order, turn_index=0)
            for combatant in combat.combatants:
                character = _find(state.characters, "character_id", combatant.character_id, "combatant")
                if character.location_id != scene.location_id:
                    raise EngineError("combatant is not at scene location", code="combat_authorization")
                for resource_name in ("health", "stamina"):
                    character.resource(resource_name)
                if character.resource("health").current <= 0:
                    raise EngineError("combat cannot start with a nonliving combatant", code="combat_nonliving")
            return replace(state, combat=combat)
        if operation == "combat_action":
            return self._apply_combat_action(state, payload)
        if operation == "create_thread":
            data = _exact(payload, {"thread"}, operation)
            thread = _thread_from(data["thread"])
            if thread.status is not ThreadStatus.SETUP or thread.progress != 0 or thread.unresolved_dependencies != thread.prerequisites:
                raise EngineError("new threads must start in SETUP at progress 0 with every prerequisite unresolved", code="thread_initial_state")
            if any(item.thread_id == thread.thread_id for item in state.threads):
                raise EngineError("thread id already exists", code="duplicate_id")
            return replace(state, threads=(*state.threads, thread))
        if operation == "thread_update":
            return self._apply_thread_update(state, payload)
        if operation == "canon_candidate":
            return self._apply_canon_candidate(state, payload)
        raise EngineError(f"unknown operation: {operation}", code="unknown_operation")

    def _validate_character_constraints(self, state: GameState, character: Character) -> None:
        _find(state.locations, "location_id", character.location_id, "location")
        _find(state.factions, "faction_id", character.faction_id, "faction")
        if character.kind is CharacterKind.PLAYER:
            if len(character.traits) > 4 or len(character.abilities) > 4:
                raise EngineError("player character exceeds constrained brief limits", code="character_constraint")
            if character.resource("health").maximum > 20 or character.resource("stamina").maximum > 10:
                raise EngineError("player resources exceed constrained limits", code="character_constraint")
        known = {item.fact_id for item in state.world_facts if item.public}
        if any(item.fact_id not in known for item in character.knowledge):
            raise EngineError("character knowledge references an unknown fact", code="knowledge_boundary")

    def _validate_character_against_brief(self, state: GameState, character: Character, brief: CharacterBrief) -> None:
        if character.character_id != brief.character_id:
            raise EngineError("character id does not match the external brief", code="brief_mismatch", field="character_id")
        if character.kind is not brief.kind:
            raise EngineError("character kind does not match the external brief", code="brief_mismatch", field="kind")
        if character.faction_id != brief.faction_id or character.location_id != brief.location_id:
            raise EngineError("character campaign bindings do not match the external brief", code="brief_mismatch", field="campaign_binding")
        if len(character.traits) > brief.trait_cap or not set(brief.required_trait_ids).issubset({item.name for item in character.traits}):
            raise EngineError("character traits violate the external brief", code="brief_constraint", field="traits")
        ability_ids = {item.ability_id for item in character.abilities}
        if len(character.abilities) > brief.ability_cap or not ability_ids.issubset(set(brief.allowed_ability_ids)):
            raise EngineError("character abilities violate the external brief", code="brief_constraint", field="abilities")
        if character.resource("health").maximum > brief.health_cap or character.resource("stamina").maximum > brief.stamina_cap:
            raise EngineError("character resources violate the external brief", code="brief_constraint", field="resources")
        self._validate_character_constraints(state, character)

    def _validate_knowledge_claims(self, state: GameState, scene: SceneState, actor_id: str, claims: Sequence[str]) -> None:
        actor = _find(state.characters, "character_id", actor_id, "actor")
        known = {item.fact_id for item in actor.knowledge} | set(scene.public_facts)
        missing = sorted(set(claims) - known - _provenance_authorized_canon_ids(state, actor, scene))
        if missing:
            raise EngineError(f"actor knowledge boundary rejects unknown claimed facts: {missing}", code="knowledge_boundary", field="knowledge_claims")

    def _validate_mention_guard(
        self,
        state: GameState,
        scene: SceneState,
        actor_id: str,
        text: str,
        claims: Sequence[str],
        *,
        field: str,
        require_claims: bool = True,
    ) -> None:
        actor = _find(state.characters, "character_id", actor_id, "actor")
        known = {item.fact_id for item in actor.knowledge} | set(scene.public_facts)
        declared = set(claims)
        folded = text.casefold()
        for fact in state.world_facts:
            aliases = (fact.fact_id, fact.predicate, fact.value)
            if not any(_lexical_mention(folded, alias) for alias in aliases):
                continue
            if require_claims and fact.fact_id not in declared:
                raise EngineError(f"text mentions fact {fact.fact_id} without an explicit knowledge claim", code="knowledge_mention", field=field)
            if fact.fact_id not in known and fact.fact_id not in declared:
                raise EngineError(f"text mentions unavailable fact {fact.fact_id}", code="knowledge_mention", field=field)
        for entry in state.canon:
            aliases = (entry.entry_id, entry.claim.predicate, entry.claim.value)
            if not any(_lexical_mention(folded, alias) for alias in aliases):
                continue
            if require_claims and entry.entry_id not in declared:
                raise EngineError(f"text mentions canon {entry.entry_id} without an explicit knowledge claim", code="knowledge_mention", field=field)
            if entry.entry_id not in known and entry.entry_id not in declared:
                raise EngineError(f"text mentions unavailable canon {entry.entry_id}", code="knowledge_mention", field=field)

    def _apply_combat_action(self, state: GameState, payload: Mapping[str, Any]) -> GameState:
        data = _exact(payload, {"combat_id", "scene_id", "actor_id", "action", "target_id", "position", "explanation"}, "combat_action")
        combat_id = _id(data["combat_id"], "combat_id")
        scene_id = _id(data["scene_id"], "scene_id")
        combat = state.combat
        if combat is None or combat.combat_id != combat_id:
            raise EngineError("combat id is not active", code="combat_not_found")
        if combat.scene_id != scene_id:
            raise EngineError("combat scene does not match", code="combat_scene_mismatch")
        if combat.status is not CombatStatus.ACTIVE:
            raise EngineError("combat has already terminated", code="combat_terminal")
        actor_id = _id(data["actor_id"], "actor_id")
        current = combat.combatants[combat.turn_index]
        if current.character_id != actor_id:
            raise EngineError("actor is not the current combat turn", code="turn_order", field="actor_id")
        actor = _find(state.characters, "character_id", actor_id, "actor")
        actor_health = actor.resource("health")
        if actor_health.current <= 0:
            raise EngineError("dead combatant cannot act", code="dead_actor")
        action = data["action"]
        if action not in {"attack", "move", "defend", "recover"}:
            raise EngineError("combat action is not legal", code="illegal_action", field="action")
        actor_stamina = actor.resource("stamina")
        target_id = None if data["target_id"] is None else _id(data["target_id"], "target_id")
        position = data["position"]
        if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position <= 100:
            raise EngineError("combat position must be a bounded integer", code="invalid_position", field="position")
        expected_explanation: str
        distance: int | None = None
        stamina_cost = 0
        damage = 0
        healing = 0
        target_before: int | None = None
        target_after: int | None = None
        updated_actor = actor
        updated_combatants = list(combat.combatants)
        if action == "attack":
            if target_id is None or target_id == actor_id:
                raise EngineError("attack requires a distinct target", code="target_required", field="target_id")
            if position != current.position:
                raise EngineError("attack position must match the actor's current position", code="position_mismatch")
            target_combatant = _find(combat.combatants, "character_id", target_id, "target")
            target = _find(state.characters, "character_id", target_id, "target")
            if target_combatant.team == current.team:
                raise EngineError("attack target must be on an opposing team", code="friendly_target")
            target_health = target.resource("health")
            if target_health.current <= 0:
                raise EngineError("target is already defeated", code="dead_target")
            distance = abs(current.position - target_combatant.position)
            ability = actor.ability("strike")
            stamina_cost = ability.cost
            if distance > ability.range:
                raise EngineError("attack target is out of range", code="range_illegal", field="target_id")
            if actor_stamina.current < stamina_cost:
                raise EngineError("insufficient stamina for attack", code="resource_insufficient", field="stamina")
            damage = ability.power
            target_before = target_health.current
            target_after = max(target_health.current - damage, 0)
            updated_actor = replace(actor, resources=_replace_resource(actor.resources, "stamina", actor_stamina.current - stamina_cost))
            updated_target = replace(target, resources=_replace_resource(target.resources, "health", target_after))
            characters = _replace_by_id(_replace_by_id(state.characters, "character_id", updated_actor), "character_id", updated_target)
            expected_explanation = f"attack actor={actor_id} target={target_id} range={distance}"
        elif action == "move":
            if target_id is not None:
                raise EngineError("move cannot have a target", code="target_forbidden")
            if abs(position - current.position) > 2:
                raise EngineError("move distance exceeds tactical limit", code="move_illegal", field="position")
            stamina_cost = 1
            if actor_stamina.current < stamina_cost:
                raise EngineError("insufficient stamina for move", code="resource_insufficient", field="stamina")
            updated_actor = replace(actor, resources=_replace_resource(actor.resources, "stamina", actor_stamina.current - stamina_cost))
            characters = _replace_by_id(state.characters, "character_id", updated_actor)
            updated_combatants[combat.turn_index] = replace(current, position=position)
            expected_explanation = f"move actor={actor_id} from={current.position} to={position}"
        elif action == "defend":
            if target_id is not None or position != current.position:
                raise EngineError("defend target/position format is invalid", code="tactical_format")
            stamina_cost = 1
            if actor_stamina.current < stamina_cost:
                raise EngineError("insufficient stamina for defend", code="resource_insufficient", field="stamina")
            updated_actor = replace(actor, resources=_replace_resource(actor.resources, "stamina", actor_stamina.current - stamina_cost))
            characters = _replace_by_id(state.characters, "character_id", updated_actor)
            expected_explanation = f"defend actor={actor_id}"
        else:
            if target_id is not None or position != current.position:
                raise EngineError("recover target/position format is invalid", code="tactical_format")
            stamina_after = min(actor_stamina.maximum, actor_stamina.current + 1)
            health = actor.resource("health")
            health_after = min(health.maximum, health.current + 1)
            healing = health_after - health.current
            updated_actor = replace(actor, resources=_replace_resource(_replace_resource(actor.resources, "stamina", stamina_after), "health", health_after))
            characters = _replace_by_id(state.characters, "character_id", updated_actor)
            expected_explanation = f"recover actor={actor_id}"
        if data["explanation"] != expected_explanation:
            raise EngineError("explanation does not match the validated tactical action", code="explanation_mismatch", field="explanation")
        actor_after = updated_actor.resource("stamina").current
        record = CombatActionRecord(
            record_id=f"combat-record-{len(combat.records) + 1:04d}", round=combat.round, turn=len(combat.records), actor_id=actor_id,
            action=action, target_id=target_id, distance=distance, stamina_cost=stamina_cost, damage=damage, healing=healing,
            explanation=_text(data["explanation"], "explanation", max_length=512), actor_stamina_before=actor_stamina.current, actor_stamina_after=actor_after,
            target_health_before=target_before, target_health_after=target_after,
        )
        candidate = replace(combat, combatants=tuple(updated_combatants), records=(*combat.records, record))
        if action == "attack":
            candidate = replace(candidate, combatants=tuple(updated_combatants))
        alive_by_team = {
            combatant.team: any(_find(characters, "character_id", item.character_id, "combatant").resource("health").current > 0 for item in candidate.combatants if item.team == combatant.team)
            for combatant in candidate.combatants
        }
        alive_teams = sorted(team for team, alive in alive_by_team.items() if alive)
        if len(alive_teams) <= 1:
            status = CombatStatus.DRAW if not alive_teams else CombatStatus.VICTORY
            candidate = replace(candidate, status=status, winner_team=alive_teams[0] if alive_teams else None)
        else:
            next_index, next_round = _next_turn(candidate, characters)
            candidate = replace(candidate, turn_index=next_index, round=next_round)
        return replace(state, characters=tuple(characters), combat=candidate)

    def _thread_transition_plan(
        self,
        state: GameState,
        *,
        thread_id: Any,
        scene_id: Any,
        actor_id: Any,
        target_status: Any,
    ) -> tuple[NarrativeThread, ThreadStatus, int, tuple[str, ...]]:
        thread = _find(state.threads, "thread_id", _id(thread_id, "thread_id"), "thread")
        scene = _find(state.scenes, "scene_id", _id(scene_id, "scene_id"), "scene")
        actor = _find(state.characters, "character_id", _id(actor_id, "actor_id"), "actor")
        if actor.character_id not in scene.participants:
            raise EngineError("thread actor is not authorized for this scene", code="scene_authorization")
        try:
            status = ThreadStatus(target_status)
        except (TypeError, ValueError) as exc:
            raise EngineError("thread status is invalid", code="thread_status", field="target_status") from exc
        known = {item.fact_id for item in actor.knowledge} | set(scene.public_facts)
        prerequisite_missing = tuple(item for item in thread.prerequisites if item not in known)
        payoff_missing = tuple(item for item in thread.payoff_conditions if item not in known)
        if thread.status is ThreadStatus.SETUP and status is ThreadStatus.ACTIVE:
            if prerequisite_missing:
                raise EngineError("thread prerequisites are not known", code="thread_prerequisites", field="unresolved_dependencies")
            return thread, status, 50, payoff_missing
        if thread.status is ThreadStatus.ACTIVE and status is ThreadStatus.RESOLVED:
            if payoff_missing:
                raise EngineError("thread payoff conditions are not known", code="thread_payoff", field="unresolved_dependencies")
            return thread, status, 100, ()
        if status is ThreadStatus.ABANDONED and thread.status in {ThreadStatus.SETUP, ThreadStatus.ACTIVE}:
            computed_missing = prerequisite_missing if thread.status is ThreadStatus.SETUP else payoff_missing
            return thread, status, thread.progress, computed_missing
        raise EngineError("thread status transition is skipped, repeated, or terminal", code="thread_status")

    def _apply_thread_update(self, state: GameState, payload: Mapping[str, Any]) -> GameState:
        data = _exact(payload, {"thread_id", "scene_id", "actor_id", "target_status", "unresolved_dependencies", "explanation", "knowledge_claims"}, "thread_update")
        _find(state.threads, "thread_id", _id(data["thread_id"], "thread_id"), "thread")
        scene = _find(state.scenes, "scene_id", _id(data["scene_id"], "scene_id"), "scene")
        actor = _find(state.characters, "character_id", _id(data["actor_id"], "actor_id"), "actor")
        if actor.character_id not in scene.participants:
            raise EngineError("thread actor is not authorized for this scene", code="scene_authorization")
        if not isinstance(data["knowledge_claims"], list) or any(not isinstance(item, str) for item in data["knowledge_claims"]):
            raise EngineError("knowledge_claims must be a list of identifiers", code="knowledge_boundary", field="knowledge_claims")
        claims = tuple(data["knowledge_claims"])
        self._validate_knowledge_claims(state, scene, actor.character_id, claims)
        explanation = _text(data["explanation"], "explanation", max_length=512)
        self._validate_mention_guard(state, scene, actor.character_id, explanation, claims, field="explanation")
        thread, target_status, progress, computed_missing = self._thread_transition_plan(
            state,
            thread_id=data["thread_id"],
            scene_id=data["scene_id"],
            actor_id=data["actor_id"],
            target_status=data["target_status"],
        )
        requested_missing = data["unresolved_dependencies"]
        if not isinstance(requested_missing, list) or any(not isinstance(item, str) for item in requested_missing):
            raise EngineError("unresolved_dependencies must be a list of identifiers", code="thread_prerequisites", field="unresolved_dependencies")
        if tuple(requested_missing) != computed_missing:
            raise EngineError("unresolved dependencies do not match the controller-computed transition", code="thread_prerequisites", field="unresolved_dependencies")
        updated = replace(thread, progress=progress, status=target_status, unresolved_dependencies=computed_missing)
        return replace_thread(state, updated)

    def _apply_canon_candidate(self, state: GameState, payload: Mapping[str, Any]) -> GameState:
        data = _exact(payload, {"entry_id", "claim", "provenance", "contradiction_links"}, "canon_candidate")
        entry_id = _id(data["entry_id"], "entry_id")
        if any(item.entry_id == entry_id for item in state.canon):
            raise EngineError("canon entry id already exists", code="duplicate_id")
        claim = _claim_from(data["claim"])
        provenance = _provenance_from(data["provenance"])
        if provenance.source_kind is SourceKind.SCENE_OBSERVATION:
            raise EngineError(
                "scene observation is prose and cannot establish structured canon; use a public_fact, character_knowledge, combat_log, or authoritative_event source",
                code="provenance_unverifiable_v0",
                field="provenance.source_kind",
            )
        scene = _find(state.scenes, "scene_id", provenance.scene_id, "scene")
        actor = _find(state.characters, "character_id", provenance.actor_id, "actor")
        if actor.character_id not in scene.participants:
            raise EngineError("canon actor is not authorized for the provenance scene", code="scene_authorization")
        subjects = {item.character_id for item in state.characters} | {item.faction_id for item in state.factions} | {item.location_id for item in state.locations} | {item.subject_id for item in state.world_facts} | {state.campaign.campaign_id if state.campaign else ""}
        if claim.subject_id not in subjects:
            raise EngineError("canon claim subject is unknown", code="unknown_reference", field="claim.subject_id")
        self._validate_provenance(state, scene, actor, provenance, claim)
        conflicts = sorted(item.entry_id for item in state.canon if item.claim.subject_id == claim.subject_id and item.claim.predicate == claim.predicate and item.claim.value != claim.value)
        links = data["contradiction_links"]
        if not isinstance(links, list) or any(not isinstance(item, str) for item in links) or len(set(links)) != len(links) or sorted(links) != conflicts:
            raise EngineError("contradiction links must preserve every conflicting canon entry", code="canon_contradiction_links", field="contradiction_links")
        status = CanonStatus.CONTRADICTED if conflicts else CanonStatus.ACCEPTED
        entry = CanonEntry(entry_id, claim, provenance, tuple(conflicts), status)
        updated_entries: list[CanonEntry] = []
        for existing in state.canon:
            if existing.entry_id in conflicts:
                updated_entries.append(replace(existing, contradiction_links=tuple(sorted(set((*existing.contradiction_links, entry_id)))), status=CanonStatus.CONTRADICTED))
            else:
                updated_entries.append(existing)
        updated_entries.append(entry)
        return replace_canon_entries(state, updated_entries)

    def _validate_provenance(self, state: GameState, scene: SceneState, actor: Character, provenance: Provenance, claim: CanonClaim) -> None:
        if provenance.source_kind is SourceKind.PUBLIC_FACT:
            if provenance.source_id not in scene.public_facts:
                raise EngineError("public-fact provenance is not public in this scene", code="provenance_invalid")
            fact = _find(state.world_facts, "fact_id", provenance.source_id, "public fact")
            if not fact.public or claim.subject_id != fact.subject_id or claim.predicate != fact.predicate or claim.value != fact.value:
                raise EngineError("canon claim does not accurately document its public fact", code="canon_accuracy")
        elif provenance.source_kind is SourceKind.CHARACTER_KNOWLEDGE:
            if not any(item.fact_id == provenance.source_id for item in actor.knowledge):
                raise EngineError("character-knowledge provenance is not known by actor", code="knowledge_boundary")
            fact = next((item for item in state.world_facts if item.fact_id == provenance.source_id), None)
            if fact is not None:
                if claim.subject_id != fact.subject_id or claim.predicate != fact.predicate or claim.value != fact.value:
                    raise EngineError("canon claim does not accurately document known fact", code="canon_accuracy")
            else:
                entry = _find(state.canon, "entry_id", provenance.source_id, "known canon")
                if claim != entry.claim:
                    raise EngineError("canon claim does not accurately document known canon", code="canon_accuracy")
        elif provenance.source_kind is SourceKind.SCENE_OBSERVATION:
            raise EngineError(
                "scene observation is prose and cannot establish structured canon; use a public_fact, character_knowledge, combat_log, or authoritative_event source",
                code="provenance_unverifiable_v0",
                field="provenance.source_kind",
            )
        elif provenance.source_kind is SourceKind.COMBAT_LOG:
            if state.combat is None or state.combat.scene_id != scene.scene_id:
                raise EngineError("combat-log provenance does not exist", code="provenance_invalid")
            record = next((item for item in state.combat.records if item.record_id == provenance.source_id), None)
            if record is None or record.actor_id != actor.character_id or claim != CanonClaim(record.actor_id, "combat_action", record.action):
                raise EngineError("combat log does not exactly support the canon claim", code="canon_accuracy")
        elif provenance.source_kind is SourceKind.AUTHORITATIVE_EVENT:
            event = next((item for item in self._events if item.event_id == provenance.source_id), None)
            if event is None:
                raise EngineError("authoritative-event provenance does not exist", code="provenance_invalid")
            if event.operation == "add_world_fact":
                fact = _world_fact_from(event.payload["fact"])
                supported = CanonClaim(fact.subject_id, fact.predicate, fact.value)
            elif event.operation == "canon_candidate":
                supported = _claim_from(event.payload["claim"])
            else:
                raise EngineError("authoritative event has no claim mapping", code="canon_accuracy")
            if claim != supported:
                raise EngineError("authoritative event does not exactly support the canon claim", code="canon_accuracy")

    def create_campaign(self, identity: CampaignIdentity) -> dict[str, Any]:
        if not isinstance(identity, CampaignIdentity):
            raise EngineError("identity must be CampaignIdentity", code="type_invalid")
        return self._commit("create_campaign", {"identity": _primitive(identity)})

    def add_location(self, location: Location) -> dict[str, Any]:
        if not isinstance(location, Location):
            raise EngineError("location must be Location", code="type_invalid")
        return self._commit("add_location", {"location": _primitive(location)})

    def add_faction(self, faction: Faction) -> dict[str, Any]:
        if not isinstance(faction, Faction):
            raise EngineError("faction must be Faction", code="type_invalid")
        return self._commit("add_faction", {"faction": _primitive(faction)})

    def add_world_fact(self, fact: WorldFact) -> dict[str, Any]:
        if not isinstance(fact, WorldFact):
            raise EngineError("fact must be WorldFact", code="type_invalid")
        return self._commit("add_world_fact", {"fact": _primitive(fact)})

    def create_character(self, character: Character) -> dict[str, Any]:
        if not isinstance(character, Character):
            raise EngineError("character must be Character", code="type_invalid")
        return self._commit("create_character", {"character": _primitive(character)})

    def create_character_from_brief(self, brief: CharacterBrief, character: Character) -> dict[str, Any]:
        if not isinstance(brief, CharacterBrief) or not isinstance(character, Character):
            raise EngineError("brief and character must be typed values", code="type_invalid")
        return self._commit("create_character_from_brief", {"brief": _primitive(brief), "character": _primitive(character)})

    def grant_knowledge(self, character_id: str, knowledge: KnowledgeFact) -> dict[str, Any]:
        if not isinstance(knowledge, KnowledgeFact):
            raise EngineError("knowledge must be KnowledgeFact", code="type_invalid")
        return self._commit("grant_knowledge", {"character_id": character_id, "knowledge": _primitive(knowledge)})

    def open_scene(self, scene: SceneState) -> dict[str, Any]:
        if not isinstance(scene, SceneState):
            raise EngineError("scene must be SceneState", code="type_invalid")
        return self._commit("open_scene", {"scene": _primitive(scene)})

    def append_scene_line(self, line: SceneLine, scene_id: str) -> dict[str, Any]:
        if not isinstance(line, SceneLine):
            raise EngineError("line must be SceneLine", code="type_invalid")
        return self._commit("scene_line", {"scene_id": scene_id, "line": _primitive(line)})

    def add_scene_intention(self, intention: SceneIntention, scene_id: str) -> dict[str, Any]:
        if not isinstance(intention, SceneIntention):
            raise EngineError("intention must be SceneIntention", code="type_invalid")
        return self._commit("scene_intention", {"scene_id": scene_id, "intention": _primitive(intention)})

    def start_combat(self, combat: CombatState) -> dict[str, Any]:
        if not isinstance(combat, CombatState):
            raise EngineError("combat must be CombatState", code="type_invalid")
        return self._commit("start_combat", {"combat": _primitive(combat)})

    def combat_action(self, *, combat_id: str, scene_id: str, actor_id: str, action: str, target_id: str | None, position: int, explanation: str) -> dict[str, Any]:
        return self._commit("combat_action", {"combat_id": combat_id, "scene_id": scene_id, "actor_id": actor_id, "action": action, "target_id": target_id, "position": position, "explanation": explanation})

    def create_thread(self, thread: NarrativeThread) -> dict[str, Any]:
        if not isinstance(thread, NarrativeThread):
            raise EngineError("thread must be NarrativeThread", code="type_invalid")
        return self._commit("create_thread", {"thread": _primitive(thread)})

    def thread_transition_requirements(
        self,
        *,
        thread_id: str,
        scene_id: str,
        actor_id: str,
        target_status: ThreadStatus | str,
    ) -> list[str]:
        """Return controller-authoritative unresolved dependencies without mutation."""

        _, _, _, requirements = self._thread_transition_plan(
            self._state,
            thread_id=thread_id,
            scene_id=scene_id,
            actor_id=actor_id,
            target_status=target_status.value if isinstance(target_status, ThreadStatus) else target_status,
        )
        return list(requirements)

    def update_thread(self, *, thread_id: str, scene_id: str, actor_id: str, target_status: ThreadStatus, unresolved_dependencies: Sequence[str], explanation: str, knowledge_claims: Sequence[str]) -> dict[str, Any]:
        return self._commit("thread_update", {"thread_id": thread_id, "scene_id": scene_id, "actor_id": actor_id, "target_status": target_status.value if isinstance(target_status, ThreadStatus) else target_status, "unresolved_dependencies": list(unresolved_dependencies), "explanation": explanation, "knowledge_claims": list(knowledge_claims)})

    def append_canon(self, *, entry_id: str, claim: CanonClaim, provenance: Provenance, contradiction_links: Sequence[str]) -> dict[str, Any]:
        if not isinstance(claim, CanonClaim) or not isinstance(provenance, Provenance):
            raise EngineError("claim and provenance types are invalid", code="type_invalid")
        return self._commit("canon_candidate", {"entry_id": entry_id, "claim": _primitive(claim), "provenance": _primitive(provenance), "contradiction_links": list(contradiction_links)})

    def legal_combat_actions(self) -> list[dict[str, Any]]:
        combat = self._state.combat
        if combat is None or combat.status is not CombatStatus.ACTIVE:
            return []
        current = combat.combatants[combat.turn_index]
        actor = _find(self._state.characters, "character_id", current.character_id, "actor")
        stamina = actor.resource("stamina")
        actions: list[dict[str, Any]] = []
        ability = actor.ability("strike")
        if stamina.current >= ability.cost:
            for target in combat.combatants:
                if target.team == current.team:
                    continue
                target_character = _find(self._state.characters, "character_id", target.character_id, "target")
                if target_character.resource("health").current <= 0:
                    continue
                distance = abs(current.position - target.position)
                if distance <= ability.range:
                    actions.append({"action": "attack", "actor_id": current.character_id, "target_id": target.character_id, "range": distance, "stamina_cost": ability.cost, "damage": ability.power})
        if stamina.current >= 1:
            for destination in sorted({max(0, current.position - 1), min(100, current.position + 1)}):
                if destination != current.position:
                    actions.append({"action": "move", "actor_id": current.character_id, "target_id": None, "position": destination, "stamina_cost": 1})
            actions.append({"action": "defend", "actor_id": current.character_id, "target_id": None, "position": current.position, "stamina_cost": 1})
        actions.append({"action": "recover", "actor_id": current.character_id, "target_id": None, "position": current.position, "stamina_cost": 0})
        return actions

    def combat_summary(self) -> dict[str, Any]:
        combat = self._state.combat
        if combat is None:
            return {"status": "not_started"}
        health = {item.character_id: _find(self._state.characters, "character_id", item.character_id, "combatant").resource("health").current for item in combat.combatants}
        stamina = {item.character_id: _find(self._state.characters, "character_id", item.character_id, "combatant").resource("stamina").current for item in combat.combatants}
        current = combat.combatants[combat.turn_index].character_id if combat.status is CombatStatus.ACTIVE else None
        return {"combat_id": combat.combat_id, "status": combat.status.value, "winner_team": combat.winner_team, "round": combat.round, "turn": current, "health": health, "stamina": stamina, "records": len(combat.records)}

    def thread_summary(self, thread_id: str) -> dict[str, Any]:
        thread = _find(self._state.threads, "thread_id", thread_id, "thread")
        available = {item.fact_id for item in self._state.world_facts if item.public}
        if thread.status in {ThreadStatus.RESOLVED, ThreadStatus.ABANDONED}:
            missing = []
        else:
            stage_dependencies = thread.prerequisites if thread.status is ThreadStatus.SETUP else thread.payoff_conditions
            missing = sorted(set(stage_dependencies) - available)
        return {"thread_id": thread.thread_id, "status": thread.status.value, "progress": thread.progress, "payoff": thread.payoff, "payoff_conditions": list(thread.payoff_conditions), "unresolved_dependencies": list(thread.unresolved_dependencies), "currently_missing_without_actor": missing}

    def _validate_event_chain(self, events: Sequence[Event]) -> None:
        previous = "0" * 64
        for index, event in enumerate(events, start=1):
            if event.sequence != index or event.event_id != f"event-{index:06d}" or event.previous_event_hash != previous:
                raise EngineError("event sequence or previous hash is invalid", code="event_chain_mismatch")
            previous = event.event_hash

    def bind_gameplay(self, *, profile, admissions, locations, members, items) -> dict[str, Any]:
        """Explicit migration on a disposable campaign; never called by load."""
        from .gameplay.profile import identity
        with self._lock:
            parent = {"state_digest": self.state_digest(), "event_count": self.event_count(),
                      "event_hash": self._events[-1].event_hash if self._events else "0" * 64,
                      "old_profile": None, "new_profile": identity()}
            return self._commit("gameplay_bind", {"profile": profile, "admissions": admissions,
                                "locations": locations, "members": members, "items": items, "parent": parent})

    @staticmethod
    def _event_receipt(event):
        return {"accepted": True, "event_id": event.event_id, "event_hash": event.event_hash,
                "state_digest": event.post_state_digest, "event_count": event.sequence}

    def _validate_gameplay_request(self, command, *, replay=False):
        from .gameplay.integration import exact, authorize
        from .gameplay.models import require, integer, identifier
        from .gameplay.profile import identity, profile_identity_is_compatible
        exact(command, {"principal_id", "actor_id", "kind", "payload", "expected_revision", "request_id", "profile"})
        require(identifier(command["request_id"]), "INVALID_REQUEST_ID")
        require(integer(command["expected_revision"]), "INVALID_REVISION")
        if replay:
            require(profile_identity_is_compatible(command["profile"]), "PROFILE_MISMATCH")
        else:
            require(_canonical_bytes(command["profile"]) == _canonical_bytes(identity()), "PROFILE_MISMATCH")
        authorize(self._state, command["principal_id"], command["actor_id"], command["kind"])
        for event in self._events:
            if event.operation != "gameplay_command":
                continue
            previous = event.payload["command"]
            if (previous["principal_id"], previous["request_id"]) == (command["principal_id"], command["request_id"]):
                require(not replay and _canonical_bytes(previous) == _canonical_bytes(command), "REQUEST_ID_REUSED")
                return self._event_receipt(event)
        require(command["expected_revision"] == len(self._events), "STALE_REVISION")
        return None

    def execute_gameplay(self, *, principal_id, request_id, expected_revision, actor_id,
                         kind, payload, profile, roll_die=None):
        """Trusted local host boundary. Principals and rolls are not model fields.

        Receipts are recoverable from saved events. Acceptance is in memory
        until explicit save; this is not a durable multiplayer acknowledgement.
        """
        from .gameplay.integration import resolve
        from .gameplay.profile import rule_refs
        from .gameplay.models import require, integer
        from secrets import randbelow
        with self._lock:
            command = copy.deepcopy({"principal_id": principal_id, "request_id": request_id,
                "expected_revision": expected_revision, "actor_id": actor_id, "kind": kind,
                "payload": payload, "profile": profile})
            try:
                retry = self._validate_gameplay_request(command)
                if retry is not None:
                    return retry
                # Validate prerequisites before asking the host for randomness.
                resolve(self._state, command, lambda sides: 1)
                recorded = []
                def draw(sides):
                    value = roll_die(sides) if roll_die is not None else randbelow(sides) + 1
                    require(integer(value, 1, sides), "INVALID_HOST_ROLL")
                    recorded.append({"sides": sides, "value": value})
                    return value
                _, effects = resolve(self._state, command, draw)
                return self._commit("gameplay_command", {"command": command, "rolls": recorded,
                                    "effects": effects, "rules": rule_refs(kind)})
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                if isinstance(exc, EngineError):
                    raise
                raise EngineError(str(exc), code=getattr(exc, "code", "invalid_gameplay")) from exc

    def gameplay_view(self, *, principal_id, actor_id=None):
        """Allowlisted local player/GM view; raw view() remains owner-only."""
        from .gameplay.views import projection
        return projection(self._state, self.event_count(), principal_id, actor_id)

    def save(self, output_dir: Path) -> dict[str, Any]:
        with self._lock:
            return self._save_locked(output_dir)

    def _save_locked(self, output_dir: Path) -> dict[str, Any]:
        output_dir = Path(output_dir)
        if output_dir.exists() or output_dir.is_symlink():
            raise EngineError("save output directory already exists; create-once persistence refuses overwrite", code="create_once_collision")
        output_dir.mkdir(parents=True, exist_ok=False)
        self._validate_event_chain(self._events)
        snapshot = {
            "schema_version": 1 if self._state.gameplay is None else 2,
            "format": "factory_dm_v0_snapshot",
            "state": state_to_dict(self._state),
            "state_digest": self.state_digest(),
            "event_count": len(self._events),
            "event_chain_head": self._events[-1].event_hash if self._events else "0" * 64,
            "genesis_state": state_to_dict(empty_state()),
            "genesis_digest": state_digest(empty_state()),
        }
        snapshot_bytes = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
        event_bytes = b"".join(_canonical_bytes(event.as_dict()) + b"\n" for event in self._events)
        _write_create_once(output_dir / "snapshot.json", snapshot_bytes)
        _write_create_once(output_dir / "events.jsonl", event_bytes)
        return {"directory": str(output_dir), "snapshot": "snapshot.json", "events": "events.jsonl", "state_digest": self.state_digest(), "event_count": len(self._events), "event_chain_head": snapshot["event_chain_head"]}

    @classmethod
    def _load_records(cls, output_dir: Path) -> tuple[dict[str, Any], list[Event]]:
        output_dir = Path(output_dir)
        snapshot_value = _parse_json(_read_regular(output_dir / "snapshot.json", "snapshot"), "snapshot")
        snapshot = _exact(snapshot_value, {"schema_version", "format", "state", "state_digest", "event_count", "event_chain_head", "genesis_state", "genesis_digest"}, "snapshot")
        if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] not in {1, 2} or snapshot["format"] != "factory_dm_v0_snapshot":
            raise EngineError("snapshot format is unsupported", code="snapshot_schema_invalid")
        state = state_from_dict(snapshot["state"])
        if snapshot["schema_version"] != (1 if state.gameplay is None else 2):
            raise EngineError("snapshot gameplay schema mismatch", code="snapshot_schema_invalid")
        if snapshot["state_digest"] != state_digest(state):
            raise EngineError("snapshot state digest mismatch", code="snapshot_digest_mismatch")
        if snapshot["genesis_digest"] != state_digest(state_from_dict(snapshot["genesis_state"])) or snapshot["genesis_digest"] != state_digest(empty_state()):
            raise EngineError("snapshot genesis digest mismatch", code="snapshot_genesis_mismatch")
        event_lines = _read_regular(output_dir / "events.jsonl", "events")
        events: list[Event] = []
        if event_lines:
            for line in event_lines.splitlines():
                if not line.strip():
                    raise EngineError("events file contains a blank line", code="event_schema_invalid")
                events.append(Event.from_dict(_parse_json(line, "event")))
        if isinstance(snapshot["event_count"], bool) or not isinstance(snapshot["event_count"], int) or snapshot["event_count"] != len(events):
            raise EngineError("snapshot event count mismatch", code="event_count_mismatch")
        head = events[-1].event_hash if events else "0" * 64
        if snapshot["event_chain_head"] != head:
            raise EngineError("snapshot event-chain head mismatch", code="event_chain_mismatch")
        return dict(snapshot), events

    @classmethod
    def replay(cls, output_dir: Path) -> "CampaignController":
        snapshot, events = cls._load_records(output_dir)
        controller = cls()
        controller._validate_event_chain(events)
        for event in events:
            if controller.state_digest() != event.pre_state_digest:
                raise EngineError("event pre-state digest does not match replay state", code="replay_digest_mismatch")
            staged = copy.deepcopy(controller._state)
            staged = controller._apply_operation(staged, event.operation, event.payload)
            if event.operation != "create_campaign":
                staged = controller._advance_clock(staged)
            validate_state(staged)
            if state_digest(staged) != event.post_state_digest:
                raise EngineError("event post-state digest does not match replay result", code="replay_digest_mismatch")
            if event.clock_tick != staged.campaign.clock.tick:
                raise EngineError("event clock tick does not match replay result", code="replay_clock_mismatch")
            controller._state = staged
            controller._events.append(event)
        if controller.state_digest() != snapshot["state_digest"]:
            raise EngineError("replay final digest does not match snapshot", code="replay_digest_mismatch")
        return controller

    @classmethod
    def load(cls, output_dir: Path) -> "CampaignController":
        """Validated snapshot load, backed by a full event-chain replay."""

        return cls.replay(output_dir)


def _provenance_authorized_canon_ids(state: GameState, actor: Character, scene: SceneState) -> set[str]:
    """Canon entry ids claimable by this actor in this scene.

    An entry is claimable exactly when its provenance source is already known
    to the actor (own knowledge plus the current scene public facts) -- the
    identical condition model_context uses to expose an entry as a permitted
    claim.  Engine claimability and model-context exposure therefore coincide;
    global canon and other actors' private knowledge stay unauthorized here.
    """

    known = {item.fact_id for item in actor.knowledge} | set(scene.public_facts)
    return {entry.entry_id for entry in state.canon if entry.provenance.source_id in known}


def _replace_resource(resources: Sequence[Resource], name: str, value: int) -> tuple[Resource, ...]:
    updated: list[Resource] = []
    found = False
    for resource in resources:
        if resource.name == name:
            updated.append(replace(resource, current=value))
            found = True
        else:
            updated.append(resource)
    if not found:
        raise EngineError(f"resource {name} is missing", code="resource_missing")
    return tuple(updated)


def _lexical_mention(text: str, candidate: str) -> bool:
    """Match an identifier/value as a whole lexical phrase, not a substring."""

    if not isinstance(candidate, str) or len(candidate) < 3:
        return False
    normalized_text = re.sub(r"[_-]+", " ", text.casefold())
    normalized_text = re.sub(r"\s+", " ", normalized_text).strip()
    normalized_candidate = re.sub(r"[_-]+", " ", candidate.casefold())
    normalized_candidate = re.sub(r"\s+", " ", normalized_candidate).strip()
    phrase = re.escape(normalized_candidate)
    return re.search(rf"(?<![a-z0-9]){phrase}(?![a-z0-9])", normalized_text) is not None


def _next_turn(combat: CombatState, characters: Sequence[Character]) -> tuple[int, int]:
    start = combat.turn_index
    by_id = {item.character_id: item for item in characters}
    for offset in range(1, len(combat.combatants) + 1):
        candidate = (start + offset) % len(combat.combatants)
        character_id = combat.combatants[candidate].character_id
        if by_id[character_id].resource("health").current > 0:
            return candidate, combat.round + (1 if candidate <= start else 0)
    return start, combat.round
