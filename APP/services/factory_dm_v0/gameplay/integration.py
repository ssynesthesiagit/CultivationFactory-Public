"""Pure adapter between canonical DM V0 records and the adapted resolver.

Mechanics World objects exist only during a calculation. HP and Path balances
are read from and committed to Character.resources, never separately persisted.
This module has no provider, store, network, clock or random generator.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from types import MappingProxyType

from ..domain import DomainError, Resource, _primitive, _character_from, state_digest
from .models import Actor, World, Scene, Membership, Item, require, integer, identifier
from . import rules
from .profile import (
    EFFECTS,
    RULES,
    SOURCES,
    digest,
    identity,
    manifest,
    profile_identity_is_compatible,
    rule_refs,
    validate_profile,
)

# Source text never selects executable code. Every admitted command routes to
# this fixed dispatcher, whose branches are the pinned pure mechanics handlers.
COMMAND_HANDLERS = MappingProxyType({kind: rules.transition for kind in rules.COMMANDS})


def exact(value, keys, code="INVALID_GAMEPLAY_FIELDS"):
    require(isinstance(value, dict) and set(value) == set(keys), code)


def _characters(state):
    return {c.character_id: c for c in state.characters}


def _compact(actor):
    result = asdict(actor)
    for key in ("name", "scene_id", "hp", "base_hp_max"):
        result.pop(key)
    for pool in result["paths"].values():
        pool.pop("current")
        pool.pop("maximum")
    return result


def character_admission(character, actor, resource_bindings, *, authority_id):
    """Explicit synthetic import boundary; no generic-stat or CL inference.

    Real PortableRuntimeAuthority does not supply this schema. A dedicated
    validated mapper is required before real characters may use this boundary.
    """
    require(isinstance(actor, Actor), "INVALID_CHARACTER_MECHANICS")
    value = {"schema": "factory-gameplay-character-v1", "authority_kind": "synthetic_fixture",
             "authority_id": authority_id, "character_id": character.character_id,
             "character": _primitive(character),
             "character_digest": digest(_primitive(character)), "mechanics": asdict(actor),
             "resource_bindings": deepcopy(resource_bindings)}
    return {**value, "digest": digest(value)}


def _effect_spec(definition_id):
    require(isinstance(definition_id, str) and definition_id in EFFECTS, "UNSUPPORTED_EFFECT")
    spec = EFFECTS[definition_id]
    rule = next(r for r in RULES if r["id"] == spec["rule_id"])
    return spec, rule["citations"][0]["source_hash"]


def effect_payload(definition_id, **application):
    """Trusted fixture/GM convenience; not available in model proposal fields."""
    spec, source_hash = _effect_spec(definition_id)
    return {**application, **{k: v for k, v in spec.items() if k != "rule_id"},
            "definition_id": definition_id, "definition_version": 1, "source_hash": source_hash}


def _validate_effect(record, now, *, reduction=False):
    spec, source_hash = _effect_spec(record.definition_id)
    require(type(record.definition_version) is int and record.definition_version == 1
            and record.source_hash == source_hash, "EFFECT_SOURCE_MISMATCH")
    require(integer(record.applied_at, 0, now), "INVALID_EFFECT_START")
    if reduction:
        require("ends_on_long_rest" in spec and record.ends_on_long_rest == spec["ends_on_long_rest"],
                "EFFECT_SCOPE_MISMATCH")
    else:
        require("kind" in spec and record.kind == spec["kind"]
                and record.long_rest_recovery == spec["long_rest_recovery"], "EFFECT_SCOPE_MISMATCH")
        require(record.kind != "exhaustion" or record.expires_at is None, "UNSUPPORTED_EXHAUSTION_EXPIRY")


def mechanics_world(state):
    """Build a disposable resolver input, with explicit canonical bindings."""
    g = state.gameplay
    require(g is not None and state.campaign is not None, "GAMEPLAY_NOT_BOUND")
    chars = _characters(state)
    actors = {}
    for actor_id, record in g["actors"].items():
        require(actor_id in chars, "CHARACTER_BINDING_MISSING")
        character = chars[actor_id]
        binding = g["bindings"][actor_id]["resources"]
        hp = character.resource(binding["hp"])
        a = deepcopy(record)
        a.update(name=character.name, scene_id=character.location_id,
                 hp=hp.current, base_hp_max=hp.maximum)
        for path_id, pool in a["paths"].items():
            resource = character.resource(binding["paths"][path_id])
            pool.update(current=resource.current, maximum=resource.maximum)
        actors[actor_id] = a
    locations = {l.location_id: asdict(Scene(l.location_id, l.name, **g["locations"][l.location_id]))
                 for l in state.locations if l.location_id in g["locations"]}
    return World.from_dict({
        "world_id": state.campaign.campaign_id, "actors": actors, "scenes": locations,
        "members": g["members"], "items": g["items"], "elapsed_seconds": g["elapsed_seconds"],
        "revision": 0, "schema_version": 1, "ruleset": "factory-dm-gameplay-v1",
    })


def validate_gameplay(state):
    try:
        g = state.gameplay
        exact(g, {"schema_version", "profile", "parent", "actors", "bindings", "locations",
                  "members", "items", "elapsed_seconds"})
        require(type(g["schema_version"]) is int and g["schema_version"] == 1, "GAMEPLAY_SCHEMA_MISMATCH")
        validate_profile(g["profile"])
        exact(g["parent"], {"state_digest", "event_count", "event_hash", "old_profile", "new_profile"})
        require(g["parent"]["old_profile"] is None and profile_identity_is_compatible(g["parent"]["new_profile"]),
                "PROFILE_TRANSITION_MISMATCH")
        require(set(g["bindings"]) == set(g["actors"]) and bool(g["actors"]), "CHARACTER_BINDING_MISSING")
        require(set(g["locations"]) <= {l.location_id for l in state.locations}, "LOCATION_BINDING_MISSING")
        for policy in g["locations"].values():
            exact(policy, {"rest_allowed", "cultivation_allowed"})
        for aid, binding in g["bindings"].items():
            common_binding_keys = {"authority_id", "authority_kind", "admission_digest", "resources"}
            require(binding["authority_kind"] in {"synthetic_fixture", "validated_level0_fixture", "validated_portable_export"}
                    and identifier(binding["authority_id"]), "CHARACTER_AUTHORITY_REQUIRED")
            if binding["authority_kind"] in {"validated_level0_fixture", "validated_portable_export"}:
                expected_keys = common_binding_keys | {"contract"}
                if binding["authority_kind"] == "validated_portable_export":
                    expected_keys.add("portable_evidence")
                exact(binding, expected_keys)
                from .character_adapter import validate_level0_contract, validate_persisted_portable_admission
                if binding["authority_kind"] == "validated_portable_export":
                    validate_persisted_portable_admission(binding["contract"], binding["portable_evidence"])
                else:
                    validate_level0_contract(binding["contract"])
            else:
                exact(binding, common_binding_keys)
            exact(binding["resources"], {"hp", "paths"})
            resources = binding["resources"]
            require(set(resources["paths"]) == set(g["actors"][aid]["paths"]), "PATH_BINDING_MISMATCH")
            names = [resources["hp"], *resources["paths"].values()]
            require(all(identifier(n) for n in names) and len(set(names)) == len(names),
                    "DUPLICATE_RESOURCE_BINDING")
            require(not _characters(state)[aid].statuses, "OPAQUE_STATUS_MAPPING_REQUIRED")
        world = mechanics_world(state)
        for aid, actor in world.actors.items():
            require(_compact(actor) == g["actors"][aid], "NONCANONICAL_GAMEPLAY_ACTOR")
            for effect in actor.conditions.values():
                _validate_effect(effect, world.elapsed_seconds)
            for effect in actor.reductions.values():
                _validate_effect(effect, world.elapsed_seconds, reduction=True)
        for item in world.items.values():
            require(item.source_id == ("potion" if item.kind == "healing_potion" else "items"),
                    "ITEM_SOURCE_MISMATCH")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        if isinstance(exc, DomainError):
            raise
        raise DomainError(str(exc)) from exc


def bind(state, payload):
    exact(payload, {"profile", "admissions", "locations", "members", "items", "parent"})
    require(state.gameplay is None, "GAMEPLAY_ALREADY_BOUND")
    require(state.combat is None, "COMBAT_MAPPING_REQUIRED")
    validate_profile(payload["profile"])
    require(payload["parent"]["state_digest"] == state_digest(state), "MIGRATION_PARENT_MISMATCH")
    chars = _characters(state)
    actors, bindings = {}, {}
    require(isinstance(payload["admissions"], list) and bool(payload["admissions"]), "CHARACTER_AUTHORITY_REQUIRED")
    for admission in payload["admissions"]:
        from .character_adapter import ADMISSION_SCHEMA
        is_level0 = admission.get("schema") == ADMISSION_SCHEMA
        validated = None
        if is_level0:
            from .character_adapter import validate_level0_admission
            validated = validate_level0_admission(admission)
        else:
            exact(admission, {"schema", "authority_kind", "authority_id", "character_id", "character",
                              "character_digest", "mechanics", "resource_bindings", "digest"})
            require(admission["schema"] == "factory-gameplay-character-v1"
                    and admission["authority_kind"] == "synthetic_fixture", "REAL_CHARACTER_MAPPING_UNAVAILABLE")
            require(digest({k: v for k, v in admission.items() if k != "digest"}) == admission["digest"],
                    "CHARACTER_AUTHORITY_HASH_MISMATCH")
        aid = admission["character_id"]
        if validated is not None:
            imported, expected_actor, expected_resources, contract = validated
        else:
            imported = expected_actor = expected_resources = contract = None
        if aid not in chars:
            imported = imported or _character_from(admission["character"])
            require(imported.character_id == aid, "CHARACTER_IDENTITY_MISMATCH")
            chars[aid] = imported
            state = replace(state, characters=(*state.characters, imported))
        require(aid in chars and aid not in actors, "CHARACTER_BINDING_MISSING")
        character = chars[aid]
        require(_primitive(character) == admission["character"], "CHARACTER_AUTHORITY_STALE")
        require(digest(_primitive(character)) == admission["character_digest"], "CHARACTER_AUTHORITY_STALE")
        # Parse a full validated fixture before dropping redundant balances.
        if expected_actor is not None:
            actor = expected_actor
        else:
            doc = {"world_id": state.campaign.campaign_id, "actors": {aid: admission["mechanics"]},
                   "scenes": {character.location_id: asdict(Scene(character.location_id, character.location_id))},
                   "members": {"importer": {"role": "gm", "actor_ids": []}}, "items": {}}
            actor = World.from_dict(doc).actors[aid]
        require(actor.actor_id == aid and actor.name == character.name
                and actor.scene_id == character.location_id, "CHARACTER_IDENTITY_MISMATCH")
        require(actor.activity is None and actor.recovery_activity_id is None and actor.last_long_rest_at is None,
                "ACTIVE_CHARACTER_IMPORT_UNSUPPORTED")
        resources = expected_resources or admission["resource_bindings"]
        exact(resources, {"hp", "paths"})
        hp = character.resource(resources["hp"])
        require((hp.current, hp.maximum) == (actor.hp, actor.base_hp_max), "HP_BINDING_MISMATCH")
        require(set(resources["paths"]) == set(actor.paths), "PATH_BINDING_MISMATCH")
        for pid, pool in actor.paths.items():
            r = character.resource(resources["paths"][pid])
            require((r.current, r.maximum) == (pool.current, pool.maximum), "PATH_BINDING_MISMATCH")
        if contract is not None:
            for item in contract["starting_items"]:
                item_id = item["record"]["instance_id"]
                require(payload["items"].get(item_id) == item["record"], "STARTING_ITEM_AUTHORITY_MISMATCH")
        actors[aid] = _compact(actor)
        bindings[aid] = {"authority_kind": admission["authority_kind"], "authority_id": admission["authority_id"],
                         "admission_digest": admission["digest"], "resources": deepcopy(resources),
                         **({"contract": deepcopy(contract)} if contract is not None else {}),
                         **({"portable_evidence": deepcopy(admission["portable_evidence"])}
                            if admission["authority_kind"] == "validated_portable_export" else {})}
    g = {"schema_version": 1, "profile": deepcopy(payload["profile"]), "parent": deepcopy(payload["parent"]),
         "actors": actors, "bindings": bindings, "locations": deepcopy(payload["locations"]),
         "members": deepcopy(payload["members"]), "items": deepcopy(payload["items"]), "elapsed_seconds": 0}
    result = replace(state, gameplay=g)
    validate_gameplay(result)
    return result


def authorize(state, principal_id, actor_id, kind):
    require(state.gameplay is not None, "GAMEPLAY_NOT_BOUND")
    require(isinstance(kind, str) and kind in rules.COMMANDS, "UNSUPPORTED_COMMAND")
    require(isinstance(principal_id, str) and principal_id in state.gameplay["members"], "MEMBER_REQUIRED")
    member = state.gameplay["members"][principal_id]
    require(kind not in rules.GM_COMMANDS or member["role"] == "gm", "GM_REQUIRED")
    require(actor_id is None if kind == "advance_time" else isinstance(actor_id, str)
            and actor_id in state.gameplay["actors"], "ACTOR_NOT_FOUND")
    if member["role"] == "player":
        require(actor_id in member["actor_ids"], "ACTOR_UNAUTHORIZED")
    require(state.combat is None, "GAMEPLAY_COMBAT_UNSUPPORTED")


def resolve(state, command, roll_die):
    exact(command, {"principal_id", "actor_id", "kind", "payload", "expected_revision", "request_id", "profile"})
    require(profile_identity_is_compatible(command["profile"]), "PROFILE_MISMATCH")
    authorize(state, command["principal_id"], command["actor_id"], command["kind"])
    kind = command["kind"]
    payload = deepcopy(command["payload"])
    require(isinstance(payload, dict), "INVALID_COMMAND_FIELDS")
    world = mechanics_world(state)
    actor = world.actors.get(command["actor_id"])
    if kind in {"apply_condition", "apply_reduction"}:
        require("applied_at" not in payload, "HOST_FIELD_FORBIDDEN")
        payload["applied_at"] = world.elapsed_seconds
        from .models import Condition, Reduction
        effect = (Condition if kind == "apply_condition" else Reduction)(**payload)
        _validate_effect(effect, world.elapsed_seconds, reduction=kind == "apply_reduction")
    if kind in {"remove_condition", "remove_reduction"}:
        rules.fields(payload, {"instance_id", "source_id", "definition_id", "source_hash"})
        instances = actor.conditions if kind == "remove_condition" else actor.reductions
        require(isinstance(payload["instance_id"], str) and payload["instance_id"] in instances, "EFFECT_NOT_FOUND")
        effect = instances[payload["instance_id"]]
        require(payload.pop("definition_id") == effect.definition_id
                and payload.pop("source_hash") == effect.source_hash
                and payload["source_id"] == effect.source_id, "REMOVAL_SOURCE_MISMATCH")
    result, events = COMMAND_HANDLERS[kind](world, command["actor_id"], kind, payload,
                                          "activity-" + digest(command)[:32], roll_die)
    g = deepcopy(state.gameplay)
    g["elapsed_seconds"] = result.elapsed_seconds
    g["items"] = {k: asdict(v) for k, v in result.items.items()}
    characters = []
    for character in state.characters:
        actor = result.actors.get(character.character_id)
        if actor is None:
            characters.append(character)
            continue
        binding = g["bindings"][character.character_id]["resources"]
        values = {binding["hp"]: actor.hp,
                  **{binding["paths"][pid]: pool.current for pid, pool in actor.paths.items()}}
        characters.append(replace(character, resources=tuple(
            replace(r, current=values.get(r.name, r.current)) for r in character.resources)))
        g["actors"][character.character_id] = _compact(actor)
    staged = replace(state, characters=tuple(characters), gameplay=g)
    validate_gameplay(staged)
    return staged, [{**e, "profile": deepcopy(command["profile"]), "rules": rule_refs(kind)} for e in events]


def apply_record(state, payload):
    exact(payload, {"command", "rolls", "effects", "rules"})
    command = payload["command"]
    require(digest(payload["rules"]) == digest(rule_refs(command["kind"])), "RULE_RECORD_MISMATCH")
    require(isinstance(payload["rolls"], list), "INVALID_ROLL_RECORD")
    rolls = iter(payload["rolls"])
    def replay_roll(sides):
        record = next(rolls, None)
        require(isinstance(record, dict) and set(record) == {"sides", "value"}
                and type(record["sides"]) is int and record["sides"] == sides
                and integer(record["value"], 1, sides), "INVALID_RECORDED_ROLL")
        return record["value"]
    result, effects = resolve(state, command, replay_roll)
    require(next(rolls, None) is None, "UNUSED_RECORDED_ROLL")
    require(digest(effects) == digest(payload["effects"]), "GAMEPLAY_EFFECT_MISMATCH")
    return result
