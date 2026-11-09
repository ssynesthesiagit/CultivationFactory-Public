"""Versioned state owned by the campaign host, never by a narrative model.

Character maxima, die types, Path CLs, practice permissions and source exceptions
must come from validated character/rule authority. They are not inferred here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1
RULESET = "factory-dm-gameplay-v1"
ABILITY_NAMES = {"str", "dex", "con", "int", "wis", "cha"}


class EngineError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise EngineError(code)


def integer(value: Any, minimum: int = 0, maximum: int | None = None) -> bool:
    return type(value) is int and value >= minimum and (maximum is None or value <= maximum)


def identifier(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 160 and value.strip() == value


@dataclass
class HitDice:
    sides: int
    maximum: int
    remaining: int


@dataclass
class PathPool:
    path: str  # body, qi, spirit; one entry per active Path
    cl: int
    maximum: int
    current: int
    short_recoveries: int = 0
    cultivation_used: bool = False


@dataclass
class Condition:
    instance_id: str
    kind: str  # poisoned or exhaustion; additional kinds require a rule adapter
    source_id: str
    levels: int = 1
    expires_at: int | None = None
    long_rest_recovery: bool | None = None
    definition_id: str = ""
    definition_version: int = 1
    source_hash: str = ""
    applied_at: int = 0

    def __post_init__(self) -> None:
        if self.long_rest_recovery is None:
            self.long_rest_recovery = self.kind == "exhaustion"


@dataclass
class Reduction:
    instance_id: str
    source_id: str
    stat: str  # hp_max or an ability name
    amount: int
    ends_on_long_rest: bool = True
    definition_id: str = ""
    definition_version: int = 1
    source_hash: str = ""
    applied_at: int = 0


@dataclass
class Activity:
    activity_id: str
    kind: str
    started_at: int
    path_ids: list[str] = field(default_factory=list)
    status: str = "active"
    elapsed: int = 0
    # Long Rest progress accumulates across immediate resumptions, while a
    # segment measures only the current uninterrupted stretch.  Segment IDs
    # make each qualified partial-rest benefit independently claimable.
    segment_elapsed: int = 0
    segment_index: int = 0
    sleeping: int = 0
    light: int = 0
    cultivation_seconds: int = 0
    required_seconds: int = 3600
    short_awarded: bool = False
    short_benefit_ids: list[str] = field(default_factory=list)
    cultivation_awarded: bool = False
    ended_at: int | None = None


@dataclass
class Actor:
    actor_id: str
    name: str
    scene_id: str
    hp: int
    base_hp_max: int
    abilities: dict[str, int]
    hit_dice: dict[str, HitDice]
    paths: dict[str, PathPool] = field(default_factory=dict)
    conditions: dict[str, Condition] = field(default_factory=dict)
    reductions: dict[str, Reduction] = field(default_factory=dict)
    cultivation_paths: list[str] = field(default_factory=list)
    light_cultivation: bool = False
    speed: int = 30
    last_long_rest_at: int | None = None
    activity: Activity | None = None
    recovery_activity_id: str | None = None
    dead: bool = False

    def score(self, ability: str) -> int:
        return self.abilities[ability] - sum(r.amount for r in self.reductions.values() if r.stat == ability)

    @property
    def hp_max(self) -> int:
        return self.base_hp_max - sum(r.amount for r in self.reductions.values() if r.stat == "hp_max")

    @property
    def con_modifier(self) -> int:
        return (self.score("con") - 10) // 2

    @property
    def exhaustion(self) -> int:
        return sum(c.levels for c in self.conditions.values() if c.kind == "exhaustion")


@dataclass
class Item:
    instance_id: str
    label: str
    source_id: str
    kind: str = "mundane"  # healing_potion is the only implemented consumable
    quantity: int = 1
    owner_id: str | None = None
    scene_id: str | None = None
    visible_to: list[str] | None = None  # None = all actors at this scene
    equipped: bool = False
    attuned: bool = False
    public_ownership: bool = False


@dataclass
class Scene:
    scene_id: str
    title: str
    public_facts: list[str] = field(default_factory=list)
    gm_notes: str = ""
    rest_allowed: bool = True
    cultivation_allowed: bool = False


@dataclass
class Membership:
    role: str  # player or gm
    actor_ids: list[str] = field(default_factory=list)


@dataclass
class World:
    world_id: str
    actors: dict[str, Actor]
    scenes: dict[str, Scene]
    members: dict[str, Membership]
    items: dict[str, Item] = field(default_factory=dict)
    elapsed_seconds: int = 0
    revision: int = 0
    schema_version: int = SCHEMA_VERSION
    ruleset: str = RULESET

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, document: dict[str, Any]) -> World:
        data = dict(document)
        actors = {}
        for key, value in data["actors"].items():
            actor = dict(value)
            for name, model in (("hit_dice", HitDice), ("paths", PathPool),
                                ("conditions", Condition), ("reductions", Reduction)):
                actor[name] = {k: model(**v) for k, v in actor[name].items()}
            actor["activity"] = Activity(**actor["activity"]) if actor["activity"] else None
            actors[key] = Actor(**actor)
        data["actors"] = actors
        data["scenes"] = {k: Scene(**v) for k, v in data["scenes"].items()}
        data["members"] = {k: Membership(**v) for k, v in data["members"].items()}
        data["items"] = {k: Item(**v) for k, v in data["items"].items()}
        world = cls(**data)
        validate_world(world)
        return world


def validate_world(world: World) -> None:
    require(type(world.schema_version) is int and world.schema_version == SCHEMA_VERSION
            and world.ruleset == RULESET, "UNSUPPORTED_STATE_VERSION")
    require(identifier(world.world_id) and integer(world.elapsed_seconds) and integer(world.revision), "INVALID_WORLD")
    require(bool(world.scenes) and bool(world.members), "EMPTY_WORLD")
    for key, scene in world.scenes.items():
        require(identifier(key) and key == scene.scene_id and identifier(scene.title), "INVALID_SCENE")
        require(all(isinstance(s, str) for s in scene.public_facts) and isinstance(scene.gm_notes, str), "INVALID_SCENE")
        require(type(scene.rest_allowed) is bool and type(scene.cultivation_allowed) is bool, "INVALID_SCENE")
    for key, actor in world.actors.items():
        require(identifier(key) and key == actor.actor_id and identifier(actor.name), "INVALID_ACTOR")
        require(actor.scene_id in world.scenes and integer(actor.base_hp_max, 1), "INVALID_ACTOR")
        require(set(actor.abilities) == ABILITY_NAMES, "INVALID_ABILITIES")
        require(all(integer(n, 1, 30) for n in actor.abilities.values()), "INVALID_ABILITIES")
        require(integer(actor.speed) and type(actor.dead) is bool and type(actor.light_cultivation) is bool, "INVALID_ACTOR")
        require(len(set(actor.cultivation_paths)) == len(actor.cultivation_paths)
                and set(actor.cultivation_paths) <= actor.paths.keys(), "INVALID_PRACTICE_PERMISSION")
        require(actor.last_long_rest_at is None or integer(actor.last_long_rest_at, 0, world.elapsed_seconds), "INVALID_REST_TIME")
        for dice_id, dice in actor.hit_dice.items():
            require(identifier(dice_id) and type(dice.sides) is int and dice.sides in (4, 6, 8, 10, 12, 20), "INVALID_HIT_DICE")
            require(integer(dice.maximum, 1) and integer(dice.remaining, 0, dice.maximum), "INVALID_HIT_DICE")
        require(len({p.path for p in actor.paths.values()}) == len(actor.paths), "DUPLICATE_PATH")
        for path_id, pool in actor.paths.items():
            require(identifier(path_id) and pool.path in ("body", "qi", "spirit"), "INVALID_PATH")
            require(integer(pool.cl, 1) and integer(pool.maximum, 1)
                    and integer(pool.current, 0, pool.maximum), "INVALID_PATH")
            limit = 2 if pool.path == "body" else 1
            require(integer(pool.short_recoveries, 0, limit) and type(pool.cultivation_used) is bool, "INVALID_PATH_COUNTER")
        for condition_id, condition in actor.conditions.items():
            validate_condition(condition, world.elapsed_seconds)
            require(condition_id == condition.instance_id, "INVALID_CONDITION_ID")
        for reduction_id, reduction in actor.reductions.items():
            validate_reduction(reduction)
            require(reduction_id == reduction.instance_id, "INVALID_REDUCTION")
        # Zero-max-HP and zero-ability consequences need their specific rule adapter.
        require(actor.hp_max >= 1 and all(actor.score(n) >= 1 for n in ABILITY_NAMES), "UNSUPPORTED_STAT_REDUCTION")
        require(integer(actor.hp, 0, actor.hp_max), "INVALID_HP")
        require((actor.exhaustion < 6 or actor.dead) and (not actor.dead or actor.hp == 0), "INVALID_DEATH_STATE")
        activity = actor.activity
        if activity:
            require(type(activity.short_awarded) is bool and type(activity.cultivation_awarded) is bool,
                    "INVALID_ACTIVITY_BENEFIT")
            require(isinstance(activity.short_benefit_ids, list)
                    and all(identifier(value) for value in activity.short_benefit_ids)
                    and len(set(activity.short_benefit_ids)) == len(activity.short_benefit_ids)
                    and activity.short_awarded == bool(activity.short_benefit_ids),
                    "INVALID_ACTIVITY_BENEFIT")
            require(identifier(activity.activity_id) and activity.kind in ACTIVITY_KINDS, "INVALID_ACTIVITY")
            require(activity.status in ("active", "completed", "interrupted", "cancelled"), "INVALID_ACTIVITY")
            require(integer(activity.started_at, 0, world.elapsed_seconds), "INVALID_ACTIVITY_TIME")
            require(all(integer(n) for n in (activity.elapsed, activity.segment_elapsed,
                                             activity.segment_index, activity.sleeping, activity.light,
                                             activity.cultivation_seconds, activity.required_seconds)),
                    "INVALID_ACTIVITY_TIME")
            require(activity.segment_elapsed <= activity.elapsed
                    and len(activity.short_benefit_ids) <= activity.segment_index + 1,
                    "INVALID_ACTIVITY_TIME")
            if activity.kind == "long_rest":
                require(activity.required_seconds == 28800 + activity.segment_index * 3600,
                        "INVALID_ACTIVITY_TIME")
            else:
                require(activity.segment_index == 0 and activity.segment_elapsed == activity.elapsed,
                        "INVALID_ACTIVITY_TIME")
            require(set(activity.path_ids) <= actor.paths.keys()
                    and len(set(activity.path_ids)) == len(activity.path_ids), "INVALID_ACTIVITY_PATHS")
            require(activity.ended_at is None or integer(activity.ended_at, activity.started_at, world.elapsed_seconds), "INVALID_ACTIVITY_TIME")
            require((activity.status == "active") == (activity.ended_at is None), "INVALID_ACTIVITY_STATUS")
        if actor.recovery_activity_id is not None:
            require(activity is not None and activity.activity_id == actor.recovery_activity_id
                    and activity.short_awarded and not actor.dead, "INVALID_RECOVERY_WINDOW")
    for subject, member in world.members.items():
        require(identifier(subject) and member.role in ("player", "gm"), "INVALID_MEMBERSHIP")
        require(len(set(member.actor_ids)) == len(member.actor_ids)
                and set(member.actor_ids) <= world.actors.keys(), "INVALID_MEMBERSHIP")
    for item_id, item in world.items.items():
        require(identifier(item_id) and item_id == item.instance_id
                and identifier(item.label) and identifier(item.source_id), "INVALID_ITEM")
        require(item.kind in ("mundane", "healing_potion") and integer(item.quantity), "INVALID_ITEM")
        require((item.owner_id is None) != (item.scene_id is None), "INVALID_ITEM_LOCATION")
        require((item.owner_id in world.actors if item.owner_id is not None else item.scene_id in world.scenes), "INVALID_ITEM_LOCATION")
        require(item.visible_to is None or (len(set(item.visible_to)) == len(item.visible_to)
                and set(item.visible_to) <= world.actors.keys()), "INVALID_ITEM_VISIBILITY")
        require(type(item.equipped) is bool and type(item.attuned) is bool
                and type(item.public_ownership) is bool, "INVALID_ITEM")
        require(item.owner_id is not None or not (item.equipped or item.attuned), "INVALID_ITEM_EQUIPMENT")


ACTIVITY_KINDS = {"short_rest", "cultivation", "short_rest_cultivation", "long_rest"}


def validate_condition(condition: Condition, elapsed_seconds: int) -> None:
    require(identifier(condition.instance_id) and identifier(condition.source_id), "INVALID_CONDITION")
    require(condition.kind in ("poisoned", "exhaustion"), "UNSUPPORTED_CONDITION")
    require(integer(condition.levels, 1, 6) and (condition.kind == "exhaustion" or condition.levels == 1), "INVALID_CONDITION_LEVEL")
    require(condition.expires_at is None or integer(condition.expires_at, elapsed_seconds + 1), "INVALID_CONDITION_EXPIRY")
    require(type(condition.long_rest_recovery) is bool, "INVALID_CONDITION_RECOVERY")
    require(condition.kind == "exhaustion" or not condition.long_rest_recovery, "UNSUPPORTED_CONDITION_RECOVERY")


def validate_reduction(reduction: Reduction) -> None:
    require(identifier(reduction.instance_id) and identifier(reduction.source_id), "INVALID_REDUCTION")
    require(isinstance(reduction.stat, str) and reduction.stat in ABILITY_NAMES | {"hp_max"}
            and integer(reduction.amount, 1) and type(reduction.ends_on_long_rest) is bool, "INVALID_REDUCTION")
