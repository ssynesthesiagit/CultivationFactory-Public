"""Typed deterministic domain objects for Factory Dungeon Master V0.

The objects in this module are immutable value-oriented records.  The engine
owns the only mutable aggregate; callers receive serialized copies rather than
references to that aggregate.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Mapping, Sequence, TypeVar


class DomainError(ValueError):
    """A domain value or invariant is invalid."""


_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MAX_TEXT = 2_048
_MAX_LIST = 128
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class EntityId(str):
    """A bounded, deterministic identifier that remains JSON-string compatible."""

    def __new__(cls, value: str) -> "EntityId":
        if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
            raise DomainError("identifier must match ^[a-z][a-z0-9_-]{0,63}$")
        return str.__new__(cls, value)


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise DomainError(f"{field} must be a lowercase bounded identifier")
    return value


def _text(value: Any, field: str, *, max_length: int = _MAX_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError(f"{field} must be a non-empty string")
    if "\x00" in value or len(value) > max_length:
        raise DomainError(f"{field} contains NUL or exceeds {max_length} characters")
    return value.strip()


def _int(value: Any, field: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainError(f"{field} must be an integer, not a boolean")
    if minimum is not None and value < minimum:
        raise DomainError(f"{field} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise DomainError(f"{field} must be at most {maximum}")
    return value


def _bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise DomainError(f"{field} must be a boolean")
    return value


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise DomainError(f"{field} must be a finite number")
    return float(value)


def _tuple_strings(values: Any, field: str, *, identifiers: bool = False, maximum: int = _MAX_LIST) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or len(values) > maximum:
        raise DomainError(f"{field} must be a bounded list")
    result: list[str] = []
    for index, value in enumerate(values):
        result.append(_id(value, f"{field}[{index}]") if identifiers else _text(value, f"{field}[{index}]", max_length=128))
    if len(set(result)) != len(result):
        raise DomainError(f"{field} must not contain duplicates")
    return tuple(result)


class CharacterKind(str, Enum):
    PLAYER = "player"
    NPC = "npc"


class CombatStatus(str, Enum):
    ACTIVE = "active"
    VICTORY = "victory"
    DEFEAT = "defeat"
    DRAW = "draw"


class ThreadStatus(str, Enum):
    SETUP = "setup"
    ACTIVE = "active"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class CanonStatus(str, Enum):
    ACCEPTED = "accepted"
    CONTRADICTED = "contradicted"


class SourceKind(str, Enum):
    PUBLIC_FACT = "public_fact"
    CHARACTER_KNOWLEDGE = "character_knowledge"
    SCENE_OBSERVATION = "scene_observation"
    COMBAT_LOG = "combat_log"
    AUTHORITATIVE_EVENT = "authoritative_event"


@dataclass(frozen=True)
class DeterministicClock:
    """An explicit integer clock; it never reads wall time or randomness."""

    tick: int = 0
    step: int = 1

    def __post_init__(self) -> None:
        _int(self.tick, "clock.tick", minimum=0, maximum=2_000_000_000)
        _int(self.step, "clock.step", minimum=1, maximum=10_000)

    def advance(self) -> "DeterministicClock":
        return replace(self, tick=self.tick + self.step)


@dataclass(frozen=True)
class CampaignIdentity:
    campaign_id: str
    title: str
    seed: int
    clock: DeterministicClock

    def __post_init__(self) -> None:
        _id(self.campaign_id, "campaign_id")
        _text(self.title, "title", max_length=160)
        _int(self.seed, "seed", minimum=0, maximum=2_000_000_000)
        if not isinstance(self.clock, DeterministicClock):
            raise DomainError("clock must be a DeterministicClock")


@dataclass(frozen=True)
class CharacterBrief:
    """Controller-owned character constraints supplied outside model prose."""

    character_id: str
    kind: CharacterKind
    faction_id: str
    location_id: str
    required_trait_ids: tuple[str, ...]
    allowed_ability_ids: tuple[str, ...]
    trait_cap: int
    ability_cap: int
    health_cap: int
    stamina_cap: int

    def __post_init__(self) -> None:
        _id(self.character_id, "brief.character_id")
        if not isinstance(self.kind, CharacterKind):
            raise DomainError("brief.kind must be CharacterKind")
        _id(self.faction_id, "brief.faction_id")
        _id(self.location_id, "brief.location_id")
        required = _tuple_strings(self.required_trait_ids, "brief.required_trait_ids", identifiers=True, maximum=8)
        allowed = _tuple_strings(self.allowed_ability_ids, "brief.allowed_ability_ids", identifiers=True, maximum=16)
        _int(self.trait_cap, "brief.trait_cap", minimum=1, maximum=8)
        _int(self.ability_cap, "brief.ability_cap", minimum=1, maximum=16)
        _int(self.health_cap, "brief.health_cap", minimum=1, maximum=1_000)
        _int(self.stamina_cap, "brief.stamina_cap", minimum=1, maximum=1_000)
        if len(required) > self.trait_cap:
            raise DomainError("brief required traits exceed trait cap")
        if len(allowed) > 0 and self.ability_cap < 1:
            raise DomainError("brief ability cap is invalid")


@dataclass(frozen=True)
class Location:
    location_id: str
    name: str
    kind: str

    def __post_init__(self) -> None:
        _id(self.location_id, "location_id")
        _text(self.name, "location.name", max_length=160)
        _text(self.kind, "location.kind", max_length=64)


@dataclass(frozen=True)
class Faction:
    faction_id: str
    name: str
    description: str

    def __post_init__(self) -> None:
        _id(self.faction_id, "faction_id")
        _text(self.name, "faction.name", max_length=160)
        _text(self.description, "faction.description")


@dataclass(frozen=True)
class WorldFact:
    fact_id: str
    subject_id: str
    predicate: str
    value: str
    public: bool
    provenance: str

    def __post_init__(self) -> None:
        _id(self.fact_id, "fact_id")
        _id(self.subject_id, "fact.subject_id")
        _id(self.predicate, "fact.predicate")
        _text(self.value, "fact.value", max_length=512)
        _bool(self.public, "fact.public")
        _text(self.provenance, "fact.provenance", max_length=256)


@dataclass(frozen=True)
class Trait:
    name: str
    rating: int

    def __post_init__(self) -> None:
        _id(self.name, "trait.name")
        _int(self.rating, "trait.rating", minimum=1, maximum=5)


@dataclass(frozen=True)
class Ability:
    ability_id: str
    power: int
    range: int
    cost: int

    def __post_init__(self) -> None:
        _id(self.ability_id, "ability_id")
        _int(self.power, "ability.power", minimum=0, maximum=100)
        _int(self.range, "ability.range", minimum=0, maximum=10)
        _int(self.cost, "ability.cost", minimum=0, maximum=100)


@dataclass(frozen=True)
class Resource:
    name: str
    current: int
    maximum: int

    def __post_init__(self) -> None:
        _id(self.name, "resource.name")
        _int(self.maximum, "resource.maximum", minimum=1, maximum=1_000)
        _int(self.current, "resource.current", minimum=0, maximum=self.maximum)


@dataclass(frozen=True)
class StatusEffect:
    status_id: str
    duration: int

    def __post_init__(self) -> None:
        _id(self.status_id, "status_id")
        _int(self.duration, "status.duration", minimum=1, maximum=100)


@dataclass(frozen=True)
class Relationship:
    target_id: str
    label: str
    score: int

    def __post_init__(self) -> None:
        _id(self.target_id, "relationship.target_id")
        _text(self.label, "relationship.label", max_length=64)
        _int(self.score, "relationship.score", minimum=-100, maximum=100)


@dataclass(frozen=True)
class KnowledgeFact:
    fact_id: str
    source: str
    confidence: int

    def __post_init__(self) -> None:
        _id(self.fact_id, "knowledge.fact_id")
        _text(self.source, "knowledge.source", max_length=256)
        _int(self.confidence, "knowledge.confidence", minimum=0, maximum=100)


@dataclass(frozen=True)
class Character:
    character_id: str
    name: str
    kind: CharacterKind
    faction_id: str
    location_id: str
    traits: tuple[Trait, ...]
    abilities: tuple[Ability, ...]
    resources: tuple[Resource, ...]
    relationships: tuple[Relationship, ...]
    statuses: tuple[StatusEffect, ...]
    knowledge: tuple[KnowledgeFact, ...]

    def __post_init__(self) -> None:
        _id(self.character_id, "character_id")
        _text(self.name, "character.name", max_length=160)
        if not isinstance(self.kind, CharacterKind):
            raise DomainError("character.kind must be CharacterKind")
        _id(self.faction_id, "character.faction_id")
        _id(self.location_id, "character.location_id")
        if not 1 <= len(self.traits) <= 8 or not all(isinstance(item, Trait) for item in self.traits):
            raise DomainError("character must have 1..8 typed traits")
        if not 1 <= len(self.abilities) <= 16 or not all(isinstance(item, Ability) for item in self.abilities):
            raise DomainError("character must have 1..16 typed abilities")
        if not 1 <= len(self.resources) <= 8 or not all(isinstance(item, Resource) for item in self.resources):
            raise DomainError("character must have 1..8 typed resources")
        if len({item.name for item in self.traits}) != len(self.traits):
            raise DomainError("character traits must be unique")
        if len({item.ability_id for item in self.abilities}) != len(self.abilities):
            raise DomainError("character abilities must be unique")
        if len({item.name for item in self.resources}) != len(self.resources):
            raise DomainError("character resources must be unique")
        if len({item.target_id for item in self.relationships}) != len(self.relationships):
            raise DomainError("character relationships must be unique")
        if len({item.status_id for item in self.statuses}) != len(self.statuses):
            raise DomainError("character statuses must be unique")
        if len({item.fact_id for item in self.knowledge}) != len(self.knowledge):
            raise DomainError("character knowledge must be unique")

    def resource(self, name: str) -> Resource:
        for item in self.resources:
            if item.name == name:
                return item
        raise DomainError(f"character {self.character_id} has no resource {name}")

    def ability(self, ability_id: str) -> Ability:
        for item in self.abilities:
            if item.ability_id == ability_id:
                return item
        raise DomainError(f"character {self.character_id} has no ability {ability_id}")


@dataclass(frozen=True)
class SceneLine:
    line_id: str
    actor_id: str
    mode: str
    text: str
    knowledge_claims: tuple[str, ...]

    def __post_init__(self) -> None:
        _id(self.line_id, "line_id")
        _id(self.actor_id, "line.actor_id")
        if self.mode not in {"narration", "dialogue"}:
            raise DomainError("scene line mode must be narration or dialogue")
        _text(self.text, "line.text")
        _tuple_strings(self.knowledge_claims, "line.knowledge_claims", identifiers=True, maximum=32)


@dataclass(frozen=True)
class SceneIntention:
    intention_id: str
    actor_id: str
    text: str
    knowledge_claims: tuple[str, ...]

    def __post_init__(self) -> None:
        _id(self.intention_id, "intention_id")
        _id(self.actor_id, "intention.actor_id")
        _text(self.text, "intention.text")
        _tuple_strings(self.knowledge_claims, "intention.knowledge_claims", identifiers=True, maximum=32)


@dataclass(frozen=True)
class SceneState:
    scene_id: str
    location_id: str
    participants: tuple[str, ...]
    public_facts: tuple[str, ...]
    lines: tuple[SceneLine, ...]
    intentions: tuple[SceneIntention, ...]
    open: bool = True

    def __post_init__(self) -> None:
        _id(self.scene_id, "scene_id")
        _id(self.location_id, "scene.location_id")
        if not 1 <= len(self.participants) <= 32:
            raise DomainError("scene must have 1..32 participants")
        _tuple_strings(self.participants, "scene.participants", identifiers=True, maximum=32)
        _tuple_strings(self.public_facts, "scene.public_facts", identifiers=True, maximum=64)
        if len(self.lines) > 256 or not all(isinstance(item, SceneLine) for item in self.lines):
            raise DomainError("scene lines are invalid or too long")
        if len(self.intentions) > 128 or not all(isinstance(item, SceneIntention) for item in self.intentions):
            raise DomainError("scene intentions are invalid or too long")
        _bool(self.open, "scene.open")


@dataclass(frozen=True)
class Combatant:
    character_id: str
    team: str
    position: int
    initiative: int

    def __post_init__(self) -> None:
        _id(self.character_id, "combatant.character_id")
        _id(self.team, "combatant.team")
        _int(self.position, "combatant.position", minimum=0, maximum=100)
        _int(self.initiative, "combatant.initiative", minimum=0, maximum=100)


@dataclass(frozen=True)
class CombatActionRecord:
    record_id: str
    round: int
    turn: int
    actor_id: str
    action: str
    target_id: str | None
    distance: int | None
    stamina_cost: int
    damage: int
    healing: int
    explanation: str
    actor_stamina_before: int
    actor_stamina_after: int
    target_health_before: int | None
    target_health_after: int | None

    def __post_init__(self) -> None:
        _id(self.record_id, "combat_record.record_id")
        _int(self.round, "combat_record.round", minimum=1)
        _int(self.turn, "combat_record.turn", minimum=0)
        _id(self.actor_id, "combat_record.actor_id")
        if self.action not in {"attack", "move", "defend", "recover"}:
            raise DomainError("combat record action is invalid")
        if self.target_id is not None:
            _id(self.target_id, "combat_record.target_id")
        if self.distance is not None:
            _int(self.distance, "combat_record.distance", minimum=0, maximum=100)
        _int(self.stamina_cost, "combat_record.stamina_cost", minimum=0, maximum=100)
        _int(self.damage, "combat_record.damage", minimum=0, maximum=100)
        _int(self.healing, "combat_record.healing", minimum=0, maximum=100)
        _text(self.explanation, "combat_record.explanation", max_length=512)
        _int(self.actor_stamina_before, "combat_record.actor_stamina_before", minimum=0, maximum=1_000)
        _int(self.actor_stamina_after, "combat_record.actor_stamina_after", minimum=0, maximum=1_000)
        if self.target_health_before is not None:
            _int(self.target_health_before, "combat_record.target_health_before", minimum=0, maximum=1_000)
        if self.target_health_after is not None:
            _int(self.target_health_after, "combat_record.target_health_after", minimum=0, maximum=1_000)


@dataclass(frozen=True)
class CombatState:
    combat_id: str
    scene_id: str
    combatants: tuple[Combatant, ...]
    turn_index: int
    round: int
    status: CombatStatus
    winner_team: str | None
    records: tuple[CombatActionRecord, ...]

    def __post_init__(self) -> None:
        _id(self.combat_id, "combat_id")
        _id(self.scene_id, "combat.scene_id")
        if not 2 <= len(self.combatants) <= 32 or not all(isinstance(item, Combatant) for item in self.combatants):
            raise DomainError("combat needs 2..32 typed combatants")
        _int(self.turn_index, "combat.turn_index", minimum=0, maximum=len(self.combatants) - 1)
        _int(self.round, "combat.round", minimum=1)
        if not isinstance(self.status, CombatStatus):
            raise DomainError("combat.status must be CombatStatus")
        if self.winner_team is not None:
            _id(self.winner_team, "combat.winner_team")
        if len(self.records) > 1_024 or not all(isinstance(item, CombatActionRecord) for item in self.records):
            raise DomainError("combat records are invalid or too long")


@dataclass(frozen=True)
class NarrativeThread:
    thread_id: str
    title: str
    setup: str
    prerequisites: tuple[str, ...]
    status: ThreadStatus
    payoff: str
    unresolved_dependencies: tuple[str, ...]
    progress: int
    payoff_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        _id(self.thread_id, "thread_id")
        _text(self.title, "thread.title", max_length=160)
        _text(self.setup, "thread.setup")
        _tuple_strings(self.prerequisites, "thread.prerequisites", identifiers=True, maximum=64)
        _tuple_strings(self.payoff_conditions, "thread.payoff_conditions", identifiers=True, maximum=64)
        if not isinstance(self.status, ThreadStatus):
            raise DomainError("thread.status must be ThreadStatus")
        _text(self.payoff, "thread.payoff")
        _tuple_strings(self.unresolved_dependencies, "thread.unresolved_dependencies", identifiers=True, maximum=64)
        if not set(self.unresolved_dependencies).issubset(set(self.prerequisites) | set(self.payoff_conditions)):
            raise DomainError("thread unresolved dependencies must be declared prerequisites or payoff conditions")
        _int(self.progress, "thread.progress", minimum=0, maximum=100)


@dataclass(frozen=True)
class CanonClaim:
    subject_id: str
    predicate: str
    value: str

    def __post_init__(self) -> None:
        _id(self.subject_id, "claim.subject_id")
        _id(self.predicate, "claim.predicate")
        _text(self.value, "claim.value", max_length=512)


@dataclass(frozen=True)
class Provenance:
    source_kind: SourceKind
    source_id: str
    actor_id: str
    scene_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.source_kind, SourceKind):
            raise DomainError("provenance.source_kind must be SourceKind")
        _id(self.source_id, "provenance.source_id")
        _id(self.actor_id, "provenance.actor_id")
        _id(self.scene_id, "provenance.scene_id")


@dataclass(frozen=True)
class CanonEntry:
    entry_id: str
    claim: CanonClaim
    provenance: Provenance
    contradiction_links: tuple[str, ...]
    status: CanonStatus

    def __post_init__(self) -> None:
        _id(self.entry_id, "entry_id")
        if not isinstance(self.claim, CanonClaim):
            raise DomainError("canon.claim must be CanonClaim")
        if not isinstance(self.provenance, Provenance):
            raise DomainError("canon.provenance must be Provenance")
        _tuple_strings(self.contradiction_links, "canon.contradiction_links", identifiers=True, maximum=64)
        if self.entry_id in self.contradiction_links:
            raise DomainError("canon entry cannot contradict itself")
        if not isinstance(self.status, CanonStatus):
            raise DomainError("canon.status must be CanonStatus")


@dataclass(frozen=True)
class GameState:
    campaign: CampaignIdentity | None
    locations: tuple[Location, ...]
    factions: tuple[Faction, ...]
    world_facts: tuple[WorldFact, ...]
    characters: tuple[Character, ...]
    scenes: tuple[SceneState, ...]
    combat: CombatState | None
    threads: tuple[NarrativeThread, ...]
    canon: tuple[CanonEntry, ...]
    gameplay: dict[str, Any] | None = None


def empty_state() -> GameState:
    return GameState(None, (), (), (), (), (), None, (), ())


def _unique(items: Sequence[Any], attribute: str, label: str) -> set[str]:
    ids = [str(getattr(item, attribute)) for item in items]
    if len(ids) != len(set(ids)):
        raise DomainError(f"{label} contains duplicate identifiers")
    return set(ids)


def validate_state(state: GameState) -> None:
    if not isinstance(state, GameState):
        raise DomainError("state must be GameState")
    if state.gameplay is not None:
        from .gameplay.integration import validate_gameplay
        validate_gameplay(state)
    location_ids = _unique(state.locations, "location_id", "locations")
    faction_ids = _unique(state.factions, "faction_id", "factions")
    fact_ids = _unique(state.world_facts, "fact_id", "world_facts")
    character_ids = _unique(state.characters, "character_id", "characters")
    scene_ids = _unique(state.scenes, "scene_id", "scenes")
    thread_ids = _unique(state.threads, "thread_id", "threads")
    canon_ids = _unique(state.canon, "entry_id", "canon")
    if state.campaign is None:
        if any((state.locations, state.factions, state.world_facts, state.characters, state.scenes, state.combat, state.threads, state.canon)):
            raise DomainError("blank state cannot contain campaign entities")
        return
    if not isinstance(state.campaign, CampaignIdentity):
        raise DomainError("campaign must be CampaignIdentity")
    subject_ids = location_ids | faction_ids | character_ids | {state.campaign.campaign_id}
    for fact in state.world_facts:
        if fact.subject_id not in subject_ids:
            raise DomainError(f"world fact {fact.fact_id} references an unknown subject")
    for character in state.characters:
        if character.location_id not in location_ids:
            raise DomainError(f"character {character.character_id} references an unknown location")
        if character.faction_id not in faction_ids:
            raise DomainError(f"character {character.character_id} references an unknown faction")
        if any(item.fact_id not in fact_ids and item.fact_id not in canon_ids for item in character.knowledge):
            raise DomainError(f"character {character.character_id} has knowledge outside known facts/canon")
    for scene in state.scenes:
        if scene.location_id not in location_ids:
            raise DomainError(f"scene {scene.scene_id} references an unknown location")
        if any(item not in character_ids for item in scene.participants):
            raise DomainError(f"scene {scene.scene_id} references an unknown participant")
        if any(item not in fact_ids for item in scene.public_facts):
            raise DomainError(f"scene {scene.scene_id} references an unknown public fact")
        line_ids = _unique(scene.lines, "line_id", f"scene {scene.scene_id} lines")
        intention_ids = _unique(scene.intentions, "intention_id", f"scene {scene.scene_id} intentions")
        del line_ids, intention_ids
        for line in scene.lines:
            if line.actor_id not in scene.participants:
                raise DomainError(f"scene line actor {line.actor_id} is not a participant")
            if any(claim not in fact_ids and claim not in canon_ids for claim in line.knowledge_claims):
                raise DomainError("scene line contains an unavailable knowledge claim")
        for intention in scene.intentions:
            if intention.actor_id not in scene.participants:
                raise DomainError("scene intention actor is not a participant")
            if any(claim not in fact_ids and claim not in canon_ids for claim in intention.knowledge_claims):
                raise DomainError("scene intention contains an unavailable knowledge claim")
    if state.combat is not None:
        combat = state.combat
        if combat.scene_id not in scene_ids:
            raise DomainError("combat references an unknown scene")
        combatant_ids = _unique(combat.combatants, "character_id", "combatants")
        if combatant_ids - character_ids:
            raise DomainError("combat references an unknown character")
        teams = {item.team for item in combat.combatants}
        if len(teams) < 2:
            raise DomainError("combat requires at least two teams")
        if state.scenes and combat.scene_id in scene_ids:
            scene = next(item for item in state.scenes if item.scene_id == combat.scene_id)
            if combatant_ids - set(scene.participants):
                raise DomainError("combatants must be scene participants")
        for record in combat.records:
            if record.actor_id not in combatant_ids or (record.target_id is not None and record.target_id not in combatant_ids):
                raise DomainError("combat record references an unknown combatant")
    for thread in state.threads:
        unknown = (set(thread.prerequisites) | set(thread.payoff_conditions)) - fact_ids - canon_ids
        if unknown:
            raise DomainError(f"thread {thread.thread_id} has unknown prerequisites: {sorted(unknown)}")
    for entry in state.canon:
        if entry.provenance.actor_id not in character_ids:
            raise DomainError("canon provenance actor is unknown")
        if entry.provenance.scene_id not in scene_ids:
            raise DomainError("canon provenance scene is unknown")
        if any(link not in canon_ids for link in entry.contradiction_links):
            raise DomainError("canon contradiction link is unknown")
        for link in entry.contradiction_links:
            linked = next(item for item in state.canon if item.entry_id == link)
            if entry.entry_id not in linked.contradiction_links:
                raise DomainError("canon contradiction links must be bidirectional")
        if entry.status is CanonStatus.CONTRADICTED and not entry.contradiction_links:
            raise DomainError("contradicted canon entries must retain contradiction links")


def _primitive(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DomainError("non-finite value cannot enter canonical state")
        return value
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _primitive(item) for key, item in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {name: _primitive(getattr(value, name)) for name in value.__dataclass_fields__ if not name.startswith("_")}
    raise DomainError(f"unsupported canonical value: {type(value).__name__}")


def state_to_dict(state: GameState) -> dict[str, Any]:
    validate_state(state)
    return {
        "campaign": None if state.campaign is None else _primitive(state.campaign),
        "locations": [_primitive(item) for item in sorted(state.locations, key=lambda item: item.location_id)],
        "factions": [_primitive(item) for item in sorted(state.factions, key=lambda item: item.faction_id)],
        "world_facts": [_primitive(item) for item in sorted(state.world_facts, key=lambda item: item.fact_id)],
        "characters": [_primitive(item) for item in sorted(state.characters, key=lambda item: item.character_id)],
        "scenes": [_primitive(item) for item in sorted(state.scenes, key=lambda item: item.scene_id)],
        "combat": None if state.combat is None else _primitive(state.combat),
        "threads": [_primitive(item) for item in sorted(state.threads, key=lambda item: item.thread_id)],
        "canon": [_primitive(item) for item in sorted(state.canon, key=lambda item: item.entry_id)],
        **({} if state.gameplay is None else {"gameplay": _primitive(state.gameplay)}),
    }


def canonical_state_bytes(state: GameState) -> bytes:
    return json.dumps(state_to_dict(state), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def state_digest(state: GameState) -> str:
    import hashlib

    return hashlib.sha256(canonical_state_bytes(state)).hexdigest()


T = TypeVar("T")


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DomainError(f"{field} must be an object")
    return value


def _exact(value: Any, keys: set[str], field: str) -> Mapping[str, Any]:
    mapping = _mapping(value, field)
    if set(mapping) != keys:
        missing = sorted(keys - set(mapping))
        unknown = sorted(set(mapping) - keys)
        raise DomainError(f"{field} keys mismatch; missing={missing}, unknown={unknown}")
    return mapping


def _list(value: Any, field: str, *, maximum: int = 2_048) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise DomainError(f"{field} must be a list")
    return value


def _enum(enum_type: type[T], value: Any, field: str) -> T:
    try:
        return enum_type(value)  # type: ignore[call-arg]
    except (TypeError, ValueError) as exc:
        raise DomainError(f"{field} has an invalid enum value") from exc


def _clock_from(value: Any) -> DeterministicClock:
    data = _exact(value, {"tick", "step"}, "clock")
    return DeterministicClock(_int(data["tick"], "clock.tick", minimum=0), _int(data["step"], "clock.step", minimum=1))


def _campaign_from(value: Any) -> CampaignIdentity | None:
    if value is None:
        return None
    data = _exact(value, {"campaign_id", "title", "seed", "clock"}, "campaign")
    return CampaignIdentity(data["campaign_id"], data["title"], data["seed"], _clock_from(data["clock"]))


def _brief_from(value: Any) -> CharacterBrief:
    data = _exact(value, {"character_id", "kind", "faction_id", "location_id", "required_trait_ids", "allowed_ability_ids", "trait_cap", "ability_cap", "health_cap", "stamina_cap"}, "brief")
    return CharacterBrief(
        data["character_id"], _enum(CharacterKind, data["kind"], "brief.kind"), data["faction_id"], data["location_id"],
        tuple(_list(data["required_trait_ids"], "brief.required_trait_ids", maximum=8)),
        tuple(_list(data["allowed_ability_ids"], "brief.allowed_ability_ids", maximum=16)),
        data["trait_cap"], data["ability_cap"], data["health_cap"], data["stamina_cap"],
    )


def _trait_from(value: Any) -> Trait:
    data = _exact(value, {"name", "rating"}, "trait")
    return Trait(data["name"], data["rating"])


def _ability_from(value: Any) -> Ability:
    data = _exact(value, {"ability_id", "power", "range", "cost"}, "ability")
    return Ability(data["ability_id"], data["power"], data["range"], data["cost"])


def _resource_from(value: Any) -> Resource:
    data = _exact(value, {"name", "current", "maximum"}, "resource")
    return Resource(data["name"], data["current"], data["maximum"])


def _status_from(value: Any) -> StatusEffect:
    data = _exact(value, {"status_id", "duration"}, "status")
    return StatusEffect(data["status_id"], data["duration"])


def _relationship_from(value: Any) -> Relationship:
    data = _exact(value, {"target_id", "label", "score"}, "relationship")
    return Relationship(data["target_id"], data["label"], data["score"])


def _knowledge_from(value: Any) -> KnowledgeFact:
    data = _exact(value, {"fact_id", "source", "confidence"}, "knowledge")
    return KnowledgeFact(data["fact_id"], data["source"], data["confidence"])


def _character_from(value: Any) -> Character:
    data = _exact(value, {"character_id", "name", "kind", "faction_id", "location_id", "traits", "abilities", "resources", "relationships", "statuses", "knowledge"}, "character")
    return Character(
        data["character_id"], data["name"], _enum(CharacterKind, data["kind"], "character.kind"),
        data["faction_id"], data["location_id"],
        tuple(_trait_from(item) for item in _list(data["traits"], "character.traits")),
        tuple(_ability_from(item) for item in _list(data["abilities"], "character.abilities")),
        tuple(_resource_from(item) for item in _list(data["resources"], "character.resources")),
        tuple(_relationship_from(item) for item in _list(data["relationships"], "character.relationships")),
        tuple(_status_from(item) for item in _list(data["statuses"], "character.statuses")),
        tuple(_knowledge_from(item) for item in _list(data["knowledge"], "character.knowledge")),
    )


def _location_from(value: Any) -> Location:
    data = _exact(value, {"location_id", "name", "kind"}, "location")
    return Location(data["location_id"], data["name"], data["kind"])


def _faction_from(value: Any) -> Faction:
    data = _exact(value, {"faction_id", "name", "description"}, "faction")
    return Faction(data["faction_id"], data["name"], data["description"])


def _world_fact_from(value: Any) -> WorldFact:
    data = _exact(value, {"fact_id", "subject_id", "predicate", "value", "public", "provenance"}, "world_fact")
    return WorldFact(data["fact_id"], data["subject_id"], data["predicate"], data["value"], data["public"], data["provenance"])


def _line_from(value: Any) -> SceneLine:
    data = _exact(value, {"line_id", "actor_id", "mode", "text", "knowledge_claims"}, "scene_line")
    return SceneLine(data["line_id"], data["actor_id"], data["mode"], data["text"], tuple(_list(data["knowledge_claims"], "line.knowledge_claims", maximum=32)))


def _intention_from(value: Any) -> SceneIntention:
    data = _exact(value, {"intention_id", "actor_id", "text", "knowledge_claims"}, "scene_intention")
    return SceneIntention(data["intention_id"], data["actor_id"], data["text"], tuple(_list(data["knowledge_claims"], "intention.knowledge_claims", maximum=32)))


def _scene_from(value: Any) -> SceneState:
    data = _exact(value, {"scene_id", "location_id", "participants", "public_facts", "lines", "intentions", "open"}, "scene")
    return SceneState(
        data["scene_id"], data["location_id"],
        tuple(_list(data["participants"], "scene.participants", maximum=32)),
        tuple(_list(data["public_facts"], "scene.public_facts", maximum=64)),
        tuple(_line_from(item) for item in _list(data["lines"], "scene.lines")),
        tuple(_intention_from(item) for item in _list(data["intentions"], "scene.intentions")),
        data["open"],
    )


def _combatant_from(value: Any) -> Combatant:
    data = _exact(value, {"character_id", "team", "position", "initiative"}, "combatant")
    return Combatant(data["character_id"], data["team"], data["position"], data["initiative"])


def _record_from(value: Any) -> CombatActionRecord:
    data = _exact(value, {"record_id", "round", "turn", "actor_id", "action", "target_id", "distance", "stamina_cost", "damage", "healing", "explanation", "actor_stamina_before", "actor_stamina_after", "target_health_before", "target_health_after"}, "combat_record")
    return CombatActionRecord(
        data["record_id"], data["round"], data["turn"], data["actor_id"], data["action"],
        data["target_id"],
        data["distance"], data["stamina_cost"], data["damage"], data["healing"], data["explanation"],
        data["actor_stamina_before"], data["actor_stamina_after"],
        None if data["target_health_before"] is None else data["target_health_before"],
        None if data["target_health_after"] is None else data["target_health_after"],
    )


def _combat_from(value: Any) -> CombatState:
    data = _exact(value, {"combat_id", "scene_id", "combatants", "turn_index", "round", "status", "winner_team", "records"}, "combat")
    return CombatState(
        data["combat_id"], data["scene_id"],
        tuple(_combatant_from(item) for item in _list(data["combatants"], "combat.combatants")),
        data["turn_index"], data["round"], _enum(CombatStatus, data["status"], "combat.status"),
        data["winner_team"],
        tuple(_record_from(item) for item in _list(data["records"], "combat.records")),
    )


def _thread_from(value: Any) -> NarrativeThread:
    data = _exact(value, {"thread_id", "title", "setup", "prerequisites", "payoff_conditions", "status", "payoff", "unresolved_dependencies", "progress"}, "thread")
    return NarrativeThread(
        data["thread_id"], data["title"], data["setup"],
        tuple(_list(data["prerequisites"], "thread.prerequisites", maximum=64)),
        _enum(ThreadStatus, data["status"], "thread.status"), data["payoff"],
        tuple(_list(data["unresolved_dependencies"], "thread.unresolved_dependencies", maximum=64)), data["progress"],
        tuple(_list(data["payoff_conditions"], "thread.payoff_conditions", maximum=64)),
    )


def _claim_from(value: Any) -> CanonClaim:
    data = _exact(value, {"subject_id", "predicate", "value"}, "claim")
    return CanonClaim(data["subject_id"], data["predicate"], data["value"])


def _provenance_from(value: Any) -> Provenance:
    data = _exact(value, {"source_kind", "source_id", "actor_id", "scene_id"}, "provenance")
    return Provenance(_enum(SourceKind, data["source_kind"], "provenance.source_kind"), data["source_id"], data["actor_id"], data["scene_id"])


def _canon_from(value: Any) -> CanonEntry:
    data = _exact(value, {"entry_id", "claim", "provenance", "contradiction_links", "status"}, "canon")
    return CanonEntry(
        data["entry_id"], _claim_from(data["claim"]), _provenance_from(data["provenance"]),
        tuple(_list(data["contradiction_links"], "canon.contradiction_links", maximum=64)),
        _enum(CanonStatus, data["status"], "canon.status"),
    )


def state_from_dict(value: Any) -> GameState:
    keys = {"campaign", "locations", "factions", "world_facts", "characters", "scenes", "combat", "threads", "canon"}
    data = _exact(value, keys | ({"gameplay"} if isinstance(value, Mapping) and "gameplay" in value else set()), "state")
    if "gameplay" in data and data["gameplay"] is None:
        raise DomainError("gameplay must be absent for legacy state, not null")
    state = GameState(
        _campaign_from(data["campaign"]),
        tuple(_location_from(item) for item in _list(data["locations"], "locations")),
        tuple(_faction_from(item) for item in _list(data["factions"], "factions")),
        tuple(_world_fact_from(item) for item in _list(data["world_facts"], "world_facts")),
        tuple(_character_from(item) for item in _list(data["characters"], "characters")),
        tuple(_scene_from(item) for item in _list(data["scenes"], "scenes")),
        None if data["combat"] is None else _combat_from(data["combat"]),
        tuple(_thread_from(item) for item in _list(data["threads"], "threads")),
        tuple(_canon_from(item) for item in _list(data["canon"], "canon")),
        data.get("gameplay"),
    )
    validate_state(state)
    return state


def replace_character(state: GameState, character: Character) -> GameState:
    return replace(state, characters=tuple(character if item.character_id == character.character_id else item for item in state.characters))


def replace_scene(state: GameState, scene: SceneState) -> GameState:
    return replace(state, scenes=tuple(scene if item.scene_id == scene.scene_id else item for item in state.scenes))


def replace_thread(state: GameState, thread: NarrativeThread) -> GameState:
    return replace(state, threads=tuple(thread if item.thread_id == thread.thread_id else item for item in state.threads))


def replace_canon_entries(state: GameState, entries: Sequence[CanonEntry]) -> GameState:
    return replace(state, canon=tuple(entries))
