from __future__ import annotations

import copy
import json
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_sha256
from .choice_authority import choice_authority_status, choice_domains_for, validate_option_selection
from .diagnostics import RecoveryDisposition, error
from .footprint_registry import ACTOR_FOOTPRINTS, resolve_actor_footprint
from .footprints import ActorFootprintDefinition
from .gate2_grid import SquareGrid
from .gate2_rolls import DeterministicRollAuthority
from .gate2_runtime_content import ACTIONS, ACTORS, BASIC_MELEE, REACTION_PARAMETERS, AN, BAI, CUI, LEE, LING
from .gate2_runtime_models import (
    ActionDefinition,
    ActionIntent,
    ActorState,
    CandidateAreaProjection,
    CandidateKind,
    CombatEvent,
    ConditionInstance,
    ConcentrationState,
    EconomyKind,
    LegalCandidate,
    MatchState,
    ModifierInstance,
    PendingResolution,
    Position,
    ReactionDecision,
    RollRecord,
    RuntimeExport,
    TerminalKind,
    TerminalResult,
    ZoneState,
)

SYSTEM_MATCH = "system:combat.match"
SYSTEM_INITIATIVE = "system:combat.initiative"
SYSTEM_TURN = "system:combat.turn"
SYSTEM_MOVE = "system:combat.movement"
SYSTEM_HAZARD = "system:battlefield.qi_hazard"
SYSTEM_OPPORTUNITY = "system:combat.opportunity_attack"
SYSTEM_CONCENTRATION = "system:combat.concentration"
SYSTEM_DEFEAT = "system:combat.nonlethal_defeat"
SYSTEM_VICTORY = "system:combat.victory"
SYSTEM_EXPIRATION = "system:combat.expiration"
SYSTEM_COMPANION_DEFAULT = "system:combat.companion_default"

GATE1_REGISTRY_SHA256 = "c3ed7fa15650d105fe375a2b6f3a1caf00a5ebc01ea8ffc1c23608dea6d403b1"


class Gate2Engine:
    """Bounded Gate 2 deterministic combat engine.

    Runtime execution consumes typed ActionDefinition and lock artifacts only. It never
    interprets character prose or exposes a generic arbitrary-delta mutation function.
    """

    def __init__(
        self,
        source_root: Path,
        *,
        match_seed: str,
        maximum_rounds: int = 20,
        actor_footprints: dict[str, ActorFootprintDefinition] | None = None,
        genesis_setup: dict[str, dict[str, object]] | None = None,
        roster_setup: dict[str, object] | None = None,
        runtime_authority: dict[str, Any] | None = None,
    ):
        self.source_root = Path(source_root)
        self.grid = SquareGrid.load(self.source_root / "combat_gate1/generated/Battlefield.json")
        self.action_catalog = dict(ACTIONS)
        self.actor_templates = dict(ACTORS)
        self.reaction_parameters = copy.deepcopy(REACTION_PARAMETERS)
        self.runtime_authority = None
        self.runtime_actor_ids: set[str] = set()
        self._ignore_resistance_sources: set[str] = set()
        self._persistent_match_created = True
        if runtime_authority:
            from .portable_runtime_authority import PortableRuntimeAuthority
            authority = PortableRuntimeAuthority.model_validate(runtime_authority)
            bundle = authority.runtime_bundle()
            self.runtime_authority = authority
            self.runtime_actor_ids.add(authority.runtime_actor_id)
            self.actor_templates[authority.runtime_actor_id] = bundle.actor_template
            for row in bundle.action_catalog:
                if row.source_definition_id in self.action_catalog:
                    raise ValueError(f"C3D_RUNTIME_ACTION_ID_COLLISION:{row.source_definition_id}")
                self.action_catalog[row.source_definition_id] = row
            for reaction_id, params in bundle.reaction_parameters.items():
                if reaction_id in self.reaction_parameters and self.reaction_parameters[reaction_id] != params:
                    raise ValueError(f"C3D_RUNTIME_REACTION_ID_COLLISION:{reaction_id}")
                self.reaction_parameters[reaction_id] = copy.deepcopy(params)
        supplied_footprints = actor_footprints or ACTOR_FOOTPRINTS
        self.actor_footprints: dict[str, ActorFootprintDefinition] = {}
        for actor_id in self.actor_templates:
            definition = supplied_footprints.get(actor_id)
            if definition is None and actor_id in self.runtime_actor_ids:
                from .footprints import standard_actor_footprint
                definition = standard_actor_footprint().model_copy(update={
                    "footprint_id": f"footprint:{actor_id}.1x1",
                    "source_definition_id": f"system:combat.actor_footprint:{actor_id}",
                })
            if definition is None:
                definition, _ = resolve_actor_footprint(actor_id)
            self.actor_footprints[actor_id] = definition.model_copy(deep=True)
        lock_path = self.source_root / "combat_gate2/generated/Gate2_Executable_Mechanics_Lock.json"
        defaults_path = self.source_root / "combat_gate2/generated/Gate2_Universal_Combat_Defaults_Lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        defaults = json.loads(defaults_path.read_text(encoding="utf-8"))
        if lock.get("material_unresolved_count") != 0 or lock.get("status") != "PASS":
            raise error(
                "GATE2_MECHANICS_LOCK_BLOCKED",
                "The Gate 2 mechanics lock is not executable.",
                phase="MATCH_CREATION", subsystem="MECHANICS_LOCK",
                recommended_action="Resolve every material mechanics gap and regenerate the lock.",
            )
        self.mechanics_lock_sha256 = lock.get("calculated_sha256") or canonical_sha256(lock)
        self.universal_defaults_lock_sha256 = defaults.get("calculated_sha256") or canonical_sha256(defaults)
        self.events: list[CombatEvent] = []
        self.rolls: list[RollRecord] = []
        self.roller = DeterministicRollAuthority(match_seed)
        self._transaction_id: str | None = None
        self._transaction_result_version = 0
        self._active_intent_id = "system:create"
        self._active_intent: ActionIntent | None = None
        self._commanded_cui_this_turn = False
        self._roster_setup = dict(roster_setup or {})
        self.state = self._create_match(match_seed, maximum_rounds)
        if genesis_setup:
            self._apply_genesis_setup(genesis_setup)


    def _apply_genesis_setup(self, setup: dict[str, dict[str, object]]) -> None:
        """Apply already validated owner setup before genesis is sealed."""
        occupied: set[tuple[int, int]] = set()
        for actor_id in sorted(setup):
            actor = self.state.actors[actor_id]
            row = setup[actor_id]
            pos = Position.model_validate(row["placement"])
            footprint = self._footprint(actor_id)
            if not self.grid.placement_legal(pos, footprint=footprint, occupied_cells=occupied):
                raise ValueError(f"C3C_GENESIS_PLACEMENT_INVALID:{actor_id}")
            occupied.update(self.grid.footprint_cells(pos, footprint))
            actor.position = pos
            for resource_id, value in dict(row.get("resources") or {}).items():
                if resource_id not in actor.resource_maximums:
                    raise ValueError(f"C3C_GENESIS_RESOURCE_UNKNOWN:{actor_id}:{resource_id}")
                amount = int(value)
                if amount < 0 or amount > actor.resource_maximums[resource_id]:
                    raise ValueError(f"C3C_GENESIS_RESOURCE_INVALID:{actor_id}:{resource_id}")
                actor.resources[resource_id] = amount

    # ------------------------------------------------------------------
    # Typed footprint authority
    # ------------------------------------------------------------------
    def _footprint(self, actor: ActorState | str) -> ActorFootprintDefinition:
        actor_id = actor if isinstance(actor, str) else actor.entity_id
        definition = self.actor_footprints.get(actor_id)
        if definition is None:
            definition, _ = resolve_actor_footprint(actor_id)
            self.actor_footprints[actor_id] = definition.model_copy(deep=True)
        return definition

    def _actor_cells(
        self,
        actor: ActorState,
        position: Position | None = None,
    ) -> tuple[tuple[int, int], ...]:
        return self._footprint(actor).occupied_cells(position or actor.position)

    def _occupied_cells_except(self, actor_id: str) -> set[tuple[int, int]]:
        occupied: set[tuple[int, int]] = set()
        for other in self.state.actors.values():
            if other.active and other.entity_id != actor_id:
                occupied.update(self._actor_cells(other))
        return occupied

    def _distance_actor_to_actor(
        self,
        actor: ActorState,
        target: ActorState,
        *,
        actor_position: Position | None = None,
        target_position: Position | None = None,
    ) -> int:
        return self.grid.distance_between_cell_sets_ft(
            self._actor_cells(actor, actor_position),
            self._actor_cells(target, target_position),
        )

    def _distance_actor_to_cell(
        self,
        actor: ActorState,
        cell: Position,
        *,
        actor_position: Position | None = None,
    ) -> int:
        return self.grid.distance_between_cell_sets_ft(
            self._actor_cells(actor, actor_position),
            ((cell.x, cell.y),),
        )

    def _line_of_sight_actor_to_actor(
        self,
        actor: ActorState,
        target: ActorState,
    ) -> bool:
        return self.grid.line_of_sight_between_cell_sets(
            self._actor_cells(actor),
            self._actor_cells(target),
            obscured_cells=self._obscured_cells(),
        )

    def _line_of_sight_actor_to_cell(
        self,
        actor: ActorState,
        cell: Position,
    ) -> bool:
        return self.grid.line_of_sight_between_cell_sets(
            self._actor_cells(actor),
            ((cell.x, cell.y),),
            obscured_cells=self._obscured_cells(),
        )

    def _cover_bonus_actor_to_actor(
        self,
        actor: ActorState,
        target: ActorState,
    ) -> int:
        return self.grid.cover_bonus_between_cell_sets(
            self._actor_cells(actor),
            self._actor_cells(target),
            obscured_cells=self._obscured_cells(),
        )

    def _footprint_intersects(
        self,
        actor: ActorState,
        cells: Iterable[Position | tuple[int, int]],
        *,
        position: Position | None = None,
    ) -> bool:
        target_cells = {
            (cell.x, cell.y) if isinstance(cell, Position) else cell
            for cell in cells
        }
        return bool(set(self._actor_cells(actor, position)) & target_cells)

    def _path_intersects_cells(
        self,
        actor: ActorState,
        path: Iterable[Position],
        cells: set[tuple[int, int]],
    ) -> bool:
        return any(self._footprint_intersects(actor, cells, position=position) for position in path)

    # ------------------------------------------------------------------
    # Match creation and transactions
    # ------------------------------------------------------------------
    def _create_match(self, seed: str, maximum_rounds: int) -> MatchState:
        selected_primary = tuple(self._roster_setup.get("primary_actor_ids") or (AN, LEE, LING, BAI))
        if len(selected_primary) < 2 or len(set(selected_primary)) != len(selected_primary):
            raise ValueError("C3C_DYNAMIC_ROSTER_INVALID")
        unknown = set(selected_primary) - set(self.actor_templates)
        if unknown:
            raise ValueError(f"C3C_DYNAMIC_ROSTER_UNKNOWN:{sorted(unknown)}")
        included = list(selected_primary)
        if BAI in selected_primary:
            included.append(CUI)
        team_overrides = dict(self._roster_setup.get("team_by_actor") or {})
        if BAI in selected_primary:
            team_overrides[CUI] = team_overrides.get(BAI, self.actor_templates[BAI].team_id)
        actors: dict[str, ActorState] = {}
        for entity_id in included:
            template = self.actor_templates[entity_id]
            supplied_positions = dict(self._roster_setup.get("starting_positions") or {})
            if entity_id in supplied_positions:
                pos = Position.model_validate(supplied_positions[entity_id])
            elif entity_id in self.grid.starting_positions:
                pos = self.grid.starting_positions[entity_id]
            else:
                occupied = {tuple((a.position.x, a.position.y)) for a in actors.values()}
                pos = next(
                    Position(x=x, y=y)
                    for y in range(self.grid.height)
                    for x in range(self.grid.width)
                    if (x, y) not in self.grid.blocked and (x, y) not in occupied
                )
            actors[entity_id] = ActorState(
                entity_id=entity_id, display_name=template.display_name,
                team_id=str(team_overrides.get(entity_id, template.team_id)),
                primary_combatant=template.primary_combatant, owner_id=template.owner_id,
                projection_sha256=template.projection_sha256, armor_class=template.armor_class,
                maximum_hp=template.maximum_hp, current_hp=template.maximum_hp, position=pos,
                speed_ft=template.speed_ft, movement_remaining_ft=template.speed_ft,
                initiative_bonus=template.initiative_bonus, dexterity_score=template.dexterity_score,
                proficiency_bonus=template.proficiency_bonus, saving_throws=dict(template.saving_throws),
                resources={r.resource_id: r.initial for r in template.resources},
                resource_maximums={r.resource_id: r.maximum for r in template.resources},
                action_ids=template.action_ids, reaction_ids=template.reaction_ids,
                passive_ids=template.passive_ids if entity_id in self.runtime_actor_ids else (),
                augment_ids=template.augment_ids if entity_id in self.runtime_actor_ids else (),
                damage_resistances=template.damage_resistances if entity_id in self.runtime_actor_ids else (),
            )
        init_rows: list[tuple[int, int, int, str]] = []
        for entity_id in selected_primary:
            actor = actors[entity_id]
            roll = self.roller.d20(modifier=actor.initiative_bonus, actor_id=entity_id, reason="INITIATIVE")
            self._record_roll(roll)
            init_rows.append((roll.total, actor.initiative_bonus, actor.dexterity_score, entity_id))
        init_rows.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))
        order = [row[3] for row in init_rows]
        state = MatchState(
            match_id=f"match:{canonical_sha256({'seed': seed, 'actors': sorted(actors), 'teams': team_overrides})[:24]}",
            match_seed=seed, gate1_registry_snapshot_sha256=GATE1_REGISTRY_SHA256,
            mechanics_lock_sha256=self.mechanics_lock_sha256,
            universal_defaults_lock_sha256=self.universal_defaults_lock_sha256,
            initiative_order=order, current_actor_id=order[0],
            actors=actors, maximum_rounds=maximum_rounds,
        )
        self.state = state
        self._append_event("MATCH_CREATED", SYSTEM_MATCH, payload={"initiative_order": order})
        self._system_start_turn(initial=True)
        return self.state

    @contextmanager
    def _transaction(self, source_definition_id: str, intent_id: str, actor_id: str):
        if self._transaction_id is not None:
            raise error(
                "GATE2_NESTED_FOREGROUND_TRANSACTION",
                "A foreground resolution transaction is already active.",
                phase="RESOLUTION", subsystem="TRANSACTION", entity_id=actor_id,
                source_definition=source_definition_id,
                recommended_action="Finish or roll back the active transaction before retrying.",
                recovery=RecoveryDisposition.RETRY,
            )
        state_before = self.state.model_copy(deep=True)
        events_before = list(self.events)
        rolls_before = list(self.rolls)
        roller_counter_before = self.roller.counter
        transaction_id = f"txn:{self.state.event_sequence + 1:08d}:{uuid.uuid5(uuid.NAMESPACE_URL, intent_id).hex[:12]}"
        self._transaction_id = transaction_id
        self._transaction_result_version = self.state.state_version + 1
        self._active_intent_id = intent_id
        try:
            yield transaction_id
            self._assert_invariants()
            self.state.state_version = self._transaction_result_version
            self.state.roll_counter = self.roller.counter
        except Exception:
            self.state = state_before
            self.events = events_before
            self.rolls = rolls_before
            self.roller.counter = roller_counter_before
            raise
        finally:
            self._transaction_id = None
            self._transaction_result_version = self.state.state_version
            self._active_intent_id = "system"

    def _append_event(
        self,
        event_type: str,
        source_definition_id: str,
        *,
        actor_id: str | None = None,
        target_ids: Iterable[str] = (),
        payload: dict[str, Any] | None = None,
        trigger_or_intent_id: str | None = None,
    ) -> CombatEvent:
        if not source_definition_id:
            raise ValueError("all events require source_definition_id")
        sequence = len(self.events) + 1
        event = CombatEvent(
            sequence=sequence,
            state_version=self._transaction_result_version,
            event_type=event_type,
            source_definition_id=source_definition_id,
            trigger_or_intent_id=trigger_or_intent_id or self._active_intent_id,
            transaction_id=self._transaction_id or "txn:match-creation",
            actor_id=actor_id,
            target_ids=tuple(target_ids),
            payload=payload or {},
        )
        self.events.append(event)
        self.state.event_sequence = sequence
        return event

    def _record_roll(self, roll: RollRecord) -> None:
        self.rolls.append(roll)
        if hasattr(self, "state"):
            self.state.roll_counter = self.roller.counter

    # ------------------------------------------------------------------
    # Turn lifecycle
    # ------------------------------------------------------------------
    def _system_start_turn(self, *, initial: bool = False) -> None:
        actor = self.state.actors[self.state.current_actor_id]
        actor.turns_started += 1
        actor.action_available = actor.active
        actor.bonus_action_available = actor.active
        actor.reaction_available = actor.active
        actor.movement_remaining_ft = self._effective_speed(actor)
        actor.turn_flags = {
            key: value for key, value in actor.turn_flags.items()
            if "_round_" in key or key.startswith("once_per_round:")
        }
        self._commanded_cui_this_turn = False
        self._expire_for_checkpoint("START_OF_TURN", actor.entity_id)
        self._append_event("TURN_STARTED", SYSTEM_TURN, actor_id=actor.entity_id, payload={
            "round": self.state.round_number,
            "slot": self.state.current_slot_index,
            "initial": initial,
        })
        if actor.active:
            self._resolve_zone_triggers(actor, checkpoint="AT_TURN_START")
        if actor.entity_id == BAI and not actor.active and self.state.actors[CUI].active:
            self._cui_guard_and_rescue_default()

    def end_turn(self, intent_id: str = "system:end-turn") -> None:
        actor_id = self.state.current_actor_id
        with self._transaction(SYSTEM_TURN, intent_id, actor_id):
            actor = self.state.actors[actor_id]
            if actor_id == LING:
                self._resolve_zone_triggers_for_owner_end(LING)
            if actor_id == BAI and actor.active and self.state.actors[CUI].active and not self._commanded_cui_this_turn:
                self._cui_default_dodge()
            self._expire_for_checkpoint("END_OF_TURN", actor_id)
            self._append_event("TURN_ENDED", SYSTEM_TURN, actor_id=actor_id, payload={"round": self.state.round_number})
            self.state.current_slot_index += 1
            if self.state.current_slot_index >= len(self.state.initiative_order):
                self.state.current_slot_index = 0
                self.state.round_number += 1
                if self.state.round_number > self.state.maximum_rounds:
                    self._end_match(TerminalKind.DRAW_DURATION, None, "Maximum round limit reached.")
                    return
                self._append_event("ROUND_STARTED", SYSTEM_TURN, payload={"round": self.state.round_number})
            self.state.current_actor_id = self.state.initiative_order[self.state.current_slot_index]
            self._system_start_turn()

    # ------------------------------------------------------------------
    # Candidate generation and intent validation
    # ------------------------------------------------------------------
    def legal_candidates(self) -> tuple[LegalCandidate, ...]:
        if self.state.terminal_result is not None:
            return ()
        actor = self.state.actors[self.state.current_actor_id]
        if self.state.pending_resolution is not None:
            actor = self.state.actors[self.state.pending_resolution.actor_id]
            return self._pending_candidates(actor)
        if not actor.active:
            return (self._candidate(CandidateKind.END_TURN, actor, SYSTEM_TURN, "End inactive turn"),)
        candidates: list[LegalCandidate] = []
        candidates.extend(self._movement_candidates(actor))
        for source_id in actor.action_ids:
            action = self.action_catalog[source_id]
            candidates.extend(self._action_candidates(actor, action))
        for source_id in ("system:combat.dodge", "system:combat.dash", "system:combat.disengage"):
            candidates.extend(self._action_candidates(actor, self.action_catalog[source_id]))
        candidates.append(self._candidate(CandidateKind.HOLD_POSITION, actor, "system:combat.hold_position", "Hold position"))
        candidates.append(self._candidate(CandidateKind.END_TURN, actor, SYSTEM_TURN, "End turn"))
        return tuple(sorted(candidates, key=lambda c: c.candidate_id))

    def _pending_candidates(self, actor: ActorState) -> tuple[LegalCandidate, ...]:
        pending = self.state.pending_resolution
        assert pending is not None
        out = []
        for source_id in pending.follow_up_candidates:
            if source_id == "talent:lee_jia.spark_step":
                occupied_cells = self._occupied_cells_except(actor.entity_id)
                reachable = self.grid.reachable(
                    actor.position,
                    movement_ft=10,
                    occupied_cells=occupied_cells,
                    difficult_cells=self._hostile_difficult_cells(actor),
                    footprint=self._footprint(actor),
                )
                visible_hostiles = tuple(sorted(
                    a.entity_id
                    for a in self.state.actors.values()
                    if a.active
                    and a.team_id != actor.team_id
                    and self._line_of_sight_actor_to_actor(actor, a)
                ))
                for destination, (path, cost) in reachable.items():
                    out.append(self._candidate(
                        CandidateKind.OPTIONAL_RIDER, actor, source_id,
                        f"Spark Step to {destination.x},{destination.y}",
                        destination=destination, path=path, movement_cost_ft=cost,
                        option_ids=visible_hostiles,
                        metadata={"pending_transaction_id":pending.transaction_id,"nonprovoking_from_one_visible_creature":True},
                    ))
                continue
            option_ids: tuple[str, ...] = ()
            if source_id == "action:bai_meizhen.moon_disc_descent":
                option_ids = ("RADIANT", "FORCE", "BLUDGEONING")
            targets_by_follow_up = pending.context.get("targets_by_follow_up", {})
            offered_targets = tuple(targets_by_follow_up.get(source_id, pending.target_ids))
            for target_id in offered_targets:
                out.append(self._candidate(
                    CandidateKind.OPTIONAL_RIDER,
                    actor,
                    source_id,
                    f"Use optional rider {source_id} on {target_id}",
                    target_ids=(target_id,),
                    option_ids=option_ids,
                    metadata={"pending_transaction_id": pending.transaction_id},
                ))
        out.append(self._candidate(
            CandidateKind.TAKE_NO_OPTIONAL_ACTION,
            actor,
            "system:combat.take_no_optional_action",
            "Take no optional action",
            metadata={"pending_transaction_id": pending.transaction_id},
        ))
        return tuple(sorted(out, key=lambda c: c.candidate_id))

    def _movement_candidates(self, actor: ActorState) -> list[LegalCandidate]:
        if actor.movement_remaining_ft <= 0 or self._has_condition(actor, "condition:core.grappled"):
            return []
        occupied_cells = self._occupied_cells_except(actor.entity_id)
        difficult = self._hostile_difficult_cells(actor)
        reachable = self.grid.reachable(
            actor.position,
            movement_ft=actor.movement_remaining_ft,
            occupied_cells=occupied_cells,
            difficult_cells=difficult,
            footprint=self._footprint(actor),
        )
        out = []
        for destination, (path, cost) in reachable.items():
            out.append(self._candidate(
                CandidateKind.MOVE, actor, SYSTEM_MOVE, f"Move to {destination.x},{destination.y}",
                destination=destination,
                path=path,
                movement_cost_ft=cost,
                metadata={
                    "compressed_path": [p.model_dump(mode="json") for p in self.grid.compress_path(path)],
                    "reaction_exposure": self._movement_reaction_exposure(actor, path),
                    "hazard_exposure": self._path_intersects_cells(
                        actor, path[1:], self.grid.qi_hazard
                    ),
                },
            ))
        return out

    def _action_candidates(self, actor: ActorState, action: ActionDefinition) -> list[LegalCandidate]:
        if action.economy == EconomyKind.ACTION and not actor.action_available:
            return []
        if action.economy == EconomyKind.BONUS_ACTION and not actor.bonus_action_available:
            return []
        if not self._can_pay(actor, action.costs):
            return []
        req_condition = action.parameters.get("requires_condition")
        if req_condition and not self._has_condition(actor, req_condition):
            return []
        req_flag = action.parameters.get("requires_turn_flag")
        if req_flag and not actor.turn_flags.get(req_flag):
            return []
        if action.source_definition_id in {"action:an_eui.paired_bi_shou_assault", "action:an_eui.first_arm"} and self._has_condition(actor, "condition:an_eui.bi_shou_primary_unusable"):
            return []
        kind = CandidateKind.ACTION if action.economy == EconomyKind.ACTION else CandidateKind.BONUS_ACTION
        if action.source_definition_id == "action:lee_jia.gather_charge":
            return self._gather_charge_candidates(actor, action, kind)
        if action.source_definition_id == "action:bai_meizhen.command_cui":
            return self._command_cui_candidates(actor, action, kind)
        if action.target_kind == "SELF":
            options = tuple(action.parameters.get("options", ()))
            if action.source_definition_id == "action:an_eui.ruin_tempered_armament_quick":
                options = ("PRIMARY_WEAPON", "PAIRED_WEAPONS")
            return [self._candidate(kind, actor, action.source_definition_id, action.display_name, target_ids=(actor.entity_id,), option_ids=options)]
        if action.target_kind == "SELF_OR_CELL":
            options = ("SELF", "CELL")
            return [self._candidate(kind, actor, action.source_definition_id, action.display_name, target_ids=(actor.entity_id,), option_ids=options)]
        if action.target_kind == "VISIBLE_ACTIVE_PATTERN":
            patterns = [z.source_definition_id for z in self.state.zones.values() if z.active and z.owner_id != actor.entity_id]
            return [self._candidate(kind, actor, action.source_definition_id, action.display_name, option_ids=tuple(sorted(patterns)))] if patterns else []
        if action.target_kind == "CELL":
            out = []
            max_cells = (action.range_ft or 0) // self.grid.square_size_ft
            radius_cells = (action.radius_ft or 0) // self.grid.square_size_ft
            for y in range(self.grid.height):
                for x in range(self.grid.width):
                    pos = Position(x=x, y=y)
                    if (
                        self._distance_actor_to_cell(actor, pos) <= max_cells * self.grid.square_size_ft
                        and self._line_of_sight_actor_to_cell(actor, pos)
                    ):
                        area = None
                        if action.radius_ft is not None:
                            area = CandidateAreaProjection(
                                center=pos,
                                radius_cells=radius_cells,
                                affected_cells=self.grid.cells_in_radius(pos, radius_cells),
                            )
                        out.append(self._candidate(
                            kind, actor, action.source_definition_id,
                            f"{action.display_name} at {x},{y}",
                            destination=pos, area=area,
                        ))
            return out
        if action.target_kind in {"HOSTILE_ENTITY", "HOSTILE_ENTITY_OR_SELF"}:
            targets = [a for a in self.state.actors.values() if a.active and a.team_id != actor.team_id]
            if action.target_kind == "HOSTILE_ENTITY_OR_SELF":
                targets.append(actor)
        elif action.target_kind == "ALLY_OR_SELF":
            targets = [a for a in self.state.actors.values() if a.active and a.team_id == actor.team_id]
        else:
            targets = []
        out = []
        for target in targets:
            if not self._target_in_range(actor, target, action):
                continue
            if action.range_ft is not None and not self._line_of_sight_actor_to_actor(actor, target):
                continue
            options = tuple(action.parameters.get("modes", action.parameters.get("options", ())))
            if action.source_definition_id == "action:an_eui.scouring_destruction_blast":
                options = ("DEEPEN",) + tuple(action.parameters.get("break_guard_options", ()))
            if action.source_definition_id == "action:an_eui.first_arm":
                options = tuple(action.parameters.get("break_guard_options", ()))
            out.append(self._candidate(kind, actor, action.source_definition_id, action.display_name, target_ids=(target.entity_id,), option_ids=options))
        return out

    def _command_cui_candidates(
        self,
        actor: ActorState,
        action: ActionDefinition,
        kind: CandidateKind,
    ) -> list[LegalCandidate]:
        """Generate one exact legal candidate family per Cui command mode.

        The Gate 5 parent exposed STRIKE, DODGE, DASH, and HOLD over one shared
        HOSTILE_ENTITY_OR_SELF target domain.  That allowed a STRIKE option to
        inherit Bai Meizhen as its target.  Gate 5.1 binds each mode to its own
        legal target shape while preserving the accepted nested Cui activation.
        """
        cui = self.state.actors[CUI]
        if not cui.active:
            return []

        def command_visible(target: ActorState) -> bool:
            if not self._target_in_range(actor, target, action):
                return False
            return self._line_of_sight_actor_to_actor(actor, target)

        out: list[LegalCandidate] = []
        actors = sorted(self.state.actors.values(), key=lambda row: row.entity_id)

        # STRIKE is hostile-only.  The exact hostile target is bound into the
        # candidate and the single option remains visible in every interface.
        for target in actors:
            if not target.active or target.team_id == cui.team_id or target.entity_id == CUI:
                continue
            if not command_visible(target):
                continue
            out.append(self._candidate(
                kind,
                actor,
                action.source_definition_id,
                "Command Cui — Strike",
                target_ids=(target.entity_id,),
                option_ids=("STRIKE",),
                metadata={"command_mode":"STRIKE", "target_domain":"ACTIVE_HOSTILE"},
            ))

        # DODGE and HOLD are self-contained companion commands.  DODGE names
        # Cui explicitly; HOLD has no external target because the resolver
        # operates directly on Cui in both cases.
        out.append(self._candidate(
            kind,
            actor,
            action.source_definition_id,
            "Command Cui — Dodge",
            target_ids=(CUI,),
            option_ids=("DODGE",),
            metadata={"command_mode":"DODGE", "target_domain":"CUI_ONLY"},
        ))
        out.append(self._candidate(
            kind,
            actor,
            action.source_definition_id,
            "Command Cui — Hold",
            option_ids=("HOLD",),
            metadata={"command_mode":"HOLD", "target_domain":"CUI_ONLY"},
        ))

        # DASH preserves the accepted target-directed movement implementation.
        # Any active non-Cui actor may be the objective; no attack is resolved.
        # Binding the objective position also keeps hostile DASH candidates
        # identity-distinct from hostile STRIKE candidates without changing the
        # global candidate identity contract.
        for target in actors:
            if not target.active or target.entity_id == CUI:
                continue
            if not command_visible(target):
                continue
            out.append(self._candidate(
                kind,
                actor,
                action.source_definition_id,
                "Command Cui — Dash",
                target_ids=(target.entity_id,),
                destination=target.position,
                option_ids=("DASH",),
                metadata={"command_mode":"DASH", "target_domain":"ACTIVE_NON_CUI_OBJECTIVE"},
            ))
        return out

    def _candidate(
        self,
        kind: CandidateKind,
        actor: ActorState,
        source_definition_id: str,
        display_name: str,
        *,
        target_ids: Iterable[str] = (),
        destination: Position | None = None,
        path: tuple[Position, ...] = (),
        movement_cost_ft: int = 0,
        option_ids: Iterable[str] = (),
        area: CandidateAreaProjection | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LegalCandidate:
        decision_id = f"decision:{self.state.state_version}:{actor.entity_id}:{self.state.event_sequence}"
        identity = {
            "decision_id": decision_id,
            "kind": kind.value,
            "actor_id": actor.entity_id,
            "source_definition_id": source_definition_id,
            "target_ids": list(target_ids),
            "destination": destination.model_dump(mode="json") if destination else None,
            "state_version": self.state.state_version,
        }
        candidate_id = f"candidate:{canonical_sha256(identity)[:24]}"
        typed_options = tuple(option_ids)
        domains = choice_domains_for(source_definition_id, typed_options, kind=kind)
        status = choice_authority_status(typed_options, domains)
        return LegalCandidate(
            candidate_id=candidate_id,
            decision_id=decision_id,
            state_version=self.state.state_version,
            kind=kind,
            actor_id=actor.entity_id,
            source_definition_id=source_definition_id,
            display_name=display_name,
            target_ids=tuple(target_ids),
            destination=destination,
            canonical_path=path,
            movement_cost_ft=movement_cost_ft,
            option_ids=typed_options,
            choice_domains=domains,
            choice_authority_status=status,
            area=area,
            metadata=metadata or {},
        )

    def execute_intent(self, intent: ActionIntent) -> None:
        if self.state.terminal_result is not None:
            raise self._intent_error("GATE2_MATCH_TERMINAL", "The match is already terminal.", intent)
        candidates = {c.candidate_id: c for c in self.legal_candidates()}
        candidate = candidates.get(intent.candidate_id)
        if candidate is None:
            raise self._intent_error("GATE2_STALE_OR_ILLEGAL_CANDIDATE", "The candidate is not legal in the current state.", intent)
        if intent.state_version != self.state.state_version or intent.decision_id != candidate.decision_id:
            raise self._intent_error("GATE2_STALE_INTENT", "The action intent was generated from a stale state version or decision point.", intent)
        expected_actor_id = self.state.pending_resolution.actor_id if self.state.pending_resolution is not None else self.state.current_actor_id
        if intent.actor_id != expected_actor_id or intent.actor_id != candidate.actor_id:
            raise self._intent_error("GATE2_WRONG_ACTOR", "The intent actor is not the current decision owner.", intent)
        if tuple(intent.target_ids) != candidate.target_ids:
            raise self._intent_error("GATE2_TARGET_MISMATCH", "The intent targets do not match the selected legal candidate.", intent)
        if intent.destination != candidate.destination:
            raise self._intent_error("GATE2_DESTINATION_MISMATCH", "The intent destination does not match the selected legal candidate.", intent)
        option_findings = validate_option_selection(candidate, intent.option_ids)
        if option_findings:
            raise self._intent_error(
                "GATE2_INVALID_OPTION",
                f"The intent option composition is not legal for the selected candidate: {', '.join(option_findings)}.",
                intent,
            )
        if (
            candidate.source_definition_id == "action:bai_meizhen.command_cui"
            and tuple(intent.option_ids) != candidate.option_ids
        ):
            raise self._intent_error(
                "GATE5_CUI_COMMAND_MODE_MISMATCH",
                "The Cui command intent must select the one exact mode bound to its legal candidate.",
                intent,
            )
        actor = self.state.actors[intent.actor_id]
        self._active_intent = intent
        try:
            with self._transaction(candidate.source_definition_id, intent.intent_id, actor.entity_id):
                self._append_event("INTENT_ACCEPTED", candidate.source_definition_id, actor_id=actor.entity_id, target_ids=candidate.target_ids, payload={
                    "candidate_id": candidate.candidate_id,
                    "kind": candidate.kind.value,
                    "option_ids": list(intent.option_ids),
                })
                if candidate.kind == CandidateKind.MOVE:
                    self._resolve_movement(actor, candidate, intent)
                elif candidate.kind in {CandidateKind.ACTION, CandidateKind.BONUS_ACTION}:
                    self._resolve_action(actor, self.action_catalog[candidate.source_definition_id], candidate, intent)
                elif candidate.kind == CandidateKind.OPTIONAL_RIDER:
                    self._resolve_optional_rider(actor, candidate, intent)
                elif candidate.kind == CandidateKind.TAKE_NO_OPTIONAL_ACTION:
                    self._append_event("OPTIONAL_ACTION_DECLINED", candidate.source_definition_id, actor_id=actor.entity_id)
                    self.state.pending_resolution = None
                elif candidate.kind == CandidateKind.HOLD_POSITION:
                    self._append_event("HOLD_POSITION_COMMITTED", candidate.source_definition_id, actor_id=actor.entity_id)
                elif candidate.kind == CandidateKind.END_TURN:
                    pass
                else:
                    raise self._intent_error("GATE2_UNSUPPORTED_CANDIDATE_KIND", "Unsupported candidate kind.", intent)
        finally:
            self._active_intent = None
        if candidate.kind == CandidateKind.END_TURN:
            self.end_turn(intent.intent_id)

    # ------------------------------------------------------------------
    # Movement and opportunity/hazard handling
    # ------------------------------------------------------------------
    def _resolve_movement(self, actor: ActorState, candidate: LegalCandidate, intent: ActionIntent) -> None:
        if candidate.movement_cost_ft > actor.movement_remaining_ft:
            raise self._intent_error("GATE2_MOVEMENT_BUDGET_EXCEEDED", "Movement exceeds the remaining movement budget.", intent)
        path = candidate.canonical_path
        if not path or path[0] != actor.position or path[-1] != candidate.destination:
            raise self._intent_error("GATE2_MOVEMENT_PATH_INVALID", "The movement candidate path is invalid.", intent)
        previous = actor.position
        traversed = [path[0]]
        spent_ft = 0
        difficult = self._hostile_difficult_cells(actor)
        occupied_cells = self._occupied_cells_except(actor.entity_id)
        for nxt in path[1:]:
            if not self.grid.step_legal(
                previous,
                nxt,
                occupied_cells=occupied_cells,
                footprint=self._footprint(actor),
            ):
                raise self._intent_error(
                    "GATE2_MOVEMENT_FOOTPRINT_COLLISION",
                    "The movement path no longer admits the actor's complete footprint.",
                    intent,
                )
            step_multiplier = self.grid.movement_step_multiplier(
                previous,
                nxt,
                footprint=self._footprint(actor),
                difficult_cells=difficult,
            )
            step_cost = self.grid.square_size_ft * step_multiplier
            if step_cost > actor.movement_remaining_ft:
                raise self._intent_error("GATE2_MOVEMENT_BUDGET_CHANGED", "The movement budget changed before the next path step.", intent)
            self._resolve_leave_reach(actor, previous, nxt, intent)
            if not actor.active or self.state.terminal_result is not None:
                break
            actor.movement_remaining_ft -= step_cost
            spent_ft += step_cost
            actor.position = nxt
            traversed.append(nxt)
            previous = nxt
            self._resolve_qi_hazard(actor)
            self._resolve_zone_entry_triggers(actor)
            self._remove_zone_leave_conditions(actor)
            if not actor.active or self.state.terminal_result is not None:
                break
        self._append_event("MOVEMENT_COMMITTED", SYSTEM_MOVE, actor_id=actor.entity_id, payload={
            "destination": actor.position.model_dump(mode="json"),
            "path": [p.model_dump(mode="json") for p in traversed],
            "cost_ft": spent_ft,
            "planned_cost_ft": candidate.movement_cost_ft,
            "interrupted": tuple(traversed) != tuple(path),
        })

    def _resolve_leave_reach(self, mover: ActorState, previous: Position, nxt: Position, intent: ActionIntent) -> None:
        if mover.turn_flags.get("disengaged"):
            return
        eligible = []
        for hostile in self.state.actors.values():
            if not hostile.active or hostile.team_id == mover.team_id or not hostile.reaction_available:
                continue
            params = self.reaction_parameters.get("reaction:core.opportunity_attack", {}) if hostile.entity_id in self.runtime_actor_ids else BASIC_MELEE.get(hostile.entity_id, {})
            reach = params.get("reach_ft", 5)
            if (
                self._distance_actor_to_actor(
                    mover, hostile, actor_position=previous
                ) <= reach
                and self._distance_actor_to_actor(
                    mover, hostile, actor_position=nxt
                ) > reach
            ):
                eligible.append(hostile)
        for reactor in sorted(eligible, key=self._initiative_rank):
            if mover.turn_flags.get("spark_step_ignore_oa_from") == reactor.entity_id:
                continue
            decision = self._reaction_decision(intent, "LEAVE_REACH", reactor.entity_id, SYSTEM_OPPORTUNITY)
            self._append_event("REACTION_WINDOW_OPENED", SYSTEM_OPPORTUNITY, actor_id=mover.entity_id, target_ids=(reactor.entity_id,), payload={"checkpoint":"LEAVE_REACH"})
            if decision is None or decision.selection == "DECLINE":
                self._append_event("REACTION_DECLINED", SYSTEM_OPPORTUNITY, actor_id=reactor.entity_id, target_ids=(mover.entity_id,))
                continue
            reactor.reaction_available = False
            if reactor.entity_id in self.runtime_actor_ids:
                params = self.reaction_parameters.get("reaction:core.opportunity_attack", {})
                from .character_runtime_adapter import CharacterCombatRuntimeEngine
                runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
                runtime.__dict__.update(self.__dict__)
                CharacterCombatRuntimeEngine._resolve_character_attack(
                    runtime, reactor, mover, source_id=SYSTEM_OPPORTUNITY,
                    attack_bonus=int(params.get("attack_bonus", 2)), damage=None,
                    damage_type=str(params.get("damage_type", "BLUDGEONING")), intent=intent,
                    fixed_damage=int(params.get("fixed_damage", 2)), ranged=False,
                )
                self.__dict__.update(runtime.__dict__)
            else:
                spec = BASIC_MELEE[reactor.entity_id]
                self._resolve_attack_spec(reactor, mover, spec, intent, reaction_depth=1, source_definition_id=SYSTEM_OPPORTUNITY)
            self._append_event("REACTION_RESOLVED", SYSTEM_OPPORTUNITY, actor_id=reactor.entity_id, target_ids=(mover.entity_id,))
            if not mover.active:
                break

    def _resolve_qi_hazard(self, actor: ActorState) -> None:
        if not self._footprint_intersects(actor, self.grid.qi_hazard):
            return
        key = f"qi_hazard_round:{self.state.round_number}:turn:{self.state.current_actor_id}"
        if actor.turn_flags.get(key):
            return
        actor.turn_flags[key] = True
        roll = self.roller.d20(modifier=actor.saving_throws.get("DEX", 0), actor_id=actor.entity_id, reason="QI_HAZARD_DEX_SAVE")
        self._record_roll(roll)
        self._append_event("SAVE_ROLLED", SYSTEM_HAZARD, actor_id=actor.entity_id, payload=roll.model_dump(mode="json"))
        if roll.total < 12:
            dmg = self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":4,"modifier":0}), actor_id=actor.entity_id, reason="QI_HAZARD_DAMAGE")
            self._record_roll(dmg)
            self._append_event("DAMAGE_ROLLED", SYSTEM_HAZARD, actor_id=actor.entity_id, payload=dmg.model_dump(mode="json"))
            self._commit_damage(actor, dmg.total, "QI_DISRUPTION", SYSTEM_HAZARD, actor.entity_id, None, reaction_depth=0)

    # ------------------------------------------------------------------
    # Action resolution
    # ------------------------------------------------------------------
    def _resolve_action(self, actor: ActorState, action: ActionDefinition, candidate: LegalCandidate, intent: ActionIntent) -> None:
        self._consume_economy(actor, action)
        self._spend_costs(actor, action.costs, action.source_definition_id)
        target = self.state.actors[candidate.target_ids[0]] if candidate.target_ids else None
        if actor.entity_id in self.runtime_actor_ids and action.resolution_kind.startswith("C3AR_"):
            from .character_runtime_adapter import CharacterCombatRuntimeEngine, RuntimeActionRequest
            runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
            runtime.__dict__.update(self.__dict__)
            request = RuntimeActionRequest(
                request_id=intent.intent_id,
                actor_id=actor.entity_id,
                action_id=action.source_definition_id,
                target_id=candidate.target_ids[0] if candidate.target_ids else None,
                destination=candidate.destination,
                option_ids=intent.option_ids,
                object_ids=getattr(intent, "object_ids", ()),
                condition_instance_id=getattr(intent, "condition_instance_id", None),
                penalty_id=getattr(intent, "penalty_id", None),
                source_effect_dc=getattr(intent, "source_effect_dc", None),
                reaction_decisions=intent.reaction_decisions,
            )
            runtime._dispatch_action(action, actor, target, request, intent)
            self.__dict__.update(runtime.__dict__)
            return
        if action.source_definition_id == "action:an_eui.scouring_destruction_blast" and "DEEPEN" in intent.option_ids:
            self._spend_resource(actor, "resource:an_eui.stamina", 1, action.source_definition_id)
            action = action.model_copy(update={"damage": action.damage.model_copy(update={"count": 3})})
        target = target or actor
        kind = action.resolution_kind
        if kind == "ATTACK":
            self._resolve_attack_action(actor, target, action, intent)
        elif kind == "MULTI_ATTACK":
            for index in range(action.attack_count):
                if target.active and self.state.terminal_result is None:
                    self._resolve_attack_action(actor, target, action, intent, attack_index=index + 1)
            if action.parameters.get("qualifies_paired_strike"):
                actor.turn_flags["paired_strike_enabled"] = True
        elif kind == "ATTACK_THEN_SAVE":
            self._resolve_attack_then_save(actor, target, action, intent)
        elif kind == "SAVE_DAMAGE":
            self._resolve_save_damage(actor, target, action, intent)
        elif kind == "STATE":
            self._resolve_state_action(actor, action, intent)
        elif kind == "FIRST_ARM":
            self._resolve_first_arm(actor, target, action, intent)
        elif kind == "STOMPING_STEP":
            self._resolve_stomping_step(actor, action, intent)
        elif kind == "GATHER_CHARGE":
            self._resolve_gather_charge(actor, action, intent)
        elif kind == "LIGHTNING_LASH":
            self._resolve_lightning_lash(actor, target, action, intent)
        elif kind == "COUNTERCURRENT":
            self._resolve_countercurrent(actor, action, intent)
        elif kind == "NOCTURNE_ZONE":
            self._resolve_zone_action(actor, action, candidate.destination, intent, zone_kind="NOCTURNE")
        elif kind == "BLACKWATER_ZONE":
            self._resolve_zone_action(actor, action, candidate.destination, intent, zone_kind="BLACKWATER")
        elif kind == "KEEP_MEASURE":
            self._resolve_keep_measure(actor, target, action)
        elif kind == "COMMAND_CUI":
            self._resolve_command_cui(actor, target, action, intent)
        elif kind == "SEA_RISEN_BEARING":
            self._resolve_sea_risen_bearing(actor, action)
        elif kind == "WATER_LASH":
            moon_sea_available_before = actor.resources.get("resource:bai_meizhen.moon_sea_radiance", 0) >= 1
            hit = self._resolve_attack_action(actor, target, action, intent)
            if self.state.terminal_result is not None:
                return
            if hit and target.active:
                self._apply_condition(target, "condition:bai_meizhen.soaked", action.source_definition_id, actor.entity_id, expires_on="END_OF_BAI_NEXT_TURN")
                follow_ups = ["action:bai_meizhen.water_whip"]
                if moon_sea_available_before:
                    follow_ups.append("action:bai_meizhen.moon_disc_descent")
                self._open_follow_up_window(actor, target, action.source_definition_id, intent, follow_ups)
                self._maybe_gain_moon_sea(actor, "VISIBLE_MANIFESTATION_HIT", action.source_definition_id)
        elif kind == "CUI_STRIKE":
            self._resolve_cui_strike(actor, target, action, intent)
        elif kind == "DODGE":
            self._apply_condition(actor, "condition:core.dodge", action.source_definition_id, actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
        elif kind == "DASH":
            actor.movement_remaining_ft += self._effective_speed(actor)
            actor.turn_flags["dash_used"] = True
        elif kind == "DISENGAGE":
            actor.turn_flags["disengaged"] = True
        else:
            raise self._intent_error("GATE2_UNSUPPORTED_RESOLUTION_KIND", f"Unsupported resolution kind {kind}.", intent)

    def _resolve_attack_action(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent, attack_index: int = 1) -> bool:
        spec = {
            "source_definition_id": action.source_definition_id,
            "attack_bonus": action.attack_bonus,
            "damage": action.damage,
            "damage_type": action.damage_type,
            "range_ft": action.range_ft,
            "reach_ft": action.reach_ft,
            "parameters": action.parameters,
        }
        return self._resolve_attack_spec(actor, target, spec, intent, source_definition_id=action.source_definition_id, attack_index=attack_index)

    def _resolve_attack_spec(
        self,
        actor: ActorState,
        target: ActorState,
        spec: dict[str, Any],
        intent: ActionIntent,
        *,
        reaction_depth: int = 0,
        source_definition_id: str,
        attack_index: int = 1,
    ) -> bool:
        mirror_trace_available_before = actor.entity_id == LING and actor.resources.get("resource:ling_qi.mirror_trace", 0) >= 1
        moon_sea_available_before = actor.entity_id == BAI and actor.resources.get("resource:bai_meizhen.moon_sea_radiance", 0) >= 1
        ancestral_available_before = actor.entity_id == BAI and actor.resources.get("resource:bai_meizhen.ancestral_resonance", 0) >= 1 and not actor.turn_flags.get("bloodline_strike_used_this_turn")
        mode = self._attack_mode(actor, target)
        if mode == "ADVANTAGE":
            for mid, modifier in list(target.modifiers.items()):
                if modifier.target_field == "incoming_attack_mode" and modifier.value == "ADVANTAGE":
                    del target.modifiers[mid]
                    self._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"modifier_id":mid,"reason":"CONSUMED"})
                    break
        if target.entity_id == CUI and self._eligible_spirit_intercession(target):
            dec = self._reaction_decision(intent, "ALLY_OR_COMPANION_ATTACKED", BAI, "reaction:bai_meizhen.spirit_intercession")
            self._append_event("REACTION_WINDOW_OPENED", "reaction:bai_meizhen.spirit_intercession", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"checkpoint":"ALLY_OR_COMPANION_ATTACKED"})
            if dec and dec.selection == "USE":
                mode = "DISADVANTAGE"
                self.state.actors[BAI].reaction_available = False
                self._append_event("REACTION_RESOLVED", "reaction:bai_meizhen.spirit_intercession", actor_id=BAI, target_ids=(target.entity_id,), payload={"attack_mode":"DISADVANTAGE"})
                self._maybe_gain_moon_sea(self.state.actors[BAI], "PROTECTION_EVENT", "reaction:bai_meizhen.spirit_intercession")
            else:
                self._append_event("REACTION_DECLINED", "reaction:bai_meizhen.spirit_intercession", actor_id=BAI, target_ids=(target.entity_id,))
        attack_bonus = int(spec.get("attack_bonus") or 0)
        attack_roll = self.roller.d20(modifier=attack_bonus, actor_id=actor.entity_id, reason=f"ATTACK:{source_definition_id}:{attack_index}", mode=mode)
        self._record_roll(attack_roll)
        attack_penalty = self._consume_attack_modifiers(actor)
        total = attack_roll.total + attack_penalty
        cover = 0
        if spec.get("range_ft") is not None:
            cover = self._cover_bonus_actor_to_actor(actor, target)
            if self._has_condition(target, "condition:an_eui.break_guard.no_half_cover"):
                cover = 0
        effective_ac = target.armor_class + cover + self._ac_modifier(target)
        natural = attack_roll.natural_result or 0
        provisional_hit = natural != 1 and (natural == 20 or total >= effective_ac)
        self._append_event("ATTACK_ROLLED", source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={
            **attack_roll.model_dump(mode="json"),
            "modified_total": total,
            "target_ac": effective_ac,
            "cover_bonus": cover,
            "provisional_hit": provisional_hit,
        })
        if provisional_hit and target.entity_id == LING and spec.get("range_ft") is not None:
            dec = self._reaction_decision(intent, "ATTACK_HIT_BEFORE_DAMAGE", LING, "reaction:ling_qi.qi_armor")
            self._append_event("REACTION_WINDOW_OPENED", "reaction:ling_qi.qi_armor", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"checkpoint":"ATTACK_HIT_BEFORE_DAMAGE"})
            if dec and dec.selection == "USE" and self._reaction_usable(LING, "reaction:ling_qi.qi_armor"):
                self._spend_resource(self.state.actors[LING], "resource:ling_qi.qi", 2, "reaction:ling_qi.qi_armor")
                self.state.actors[LING].reaction_available = False
                effective_ac += 3
                provisional_hit = natural == 20 or total >= effective_ac
                self._append_event("REACTION_RESOLVED", "reaction:ling_qi.qi_armor", actor_id=LING, target_ids=(target.entity_id,), payload={"ac_bonus":3,"new_ac":effective_ac,"hit_after_recheck":provisional_hit})
            else:
                self._append_event("REACTION_DECLINED", "reaction:ling_qi.qi_armor", actor_id=LING, target_ids=(target.entity_id,))
        if not provisional_hit:
            if target.entity_id == LING and actor.team_id != target.team_id:
                self._maybe_gain_mirror_trace("HOSTILE_ATTACK_MISS", source_definition_id)
            if target.entity_id in {BAI, CUI} and actor.team_id != target.team_id:
                self._maybe_gain_moon_sea(self.state.actors[BAI], "FAILED_HOSTILE_CONTEST", source_definition_id)
            return False
        if target.entity_id == CUI:
            intercession = self._reaction_decision(intent, "ALLY_OR_COMPANION_ATTACKED", BAI, "reaction:bai_meizhen.spirit_intercession")
            if intercession and intercession.selection == "USE":
                bai = self.state.actors[BAI]
                if "SPEND_QI" in intercession.option_ids and bai.resources.get("resource:bai_meizhen.qi", 0) >= 1:
                    self._spend_resource(bai, "resource:bai_meizhen.qi", 1, "reaction:bai_meizhen.spirit_intercession")
                else:
                    self._gain_resource(bai, "resource:bai_meizhen.cui_bond_strain", 1, "reaction:bai_meizhen.spirit_intercession")
        critical = natural == 20
        damage_spec = spec.get("damage")
        if damage_spec is None:
            return True
        fixed = spec.get("fixed_damage")
        damage_roll = self.roller.roll(damage_spec, actor_id=actor.entity_id, reason=f"DAMAGE:{source_definition_id}:{attack_index}", critical=critical, fixed_damage=fixed)
        self._record_roll(damage_roll)
        damage_total = damage_roll.total
        if critical and actor.entity_id == AN and self._has_condition(actor, "condition:an_eui.ruin_tempered"):
            extra = self.roller.roll(damage_spec.model_copy(update={"count":2,"sides":6,"modifier":0}), actor_id=actor.entity_id, reason="RUIN_TEMPERED_CRITICAL")
            self._record_roll(extra)
            damage_total += extra.total
        self._append_event("DAMAGE_ROLLED", source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={
            **damage_roll.model_dump(mode="json"), "critical":critical, "combined_total":damage_total,
        })
        weapon_charge = next((c for c in actor.conditions.values() if c.condition_id == "condition:lee_jia.lightning_charge.held_weapon"), None)
        if weapon_charge is not None:
            damage_total += actor.proficiency_bonus
            self._append_event("DAMAGE_ROLLED", "resource:lee_jia.lightning_charge", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"fixed_lightning_damage":actor.proficiency_bonus,"discharge":"HELD_WEAPON_NEXT_HIT"})
            self._remove_lightning_charge_condition(actor, weapon_charge.instance_id, "WEAPON_HIT_DISCHARGE")
        damage_type = spec.get("damage_type") or "UNTYPED"
        hp_damage = self._commit_damage(target, damage_total, damage_type, source_definition_id, actor.entity_id, intent, reaction_depth=reaction_depth)
        if self.state.terminal_result is not None:
            return True
        if hp_damage > 0 and spec.get("parameters", {}).get("severance_generation"):
            self._maybe_gain_severance(actor)
        if target.active:
            if mirror_trace_available_before:
                self._open_follow_up_window(actor, target, source_definition_id, intent, ["action:ling_qi.reflection_cut"])
            if actor.entity_id == BAI and source_definition_id != "action:bai_meizhen.water_lash":
                follow_ups: list[str] = []
                if moon_sea_available_before:
                    follow_ups.append("action:bai_meizhen.moon_disc_descent")
                if ancestral_available_before and source_definition_id in {"action:bai_meizhen.numbing_venom_palm", "action:bai_meizhen.blackwater_serpent_court"}:
                    follow_ups.append("action:bai_meizhen.bloodline_strike")
                self._open_follow_up_window(actor, target, source_definition_id, intent, follow_ups)
        if actor.entity_id == BAI and hp_damage > 0:
            self._maybe_gain_moon_sea(actor, "VISIBLE_MANIFESTATION_HIT", source_definition_id)
        return True

    def _resolve_attack_then_save(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        hit = self._resolve_attack_action(actor, target, action, intent)
        if self.state.terminal_result is not None or not hit or not target.active or action.save is None:
            return
        save = self._roll_save(target, action.save.ability, action.save.dc, action.source_definition_id)
        failed = save.total < action.save.dc
        if action.source_definition_id == "action:an_eui.scouring_destruction_blast" and failed:
            self._apply_condition(target, "condition:core.reaction_denied", action.source_definition_id, actor.entity_id, expires_on="START_OF_TARGET_NEXT_TURN")
            option = intent.option_ids[0] if intent.option_ids else "AC_MINUS_1"
            if option == "AC_MINUS_1":
                self._add_modifier(target, action.source_definition_id, "armor_class", "ADD", -1, "ALL_ATTACKS", expires_on="START_OF_TARGET_NEXT_TURN")
            elif option == "NEXT_ATTACK_ADVANTAGE":
                self._add_modifier(target, action.source_definition_id, "incoming_attack_mode", "ADVANTAGE", 1, "NEXT_ATTACK", expires_on="CONSUMED")
            elif option == "NO_HALF_COVER":
                self._apply_condition(target, "condition:an_eui.break_guard.no_half_cover", action.source_definition_id, actor.entity_id, expires_on="START_OF_TARGET_NEXT_TURN")
        elif action.source_definition_id == "action:bai_meizhen.numbing_venom_palm":
            if failed:
                self._apply_dose(target, action.source_definition_id, actor.entity_id)
                self._apply_condition(target, "condition:core.reaction_denied", action.source_definition_id, actor.entity_id, expires_on="START_OF_BAI_NEXT_TURN")
                self._add_modifier(target, action.source_definition_id, "speed_ft", "ADD", -10, "ALL_MOVEMENT", expires_on="START_OF_BAI_NEXT_TURN")
            else:
                self._add_modifier(target, action.source_definition_id, "speed_ft", "ADD", -5, "ALL_MOVEMENT", expires_on="START_OF_BAI_NEXT_TURN")

    def _resolve_save_damage(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        assert action.save and action.damage
        save = self._roll_save(target, action.save.ability, action.save.dc, action.source_definition_id)
        damage_roll = self.roller.roll(action.damage, actor_id=actor.entity_id, reason=f"DAMAGE:{action.source_definition_id}")
        self._record_roll(damage_roll)
        self._append_event("DAMAGE_ROLLED", action.source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload=damage_roll.model_dump(mode="json"))
        failed = save.total < action.save.dc
        amount = damage_roll.total if failed else damage_roll.total // 2
        self._commit_damage(target, amount, action.damage_type or "UNTYPED", action.source_definition_id, actor.entity_id, intent, reaction_depth=0)
        if self.state.terminal_result is not None:
            return
        if failed and action.parameters.get("fail_modifier") == "NEXT_ATTACK_DISADVANTAGE":
            self._add_modifier(target, action.source_definition_id, "attack_mode", "DISADVANTAGE", 1, "NEXT_ATTACK", expires_on="END_OF_TARGET_NEXT_TURN_OR_CONSUMED")
        if failed and action.parameters.get("fail_modifier") == "NEXT_ATTACK_SUBTRACT_1D4":
            self._add_modifier(target, action.source_definition_id, "attack_roll", "SUBTRACT_DIE", "1d4", "NEXT_ATTACK", expires_on="START_OF_LING_NEXT_TURN_OR_CONSUMED")

    def _resolve_state_action(self, actor: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        if action.concentration:
            self._start_concentration(actor, action.source_definition_id)
        if action.source_definition_id == "action:an_eui.ruin_tempered_armament_quick":
            if "PAIRED_WEAPONS" in intent.option_ids:
                self._spend_resource(actor, "resource:an_eui.stamina", 1, action.source_definition_id)
            self._apply_condition(actor, "condition:an_eui.ruin_tempered", action.source_definition_id, actor.entity_id, expires_on="CONCENTRATION_END")

    def _resolve_first_arm(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        hit = self._resolve_attack_action(actor, target, action, intent)
        if not hit:
            miss_damage = self.roller.roll(action.damage.model_copy(update={"count":1,"sides":6,"modifier":0}), actor_id=actor.entity_id, reason="FIRST_ARM_MISS_SELF_DAMAGE")
            self._record_roll(miss_damage)
            self._append_event("DAMAGE_ROLLED", action.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,), payload={**miss_damage.model_dump(mode="json"),"unavoidable":True,"reason":"ON_MISS"})
            self._commit_damage(actor, miss_damage.total, "UNAVOIDABLE", action.source_definition_id, actor.entity_id, None, reaction_depth=0)
        else:
            extra = self.roller.roll(action.damage.model_copy(update={"count":3,"sides":6,"modifier":0}), actor_id=actor.entity_id, reason="FIRST_ARM_EXTRA_DAMAGE")
            self._record_roll(extra)
            self._append_event("DAMAGE_ROLLED", action.source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload=extra.model_dump(mode="json"))
            self._commit_damage(target, extra.total, "SLASHING_DESTRUCTION", action.source_definition_id, actor.entity_id, intent, reaction_depth=0)
            if target.active:
                save = self._roll_save(target, "DEX", 14, action.source_definition_id)
                if save.total < 14:
                    self._apply_condition(target, "condition:core.reaction_denied", action.source_definition_id, actor.entity_id, expires_on="START_OF_TARGET_NEXT_TURN")
                    option = intent.option_ids[0] if intent.option_ids else "AC_MINUS_1"
                    if option == "AC_MINUS_1":
                        self._add_modifier(target, action.source_definition_id, "armor_class", "ADD", -1, "ALL_ATTACKS", expires_on="START_OF_TARGET_NEXT_TURN")
                    elif option == "NEXT_ATTACK_ADVANTAGE":
                        self._add_modifier(target, action.source_definition_id, "incoming_attack_mode", "ADVANTAGE", 1, "NEXT_ATTACK", expires_on="CONSUMED")
                    elif option == "NO_HALF_COVER":
                        self._apply_condition(target, "condition:an_eui.break_guard.no_half_cover", action.source_definition_id, actor.entity_id, expires_on="START_OF_TARGET_NEXT_TURN")
        self_save = self._roll_save(actor, "CON", 14, action.source_definition_id)
        if self_save.total < 14 and actor.active:
            backlash = self.roller.roll(action.damage.model_copy(update={"count":1,"sides":6,"modifier":0}), actor_id=actor.entity_id, reason="FIRST_ARM_SELF_CON_FAILURE")
            self._record_roll(backlash)
            self._append_event("DAMAGE_ROLLED", action.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,), payload={**backlash.model_dump(mode="json"),"unavoidable":True,"reason":"SELF_CON_FAILURE"})
            self._commit_damage(actor, backlash.total, "UNAVOIDABLE", action.source_definition_id, actor.entity_id, None, reaction_depth=0)
        integrity = self.roller.d20(modifier=actor.saving_throws.get("CON",0), actor_id=actor.entity_id, reason="FIRST_ARM_WEAPON_INTEGRITY_CON")
        self._record_roll(integrity)
        self._append_event("SAVE_ROLLED", action.source_definition_id, actor_id=actor.entity_id, target_ids=("weapon:an_eui.bi_shou_primary",), payload={**integrity.model_dump(mode="json"),"dc":14,"success":integrity.total>=14,"integrity_check":True})
        if integrity.total < 14:
            self._apply_condition(actor, "condition:an_eui.bi_shou_primary_unusable", action.source_definition_id, actor.entity_id, expires_on="UNTIL_REPAIRED")
        self._remove_condition(actor, "condition:an_eui.ruin_tempered", action.source_definition_id)
        self._end_concentration(actor, "FIRST_ARM_CONSUMED")

    def _resolve_stomping_step(self, actor: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        option = intent.option_ids[0] if intent.option_ids else "DASH"
        if option == "DASH":
            actor.movement_remaining_ft += self._effective_speed(actor)
            actor.turn_flags["stomping_step_dash"] = True
        elif option == "DISENGAGE":
            actor.turn_flags["disengaged"] = True
        else:
            raise self._intent_error("GATE2_INVALID_STOMPING_OPTION", "Stomping Step requires DASH or DISENGAGE.", intent)

    def _resolve_gather_charge(self, actor: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        if actor.resources["resource:lee_jia.lightning_charge"] >= 3:
            self._end_oldest_lightning_charge(actor)
        if intent.destination is not None:
            self._create_space_lightning_charge(actor, intent.destination, action.source_definition_id)
        elif intent.target_ids:
            target = self.state.actors[intent.target_ids[0]]
            kind = "SELF" if target.entity_id == actor.entity_id else "WILLING_CREATURE"
            self._create_actor_lightning_charge(actor, target, kind, action.source_definition_id)
        elif "HELD_WEAPON" in intent.option_ids:
            self._create_actor_lightning_charge(actor, actor, "HELD_WEAPON", action.source_definition_id)
        else:
            self._create_actor_lightning_charge(actor, actor, "SELF", action.source_definition_id)
        if actor.entity_id in intent.target_ids or "SELF" in intent.option_ids:
            self.state.pending_resolution = PendingResolution(
                transaction_id=self._transaction_id or "",
                source_definition_id=action.source_definition_id,
                intent_id=intent.intent_id,
                actor_id=actor.entity_id,
                target_ids=(actor.entity_id,),
                stage="SPARK_STEP_OPTION",
                follow_up_candidates=["talent:lee_jia.spark_step"],
                context={"maximum_movement_ft":10},
            )

    def _resolve_lightning_lash(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        mode = intent.option_ids[0] if intent.option_ids else "CHARGE"
        hit = self._resolve_attack_action(actor, target, action, intent)
        if not hit:
            return
        if mode == "CHARGE":
            self._gain_resource(actor, "resource:lee_jia.lightning_charge", 1, action.source_definition_id)
        elif mode == "JOLT":
            self._apply_condition(target, "condition:lee_jia.jolted", action.source_definition_id, actor.entity_id, expires_on="START_OF_LEE_NEXT_TURN")
        elif mode == "FLASH":
            self._apply_condition(target, "condition:lee_jia.flash_exposed", action.source_definition_id, actor.entity_id, expires_on="START_OF_LEE_NEXT_TURN")
        elif mode == "ARC":
            adjacent = [
                a
                for a in self.state.actors.values()
                if a.active
                and a.team_id == target.team_id
                and a.entity_id != target.entity_id
                and self._distance_actor_to_actor(a, target) <= 5
            ]
            if adjacent:
                secondary = sorted(adjacent, key=lambda a: a.entity_id)[0]
                self._commit_damage(secondary, int(action.parameters["arc_damage"]), "LIGHTNING", action.source_definition_id, actor.entity_id, intent, reaction_depth=0)
        else:
            raise self._intent_error("GATE2_INVALID_LIGHTNING_LASH_MODE", "Lightning Lash mode is invalid.", intent)
        actor.movement_remaining_ft += int(action.parameters.get("spark_step_ft", 0))

    def _resolve_countercurrent(self, actor: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        pattern = intent.option_ids[0] if intent.option_ids else None
        if not pattern:
            raise self._intent_error("GATE2_PATTERN_REQUIRED", "Countercurrent requires one visible active pattern.", intent)
        self._apply_condition(actor, "condition:lee_jia.countercurrent_read", action.source_definition_id, actor.entity_id, expires_on="END_OF_LEE_NEXT_TURN", data={"pattern":pattern})

    def _resolve_zone_action(self, actor: ActorState, action: ActionDefinition, center: Position | None, intent: ActionIntent, *, zone_kind: str) -> None:
        if center is None:
            raise self._intent_error("GATE2_ZONE_CENTER_REQUIRED", "A zone action requires a legal center cell.", intent)
        self._start_concentration(actor, action.source_definition_id)
        zone_id = f"zone:{action.source_definition_id}:{self.state.event_sequence + 1}"
        cells = self.grid.cells_in_radius(center, (action.radius_ft or 0) // self.grid.square_size_ft)
        zone = ZoneState(
            zone_id=zone_id,
            source_definition_id=action.source_definition_id,
            owner_id=actor.entity_id,
            center=center,
            radius_cells=(action.radius_ft or 0)//self.grid.square_size_ft,
            affected_cells=cells,
            concentration_link=True,
            duration_rounds=10,
            created_round=self.state.round_number,
            trigger_profile={"kind":zone_kind},
        )
        self.state.zones[zone_id] = zone
        actor.concentration = ConcentrationState(source_definition_id=action.source_definition_id, zone_id=zone_id, started_sequence=self.state.event_sequence + 1)
        self._append_event("ZONE_CREATED", action.source_definition_id, actor_id=actor.entity_id, payload={"zone":zone.model_dump(mode="json")})
        for target in sorted(self.state.actors.values(), key=lambda a:a.entity_id):
            if target.active and target.team_id != actor.team_id and self._in_zone(target, zone):
                self._resolve_zone_effect(zone, target, checkpoint="ON_APPEAR")

    def _resolve_keep_measure(self, actor: ActorState, target: ActorState, action: ActionDefinition) -> None:
        self._apply_condition(target, "condition:ling_qi.keep_the_measure", action.source_definition_id, actor.entity_id, expires_on="START_OF_LING_AFTER_10_TURNS")
        if not self._has_condition(target, "condition:ling_qi.keep_measure_temp_hp_consumed"):
            self._grant_temp_hp(target, 7, action.source_definition_id, actor.entity_id)
            self._apply_condition(target, "condition:ling_qi.keep_measure_temp_hp_consumed", action.source_definition_id, actor.entity_id, expires_on="UNTIL_SHORT_REST")

    def _resolve_sea_risen_bearing(self, actor: ActorState, action: ActionDefinition) -> None:
        self._grant_temp_hp(actor, int(action.parameters["temp_hp"]), action.source_definition_id, actor.entity_id)
        zone_id = f"zone:{action.source_definition_id}:{self.state.event_sequence + 1}"
        cells = self.grid.cells_in_radius_of_cells(
            self._actor_cells(actor),
            int(action.parameters["radius_ft"]) // self.grid.square_size_ft,
        )
        zone = ZoneState(
            zone_id=zone_id, source_definition_id=action.source_definition_id, owner_id=actor.entity_id,
            center=actor.position, radius_cells=int(action.parameters["radius_ft"]) // self.grid.square_size_ft,
            affected_cells=cells, concentration_link=False, duration_rounds=1, created_round=self.state.round_number,
            trigger_profile={"kind":"SEA_RISEN", "speed_delta":int(action.parameters["speed_delta"]), "expires":"START_OF_BAI_NEXT_TURN"},
        )
        self.state.zones[zone_id] = zone
        self._append_event("ZONE_CREATED", action.source_definition_id, actor_id=actor.entity_id, payload={"zone":zone.model_dump(mode="json")})

    def _resolve_command_cui(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        cui = self.state.actors[CUI]
        if not cui.active:
            raise self._intent_error("GATE2_CUI_INACTIVE", "Cui cannot be commanded while inactive.", intent)
        option = intent.option_ids[0] if intent.option_ids else ""
        if option == "STRIKE" and (
            not target.active
            or target.team_id == cui.team_id
            or target.entity_id == cui.entity_id
        ):
            raise self._intent_error(
                "GATE5_CUI_STRIKE_TARGET_NOT_HOSTILE",
                "Cui Strike requires one active hostile target and cannot target Cui or an ally.",
                intent,
            )
        self._remove_condition(cui, "condition:core.dodge", action.source_definition_id)
        self._commanded_cui_this_turn = True
        if option == "STRIKE":
            self._move_cui_toward(target, max_distance_ft=cui.speed_ft)
            if self._distance_actor_to_actor(cui, target) <= 5 and target.active:
                self._resolve_cui_strike(cui, target, ACTIONS["action:bai_cui.companion_strike"], intent)
        elif option == "DODGE":
            self._apply_condition(cui, "condition:core.dodge", action.source_definition_id, actor.entity_id, expires_on="START_OF_CUI_NEXT_ACTIVATION")
        elif option == "DASH":
            self._move_cui_toward(target, max_distance_ft=cui.speed_ft * 2)
        elif option == "HOLD":
            self._append_event("HOLD_POSITION_COMMITTED", action.source_definition_id, actor_id=CUI)
        else:
            raise self._intent_error("GATE2_INVALID_CUI_COMMAND", "Cui command option is invalid.", intent)

    def _resolve_cui_strike(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        hit = self._resolve_attack_action(actor, target, action, intent)
        if hit and target.active:
            save = self._roll_save(target, "CON", 15, action.source_definition_id)
            if save.total < 15 and not actor.turn_flags.get("dose_applied_this_activation"):
                self._apply_dose(target, action.source_definition_id, actor.entity_id)
                actor.turn_flags["dose_applied_this_activation"] = True

    def _resolve_optional_rider(self, actor: ActorState, candidate: LegalCandidate, intent: ActionIntent) -> None:
        pending = self.state.pending_resolution
        if pending is None or candidate.source_definition_id not in pending.follow_up_candidates:
            raise self._intent_error("GATE2_OPTIONAL_RIDER_WINDOW_CLOSED", "The optional rider trigger window is closed.", intent)
        target = self.state.actors[candidate.target_ids[0]]
        source_id = candidate.source_definition_id
        if source_id == "talent:lee_jia.spark_step":
            if candidate.destination is None:
                raise self._intent_error("GATE2_SPARK_STEP_DESTINATION_REQUIRED", "Spark Step requires an offered destination.", intent)
            ignored = intent.option_ids[0] if intent.option_ids else None
            if ignored:
                actor.turn_flags["spark_step_ignore_oa_from"] = ignored
            actor.movement_remaining_ft += candidate.movement_cost_ft
            self._resolve_movement(actor, candidate, intent)
            actor.turn_flags.pop("spark_step_ignore_oa_from", None)
        elif source_id == "action:bai_meizhen.water_whip":
            self._spend_resource(actor, "resource:bai_meizhen.qi", 1, source_id)
            save = self._roll_save(target, "STR", 15, source_id)
            if save.total < 15:
                self._apply_condition(target, "condition:core.grappled", source_id, actor.entity_id, expires_on="END_OF_BAI_NEXT_TURN", data={"escape_dc":15})
                self._maybe_gain_ancestral_resonance(actor, "GRAPPLE", source_id)
        elif source_id == "action:ling_qi.reflection_cut":
            self._spend_resource(actor, "resource:ling_qi.mirror_trace", 1, source_id)
            self._remove_condition(actor, "condition:ling_qi.mirror_trace_window", source_id)
            self._commit_damage(target, 3, "PSYCHIC", source_id, actor.entity_id, intent, reaction_depth=0)
        elif source_id == "action:bai_meizhen.moon_disc_descent":
            self._spend_resource(actor, "resource:bai_meizhen.moon_sea_radiance", 1, source_id)
            self._remove_condition(actor, "condition:bai_meizhen.moon_sea_radiance_window", source_id)
            damage_type = intent.option_ids[0] if intent.option_ids else "RADIANT"
            self._commit_damage(target, 7, damage_type, source_id, actor.entity_id, intent, reaction_depth=0)
            if target.active:
                self._add_modifier(target, source_id, "speed_ft", "ADD", -10, "ALL_MOVEMENT", expires_on="START_OF_BAI_NEXT_TURN")
        elif source_id == "action:bai_meizhen.bloodline_strike":
            self._spend_resource(actor, "resource:bai_meizhen.ancestral_resonance", 1, source_id)
            roll = self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":8,"modifier":0}), actor_id=actor.entity_id, reason="BLOODLINE_STRIKE_DAMAGE")
            self._record_roll(roll)
            self._append_event("DAMAGE_ROLLED", source_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload=roll.model_dump(mode="json"))
            self._commit_damage(target, roll.total, "POISON", source_id, actor.entity_id, intent, reaction_depth=0)
            actor.turn_flags["bloodline_strike_used_this_turn"] = True
        else:
            raise self._intent_error("GATE2_UNKNOWN_OPTIONAL_RIDER", "Unknown optional rider.", intent)
        self._complete_follow_up(source_id)

    def _open_follow_up_window(
        self, actor: ActorState, target: ActorState, source_id: str, intent: ActionIntent | None, follow_ups: Iterable[str]
    ) -> None:
        offered = [item for item in follow_ups if item]
        if not offered or not target.active or self.state.terminal_result is not None:
            return
        pending = self.state.pending_resolution
        if pending is None:
            pending = PendingResolution(
                transaction_id=self._transaction_id or "", source_definition_id=source_id,
                intent_id=intent.intent_id if intent else self._active_intent_id, actor_id=actor.entity_id,
                target_ids=(target.entity_id,), stage="OPTIONAL_RIDER", follow_up_candidates=[],
                context={"targets_by_follow_up":{}},
            )
            self.state.pending_resolution = pending
        if pending.actor_id != actor.entity_id:
            return
        target_map = pending.context.setdefault("targets_by_follow_up", {})
        for follow_up in offered:
            if follow_up not in pending.follow_up_candidates:
                pending.follow_up_candidates.append(follow_up)
            targets = target_map.setdefault(follow_up, [])
            if target.entity_id not in targets:
                targets.append(target.entity_id)
        pending.target_ids = tuple(sorted(set(pending.target_ids + (target.entity_id,))))

    def _complete_follow_up(self, source_id: str) -> None:
        pending = self.state.pending_resolution
        if pending is None:
            return
        pending.follow_up_candidates = [item for item in pending.follow_up_candidates if item != source_id]
        pending.context.get("targets_by_follow_up", {}).pop(source_id, None)
        if not pending.follow_up_candidates:
            self.state.pending_resolution = None

    def _maybe_gain_mirror_trace(self, trigger: str, source_id: str) -> bool:
        ling = self.state.actors[LING]
        key = f"once_per_round:mirror_trace:{self.state.round_number}"
        if not ling.active or ling.resources.get("resource:ling_qi.mirror_trace", 0) >= 1 or ling.turn_flags.get(key):
            return False
        ling.turn_flags[key] = True
        self._gain_resource(ling, "resource:ling_qi.mirror_trace", 1, "passive:ling_qi.mirror_trace")
        self._apply_condition(ling, "condition:ling_qi.mirror_trace_window", "passive:ling_qi.mirror_trace", LING, expires_on="END_OF_LING_NEXT_TURN", data={"trigger":trigger,"source":source_id,"generated_transaction":self._transaction_id})
        return True

    def _maybe_gain_moon_sea(self, actor: ActorState, trigger: str, source_id: str) -> bool:
        if actor.entity_id != BAI or source_id in {"action:bai_meizhen.sea_risen_bearing", "action:bai_meizhen.moon_disc_descent", "reaction:bai_meizhen.sea_moon_interposition"}:
            return False
        key = f"once_per_round:moon_sea:{self.state.round_number}"
        if not actor.active or actor.resources.get("resource:bai_meizhen.moon_sea_radiance", 0) >= 1 or actor.turn_flags.get(key):
            return False
        actor.turn_flags[key] = True
        self._gain_resource(actor, "resource:bai_meizhen.moon_sea_radiance", 1, "resource:bai_meizhen.moon_sea_radiance")
        self._apply_condition(actor, "condition:bai_meizhen.moon_sea_radiance_window", "resource:bai_meizhen.moon_sea_radiance", BAI, expires_on="END_OF_BAI_NEXT_TURN", data={"trigger":trigger,"source":source_id,"generated_transaction":self._transaction_id})
        return True

    def _maybe_gain_ancestral_resonance(self, actor: ActorState, trigger: str, source_id: str) -> bool:
        if actor.entity_id != BAI or not actor.active or actor.turn_flags.get("ancestral_resonance_gain_this_turn"):
            return False
        actor.turn_flags["ancestral_resonance_gain_this_turn"] = True
        self._gain_resource(actor, "resource:bai_meizhen.ancestral_resonance", 1, "resource:bai_meizhen.ancestral_resonance")
        self._append_event("RESOURCE_TRIGGERED", "resource:bai_meizhen.ancestral_resonance", actor_id=BAI, payload={"trigger":trigger,"source":source_id})
        return True

    # ------------------------------------------------------------------
    # Reactions and damage
    # ------------------------------------------------------------------
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
        pending = max(0, amount)
        if target.entity_id in getattr(self, "runtime_actor_ids", set()):
            from .character_runtime_adapter import CharacterCombatRuntimeEngine
            runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
            runtime.__dict__.update(self.__dict__)
            pending = CharacterCombatRuntimeEngine._apply_damage_resistance(runtime, target, pending, damage_type, source_definition_id)
            self.__dict__.update(runtime.__dict__)
        self._append_event("REACTION_WINDOW_OPENED", source_definition_id, actor_id=source_actor_id, target_ids=(target.entity_id,), payload={"checkpoint":"DAMAGE_APPLICATION","pending_damage":pending,"reaction_depth":reaction_depth})
        if intent is not None and reaction_depth <= 2:
            pending = self._resolve_damage_reaction(target, pending, intent, reaction_depth)
        if pending < 0:
            pending = 0
        temp_absorb = min(target.temporary_hp, pending)
        target.temporary_hp -= temp_absorb
        hp_damage = pending - temp_absorb
        target.current_hp = max(0, target.current_hp - hp_damage)
        self._append_event("DAMAGE_COMMITTED", source_definition_id, actor_id=source_actor_id, target_ids=(target.entity_id,), payload={
            "rolled_or_pending_damage": amount,
            "reduced_to": pending,
            "temporary_hp_absorbed": temp_absorb,
            "hp_damage": hp_damage,
            "damage_type": damage_type,
            "remaining_hp": target.current_hp,
        })
        if hp_damage > 0 and target.concentration is not None and target.active:
            self._concentration_check(target, hp_damage)
        if target.current_hp == 0 and target.active:
            self._defeat(target, source_definition_id)
        self._check_victory()
        return hp_damage

    def _resolve_damage_reaction(self, target: ActorState, pending: int, intent: ActionIntent, reaction_depth: int) -> int:
        if any("reaction:fire.fire_ward" in actor.reaction_ids for actor in self.state.actors.values()) and hasattr(self, "runtime_actor_ids"):
            from .character_runtime_adapter import CharacterCombatRuntimeEngine
            runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
            runtime.__dict__.update(self.__dict__)
            result = CharacterCombatRuntimeEngine._resolve_damage_reaction(runtime, target, pending, intent, reaction_depth)
            self.__dict__.update(runtime.__dict__)
            if result != pending:
                return result
        candidates: list[tuple[str, str]] = []
        if target.entity_id == AN:
            candidates += [(AN,"reaction:an_eui.sheath_bone_guard"),(AN,"reaction:core.stamina_guard")]
        if target.entity_id == LING:
            candidates += [(LING,"reaction:ling_qi.false_image_guard")]
        ling = self.state.actors.get(LING)
        if ling is not None and target.team_id == ling.team_id and self._distance_actor_to_actor(ling, target) <= 30:
            candidates += [(LING,"reaction:ling_qi.rhythmic_guard")]
        bai = self.state.actors.get(BAI)
        if bai is not None and target.team_id == bai.team_id and self._distance_actor_to_actor(bai, target) <= 30:
            candidates += [(BAI,"reaction:bai_meizhen.water_shield"),(BAI,"reaction:bai_meizhen.sea_moon_interposition")]
        candidates.sort(key=lambda row:(0 if row[0]==target.entity_id else 1,self._initiative_rank(self.state.actors[row[0]]),row[1]))
        for reactor_id, reaction_id in candidates:
            if not self._reaction_usable(reactor_id,reaction_id):
                continue
            decision = self._reaction_decision(intent,"DAMAGE_APPLICATION",reactor_id,reaction_id)
            if decision is None or decision.selection == "DECLINE":
                continue
            reactor = self.state.actors[reactor_id]
            reduction = 0
            if reaction_id == "reaction:core.stamina_guard":
                maximum = min(reactor.proficiency_bonus, reactor.resources.get("resource:an_eui.stamina",0))
                if not 1 <= decision.spend <= maximum:
                    raise self._intent_error("GATE2_INVALID_STAMINA_GUARD_SPEND", "Stamina Guard spend is outside the legal range.", intent)
                self._spend_resource(reactor,"resource:an_eui.stamina",decision.spend,reaction_id)
                for index in range(decision.spend):
                    roll = self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":10,"modifier":0}), actor_id=reactor_id, reason=f"STAMINA_GUARD_REDUCTION:{index+1}")
                    self._record_roll(roll)
                    reduction += roll.total
            elif reaction_id == "reaction:an_eui.sheath_bone_guard":
                self._spend_resource(reactor,"resource:an_eui.severance_edge",1,reaction_id); reduction=6
            elif reaction_id == "reaction:ling_qi.false_image_guard":
                self._spend_resource(reactor,"resource:ling_qi.mirror_trace",1,reaction_id); reduction=7
            elif reaction_id == "reaction:ling_qi.rhythmic_guard":
                self._spend_resource(reactor,"resource:ling_qi.qi",1,reaction_id)
                roll=self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":8,"modifier":4}),actor_id=reactor_id,reason="RHYTHMIC_GUARD_REDUCTION");self._record_roll(roll);reduction=roll.total
            elif reaction_id == "reaction:bai_meizhen.water_shield":
                self._spend_resource(reactor,"resource:bai_meizhen.qi",1,reaction_id)
                roll=self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":10,"modifier":4}),actor_id=reactor_id,reason="WATER_SHIELD_REDUCTION");self._record_roll(roll);reduction=roll.total
                self._maybe_gain_moon_sea(reactor, "PROTECTION_EVENT", reaction_id)
            elif reaction_id == "reaction:bai_meizhen.sea_moon_interposition":
                self._spend_resource(reactor,"resource:bai_meizhen.moon_sea_radiance",1,reaction_id);reduction=10 if "DIRECT_CONTEST" in decision.option_ids else 7
            reactor.reaction_available=False
            reduced=max(0,pending-reduction)
            self._append_event("REACTION_RESOLVED",reaction_id,actor_id=reactor_id,target_ids=(target.entity_id,),payload={"checkpoint":"DAMAGE_APPLICATION","spend":decision.spend,"reduction":reduction,"pending_before":pending,"pending_after":reduced,"reaction_depth":reaction_depth})
            return reduced
        self._append_event("REACTION_DECLINED",source_definition_id="system:combat.damage_reaction_window",actor_id=target.entity_id,payload={"pending_damage":pending})
        return pending

    # ------------------------------------------------------------------
    # Conditions, modifiers, concentration, zones, companion defaults
    # ------------------------------------------------------------------
    def _apply_condition(self, target: ActorState, condition_id: str, source_id: str, source_actor_id: str, *, expires_on: str | None, data: dict[str,Any] | None=None) -> None:
        instance_id=f"condition-instance:{condition_id}:{target.entity_id}:{self.state.event_sequence+1}"
        target.conditions[instance_id]=ConditionInstance(instance_id=instance_id,condition_id=condition_id,source_definition_id=source_id,source_actor_id=source_actor_id,target_id=target.entity_id,applied_sequence=self.state.event_sequence+1,expires_on=expires_on,data=data or {})
        self._append_event("CONDITION_APPLIED",source_id,actor_id=source_actor_id,target_ids=(target.entity_id,),payload={"condition_id":condition_id,"instance_id":instance_id,"expires_on":expires_on})

    def _remove_condition(self,target:ActorState,condition_id:str,source_id:str) -> None:
        for iid,condition in list(target.conditions.items()):
            if condition.condition_id==condition_id:
                del target.conditions[iid]
                self._append_event("CONDITION_REMOVED",source_id,actor_id=condition.source_actor_id,target_ids=(target.entity_id,),payload={"condition_id":condition_id,"instance_id":iid})

    def _add_modifier(self,target:ActorState,source_id:str,target_field:str,operation:str,value:int|str,applies_to:str,*,expires_on:str|None) -> None:
        mid=f"modifier:{source_id}:{target.entity_id}:{self.state.event_sequence+1}"
        target.modifiers[mid]=ModifierInstance(modifier_id=mid,source_definition_id=source_id,source_actor_id=self.state.current_actor_id,target_id=target.entity_id,target_field=target_field,operation=operation,value=value,applies_to=applies_to,expires_on=expires_on)
        self._append_event("MODIFIER_APPLIED",source_id,actor_id=self.state.current_actor_id,target_ids=(target.entity_id,),payload={"modifier_id":mid,"target_field":target_field,"operation":operation,"value":value,"expires_on":expires_on})

    def _grant_temp_hp(self,target:ActorState,amount:int,source_id:str,source_actor_id:str) -> None:
        before=target.temporary_hp;target.temporary_hp=max(before,amount)
        self._append_event("TEMP_HP_GRANTED",source_id,actor_id=source_actor_id,target_ids=(target.entity_id,),payload={"offered":amount,"before":before,"after":target.temporary_hp})

    def _start_concentration(self,actor:ActorState,source_id:str) -> None:
        if actor.concentration is not None:
            self._end_concentration(actor,"REPLACED")
        actor.concentration=ConcentrationState(source_definition_id=source_id,started_sequence=self.state.event_sequence+1)
        self._append_event("CONCENTRATION_STARTED",source_id,actor_id=actor.entity_id)

    def _end_concentration(self,actor:ActorState,reason:str) -> None:
        if actor.concentration is None:return
        conc=actor.concentration
        if conc.zone_id and conc.zone_id in self.state.zones:
            zone=self.state.zones[conc.zone_id];zone.active=False
            self._append_event("ZONE_REMOVED",conc.source_definition_id,actor_id=actor.entity_id,payload={"zone_id":zone.zone_id,"reason":reason})
        actor.concentration=None
        for a in self.state.actors.values():
            for iid,c in list(a.conditions.items()):
                if c.source_definition_id==conc.source_definition_id and c.expires_on=="CONCENTRATION_END":
                    del a.conditions[iid]
                    self._append_event("CONDITION_REMOVED",conc.source_definition_id,actor_id=actor.entity_id,target_ids=(a.entity_id,),payload={"instance_id":iid,"reason":reason})
        self._append_event("CONCENTRATION_ENDED",conc.source_definition_id,actor_id=actor.entity_id,payload={"reason":reason})

    def _concentration_check(self,actor:ActorState,hp_damage:int) -> None:
        dc=max(10,hp_damage//2)
        roll=self._roll_save(actor,"CON",dc,SYSTEM_CONCENTRATION)
        if roll.total<dc:self._end_concentration(actor,"FAILED_DAMAGE_CHECK")

    def _resolve_zone_triggers(self,actor:ActorState,*,checkpoint:str) -> None:
        for zone in sorted(self.state.zones.values(),key=lambda z:z.zone_id):
            if zone.active and self._in_zone(actor,zone) and self.state.actors[zone.owner_id].team_id!=actor.team_id:
                if checkpoint=="AT_TURN_START" and zone.trigger_profile.get("kind")=="BLACKWATER":self._resolve_zone_effect(zone,actor,checkpoint=checkpoint)
                elif checkpoint=="AT_TURN_START" and zone.trigger_profile.get("kind")=="SEA_RISEN":self._resolve_zone_effect(zone,actor,checkpoint=checkpoint)

    def _resolve_zone_entry_triggers(self,actor:ActorState) -> None:
        for zone in sorted(self.state.zones.values(),key=lambda z:z.zone_id):
            if not zone.active or not self._in_zone(actor, zone):
                continue
            if zone.trigger_profile.get("kind") == "CHARGE_SPACE" and actor.entity_id != zone.owner_id:
                self._commit_damage(actor, 3, "LIGHTNING", "resource:lee_jia.lightning_charge", zone.owner_id, None, reaction_depth=0)
                self._remove_lightning_charge_zone(zone, "FIRST_ENTRY_DISCHARGE")
            elif self.state.actors[zone.owner_id].team_id != actor.team_id and zone.trigger_profile.get("kind")=="BLACKWATER":
                self._resolve_zone_effect(zone,actor,checkpoint="ON_ENTER_ZONE")
            elif self.state.actors[zone.owner_id].team_id != actor.team_id and zone.trigger_profile.get("kind")=="SEA_RISEN":
                self._resolve_zone_effect(zone,actor,checkpoint="ON_ENTER_ZONE")

    def _resolve_zone_triggers_for_owner_end(self,owner_id:str) -> None:
        for zone in sorted(self.state.zones.values(),key=lambda z:z.zone_id):
            if zone.active and zone.owner_id==owner_id and zone.trigger_profile.get("kind")=="NOCTURNE":
                for target in sorted(self.state.actors.values(),key=lambda a:a.entity_id):
                    if target.active and target.team_id!=self.state.actors[owner_id].team_id and self._in_zone(target,zone):self._resolve_zone_effect(zone,target,checkpoint="AT_TURN_END")

    def _resolve_zone_effect(self,zone:ZoneState,target:ActorState,*,checkpoint:str) -> None:
        owner = self.state.actors[zone.owner_id]
        trace_available_before = owner.entity_id == LING and owner.resources.get("resource:ling_qi.mirror_trace", 0) >= 1
        moon_available_before = owner.entity_id == BAI and owner.resources.get("resource:bai_meizhen.moon_sea_radiance", 0) >= 1
        ancestral_available_before = owner.entity_id == BAI and owner.resources.get("resource:bai_meizhen.ancestral_resonance", 0) >= 1 and not owner.turn_flags.get("bloodline_strike_used_this_turn")
        key=f"{self.state.round_number}:{self.state.current_actor_id}"
        stable_key = int(canonical_sha256({"key": key})[:12], 16)
        if zone.per_turn_triggered.get(target.entity_id)==stable_key:return
        zone.per_turn_triggered[target.entity_id]=stable_key
        if zone.trigger_profile.get("kind")=="BLACKWATER":
            save=self._roll_save(target,"CON",15,zone.source_definition_id)
            dmg=self.roller.roll(ACTIONS[zone.source_definition_id].damage,actor_id=owner.entity_id,reason=f"ZONE_DAMAGE:{zone.zone_id}");self._record_roll(dmg)
            amount=dmg.total if save.total<15 else dmg.total//2
            self._commit_damage(target,amount,"POISON",zone.source_definition_id,owner.entity_id,self._active_intent,reaction_depth=0)
            if save.total<15 and target.active:
                if moon_available_before:
                    self._open_follow_up_window(owner, target, zone.source_definition_id, self._active_intent, ["action:bai_meizhen.moon_disc_descent"])
                if ancestral_available_before:
                    self._open_follow_up_window(owner, target, zone.source_definition_id, self._active_intent, ["action:bai_meizhen.bloodline_strike"])
                self._apply_dose(target,zone.source_definition_id,owner.entity_id)
                self._apply_condition(target,"condition:core.reaction_denied",zone.source_definition_id,owner.entity_id,expires_on="LEAVE_ZONE_OR_START_OF_NEXT_TURN")
                self._maybe_gain_moon_sea(owner, "FAILED_HOSTILE_CONTEST", zone.source_definition_id)
        elif zone.trigger_profile.get("kind")=="NOCTURNE":
            save=self._roll_save(target,"WIS",15,zone.source_definition_id)
            if save.total<15:
                if trace_available_before:
                    self._open_follow_up_window(owner, target, zone.source_definition_id, self._active_intent, ["action:ling_qi.reflection_cut"])
                self._maybe_gain_mirror_trace("HOSTILE_FAILED_SAVE", zone.source_definition_id)
                self._apply_condition(target,"condition:ling_qi.nocturne_hindered",zone.source_definition_id,owner.entity_id,expires_on="LEAVE_ZONE_OR_CONCENTRATION_END",data={"speed_delta":-10,"reaction_denied":True})
        elif zone.trigger_profile.get("kind")=="SEA_RISEN":
            self._add_modifier(target, zone.source_definition_id, "speed_ft", "ADD", int(zone.trigger_profile.get("speed_delta", -5)), "ALL_MOVEMENT", expires_on="END_OF_CURRENT_TURN")

    def _remove_zone_leave_conditions(self, actor: ActorState) -> None:
        active_zone_sources = {zone.source_definition_id for zone in self.state.zones.values() if zone.active and self._in_zone(actor, zone)}
        for iid, condition in list(actor.conditions.items()):
            if condition.expires_on in {"LEAVE_ZONE_OR_START_OF_NEXT_TURN", "LEAVE_ZONE_OR_CONCENTRATION_END"} and condition.source_definition_id not in active_zone_sources:
                del actor.conditions[iid]
                self._append_event("CONDITION_REMOVED", SYSTEM_EXPIRATION, actor_id=actor.entity_id, target_ids=(actor.entity_id,), payload={"instance_id":iid,"condition_id":condition.condition_id,"reason":"LEFT_ZONE"})

    def _cui_default_dodge(self) -> None:
        cui=self.state.actors[CUI]
        self._remove_condition(cui,"condition:core.dodge",SYSTEM_COMPANION_DEFAULT)
        self._apply_condition(cui,"condition:core.dodge",SYSTEM_COMPANION_DEFAULT,BAI,expires_on="START_OF_CUI_NEXT_ACTIVATION")
        self._append_event("COMPANION_DEFAULT_APPLIED",SYSTEM_COMPANION_DEFAULT,actor_id=CUI,payload={"behavior":"DODGE_AND_HOLD"})

    def _cui_guard_and_rescue_default(self) -> None:
        cui=self.state.actors[CUI]
        self._remove_condition(cui,"condition:core.dodge",SYSTEM_COMPANION_DEFAULT)
        active_allies=[a for a in self.state.actors.values() if a.active and a.team_id==cui.team_id and a.primary_combatant]
        if active_allies:
            target=min(active_allies,key=lambda a:(a.current_hp/a.maximum_hp,a.entity_id))
            self._move_cui_toward(target,max_distance_ft=cui.speed_ft)
        self._apply_condition(cui,"condition:core.dodge",SYSTEM_COMPANION_DEFAULT,CUI,expires_on="START_OF_CUI_NEXT_ACTIVATION")
        self._append_event("COMPANION_DEFAULT_APPLIED",SYSTEM_COMPANION_DEFAULT,actor_id=CUI,payload={"behavior":"GUARD_AND_RESCUE"})

    def _move_cui_toward(self,target:ActorState,*,max_distance_ft:int) -> None:
        cui=self.state.actors[CUI]
        reachable=self.grid.reachable(
            cui.position,
            movement_ft=max_distance_ft,
            occupied_cells=self._occupied_cells_except(CUI),
            difficult_cells=self._hostile_difficult_cells(cui),
            footprint=self._footprint(cui),
        )
        if not reachable:return
        ranked=sorted(
            reachable.items(),
            key=lambda row:(
                self._distance_actor_to_actor(cui, target, actor_position=row[0]),
                row[1][1],
                row[0].y,
                row[0].x,
            ),
        )
        dest,(path,cost)=ranked[0];cui.position=dest
        self._append_event("MOVEMENT_COMMITTED","action:bai_meizhen.command_cui",actor_id=CUI,payload={"destination":dest.model_dump(mode="json"),"path":[p.model_dump(mode="json") for p in path],"cost_ft":cost})

    # ------------------------------------------------------------------
    # Atomic mutation helpers and invariants
    # ------------------------------------------------------------------
    def _spend_costs(self,actor:ActorState,costs:Iterable[tuple[str,int]],source_id:str) -> None:
        for rid,amount in costs:self._spend_resource(actor,rid,amount,source_id)

    def _spend_resource(self,actor:ActorState,resource_id:str,amount:int,source_id:str) -> None:
        current=actor.resources.get(resource_id)
        if current is None or amount<0 or current<amount:raise error("GATE2_RESOURCE_UNDERFLOW",f"{actor.display_name} cannot spend {amount} {resource_id}.",phase="RESOLUTION",subsystem="RESOURCE",entity_id=actor.entity_id,source_definition=source_id,recommended_action="Choose a legal candidate with an affordable cost.",recovery=RecoveryDisposition.RETRY)
        actor.resources[resource_id]=current-amount
        self._append_event("RESOURCE_SPENT",source_id,actor_id=actor.entity_id,payload={"resource_id":resource_id,"amount":amount,"remaining":actor.resources[resource_id]})
        if actor.resources[resource_id] == 0 and resource_id == "resource:ling_qi.mirror_trace":
            self._remove_condition(actor, "condition:ling_qi.mirror_trace_window", source_id)
        if actor.resources[resource_id] == 0 and resource_id == "resource:bai_meizhen.moon_sea_radiance":
            self._remove_condition(actor, "condition:bai_meizhen.moon_sea_radiance_window", source_id)

    def _gain_resource(self,actor:ActorState,resource_id:str,amount:int,source_id:str) -> None:
        current=actor.resources.get(resource_id);maximum=actor.resource_maximums.get(resource_id)
        if current is None or maximum is None or amount<0:raise ValueError("unknown resource")
        gained=min(amount,maximum-current);actor.resources[resource_id]=current+gained
        self._append_event("RESOURCE_GAINED",source_id,actor_id=actor.entity_id,payload={"resource_id":resource_id,"requested":amount,"gained":gained,"current":actor.resources[resource_id]})

    def _consume_economy(self,actor:ActorState,action:ActionDefinition) -> None:
        if action.economy==EconomyKind.ACTION:
            if not actor.action_available:raise ValueError("action unavailable")
            actor.action_available=False
        elif action.economy==EconomyKind.BONUS_ACTION:
            if not actor.bonus_action_available:raise ValueError("bonus action unavailable")
            actor.bonus_action_available=False

    def _defeat(self,target:ActorState,source_id:str) -> None:
        target.current_hp=0;target.active=False;target.action_available=False;target.bonus_action_available=False;target.reaction_available=False;target.movement_remaining_ft=0
        self._end_concentration(target,"ENTITY_DEFEATED")
        self._append_event("ENTITY_DEFEATED",SYSTEM_DEFEAT,actor_id=target.entity_id,payload={"nonlethal":True,"defeating_source":source_id})

    def _check_victory(self) -> None:
        teams={a.team_id for a in self.state.actors.values() if a.primary_combatant}
        active={team:sum(1 for a in self.state.actors.values() if a.primary_combatant and a.team_id==team and a.active) for team in teams}
        live=[team for team,count in active.items() if count>0]
        if len(live)==1:self._end_match(TerminalKind.VICTORY,live[0],"Opposing primary combatants are inactive.")
        elif len(live)==0:self._end_match(TerminalKind.DRAW_SIMULTANEOUS,None,"Both teams lost all primary combatants in one atomic resolution.")

    def _end_match(self,kind:TerminalKind,winning_team_id:str|None,reason:str) -> None:
        if self.state.terminal_result is not None:return
        terminal=TerminalResult(kind=kind,winning_team_id=winning_team_id,reason=reason,event_sequence=self.state.event_sequence+1)
        self.state.terminal_result=terminal
        self._append_event("MATCH_ENDED",SYSTEM_VICTORY,payload=terminal.model_dump(mode="json"))

    def _assert_invariants(self) -> None:
        occupied: set[tuple[int, int]] = set()
        for actor in self.state.actors.values():
            if not 0<=actor.current_hp<=actor.maximum_hp:raise ValueError("HP invariant")
            if actor.temporary_hp<0 or actor.movement_remaining_ft<0:raise ValueError("nonnegative invariant")
            for rid,value in actor.resources.items():
                if not 0<=value<=actor.resource_maximums[rid]:raise ValueError(f"resource invariant {rid}")
            actor_cells = set(self._actor_cells(actor))
            if not actor_cells:
                raise ValueError("empty footprint invariant")
            if any(not self.grid.in_bounds(cell) or cell in self.grid.blocked for cell in actor_cells):
                raise ValueError("footprint position invariant")
            if actor.active:
                if occupied & actor_cells:
                    raise ValueError("occupied footprint invariant")
                occupied.update(actor_cells)
            if not actor.active and (actor.action_available or actor.bonus_action_available):raise ValueError("inactive economy invariant")
        if [e.sequence for e in self.events]!=list(range(1,len(self.events)+1)):raise ValueError("event sequence invariant")
        if self.state.pending_resolution and self.state.pending_resolution.reaction_depth>2:raise ValueError("reaction depth invariant")

    # ------------------------------------------------------------------
    # Utility calculations
    # ------------------------------------------------------------------
    def _roll_save(self,target:ActorState,ability:str,dc:int,source_id:str) -> RollRecord:
        mode="NORMAL"
        charge = next((c for c in target.conditions.values() if c.condition_id in {"condition:lee_jia.lightning_charge.self","condition:lee_jia.lightning_charge.willing_creature"}), None)
        if ability == "DEX" and charge is not None:
            mode = "ADVANTAGE"
        if self._has_condition(target,"condition:core.dodge") and ability=="DEX":mode="ADVANTAGE"
        roll=self.roller.d20(modifier=target.saving_throws.get(ability,0),actor_id=target.entity_id,reason=f"SAVE:{source_id}:{ability}",mode=mode)
        self._record_roll(roll)
        true_name_used = False
        if target.entity_id == LING and target.resources.get("resource:ling_qi.mirror_trace", 0) >= 1 and self._active_intent is not None:
            decision = self._reaction_decision(self._active_intent, "SAVE_RESULT_BEFORE_DECLARED", LING, "action:ling_qi.true_name_witness")
            if decision is not None and decision.selection == "USE":
                self._spend_resource(target, "resource:ling_qi.mirror_trace", 1, "action:ling_qi.true_name_witness")
                roll = roll.model_copy(update={"modifier":roll.modifier + 3, "total":roll.total + 3})
                true_name_used = True
                self._append_event("REACTION_RESOLVED", "action:ling_qi.true_name_witness", actor_id=LING, target_ids=(LING,), payload={"checkpoint":"SAVE_RESULT_BEFORE_DECLARED","bonus":3,"source_save":source_id})
        self._append_event("SAVE_ROLLED",source_id,actor_id=target.entity_id,payload={**roll.model_dump(mode="json"),"dc":dc,"success":roll.total>=dc,"true_name_witness":true_name_used})
        if ability == "DEX" and charge is not None:
            self._remove_lightning_charge_condition(target, charge.instance_id, "DEX_SAVE_DISCHARGE")
        return roll

    def _attack_mode(self,actor:ActorState,target:ActorState) -> str:
        disadvantage=self._has_condition(target,"condition:core.dodge") or any(m.target_field=="attack_mode" and m.value=="DISADVANTAGE" and not m.consumed for m in actor.modifiers.values())
        advantage=any(m.target_field=="incoming_attack_mode" and m.value=="ADVANTAGE" and not m.consumed for m in target.modifiers.values())
        if disadvantage and advantage:return "NORMAL"
        if advantage:return "ADVANTAGE"
        if disadvantage:return "DISADVANTAGE"
        return "NORMAL"

    def _consume_attack_modifiers(self,actor:ActorState) -> int:
        delta=0
        for mid,m in list(actor.modifiers.items()):
            if m.target_field=="attack_roll" and m.operation=="SUBTRACT_DIE" and not m.consumed:
                roll=self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":4,"modifier":0}),actor_id=actor.entity_id,reason="ATTACK_PENALTY_1D4");self._record_roll(roll);delta-=roll.total
                del actor.modifiers[mid];self._append_event("MODIFIER_REMOVED",m.source_definition_id,actor_id=actor.entity_id,payload={"modifier_id":mid,"reason":"CONSUMED"})
            elif m.target_field=="attack_mode" and not m.consumed:
                del actor.modifiers[mid];self._append_event("MODIFIER_REMOVED",m.source_definition_id,actor_id=actor.entity_id,payload={"modifier_id":mid,"reason":"CONSUMED"})
        return delta

    def _ac_modifier(self,target:ActorState) -> int:
        return sum(int(m.value) for m in target.modifiers.values() if m.target_field=="armor_class" and m.operation=="ADD")

    def _effective_speed(self,actor:ActorState) -> int:
        if self._has_condition(actor,"condition:core.grappled"):return 0
        delta=sum(int(m.value) for m in actor.modifiers.values() if m.target_field=="speed_ft" and m.operation=="ADD")
        for c in actor.conditions.values():
            delta+=int(c.data.get("speed_delta",0))
        return max(0,actor.speed_ft+delta)

    def _has_condition(self,actor:ActorState,condition_id:str) -> bool:return any(c.condition_id==condition_id for c in actor.conditions.values())
    def _can_pay(self,actor:ActorState,costs:Iterable[tuple[str,int]]) -> bool:return all(actor.resources.get(rid,0)>=amount for rid,amount in costs)
    def _target_in_range(self,actor:ActorState,target:ActorState,action:ActionDefinition) -> bool:
        max_ft=action.range_ft if action.range_ft is not None else action.reach_ft
        return max_ft is None or self._distance_actor_to_actor(actor, target) <= max_ft
    def _obscured_cells(self) -> set[tuple[int,int]]:
        return {(p.x,p.y) for z in self.state.zones.values() if z.active and z.trigger_profile.get("kind")=="NOCTURNE" for p in z.affected_cells}
    def _hostile_difficult_cells(self,actor:ActorState) -> set[tuple[int,int]]:
        return {(p.x,p.y) for z in self.state.zones.values() if z.active and z.trigger_profile.get("kind")=="BLACKWATER" and self.state.actors[z.owner_id].team_id!=actor.team_id for p in z.affected_cells}
    def _in_zone(self,actor:ActorState,zone:ZoneState) -> bool:
        return self._footprint_intersects(actor, zone.affected_cells)
    def _initiative_rank(self,actor:ActorState) -> int:
        try:return self.state.initiative_order.index(actor.entity_id)
        except ValueError:return len(self.state.initiative_order)+1
    def _movement_reaction_exposure(self,actor:ActorState,path:tuple[Position,...]) -> list[str]:
        exposed=[]
        for hostile in self.state.actors.values():
            if hostile.active and hostile.team_id!=actor.team_id and hostile.reaction_available:
                reach=BASIC_MELEE.get(hostile.entity_id,{}).get("reach_ft",5)
                if any(
                    self._distance_actor_to_actor(actor, hostile, actor_position=a) <= reach
                    and self._distance_actor_to_actor(actor, hostile, actor_position=b) > reach
                    for a,b in zip(path,path[1:])
                ):
                    exposed.append(hostile.entity_id)
        return sorted(exposed)
    def _reaction_decision(self,intent:ActionIntent,checkpoint:str,reactor_id:str,reaction_id:str) -> ReactionDecision|None:
        matches=[d for d in intent.reaction_decisions if d.checkpoint==checkpoint and d.reactor_id==reactor_id and d.reaction_source_id==reaction_id]
        if len(matches)>1:raise self._intent_error("GATE2_DUPLICATE_REACTION_DECISION","A reaction was selected more than once.",intent)
        return matches[0] if matches else None
    def _reaction_usable(self,reactor_id:str,reaction_id:str) -> bool:
        reactor=self.state.actors[reactor_id]
        if not reactor.active or not reactor.reaction_available or self._has_condition(reactor,"condition:core.reaction_denied") or any(bool(c.data.get("reaction_denied")) for c in reactor.conditions.values()):return False
        params=self.reaction_parameters.get(reaction_id,{})
        resource=params.get("resource");cost=params.get("cost",1)
        if resource and reactor.resources.get(resource,0)<cost:return False
        if reaction_id=="reaction:ling_qi.rhythmic_guard" and not any(self._has_condition(a,"condition:ling_qi.keep_the_measure") for a in self.state.actors.values()):return False
        return True
    def _eligible_spirit_intercession(self,target:ActorState) -> bool:
        bai=self.state.actors[BAI]
        return (
            target.entity_id==CUI
            and bai.active
            and bai.reaction_available
            and not self._has_condition(bai,"condition:core.reaction_denied")
            and self._distance_actor_to_actor(bai, target) <= 30
        )
    def _maybe_gain_severance(self,actor:ActorState) -> None:
        if actor.resources.get("resource:an_eui.severance_edge",0)>=1:return
        key=f"severance_generated_round_{self.state.round_number}"
        if actor.turn_flags.get(key):return
        actor.turn_flags[key]=True;self._gain_resource(actor,"resource:an_eui.severance_edge",1,"passive:an_eui.severance_edge")
    def _apply_dose(self,target:ActorState,source_id:str,source_actor_id:str) -> None:
        existing=[c for c in target.conditions.values() if c.condition_id=="condition:bai_meizhen.dose_mark"]
        if existing:
            existing[0].stacks+=1
            self._append_event("CONDITION_APPLIED",source_id,actor_id=source_actor_id,target_ids=(target.entity_id,),payload={"condition_id":"condition:bai_meizhen.dose_mark","stacks":existing[0].stacks})
        else:self._apply_condition(target,"condition:bai_meizhen.dose_mark",source_id,source_actor_id,expires_on="UNTIL_REMOVED")
        bai=self.state.actors[BAI]
        self._maybe_gain_ancestral_resonance(bai, "POISON_OR_MARK", source_id)

    def _gather_charge_candidates(self, actor: ActorState, action: ActionDefinition, kind: CandidateKind) -> list[LegalCandidate]:
        out = [self._candidate(kind, actor, action.source_definition_id, "Gather Charge — Self", target_ids=(actor.entity_id,), option_ids=("SELF",))]
        out.append(self._candidate(kind, actor, action.source_definition_id, "Gather Charge — Held Weapon", option_ids=("HELD_WEAPON",)))
        for ally in sorted(self.state.actors.values(), key=lambda a:a.entity_id):
            if (
                ally.active
                and ally.team_id == actor.team_id
                and ally.entity_id != actor.entity_id
                and self._distance_actor_to_actor(actor, ally) <= 60
                and self._line_of_sight_actor_to_actor(actor, ally)
            ):
                out.append(self._candidate(kind, actor, action.source_definition_id, f"Gather Charge — {ally.display_name}", target_ids=(ally.entity_id,), option_ids=("WILLING_CREATURE",)))
        occupied = {
            cell
            for a in self.state.actors.values()
            if a.active
            for cell in self._actor_cells(a)
        }
        for y in range(self.grid.height):
            for x in range(self.grid.width):
                pos=Position(x=x,y=y)
                if (
                    (x,y) not in occupied
                    and (x,y) not in self.grid.blocked
                    and self._distance_actor_to_cell(actor, pos) <= 60
                    and self._line_of_sight_actor_to_cell(actor, pos)
                ):
                    out.append(self._candidate(kind,actor,action.source_definition_id,f"Gather Charge — Space {x},{y}",destination=pos,option_ids=("SPACE",)))
        return out

    def _lightning_charge_count(self) -> int:
        conditions=sum(1 for a in self.state.actors.values() for c in a.conditions.values() if c.condition_id.startswith("condition:lee_jia.lightning_charge."))
        zones=sum(1 for z in self.state.zones.values() if z.active and z.trigger_profile.get("kind")=="CHARGE_SPACE")
        return conditions+zones

    def _synchronize_lightning_charge_resource(self, lee: ActorState) -> None:
        lee.resources["resource:lee_jia.lightning_charge"] = min(3, self._lightning_charge_count())

    def _create_actor_lightning_charge(self, lee: ActorState, target: ActorState, kind: str, source_id: str) -> None:
        condition_id=f"condition:lee_jia.lightning_charge.{kind.lower()}"
        self._apply_condition(target,condition_id,source_id,lee.entity_id,expires_on="START_OF_LEE_NEXT_TURN",data={"charge_kind":kind,"created_sequence":self.state.event_sequence+1})
        self._synchronize_lightning_charge_resource(lee)

    def _create_space_lightning_charge(self, lee: ActorState, destination: Position, source_id: str) -> None:
        zone_id=f"zone:lee_jia.lightning_charge:{self.state.event_sequence+1}"
        zone=ZoneState(zone_id=zone_id,source_definition_id=source_id,owner_id=lee.entity_id,center=destination,radius_cells=0,affected_cells=(destination,),concentration_link=False,duration_rounds=1,created_round=self.state.round_number,trigger_profile={"kind":"CHARGE_SPACE","created_sequence":self.state.event_sequence+1})
        self.state.zones[zone_id]=zone
        self._append_event("ZONE_CREATED",source_id,actor_id=lee.entity_id,payload={"zone":zone.model_dump(mode="json")})
        self._synchronize_lightning_charge_resource(lee)

    def _end_oldest_lightning_charge(self, lee: ActorState) -> None:
        condition_rows=[]
        for actor in self.state.actors.values():
            for iid,c in actor.conditions.items():
                if c.condition_id.startswith("condition:lee_jia.lightning_charge."):
                    condition_rows.append((c.applied_sequence,"condition",actor,iid))
        zone_rows=[(int(z.trigger_profile.get("created_sequence",0)),"zone",z,None) for z in self.state.zones.values() if z.active and z.trigger_profile.get("kind")=="CHARGE_SPACE"]
        rows=sorted(condition_rows+zone_rows,key=lambda row:(row[0],row[1]))
        if not rows:return
        _,kind,obj,iid=rows[0]
        if kind=="condition":self._remove_lightning_charge_condition(obj,iid,"CAP_REPLACEMENT")
        else:self._remove_lightning_charge_zone(obj,"CAP_REPLACEMENT")
        self._synchronize_lightning_charge_resource(lee)

    def _remove_lightning_charge_condition(self,target:ActorState,instance_id:str,reason:str) -> None:
        condition=target.conditions.pop(instance_id,None)
        if condition:
            self._append_event("CONDITION_REMOVED","resource:lee_jia.lightning_charge",actor_id=LEE,target_ids=(target.entity_id,),payload={"instance_id":instance_id,"reason":reason})
            self._synchronize_lightning_charge_resource(self.state.actors[LEE])

    def _remove_lightning_charge_zone(self,zone:ZoneState,reason:str) -> None:
        if zone.active:
            zone.active=False
            self._append_event("ZONE_REMOVED","resource:lee_jia.lightning_charge",actor_id=LEE,payload={"zone_id":zone.zone_id,"reason":reason})
            self._synchronize_lightning_charge_resource(self.state.actors[LEE])

    def _expire_all_lightning_charges(self,lee:ActorState) -> None:
        for target in self.state.actors.values():
            for iid,c in list(target.conditions.items()):
                if c.condition_id.startswith("condition:lee_jia.lightning_charge."):
                    self._remove_lightning_charge_condition(target,iid,"START_OF_LEE_NEXT_TURN")
        for zone in list(self.state.zones.values()):
            if zone.active and zone.trigger_profile.get("kind")=="CHARGE_SPACE":self._remove_lightning_charge_zone(zone,"START_OF_LEE_NEXT_TURN")
        self._synchronize_lightning_charge_resource(lee)

    def _expire_for_checkpoint(self,checkpoint:str,actor_id:str) -> None:
        actor=self.state.actors[actor_id]
        if checkpoint=="START_OF_TURN" and actor_id==LEE:
            self._expire_all_lightning_charges(actor)
        if checkpoint=="START_OF_TURN" and actor_id==BAI:
            for zone in self.state.zones.values():
                if zone.active and zone.owner_id==BAI and zone.trigger_profile.get("kind")=="SEA_RISEN":
                    zone.active=False
                    self._append_event("ZONE_REMOVED",zone.source_definition_id,actor_id=BAI,payload={"zone_id":zone.zone_id,"reason":"START_OF_BAI_NEXT_TURN"})
        tokens={
            "START_OF_TURN":{"START_OF_SELF_NEXT_TURN","START_OF_TARGET_NEXT_TURN",f"START_OF_{'BAI' if actor_id==BAI else 'LEE' if actor_id==LEE else 'LING' if actor_id==LING else 'AN'}_NEXT_TURN"},
            "END_OF_TURN":{"END_OF_CURRENT_TURN","END_OF_TARGET_NEXT_TURN_OR_CONSUMED",f"END_OF_{'BAI' if actor_id==BAI else 'LEE' if actor_id==LEE else 'LING' if actor_id==LING else 'AN'}_NEXT_TURN"},
        }[checkpoint]
        for target in self.state.actors.values():
            for iid,c in list(target.conditions.items()):
                if c.expires_on in tokens and (c.source_actor_id==actor_id or target.entity_id==actor_id):
                    del target.conditions[iid]
                    if c.condition_id=="condition:ling_qi.mirror_trace_window":
                        before=target.resources.get("resource:ling_qi.mirror_trace",0);target.resources["resource:ling_qi.mirror_trace"]=0
                        self._append_event("RESOURCE_EXPIRED","resource:ling_qi.mirror_trace",actor_id=target.entity_id,payload={"before":before,"after":0})
                    if c.condition_id=="condition:bai_meizhen.moon_sea_radiance_window":
                        before=target.resources.get("resource:bai_meizhen.moon_sea_radiance",0);target.resources["resource:bai_meizhen.moon_sea_radiance"]=0
                        self._append_event("RESOURCE_EXPIRED","resource:bai_meizhen.moon_sea_radiance",actor_id=target.entity_id,payload={"before":before,"after":0})
                    self._append_event("CONDITION_REMOVED",SYSTEM_EXPIRATION,actor_id=actor_id,target_ids=(target.entity_id,),payload={"instance_id":iid,"condition_id":c.condition_id,"checkpoint":checkpoint})
            for mid,m in list(target.modifiers.items()):
                if m.expires_on in tokens and (m.source_actor_id==actor_id or target.entity_id==actor_id or m.expires_on=="END_OF_CURRENT_TURN"):
                    del target.modifiers[mid];self._append_event("MODIFIER_REMOVED",SYSTEM_EXPIRATION,actor_id=actor_id,target_ids=(target.entity_id,),payload={"modifier_id":mid,"checkpoint":checkpoint})

    def _intent_error(self,code:str,explanation:str,intent:ActionIntent):
        return error(code,explanation,phase="INTENT_VALIDATION",subsystem="GATE2_ENGINE",entity_id=intent.actor_id,recommended_action="Regenerate legal candidates from the current state and select one exact candidate.",recovery=RecoveryDisposition.RETRY,details={"intent_id":intent.intent_id,"candidate_id":intent.candidate_id,"state_version":intent.state_version})

    # ------------------------------------------------------------------
    # Canonical export
    # ------------------------------------------------------------------
    def export(self) -> RuntimeExport:
        final_state=self.state.model_dump(mode="json",by_alias=True)
        event_docs=[e.model_dump(mode="json") for e in self.events]
        return RuntimeExport(
            final_state=final_state,
            events=tuple(self.events),
            rolls=tuple(self.rolls),
            canonical_state_sha256=canonical_sha256(final_state),
            canonical_event_log_sha256=canonical_sha256(event_docs),
        )
