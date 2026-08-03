from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from app.core import FoundryError, sha256_bytes, sha256_file
from portable_character.service import PortableCharacterPackageService

from .canonical import canonical_sha256
from .character_compilation import CombatSheet, ExecutableMechanicsLock, PrimitiveRegistry
from .diagnostics import RecoveryDisposition, error
from .footprints import standard_actor_footprint
from .gate2_engine import Gate2Engine, SYSTEM_MOVE, SYSTEM_OPPORTUNITY
from .gate2_grid import SquareGrid
from .gate2_rolls import DeterministicRollAuthority
from .gate2_runtime_models import (
    ActionDefinition,
    ActionIntent,
    ActorState,
    ActorTemplate,
    CandidateKind,
    CombatEvent,
    ConditionInstance,
    ConcentrationState,
    DiceSpec,
    EconomyKind,
    LegalCandidate,
    MatchState,
    ModifierInstance,
    Position,
    ReactionDecision,
    ResourceDefinition,
    RuntimeObjectState,
    SaveDefinition,
    ZoneState,
)
from .models import StrictModel

RUNTIME_ADAPTER_ID = "TianxiaFoundry.CharacterCombatRuntimeAdapter.C3A-R"
RUNTIME_ADAPTER_VERSION = "1.0.0"
RUNTIME_ENGINE_VERSION = "0.6.6.9.2-C3A-R"
RUNTIME_READY_STAGE = "COMBAT_RUNTIME_READY"
SOURCE_CHARACTER_ID = "6a64af8e-7b8f-447b-bd81-fe4432b048c2"
SOURCE_ACTOR_ID = f"character:{SOURCE_CHARACTER_ID}"


class RuntimeResourceInitialization(StrictModel):
    qi_current: int = Field(ge=0, le=15)
    martial_focus_current: int = Field(ge=0, le=1)
    provenance_kind: Literal["ENCOUNTER_AUTHORITY", "TEST_FIXTURE"]
    provenance_id: str = Field(min_length=1)
    canonical_owner_choice: Literal[False] = False


class RuntimeMechanicSupport(StrictModel):
    stable_id: str
    mechanic_kind: Literal["ACTION", "REACTION", "AUGMENT", "PASSIVE", "RESOURCE"]
    required_primitives: tuple[str, ...]
    runtime_representation: str
    runtime_catalog_entry: str
    executing_handler: str
    reducer_event_types: tuple[str, ...]
    dry_run_test: str
    status: Literal[
        "RUNTIME_EXECUTABLE",
        "RUNTIME_EXECUTABLE_AFTER_BOUNDED_EXTENSION",
        "STATIC_ONLY",
        "BLOCKED",
    ]


class RuntimePrimitiveBinding(StrictModel):
    primitive_id: str
    executing_handler: str
    reducer_support: str
    status: Literal["RUNTIME_EXECUTABLE", "RUNTIME_EXECUTABLE_AFTER_BOUNDED_EXTENSION"]


class CharacterRuntimeBundle(StrictModel):
    schema_name: Literal["TianxiaCharacterRuntimeBundle.v1"] = Field(
        default="TianxiaCharacterRuntimeBundle.v1", alias="schema"
    )
    adapter_id: Literal[RUNTIME_ADAPTER_ID] = RUNTIME_ADAPTER_ID
    adapter_version: Literal[RUNTIME_ADAPTER_VERSION] = RUNTIME_ADAPTER_VERSION
    engine_version: Literal[RUNTIME_ENGINE_VERSION] = RUNTIME_ENGINE_VERSION
    source_combat_sheet_sha256: str
    mechanics_lock_sha256: str
    primitive_registry_sha256: str
    actor_template: ActorTemplate
    action_catalog: tuple[ActionDefinition, ...]
    reaction_parameters: dict[str, dict[str, Any]]
    passive_bindings: tuple[str, ...]
    augment_bindings: tuple[str, ...]
    primitive_bindings: tuple[RuntimePrimitiveBinding, ...]
    support_matrix: tuple[RuntimeMechanicSupport, ...]
    resource_initialization: RuntimeResourceInitialization
    readiness: Literal["COMBAT_RUNTIME_READY"] = RUNTIME_READY_STAGE
    typed_data_only: Literal[True] = True
    runtime_prose_parsing: Literal[False] = False
    persistent_match_created: Literal[False] = False
    combat_events_committed: Literal[0] = 0
    bundle_sha256: str

    @model_validator(mode="after")
    def validate_bundle(self) -> "CharacterRuntimeBundle":
        raw = self.model_dump(mode="json", by_alias=True)
        expected = raw.pop("bundle_sha256")
        if canonical_sha256(raw) != expected:
            raise ValueError("runtime bundle checksum mismatch")
        action_ids = [row.source_definition_id for row in self.action_catalog]
        if action_ids != sorted(action_ids) or len(action_ids) != len(set(action_ids)):
            raise ValueError("runtime action catalog must be unique and sorted")
        matrix_ids = [row.stable_id for row in self.support_matrix]
        if matrix_ids != sorted(matrix_ids) or len(matrix_ids) != len(set(matrix_ids)):
            raise ValueError("runtime support matrix must be unique and sorted")
        if any(row.status in {"STATIC_ONLY", "BLOCKED"} for row in self.support_matrix):
            raise ValueError("runtime-ready bundle contains a non-runtime mechanic")
        return self


class RuntimeActionRequest(StrictModel):
    request_id: str
    actor_id: str
    action_id: str
    target_id: str | None = None
    destination: Position | None = None
    option_ids: tuple[str, ...] = ()
    object_ids: tuple[str, ...] = ()
    condition_instance_id: str | None = None
    penalty_id: str | None = None
    source_effect_dc: int | None = Field(default=None, ge=1)
    reaction_decisions: tuple[ReactionDecision, ...] = ()


class RuntimeExecutionResult(StrictModel):
    schema_name: Literal["TianxiaCharacterRuntimeDryRun.v1"] = Field(
        default="TianxiaCharacterRuntimeDryRun.v1", alias="schema"
    )
    action_id: str
    actor_id: str
    target_id: str | None
    pre_state_sha256: str
    post_state_sha256: str
    events: tuple[dict[str, Any], ...]
    rolls: tuple[dict[str, Any], ...]
    persistent_match_created: Literal[False] = False
    persisted_event_count: Literal[0] = 0
    deterministic: Literal[True] = True


_PRIMITIVE_HANDLERS = {
    "primitive:apply_condition": "combat.gate2_engine.Gate2Engine._apply_condition",
    "primitive:attack_roll": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._resolve_character_attack",
    "primitive:check_roll": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._resolve_typed_check",
    "primitive:concentration": "combat.gate2_engine.Gate2Engine._start_concentration",
    "primitive:create_zone": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._create_runtime_zone",
    "primitive:damage": "combat.gate2_engine.Gate2Engine._commit_damage",
    "primitive:damage_reduction": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._resolve_damage_reaction",
    "primitive:event_emit": "combat.gate2_engine.Gate2Engine._append_event",
    "primitive:forced_movement": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._forced_movement",
    "primitive:gain_resource": "combat.gate2_engine.Gate2Engine._gain_resource",
    "primitive:ignite_object": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._ignite_object",
    "primitive:movement": "combat.gate2_engine.Gate2Engine._resolve_movement",
    "primitive:no_opportunity_movement": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._no_opportunity_movement",
    "primitive:once_per_turn": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._claim_once_per_turn",
    "primitive:register_reaction": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._reaction_checkpoint",
    "primitive:resistance": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._apply_damage_resistance",
    "primitive:save_roll": "combat.gate2_engine.Gate2Engine._roll_save",
    "primitive:spend_resource": "combat.gate2_engine.Gate2Engine._spend_resource",
    "primitive:suppress_condition_penalty": "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._suppress_condition_penalty",
}


class CharacterCombatRuntimeAdapter:
    """Sealed Combat Sheet -> existing Gate 2 runtime contracts.

    The adapter validates every input before it produces a catalog. It does not
    mutate the module-level Gate 2 catalogs and it does not create an encounter.
    """

    def __init__(self, package: Path):
        self.package = Path(package).resolve()
        self.audit = PortableCharacterPackageService.audit(self.package)
        with zipfile.ZipFile(self.package) as zf:
            self.files = {
                row.filename: zf.read(row.filename)
                for row in zf.infolist()
                if not row.is_dir()
            }
        for required in (
            "combat/Combat_Sheet.json",
            "combat/Executable_Mechanics_Lock.json",
            "combat/Primitive_Registry.json",
        ):
            if required not in self.files:
                raise FoundryError(
                    "C3AR_RUNTIME_INPUT_MISSING",
                    f"The sealed Character package is missing {required}.",
                )
        self.sheet = CombatSheet.model_validate_json(self.files["combat/Combat_Sheet.json"])
        self.lock = ExecutableMechanicsLock.model_validate_json(
            self.files["combat/Executable_Mechanics_Lock.json"]
        )
        self.registry = PrimitiveRegistry.model_validate_json(
            self.files["combat/Primitive_Registry.json"]
        )
        self._validate_authority()

    def _validate_authority(self) -> None:
        identities = self.sheet.mechanics_lock_identity
        if identities.get("lock_sha256") != self.lock.lock_sha256:
            raise FoundryError("C3AR_LOCK_MISMATCH", "Combat Sheet and mechanics lock differ.")
        if identities.get("primitive_registry_sha256") != self.registry.registry_sha256:
            raise FoundryError("C3AR_REGISTRY_MISMATCH", "Combat Sheet and primitive registry differ.")
        missing_handlers = sorted(
            {
                primitive
                for mechanic in self.lock.mechanics
                for primitive in mechanic.required_primitives
                if primitive not in _PRIMITIVE_HANDLERS
            }
        )
        if missing_handlers:
            raise FoundryError(
                "C3AR_MISSING_PRIMITIVE_HANDLER",
                "One or more sealed primitives have no runtime handler.",
                details={"missing": missing_handlers},
            )

    @staticmethod
    def _economy(value: str) -> EconomyKind:
        if value == "ACTION":
            return EconomyKind.ACTION
        if value == "BONUS_ACTION":
            return EconomyKind.BONUS_ACTION
        if value == "REACTION":
            return EconomyKind.REACTION
        return EconomyKind.NONE

    def _action_definition(self, mechanic: Any) -> ActionDefinition:
        sid = mechanic.stable_id
        economy = self._economy(mechanic.timing.action_economy)
        target_kind = "SELF"
        range_ft = mechanic.targets.range_ft
        reach_ft = None
        radius_ft = None
        attack_bonus = None
        damage = None
        damage_type = None
        save = None
        costs: tuple[tuple[str, int], ...] = ()
        if mechanic.resource_cost:
            costs = ((str(mechanic.resource_cost["resource_id"]), int(mechanic.resource_cost["amount"])),)
        parameters = {
            "stable_id": sid,
            "required_primitives": list(mechanic.required_primitives),
            "typed_details": copy.deepcopy(mechanic.typed_details),
            "conditions": list(mechanic.conditions),
            "riders": copy.deepcopy(list(mechanic.riders)),
        }
        resolution_kind = {
            "action:core.dash": "C3AR_DASH",
            "action:core.disengage": "C3AR_DISENGAGE",
            "action:core.dodge": "C3AR_DODGE",
            "action:core.unarmed_strike": "C3AR_UNARMED_STRIKE",
            "action:fire.burning_weapon": "C3AR_BURNING_WEAPON",
            "action:fire.combustive_step": "C3AR_COMBUSTIVE_STEP",
            "action:fire.conflagration": "C3AR_CONFLAGRATION",
            "action:fire.fireball_art": "C3AR_FIREBALL_ART",
            "action:fire.flame_lash": "C3AR_FLAME_LASH",
            "action:fire.ignite": "C3AR_IGNITE",
            "action:qi.meridian_regulation": "C3AR_MERIDIAN_REGULATION",
            "action:scoundrel.dirty_trick": "C3AR_DIRTY_TRICK",
            "action:scoundrel.steal": "C3AR_STEAL",
        }[sid]
        if sid in {"action:core.unarmed_strike", "action:fire.flame_lash", "action:fire.ignite"}:
            target_kind = "HOSTILE_ENTITY"
            attack_bonus = int(mechanic.formula["bonus"])
            if sid == "action:core.unarmed_strike":
                reach_ft = 5
                range_ft = None
                damage_type = "BLUDGEONING"
                parameters["fixed_damage"] = 2
            elif sid == "action:fire.flame_lash":
                damage = DiceSpec(count=2, sides=8, modifier=0)
                damage_type = "FIRE"
            else:
                damage = DiceSpec(count=2, sides=10, modifier=0)
                damage_type = "FIRE"
        elif sid in {"action:fire.conflagration", "action:fire.fireball_art"}:
            target_kind = "CELL"
            radius_ft = 15 if sid == "action:fire.conflagration" else 20
            save = SaveDefinition(ability="DEX", dc=14)
            damage = DiceSpec(count=2 if sid == "action:fire.conflagration" else 6, sides=6, modifier=0)
            damage_type = "FIRE"
        elif sid == "action:fire.combustive_step":
            target_kind = "CELL"
            range_ft = 15
        elif sid in {"action:qi.meridian_regulation", "action:scoundrel.dirty_trick", "action:scoundrel.steal"}:
            target_kind = "ACTIVE_ENTITY"
            reach_ft = 5
            range_ft = None
        elif sid == "action:fire.burning_weapon":
            target_kind = "SELF"
        return ActionDefinition(
            source_definition_id=sid,
            display_name=mechanic.display_name,
            owner_id=SOURCE_ACTOR_ID,
            economy=economy,
            resolution_kind=resolution_kind,
            target_kind=target_kind,
            range_ft=range_ft,
            reach_ft=reach_ft,
            attack_bonus=attack_bonus,
            damage=damage,
            damage_type=damage_type,
            save=save,
            costs=costs,
            concentration=mechanic.concentration,
            radius_ft=radius_ft,
            parameters=parameters,
        )

    def _support_matrix(self) -> tuple[RuntimeMechanicSupport, ...]:
        rows: list[RuntimeMechanicSupport] = []
        for mechanic in self.lock.mechanics:
            if mechanic.mechanic_kind == "ACTION":
                representation = "ActionDefinition"
                catalog = f"action_catalog[{mechanic.stable_id}]"
                handler = "combat.character_runtime_adapter.CharacterCombatRuntimeEngine.execute_action"
            elif mechanic.mechanic_kind == "REACTION":
                representation = "reaction_parameters + exact checkpoint handler"
                catalog = f"reaction_parameters[{mechanic.stable_id}]"
                handler = "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._reaction_checkpoint"
            elif mechanic.mechanic_kind == "RESOURCE":
                representation = "ResourceDefinition + RuntimeResourceInitialization"
                catalog = f"actor_template.resources[{mechanic.stable_id}]"
                handler = "combat.character_runtime_adapter.CharacterCombatRuntimeAdapter.build_bundle"
            elif mechanic.mechanic_kind == "PASSIVE":
                representation = "typed passive binding"
                catalog = f"passive_bindings[{mechanic.stable_id}]"
                handler = "combat.character_runtime_adapter.CharacterCombatRuntimeEngine.evaluate_passive"
            else:
                representation = "typed augment binding"
                catalog = f"augment_bindings[{mechanic.stable_id}]"
                handler = "combat.character_runtime_adapter.CharacterCombatRuntimeEngine._apply_augment"
            rows.append(
                RuntimeMechanicSupport(
                    stable_id=mechanic.stable_id,
                    mechanic_kind=mechanic.mechanic_kind,
                    required_primitives=mechanic.required_primitives,
                    runtime_representation=representation,
                    runtime_catalog_entry=catalog,
                    executing_handler=handler,
                    reducer_event_types=tuple(sorted(set(self._event_types_for(mechanic.stable_id)))),
                    dry_run_test=f"tests/test_c3ar_runtime_executability.py::test_runtime_support_matrix_all_30[{mechanic.stable_id}]",
                    status="RUNTIME_EXECUTABLE_AFTER_BOUNDED_EXTENSION",
                )
            )
        return tuple(sorted(rows, key=lambda row: row.stable_id))

    @staticmethod
    def _test_name(stable_id: str) -> str:
        return "test_runtime_" + stable_id.replace(":", "_").replace(".", "_")

    @staticmethod
    def _event_types_for(stable_id: str) -> tuple[str, ...]:
        if stable_id.startswith("resource:"):
            return ("RESOURCE_SPENT", "RESOURCE_GAINED")
        if stable_id.startswith("reaction:"):
            return ("REACTION_WINDOW_OPENED", "REACTION_RESOLVED", "RESOURCE_SPENT")
        if stable_id.startswith("passive:"):
            return ("PASSIVE_TRIGGERED",)
        if stable_id.startswith("augment:"):
            return ("PASSIVE_TRIGGERED", "RESOURCE_SPENT")
        return ("INTENT_ACCEPTED",)

    def build_bundle(self, initialization: RuntimeResourceInitialization) -> CharacterRuntimeBundle:
        mechanics = {row.stable_id: row for row in self.lock.mechanics}
        action_rows = [row for row in self.lock.mechanics if row.mechanic_kind == "ACTION"]
        actions = tuple(sorted((self._action_definition(row) for row in action_rows), key=lambda row: row.source_definition_id))
        stats = self.sheet.combatant_stats
        resource_rows = (
            ResourceDefinition(resource_id="resource:core.qi", initial=initialization.qi_current, maximum=15),
            ResourceDefinition(resource_id="resource:core.martial_focus", initial=initialization.martial_focus_current, maximum=1),
        )
        actor = ActorTemplate(
            entity_id=SOURCE_ACTOR_ID,
            display_name=self.sheet.display_name,
            team_id="team:source_character",
            primary_combatant=True,
            owner_id=self.sheet.character_id,
            projection_sha256=self.sheet.sheet_commitment_sha256,
            armor_class=stats.armor_class,
            maximum_hp=stats.hit_points_maximum,
            speed_ft=stats.speed_ft,
            initiative_bonus=stats.initiative_bonus,
            dexterity_score=stats.ability_scores["DEX"],
            proficiency_bonus=stats.proficiency_bonus,
            saving_throws=dict(stats.saving_throws),
            skills=dict(stats.skills),
            resources=resource_rows,
            action_ids=tuple(row.source_definition_id for row in actions),
            reaction_ids=(
                "reaction:core.opportunity_attack",
                "reaction:fire.fire_ward",
                "reaction:qi.qi_armor",
            ),
            passive_ids=tuple(sorted(row.stable_id for row in self.lock.mechanics if row.mechanic_kind == "PASSIVE")),
            augment_ids=tuple(sorted(row.stable_id for row in self.lock.mechanics if row.mechanic_kind == "AUGMENT")),
            damage_resistances=("FIRE",),
        )
        reactions = {
            "reaction:core.opportunity_attack": {
                "checkpoint": "LEAVE_REACH",
                "target": "HOSTILE_CREATURE",
                "reach_ft": 5,
                "attack_bonus": 2,
                "fixed_damage": 2,
                "damage_type": "BLUDGEONING",
            },
            "reaction:fire.fire_ward": {
                "checkpoint": "DAMAGE_APPLICATION",
                "target": "ALLY_OR_SELF_WITHIN_30",
                "resource": "resource:core.qi",
                "cost": 1,
                "reduction": "1d8+3",
                "retaliation_range_ft": 10,
                "retaliation_damage": 3,
                "retaliation_type": "FIRE",
            },
            "reaction:qi.qi_armor": {
                "checkpoint": "ATTACK_HIT_BEFORE_DAMAGE",
                "target": "SELF",
                "resource": "resource:core.qi",
                "cost": 2,
                "ac_bonus": 3,
                "ranged_only": True,
                "expires_on": "START_OF_SELF_NEXT_TURN",
            },
        }
        primitive_bindings = tuple(
            RuntimePrimitiveBinding(
                primitive_id=pid,
                executing_handler=handler,
                reducer_support=(
                    "combat.gate3_reducer.Gate3EventReducer"
                    if pid not in {"primitive:register_reaction"}
                    else "reaction checkpoint events + Gate3 runtime-control snapshot"
                ),
                status=(
                    "RUNTIME_EXECUTABLE_AFTER_BOUNDED_EXTENSION"
                    if pid in {
                        "primitive:no_opportunity_movement",
                        "primitive:suppress_condition_penalty",
                        "primitive:ignite_object",
                        "primitive:once_per_turn",
                    }
                    else "RUNTIME_EXECUTABLE"
                ),
            )
            for pid, handler in sorted(_PRIMITIVE_HANDLERS.items())
        )
        raw = {
            "schema": "TianxiaCharacterRuntimeBundle.v1",
            "adapter_id": RUNTIME_ADAPTER_ID,
            "adapter_version": RUNTIME_ADAPTER_VERSION,
            "engine_version": RUNTIME_ENGINE_VERSION,
            "source_combat_sheet_sha256": self.sheet.sheet_commitment_sha256,
            "mechanics_lock_sha256": self.lock.lock_sha256,
            "primitive_registry_sha256": self.registry.registry_sha256,
            "actor_template": actor.model_dump(mode="json"),
            "action_catalog": [row.model_dump(mode="json") for row in actions],
            "reaction_parameters": reactions,
            "passive_bindings": list(actor.passive_ids),
            "augment_bindings": list(actor.augment_ids),
            "primitive_bindings": [row.model_dump(mode="json") for row in primitive_bindings],
            "support_matrix": [row.model_dump(mode="json") for row in self._support_matrix()],
            "resource_initialization": initialization.model_dump(mode="json"),
            "readiness": RUNTIME_READY_STAGE,
            "typed_data_only": True,
            "runtime_prose_parsing": False,
            "persistent_match_created": False,
            "combat_events_committed": 0,
        }
        raw["bundle_sha256"] = canonical_sha256(raw)
        return CharacterRuntimeBundle.model_validate(raw)


class CharacterCombatRuntimeEngine(Gate2Engine):
    """In-memory C3A-R extension over Gate2Engine primitives.

    This class deliberately does not call Gate2Engine.__init__, because that
    constructor creates the accepted Gate 2 match and rolls initiative. The
    isolated harness constructs only a temporary MatchState and never invokes
    persistence, Gate 4 controllers, or Factory encounter creation.
    """

    def __init__(
        self,
        source_root: Path,
        bundle: CharacterRuntimeBundle,
        *,
        match_seed: str,
        additional_actors: tuple[ActorTemplate, ...] = (),
        positions: dict[str, Position] | None = None,
        objects: tuple[RuntimeObjectState, ...] = (),
    ):
        self.source_root = Path(source_root)
        self.grid = SquareGrid.load(self.source_root / "combat_gate1/generated/Battlefield.json")
        self.action_catalog = {row.source_definition_id: row for row in bundle.action_catalog}
        self.reaction_parameters = copy.deepcopy(bundle.reaction_parameters)
        templates = {bundle.actor_template.entity_id: bundle.actor_template}
        for row in additional_actors:
            if row.entity_id in templates:
                raise ValueError(f"duplicate actor template: {row.entity_id}")
            templates[row.entity_id] = row
        self.actor_templates = templates
        self.actor_footprints = {
            actor_id: standard_actor_footprint().model_copy(
                update={
                    "footprint_id": f"footprint:{actor_id}.1x1",
                    "source_definition_id": f"system:combat.actor_footprint:{actor_id}",
                }
            )
            for actor_id in templates
        }
        lock = json.loads(
            (self.source_root / "combat_gate2/generated/Gate2_Executable_Mechanics_Lock.json").read_text(
                encoding="utf-8"
            )
        )
        defaults = json.loads(
            (self.source_root / "combat_gate2/generated/Gate2_Universal_Combat_Defaults_Lock.json").read_text(
                encoding="utf-8"
            )
        )
        self.mechanics_lock_sha256 = lock.get("calculated_sha256") or canonical_sha256(lock)
        self.universal_defaults_lock_sha256 = defaults.get("calculated_sha256") or canonical_sha256(defaults)
        self.events: list[CombatEvent] = []
        self.rolls = []
        self.roller = DeterministicRollAuthority(match_seed)
        self._transaction_id = None
        self._transaction_result_version = 0
        self._active_intent_id = "isolated-runtime"
        self._active_intent: ActionIntent | None = None
        self._commanded_cui_this_turn = False
        self._persistent_match_created = False
        self._ignore_resistance_sources: set[str] = set()
        self._positions = positions or self._default_positions(tuple(templates))
        actors: dict[str, ActorState] = {}
        for actor_id, template in sorted(templates.items()):
            if actor_id not in self._positions:
                raise ValueError(f"missing isolated runtime position: {actor_id}")
            actors[actor_id] = ActorState(
                entity_id=actor_id,
                display_name=template.display_name,
                team_id=template.team_id,
                primary_combatant=template.primary_combatant,
                owner_id=template.owner_id,
                projection_sha256=template.projection_sha256,
                armor_class=template.armor_class,
                maximum_hp=template.maximum_hp,
                current_hp=template.maximum_hp,
                position=self._positions[actor_id],
                speed_ft=template.speed_ft,
                movement_remaining_ft=template.speed_ft,
                initiative_bonus=template.initiative_bonus,
                dexterity_score=template.dexterity_score,
                proficiency_bonus=template.proficiency_bonus,
                saving_throws=dict(template.saving_throws),
                skills=dict(template.skills),
                resources={row.resource_id: row.initial for row in template.resources},
                resource_maximums={row.resource_id: row.maximum for row in template.resources},
                action_ids=template.action_ids,
                reaction_ids=template.reaction_ids,
                passive_ids=template.passive_ids,
                augment_ids=template.augment_ids,
                damage_resistances=template.damage_resistances,
                turns_started=1,
            )
        order = list(sorted(actors))
        if bundle.actor_template.entity_id in order:
            order.remove(bundle.actor_template.entity_id)
            order.insert(0, bundle.actor_template.entity_id)
        self.state = MatchState(
            match_id=f"isolated-runtime:{canonical_sha256({'seed': match_seed, 'actors': order})[:24]}",
            match_seed=match_seed,
            gate1_registry_snapshot_sha256="c3ed7fa15650d105fe375a2b6f3a1caf00a5ebc01ea8ffc1c23608dea6d403b1",
            mechanics_lock_sha256=self.mechanics_lock_sha256,
            universal_defaults_lock_sha256=self.universal_defaults_lock_sha256,
            initiative_order=order,
            current_actor_id=order[0],
            actors=actors,
            objects={row.object_id: row.model_copy(deep=True) for row in objects},
            maximum_rounds=1,
        )
        self._assert_invariants()

    def _default_positions(self, actor_ids: tuple[str, ...]) -> dict[str, Position]:
        open_cells = [
            Position(x=x, y=y)
            for y in range(self.grid.height)
            for x in range(self.grid.width)
            if (x, y) not in self.grid.blocked
        ]
        if len(open_cells) < len(actor_ids):
            raise ValueError("battlefield has insufficient open cells")
        return {actor_id: open_cells[index * 2] for index, actor_id in enumerate(actor_ids)}

    def _check_victory(self) -> None:
        # The isolated harness is not a match and therefore has no terminal match semantics.
        return

    def _reaction_usable(self, reactor_id: str, reaction_id: str) -> bool:
        reactor = self.state.actors[reactor_id]
        if not reactor.active or not reactor.reaction_available:
            return False
        if self._reaction_denied(reactor):
            return False
        params = self.reaction_parameters.get(reaction_id, {})
        resource = params.get("resource")
        cost = int(params.get("cost", 0))
        return not resource or reactor.resources.get(resource, 0) >= cost

    def _reaction_denied(self, actor: ActorState) -> bool:
        for condition in actor.conditions.values():
            if condition.condition_id == "condition:core.reaction_denied" or condition.data.get("reaction_denied"):
                if not self._condition_penalty_suppressed(actor, condition.instance_id, "reaction_denied"):
                    return True
        return False

    def _condition_penalty_suppressed(self, actor: ActorState, instance_id: str, penalty_id: str) -> bool:
        target_field = f"condition_penalty:{instance_id}:{penalty_id}"
        return any(
            row.target_field == target_field and row.operation == "SUPPRESS" and not row.consumed
            for row in actor.modifiers.values()
        )

    def _apply_damage_resistance(self, target: ActorState, amount: int, damage_type: str, source_id: str) -> int:
        if damage_type.upper() not in {row.upper() for row in target.damage_resistances}:
            return amount
        if source_id in self._ignore_resistance_sources:
            return amount
        reduced = amount // 2
        self._append_event(
            "PASSIVE_TRIGGERED",
            "passive:cinder.fire_resistance",
            actor_id=target.entity_id,
            target_ids=(target.entity_id,),
            payload={"damage_type": damage_type, "before": amount, "after": reduced, "source": source_id},
        )
        return reduced

    def _commit_damage(
        self,
        target: ActorState,
        amount: int,
        damage_type: str,
        source_definition_id: str,
        source_actor_id: str,
        intent: ActionIntent | None,
        *,
        reaction_depth: int,
    ) -> int:
        adjusted = self._apply_damage_resistance(target, max(0, amount), damage_type, source_definition_id)
        return super()._commit_damage(
            target,
            adjusted,
            damage_type,
            source_definition_id,
            source_actor_id,
            intent,
            reaction_depth=reaction_depth,
        )

    def _resolve_damage_reaction(
        self, target: ActorState, pending: int, intent: ActionIntent, reaction_depth: int
    ) -> int:
        candidates: list[tuple[ActorState, str]] = []
        for reactor in self.state.actors.values():
            if "reaction:fire.fire_ward" not in reactor.reaction_ids:
                continue
            if reactor.team_id != target.team_id:
                continue
            if self._distance_actor_to_actor(reactor, target) > 30:
                continue
            candidates.append((reactor, "reaction:fire.fire_ward"))
        for reactor, reaction_id in sorted(candidates, key=lambda row: row[0].entity_id):
            self._reaction_checkpoint(
                reaction_id,
                checkpoint="DAMAGE_APPLICATION",
                reactor_id=reactor.entity_id,
                target_id=target.entity_id,
                pending_damage=pending,
            )
            decision = self._reaction_decision(
                intent, "DAMAGE_APPLICATION", reactor.entity_id, reaction_id
            )
            if decision is None or decision.selection == "DECLINE" or not self._reaction_usable(reactor.entity_id, reaction_id):
                continue
            self._spend_resource(reactor, "resource:core.qi", 1, reaction_id)
            roll = self.roller.roll(
                DiceSpec(count=1, sides=8, modifier=3),
                actor_id=reactor.entity_id,
                reason="FIRE_WARD_REDUCTION",
            )
            self._record_roll(roll)
            reduced = max(0, pending - roll.total)
            reactor.reaction_available = False
            self._append_event(
                "REACTION_RESOLVED",
                reaction_id,
                actor_id=reactor.entity_id,
                target_ids=(target.entity_id,),
                payload={
                    "checkpoint": "DAMAGE_APPLICATION",
                    "reduction": roll.total,
                    "pending_before": pending,
                    "pending_after": reduced,
                    "reaction_depth": reaction_depth,
                },
            )
            attacker = self.state.actors.get(intent.actor_id)
            if attacker is not None and self._distance_actor_to_actor(reactor, attacker) <= 10:
                super()._commit_damage(
                    attacker,
                    3,
                    "FIRE",
                    reaction_id,
                    reactor.entity_id,
                    None,
                    reaction_depth=reaction_depth + 1,
                )
            return reduced
        self._append_event(
            "REACTION_DECLINED",
            "system:combat.damage_reaction_window",
            actor_id=target.entity_id,
            payload={"pending_damage": pending},
        )
        return pending

    def _reaction_checkpoint(
        self,
        reaction_id: str,
        *,
        checkpoint: str,
        reactor_id: str,
        target_id: str,
        **payload: Any,
    ) -> None:
        self._append_event(
            "REACTION_WINDOW_OPENED",
            reaction_id,
            actor_id=reactor_id,
            target_ids=(target_id,),
            payload={"checkpoint": checkpoint, **payload},
        )

    def _claim_once_per_turn(self, actor: ActorState, source_scope: str) -> None:
        key = f"once_per_turn:{source_scope}"
        current_turn = actor.turns_started
        if actor.turn_flags.get(key) == current_turn:
            raise error(
                "C3AR_ONCE_PER_TURN_ALREADY_CLAIMED",
                f"{source_scope} was already claimed this turn.",
                phase="RESOLUTION",
                subsystem="C3AR_ONCE_PER_TURN",
                entity_id=actor.entity_id,
                source_definition=source_scope,
                recommended_action="Wait for the actor's next turn boundary.",
                recovery=RecoveryDisposition.RETRY,
            )
        actor.turn_flags[key] = current_turn
        self._append_event(
            "ONCE_PER_TURN_CLAIMED",
            source_scope,
            actor_id=actor.entity_id,
            payload={"scope": source_scope, "turns_started": current_turn},
        )

    def advance_isolated_turn_boundary(self, actor_id: str) -> tuple[str, ...]:
        actor = self.state.actors[actor_id]
        reset = tuple(sorted(key for key in actor.turn_flags if key.startswith("once_per_turn:")))
        with self._transaction("system:combat.turn", f"isolated-turn:{actor.turns_started + 1}", actor_id):
            for key in reset:
                actor.turn_flags.pop(key, None)
                self._append_event(
                    "ONCE_PER_TURN_RESET",
                    key.split("once_per_turn:", 1)[1],
                    actor_id=actor_id,
                    payload={"scope": key.split("once_per_turn:", 1)[1], "previous_turns_started": actor.turns_started},
                )
            actor.turns_started += 1
            actor.action_available = True
            actor.bonus_action_available = True
            actor.reaction_available = True
            actor.movement_remaining_ft = self._effective_speed(actor)
        return reset

    def _suppress_condition_penalty(
        self,
        actor: ActorState,
        condition_instance_id: str,
        penalty_id: str,
        source_id: str,
        *,
        expires_on: str,
    ) -> str:
        condition = actor.conditions.get(condition_instance_id)
        if condition is None:
            raise ValueError("condition instance is absent")
        penalties = tuple(condition.data.get("penalties", ()))
        if penalty_id not in penalties:
            raise ValueError("penalty is not authorized by the condition instance")
        target_field = f"condition_penalty:{condition_instance_id}:{penalty_id}"
        modifier_id = f"modifier:{source_id}:{actor.entity_id}:{self.state.event_sequence + 1}"
        actor.modifiers[modifier_id] = ModifierInstance(
            modifier_id=modifier_id,
            source_definition_id=source_id,
            source_actor_id=self.state.current_actor_id,
            target_id=actor.entity_id,
            target_field=target_field,
            operation="SUPPRESS",
            value=1,
            applies_to="EXACT_CONDITION_PENALTY",
            expires_on=expires_on,
        )
        self._append_event(
            "MODIFIER_APPLIED",
            source_id,
            actor_id=self.state.current_actor_id,
            target_ids=(actor.entity_id,),
            payload={
                "modifier_id": modifier_id,
                "target_field": target_field,
                "operation": "SUPPRESS",
                "value": 1,
                "expires_on": expires_on,
                "condition_instance_id": condition_instance_id,
                "penalty_id": penalty_id,
            },
        )
        return modifier_id

    def _ignite_object(self, object_id: str, source_id: str, actor_id: str) -> None:
        obj = self.state.objects.get(object_id)
        if obj is None:
            raise ValueError("typed object target does not exist")
        if not obj.unattended or not obj.flammable:
            raise ValueError("object ignition requires an unattended flammable object")
        if obj.ignited:
            return
        obj.ignited = True
        obj.ignition_source_definition_id = source_id
        obj.ignition_actor_id = actor_id
        obj.ignition_sequence = self.state.event_sequence + 1
        self._append_event(
            "OBJECT_IGNITED",
            source_id,
            actor_id=actor_id,
            payload={"object": obj.model_dump(mode="json")},
        )

    def _create_runtime_zone(
        self,
        actor: ActorState,
        action: ActionDefinition,
        center: Position,
        *,
        kind: str,
        radius_ft: int,
        concentration_link: bool,
        extra: dict[str, Any] | None = None,
    ) -> ZoneState:
        radius_cells = radius_ft // self.grid.square_size_ft
        zone_id = f"zone:{action.source_definition_id}:{self.state.event_sequence + 1}"
        zone = ZoneState(
            zone_id=zone_id,
            source_definition_id=action.source_definition_id,
            owner_id=actor.entity_id,
            center=center,
            radius_cells=radius_cells,
            affected_cells=self.grid.cells_in_radius(center, radius_cells),
            concentration_link=concentration_link,
            duration_rounds=10 if concentration_link else 1,
            created_round=self.state.round_number,
            trigger_profile={"kind": kind, **(extra or {})},
        )
        self.state.zones[zone_id] = zone
        self._append_event(
            "ZONE_CREATED",
            action.source_definition_id,
            actor_id=actor.entity_id,
            payload={"zone": zone.model_dump(mode="json")},
        )
        if concentration_link:
            self._start_concentration(actor, action.source_definition_id)
            if actor.concentration is not None:
                actor.concentration.zone_id = zone_id
        return zone

    def _forced_movement(self, actor: ActorState, target: ActorState, distance_ft: int, *, pull: bool, source_id: str) -> None:
        cells = max(1, distance_ft // self.grid.square_size_ft)
        dx = actor.position.x - target.position.x
        dy = actor.position.y - target.position.y
        step_x = 0 if dx == 0 else (1 if dx > 0 else -1)
        step_y = 0 if dy == 0 else (1 if dy > 0 else -1)
        if not pull:
            step_x *= -1
            step_y *= -1
        current = target.position
        traversed = [current]
        for _ in range(cells):
            nxt = Position(x=max(0, current.x + step_x), y=max(0, current.y + step_y))
            if not self.grid.step_legal(
                current,
                nxt,
                occupied_cells=self._occupied_cells_except(target.entity_id),
                footprint=self._footprint(target),
            ):
                break
            target.position = nxt
            current = nxt
            traversed.append(nxt)
        self._append_event(
            "MOVEMENT_COMMITTED",
            source_id,
            actor_id=target.entity_id,
            payload={
                "destination": target.position.model_dump(mode="json"),
                "path": [row.model_dump(mode="json") for row in traversed],
                "cost_ft": 0,
                "forced": True,
                "provokes_opportunity_attacks": False,
            },
        )

    def _no_opportunity_movement(self, actor: ActorState, destination: Position, source_id: str, intent: ActionIntent) -> None:
        path_row = self.grid.shortest_path(
            actor.position,
            destination,
            occupied_cells=self._occupied_cells_except(actor.entity_id),
            max_cost_ft=15,
            footprint=self._footprint(actor),
        )
        if path_row is None:
            raise ValueError("Combustive Step destination is not reachable within 15 feet")
        path, cost = path_row
        candidate = LegalCandidate(
            candidate_id=f"candidate:{canonical_sha256({'source': source_id, 'destination': destination.model_dump(mode='json')})[:24]}",
            decision_id=f"decision:{self.state.state_version}:{actor.entity_id}:{self.state.event_sequence}",
            state_version=self.state.state_version,
            kind=CandidateKind.MOVE,
            actor_id=actor.entity_id,
            source_definition_id=source_id,
            display_name="Combustive Step movement",
            destination=destination,
            canonical_path=path,
            movement_cost_ft=cost,
            metadata={"no_opportunity_movement": True},
        )
        actor.turn_flags["c3ar:no_opportunity_packet"] = self._transaction_id
        try:
            self._resolve_movement(actor, candidate, intent)
        finally:
            actor.turn_flags.pop("c3ar:no_opportunity_packet", None)

    def _resolve_leave_reach(self, mover: ActorState, previous: Position, nxt: Position, intent: ActionIntent) -> None:
        if mover.turn_flags.get("disengaged") or mover.turn_flags.get("c3ar:no_opportunity_packet") == self._transaction_id:
            self._append_event(
                "OPPORTUNITY_EXPOSURE_SUPPRESSED",
                mover.turn_flags.get("c3ar:no_opportunity_source", "primitive:no_opportunity_movement"),
                actor_id=mover.entity_id,
                payload={"from": previous.model_dump(mode="json"), "to": nxt.model_dump(mode="json")},
            )
            return
        for reactor in sorted(self.state.actors.values(), key=lambda row: row.entity_id):
            if reactor.team_id == mover.team_id or not reactor.active or not reactor.reaction_available:
                continue
            if "reaction:core.opportunity_attack" not in reactor.reaction_ids:
                continue
            if self._distance_actor_to_actor(mover, reactor, actor_position=previous) > 5:
                continue
            if self._distance_actor_to_actor(mover, reactor, actor_position=nxt) <= 5:
                continue
            self._reaction_checkpoint(
                "reaction:core.opportunity_attack",
                checkpoint="LEAVE_REACH",
                reactor_id=reactor.entity_id,
                target_id=mover.entity_id,
            )
            decision = self._reaction_decision(
                intent, "LEAVE_REACH", reactor.entity_id, "reaction:core.opportunity_attack"
            )
            if decision is None or decision.selection == "DECLINE":
                self._append_event(
                    "REACTION_DECLINED",
                    "reaction:core.opportunity_attack",
                    actor_id=reactor.entity_id,
                    target_ids=(mover.entity_id,),
                )
                continue
            reactor.reaction_available = False
            self._resolve_character_attack(
                reactor,
                mover,
                source_id="reaction:core.opportunity_attack",
                attack_bonus=2,
                damage=DiceSpec(count=1, sides=2, modifier=1),
                damage_type="BLUDGEONING",
                intent=intent,
                fixed_damage=2,
                ranged=False,
            )
            self._append_event(
                "REACTION_RESOLVED",
                "reaction:core.opportunity_attack",
                actor_id=reactor.entity_id,
                target_ids=(mover.entity_id,),
                payload={"checkpoint": "LEAVE_REACH"},
            )

    def _resolve_character_attack(
        self,
        actor: ActorState,
        target: ActorState,
        *,
        source_id: str,
        attack_bonus: int,
        damage: DiceSpec | None,
        damage_type: str,
        intent: ActionIntent,
        fixed_damage: int | None = None,
        ranged: bool,
        advantage_if_burning: bool = False,
        qi_powered: bool = False,
        cinder_touch: bool = False,
        overheat: bool = False,
    ) -> bool:
        mode = "ADVANTAGE" if advantage_if_burning and self._has_condition(target, "condition:core.burning") else "NORMAL"
        exploited = next(
            (
                row
                for row in actor.conditions.values()
                if row.condition_id == "condition:scoundrel.exploited_opening"
                and row.data.get("target_id") == target.entity_id
            ),
            None,
        )
        if exploited is not None:
            mode = "ADVANTAGE"
            actor.conditions.pop(exploited.instance_id, None)
            self._append_event(
                "CONDITION_REMOVED",
                "passive:scoundrel.exploited_opening",
                actor_id=actor.entity_id,
                target_ids=(actor.entity_id,),
                payload={"instance_id": exploited.instance_id, "condition_id": exploited.condition_id, "reason": "CONSUMED"},
            )
        roll = self.roller.d20(
            modifier=attack_bonus,
            actor_id=actor.entity_id,
            reason=f"ATTACK:{source_id}",
            mode=mode,
        )
        self._record_roll(roll)
        effective_ac = target.armor_class + self._ac_modifier(target)
        natural = roll.natural_result or 0
        hit = natural != 1 and (natural == 20 or roll.total >= effective_ac)
        self._append_event(
            "ATTACK_ROLLED",
            source_id,
            actor_id=actor.entity_id,
            target_ids=(target.entity_id,),
            payload={**roll.model_dump(mode="json"), "target_ac": effective_ac, "provisional_hit": hit},
        )
        if hit and ranged and "reaction:qi.qi_armor" in target.reaction_ids:
            self._reaction_checkpoint(
                "reaction:qi.qi_armor",
                checkpoint="ATTACK_HIT_BEFORE_DAMAGE",
                reactor_id=target.entity_id,
                target_id=target.entity_id,
                triggering_attack=source_id,
            )
            decision = self._reaction_decision(
                intent, "ATTACK_HIT_BEFORE_DAMAGE", target.entity_id, "reaction:qi.qi_armor"
            )
            if decision is not None and decision.selection == "USE" and self._reaction_usable(target.entity_id, "reaction:qi.qi_armor"):
                self._spend_resource(target, "resource:core.qi", 2, "reaction:qi.qi_armor")
                target.reaction_available = False
                self._add_modifier(
                    target,
                    "reaction:qi.qi_armor",
                    "armor_class",
                    "ADD",
                    3,
                    "ALL_ATTACKS",
                    expires_on="START_OF_SELF_NEXT_TURN",
                )
                effective_ac += 3
                hit = natural == 20 or roll.total >= effective_ac
                self._append_event(
                    "REACTION_RESOLVED",
                    "reaction:qi.qi_armor",
                    actor_id=target.entity_id,
                    target_ids=(target.entity_id,),
                    payload={"ac_bonus": 3, "new_ac": effective_ac, "hit_after_recheck": hit},
                )
        if not hit:
            return False
        total = fixed_damage or 0
        if damage is not None and fixed_damage is None:
            damage_roll = self.roller.roll(
                damage,
                actor_id=actor.entity_id,
                reason=f"DAMAGE:{source_id}",
                critical=natural == 20,
            )
            self._record_roll(damage_roll)
            total = damage_roll.total
            self._append_event(
                "DAMAGE_ROLLED",
                source_id,
                actor_id=actor.entity_id,
                target_ids=(target.entity_id,),
                payload={**damage_roll.model_dump(mode="json"), "critical": natural == 20},
            )
        if qi_powered and "passive:qi.technique_potency" in actor.passive_ids:
            total += 3
            self._append_event(
                "PASSIVE_TRIGGERED",
                "passive:qi.technique_potency",
                actor_id=actor.entity_id,
                target_ids=(target.entity_id,),
                payload={"added_damage": 3, "source": source_id},
            )
        if actor.concentration and actor.concentration.source_definition_id == "action:fire.burning_weapon":
            self._claim_once_per_turn(actor, "action:fire.burning_weapon")
            bonus = self.roller.roll(DiceSpec(count=1, sides=6, modifier=0), actor_id=actor.entity_id, reason="BURNING_WEAPON_DAMAGE")
            self._record_roll(bonus)
            total += bonus.total
            self._append_event(
                "PASSIVE_TRIGGERED",
                "action:fire.burning_weapon",
                actor_id=actor.entity_id,
                target_ids=(target.entity_id,),
                payload={"added_fire_damage": bonus.total},
            )
        combustive = next(
            (row for row in actor.modifiers.values() if row.source_definition_id == "action:fire.combustive_step" and row.target_field == "next_qualifying_attack_damage"),
            None,
        )
        if combustive is not None:
            total += actor.proficiency_bonus
            actor.modifiers.pop(combustive.modifier_id, None)
            self._append_event(
                "MODIFIER_REMOVED",
                "action:fire.combustive_step",
                actor_id=actor.entity_id,
                payload={"modifier_id": combustive.modifier_id, "reason": "CONSUMED"},
            )
        if cinder_touch and "passive:cinder.touch_damage" in actor.passive_ids:
            self._claim_once_per_turn(actor, "passive:cinder.touch_damage")
            total += 3
            self._append_event(
                "PASSIVE_TRIGGERED",
                "passive:cinder.touch_damage",
                actor_id=actor.entity_id,
                target_ids=(target.entity_id,),
                payload={"added_damage": 3, "damage_type": "FIRE"},
            )
        hp_damage = self._commit_damage(
            target,
            total,
            damage_type,
            source_id,
            actor.entity_id,
            intent,
            reaction_depth=0,
        )
        if hp_damage > 0 and damage_type == "FIRE" and "passive:cinder.revealing_ember" in actor.passive_ids and target.active:
            self._apply_condition(
                target,
                "condition:fire.revealing_ember",
                "passive:cinder.revealing_ember",
                actor.entity_id,
                expires_on="START_OF_SELF_NEXT_TURN",
                data={"revealed_to": actor.entity_id, "range_ft": 60, "dim_light_radius_ft": 5},
            )
            self._append_event(
                "PASSIVE_TRIGGERED",
                "passive:cinder.revealing_ember",
                actor_id=actor.entity_id,
                target_ids=(target.entity_id,),
            )
        if overheat:
            self._ignore_resistance_sources.add("augment:fire.overheat_ignite")
            before = actor.current_hp
            actor.current_hp = max(1, actor.current_hp - 3)
            self._append_event(
                "DAMAGE_COMMITTED",
                "augment:fire.overheat_ignite",
                actor_id=actor.entity_id,
                target_ids=(actor.entity_id,),
                payload={
                    "rolled_or_pending_damage": 3,
                    "reduced_to": 3,
                    "temporary_hp_absorbed": 0,
                    "hp_damage": before - actor.current_hp,
                    "damage_type": "FIRE",
                    "remaining_hp": actor.current_hp,
                    "minimum_hp": 1,
                    "ignores_resistance": True,
                },
            )
        return True

    def _resolve_typed_check(
        self,
        actor: ActorState,
        target: ActorState,
        *,
        source_id: str,
        target_mode: str,
    ) -> bool:
        actor_bonus = actor.skills.get("Sleight of Hand", actor.saving_throws.get("DEX", 0))
        if target_mode == "PASSIVE_PERCEPTION":
            dc = 10 + target.skills.get("Perception", target.saving_throws.get("WIS", 0))
            actor_roll = self.roller.d20(modifier=actor_bonus, actor_id=actor.entity_id, reason=f"CHECK:{source_id}")
            self._record_roll(actor_roll)
            success = actor_roll.total >= dc
            payload = {"actor": actor_roll.model_dump(mode="json"), "dc": dc, "success": success}
        else:
            athletics = target.skills.get("Athletics", target.saving_throws.get("STR", 0))
            acrobatics = target.skills.get("Acrobatics", target.saving_throws.get("DEX", 0))
            defender_bonus = max(athletics, acrobatics)
            actor_roll = self.roller.d20(modifier=actor_bonus, actor_id=actor.entity_id, reason=f"CHECK:{source_id}:ACTOR")
            defender_roll = self.roller.d20(modifier=defender_bonus, actor_id=target.entity_id, reason=f"CHECK:{source_id}:DEFENDER")
            self._record_roll(actor_roll)
            self._record_roll(defender_roll)
            success = actor_roll.total > defender_roll.total
            payload = {
                "actor": actor_roll.model_dump(mode="json"),
                "defender": defender_roll.model_dump(mode="json"),
                "success": success,
                "ties": "defender",
            }
        self._append_event(
            "CHECK_ROLLED",
            source_id,
            actor_id=actor.entity_id,
            target_ids=(target.entity_id,),
            payload=payload,
        )
        return success

    def _validate_target(self, actor: ActorState, action: ActionDefinition, target: ActorState | None, destination: Position | None) -> None:
        if action.target_kind == "SELF":
            return
        if action.target_kind == "CELL":
            if destination is None:
                raise ValueError("action requires a destination")
            if self._distance_actor_to_cell(actor, destination) > int(action.range_ft or 0):
                raise ValueError("destination is out of range")
            if not self._line_of_sight_actor_to_cell(actor, destination):
                raise ValueError("destination lacks line of sight")
            return
        if target is None:
            raise ValueError("action requires a typed actor target")
        if action.target_kind == "HOSTILE_ENTITY" and target.team_id == actor.team_id:
            raise ValueError("action requires a hostile target")
        if not self._target_in_range(actor, target, action):
            raise ValueError("target is out of range")
        if not self._line_of_sight_actor_to_actor(actor, target):
            raise ValueError("target lacks line of sight")

    def execute_action(self, request: RuntimeActionRequest) -> RuntimeExecutionResult:
        action = self.action_catalog.get(request.action_id)
        if action is None:
            raise ValueError("action is not registered in the runtime adapter catalog")
        actor = self.state.actors[request.actor_id]
        if request.action_id not in actor.action_ids:
            raise ValueError("actor does not own the action")
        target = self.state.actors.get(request.target_id) if request.target_id else None
        self._validate_target(actor, action, target, request.destination)
        pre_state = canonical_sha256(self.state.model_dump(mode="json", by_alias=True))
        events_before = len(self.events)
        rolls_before = len(self.rolls)
        intent = ActionIntent(
            intent_id=request.request_id,
            decision_id=f"isolated:{self.state.state_version}",
            candidate_id=f"isolated:{request.action_id}",
            state_version=self.state.state_version,
            actor_id=actor.entity_id,
            target_ids=(target.entity_id,) if target else (),
            destination=request.destination,
            option_ids=request.option_ids,
            reaction_decisions=request.reaction_decisions,
        )
        self._active_intent = intent
        try:
            with self._transaction(action.source_definition_id, request.request_id, actor.entity_id):
                self._append_event(
                    "INTENT_ACCEPTED",
                    action.source_definition_id,
                    actor_id=actor.entity_id,
                    target_ids=(target.entity_id,) if target else (),
                    payload={"runtime_adapter": RUNTIME_ADAPTER_ID, "option_ids": list(request.option_ids)},
                )
                self._consume_economy(actor, action)
                self._spend_costs(actor, action.costs, action.source_definition_id)
                self._dispatch_action(action, actor, target, request, intent)
        finally:
            self._active_intent = None
        post_state = canonical_sha256(self.state.model_dump(mode="json", by_alias=True))
        return RuntimeExecutionResult(
            action_id=request.action_id,
            actor_id=actor.entity_id,
            target_id=target.entity_id if target else None,
            pre_state_sha256=pre_state,
            post_state_sha256=post_state,
            events=tuple(row.model_dump(mode="json") for row in self.events[events_before:]),
            rolls=tuple(row.model_dump(mode="json") for row in self.rolls[rolls_before:]),
        )

    def _dispatch_action(
        self,
        action: ActionDefinition,
        actor: ActorState,
        target: ActorState | None,
        request: RuntimeActionRequest,
        intent: ActionIntent,
    ) -> None:
        kind = action.resolution_kind
        options = set(request.option_ids)
        if kind == "C3AR_DASH":
            actor.movement_remaining_ft += self._effective_speed(actor)
            self._append_event("PASSIVE_TRIGGERED", action.source_definition_id, actor_id=actor.entity_id, payload={"movement_remaining_ft": actor.movement_remaining_ft})
            if actor.resources.get("resource:core.martial_focus", 0) == 0:
                self._gain_resource(actor, "resource:core.martial_focus", 1, "passive:scoundrel.martial_focus_rules")
        elif kind == "C3AR_DISENGAGE":
            actor.turn_flags["disengaged"] = True
            self._append_event("PASSIVE_TRIGGERED", action.source_definition_id, actor_id=actor.entity_id, payload={"prevents_opportunity_attacks": True})
            if actor.resources.get("resource:core.martial_focus", 0) == 0:
                self._gain_resource(actor, "resource:core.martial_focus", 1, "passive:scoundrel.martial_focus_rules")
        elif kind == "C3AR_DODGE":
            self._apply_condition(actor, "condition:core.dodging", action.source_definition_id, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
        elif kind == "C3AR_UNARMED_STRIKE":
            assert target is not None
            self._resolve_character_attack(actor, target, source_id=action.source_definition_id, attack_bonus=2, damage=None, damage_type="BLUDGEONING", intent=intent, fixed_damage=2, ranged=False)
        elif kind == "C3AR_BURNING_WEAPON":
            self._start_concentration(actor, action.source_definition_id)
            self._apply_condition(actor, "condition:fire.burning_weapon", action.source_definition_id, actor.entity_id, expires_on="CONCENTRATION_END", data={"extra_damage": "1d6", "once_per_turn": True})
        elif kind == "C3AR_COMBUSTIVE_STEP":
            if request.destination is None:
                raise ValueError("Combustive Step requires a destination")
            actor.turn_flags["c3ar:no_opportunity_source"] = action.source_definition_id
            try:
                self._no_opportunity_movement(actor, request.destination, action.source_definition_id, intent)
            finally:
                actor.turn_flags.pop("c3ar:no_opportunity_source", None)
            self._add_modifier(actor, action.source_definition_id, "next_qualifying_attack_damage", "ADD", actor.proficiency_bonus, "IGNITE_OR_MELEE_ATTACK", expires_on="END_OF_CURRENT_TURN")
        elif kind in {"C3AR_CONFLAGRATION", "C3AR_FIREBALL_ART"}:
            if request.destination is None:
                raise ValueError("area action requires destination")
            self._resolve_area_fire(action, actor, request.destination, request, intent)
        elif kind == "C3AR_FLAME_LASH":
            assert target is not None
            hit = self._resolve_character_attack(actor, target, source_id=action.source_definition_id, attack_bonus=6, damage=action.damage, damage_type="FIRE", intent=intent, ranged=True, advantage_if_burning=True, qi_powered=True, cinder_touch="USE_CINDER_TOUCH" in options)
            if hit and target.active:
                movement_options = options & {"PUSH_10_FT", "PULL_10_FT", "NO_MOVEMENT"}
                if len(movement_options) != 1:
                    raise ValueError("Flame Lash requires exactly one movement disposition")
                if "PUSH_10_FT" in movement_options:
                    self._forced_movement(actor, target, 10, pull=False, source_id=action.source_definition_id)
                elif "PULL_10_FT" in movement_options:
                    self._forced_movement(actor, target, 10, pull=True, source_id=action.source_definition_id)
        elif kind == "C3AR_IGNITE":
            assert target is not None
            rider_options = options & {"PUSH_5_FT", "CREATE_FIRE_TERRAIN", "INCREASE_BURN", "KINDLED_BONUS_DAMAGE"}
            if len(rider_options) != 1:
                raise ValueError("Ignite requires exactly one typed rider choice")
            overheat = "AUGMENT_OVERHEAT" in options
            damage = action.damage
            if overheat:
                self._spend_resource(actor, "resource:core.qi", 1, "augment:fire.overheat_ignite")
                damage = DiceSpec(count=3, sides=10, modifier=0)
                self._append_event("PASSIVE_TRIGGERED", "augment:fire.overheat_ignite", actor_id=actor.entity_id, target_ids=(target.entity_id,))
            if "KINDLED_BONUS_DAMAGE" in rider_options and self._is_kindled(target):
                damage = damage.model_copy(update={"modifier": damage.modifier + actor.proficiency_bonus})
            hit = self._resolve_character_attack(actor, target, source_id=action.source_definition_id, attack_bonus=6, damage=damage, damage_type="FIRE", intent=intent, ranged=True, qi_powered=True, cinder_touch="USE_CINDER_TOUCH" in options, overheat=overheat)
            if hit and target.active:
                burn_damage = 3 + (actor.proficiency_bonus if "INCREASE_BURN" in rider_options else 0)
                self._apply_burn(actor, target, action.source_definition_id, burn_damage)
                if "PUSH_5_FT" in rider_options:
                    self._forced_movement(actor, target, 5, pull=False, source_id=action.source_definition_id)
                elif "CREATE_FIRE_TERRAIN" in rider_options:
                    self._create_runtime_zone(actor, action, target.position, kind="FIRE_TERRAIN", radius_ft=0, concentration_link=False, extra={"dc": 14, "burn_damage": 3, "lightly_obscured": True})
        elif kind == "C3AR_MERIDIAN_REGULATION":
            assert target is not None
            if not request.condition_instance_id or not request.penalty_id or not request.source_effect_dc:
                raise ValueError("Meridian Regulation requires condition instance, exact penalty, and printed DC")
            condition = target.conditions.get(request.condition_instance_id)
            if condition is None:
                raise ValueError("Meridian Regulation condition instance is absent")
            eligible = set(condition.data.get("effect_tags", ())) & {"poison", "disease", "directly_caused_physical_impairment"}
            excluded = set(condition.data.get("effect_tags", ())) & {"curse", "tribulation", "foundation_injury", "hidden_injury", "possession", "permanent", "soul_damage"}
            if not eligible or excluded:
                raise ValueError("effect is not eligible for Meridian Regulation")
            save = self.roller.d20(modifier=target.saving_throws.get("CON", 0), actor_id=target.entity_id, reason="SAVE:action:qi.meridian_regulation:CON", mode="ADVANTAGE")
            self._record_roll(save)
            success = save.total >= request.source_effect_dc
            self._append_event("SAVE_ROLLED", action.source_definition_id, actor_id=target.entity_id, payload={**save.model_dump(mode="json"), "dc": request.source_effect_dc, "success": success})
            if success:
                self._suppress_condition_penalty(target, request.condition_instance_id, request.penalty_id, action.source_definition_id, expires_on="SOURCE_EFFECT_END")
        elif kind == "C3AR_DIRTY_TRICK":
            assert target is not None
            success = self._resolve_typed_check(actor, target, source_id=action.source_definition_id, target_mode="OPPOSED")
            if success:
                choices = options & {"BLINDED", "DEAFENED", "HALVE_SPEED", "PRONE", "REACTION_DENIED", "EXPLOITED_OPENING"}
                if len(choices) != 1:
                    raise ValueError("Dirty Trick requires one success option")
                choice = next(iter(choices))
                if choice == "BLINDED":
                    self._apply_condition(target, "condition:core.blinded", action.source_definition_id, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
                elif choice == "DEAFENED":
                    self._apply_condition(target, "condition:core.deafened", action.source_definition_id, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
                elif choice == "HALVE_SPEED":
                    self._add_modifier(target, action.source_definition_id, "speed_multiplier", "MULTIPLY", "1/2", "ALL_MOVEMENT", expires_on="START_OF_SELF_NEXT_TURN")
                elif choice == "PRONE":
                    self._apply_condition(target, "condition:core.prone", action.source_definition_id, actor.entity_id, expires_on="UNTIL_REMOVED")
                elif choice == "REACTION_DENIED":
                    self._apply_condition(target, "condition:core.reaction_denied", action.source_definition_id, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN", data={"reaction_denied": True})
                else:
                    self._apply_condition(actor, "condition:scoundrel.exploited_opening", "passive:scoundrel.exploited_opening", actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN", data={"target_id": target.entity_id, "prevents_target_opportunity_attack": True})
        elif kind == "C3AR_STEAL":
            assert target is not None
            unaware = "TARGET_UNAWARE" in options
            success = self._resolve_typed_check(actor, target, source_id=action.source_definition_id, target_mode="PASSIVE_PERCEPTION" if unaware else "OPPOSED")
            self._append_event("PASSIVE_TRIGGERED", action.source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"success": success, "object_activated": False})
        else:
            raise ValueError(f"unsupported C3A-R action kind: {kind}")

    def _is_kindled(self, target: ActorState) -> bool:
        return self._has_condition(target, "condition:core.burning") or self._has_condition(target, "condition:fire.kindled") or any(self._in_zone(target, zone) and zone.trigger_profile.get("kind") == "FIRE_TERRAIN" for zone in self.state.zones.values() if zone.active)

    def _apply_burn(self, actor: ActorState, target: ActorState, source_id: str, damage: int) -> None:
        existing = [row for row in target.conditions.values() if row.condition_id == "condition:core.burning" and row.source_actor_id == actor.entity_id]
        if existing:
            existing[0].data["burn_damage"] = max(int(existing[0].data.get("burn_damage", 3)), damage)
            self._append_event("CONDITION_APPLIED", source_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"condition_id": "condition:core.burning", "instance_id": existing[0].instance_id, "burn_damage": existing[0].data["burn_damage"], "stacked": False})
            return
        self._apply_condition(target, "condition:core.burning", source_id, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN", data={"burn_damage": damage})

    def resolve_burn_start_of_turn(self, target_id: str) -> int:
        target = self.state.actors[target_id]
        burns = [row for row in target.conditions.values() if row.condition_id == "condition:core.burning"]
        if not burns:
            return 0
        damage = max(int(row.data.get("burn_damage", 3)) for row in burns)
        source = sorted(burns, key=lambda row: row.instance_id)[0]
        with self._transaction("passive:fire.core_rules", f"burn:{target_id}:{target.turns_started}", target_id):
            self._commit_damage(target, damage, "FIRE", "passive:fire.core_rules", source.source_actor_id, None, reaction_depth=0)
            self._append_event("PASSIVE_TRIGGERED", "passive:fire.core_rules", actor_id=source.source_actor_id, target_ids=(target_id,), payload={"burn_damage": damage})
        return damage

    def resolve_fire_terrain_trigger(self, zone_id: str, target_id: str) -> bool:
        zone = self.state.zones[zone_id]
        target = self.state.actors[target_id]
        owner = self.state.actors[zone.owner_id]
        with self._transaction(zone.source_definition_id, f"fire-terrain:{zone_id}:{target_id}:{target.turns_started}", target_id):
            self._claim_once_per_turn(target, f"fire_terrain:{zone_id}")
            save = self._roll_save(target, "DEX", int(zone.trigger_profile.get("dc", 14)), zone.source_definition_id)
            if save.total < int(zone.trigger_profile.get("dc", 14)):
                self._commit_damage(target, int(zone.trigger_profile.get("burn_damage", 3)), "FIRE", zone.source_definition_id, owner.entity_id, None, reaction_depth=0)
                self._apply_burn(owner, target, zone.source_definition_id, int(zone.trigger_profile.get("burn_damage", 3)))
                return False
            self._apply_condition(target, "condition:fire.kindled", zone.source_definition_id, owner.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
            return True

    def _resolve_area_fire(
        self,
        action: ActionDefinition,
        actor: ActorState,
        center: Position,
        request: RuntimeActionRequest,
        intent: ActionIntent,
    ) -> None:
        radius_cells = int(action.radius_ft or 0) // self.grid.square_size_ft
        affected_cells = set((row.x, row.y) for row in self.grid.cells_in_radius(center, radius_cells))
        targets = [
            row
            for row in self.state.actors.values()
            if row.entity_id != actor.entity_id and row.active and bool(set(self._actor_cells(row)) & affected_cells)
        ]
        damage_roll = self.roller.roll(action.damage, actor_id=actor.entity_id, reason=f"DAMAGE:{action.source_definition_id}")
        self._record_roll(damage_roll)
        self._append_event("DAMAGE_ROLLED", action.source_definition_id, actor_id=actor.entity_id, payload=damage_roll.model_dump(mode="json"))
        base_damage = damage_roll.total
        if "passive:qi.technique_potency" in actor.passive_ids:
            base_damage += 3
            self._append_event("PASSIVE_TRIGGERED", "passive:qi.technique_potency", actor_id=actor.entity_id, payload={"added_damage": 3, "source": action.source_definition_id})
        cinder_available = "USE_CINDER_TOUCH" in request.option_ids and "passive:cinder.touch_damage" in actor.passive_ids
        cinder_used = False
        for target in sorted(targets, key=lambda row: row.entity_id):
            save = self._roll_save(target, "DEX", 14, action.source_definition_id)
            amount = base_damage if save.total < 14 else base_damage // 2
            if cinder_available and not cinder_used:
                self._claim_once_per_turn(actor, "passive:cinder.touch_damage")
                amount += 3
                cinder_used = True
                self._append_event("PASSIVE_TRIGGERED", "passive:cinder.touch_damage", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"added_damage": 3})
            self._commit_damage(target, amount, "FIRE", action.source_definition_id, actor.entity_id, intent, reaction_depth=0)
            if target.active:
                if save.total < 14:
                    self._apply_burn(actor, target, action.source_definition_id, 3)
                elif action.source_definition_id == "action:fire.conflagration":
                    self._apply_condition(target, "condition:fire.kindled", action.source_definition_id, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
        zone = None
        if action.source_definition_id == "action:fire.conflagration":
            zone = self._create_runtime_zone(actor, action, center, kind="FIRE_TERRAIN", radius_ft=15, concentration_link=True, extra={"dc": 14, "burn_damage": 3, "lightly_obscured": True})
            if "AUGMENT_HEAT_HAZE" in request.option_ids:
                self._apply_augment(actor, "augment:fire.heat_haze", zone)
            if "AUGMENT_LINGERING" in request.option_ids:
                self._apply_augment(actor, "augment:fire.lingering_conflagration", zone)
        for object_id in request.object_ids:
            obj = self.state.objects.get(object_id)
            if obj is None or (obj.position.x, obj.position.y) not in affected_cells:
                raise ValueError("object target is not a typed object in the affected area")
            self._ignite_object(object_id, action.source_definition_id, actor.entity_id)

    def _apply_augment(self, actor: ActorState, augment_id: str, zone: ZoneState | None = None) -> None:
        if augment_id not in actor.augment_ids:
            raise ValueError("actor does not own augment")
        if augment_id == "augment:fire.heat_haze":
            if zone is None or zone.source_definition_id != "action:fire.conflagration":
                raise ValueError("Heat Haze requires an existing Conflagration zone")
            self._spend_resource(actor, "resource:core.qi", 1, augment_id)
            zone.trigger_profile["heat_haze"] = True
            zone.trigger_profile["ranged_attacks_through_disadvantage"] = True
            self._append_event("PASSIVE_TRIGGERED", augment_id, actor_id=actor.entity_id, payload={"zone_id": zone.zone_id, "zone_after": zone.model_dump(mode="json")})
        elif augment_id == "augment:fire.lingering_conflagration":
            if zone is None or zone.source_definition_id != "action:fire.conflagration":
                raise ValueError("Lingering Conflagration requires an existing Conflagration zone")
            self._spend_resource(actor, "resource:core.qi", 2, augment_id)
            zone.concentration_link = False
            zone.duration_rounds = 10
            if actor.concentration and actor.concentration.zone_id == zone.zone_id:
                actor.concentration = None
                self._append_event("CONCENTRATION_ENDED", augment_id, actor_id=actor.entity_id, payload={"reason": "LINGERING_CONFLAGRATION", "zone_persists": True})
            self._append_event("PASSIVE_TRIGGERED", augment_id, actor_id=actor.entity_id, payload={"zone_id": zone.zone_id, "persists_without_concentration": True, "zone_after": zone.model_dump(mode="json")})
        else:
            raise ValueError("Overheat is applied only as an Ignite activation augment")

    def evaluate_passive(self, actor_id: str, passive_id: str, context: dict[str, Any]) -> dict[str, Any]:
        actor = self.state.actors[actor_id]
        if passive_id not in actor.passive_ids:
            raise ValueError("actor does not own passive")
        result: dict[str, Any]
        if passive_id == "passive:qi.qi_sensing":
            active_energy = bool(context.get("active_supernatural_energy"))
            blocked = bool(context.get("blocked_by_typed_material"))
            distance = int(context.get("distance_ft", 999))
            result = {"detected": active_energy and not blocked and distance <= 30, "precise_space_revealed": False}
        elif passive_id == "passive:origin.street_hardened":
            ordinary = bool(context.get("ordinary_ambush_or_street_threat"))
            attentive = bool(context.get("awake_mobile_attentive"))
            excluded = bool(context.get("supernatural_concealment_or_extraordinary_trap"))
            applies = ordinary and attentive and not excluded
            result = {"cannot_be_surprised": applies, "initiative_advantage": applies, "perception_advantage": applies}
        elif passive_id == "passive:scoundrel.martial_focus_rules":
            result = {"maximum": 1, "current": actor.resources.get("resource:core.martial_focus", 0), "cannot_spend_when_absent": True}
        elif passive_id == "passive:fire.core_rules":
            result = {"kindled": bool(context.get("target_id") and self._is_kindled(self.state.actors[str(context["target_id"])])), "fire_zone_count": sum(1 for zone in self.state.zones.values() if zone.active and zone.trigger_profile.get("kind") == "FIRE_TERRAIN")}
        else:
            result = {"bound": True, "handled_by_action_or_damage_hook": True}
        with self._transaction(passive_id, f"passive-eval:{passive_id}:{self.state.event_sequence+1}", actor_id):
            self._append_event("PASSIVE_TRIGGERED", passive_id, actor_id=actor_id, payload={"context": context, "result": result})
        return result


def dummy_actor_template(
    entity_id: str,
    *,
    team_id: str = "team:dummy",
    armor_class: int = 12,
    maximum_hp: int = 100,
    reaction_ids: tuple[str, ...] = (),
    qi: int = 0,
    fire_resistance: bool = False,
) -> ActorTemplate:
    return ActorTemplate(
        entity_id=entity_id,
        display_name=entity_id,
        team_id=team_id,
        primary_combatant=False,
        armor_class=armor_class,
        maximum_hp=maximum_hp,
        speed_ft=30,
        initiative_bonus=0,
        dexterity_score=10,
        proficiency_bonus=3,
        saving_throws={"STR": 0, "DEX": 0, "CON": 0, "INT": 0, "WIS": 0, "CHA": 0},
        skills={"Athletics": 0, "Acrobatics": 0, "Perception": 0, "Sleight of Hand": 0},
        resources=(ResourceDefinition(resource_id="resource:core.qi", initial=qi, maximum=max(qi, 15)),),
        action_ids=(),
        reaction_ids=reaction_ids,
        damage_resistances=("FIRE",) if fire_resistance else (),
    )
