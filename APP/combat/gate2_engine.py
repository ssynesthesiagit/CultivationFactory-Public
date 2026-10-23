from __future__ import annotations

from .relations import relation, ALLY, ENEMY

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

    # General lifecycle capability; subclasses that dispatch turn_start while
    # recording TURN_STARTED opt out of the initialization fallback.
    turn_start_via_events = False
    # The candidate_allowed hook is honored here unless a subclass applies it in
    # its own generation pass (Gate 4 does, together with availability journaling).
    applies_plugin_candidate_vetoes = True

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
        typed_bundles: tuple[dict[str, Any], ...] = (),
        battlefield: dict[str, Any] | None = None,
    ):
        self.source_root = Path(source_root)
        # A Factory test fight may use its own arena (saved with the match).
        self.battlefield_document = copy.deepcopy(battlefield) if battlefield else None
        self.grid = SquareGrid(battlefield) if battlefield else SquareGrid.load(self.source_root / "combat_gate1/generated/Battlefield.json")
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
        # Compiled Factory characters (combat/factory_compiler.py).
        self.typed_actor_ids: set[str] = set()
        self.typed_bundle_documents: tuple[dict[str, Any], ...] = tuple(typed_bundles)
        # Passive/reaction building blocks per Factory fighter (combat/typed_reactions.py).
        self.typed_reaction_rows: dict[str, list[dict[str, Any]]] = {}
        self.typed_passive_rows: dict[str, list[dict[str, Any]]] = {}
        # Summoned creatures and companions, by creature id (combat/summons.py).
        self.summon_records: dict[str, dict[str, Any]] = {}
        self._summon_skip = False
        for bundle in typed_bundles:
            from .factory_compiler import register_bundle
            actor_id = register_bundle(self.actor_templates, self.action_catalog, bundle)
            self.typed_actor_ids.add(actor_id)
            self.typed_reaction_rows[actor_id] = list(bundle.get("typed_reactions") or [])
            self.typed_passive_rows[actor_id] = list(bundle.get("typed_passives") or [])
            if bundle.get("summons"):
                from . import summons
                summons.register(self, bundle)
        supplied_footprints = actor_footprints or ACTOR_FOOTPRINTS
        self.actor_footprints: dict[str, ActorFootprintDefinition] = {}
        for actor_id in self.actor_templates:
            definition = supplied_footprints.get(actor_id)
            if actor_id in self.summon_records and not (actor_footprints and actor_id in actor_footprints):
                definition = self.__dict__.get('_summon_footprints', {}).get(actor_id)
            if definition is None and (actor_id in self.runtime_actor_ids or actor_id in self.typed_actor_ids):
                from .footprints import native_actor_footprint
                definition = native_actor_footprint(actor_id, self.actor_templates[actor_id].size_category)
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
        self.roller.before_d20 = self._prepare_d20
        self.roller.after_d20 = self._rewrite_d20
        if genesis_setup:
            self._apply_genesis_setup(genesis_setup)
        # Buffs each fighter cast before the fight (owner 2026-09-29, combat/prefight.py): cast as the match is made, so
        # they are part of its genesis and a saved fight keeps them.
        if any((bundle.get("prefight") or {}).get("picks") for bundle in typed_bundles):
            from . import prefight

            prefight.cast_all(self)

        from . import ext
        ext.run("match_start", self)


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
        state = getattr(self, "state", None)
        current = state.actors.get(actor_id) if state is not None else None
        if current is not None and current.transformed_size_category is not None:
            from .dynamic_size import shape
            return shape(definition, current.transformed_size_category)
        return definition

    def _actor_cells(
        self,
        actor: ActorState,
        position: Position | None = None,
    ) -> tuple[tuple[int, int], ...]:
        return self._footprint(actor).occupied_cells(position or actor.position)

    def _actor_volume(self, actor: ActorState, position: Position | None = None):
        """Occupied 3D cells; _actor_cells remains the documented map projection."""
        from .space import volume
        return volume(position or actor.position, self._footprint(actor))

    def _vertical_overlap(self, actor: ActorState, other: ActorState, position: Position | None = None) -> bool:
        z = (position or actor.position).z
        if z == other.position.z:
            return True
        return (z < other.position.z + self._footprint(other).width_cells
                and other.position.z < z + self._footprint(actor).width_cells)

    def _occupied_volumes_except(self, actor_id: str, *, observed: bool = False, ignore_actor_ids=()):
        """Occupancy for a native creature/object body; observed queries need a creature."""
        from .target_knowledge import actors_for, knowledge
        from .space import point
        actor = self.state.actors.get(actor_id)
        if actor is None and (observed or actor_id not in self.state.objects):
            raise ValueError("Observed occupancy requires a known creature; actual occupancy requires a native subject")
        occupied = set()
        if observed:
            for saved in list(actor.turn_flags.get('unseen_blockers', {}).values()) + list(actor.turn_flags.get('unseen_contact_cells', [])):
                occupied.add(point(Position.model_validate(saved)))
        others = actors_for(self, actor) if observed else self.state.actors.values()
        for other in others:
            if not other.active or not self._on_battlefield(other) or other.entity_id == actor_id or other.entity_id in ignore_actor_ids or (actor is not None and self._shared_occupancy_pair(actor_id, other.entity_id)):
                continue
            known = knowledge(self, actor, self.state.actors[other.entity_id]) if observed else None
            if known is None or known.mode != 'LAST_OBSERVED':
                occupied.update(self._actor_volume(other))
        return occupied

    def _summons_of(self, actor: ActorState, group: str) -> list[ActorState]:
        from . import summons
        return summons.owned_by(self, actor.entity_id, group)

    def _summons_commandable(self, actor: ActorState, action: ActionDefinition) -> bool:
        from . import summons
        return bool(summons.commandable(self, actor, action.parameters["summon_command"]))

    def _on_battlefield(self, actor: ActorState) -> bool:
        """Pure opt-in spatial presence; life/initiative remain independent."""
        from . import ext
        return not ext.any_false("battlefield_presence", self, actor)

    def _occupied_cells_except(self, actor_id: str, *, observed: bool = False) -> set[tuple[int, int]]:
        occupied: set[tuple[int, int]] = set()
        if observed:
            viewer = self.state.actors[actor_id]
            low, high = viewer.position.z, viewer.position.z + self._footprint(viewer).width_cells
            occupied.update((position['x'], position['y']) for position in
                            viewer.turn_flags.get('unseen_blockers', {}).values() if low <= position.get('z', 0) < high)
            occupied.update((position['x'], position['y']) for position in
                            viewer.turn_flags.get('unseen_contact_cells', []) if low <= position.get('z', 0) < high)
        from .target_knowledge import actors_for
        actors = actors_for(self, self.state.actors[actor_id]) if observed else self.state.actors.values()
        for other in actors:
            if other.active and self._on_battlefield(other) and other.entity_id != actor_id and not self._shared_occupancy_pair(actor_id, other.entity_id):
                if not self._vertical_overlap(self.state.actors[actor_id], other):
                    continue
                from .target_knowledge import knowledge
                known = knowledge(self, self.state.actors[actor_id], self.state.actors[other.entity_id]) if observed else None
                if known is not None and known.mode == 'LAST_OBSERVED':
                    continue  # a remembered square is a guess, not confirmed occupancy
                else:
                    occupied.update(self._actor_cells(other))
        return occupied

    def _shared_occupancy_pair(self, left_id: str, right_id: str):
        """A validated mount pair or explicit live sharing relationship waives mutual collision."""
        from . import ext

        left, right = self.state.actors[left_id], self.state.actors[right_id]
        if not left.active or not right.active or left_id == right_id:
            return None
        if any(reply is True for reply in ext.run_strict('shared_space', self, left, right)):
            return tuple(sorted((left, right), key=lambda a: len(self._actor_volume(a))))
        for pair in ext.run("shared_occupancy", self, left, right):
            if not isinstance(pair, dict) or {pair.get("rider_id"), pair.get("mount_id")} != {left_id, right_id}:
                continue
            rider, mount = self.state.actors[pair["rider_id"]], self.state.actors[pair["mount_id"]]
            if len(self._actor_cells(rider)) < len(self._actor_cells(mount)):
                return rider, mount
        return None

    def _distance_actor_to_actor(
        self,
        actor: ActorState,
        target: ActorState,
        *,
        actor_position: Position | None = None,
        target_position: Position | None = None,
    ) -> int:
        cells = self._actor_volume if (actor_position or actor.position).z or (target_position or target.position).z else self._actor_cells
        return self.grid.distance_between_cell_sets_ft(
            cells(actor, actor_position),
            cells(target, target_position),
        )

    def _distance_actor_to_cell(
        self,
        actor: ActorState,
        cell: Position,
        *,
        actor_position: Position | None = None,
    ) -> int:
        cells = self._actor_volume if (actor_position or actor.position).z or cell.z else self._actor_cells
        return self.grid.distance_between_cell_sets_ft(
            cells(actor, actor_position),
            (cell,),
        )

    def _effect_cells(self, actor):
        from .action_geometry import cells
        return cells(self, actor)

    def _effect_volume(self, actor):
        from .action_geometry import volume
        return volume(self, actor)

    def _effect_distance(self, actor, target):
        from .action_geometry import distance
        return distance(self, actor, target)

    def _effect_distance_to_cell(self, actor, cell):
        return self.grid.distance_between_cell_sets_ft(self._effect_volume(actor), (cell,))

    def _line_of_sight_actor_to_actor(
        self,
        actor: ActorState,
        target: ActorState,
    ) -> bool:
        from .shot_geometry import sight
        alternate = sight(self, actor, target)
        if alternate is not None:
            return alternate
        from .action_geometry import point
        elevated = point(self, actor).z or target.position.z or self.grid.finite_heights
        cells = self._actor_volume if elevated else self._actor_cells
        return self.grid.line_of_sight_between_cell_sets(
            self._effect_volume(actor) if elevated else self._effect_cells(actor),
            cells(target),
            obscured_cells=self._obscured_cells(),
        )

    def _line_of_sight_actor_to_cell(
        self,
        actor: ActorState,
        cell: Position,
    ) -> bool:
        from .action_geometry import point
        elevated = point(self, actor).z or cell.z or self.grid.finite_heights
        return self.grid.line_of_sight_between_cell_sets(
            self._effect_volume(actor) if elevated else self._effect_cells(actor),
            (cell,),
            obscured_cells=self._obscured_cells(),
        )

    def _cover_bonus_actor_to_actor(self, actor: ActorState, target: ActorState) -> int:
        from .shot_geometry import reduce_cover
        return reduce_cover(self, actor, target, self._raw_cover_bonus_actor_to_actor(actor, target))

    def _raw_cover_bonus_actor_to_actor(self, actor: ActorState, target: ActorState) -> int:
        from .shot_geometry import source_cells
        from .action_geometry import point
        cells = self._actor_volume if point(self, actor).z or target.position.z or self.grid.finite_heights else self._actor_cells
        from .effect_cover import terrain_bonus
        return terrain_bonus(self, source_cells(self, actor, target), cells(target))

    def cover_from(self, origin_cells, source_actor_id, target, *, purpose='effect', target_cells=None):
        """Pure shared cover query from explicit cells; see ext's spatial-save contract."""
        from .effect_cover import query
        return query(self, origin_cells, source_actor_id, target, purpose=purpose, target_cells=target_cells)

    def _footprint_intersects(
        self,
        actor: ActorState,
        cells: Iterable[Position | tuple[int, int]],
        *,
        position: Position | None = None,
    ) -> bool:
        from .space import point
        return bool(set(self._actor_volume(actor, position)) & {point(cell) for cell in cells})

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
                size_category=template.size_category,
                ai_tier=template.ai_tier or "TRICKY",
                creature_types=template.creature_types,
                team_id=str(team_overrides.get(entity_id, template.team_id)),
                primary_combatant=template.primary_combatant, owner_id=template.owner_id,
                projection_sha256=template.projection_sha256, armor_class=template.armor_class,
                maximum_hp=template.maximum_hp, current_hp=template.maximum_hp, position=pos,
                speed_ft=template.speed_ft, movement_remaining_ft=template.speed_ft,
                fly_speed_ft=template.fly_speed_ft, climb_speed_ft=template.climb_speed_ft, hover=template.hover,
                initiative_bonus=template.initiative_bonus, dexterity_score=template.dexterity_score,
                strength_score=template.strength_score,
                proficiency_bonus=template.proficiency_bonus, saving_throws=dict(template.saving_throws),
                resources={r.resource_id: r.initial for r in template.resources},
                resource_maximums={r.resource_id: r.maximum for r in template.resources},
                action_ids=template.action_ids, reaction_ids=template.reaction_ids,
                passive_ids=template.passive_ids if entity_id in self.runtime_actor_ids else (),
                augment_ids=template.augment_ids if entity_id in self.runtime_actor_ids else (),
                damage_resistances=template.damage_resistances if entity_id in self.runtime_actor_ids else (),
            )
        init_rows: list[tuple[int, int, int, str]] = []
        initiative_rolls: list[RollRecord] = []
        for entity_id in selected_primary:
            actor = actors[entity_id]
            roll = self.roller.d20(modifier=actor.initiative_bonus, actor_id=entity_id, reason="INITIATIVE")
            self._record_roll(roll)
            initiative_rolls.append(roll)
            init_rows.append((roll.total, actor.initiative_bonus, actor.dexterity_score, entity_id))
        init_rows.sort(key=lambda row: (-row[0], -row[1], -row[2], row[3]))
        order = [row[3] for row in init_rows]
        if self.summon_records:
            from . import summons  # each summoner's creatures act right after it (owner 2026-09-27)
            summons.add_to_match(self, actors, order, team_overrides)
        # The accepted Gate 2 identity is seed + roster; teams are part of it only where a fighter's team differs from
        # its own (a dynamic roster), so the retained fight keeps its match id (owner-approved repair, 2026-09-26).
        teams = {entity_id: team for entity_id, team in sorted(team_overrides.items())
                 if entity_id in actors and team != self.actor_templates[entity_id].team_id}
        from .relation_models import Relations
        relations = Relations.model_validate(self._roster_setup['relations']) if self._roster_setup.get('relations') else None
        identity = {"seed": seed, "actors": sorted(actors), **({"teams": teams} if teams else {}),
                    **({'relations': relations.model_dump(mode='json')} if relations is not None else {})}
        state = MatchState(
            match_id=f"match:{canonical_sha256(identity)[:24]}",
            match_seed=seed, gate1_registry_snapshot_sha256=GATE1_REGISTRY_SHA256,
            mechanics_lock_sha256=self.mechanics_lock_sha256,
            universal_defaults_lock_sha256=self.universal_defaults_lock_sha256,
            initiative_order=order, current_actor_id=order[0],
            actors=actors, maximum_rounds=maximum_rounds, relations=relations,
            rules=dict(self._roster_setup.get("rules") or {}),
            # Initiative is rolled before the state exists (_record_roll cannot move its cursor yet): without this the
            # sealed state says 0 rolls were made, and recovery of a failed first commit re-rolls from the wrong point.
            roll_counter=self.roller.counter,
        )
        self.state = state
        # Transactional initialization sees the complete roster before any
        # observation, setup task or first-turn trigger. Absent providers are inert.
        from . import ext
        self._initial_turn_hooks_requested = any(
            reply is True for reply in ext.run_strict("match_initialize", self))
        battlefield = self.battlefield_document or json.loads((self.source_root / "combat_gate1/generated/Battlefield.json").read_text(encoding="utf-8"))
        self._append_event("MATCH_CREATED", SYSTEM_MATCH, payload={
            **({"Cui_first_class": True} if CUI in actors else {}),
            "actors": sorted(actors), "battlefield_id": battlefield.get("stable_id"), "match_id": state.match_id,
            **({"rules": dict(state.rules)} if state.rules else {}),
        })
        from .target_knowledge import observe
        observe(self)
        # The creation record the accepted Gate 2 run kept: each initiative roll, then round 1.
        for roll in initiative_rolls:
            self._append_event("INITIATIVE_ROLLED", SYSTEM_INITIATIVE, actor_id=roll.actor_id, payload=roll.model_dump(mode="json"))
        from .fight_setup import collect
        self.state.setup_tasks = collect(self)
        if self.state.setup_tasks:
            return self.state
        self._append_event("ROUND_STARTED", SYSTEM_TURN, payload={"round": self.state.round_number})
        self._system_start_turn(initial=True)
        return self.state

    @contextmanager
    def _transaction(self, source_definition_id: str, intent_id: str, actor_id: str):
        from .ext import ControllerPause

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
            from .paid_relocation import transaction
            with transaction(self, self.state.actors.get(actor_id), source_definition_id):
                yield transaction_id
                from .falling import settle
                settle(self, source_definition_id)
                # A general post-resolution receipt boundary, including turn
                # effects and final falling, still inside rollback/choice scope.
                self._run_final_riders('transaction_settled', self, source_definition_id,
                    actor_id, getattr(self, '_active_intent', None), state_before.event_sequence)
                from .target_knowledge import observe
                observe(self)
                self._assert_invariants()
                self.state.state_version = self._transaction_result_version
                self.state.roll_counter = self.roller.counter
        except (Exception, ControllerPause):
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
        _ended_effect: dict[str, Any] | None = None,
    ) -> CombatEvent:
        if not source_definition_id:
            raise ValueError("all events require source_definition_id")
        target_ids = tuple(target_ids)
        if event_type == 'MOVEMENT_COMMITTED' and actor_id in self.state.actors:
            from .target_knowledge import located
            mover = self.state.actors[actor_id]
            sides = {viewer.team_id for viewer in self.state.actors.values()
                     if relation(self, viewer, mover) == ALLY or located(self, viewer, mover)}
            payload = {**(payload or {}), 'observed_by': sorted(sides)}
        if event_type == "HEALING_APPLIED":
            for target_id in target_ids:
                healed = self.state.actors.get(target_id)
                from .typed_executor import healing_denied
                if healed is not None and healing_denied(healed):
                    # Some native healers commit HP directly, so the recorded
                    # healing checkpoint must enforce a live area restriction too.
                    before = int((payload or {}).get('before', healed.current_hp))
                    healed.current_hp = min(healed.current_hp, before)
                    payload = {**(payload or {}), 'after': healed.current_hp,
                               'blocked_log': f'{healed.display_name} cannot regain Hit Points while this effect applies.'}
                if healed is not None and healed.life_state is not None and healed.current_hp > 0:
                    self._set_life_state(healed, None, source_definition_id)
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
        if event_type == "REACTION_RESOLVED":
            from . import ext
            ext.run("reaction_resolved", self, event)
        from .paid_relocation import observe_falls
        observe_falls(self)
        from . import maximum_hp
        maximum_hp.on_event(self, event)
        from .prepared_actions import on_event
        on_event(self, event)
        if event_type in {"CONDITION_APPLIED", "CONDITION_REMOVED"}:
            from .dynamic_size import sync
            sync(self, source_definition_id)
        if event_type in {"CONDITION_APPLIED", "CONDITION_REMOVED", "MODIFIER_APPLIED", "MODIFIER_REMOVED", "TURN_STARTED", "ROUND_STARTED", "ACTOR_DEFEATED", "LIFE_STATE_CHANGED"}:
            from .falling import settle
            settle(self, source_definition_id)
        if event_type == 'CONDITION_REMOVED':
            from .movement_budget import condition_removed
            condition_removed(self, event, _ended_effect)
        from .state_events import dispatch
        dispatch(self, event)
        from .effect_endings import dispatch as dispatch_ending, is_ending_event
        if is_ending_event(self, event):
            dispatch_ending(self, event, _ended_effect)
        observe_falls(self)
        return event

    def _record_roll(self, roll: RollRecord) -> None:
        self.rolls.append(roll)
        if hasattr(self, "state"):
            self.state.roll_counter = self.roller.counter

    def _prepare_d20(self, request):
        """Transactional pre-draw numeric contributions, then fixed-natural consent.

        Both documented pre-roll seams run here, in order. ``before_d20_bonus``
        providers contribute integers that are folded into the request modifier
        before anything is drawn; ``before_d20`` providers (roll_checkpoints.
        prepare_d20) may then consent to a fixed natural result and return a
        prepared RollRecord. Returning None means "draw ordinarily", which is
        exactly what happens when no provider contributes anything, so a fight
        with neither seam registered rolls identically to main.
        """
        from . import ext
        from .roll_checkpoints import prepare_d20
        prepared = dict(request)
        bonus = 0
        for contribution in ext.run_strict("before_d20_bonus", self, dict(request), self._active_intent):
            if type(contribution) is not int:
                raise ValueError("before_d20_bonus requires an integer")
            bonus += contribution
        if bonus:
            prepared["modifier"] += bonus
        fixed = prepare_d20(self, prepared)
        if fixed is not None:
            return fixed
        if bonus:
            return self.roller.raw_d20(**prepared)
        return None

    def _rewrite_d20(self, roll: RollRecord) -> RollRecord:
        from .roll_checkpoints import rewrite_d20
        from .roll_reasons import attach
        return attach(self, rewrite_d20(self, roll))

    # ------------------------------------------------------------------
    # Turn lifecycle
    # ------------------------------------------------------------------
    def _system_start_turn(self, *, initial: bool = False) -> None:
        actor = self.state.actors[self.state.current_actor_id]
        actor.turns_started += 1
        from . import ext
        ext.run_strict('turn_boundary_start', self, actor)
        # A boundary subscriber may end combat before this turn begins.
        if self.state.terminal_result is not None:
            return
        from .turn_uses import reset_at_turn_start
        reset_at_turn_start(self)
        actor.action_available = actor.active and actor.life_state in (None, "CONSCIOUS")
        actor.bonus_action_available = actor.active and actor.life_state in (None, "CONSCIOUS")
        actor.reaction_available = actor.active and actor.life_state in (None, "CONSCIOUS")
        actor.movement_remaining_ft = 0 if actor.life_state in ("DYING", "STABLE") else self._effective_speed(actor)
        actor.turn_flags = {
            key: value for key, value in actor.turn_flags.items()
            if "_round_" in key or key.startswith("once_per_round:")
        }
        from .flight import begin_turn
        begin_turn(self, actor)
        self._commanded_cui_this_turn = False
        from .movement_budget import start_turn
        self._expire_for_checkpoint("START_OF_TURN", actor.entity_id)
        start_turn(self, actor)
        self._append_event("TURN_STARTED", SYSTEM_TURN, actor_id=actor.entity_id, payload={
            "round": self.state.round_number,
            "slot": self.state.current_slot_index,
            "initial": initial,
        })
        # Explicit initialization can require first-turn triggers in Gate2
        # genesis before controller upgrade. Event-delivering engines already
        # dispatched them, and ordinary fights retain their existing genesis.
        if (initial and getattr(self, '_initial_turn_hooks_requested', False)
                and not self.turn_start_via_events):
            ext.run("turn_start", self, actor)
        if getattr(self, "typed_actor_ids", None) and self.state.terminal_result is None:
            from . import typed_reactions  # a turn begins: marked foes, allies in an aura, "initiative is rolled" (R5)
            typed_reactions.on_turn_start(self, actor)
        if actor.active:
            self._resolve_zone_triggers(actor, checkpoint="AT_TURN_START")
        if actor.entity_id == BAI and not actor.active and self.state.actors[CUI].active:
            self._cui_guard_and_rescue_default()
        if self.summon_records and self.state.terminal_result is None:
            from . import summons  # an uncommanded or absent creature's turn passes by itself
            self._summon_skip = summons.on_turn_start(self, actor)

    def end_turn(self, intent_id: str = "system:end-turn") -> None:
        if self.state.setup_tasks:
            raise ValueError('Finish fight setup before ending a turn.')
        actor_id = self.state.current_actor_id
        with self._transaction(SYSTEM_TURN, intent_id, actor_id):
            actor = self.state.actors[actor_id]
            if actor_id == LING:
                self._resolve_zone_triggers_for_owner_end(LING)
            if actor_id == BAI and actor.active and self.state.actors[CUI].active and not self._commanded_cui_this_turn:
                self._cui_default_dodge()
            self._expire_for_checkpoint("END_OF_TURN", actor_id)
            self._append_event("TURN_ENDED", SYSTEM_TURN, actor_id=actor_id, payload={"round": self.state.round_number})
            while True:
                self.state.current_slot_index += 1
                if self.state.current_slot_index >= len(self.state.initiative_order):
                    self.state.current_slot_index = 0
                    self.state.round_number += 1
                    if self.state.round_number > self.state.maximum_rounds:
                        self._end_match(TerminalKind.DRAW_DURATION, None, "Maximum round limit reached.")
                        return
                    self._append_event("ROUND_STARTED", SYSTEM_TURN, payload={"round": self.state.round_number})
                self.state.current_actor_id = self.state.initiative_order[self.state.current_slot_index]
                self._summon_skip = False
                from .turn_decisions import omits_turn
                if omits_turn(self, self.state.current_actor_id):
                    # A nominal initiative slot still owns deadlines, but is not
                    # a creature turn: no resets, saves, menus or turn callbacks.
                    from .ext.effect_durations import nominal_slot
                    nominal_slot(self, self.state.actors[self.state.current_actor_id])
                    if self.state.terminal_result is not None:
                        return
                    continue
                self._system_start_turn()
                from .turn_decisions import passes_without_decision
                if (not self._summon_skip and not passes_without_decision(self, self.state.current_actor_id)
                        or self.state.terminal_result is not None):
                    break
                # Keep normal boundaries for expiry/death saves, then pass a
                # creature's turn if it cannot decide or its summon rule passes it.
                self._summon_skip = False
                skipped = self.state.current_actor_id
                self._expire_for_checkpoint("END_OF_TURN", skipped)
                self._append_event("TURN_ENDED", SYSTEM_TURN, actor_id=skipped, payload={"round": self.state.round_number})

    # ------------------------------------------------------------------
    # Candidate generation and intent validation
    # ------------------------------------------------------------------
    def action_availability(self, actor_id: str, source_id: str) -> dict:
        """Pure explanation from the actual current candidate-generation checks."""
        from .action_legality import query
        return query(self, actor_id, source_id)

    def action_target_availability(self, actor_id: str, source_id: str, target_id: str) -> dict:
        """Pure explanation for one exact source and target pair."""
        from .action_legality import query_target
        return query_target(self, actor_id, source_id, target_id)

    def action_target_availabilities(self, actor_id: str, source_target_pairs) -> dict:
        """The same target-scoped explanations, sharing one isolated candidate pass."""
        from .action_legality import query_targets
        return query_targets(self, actor_id, source_target_pairs)

    def action_availabilities(self, actor_id: str, source_ids) -> dict:
        """The same independent explanations, sharing one read-only query pass."""
        from .action_legality import query_many
        return query_many(self, actor_id, source_ids)

    def legal_candidates(self) -> tuple[LegalCandidate, ...]:
        return self._generate_legal_candidates()

    def _generate_legal_candidates(self, intent=None, *, sources=None) -> tuple[LegalCandidate, ...]:
        """Native generator, optionally narrowed to an intent's identity hints.

        This is fresh generation, never an issued-candidate cache. Pending/setup
        choices retain full generation. All final execution checks still apply.
        """
        if self.state.terminal_result is not None:
            return ()
        actor = self.state.actors[self.state.current_actor_id]
        if self.state.setup_tasks:
            from .fight_setup import SOURCE
            return (self._candidate(CandidateKind.ACTION, actor, SOURCE, 'Finish fight setup'),)
        if self.state.pending_resolution is not None:
            actor = self.state.actors[self.state.pending_resolution.actor_id]
            return self._pending_candidates(actor)
        if not actor.active or actor.life_state in ("DYING", "STABLE"):
            return (self._candidate(CandidateKind.END_TURN, actor, SYSTEM_TURN, "End inactive turn"),)
        candidates: list[LegalCandidate] = []
        if sources is None and (intent is None or self._identity_matches(intent, CandidateKind.MOVE, actor, SYSTEM_MOVE)):
            candidates.extend(self._movement_candidates(actor, intent=intent))
        from . import posture
        stand_cost = posture.standing_cost(self, actor)
        if sources is None and stand_cost is not None:
            ordinary_cost = posture.standing_cost(self, actor, include_offers=False, check_budget=False)
            candidates.append(self._candidate(CandidateKind.ACTION, actor, posture.SOURCE,
                f'Stand up — spend {stand_cost} feet of movement; end Prone',
                metadata={'standing_cost_ft': stand_cost,
                          'standing_ordinary_cost_ft': ordinary_cost,
                          'standing_discount_conditional': ordinary_cost is not None and stand_cost < ordinary_cost}))
        from .typed_executor import condition_rules
        acting = not any(row.get("no_actions") for row in condition_rules(actor))
        if acting and (sources is None or any(source not in actor.action_ids for source in sources)):
            from .prepared_actions import candidates as prepared_candidates
            # Supplemental catalog actions enforce their own Action/Bonus/free
            # economy. Ready declarations retain their separate Action gate.
            candidates.extend(c for c in prepared_candidates(self, actor)
                              if sources is None or c.source_definition_id in sources)
        for source_id in actor.action_ids if acting else ():
            if sources is not None and source_id not in sources:
                continue
            action = self.action_catalog[source_id]
            candidates.extend(self._action_candidates(actor, action, intent=intent))
        for source_id in ("system:combat.dodge", "system:combat.dash", "system:combat.disengage") if acting else ():
            if sources is not None and source_id not in sources:
                continue
            candidates.extend(self._action_candidates(actor, self.action_catalog[source_id], intent=intent))
        from .hold_position import used as hold_used
        if sources is None and not hold_used(actor):
            candidates.append(self._candidate(CandidateKind.HOLD_POSITION, actor, "system:combat.hold_position", "Hold position"))
        if sources is None:
            candidates.append(self._candidate(CandidateKind.END_TURN, actor, SYSTEM_TURN, "End turn"))
        # The general candidate_allowed contract ("False to leave that choice
        # out of what the fighter is offered now, player and AI alike") applies
        # to this engine too. Without it, options whose own provider says they
        # are dormant (e.g. a scene check with no live relevance provider)
        # stayed in every Gate-2 seat's menu; the AI then picked such a free,
        # no-progress action forever and never ended its turn.
        from . import ext
        if candidates and self.applies_plugin_candidate_vetoes and ext.has("candidate_allowed"):
            kept = []
            for candidate in candidates:
                if candidate.metadata.get("placement_picker") or candidate.metadata.get("lazy_action"):
                    # A lazy action header is not an issued choice: its vetoes run on the
                    # expansion (ext.py "Human lazy discovery") and again at commit.
                    kept.append(candidate)
                    continue
                owner = self.state.actors.get(candidate.actor_id) or actor
                if not ext.any_false("candidate_allowed", self, owner, candidate,
                                     self.action_catalog.get(candidate.source_definition_id)):
                    kept.append(candidate)
            candidates = kept
        from .movement_routes import ordered_candidates
        return ordered_candidates(candidates)

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
                    and relation(self, a, actor) == ENEMY
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

    def _dropped_weapons_near(self, actor: ActorState) -> list[tuple[ActorState, str]]:
        """Other creatures' dropped weapons within 5 ft of this actor: (owner, condition instance id), nearest first."""
        found = []
        for owner in self.state.actors.values():
            if owner.entity_id == actor.entity_id:
                continue
            for iid, c in owner.conditions.items():
                spot = c.data.get("dropped_at")
                if c.data.get("disables_action") and isinstance(spot, dict) and self._within_reach_of_cell(actor, spot):
                    found.append((self._distance_actor_to_cell(actor, Position(x=int(spot["x"]), y=int(spot["y"]))), iid, owner))
        return [(owner, iid) for _, iid, owner in sorted(found, key=lambda row: (row[0], row[1]))]

    def _within_reach_of_cell(self, actor: ActorState, cell: Any) -> bool:
        if not isinstance(cell, dict):
            return True
        return self._distance_actor_to_cell(actor, Position(x=int(cell["x"]), y=int(cell["y"]))) <= 5

    def _dragged_by(self, actor: ActorState) -> list[tuple[ActorState, int]]:
        """Creatures a typed grapple lets this actor drag, with the grapple's reach (2024 Grappled: "Movable")."""
        out = []
        for other in self.state.actors.values():
            if other.entity_id != actor.entity_id and other.active:
                grip = next((c for c in other.conditions.values() if c.condition_id == "condition:typed.grappled"
                             and c.source_actor_id == actor.entity_id and c.data.get("reach_ft") is not None), None)
                if grip is not None:
                    out.append((other, int(grip.data["reach_ft"])))
        return out

    def _drag_multiplier(self, actor: ActorState) -> int:
        """Each foot of movement costs 1 extra foot while dragging, unless the creature is two or more sizes smaller."""
        from .dynamic_size import CATEGORIES, current_category
        from .ext.effective_size import steps
        rank = CATEGORIES.index(current_category(self, actor)) + steps(self, actor, "act", {"carrying"})
        return 2 if any(CATEGORIES.index(current_category(self, other)) > rank - 2
                        for other, _ in self._dragged_by(actor)) else 1

    def _drag_along(self, actor: ActorState) -> tuple[dict[str, list[Position]], bool]:
        """Pull each grappled creature one square at a time toward its grappler until it is back within reach."""
        moved: dict[str, list[Position]] = {}
        stopped = False
        for other, reach in self._dragged_by(actor):
            for _ in range(64):
                if not actor.active or not other.active:
                    break
                if self._distance_actor_to_actor(actor, other) <= reach:
                    break
                options = [Position(x=other.position.x + dx, y=other.position.y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                           if (dx or dy) and other.position.x + dx >= 0 and other.position.y + dy >= 0]
                if actor.position.z or other.position.z:
                    from itertools import product
                    options = [Position(x=other.position.x+dx, y=other.position.y+dy, z=other.position.z+dz)
                               for dx,dy,dz in product((-1,0,1), repeat=3) if (dx or dy or dz)
                               and min(other.position.x+dx, other.position.y+dy, other.position.z+dz) >= 0]
                    legal = [cell for cell in options if self.grid.volume_step_legal(other.position, cell,
                        occupied_cells=self._occupied_volumes_except(other.entity_id), footprint=self._footprint(other))
                        and self.grid.distance_ft(cell, actor.position) < self.grid.distance_ft(other.position, actor.position)]
                else:
                    legal = [cell for cell in options if self.grid.step_legal(other.position, cell, occupied_cells=self._occupied_cells_except(other.entity_id),
                                                                                 footprint=self._footprint(other))]
                if not legal:
                    break
                best = min(legal, key=lambda cell: (self.grid.distance_ft(cell, actor.position), cell.y, cell.x))
                moved.setdefault(other.entity_id, [other.position]).append(best)
                previous = other.position
                other.position = best
                from .movement_paths import landed_forced_step
                if landed_forced_step(self, other, previous, best):
                    stopped = True
                    break
            # The mover already committed this step. A landing may stop the
            # next step, but every remaining hold must still settle this one.
            if not actor.active or not other.active or self._distance_actor_to_actor(actor, other) > reach:
                stopped = True
                for iid, condition in list(other.conditions.items()):
                    if condition.condition_id == 'condition:typed.grappled' and condition.source_actor_id == actor.entity_id:
                        del other.conditions[iid]
                        self._append_event('CONDITION_REMOVED', condition.source_definition_id,
                            actor_id=actor.entity_id, target_ids=(other.entity_id,),
                            payload={'condition_id': condition.condition_id, 'instance_id': iid,
                                     'reason': 'DRAG_CANNOT_RETAIN_HOLD'})
                        self._append_event('GM_RIDER', condition.source_definition_id,
                            actor_id=actor.entity_id, target_ids=(other.entity_id,),
                            payload={'rider': f'{actor.display_name} releases {other.display_name}: the hold cannot be maintained after this step.'})
        return moved, stopped

    def movement_explanation(self, actor_id: str, destination: Position | None = None) -> dict[str, Any]:
        """Read-only reasons for movement restrictions; never movement permission."""
        from .movement_explanations import describe
        return describe(self, actor_id, destination)

    def _movement_candidates(self, actor: ActorState, *, recorded=None, intent=None,
                             movement_grant_ft: int | None = None) -> list[LegalCandidate]:
        """Build native movement candidates with an optional independent query budget.

        ``movement_grant_ft`` replaces remaining walk/flight allowance only for
        this read-only enumeration; the commit still validates its own grant.
        """
        recorded = recorded or getattr(self, '_recorded_route_candidate', None)
        from . import flight, posture
        from .movement_costs import surcharge
        extra_cost = surcharge(self, actor)
        spatial = bool(actor.position.z or flight.profile(self, actor).speed_ft or actor.turn_flags.get("flight_movement_overrun_ft"))
        from .roof_movement import profile as climbing_profile
        if self.grid.roof_surfaces or climbing_profile(self, actor).virtual_wall:
            # Roof maps share one priced spatial route representation on the
            # ground and above it, including drag and a remaining Climb Speed.
            spatial = True
        query_budget_ft = actor.movement_remaining_ft if movement_grant_ft is None else movement_grant_ft
        if movement_grant_ft is None:
            query_budget_ft = flight.remaining(self, actor, 'walk')
        if (query_budget_ft <= 0 and not spatial and not flight.mode_credit(self, actor, 'jump')) or self._effective_speed(actor) <= 0:
            return []
        from .creature_passage import geometry
        occupied_cells, end_blocked, extra_difficult, passage = geometry(self, actor, observed=True)
        difficult = self._hostile_difficult_cells(actor) | extra_difficult
        from .voluntary_movement import edge_predicate
        restriction = edge_predicate(self, actor)
        from .movement_routes import native_selector
        from . import lazy_menu
        # Keep native path tie selection: jump run-up can depend on the route,
        # even when the table is only asking for endpoint prices.
        selector = None if recorded is not None else native_selector(self, actor)
        reachable = flight.reachable(self, actor, grant_ft=movement_grant_ft, path_selector=selector) if spatial else self.grid.reachable(
            actor.position,
            movement_ft=query_budget_ft // self._drag_multiplier(actor),
            extra_step_cost_ft=extra_cost,
            occupied_cells=occupied_cells,
            difficult_cells=difficult,
            end_blocked_cells=end_blocked,
            footprint=self._footprint(actor),
            extra_step_multiplier=posture.walking_extra(self, actor),
            path_selector=selector,
            **({'edge_allowed': restriction} if restriction is not None else {}),
        )
        from .movement_routes import merge_modes
        alternatives = []
        from .terrain_materials import profiles as material_profiles, routes as material_routes
        for capability in material_profiles(self, actor):
            merge_modes(reachable, material_routes(self, actor, capability['mode'],
                        grant_ft=movement_grant_ft, path_selector=selector), alternatives)
        if self.grid.roof_surfaces or climbing_profile(self, actor).virtual_wall:
            from .roof_movement import routes as climb_routes
            merge_modes(reachable, climb_routes(self, actor, path_selector=selector), alternatives)
        # AI seats gain the same supported high-jump landings as players. Keep
        # unsupported up-and-fall jumps manual; they do not advance an AI route.
        if posture.allows_jumping(actor):
            jumps = flight.jumps(self, actor, reachable)
            jumps.update(flight.horizontal_jumps(self, actor))
            if (getattr(self, "typed_control_modes", {}).get(actor.entity_id) in {"LOCAL_AUTO", "API_AUTO"}
                    and not any(c.data.get('jump_allow_unsupported') for c in flight.credit_rows(self, actor, 'jump'))):
                from .falling import supported
                jumps = {destination: route for destination, route in jumps.items()
                         if supported(self, actor, destination)}
            merge_modes(reachable, jumps, alternatives)
        out = []
        from . import movement_menu
        price_only = lazy_menu.active(self) and movement_menu.active()
        tactical = not price_only and actor.entity_id in getattr(self, "typed_actor_ids", set())
        from .target_knowledge import actors_for
        observed = {} if price_only else {a.entity_id: a for a in actors_for(self, actor)}
        hostiles = [a for a in observed.values() if a.active and relation(self, a, actor) == ENEMY] if tactical else []
        from .voluntary_movement import fear_sources, path_allowed
        fears = fear_sources(self, actor)
        reaction_cache = {}  # discarded after this one actor's movement query
        opportunity_cache = {}  # projected eligibility, one unchanged actor/menu only
        ranged_threats = {}  # immutable descriptors, scoped to this observed-actor query
        from . import ext
        directional_threats = ext.has('directional_cover')
        from .zones import hazard_test
        zone_hazard = None if price_only else hazard_test(self, actor)
        hazard_by_cell = {}  # one movement query, shared path prefixes only
        def dangerous(position):
            cell = (position.x, position.y, position.z)
            if cell not in hazard_by_cell:
                hazard_by_cell[cell] = zone_hazard(position)
            return hazard_by_cell[cell]
        routes = [(destination, route, False) for destination, route in reachable.items()]
        routes.extend((destination, route, True) for destination, route in alternatives
                      if recorded is None or destination != recorded.destination)
        for destination, route, route_bound in routes:
            if intent is not None and destination != intent.destination:
                continue
            path, cost = route[:2]
            mode = route[2] if len(route) > 2 else "walk"
            if extra_cost and len(route) == 2:
                cost *= self._drag_multiplier(actor)
            if recorded is not None and destination == recorded.destination:
                from .movement_routes import validate_path
                recorded_mode = recorded.metadata.get('movement_mode', 'walk')
                recorded_cost = validate_path(self, actor, recorded.canonical_path, recorded_mode)
                if recorded_cost != recorded.movement_cost_ft:
                    raise ValueError('The recorded route has a different movement cost')
                path, cost, mode = recorded.canonical_path, recorded_cost, recorded_mode
            can_jump_down = False
            if self.grid.roof_surfaces:
                from .roof_movement import valid_drop
                can_jump_down = valid_drop(self, actor, path)
                if can_jump_down and mode == "walk" and not flight.profile(self, actor).speed_ft:
                    mode = "jump_down"
            if not path_allowed(self, actor, path, sources=fears):
                continue
            # A table highlight needs prices/endpoints, not AI threat scores or
            # issued candidates. Execution/AI never enter this request scope.
            from . import movement_menu
            if (intent is None and recorded is None and movement_grant_ft is None
                    and getattr(self, 'typed_control_modes', {}).get(actor.entity_id, 'MANUAL')
                    not in {'LOCAL_AUTO', 'API_AUTO'}
                    and movement_menu.collect(self, actor, destination, path, cost, mode, can_jump_down,
                                               route_bound, passage)):
                continue
            metadata = {
                "compressed_path": [p.model_dump(mode="json") for p in self.grid.compress_path(path)],
                "reaction_exposure": self._movement_reaction_exposure(actor, path, cache=reaction_cache),
                "hazard_exposure": self._path_intersects_cells(
                    actor, path[1:], self.grid.qi_hazard
                ),
            }
            if route_bound or (recorded is not None and destination == recorded.destination
                               and recorded.metadata.get('explicit_movement_path')):
                metadata.update(explicit_movement_path=True, movement_mode=mode)
            if passage:
                metadata['creature_passage'] = passage
            if zone_hazard is not None:
                exposed = any(dangerous(position) for position in path[1:])
                metadata['zone_hazard_exposure'] = exposed
                metadata['hazard_exposure'] = metadata['hazard_exposure'] or exposed
            if mode != "walk" or (
                    self.grid.roof_surfaces and any(p.z for p in path)):
                metadata.update(movement_mode=mode, altitude_ft=destination.z * 5)
            if can_jump_down:
                metadata['can_jump_down'] = True
            if recorded is None or 'expected_opportunity_attacks' in recorded.metadata:
                from .movement_routes import threat_metadata
                if actor.entity_id in getattr(self, 'typed_actor_ids', set()):
                    metadata.update(threat_metadata(self, actor, path, cache=opportunity_cache, reactors=tuple(observed.values())))
                    if 'expected_opportunity_attacks' in metadata:
                        metadata['reaction_exposure'] = [r['actor_id'] for r in metadata['expected_opportunity_attacks']]
            if tactical and hostiles:
                # Factory fighters' AI weighs cover and being surrounded (fixture fights unchanged).
                nearest = min(hostiles, key=lambda h: self.grid.distance_ft(destination, h.position))
                from .directional_cover import tactical_cover
                from .attack_provenance import ranged_attacks
                if directional_threats and nearest.entity_id not in ranged_threats:
                    ranged_threats[nearest.entity_id] = tuple(ranged_attacks(self, nearest))
                metadata["cover_from_nearest_hostile"] = tactical_cover(
                    self, nearest, actor, destination, ranged_threats.get(nearest.entity_id))
                metadata["adjacent_hostiles"] = sum(1 for h in hostiles if self.grid.distance_ft(destination, h.position) <= 5)
            out.append(self._candidate(
                CandidateKind.MOVE, actor, SYSTEM_MOVE,
                f"{mode.replace('_', ' ').title()} to {destination.x},{destination.y} at {destination.z * 5} ft." if mode != "walk" else f"Move to {destination.x},{destination.y}",
                destination=destination,
                path=path,
                movement_cost_ft=cost,
                metadata=metadata,
            ))
        return out

    def _action_candidates(self, actor: ActorState, action: ActionDefinition, *, intent=None) -> list[LegalCandidate]:
        from . import lazy_menu
        if intent is None and lazy_menu.active(self):
            return self._action_candidates_impl(actor, action)
        from .action_geometry import activate, origins
        with activate(self, actor, action.source_definition_id, None):
            choices = [None, *origins(self, actor, action)]
        out = []
        for origin in choices:
            with activate(self, actor, action.source_definition_id, origin):
                if intent is None or any(self._identity_matches(intent, kind, actor, action.source_definition_id)
                                         for kind in (CandidateKind.ACTION, CandidateKind.BONUS_ACTION)):
                    out.extend(self._action_candidates_at_origin(actor, action, intent=intent))
        return out

    def _action_candidates_at_origin(self, actor: ActorState, action: ActionDefinition, *, intent=None) -> list[LegalCandidate]:
        from .shot_geometry import scope
        with scope(self, actor, action):
            return self._action_candidates_impl(actor, action, intent=intent)

    def _action_candidates_impl(self, actor: ActorState, action: ActionDefinition, *, intent=None) -> list[LegalCandidate]:
        from .action_legality import deny
        source = action.source_definition_id
        if action.economy == EconomyKind.ACTION and not actor.action_available:
            return deny(source, 'ACTION', 'Your action has already been used this turn.')
        if action.economy == EconomyKind.BONUS_ACTION and not actor.bonus_action_available:
            return deny(source, 'BONUS_ACTION', 'Your Bonus Action has already been used this turn.')
        if action.economy == EconomyKind.REACTION:
            # A Reaction is only offered through its own trigger window (a foe leaving reach,
            # damage application, ...), never as a primary turn intent -- for AI and human
            # seats alike. Trigger handlers pay through their reaction-spending
            # path, including any printed additional-reaction or free-use grants.
            return deny(source, 'REACTION', 'Use this Reaction when its trigger occurs; it is not an action on your turn.')
        from .primary_intents import allows_primary
        if not allows_primary(action):
            return deny(source, 'PARENT_OPTION', 'Choose this option when you use its ability; it cannot be used by itself.')
        if not self._can_pay(actor, action.costs, source_id=action.source_definition_id):
            return []
        req_condition = action.parameters.get("requires_condition")
        if req_condition and not self._has_condition(actor, req_condition):
            # Name the missing condition (SHEETAVAIL2): the sheet's greyed row, the table's hover and the
            # refusal for a click all read this sentence, so a player sees which stance is required
            # ("You must be Prone to use this.") rather than that something unnamed is missing. The name is the
            # one the condition pill already shows (combat/presentation.condition_label), so no ability keeps a
            # second spelling; an id that yields no readable name keeps the generic sentence.
            from .presentation import condition_label
            named = condition_label(req_condition)
            if named and named != 'Effect':
                return deny(source, 'REQUIRES_CONDITION', f'You must be {named} to use this.')
            return deny(source, 'REQUIRES_CONDITION', 'The required effect or stance is not active on you.')
        req_flag = action.parameters.get("requires_turn_flag")
        if req_flag and not actor.turn_flags.get(req_flag):
            return deny(source, 'REQUIRES_TURN_FLAG', 'The required earlier action or trigger has not happened this turn.')
        if any(not actor.turn_flags.get(flag) for flag in action.parameters.get("requires_turn_flags") or ()):
            return deny(source, 'REQUIRES_TURN_FLAGS', 'Complete the required earlier attacks or triggers this turn.')
        # A weapon knocked away by a typed Disarm (owner 2026-09-26): its attacks wait until it is picked up, and only
        # then is picking it up offered.
        if any(c.data.get("disables_action") == action.source_definition_id.split("#")[0] for c in actor.conditions.values()):
            return deny(source, 'WEAPON_DISABLED', 'The weapon needed for this action is unavailable; recover it before attacking with it.')
        needs_disabled = action.parameters.get("requires_disabled_action")
        if needs_disabled and not any(c.data.get("disables_action") == needs_disabled and isinstance(c.data.get("dropped_at"), dict)
                                      and self._within_reach_of_cell(actor, c.data.get("dropped_at")) for c in actor.conditions.values()):
            return deny(source, 'DROPPED_WEAPON', 'Your dropped weapon must be within 5 feet and not held by another creature.')
        if action.parameters.get("requires_dropped_nearby") and not self._dropped_weapons_near(actor):
            return deny(source, 'NO_DROPPED_WEAPON', 'There is no dropped weapon within 5 feet to pick up.')
        held = action.parameters.get("requires_held_weapon")  # another fighter's weapon this actor took
        if held and not any(c.data.get("disables_action") == held and c.data.get("held_by") == actor.entity_id
                            for other in self.state.actors.values() for c in other.conditions.values()):
            return deny(source, 'HELD_WEAPON', 'You are not holding the weapon required for this action.')
        absent = action.parameters.get("requires_absent_condition")
        if absent and self._has_condition(actor, absent):
            return deny(source, 'BLOCKING_CONDITION', 'An effect already on you prevents this action.')
        blocked_flag = action.parameters.get("blocked_by_turn_flag")
        if blocked_flag and actor.turn_flags.get(blocked_flag):
            return deny(source, 'TURN_LIMIT', 'This action or its triggering benefit has already been used this turn.')
        if any(actor.resources.get(rid, 0) < int(amount) for rid, amount in (action.parameters.get("requires_resource") or {}).items()):
            from .resource_labels import resource_name
            needs = ', '.join(f'{amount} {resource_name(rid)}' for rid, amount in action.parameters['requires_resource'].items()
                              if actor.resources.get(rid, 0) < int(amount))
            return deny(source, 'RESOURCE_PREREQUISITE', f'You must have {needs} available before using this action.')
        if action.parameters.get("requires_grappling") and not self._dragged_by(actor):
            return deny(source, 'GRAPPLE', 'You must be grappling a creature before dragging it.')
        if action.parameters.get("summon_command") and not self._summons_commandable(actor, action):
            return deny(source, 'SUMMON_COMMAND', 'No active summon of this group is within command range and still able to receive this command.')
        if action.parameters.get("summon_group") and any(
                row.active and row.summon["status"] == "present" for row in self._summons_of(actor, action.parameters["summon_group"])):
            return deny(source, 'SUMMON_PRESENT', 'A summon of this group is already present.')
        band = action.parameters.get("hp_band")  # e.g. a Painted Formation's weaker assault below half its Hit Points
        if band and (actor.current_hp * 2 > actor.maximum_hp) != (band == "above_half"):
            return deny(source, 'HP_BAND', 'This action requires you to be ' + ('above half your maximum HP.' if band == 'above_half' else 'at half your maximum HP or less.'))
        if action.source_definition_id in {"action:an_eui.paired_bi_shou_assault", "action:an_eui.first_arm"} and self._has_condition(actor, "condition:an_eui.bi_shou_primary_unusable"):
            return deny(source, 'PRIMARY_WEAPON', 'Your primary weapon is unavailable.')
        kind = CandidateKind.ACTION if action.economy == EconomyKind.ACTION else CandidateKind.BONUS_ACTION
        from . import lazy_menu
        if intent is None and lazy_menu.active(self) and lazy_menu.defer(action):
            return [lazy_menu.header(self, actor, action, kind)]
        if action.source_definition_id == "action:lee_jia.gather_charge":
            return self._gather_charge_candidates(actor, action, kind)
        if action.source_definition_id == "action:bai_meizhen.command_cui":
            return self._command_cui_candidates(actor, action, kind)
        from .recipients import allowed
        if action.target_kind in {"SELF", "SELF_OR_CELL"} and not allowed(self, actor, actor, action):
            return []
        if action.target_kind == "SELF":
            options = tuple(action.parameters.get("options", ()))
            if action.source_definition_id == "action:an_eui.ruin_tempered_armament_quick":
                options = ("PRIMARY_WEAPON", "PAIRED_WEAPONS")
            options = tuple(option for option in options if self._option_payable(actor, action.source_definition_id, option))
            return [self._candidate(kind, actor, action.source_definition_id, action.display_name, target_ids=(actor.entity_id,), option_ids=options)]
        if action.target_kind == "SELF_OR_CELL":
            options = ("SELF", "CELL")
            return [self._candidate(kind, actor, action.source_definition_id, action.display_name, target_ids=(actor.entity_id,), option_ids=options)]
        if action.target_kind == "VISIBLE_ACTIVE_PATTERN":
            patterns = [z.source_definition_id for z in self.state.zones.values() if z.active and z.owner_id != actor.entity_id]
            return [self._candidate(kind, actor, action.source_definition_id, action.display_name, option_ids=tuple(sorted(patterns)))] if patterns else deny(source, 'NO_PATTERN', 'There is no active enemy pattern to affect.')
        if action.target_kind == "CELL":
            out = []
            from . import candidate_knowledge
            from . import cell_placement
            from .targeting import aim_requires_line_of_effect, line_of_effect
            from .area_knowledge import enabled as area_knowledge_enabled, origin_allowed
            placement = cell_placement.profile(self, actor, action)
            max_cells = (action.range_ft or 0) // self.grid.square_size_ft
            radius_cells = (action.radius_ft or 0) // self.grid.square_size_ft
            from .target_knowledge import actors_for
            from itertools import product
            levels = sorted({0, actor.position.z} | {other.position.z for other in actors_for(self, actor)})
            from .placement_menu import axes
            xs, ys, zs = axes(self.grid, intent, levels)
            for y in ys:
                for x, z in product(xs, zs):
                    pos = Position(x=x, y=y, z=z)
                    if intent is not None and pos != intent.destination:
                        continue
                    # Some utility actions target an empty square. Their owner
                    # may require that automatic controllers only receive
                    # destinations the acting creature can perceive; manual
                    # player menus retain the full printed choice set.
                    if (action.parameters.get("ai_requires_perceived_destination")
                            and candidate_knowledge.active(self)
                            and not candidate_knowledge.aim_allowed(self, actor, pos, action)):
                        continue
                    if (
                        self._effect_distance_to_cell(actor, pos) <= max_cells * self.grid.square_size_ft
                        and (not aim_requires_line_of_effect(action)
                             or line_of_effect(self, actor, destination=pos))
                        and origin_allowed(self, actor, action, pos)
                    ):
                        area = None
                        if action.radius_ft is not None:
                            area = CandidateAreaProjection(
                                center=pos,
                                radius_cells=radius_cells,
                                affected_cells=self.grid.cells_in_radius(pos, radius_cells),
                            )
                        metadata = None
                        shape, safety, warning = {}, {}, ''
                        if placement is not None:
                            if not cell_placement.legal(self, actor, action, pos, placement=placement, preview=True):
                                continue
                            metadata = cell_placement.metadata(self, actor, action, placement=placement)
                        elif action.resolution_kind == "TYPED":
                            # Typed area abilities: only squares whose area catches an enemy,
                            # and the AI's damage estimate counts the enemies caught.
                            shape = (action.parameters.get("typed") or {}).get("area") or {}
                            if shape.get("size_ft"):
                                # Counted in the shape it lands in (owner 2026-09-26, step 13): a line or cone
                                # runs from the caster through this square, not a circle around it.
                                from .area_safety import preview

                                caught, safety, warning = preview(self, actor, action, pos,
                                                                  actors=candidate_knowledge.roster(self))
                            else:
                                caught = self._typed_hostiles_within(actor, pos, action.radius_ft or 0)
                            if not caught:
                                if not area_knowledge_enabled(self) and not (action.parameters.get("typed") or {}).get("zone_spec"):
                                    continue
                                # Players may legally blast a seen empty square. Knowledge-only
                                # empty-area metadata keeps the existing AI filter inert there.
                                # Cell actions that are not area effects (for example, a teleport landing)
                                # can opt out of this AI-only empty-area marker with ai_empty_area_filter=False.
                                if action.parameters.get("ai_empty_area_filter", True):
                                    metadata = {"expected_damage": 0, "hostiles_in_area": 0, "empty_area": True}
                            else:
                                metadata = {"expected_damage": int(action.parameters.get("expected_damage") or 0) * caught,
                                            "hostiles_in_area": caught}
                        if action.resolution_kind == 'TYPED' and shape.get('size_ft'):
                            metadata = {**(metadata or {}), **safety}
                        else:
                            warning = ''
                        # Estimate using observed occupants first. Empty damage
                        # areas need no additional terrain sight query.
                        if ((action.radius_ft is not None or (action.parameters.get('typed') or {}).get('area'))
                                and not candidate_knowledge.aim_allowed(self, actor, pos, action)):
                            continue
                        out.append(self._candidate(
                            kind, actor, action.source_definition_id,
                            f"{action.display_name} at {x},{y}" + (f" — {warning}" if warning else ''),
                            destination=pos, area=area, metadata=metadata,
                        ))
                        from .placement_menu import representative
                        root = representative(self, actor, action, out[-1], intent=intent)
                        if root is not None:
                            return [root]
            return out or deny(source, 'NO_AREA', 'No square within range has a clear line of effect and an eligible target or permits this area effect.')
        if action.target_kind in {"HOSTILE_ENTITY", "HOSTILE_ENTITY_OR_SELF"}:
            targets = [a for a in self.state.actors.values() if relation(self, a, actor) == ENEMY]
            if action.target_kind == "HOSTILE_ENTITY_OR_SELF":
                targets.append(actor)
        elif action.target_kind == "ALLY_OR_SELF":
            targets = [a for a in self.state.actors.values() if a.active and relation(self, a, actor) == ALLY]
        elif action.target_kind == "ANY_CREATURE":
            targets = list(self.state.actors.values())
        else:
            targets = []
        out = []
        for target in targets:
            if intent is not None and intent.target_ids != (target.entity_id,):
                continue
            if not allowed(self, actor, target, action, allow_remembered=True):
                continue
            from .target_knowledge import Knowledge, knowledge
            # An owned visibility exception has already passed the shared
            # recipient contract; it may identify an otherwise unknown creature.
            known = knowledge(self, actor, target, action) or Knowledge('DIRECT', target.position)
            options = tuple(action.parameters.get("modes", action.parameters.get("options", ())))
            if action.source_definition_id == "action:an_eui.scouring_destruction_blast":
                options = ("DEEPEN",) + tuple(action.parameters.get("break_guard_options", ()))
            if action.source_definition_id == "action:an_eui.first_arm":
                options = tuple(action.parameters.get("break_guard_options", ()))
            options = tuple(option for option in options if self._option_payable(actor, action.source_definition_id, option))
            from .shot_geometry import receipt as shot_receipt
            remembered = known.mode == 'LAST_OBSERVED'
            from .targeting import remembered_square_label
            out.append(self._candidate(kind, actor, action.source_definition_id, action.display_name,
                target_ids=(target.entity_id,), option_ids=options,
                destination=known.position if remembered else None,
                metadata={'target_knowledge': known.mode, 'expected_damage': 0,
                          'target_label': remembered_square_label(self, actor, target)} if remembered else shot_receipt(self, actor, target)))
        from . import ext

        object_ids = set()
        for ids in ext.run("object_targets", self, actor, action):
            object_ids.update(ids)
        for object_id in sorted(object_ids):
            if intent is not None and intent.target_ids != (object_id,):
                continue
            obj = self.state.objects.get(object_id)
            if obj is None or obj.destroyed or obj.ac is None or obj.current_hp is None:
                continue
            from .attack_reach import maximum as attack_maximum
            maximum = attack_maximum(self, actor, action)
            from .object_geometry import target_cells
            # One occupied square must satisfy BOTH constraints. A near hidden
            # end cannot borrow sight from a visible end outside this action's range.
            if not any((maximum is None or self._effect_distance_to_cell(actor, cell) <= maximum)
                       and self._line_of_sight_actor_to_cell(actor, cell)
                       for cell in target_cells(self, obj)):
                continue
            options = tuple(option for option in action.parameters.get("modes", action.parameters.get("options", ()))
                            if self._option_payable(actor, action.source_definition_id, option))
            out.append(self._candidate(kind, actor, action.source_definition_id, action.display_name,
                                       target_ids=(object_id,), option_ids=options, metadata={"object_target": True}))
        return out

    # Options whose resolution spends a resource: offered only while payable, so
    # a fighter who runs dry mid-fight is never handed an option it cannot pay.
    OPTION_COSTS: dict[tuple[str, str], dict[str, int]] = {
        ("action:an_eui.scouring_destruction_blast", "DEEPEN"): {"resource:an_eui.stamina": 1},
        ("action:an_eui.ruin_tempered_armament_quick", "PAIRED_WEAPONS"): {"resource:an_eui.stamina": 1},
    }

    def _typed_hostiles_within(self, actor: ActorState, center: Position, radius_ft: int) -> int:
        from .target_knowledge import actors_for
        return sum(1 for other in actors_for(self, actor)
                   if other.active and relation(self, other, actor) == ENEMY
                   and self.grid.distance_ft(center, other.position) <= radius_ft)

    def _option_payable(self, actor: ActorState, source_id: str, option: str) -> bool:
        costs = self.OPTION_COSTS.get((source_id, option), {})
        return all(actor.resources.get(resource_id, 0) >= amount for resource_id, amount in costs.items())

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
            from .action_legality import deny
            return deny(action.source_definition_id, 'COMPANION_INACTIVE', 'Your companion is inactive and cannot receive a command.')

        def command_visible(target: ActorState) -> bool:
            from .target_knowledge import knowledge
            known = knowledge(self, actor, target)
            if known is None or known.mode != 'DIRECT':
                return False  # an order to chase a creature cannot disclose its hidden destination
            if not self._target_in_range(actor, target, action):
                return False
            return self._line_of_sight_actor_to_actor(actor, target)

        out: list[LegalCandidate] = []
        actors = sorted(self.state.actors.values(), key=lambda row: row.entity_id)

        # STRIKE is hostile-only.  The exact hostile target is bound into the
        # candidate and the single option remains visible in every interface.
        for target in actors:
            if not target.active or relation(self, target, cui) != ENEMY or target.entity_id == CUI:
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
        # Query-only observed geometry. No view is active during execution or
        # historical/player menu generation (combat/candidate_knowledge.py).
        from .candidate_knowledge import roster
        typed_action = self.action_catalog.get(source_definition_id)
        if typed_action is not None and typed_action.resolution_kind == "TYPED" and "expected_damage" not in (metadata or {}):
            expected = int(typed_action.parameters.get("expected_damage") or 0)
            if typed_action.target_kind == "SELF" and typed_action.radius_ft:
                # Areas centred on the user count the enemies inside.
                expected *= self._typed_hostiles_within(actor, actor.position, typed_action.radius_ft)
            metadata = {**(metadata or {}), "expected_damage": expected}
        if typed_action is not None and typed_action.resolution_kind == "TYPED":
            utility = typed_action.parameters.get('rider_utility')
            if type(utility) is int and utility:
                metadata = {**(metadata or {}), 'rider_utility': utility}
        from .relations import enabled
        if typed_action is not None and enabled(self) and int((metadata or {}).get('expected_damage') or 0) > 0:
            shape = (typed_action.parameters.get('typed') or {}).get('area') or {}
            if shape.get('size_ft'):
                from .typed_executor import _area_targets
                from .area_knowledge import preview_engine
                view = preview_engine(self, actor)
                caught = sum(relation(view, actor, other) != ENEMY for other in _area_targets(view, actor, destination, shape, actors=roster(self)))
                if caught:
                    metadata = {**(metadata or {}), 'nonenemy_area_count': caught}
        if (typed_action is not None and typed_action.target_kind == 'SELF'
                and ((typed_action.parameters.get('typed') or {}).get('area') or {}).get('size_ft')):
            from .area_safety import preview
            safety = preview(self, actor, typed_action, destination, actors=roster(self))
            if safety is not None:
                _, extra, warning = safety
                metadata = {**(metadata or {}), **extra}
                if warning:
                    display_name += f' — {warning}'
        identity = self._candidate_identity(kind, actor, source_definition_id, target_ids, destination)
        decision_id = identity['decision_id']
        if (metadata or {}).get('explicit_movement_path'):
            identity['movement_path'] = [p.model_dump(mode='json') for p in path]
            identity['movement_mode'] = metadata.get('movement_mode', 'walk')
        origin = identity.get('effect_origin')
        if origin:
            metadata = {**(metadata or {}), 'effect_origin': origin}
            display_name += f" from {origin['label']} ({origin['position']['x']},{origin['position']['y']})"
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

    def _candidate_identity(self, kind, actor, source_definition_id, target_ids, destination):
        """Shared identity for native objects and untrusted intent query hints."""
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
        from .action_geometry import record_for
        origin = record_for(self, actor, source_definition_id)
        if origin:
            identity['effect_origin'] = origin
        return identity

    def _identity_matches(self, intent, kind, actor, source):
        identity = self._candidate_identity(kind, actor, source, intent.target_ids, intent.destination)
        return intent.candidate_id == f"candidate:{canonical_sha256(identity)[:24]}"

    @contextmanager
    def _reuse_legal_candidates(self, candidates):
        """Legacy persistence scope; execution now always regenerates its choice.

        Kept for saved-fight callers in the Gate3 lock. Supplied objects are never
        retained or used as authority, including during nested state mutations.
        """
        yield

    def candidates_for_intent(self, intent: ActionIntent) -> tuple[LegalCandidate, ...]:
        """Exact persistence/recovery binding for ordinary and explicit GM commands.

        Actor/AI menus never offer a relation command. The owner-facing service
        builds it; actor/provider payloads cannot supply relation_change.
        """
        if intent.relation_change is not None:
            from .relations import command_candidate
            return (command_candidate(self, intent.relation_change),)
        if intent.movement_path is not None:
            from .movement_routes import explicit_candidate
            return (explicit_candidate(self, intent.actor_id, intent.movement_path, intent.movement_mode or 'walk'),)
        if intent.movement_mode is not None:
            raise ValueError('A movement mode requires a chosen route')
        from .candidate_knowledge import binding_candidates
        prepared = binding_candidates(self)
        if prepared is not None:
            return prepared
        # Ordinary choices already carry enough identity to regenerate just
        # their native action. Do that before searching the complete square-
        # picker menu: preview, PREPARE and resolution each validate afresh.
        # Picker roots have no destination and cannot bind through the exact-
        # cell path, so they retain the existing full-menu fallback below.
        matched = tuple(c for c in self._generate_legal_candidates(intent) if c.candidate_id == intent.candidate_id)
        if matched:
            return matched
        if intent.destination is None:
            from .placement_menu import query
            with query():
                roots = tuple(c for c in self._generate_legal_candidates()
                              if c.candidate_id == intent.candidate_id and c.metadata.get('placement_picker'))
            if roots:
                return roots
        # Malformed/stale identity hints must preserve the native mismatch error
        # and candidate metadata, rather than pretending the ID never existed.
        matched = tuple(c for c in self._generate_legal_candidates() if c.candidate_id == intent.candidate_id)
        if (matched or self.state.terminal_result is not None or self.state.pending_resolution is not None
                or intent.state_version != self.state.state_version):
            # A stale intent can never bind, so it needs no projected query.
            return matched
        # A known-square area can be absent from the real-roster preview when
        # its remembered occupants moved. Validate that exact candidate again
        # through the pure AI view, then execute against the actual roster.
        from .candidate_knowledge import query
        with query(self):
            projected = self.legal_candidates()
        return tuple(c for c in projected if c.candidate_id == intent.candidate_id
                     and c.destination is not None
                     and (self.action_catalog[c.source_definition_id].parameters.get('typed') or {}).get('area'))

    def bind_recorded_move(self, intent, binding):
        """Replay/recovery only: validate the journal's route, never reroute it.

        Absence of route fields preserves old intent serialization and identity.
        The recorded route is revalidated by fresh generation on execute.
        """
        recorded = LegalCandidate.model_validate(binding)
        if recorded.kind != CandidateKind.MOVE or intent.movement_path is not None:
            return None
        previous = getattr(self, '_recorded_route_candidate', None)
        self._recorded_route_candidate = recorded
        try:
            candidates = self.legal_candidates()
        finally:
            self._recorded_route_candidate = previous
        candidate = next((c for c in candidates if c.candidate_id == intent.candidate_id), None)
        if candidate is not None and candidate.model_dump(mode='json') == binding:
            self._recorded_intent_route = recorded
        return candidate

    def execute_intent(self, intent: ActionIntent) -> None:
        if self.state.terminal_result is not None:
            raise self._intent_error("GATE2_MATCH_TERMINAL", "The match is already terminal.", intent)
        self._prepared_candidates = None  # single use, including failures
        recorded = self.__dict__.pop('_recorded_intent_route', None)
        previous = getattr(self, '_recorded_route_candidate', None)
        if recorded is not None and recorded.candidate_id == intent.candidate_id:
            self._recorded_route_candidate = recorded
        try:
            candidates = {c.candidate_id: c for c in self.candidates_for_intent(intent)}
        finally:
            self._recorded_route_candidate = previous
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
        self._active_candidate = candidate
        self._active_action_source_id = candidate.source_definition_id
        try:
            with self._transaction(candidate.source_definition_id, intent.intent_id, actor.entity_id):
                before_acceptance = self.state.event_sequence
                self._append_event("INTENT_ACCEPTED", candidate.source_definition_id, actor_id=actor.entity_id, target_ids=candidate.target_ids, payload={
                    "candidate_id": candidate.candidate_id,
                    "kind": candidate.kind.value,
                    "option_ids": list(intent.option_ids),
                })
                if intent.relation_change is not None:
                    from .relations import apply_change
                    apply_change(self, intent.relation_change)
                    return
                if candidate.source_definition_id == 'system:combat.fight_setup':
                    from .fight_setup import resolve
                    resolve(self, intent)
                    self._append_event("ROUND_STARTED", SYSTEM_TURN, payload={"round": self.state.round_number})
                    self._system_start_turn(initial=True)
                elif candidate.source_definition_id == 'system:combat.stand_up':
                    from . import posture
                    posture.stand_up(self, actor)
                elif candidate.kind == CandidateKind.MOVE:
                    self._resolve_movement(actor, candidate, intent, interrupt_after=before_acceptance)
                elif candidate.kind in {CandidateKind.ACTION, CandidateKind.BONUS_ACTION}:
                    completed = True
                    if candidate.source_definition_id.startswith("system:combat.ready:"):
                        from .prepared_actions import prepare
                        prepare(self, actor, candidate)
                    else:
                        action = self.action_catalog[candidate.source_definition_id]
                        from .technique_interception import activation
                        typed_activation = getattr(action.resolution_kind, "value", action.resolution_kind) == "TYPED"
                        try:
                            with activation(self, actor, action, candidate, intent) as (action, resolved_candidate, canceled):
                                completed = not canceled
                                if completed:
                                    completed = self._resolve_action(actor, action, resolved_candidate, intent) is not False
                                if completed:
                                    self._run_final_riders("resolution_final", self, actor, action, resolved_candidate, intent)
                        finally:
                            if typed_activation:
                                from . import ext
                                # Includes declarations canceled before _resolve_action, as well as counter,
                                # start-veto and exception exits. This is the general transient-state boundary
                                # for accepted foreground typed Actions and Bonus Actions only.
                                # Nested follow-ups and reactions do not dispatch this hook.
                                ext.run("activation_end", self, actor, action, candidate, intent)
                    if completed and getattr(self, "typed_actor_ids", None) and self.state.terminal_result is None:
                        from . import typed_reactions  # "a marked creature completes an Action ..." (R3, owner 2026-09-26)
                        typed_reactions.on_action_completed(self, actor, candidate.kind.value, candidate.source_definition_id)
                elif candidate.kind == CandidateKind.OPTIONAL_RIDER:
                    self._resolve_optional_rider(actor, candidate, intent)
                elif candidate.kind == CandidateKind.TAKE_NO_OPTIONAL_ACTION:
                    self._append_event("OPTIONAL_ACTION_DECLINED", candidate.source_definition_id, actor_id=actor.entity_id)
                    self.state.pending_resolution = None
                elif candidate.kind == CandidateKind.HOLD_POSITION:
                    from .hold_position import claim
                    claim(self, actor)
                    self._append_event("HOLD_POSITION_COMMITTED", candidate.source_definition_id, actor_id=actor.entity_id)
                elif candidate.kind == CandidateKind.END_TURN:
                    pass
                else:
                    raise self._intent_error("GATE2_UNSUPPORTED_CANDIDATE_KIND", "Unsupported candidate kind.", intent)
            if candidate.kind == CandidateKind.END_TURN:
                self._active_turn_advancing = True
                try:
                    self.end_turn(intent.intent_id)
                finally:
                    self._active_turn_advancing = False
        finally:
            self._active_intent = None
            self._active_candidate = None
            self._active_action_source_id = None

    # ------------------------------------------------------------------
    # Movement and opportunity/hazard handling
    # ------------------------------------------------------------------
    def _run_final_riders(self, point: str, *args: Any) -> None:
        from . import ext
        if not ext.has(point):
            return
        previous = getattr(self, "_final_rider_active", False)
        terminal = self.state.terminal_result.model_copy(deep=True) if self.state.terminal_result is not None else None
        self._final_rider_active = True
        try:
            if ext.run_strict(point, *args):
                raise ValueError(f"{point} must return None")
            if terminal is not None and self.state.terminal_result != terminal:
                raise ValueError("final riders cannot rewrite a declared terminal result")
        finally:
            self._final_rider_active = previous

    def _voluntary_step_allowed(self, actor: ActorState, previous: Position, destination: Position) -> bool:
        from .voluntary_movement import blocking_source
        source = blocking_source(self, actor, previous, destination)
        if source is None:
            return True
        self._append_event("PASSIVE_TRIGGERED", SYSTEM_MOVE, actor_id=actor.entity_id,
                           payload={"log": f"{actor.display_name} stops: Frightened prevents a step closer to {source.display_name} while that creature is visible."})
        return False
    def _record_movement_collision(self, actor: ActorState, destination: Position) -> None:
        """An accepted move stops before an obstructed step without charging it."""
        from .target_knowledge import movement_contact
        if not movement_contact(self, actor, destination):
            self._append_event("PASSIVE_TRIGGERED", SYSTEM_MOVE, actor_id=actor.entity_id,
                               payload={"log": "Movement stopped before a blocked space.",
                                        "attempted_destination": destination.model_dump(mode="json")})

    def move_path(self, actor: ActorState, path: tuple[Position, ...], source: str, *,
                  kind: str = 'willing', feet: int | None = None, intent: ActionIntent | None = None,
                  provokes: bool = True, ignore_oa_from: tuple[str, ...] = (),
                  source_actor_id: str | None = None) -> int:
        """Recorded plug-in path execution; see combat.movement_paths for its contract."""
        from .movement_paths import resolve
        return resolve(self, actor, path, source, kind=kind, feet=feet, intent=intent,
                       provokes=provokes, ignore_oa_from=ignore_oa_from, source_actor_id=source_actor_id)

    def grant_movement(self, actor: ActorState, path: tuple[Position, ...], source: str, *,
                       feet: int, intent: ActionIntent | None = None, provokes: bool = True,
                       ignore_oa_from: tuple[str, ...] = (), mode: str | None = None) -> int:
        """Native granted path entry for Patrol, Interpose and selective exemptions."""
        from .granted_movement import resolve_path
        return resolve_path(self, actor, path, source, feet=feet, intent=intent,
                            provokes=provokes, ignore_oa_from=ignore_oa_from, mode=mode)

    def _resolve_movement(self, actor: ActorState, candidate: LegalCandidate, intent: ActionIntent, *,
                          granted_ft: int | None = None, ignore_oa_from: tuple[str, ...] = (),
                          grant_source: str | None = None, interrupt_after: int | None = None,
                          movement_context: dict | None = None) -> None:
        from .movement_sequences import sequence
        with sequence(self, actor, context=movement_context):
            self._resolve_movement_sequence(actor, candidate, intent, granted_ft=granted_ft,
                ignore_oa_from=ignore_oa_from, grant_source=grant_source, interrupt_after=interrupt_after)

    def _resolve_movement_sequence(self, actor, candidate, intent, *, granted_ft=None,
                                   ignore_oa_from=(), grant_source=None, interrupt_after=None):
        from .movement_steps import opportunity_policy
        from . import ext
        # INTENT_ACCEPTED can resolve a prepared response which stops this
        # move before its first step. Do not dispatch movement-start benefits
        # after that general interruption receipt has already been recorded.
        interrupted_before_start = (interrupt_after is not None and
            int(actor.turn_flags.get("movement_interrupted_sequence", 0)) > interrupt_after)
        if candidate.canonical_path and len(candidate.canonical_path) > 1 and not interrupted_before_start:
            ext.run_strict("movement_begin", self, actor, candidate, intent, granted_ft)
        with opportunity_policy(self, actor, ignore_oa_from, candidate.canonical_path):
            self._resolve_movement_with_policy(actor, candidate, intent, granted_ft=granted_ft,
                ignore_oa_from=ignore_oa_from, grant_source=grant_source, interrupt_after=interrupt_after)

    def _resolve_movement_with_policy(self, actor: ActorState, candidate: LegalCandidate, intent: ActionIntent, *,
                          granted_ft: int | None = None, ignore_oa_from: tuple[str, ...] = (),
                          grant_source: str | None = None, interrupt_after: int | None = None) -> None:
        if granted_ft is not None and (type(granted_ft) is not int or granted_ft < 0):
            raise ValueError('granted movement requires nonnegative integer feet')
        if granted_ft is not None and self._effective_speed(actor) <= 0:
            return
        if interrupt_after is not None and int(actor.turn_flags.get("movement_interrupted_sequence", 0)) > interrupt_after:
            # A prepared response to INTENT_ACCEPTED already ended this move.
            # Its displacement/payment receipts stand; do not validate or charge
            # a path bound to the actor's space before that response.
            self._append_event("MOVEMENT_COMMITTED", grant_source or SYSTEM_MOVE, actor_id=actor.entity_id,
                payload={"destination": actor.position.model_dump(mode="json"),
                         "path": [actor.position.model_dump(mode="json")], "cost_ft": 0,
                         "planned_cost_ft": candidate.movement_cost_ft, "interrupted": True})
            return
        from . import flight
        mode = str(candidate.metadata.get("movement_mode") or ("fly" if any(p.z for p in candidate.canonical_path) and flight.profile(self, actor).speed_ft else "walk"))
        # A separate grant only constrains the creature whose grant is active.
        # Nested movement by a reaction target, and native grants made outside
        # the extension scope, use the caller's declared grant. Ordinary moves
        # still use their own remaining allowance.
        active_grant = getattr(self, "_granted_movement_budget", None)
        if not isinstance(active_grant, dict) or active_grant.get("actor") is not actor:
            active_grant = None
        spent_ft = 0
        paid_ft = 0
        def budget(previous=None, destination=None) -> int:
            if granted_ft is None:
                if mode == "climb":
                    if previous is None:
                        return max(flight.remaining(self, actor, "walk"), flight.remaining(self, actor, "climb"))
                    from .roof_movement import step_mode
                    return flight.remaining(self, actor, step_mode(self, actor, previous, destination))
                allowance = flight.remaining(self, actor, mode)
                if previous is None and mode == 'jump':
                    return flight.path_allowance(self, actor, candidate.canonical_path, mode)
                if previous is not None and mode == 'jump':
                    allowance += flight.mode_credit(self, actor, mode, previous, destination) - flight.mode_credit(self, actor, mode)
                return allowance
            # Only an active budget owned by this mover can reduce its grant
            # after a reaction. Native callers need no extension scope.
            remaining_grant = (granted_ft if active_grant is None else
                               min(granted_ft, int(active_grant.get("grant", granted_ft))))
            return remaining_grant - spent_ft
        if candidate.movement_cost_ft > budget():
            raise self._intent_error("GATE2_MOVEMENT_BUDGET_EXCEEDED", "Movement exceeds the remaining movement budget.", intent)
        path = candidate.canonical_path
        if not path or path[0] != actor.position or path[-1] != candidate.destination:
            raise self._intent_error("GATE2_MOVEMENT_PATH_INVALID", "The movement candidate path is invalid.", intent)
        if mode == "jump" and not flight.valid_jump(self, actor, path):
            raise self._intent_error("GATE2_MOVEMENT_PATH_INVALID", "That high jump exceeds this creature's jump height.", intent)
        from .roof_movement import valid_climb, valid_drop
        if mode == "climb" and not valid_climb(self, actor, path):
            raise self._intent_error("GATE2_MOVEMENT_PATH_INVALID", "Start a climb from a supported space or your existing grip.", intent)
        if mode == "jump_down" and not valid_drop(self, actor, path):
            raise self._intent_error("GATE2_MOVEMENT_PATH_INVALID", "Jump down by stepping from a supported edge into open space.", intent)
        from .ext import next_jump
        jump_receipts = next_jump.prepare(self, actor, mode, path)
        climb_checked = False
        previous = actor.position
        traversed = [path[0]]
        from .creature_passage import geometry, finish, entered
        occupied_cells, end_blocked, extra_difficult, passage = geometry(self, actor)
        difficult = self._hostile_difficult_cells(actor) | extra_difficult
        drag = self._drag_multiplier(actor)
        dragged: dict[str, list[Position]] = {}
        interruptions = []
        stop_sequence = int(actor.turn_flags.get("movement_interrupted_sequence", 0)) if interrupt_after is None else interrupt_after
        # Native movement scope: plug-ins ask movement_scope(actor_id) while these steps,
        # and the reactions and opportunity attacks they provoke, resolve.
        with self._movement_scope(actor, grant_source or SYSTEM_MOVE, mode, granted_ft is not None):
            for nxt in path[1:]:
                if int(actor.turn_flags.get("movement_interrupted_sequence", 0)) > stop_sequence:
                    break
                if not self._voluntary_step_allowed(actor, previous, nxt):
                    break
                # Earlier movement hazards/reactions can move another creature too.
                occupied_cells, end_blocked, extra_difficult, passage = geometry(self, actor)
                difficult = self._hostile_difficult_cells(actor) | extra_difficult
                if not flight.step_allowed(self, actor, previous, nxt, mode=mode):
                    self._record_movement_collision(actor, nxt)
                    break
                step_cost = flight.step_cost(self, actor, previous, nxt, mode, difficult)
                if step_cost > budget(previous, nxt):
                    self._append_event("PASSIVE_TRIGGERED", grant_source or SYSTEM_MOVE, actor_id=actor.entity_id,
                        payload={"log": f"{actor.display_name} stops here: the next step costs {step_cost} feet of movement, "
                                        f"but only {budget(previous, nxt)} feet remain."})
                    break
                from .typed_executor import condition_rules
                prone_before = any(row.get("ends_on_stand_up") for row in condition_rules(actor))
                from .movement_steps import checkpoint
                denied = checkpoint(self, actor, previous, nxt, intent, point='movement_attempt',
                    travelled_ft=(len(traversed) - 1) * self.grid.square_size_ft,
                    remaining_ft=(len(path) - len(traversed)) * self.grid.square_size_ft,
                    destination=candidate.destination, allowance_ft=budget(), mode=mode,
                    granted=granted_ft is not None)
                if denied:
                    interruptions.extend(denied)
                    break
                # An attempt response can stop, displace or incapacitate the mover
                # without returning a stop receipt. Do not open stale leave-reach OAs.
                if (int(actor.turn_flags.get("movement_interrupted_sequence", 0)) > stop_sequence
                        or not actor.active or (self.state.terminal_result is not None and not getattr(self, "_final_rider_active", False))
                        or self._effective_speed(actor) <= 0 or actor.position != previous
                        or (not prone_before and any(row.get("ends_on_stand_up") for row in condition_rules(actor)))):
                    break
                self._resolve_leave_reach(actor, previous, nxt, intent, ignore_oa_from=ignore_oa_from)
                # Reactions can incapacitate, displace or immobilise the mover, or
                # change terrain, occupancy and drag costs. Never charge the old step.
                if (int(actor.turn_flags.get("movement_interrupted_sequence", 0)) > stop_sequence
                        or not actor.active or (self.state.terminal_result is not None and not getattr(self, "_final_rider_active", False))
                        or self._effective_speed(actor) <= 0 or actor.position != previous
                        or (not prone_before and any(row.get("ends_on_stand_up") for row in condition_rules(actor)))):
                    break
                if not self._voluntary_step_allowed(actor, previous, nxt):
                    break
                occupied_cells, end_blocked, extra_difficult, passage = geometry(self, actor)
                if not flight.step_allowed(self, actor, previous, nxt, mode=mode):
                    self._record_movement_collision(actor, nxt)
                    break
                difficult = self._hostile_difficult_cells(actor) | extra_difficult
                drag = self._drag_multiplier(actor)
                step_cost = flight.step_cost(self, actor, previous, nxt, mode, difficult)
                if step_cost > budget(previous, nxt):
                    break
                if mode == "climb" and not climb_checked:
                    from .roof_movement import climb_check, needs_check
                    if needs_check(self, actor, previous, nxt):
                        climb_checked = True
                        if not climb_check(self, actor, previous, nxt, intent):
                            if granted_ft is None:
                                flight.spend(actor, step_cost)
                                paid_ft += step_cost
                            spent_ft += step_cost
                            break
                if granted_ft is None:
                    paid_ft += flight.spend_mode(self, actor, step_cost, mode, previous, nxt)
                spent_ft += step_cost
                actor.position = nxt
                if mode == "climb" or self.grid.roof_surfaces or actor.climbing:
                    from .falling import supported
                    actor.climbing = mode == "climb" and not supported(self, actor)
                traversed.append(nxt)
                from .movement_steps import landed
                landed(self, actor, previous, nxt, intent)
                entered(self, actor, previous, intent)
                from .movement_steps import checkpoint
                interruption = checkpoint(self, actor, previous, nxt, intent,
                    travelled_ft=(len(traversed) - 1) * self.grid.square_size_ft,
                    remaining_ft=(len(path) - len(traversed)) * self.grid.square_size_ft,
                    destination=candidate.destination, allowance_ft=budget(), mode=mode,
                    granted=granted_ft is not None)
                if interruption:
                    interruptions.extend(interruption)
                previous = nxt
                dragged_steps, drag_stopped = self._drag_along(actor)
                for other_id, steps in dragged_steps.items():  # the grappled creature comes along
                    dragged.setdefault(other_id, [steps[0]]).extend(steps[1:])
                self._resolve_qi_hazard(actor)
                self._resolve_zone_entry_triggers(actor)
                self._remove_zone_leave_conditions(actor)
                if (int(actor.turn_flags.get("movement_interrupted_sequence", 0)) > stop_sequence
                        or interruption or drag_stopped or not actor.active or actor.position != nxt or (self.state.terminal_result is not None and not getattr(self, "_final_rider_active", False))
                        or self._effective_speed(actor) <= 0
                        or (not prone_before and any(row.get("ends_on_stand_up") for row in condition_rules(actor)))):
                    break
        willing_ft = (len(traversed) - 1) * self.grid.square_size_ft
        finish(self, actor, traversed, intent, mode=mode)
        from .movement_sequences import receipt
        self._append_event("MOVEMENT_COMMITTED", grant_source or SYSTEM_MOVE, actor_id=actor.entity_id, payload={
            "destination": actor.position.model_dump(mode="json"),
            "path": [p.model_dump(mode="json") for p in traversed],
            "cost_ft": paid_ft if granted_ft is None else 0,
            **({"movement_credit_spent_ft": spent_ft - paid_ft} if granted_ft is None and spent_ft != paid_ft else {}),
            **({"granted_cost_ft": spent_ft} if granted_ft is not None else {}),
            # Native walking and a separately granted move are chosen by the
            # mover. Receipts always state that consent so passive listeners
            # never have to infer willingness from a missing field.
            "forced": False,
            **({'movement_selections': receipt(self, actor)} if receipt(self, actor) else {}),
            **({"reaction": True} if grant_source is not None and granted_ft is not None else {}),
            "planned_cost_ft": candidate.movement_cost_ft,
            "interrupted": tuple(traversed) != tuple(path),
            **({"interruptions": interruptions} if interruptions else {}),
            **({"movement_mode": mode, "altitude_ft": actor.position.z * 5} if mode != "walk" else {}),
        })
        next_jump.commit(self, actor, mode, jump_receipts, traversed)
        if mode == "jump" and actor.position.z > path[0].z:
            self._append_event("PASSIVE_TRIGGERED", grant_source or SYSTEM_MOVE, actor_id=actor.entity_id,
                payload={"log": f"{actor.display_name} jumps {5 * (actor.position.z - path[0].z)} ft. up."})
        if mode == "fly" and actor.position.z != path[0].z:
            direction = "up" if actor.position.z > path[0].z else "down"
            self._append_event("PASSIVE_TRIGGERED", grant_source or SYSTEM_MOVE, actor_id=actor.entity_id,
                payload={"log": f"{actor.display_name} flies {direction} to {actor.position.z * 5} ft."})
        from .falling import settle, drop
        if mode == "climb" and len(traversed) > 1:
            self._append_event("PASSIVE_TRIGGERED", grant_source or SYSTEM_MOVE, actor_id=actor.entity_id,
                payload={"log": f"{actor.display_name} climbs to {actor.position.z * 5} ft."})
        if mode == "jump_down":
            drop(self, actor, intent)
        else:
            settle(self, grant_source or SYSTEM_MOVE, intent)
        for other_id, steps in dragged.items():
            self._append_event("MOVEMENT_COMMITTED", SYSTEM_MOVE, actor_id=other_id, payload={
                "destination": self.state.actors[other_id].position.model_dump(mode="json"),
                "path": [p.model_dump(mode="json") for p in steps], "cost_ft": 0, "forced": True, "dragged_by": actor.entity_id})
        if getattr(self, "typed_actor_ids", None) and actor.active and self.state.terminal_result is None and len(traversed) > 1:
            from . import typed_reactions  # "when a creature within your Speed moves willingly" (owner 2026-09-26)
            typed_reactions.on_creature_event(self, actor, "moved", moved_ft=willing_ft)
            typed_reactions.on_moved_geometry(self, actor, traversed[0], traversed[-1], zones_handled=True)

    @contextmanager
    def _movement_scope(self, actor: ActorState, source_id: str, mode: str, granted: bool):
        """Transient, never saved: unwinds on pauses and errors with the move itself."""
        scopes = self.__dict__.setdefault("_movement_scopes", [])
        scopes.append({"actor_id": actor.entity_id, "source_id": source_id, "mode": mode, "granted": granted})
        try:
            yield
        finally:
            scopes.pop()

    def movement_scope(self, actor_id: str) -> dict[str, Any] | None:
        """Public seam: the innermost native move this actor is making right now, or None.

        Covers _resolve_movement's steps, including movement_attempt/step
        checkpoints and the opportunity attacks those steps provoke. Returns a
        copy {actor_id, source_id, mode, granted}; None before validation and
        after MOVEMENT_COMMITTED. Pure query: never stored in saved state.
        """
        for scope in reversed(self.__dict__.get("_movement_scopes") or ()):
            if scope["actor_id"] == actor_id:
                return dict(scope)
        return None

    def _resolve_leave_reach(self, mover: ActorState, previous: Position, nxt: Position, intent: ActionIntent, *,
                             ignore_oa_from: tuple[str, ...] = ()) -> None:
        from . import typed_reactions
        from .paid_relocation import activation as relocation_activation
        from . import ext
        if mover.turn_flags.get("disengaged"):
            if not ext.has('disengage_protection'):
                return
            from .opportunity_protection import disengage_protects
            projected = mover.model_copy(update={'position': previous})
            if all(disengage_protects(self, hostile, projected)
                   for hostile in self.state.actors.values()
                   if hostile.active and relation(self, hostile, mover) == ENEMY):
                return  # preserve saved movement exemptions when fully protected
        # A separately exempt step cannot consume protection saved for a later
        # ordinary step. Partial exemptions still leave other enemies eligible.
        if ignore_oa_from and all(a.entity_id in ignore_oa_from
                for a in self.state.actors.values() if a.active and relation(self, a, mover) == ENEMY):
            return
        free = int(mover.turn_flags.get("oa_free_ft") or 0)
        if free > 0:  # movement an ability granted "without provoking" (owner 2026-09-27), spent square by square
            mover.turn_flags["oa_free_ft"] = max(0, free - self.grid.square_size_ft)
            return
        eligible = []
        from .opportunity_protection import disengage_protects
        projected = mover.model_copy(update={'position': previous})
        for hostile in self.state.actors.values():
            if hostile.entity_id in ignore_oa_from:
                continue
            if not hostile.active or relation(self, hostile, mover) != ENEMY:
                continue
            if disengage_protects(self, hostile, projected):
                continue  # protection also suppresses spent-Reaction notices
            waiver_row = typed_reactions.opportunity_reaction_row(self, hostile)
            if not hostile.reaction_available and not typed_reactions.reaction_waived(self, hostile, waiver_row):
                row = typed_reactions._opportunity_row(self, hostile) if hostile.entity_id in getattr(self, "typed_actor_ids", set()) else None
                from .attack_reach import opportunity_distance
                reach = opportunity_distance(self, hostile, row) if row else 5
                if row is not None and self._distance_actor_to_actor(mover, hostile, actor_position=previous) <= reach < self._distance_actor_to_actor(mover, hostile, actor_position=nxt):
                    # Say why no opportunity attack came (owner 2026-09-27 playtest: "attacks of opportunity werent taken").
                    self._append_event("REACTION_DECLINED", SYSTEM_OPPORTUNITY, actor_id=hostile.entity_id, target_ids=(mover.entity_id,),
                                       payload={"checkpoint": "LEAVE_REACH", "reason": "its reaction was already used this round"})
                continue
            if hostile.entity_id in getattr(self, "typed_actor_ids", set()):
                reach = self._typed_opportunity_reach(hostile)  # its best melee weapon's reach (owner 2026-09-26)
                if reach is None:
                    continue
            else:
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
        admitted = set(self.opportunity_eligible(mover, previous, nxt, ignore_oa_from=ignore_oa_from, free_ft=0))
        for reactor in sorted(eligible, key=self._initiative_rank):
            if reactor.entity_id not in admitted:
                continue
            waiver_row = typed_reactions.opportunity_reaction_row(self, reactor)
            if not typed_reactions._can_react(self, reactor, waiver_row):
                continue
            # Accepted step only: optional protection may ask, spend and veto.
            from . import ext
            if reactor.entity_id not in getattr(self, 'typed_actor_ids', set()) and ext.any_false('opportunity_response', self, reactor, mover):
                continue
            if reactor.entity_id in getattr(self, "typed_actor_ids", set()):
                # A Factory fighter follows its reaction plan (combat/typed_reactions.py) rather than the fixture AI.
                from . import typed_reactions
                if not typed_reactions.wants_opportunity_attack(self, reactor, mover):
                    continue
                with relocation_activation(self, reactor, waiver_row["action_id"], independent=True):
                    self._append_event("REACTION_WINDOW_OPENED", SYSTEM_OPPORTUNITY, actor_id=mover.entity_id, target_ids=(reactor.entity_id,), payload={"checkpoint":"LEAVE_REACH"})
                    typed_reactions.spend_reaction(self, reactor, waiver_row)
                    typed_reactions.opportunity_attack(self, reactor, mover, intent, trigger="movement")
                    self._append_event("REACTION_RESOLVED", SYSTEM_OPPORTUNITY, actor_id=reactor.entity_id, target_ids=(mover.entity_id,))
                    if not mover.active:
                        break
                    continue
            decision = self._reaction_decision(intent, "LEAVE_REACH", reactor.entity_id, SYSTEM_OPPORTUNITY)
            self._append_event("REACTION_WINDOW_OPENED", SYSTEM_OPPORTUNITY, actor_id=mover.entity_id, target_ids=(reactor.entity_id,), payload={"checkpoint":"LEAVE_REACH"})
            if decision is None or decision.selection == "DECLINE":
                self._append_event("REACTION_DECLINED", SYSTEM_OPPORTUNITY, actor_id=reactor.entity_id, target_ids=(mover.entity_id,))
                continue
            with relocation_activation(self, reactor, SYSTEM_OPPORTUNITY, independent=True):
                typed_reactions.spend_reaction(self, reactor, waiver_row)
                typed_reactions.opportunity_attack(self, reactor, mover, intent, trigger="movement")
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
        checkpoint_results = self._dex_checkpoint(actor, "DEX", 12, SYSTEM_HAZARD,
                                                  {"area_cells": sorted(self.grid.qi_hazard)})
        if checkpoint_results and not self._footprint_intersects(actor, self.grid.qi_hazard):
            return
        roll = self.roller.d20(modifier=actor.saving_throws.get("DEX", 0), actor_id=actor.entity_id, reason="QI_HAZARD_DEX_SAVE",
                               mode=self.direct_save_mode(actor, "DEX", 12, SYSTEM_HAZARD, modes={r.get("mode") for r in checkpoint_results if isinstance(r, dict)}))
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
    def _resolve_action(self, actor: ActorState, action: ActionDefinition, candidate: LegalCandidate, intent: ActionIntent) -> bool | None:
        from .placement_menu import resolve
        candidate, intent = resolve(self, actor, action, candidate, intent)
        from .action_geometry import activate, valid
        origin = candidate.metadata.get('effect_origin')
        with activate(self, actor, action.source_definition_id, origin):
            if not valid(self, actor, action):
                raise self._intent_error("ORIGIN_UNAVAILABLE", "The selected origin is no longer available.", intent)
            if origin:
                self._append_event("PASSIVE_TRIGGERED", action.source_definition_id, actor_id=actor.entity_id,
                    payload={'effect_origin': origin, 'log': f"{actor.display_name} uses {action.display_name} from {origin['label']}. No extra movement is used."})
            return self._resolve_action_at_origin(actor, action, candidate, intent)

    def _resolve_action_at_origin(self, actor: ActorState, action: ActionDefinition, candidate: LegalCandidate, intent: ActionIntent) -> bool | None:
        from .shot_geometry import scope, route, valid
        bound = candidate.metadata.get('shot_geometry')
        with scope(self, actor, action, bound):
            if bound and bound.get('route'):
                target = self.state.actors[bound['target_id']]
                if not valid(self, actor, target, route(self, actor, target)):
                    raise self._intent_error('SHOT_PATH_CHANGED', 'The chosen projectile path is no longer clear.', intent)
                self._append_event('PASSIVE_TRIGGERED', action.source_definition_id, actor_id=actor.entity_id,
                    target_ids=candidate.target_ids, payload={'shot_geometry': bound, 'log': bound['route']['label']})
            return self._resolve_action_impl(actor, action, candidate, intent)

    def _resolve_action_impl(self, actor: ActorState, action: ActionDefinition, candidate: LegalCandidate, intent: ActionIntent) -> bool | None:
        from .attack_completion import deferred
        with deferred(self, enabled=action.resolution_kind not in {'ATTACK', 'MULTI_ATTACK', 'TYPED'}):
            return self._resolve_action_effect(actor, action, candidate, intent)

    def _resolve_action_effect(self, actor: ActorState, action: ActionDefinition, candidate: LegalCandidate, intent: ActionIntent) -> bool | None:
        self._consume_economy(actor, action)
        self._spend_costs(actor, action.costs, action.source_definition_id)
        # Payment can deliver damage or conditions through recorded event riders.
        # Costs stay spent, but an incapacitated payer cannot complete the action.
        from .typed_executor import condition_rules
        if not actor.active or actor.life_state not in {None, 'CONSCIOUS'} or any(row.get("no_actions") for row in condition_rules(actor)):
            self._append_event("PASSIVE_TRIGGERED", action.source_definition_id, actor_id=actor.entity_id,
                               payload={"log": f"{actor.display_name} cannot finish this action after paying its cost."})
            return False
        from .technique_interception import frame
        if frame(self, actor.entity_id, action.source_definition_id).get('range_delta_ft'):
            maximum = action.range_ft if action.range_ft is not None else action.reach_ft
            distant = maximum is not None and ((candidate.destination is not None
                and self._effect_distance_to_cell(actor, candidate.destination) > maximum)
                or any(not self._target_in_range(actor, self.state.actors[tid], action)
                       for tid in candidate.target_ids if tid in self.state.actors))
            if distant:
                self._append_event('PASSIVE_TRIGGERED', action.source_definition_id, actor_id=actor.entity_id,
                    payload={'log': f'{action.display_name} cannot reach its chosen target after its range was reduced. Its activation cost is spent.'})
                return
        if candidate.target_ids and candidate.target_ids[0] in self.state.objects:
            from . import ext

            obj = self.state.objects[candidate.target_ids[0]]
            if not obj.destroyed and any(result is True for result in ext.run_strict(
                    "object_action", self, actor, action, obj, candidate, intent)):
                return
            raise self._intent_error("OBJECT_ACTION_UNHANDLED", "No object resolver accepted this action.", intent)
        target = self.state.actors[candidate.target_ids[0]] if candidate.target_ids else None
        if target is not None and action.resolution_kind != 'TYPED':
            from .target_knowledge import location_missed
            if location_missed(self, actor, target, action.source_definition_id):
                return  # costs/economy are spent; no effects or reactions target an absent creature
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
            from .attack_notifications import can_strike
            from .attack_completion import can_continue
            for index in range(action.attack_count):
                if not can_strike(actor) or not can_continue(self, actor) or not target.active or self.state.terminal_result is not None:
                    break
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
            hit, target = self._resolve_attack_action(actor, target, action, intent, with_target=True)
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
            from .flight import dash
            dash(self, actor)
            actor.turn_flags["dash_used"] = True
        elif kind == "DISENGAGE":
            actor.turn_flags["disengaged"] = True
        elif kind == "TYPED":
            # Data-driven abilities (combat/typed_executor.py).
            from .typed_executor import resolve_typed
            typed_target = self.state.actors[candidate.target_ids[0]] if candidate.target_ids else None
            resolve_typed(self, actor, typed_target, action, candidate, intent)
        else:
            raise self._intent_error("GATE2_UNSUPPORTED_RESOLUTION_KIND", f"Unsupported resolution kind {kind}.", intent)

    def _resolve_attack_action(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent, attack_index: int = 1, *, with_target: bool = False):
        spec = {
            "source_definition_id": action.source_definition_id,
            "attack_bonus": action.attack_bonus,
            "damage": action.damage,
            "damage_type": action.damage_type,
            "range_ft": action.range_ft,
            "reach_ft": action.reach_ft,
            "parameters": action.parameters,
        }
        hit = self._resolve_attack_spec(actor, target, spec, intent, source_definition_id=action.source_definition_id, attack_index=attack_index)
        return (hit, self.state.actors[spec["resolved_target_id"]]) if with_target else hit

    def _resolve_attack_spec(
        self, actor: ActorState, target: ActorState, spec: dict[str, Any], intent: ActionIntent,
        *, reaction_depth: int = 0, source_definition_id: str, attack_index: int = 1, notify: bool = True,
    ) -> bool:
        from .action_geometry import attack
        from .shot_geometry import attack_scope
        spec['attack_roll_occurred'] = False
        spec.pop('concealment_missed', None)
        from contextlib import ExitStack
        from . import ext
        with ExitStack() as extension_scopes, attack(self, actor, source_definition_id), attack_scope(self, actor, source_definition_id):
            for scope in ext.run_strict("attack_resolution_scope", self, actor, target, spec, intent):
                extension_scopes.enter_context(scope)
            from .technique_interception import frame, activation
            if not frame(self, actor.entity_id, source_definition_id):
                original = self.action_catalog.get(source_definition_id)
                action = (original.model_copy(update={'costs': (), 'economy': EconomyKind.NONE,
                          'range_ft': spec.get('range_ft'), 'reach_ft': spec.get('reach_ft')}) if original else
                          ActionDefinition(source_definition_id=source_definition_id, display_name='Reaction attack',
                            owner_id=actor.entity_id, economy=EconomyKind.NONE, resolution_kind='ATTACK',
                            target_kind='HOSTILE_ENTITY', range_ft=spec.get('range_ft'), reach_ft=spec.get('reach_ft')))
                candidate = self._candidate(CandidateKind.REACTION, actor, source_definition_id, action.display_name,
                                            target_ids=(target.entity_id,))
                with activation(self, actor, action, candidate, intent) as (declared, chosen, canceled):
                    if canceled:
                        return False
                    adjusted = dict(spec)
                    adjusted['range_ft'], adjusted['reach_ft'] = declared.range_ft, declared.reach_ft
                    redirected = self.state.actors[chosen.target_ids[0]]
                    if redirected is not target:
                        adjusted.pop('target_check', None)
                    hit = self._resolve_attack_spec(actor, redirected, adjusted, intent,
                        reaction_depth=reaction_depth, source_definition_id=source_definition_id,
                        attack_index=attack_index, notify=notify)
                    spec.update(adjusted)
                    return hit
            from .target_knowledge import location_missed
            if location_missed(self, actor, target, source_definition_id, attack_index):
                return False
            from .pending_damage import resources
            before_hit_resources = resources(self)
            hit, resolved = self._resolve_attack_packet(actor, target, spec, intent, reaction_depth=reaction_depth,
                source_definition_id=source_definition_id, attack_index=attack_index,
                consume_target_modes=notify)
            if hit:
                from .post_hit import resolve
                resolve(self, actor, resolved, spec, intent, before_hit_resources)
            if notify and (spec['attack_roll_occurred'] or spec.get('concealment_missed')):
                from .attack_notifications import notify as notify_result
                notify_result(self, actor, resolved, spec, intent, source_definition_id, hit, attack_index)
                from .attack_completion import notify as complete_attack
                complete_attack(self, actor, resolved, spec, intent, source_definition_id, hit, attack_index)
            return hit

    def _resolve_attack_packet(
        self,
        actor: ActorState,
        target: ActorState,
        spec: dict[str, Any],
        intent: ActionIntent,
        *,
        reaction_depth: int = 0,
        source_definition_id: str,
        attack_index: int = 1,
        consume_target_modes: bool = True,
    ) -> tuple[bool, ActorState]:
        # A strike owns its receipt; an unrolled later strike cannot borrow one.
        spec.pop('attack_roll_id', None)
        spec.pop('resolved_attack_context', None)
        with self.d20_scope({"kind": "attack", "actor_id": actor.entity_id, "target_id": target.entity_id,
                             "spec": spec, "source_id": source_definition_id, "source_actor_id": actor.entity_id,
                             "attack_index": attack_index}):
            from .attack_reach import spec_maximum
            declared_reach = spec_maximum(self, actor, source_definition_id, spec)
            extended_reach = declared_reach > int(spec.get('range_ft') or spec.get('reach_ft') or 5)
            if not spec.get("declaration_done"):
                from .attack_declaration import declare
                original = target
                target, cover = declare(self, actor, target, source_definition_id, intent, attack_index,
                                        range_ft=declared_reach,
                                        context=spec.get("checkpoint_context"))
                spec["declaration_cover"] = cover
                if target is not original:
                    spec.pop("target_check", None)
            spec["resolved_target_id"] = target.entity_id
            from .attack_declaration import intercepted
            if intercepted(self, actor, target, source_definition_id, intent, attack_index, spec=spec):
                return False, target
            from .targeting import attack_line_of_effect
            from .action_geometry import valid_for_source
            check = spec.get("target_check") or (lambda: valid_for_source(self, actor, source_definition_id)
                                                 and self._effect_distance(actor, target) <=
                                                 spec_maximum(self, actor, source_definition_id, spec)
                                                 and attack_line_of_effect(self, actor, target, source_definition_id))
            checkpoint_results = self._attack_checkpoint(actor, target, source_definition_id, intent,
                                                         attack_index, {**(spec.get("checkpoint_context") or {}),
                                                                        "ranged": spec.get("range_ft") is not None})
            from .target_knowledge import location_missed
            if location_missed(self, actor, target, source_definition_id, attack_index):
                return False, target
            if not valid_for_source(self, actor, source_definition_id):
                self._append_event("GM_RIDER", source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                                   payload={"rider": "The chosen origin moved or is no longer available; the attack misses."})
                return False, target
            from .technique_interception import frame
            range_changed = frame(self, actor.entity_id, source_definition_id).get('range_delta_ft')
            from .shot_geometry import valid_for_attack
            if not valid_for_attack(self, actor, target):
                self._append_event("PASSIVE_TRIGGERED", source_definition_id, actor_id=actor.entity_id,
                                   target_ids=(target.entity_id,),
                                   payload={"log": "The chosen projectile path is no longer clear or no longer reaches the defender; the attack misses."})
                return False, target
            if (checkpoint_results or range_changed or extended_reach or spec.get('target_check')) and not check():
                self._append_event("GM_RIDER", source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,),
                                   payload={"rider": "The defender moved out of the attack's reach or sight; the attack misses."})
                return False, target
            mirror_trace_available_before = actor.entity_id == LING and actor.resources.get("resource:ling_qi.mirror_trace", 0) >= 1
            from .targeting import attack_missed
            if attack_missed(self, actor, target, source_definition_id, attack_index, spec=spec):
                return False, target
            moon_sea_available_before = actor.entity_id == BAI and actor.resources.get("resource:bai_meizhen.moon_sea_radiance", 0) >= 1
            ancestral_available_before = actor.entity_id == BAI and actor.resources.get("resource:bai_meizhen.ancestral_resonance", 0) >= 1 and not actor.turn_flags.get("bloodline_strike_used_this_turn")
            from . import attack_modes
            attack_kind = str(spec.get("attack_profile") or (spec.get("parameters") or {}).get("attack_kind") or "")
            typed_attack = spec.get("typed") or {}
            from .attack_delivery import is_ranged
            ranged_attack = is_ranged(attack_kind, spec.get("range_ft"), typed_attack.get("weapon"))
            removed_modes = attack_modes.removed(self, actor, target, ranged_attack)
            chosen_modes = attack_modes.chosen(self, source_definition_id, spec)
            mode_sources = set()
            mode = self._attack_mode(actor, target, removed=removed_modes,
                                    ranged=ranged_attack,
                                    provenance=attack_modes.provenance_for(self, actor, target, source_definition_id),
                                    contributions=mode_sources, chosen_modes=chosen_modes)
            from .roll_reasons import remember, later_source
            remember(self, getattr(mode, 'mode_sources', ()))
            later_receipts = []
            if checkpoint_results:
                # A declaration may substitute a flat penalty when the attack
                # already has Disadvantage. Resolve against the pre-checkpoint
                # mode once; several subscribers cannot change each other's test.
                from .attack_modes import disadvantage_alternatives
                checkpoint_results, penalty = disadvantage_alternatives(checkpoint_results, mode)
                spec["attack_bonus"] = int(spec.get("attack_bonus") or 0) + penalty
                filtered_checkpoints = attack_modes.checkpoint_results(checkpoint_results, removed_modes)
                from .choice_checkpoints import roll_modes
                mode = roll_modes(mode, filtered_checkpoints)
                # Carry each later contributor's display attribution through the
                # composition (review 2026-10-16 finding 2), so a checkpoint
                # answer cancelling an earlier effect explains the cancellation.
                later_receipts.extend(later_source(self, row) for row in filtered_checkpoints)
            from .native_reactions import roll_mode
            mode = roll_mode(self, actor.entity_id, source_definition_id, mode,
                             contributions=mode_sources,
                             checkpoints=attack_modes.checkpoint_results(checkpoint_results, removed_modes),
                             reasons=later_receipts)
            remember(self, [row for row in later_receipts if row])
            if mode == "ADVANTAGE":
                for mid, modifier in list(target.modifiers.items()):
                    if modifier.target_field == "incoming_attack_mode" and modifier.value == "ADVANTAGE":
                        del target.modifiers[mid]
                        self._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"modifier_id":mid,"reason":"CONSUMED"})
                        break
            from .paid_relocation import activation as relocation_activation, capture, causal_scope
            spirit_intercession_owner = None
            if target.entity_id == CUI and self._eligible_spirit_intercession(target):
                dec = self._reaction_decision(intent, "ALLY_OR_COMPANION_ATTACKED", BAI, "reaction:bai_meizhen.spirit_intercession")
                self._append_event("REACTION_WINDOW_OPENED", "reaction:bai_meizhen.spirit_intercession", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"checkpoint":"ALLY_OR_COMPANION_ATTACKED"})
                if dec and dec.selection == "USE":
                    with relocation_activation(self, self.state.actors[BAI], "reaction:bai_meizhen.spirit_intercession", independent=True):
                        spirit_intercession_owner = capture(self)
                        mode = "DISADVANTAGE"
                        self.state.actors[BAI].reaction_available = False
                        self._append_event("REACTION_RESOLVED", "reaction:bai_meizhen.spirit_intercession", actor_id=BAI, target_ids=(target.entity_id,), payload={"attack_mode":"DISADVANTAGE"})
                        self._maybe_gain_moon_sea(self.state.actors[BAI], "PROTECTION_EVENT", "reaction:bai_meizhen.spirit_intercession")
                else:
                    self._append_event("REACTION_DECLINED", "reaction:bai_meizhen.spirit_intercession", actor_id=BAI, target_ids=(target.entity_id,))
            attack_bonus = int(spec.get("attack_bonus") or 0)
            from . import critical_attacks
            from .history_text import history_name
            named_action = self.action_catalog.get(source_definition_id)
            spec['attack_name'] = history_name(source_definition_id,
                {source_definition_id: named_action.display_name} if named_action else {})
            spec["attack_roll_mode"] = mode
            critical_threshold = critical_attacks.lowest(self, actor, target, spec)
            if critical_threshold != 20:
                spec["critical_threshold"] = critical_threshold
            else:
                spec.pop('critical_threshold', None)
            attack_roll = self.roller.d20(modifier=attack_bonus, actor_id=actor.entity_id, reason=f"ATTACK:{source_definition_id}:{attack_index}", mode=mode)
            self._record_roll(attack_roll)
            spec['attack_roll_occurred'] = True
            spec['attack_roll_id'] = attack_roll.roll_id
            spec['attack_natural_result'] = attack_roll.natural_result
            attack_penalty = self._consume_attack_modifiers(actor)
            # Native rolls spend target-specific next-roll benefits before any
            # damage or nested hit aftermath can grant/use a fresh one. Typed
            # callers retain their later, Context-aware consumption phase.
            if consume_target_modes:
                from .attack_modes import consume_targeted_next_attack
                consume_targeted_next_attack(self, actor, target)
            total = attack_roll.total + attack_penalty
            cover, effective_ac = self._attack_defense(actor, target, spec, source_definition_id)
            natural = attack_roll.natural_result or 0
            automatic_hit = natural >= critical_threshold
            provisional_hit = critical_attacks.hits(natural, total, effective_ac, critical_threshold)
            self._append_event("ATTACK_ROLLED", source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={
                **attack_roll.model_dump(mode="json"),
                "modified_total": total,
                "target_ac": effective_ac,
                "cover_bonus": cover,
                "provisional_hit": provisional_hit,
                **({"chosen_attack_modes": sorted(chosen_modes)} if chosen_modes else {}),
                **({"attack_mode_removed": sorted(removed_modes)} if removed_modes else {}),
                **({"critical_threshold": critical_threshold} if critical_threshold != 20 else {}),
            })
            from .attack_outcomes import forced_miss
            forced = forced_miss(self, actor, target, source_definition_id, attack_index, attack_roll, checkpoint_results)
            if forced:
                provisional_hit = False
            correction_attempted = False
            correction_damage = 0
            miss_outcome_attempted = False
            def correct_at_ac(pending_total, defense_ac):
                nonlocal total, correction_damage, correction_attempted
                if forced or natural == 1 or correction_attempted:
                    return pending_total
                from .attack_outcomes import correct_miss
                correction_attempted = True
                total, correction_damage = correct_miss(self, actor, target, spec, attack_roll, intent, pending_total, defense_ac)
                return total
            def replace_at_ac(pending_total, defense_ac):
                nonlocal miss_outcome_attempted
                if forced or miss_outcome_attempted:
                    return False
                miss_outcome_attempted = True
                from .attack_outcomes import replace_miss_with_hit
                return replace_miss_with_hit(self, actor, target, spec, attack_roll, intent, pending_total, defense_ac)
            if not provisional_hit and not forced and natural != 1:
                total = correct_at_ac(total, effective_ac)
                provisional_hit = critical_attacks.hits(natural, total, effective_ac, critical_threshold)
            if not provisional_hit and not forced:
                provisional_hit = replace_at_ac(total, effective_ac)
            from . import ext
            # A provider may transfer a cover-only miss without drawing another
            # attack die. Recipient defenses and damage still resolve natively.
            if not provisional_hit and not forced and natural != 1 and cover > 0 and total >= effective_ac - cover:
                redirects = ext.run_strict('cover_miss_recipient', self, actor, target, spec, attack_roll, intent, total, cover)
                if redirects:
                    recipient_id = redirects[0]
                    recipient = self.state.actors.get(recipient_id) if isinstance(recipient_id, str) else None
                    if recipient is None or not recipient.active or recipient.entity_id in {actor.entity_id, target.entity_id}:
                        raise ValueError('cover_miss_recipient requires another active recipient')
                    self._append_event('PASSIVE_TRIGGERED', source_definition_id, actor_id=actor.entity_id,
                        target_ids=(recipient.entity_id,), payload={'original_target_id': target.entity_id,
                            'attack_redirected': 1,
                            'roll_id': attack_roll.roll_id, 'total': total,
                            'log': f'Cover makes the attack miss {target.display_name}; resolve its original roll against {recipient.display_name}.'})
                    target = recipient
                    spec['resolved_target_id'] = target.entity_id
                    cover, effective_ac = self._attack_defense(actor, target, spec, source_definition_id)
                    provisional_hit = critical_attacks.hits(natural, total, effective_ac, critical_threshold)
            if provisional_hit and target.entity_id in self.typed_actor_ids:
                from .typed_reactions import on_attack_hit
                effective_ac, provisional_hit = on_attack_hit(self, actor, target, spec, total, natural, effective_ac,
                                                               correct_ac_miss=correct_at_ac,
                                                               replace_ac_miss=replace_at_ac)
            if provisional_hit and target.entity_id == LING and spec.get("range_ft") is not None:
                dec = self._reaction_decision(intent, "ATTACK_HIT_BEFORE_DAMAGE", LING, "reaction:ling_qi.qi_armor")
                self._append_event("REACTION_WINDOW_OPENED", "reaction:ling_qi.qi_armor", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"checkpoint":"ATTACK_HIT_BEFORE_DAMAGE"})
                if dec and dec.selection == "USE" and self._reaction_usable(LING, "reaction:ling_qi.qi_armor"):
                    with relocation_activation(self, self.state.actors[LING], "reaction:ling_qi.qi_armor", independent=True):
                        armor = self.reaction_parameters["reaction:ling_qi.qi_armor"]
                        self._spend_resource(self.state.actors[LING], armor["resource"], armor["cost"], "reaction:ling_qi.qi_armor")
                        self.state.actors[LING].reaction_available = False
                        effective_ac += armor["ac_bonus"]
                        provisional_hit = automatic_hit or total >= effective_ac
                        self._append_event("REACTION_RESOLVED", "reaction:ling_qi.qi_armor", actor_id=LING, target_ids=(target.entity_id,), payload={"ac_bonus":armor["ac_bonus"],"new_ac":effective_ac,"hit_after_recheck":provisional_hit})
                        if not provisional_hit:
                            from .attack_outcomes import correct_ac_defense
                            total, provisional_hit = correct_ac_defense(total, effective_ac, natural, spec, correct_at_ac)
                            if not provisional_hit:
                                provisional_hit = replace_at_ac(total, effective_ac)
                else:
                    self._append_event("REACTION_DECLINED", "reaction:ling_qi.qi_armor", actor_id=LING, target_ids=(target.entity_id,))
            if not provisional_hit:
                if target.entity_id == LING and relation(self, actor, target) == ENEMY:
                    self._maybe_gain_mirror_trace("HOSTILE_ATTACK_MISS", source_definition_id)
                if target.entity_id in {BAI, CUI} and relation(self, actor, target) == ENEMY:
                    self._maybe_gain_moon_sea(self.state.actors[BAI], "FAILED_HOSTILE_CONTEST", source_definition_id)
                return False, target
            if target.entity_id == CUI:
                intercession = self._reaction_decision(intent, "ALLY_OR_COMPANION_ATTACKED", BAI, "reaction:bai_meizhen.spirit_intercession")
                if intercession and intercession.selection == "USE":
                    bai = self.state.actors[BAI]
                    scope = (causal_scope(self, spirit_intercession_owner) if spirit_intercession_owner is not None else
                             relocation_activation(self, bai, "reaction:bai_meizhen.spirit_intercession", independent=True))
                    with scope:
                        if "SPEND_QI" in intercession.option_ids and bai.resources.get("resource:bai_meizhen.qi", 0) >= 1:
                            self._spend_resource(bai, "resource:bai_meizhen.qi", 1, "reaction:bai_meizhen.spirit_intercession")
                        else:
                            self._gain_resource(bai, "resource:bai_meizhen.cui_bond_strain", 1, "reaction:bai_meizhen.spirit_intercession")
            critical_qualified = critical_attacks.qualifies(self, actor, target, spec, attack_roll, intent, critical_threshold)
            critical = critical_attacks.resolve(self, actor, target, spec, attack_roll, intent,
                                                source_definition_id, critical_threshold, qualified=critical_qualified)
            if critical and target.entity_id in self.typed_actor_ids:
                from .typed_reactions import offer_critical_hit
                offer_critical_hit(self, actor, target)
            from .damage_context import AttackDamage
            attack_context = AttackDamage(source_definition_id, actor.entity_id, target.entity_id,
                attack_index, attack_roll.roll_id, natural, total, critical,
                kind=str((spec.get('parameters') or {}).get('attack_kind') or 'other'),
                critical_cancelled=critical_qualified and not critical)
            spec['resolved_attack_context'] = attack_context
            from .attack_notifications import capture
            spec['hit_snapshots'] = capture(self, actor, target, attack_context, intent)
# Main's typed delivery seam: confirmed hit, before any damage.
            # The caller owns the context and transactional choice transport.
            before_damage = spec.get('before_attack_damage')
            if before_damage is not None:
                before_damage(self, actor, target, spec, attack_context)
            # The branch's transient packet preparation: after hit/critical
            # choices and snapshots, immediately before this strike's actual
            # damage draw. Fixed/no-damage packets bypass roll-only providers;
            # absent callbacks preserve the native resolver's predecessor
            # behaviour. Both seams run before the same damage draw and neither
            # consumes the other's state.
            prepare_damage = spec.get("prepare_damage_roll")
            if prepare_damage is not None and spec.get("damage") is not None and spec.get("fixed_damage") is None:
                prepare_damage(self, actor, target, spec)
            damage_spec = spec.get("damage")
            if damage_spec is None:
                return True, target
            fixed = spec.get("fixed_damage")
            damage_roll = self.roller.roll(damage_spec, actor_id=actor.entity_id, reason=f"DAMAGE:{source_definition_id}:{attack_index}", critical=critical, fixed_damage=fixed)
            self._record_roll(damage_roll)
            damage_total = damage_roll.total + correction_damage
            from . import ext
            adjustments = ext.run_strict("confirmed_damage_roll_adjustment", self, actor, target, spec, intent, source_definition_id, damage_roll)
            for adjustment in adjustments:
                if type(adjustment) is not int:
                    raise ValueError("confirmed_damage_roll_adjustment requires an integer adjustment")
                damage_total += adjustment
            if adjustments:
                damage_total = max(0, damage_total)
            if critical and actor.entity_id == AN and self._has_condition(actor, "condition:an_eui.ruin_tempered"):
                extra = self.roller.roll(damage_spec.model_copy(update={"count":2,"sides":6,"modifier":0}), actor_id=actor.entity_id, reason="RUIN_TEMPERED_CRITICAL")
                self._record_roll(extra)
                damage_total += extra.total
            from .technique_interception import damage_amount
            damage_total = damage_amount(self, actor.entity_id, source_definition_id, damage_roll.roll_id, damage_total)
            self._append_event("DAMAGE_ROLLED", source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={
                **damage_roll.model_dump(mode="json"), "critical":critical, "combined_total":damage_total,
            })
            weapon_charge = next((c for c in actor.conditions.values() if c.condition_id == "condition:lee_jia.lightning_charge.held_weapon"), None)
            if weapon_charge is not None:
                damage_total += actor.proficiency_bonus
                self._append_event("DAMAGE_ROLLED", "resource:lee_jia.lightning_charge", actor_id=actor.entity_id, target_ids=(target.entity_id,), payload={"fixed_lightning_damage":actor.proficiency_bonus,"discharge":"HELD_WEAPON_NEXT_HIT"})
                self._remove_lightning_charge_condition(actor, weapon_charge.instance_id, "WEAPON_HIT_DISCHARGE")
            damage_type = spec.get("damage_type") or "UNTYPED"
            hp_damage = self._commit_damage(target, damage_total, damage_type, source_definition_id, actor.entity_id, intent,
                reaction_depth=reaction_depth, attack_context=attack_context)
            if self.state.terminal_result is not None:
                return True, target
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
            return True, target

    def _resolve_attack_then_save(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        from .attack_completion import deferred
        with deferred(self):
            self._resolve_attack_then_save_effect(actor, target, action, intent)

    def _resolve_attack_then_save_effect(self, actor: ActorState, target: ActorState, action: ActionDefinition, intent: ActionIntent) -> None:
        hit, target = self._resolve_attack_action(actor, target, action, intent, with_target=True)
        if self.state.terminal_result is not None or not hit or not target.active or action.save is None:
            return
        save = self._roll_save(target, action.save.ability, action.save.dc, action.source_definition_id,
                               checkpoint_context={"actor_id": actor.entity_id},
                               target_check=lambda: self._target_in_range(actor, target, action))
        if save is None:
            return
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
        save = self._roll_save(target, action.save.ability, action.save.dc, action.source_definition_id,
                               checkpoint_context={"actor_id": actor.entity_id},
                               target_check=lambda: self._target_in_range(actor, target, action))
        if save is None:
            return
        damage_roll = self.roller.roll(action.damage, actor_id=actor.entity_id, reason=f"DAMAGE:{action.source_definition_id}")
        self._record_roll(damage_roll)
        self._append_event("DAMAGE_ROLLED", action.source_definition_id, actor_id=actor.entity_id, target_ids=(target.entity_id,), payload=damage_roll.model_dump(mode="json"))
        failed = save.total < action.save.dc
        from .technique_interception import damage_amount
        total = damage_amount(self, actor.entity_id, action.source_definition_id, damage_roll.roll_id, damage_roll.total)
        amount = total if failed else total // 2
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
        hit, target = self._resolve_attack_action(actor, target, action, intent, with_target=True)
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
                if save is not None and save.total < 14:
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
            from .flight import dash
            dash(self, actor)
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
        hit, target = self._resolve_attack_action(actor, target, action, intent, with_target=True)
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
                and relation(self, a, target) == ALLY
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
            if target.active and relation(self, target, actor) == ENEMY and self._in_zone(target, zone):
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
            or relation(self, target, cui) != ENEMY
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
        hit, target = self._resolve_attack_action(actor, target, action, intent, with_target=True)
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
    def damage_context(self):
        """Immutable attack provenance for this packet, or None for other damage."""
        return getattr(self, '_damage_packet_context', None)

    def _commit_damage(self, target, amount, damage_type, source_definition_id, source_actor_id, intent,
                       *, reaction_depth, attack_context=None, pressure_kind='damage', source_flags=()):
        from .damage_context import AttackDamage
        if attack_context is not None and (not isinstance(attack_context, AttackDamage)
                or attack_context.source_id != source_definition_id
                or attack_context.attacker_id != source_actor_id or attack_context.target_id != target.entity_id):
            raise ValueError('attack damage context must identify this damage packet')
        previous = self.damage_context()
        self._damage_packet_context = attack_context  # nested non-attack packets explicitly clear it
        try:
            from .pending_damage import scope
            with scope(self, target, amount, damage_type, source_definition_id, source_actor_id,
                       pressure_kind=pressure_kind, source_flags=source_flags):
                return self._commit_damage_packet(target, amount, damage_type, source_definition_id, source_actor_id,
                    intent, reaction_depth=reaction_depth)
        finally:
            self._damage_packet_context = previous

    def _commit_damage_packet(
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
        # General opt-in seam for effects that increase an existing damage value.
        # Apply before defenses and reactions so the increase is one damage packet.
        from . import ext
        if ext.has("damage_value_adjustment"):
            for adjustment in ext.run_strict("damage_value_adjustment", self, target, pending,
                                             damage_type, source_definition_id, source_actor_id, intent):
                if type(adjustment) is not int or adjustment < 0:
                    raise ValueError("damage_value_adjustment must return a nonnegative integer")
                pending += adjustment
            amount = pending
        from .pending_damage import current
        packet = current(self)
        bypass_temp = packet is not None and 'bypass_temporary_hp' in packet.source_flags
        def temporary_buffer():
            return 0 if bypass_temp else target.temporary_hp
        from . import typed_reactions
        typed_target = target.entity_id in getattr(self, "typed_actor_ids", set())
        additional = None if typed_target else typed_reactions.additional_defenses(self, target, damage_type, source_definition_id, source_actor_id)
        if target.entity_id in getattr(self, "runtime_actor_ids", set()) and not additional:
            from .character_runtime_adapter import CharacterCombatRuntimeEngine
            runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
            runtime.__dict__.update(self.__dict__)
            pending = CharacterCombatRuntimeEngine._apply_damage_resistance(runtime, target, pending, damage_type, source_definition_id)
            self.__dict__.update(runtime.__dict__)
        typed_kind = str(damage_type).upper()
        if typed_target or additional:  # one defense application, including opt-in native conditions
            pending = typed_reactions.defend(self, target, pending, typed_kind, source_definition_id, source_actor_id,
                                             additional=additional, native=not typed_target)
        elif any(m.target_field == "damage_immunity" and str(m.value) == typed_kind for m in target.modifiers.values()):
            pending = 0
        elif any(m.target_field == "damage_resistance" and str(m.value) == typed_kind for m in target.modifiers.values()):
            pending //= 2
        self._append_event("REACTION_WINDOW_OPENED", source_definition_id, actor_id=source_actor_id, target_ids=(target.entity_id,), payload={"checkpoint":"DAMAGE_APPLICATION","pending_damage":pending,"reaction_depth":reaction_depth})
        if intent is not None and reaction_depth <= 2:
            if typed_target:
                pending = typed_reactions.on_damage(self, target, pending, reaction_depth, source_definition_id, source_actor_id)
            else:
                pending = self._resolve_damage_reaction(target, pending, intent, reaction_depth)
        if pending < 0:
            pending = 0
        from . import ext
        from .damage_allocation import available_temporary_hp
        available_temp = available_temporary_hp(self, target, pending, source_actor_id,
                                                source_id=source_definition_id, damage_type=damage_type)
        bypass_temp = available_temp == 0 and target.temporary_hp > 0
        if ext.has("final_damage"):
            defended = pending
            floor = 0
            reduction = 0
            settlements = []
            for answer in ext.run_strict("final_damage", self, target, defended, damage_type,
                                         source_definition_id, source_actor_id, intent):
                if not isinstance(answer, dict) or set(answer) - {"amount", "hp_floor", "reduction", "settle"}:
                    raise ValueError("final_damage must return amount, hp_floor, reduction and/or settle")
                if "settle" in answer and ("reduction" not in answer or not callable(answer["settle"])):
                    raise ValueError("final_damage settle requires a reduction and a callable")
                reduced = answer.get("amount", defended)
                minimum_hp = answer.get("hp_floor", 0)
                additive = answer.get("reduction", 0)
                if (type(reduced) is not int or not 0 <= reduced <= defended
                        or type(minimum_hp) is not int or not 0 <= minimum_hp <= target.maximum_hp
                        or type(additive) is not int or not 0 <= additive <= defended):
                    raise ValueError("final_damage requires bounded integer damage, reduction and HP floor")
                pending = min(pending, reduced)
                floor = max(floor, minimum_hp)
                reduction += additive
                if "reduction" in answer:
                    settlements.append((additive, answer.get("settle")))
            remaining = pending
            pending = max(0, pending - reduction)
            floor_cap = remaining
            if floor:
                # Shared packet allocation keeps rescue floors consistent with Temporary HP bypass.
                from .damage_allocation import maximum_packet_before_hp_floor
                floor_cap = maximum_packet_before_hp_floor(self, target, remaining, floor, source_actor_id,
                                                           source_id=source_definition_id, damage_type=damage_type)
                pending = min(pending, floor_cap)
            # Attribute each reduction in provider order, retaining legacy amount/floor
            # precedence. Callbacks are transient and run only after every reply validates.
            for additive, settle in settlements:
                after = max(0, remaining - additive)
                applied = min(remaining, floor_cap) - min(after, floor_cap)
                remaining = after
                if settle is not None and settle(applied) is not None:
                    raise ValueError("final_damage settle must return None")
        if getattr(self, "_fall_packet", None) is not None:
            from .falling import remaining_packet
            pending = remaining_packet(self, target, pending, damage_type, source_definition_id, intent)
        # Optional floor decisions observe the result of every final reduction,
        # so a defensive half-damage reply cannot cause an unnecessary rescue.
        for minimum_hp in ext.run_strict('damage_floor', self, target, pending, damage_type,
                                         source_definition_id, source_actor_id, intent):
            if type(minimum_hp) is not int or not 0 <= minimum_hp <= target.maximum_hp:
                raise ValueError('damage_floor requires a bounded integer HP floor')
            if minimum_hp:
                from .damage_allocation import maximum_packet_before_hp_floor
                pending = min(pending, maximum_packet_before_hp_floor(self, target, pending, minimum_hp,
                    source_actor_id, source_id=source_definition_id, damage_type=damage_type))
        if ext.has("damage_deferral") and pending:
            from .damage_deferral import apply as defer_damage
            pending = defer_damage(self, target, pending, damage_type, source_definition_id, source_actor_id, intent)
        # Survival decisions see the damage left after every ordinary reduction
        # and floor. Recheck between subscribers so a rescue is not paid twice.
        for respond in ext.callbacks('lethal_damage'):
            if target.current_hp <= 0 or pending < target.current_hp + min(available_temp, pending):
                break
            floor = respond(self, target, pending, damage_type, source_definition_id, source_actor_id, intent)
            if floor is None:
                continue
            if type(floor) is not int or not 0 <= floor <= target.maximum_hp:
                raise ValueError('lethal_damage must return None or a bounded integer HP floor')
            from .damage_allocation import maximum_packet_before_hp_floor
            pending = min(pending, maximum_packet_before_hp_floor(self, target, pending, floor,
                source_actor_id, source_id=source_definition_id, damage_type=damage_type))
        temp_absorb = 0 if bypass_temp else min(target.temporary_hp, pending)
        target.temporary_hp -= temp_absorb
        hp_damage = pending - temp_absorb
        initial_damage_excess = max(0, hp_damage - target.current_hp)
        hp_before = target.current_hp
        receipt_facts = {}
        from . import ext
        for facts in ext.run_strict('damage_receipt_facts', self, target, source_definition_id, source_actor_id):
            reserved = {'rolled_or_pending_damage', 'reduced_to', 'temporary_hp_absorbed',
                        'hp_damage', 'hp_before', 'damage_type', 'remaining_hp'}
            if not isinstance(facts, dict) or any(key in receipt_facts or key in reserved for key in facts):
                raise ValueError('damage_receipt_facts must return nonoverlapping dictionaries')
            if any(not isinstance(key, str) or type(value) not in (str, int, list)
                   or (isinstance(value, list) and any(type(v) not in (str, int) for v in value))
                   for key, value in facts.items()):
                raise ValueError('damage receipt facts must be primitive replayable values')
            receipt_facts.update(facts)
        target.current_hp = max(0, target.current_hp - hp_damage)
        from .pending_damage import current as current_pending_damage
        packet = current_pending_damage(self)
        pressure_receipt = ({'pressure_kind': packet.pressure_kind}
                            if packet is not None and packet.pressure_kind != 'damage' else {})
        self._append_event("DAMAGE_COMMITTED", source_definition_id, actor_id=source_actor_id, target_ids=(target.entity_id,), payload={
            **pressure_receipt,
            "rolled_or_pending_damage": amount,
            "reduced_to": pending,
            "temporary_hp_absorbed": temp_absorb,
            "hp_damage": hp_damage,
            # Event consumers can distinguish a new drop from damage to an
            # already-down creature without reconstructing prior state.
            "hp_before": hp_before,
            "damage_type": damage_type,
            "remaining_hp": target.current_hp,
            **receipt_facts,
        })
        if pending > 0 and target.concentration is not None and target.active:
            from .attached_concentration import defer
            # An attached attack packet's save waits for the attack's combined damage (attack_damage_final).
            if not defer(self, target, pending, source_actor_id, source_definition_id):
                self._concentration_check(target, pending, source_actor_id=source_actor_id,
                                          damage_source_id=source_definition_id)
        if target.current_hp == 0 and target.active:
            self._defeat(target, source_definition_id, initial_damage_excess=initial_damage_excess)
        self._check_victory()
        return hp_damage

    def _resolve_damage_reaction(self, target: ActorState, pending: int, intent: ActionIntent, reaction_depth: int) -> int:
        if target.entity_id in getattr(self, "typed_actor_ids", set()):
            from .typed_reactions import on_damage
            return on_damage(self, target, pending, reaction_depth)
        if any("reaction:fire.fire_ward" in actor.reaction_ids for actor in self.state.actors.values()) and hasattr(self, "runtime_actor_ids"):
            from .character_runtime_adapter import CharacterCombatRuntimeEngine
            runtime = CharacterCombatRuntimeEngine.__new__(CharacterCombatRuntimeEngine)
            runtime.__dict__.update(self.__dict__)
            result = CharacterCombatRuntimeEngine._resolve_damage_reaction(runtime, target, pending, intent, reaction_depth)
            self.__dict__.update(runtime.__dict__)
            if result != pending:
                return result
        from .activation_payments import reaction_completed
        candidates: list[tuple[str, str]] = []
        if target.entity_id == AN:
            candidates += [(AN,"reaction:an_eui.sheath_bone_guard"),(AN,"reaction:core.stamina_guard")]
        if target.entity_id == LING:
            candidates += [(LING,"reaction:ling_qi.false_image_guard")]
        ling = self.state.actors.get(LING)
        if ling is not None and relation(self, target, ling) == ALLY and self._distance_actor_to_actor(ling, target) <= 30:
            candidates += [(LING,"reaction:ling_qi.rhythmic_guard")]
        bai = self.state.actors.get(BAI)
        if bai is not None and relation(self, target, bai) == ALLY and self._distance_actor_to_actor(bai, target) <= 30:
            candidates += [(BAI,"reaction:bai_meizhen.water_shield"),(BAI,"reaction:bai_meizhen.sea_moon_interposition")]
        candidates.sort(key=lambda row:(0 if row[0]==target.entity_id else 1,self._initiative_rank(self.state.actors[row[0]]),row[1]))
        for reactor_id, reaction_id in candidates:
            if not self._reaction_usable(reactor_id,reaction_id):
                continue
            decision = self._reaction_decision(intent,"DAMAGE_APPLICATION",reactor_id,reaction_id)
            if decision is None or decision.selection == "DECLINE":
                continue
            reactor = self.state.actors[reactor_id]
            from .paid_relocation import activation as relocation_activation

            with relocation_activation(self, reactor, reaction_id, independent=True):
                reduction = 0
                if reaction_id == "reaction:core.stamina_guard":
                    maximum = min(reactor.proficiency_bonus, reactor.resources.get("resource:an_eui.stamina",0))
                    if not 1 <= decision.spend <= maximum:
                        raise self._intent_error("GATE2_INVALID_STAMINA_GUARD_SPEND", "Stamina Guard spend is outside the legal range.", intent)
                    reactor.reaction_available = False
                    self._spend_resource(reactor,"resource:an_eui.stamina",decision.spend,reaction_id)
                    if not reaction_completed(self, reactor, reaction_id):
                        continue
                    for index in range(decision.spend):
                        roll = self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":10,"modifier":0}), actor_id=reactor_id, reason=f"STAMINA_GUARD_REDUCTION:{index+1}")
                        self._record_roll(roll)
                        reduction += roll.total
                elif reaction_id == "reaction:an_eui.sheath_bone_guard":
                    reactor.reaction_available = False
                    self._spend_resource(reactor,"resource:an_eui.severance_edge",1,reaction_id)
                    if not reaction_completed(self, reactor, reaction_id):
                        continue
                    reduction=6
                elif reaction_id == "reaction:ling_qi.false_image_guard":
                    reactor.reaction_available = False
                    self._spend_resource(reactor,"resource:ling_qi.mirror_trace",1,reaction_id)
                    if not reaction_completed(self, reactor, reaction_id):
                        continue
                    reduction=7
                elif reaction_id == "reaction:ling_qi.rhythmic_guard":
                    reactor.reaction_available = False
                    self._spend_resource(reactor,"resource:ling_qi.qi",1,reaction_id)
                    if not reaction_completed(self, reactor, reaction_id):
                        continue
                    roll=self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":8,"modifier":4}),actor_id=reactor_id,reason="RHYTHMIC_GUARD_REDUCTION");self._record_roll(roll);reduction=roll.total
                elif reaction_id == "reaction:bai_meizhen.water_shield":
                    reactor.reaction_available = False
                    self._spend_resource(reactor,"resource:bai_meizhen.qi",1,reaction_id)
                    if not reaction_completed(self, reactor, reaction_id):
                        continue
                    roll=self.roller.roll(ACTIONS["action:ling_qi.sound_resonant_note"].damage.model_copy(update={"count":1,"sides":10,"modifier":4}),actor_id=reactor_id,reason="WATER_SHIELD_REDUCTION");self._record_roll(roll);reduction=roll.total
                    self._maybe_gain_moon_sea(reactor, "PROTECTION_EVENT", reaction_id)
                elif reaction_id == "reaction:bai_meizhen.sea_moon_interposition":
                    reactor.reaction_available = False
                    self._spend_resource(reactor,"resource:bai_meizhen.moon_sea_radiance",1,reaction_id)
                    if not reaction_completed(self, reactor, reaction_id):
                        continue
                    reduction=10 if "DIRECT_CONTEST" in decision.option_ids else 7
                reactor.reaction_available=False
                reduced=max(0,pending-reduction)
                self._append_event("REACTION_RESOLVED",reaction_id,actor_id=reactor_id,target_ids=(target.entity_id,),payload={"checkpoint":"DAMAGE_APPLICATION","spend":decision.spend,"reduction":reduction,"pending_before":pending,"pending_after":reduced,"reaction_depth":reaction_depth})
                return reduced
        self._append_event("REACTION_DECLINED",source_definition_id="system:combat.damage_reaction_window",actor_id=target.entity_id,payload={"pending_damage":pending})
        return pending

    # ------------------------------------------------------------------
    # Conditions, modifiers, concentration, zones, companion defaults
    # ------------------------------------------------------------------
    def _apply_condition(self, target: ActorState, condition_id: str, source_id: str, source_actor_id: str, *, expires_on: str | None, data: dict[str,Any] | None=None, unavoidable: bool=False) -> None:
        """Event a condition; an explicit unavoidable rule bypasses prevention only."""
        from .typed_executor import CONDITION_PREFIX, condition_immune
        if not unavoidable and condition_id.startswith(CONDITION_PREFIX) and condition_immune(self, target, condition_id[len(CONDITION_PREFIX):]):
            self._append_event('PASSIVE_TRIGGERED', source_id, actor_id=source_actor_id, target_ids=(target.entity_id,),
                               payload={'log': f'{target.display_name} is immune to {condition_id[len(CONDITION_PREFIX):].replace("_", " ").title()}.'})
            return
        from . import ext
        replies = [] if unavoidable else ext.run_checkpoint("condition_application_attempt", self, target, condition_id, source_id, source_actor_id)
        if any(type(reply) is not bool for reply in replies):
            raise ext.CheckpointError("condition_application_attempt must return bool or None")
        if any(reply is False for reply in replies):
            return
        condition_data = dict(data or {})
        # Reaction-denying conditions suppress an available Reaction without
        # spending it. Persist the pre-suppression state on the condition so
        # removal can restore only a Reaction that was actually still available.
        # Overlapping denials inherit this bit from the existing suppression.
        rules = {}
        if condition_id.startswith(CONDITION_PREFIX):
            from .typed_executor import rules as condition_rules
            rules = condition_rules()["conditions"].get(condition_id[len(CONDITION_PREFIX):], {})
        denies_reaction = bool((condition_data.get("rule") or {}).get("no_reactions") or rules.get("no_reactions"))
        if denies_reaction:
            inherited = any(bool((held.data or {}).get("reaction_suppression_restore"))
                            for held in target.conditions.values())
            condition_data["reaction_suppression_restore"] = bool(inherited or target.reaction_available)
        instance_id=f"condition-instance:{condition_id}:{target.entity_id}:{self.state.event_sequence+1}"
        target.conditions[instance_id]=ConditionInstance(instance_id=instance_id,condition_id=condition_id,source_definition_id=source_id,source_actor_id=source_actor_id,target_id=target.entity_id,applied_sequence=self.state.event_sequence+1,expires_on=expires_on,data=condition_data)
        self._append_event("CONDITION_APPLIED",source_id,actor_id=source_actor_id,target_ids=(target.entity_id,),payload={"condition_id":condition_id,"instance_id":instance_id,"expires_on":expires_on})

    def _update_condition_data(self, target: ActorState, condition: ConditionInstance, data: dict[str, Any], source_id: str,
                               *, expires_on: Any = ...) -> None:
        """Update one retained instance; optionally replace its expiry without renewing it.

        Omitted expiry preserves the existing deadline. Explicit None removes it.
        Persistence augments can detach a condition from Concentration while
        preserving the instance identity used by dependent grants/permissions.
        CONDITION_UPDATED carries the changed fields through Gate 3 replay;
        consumers that trigger on CONDITION_APPLIED therefore see only new conditions.
        """
        if target.conditions.get(condition.instance_id) is not condition:
            raise ValueError("condition update requires the live instance owned by its target")
        condition.data = dict(data)
        if expires_on is not ...:
            condition.expires_on = expires_on
        self._append_event("CONDITION_UPDATED", source_id, actor_id=condition.source_actor_id,
            target_ids=(target.entity_id,), payload={"condition_id":condition.condition_id,
                "instance_id":condition.instance_id, "data":dict(condition.data),
                **({"expires_on": expires_on} if expires_on is not ... else {})})

    def _remove_condition(self,target:ActorState,condition_id:str,source_id:str) -> None:
        for iid,condition in list(target.conditions.items()):
            if condition.condition_id==condition_id:
                self._remove_condition_instance(target, iid, source_id, expected=condition)

    def _remove_condition_instance(self, target: ActorState, instance_id: str, source_id: str, **kwargs: Any) -> bool:
        """General exact-instance ending, shared by manual and deadline callers."""
        from .effect_endings import remove_instance
        return remove_instance(self, target, "condition", instance_id, source_id, **kwargs)

    def _remove_modifier_instance(self, target: ActorState, modifier_id: str, source_id: str, **kwargs: Any) -> bool:
        """General exact-instance modifier ending with the same subscribers."""
        from .effect_endings import remove_instance
        return remove_instance(self, target, "modifier", modifier_id, source_id, **kwargs)

    def _reconcile_reaction_after_condition_removal(self, target: ActorState, removed: list[ConditionInstance]) -> None:
        """Release Reaction suppression when its final typed denial ends."""
        if not any(bool((held.data or {}).get("reaction_suppression_restore")) for held in removed):
            return
        from .typed_executor import condition_rules
        if not any(rule.get("no_reactions") for rule in condition_rules(target)):
            target.reaction_available = True

    def _add_modifier(self,target:ActorState,source_id:str,target_field:str,operation:str,value:int|str,applies_to:str,*,expires_on:str|None,source_actor_id:str|None=None,application_id:str|None=None,origin_save:dict[str,int|str]|None=None) -> str:
        """Add a modifier; explicit ownership supports off-turn named effects.

        Omitted ownership retains the ordinary current-turn attribution.
        Optional origin_save retains the actual native ability/DC, never a
        guessed DC from the caster's later statistics; absent on ordinary rows.
        """
        modifier_owner = source_actor_id or self.state.current_actor_id
        mid=f"modifier:{source_id}:{target.entity_id}:{self.state.event_sequence+1}"
        target.modifiers[mid]=ModifierInstance(modifier_id=mid,source_definition_id=source_id,source_actor_id=modifier_owner,target_id=target.entity_id,target_field=target_field,operation=operation,value=value,applies_to=applies_to,application_id=application_id,origin_save=origin_save,expires_on=expires_on)
        self._append_event("MODIFIER_APPLIED",source_id,actor_id=modifier_owner,target_ids=(target.entity_id,),payload={"modifier_id":mid,"target_field":target_field,"operation":operation,"value":value,"expires_on":expires_on})
        return mid

    def _heal(self, target: ActorState, amount: int, source_id: str, source_actor_id: str | None,
              *, notify_healed: bool = False) -> int:
        """Commit one HP grant after caller-owned stored reductions; never revive implicitly."""
        from .typed_executor import healing_pending
        from .support_values import healing_offer
        amount = healing_offer(self, target, source_id, source_actor_id, amount)
        amount = healing_pending(self, target, amount, self.state.actors.get(source_actor_id), source_id, "hp")
        before = target.current_hp
        target.current_hp = min(target.maximum_hp, before + amount)
        if notify_healed and target.current_hp > before:
            from .typed_reactions import on_creature_event
            on_creature_event(self, target, "healed")
        self._append_event("HEALING_APPLIED", source_id, actor_id=source_actor_id, target_ids=(target.entity_id,),
                           payload={"offered": amount, "before": before, "after": target.current_hp})
        return target.current_hp - before

    def _grant_temp_hp(self,target:ActorState,amount:int,source_id:str,source_actor_id:str,
                       *, original_amount:int|None=None, offer_cap:int|None=None) -> None:
        from .typed_executor import condition_rules
        if any(rule.get('temp_hp_denied') for rule in condition_rules(target)):
            self._append_event('PASSIVE_TRIGGERED', source_id, actor_id=source_actor_id, target_ids=(target.entity_id,),
                payload={'log': f'{target.display_name} cannot gain Temporary Hit Points while this effect applies.'})
            return
        from .temp_hp_offers import offered_bonus
        if offer_cap is not None and (type(offer_cap) is not int or offer_cap < 0):
            raise ValueError('Temporary HP offer cap must be a nonnegative integer')
        amount += offered_bonus(self, target, amount, source_id, source_actor_id, consume=True,
                                original_amount=original_amount, offer_cap=offer_cap)
        if offer_cap is not None:
            amount = min(amount, offer_cap)
        from .typed_executor import healing_pending
        amount = healing_pending(self, target, amount, self.state.actors.get(source_actor_id), source_id, "temp_hp")
        before=target.temporary_hp;target.temporary_hp=max(before,amount)
        self._append_event("TEMP_HP_GRANTED",source_id,actor_id=source_actor_id,target_ids=(target.entity_id,),payload={"offered":amount,"before":before,"after":target.temporary_hp})

    def _start_concentration(self,actor:ActorState,source_id:str) -> None:
        # Several at once by Cultivation Level (owner 2026-09-29, combat/concentration.py): one more at the limit ends the one
        # held longest; the current one is held, not ended. The same technique again takes one more slot like any other
        # (owner ruling 2026-09-29: "they can hold any number of the same spells as long as they arent the same stacking buff").
        from . import concentration
        if actor.concentration is not None:
            limit=concentration.limit(self,actor)
            if limit<=1:
                self._end_concentration(actor,"REPLACED")
            else:
                held=concentration.held(actor)
                while held and 1+len(held)>=limit:
                    concentration.end_held(self,actor,held[0][0],"REPLACED");held=held[1:]
                concentration.hold_current(self,actor)
        actor.concentration=ConcentrationState(source_definition_id=source_id,started_sequence=self.state.event_sequence+1)
        self._append_event("CONCENTRATION_STARTED",source_id,actor_id=actor.entity_id)

    def _end_concentration(self,actor:ActorState,reason:str) -> None:
        if actor.concentration is None:return
        conc=actor.concentration
        # Detach this exact copy before a zone or other ending subscriber can
        # re-enter Concentration cleanup. The local snapshot retains ownership.
        actor.concentration=None
        if conc.zone_id and conc.zone_id in self.state.zones:
            from .zones import remove
            remove(self, self.state.zones[conc.zone_id], reason)
        from . import concentration  # the ones it still holds (combat/concentration.py)
        concentration.end_conditions(self,actor,conc.source_definition_id,conc.started_sequence,reason)  # this copy's own, not another copy's
        concentration.end_summons(self,actor,conc.source_definition_id,reason)  # a Concentration summon (the Painted Beast) leaves with it
        self._append_event("CONCENTRATION_ENDED",conc.source_definition_id,actor_id=actor.entity_id,payload={"reason":reason,"started_sequence":conc.started_sequence})
        if reason in {"ENTITY_DEFEATED", "DYING"}:concentration.end_all_held(self,actor,reason)
        elif reason!="REPLACED":concentration.resume_latest(self,actor)

    def _concentration_check(self,actor:ActorState,hp_damage:int, *, source_actor_id=None, damage_source_id=None,
                             owed_sequence: int | None = None) -> None:
        dc=min(30,max(10,hp_damage//2))
        from . import ext
        from . import concentration  # Advantage/Disadvantage on Concentration saves (owner 2026-09-29, Breath Seal ...)
        support_sources = concentration.support_sources(self, actor)
        outcome_receipt = {}
        mode_sources = []
        # owed_sequence: the save was already due when this damage landed (combat/attached_concentration.py);
        # a one-use mode applied after that moment belongs to the following save.
        modes, support_bonus = concentration.save_contributions(self, actor, reasons=mode_sources, owed_sequence=owed_sequence)
        roll=self._roll_save(actor,"CON",dc,SYSTEM_CONCENTRATION,
                            outcome_receipt=outcome_receipt,
                            roll_context={"source_actor_id": source_actor_id, "damage_source_id": damage_source_id,
                                          "save_modes": sorted(modes), 'additional_bonus': support_bonus,
                                          'mode_sources': mode_sources})
        # Native Concentration consumes the same explicit result override as typed saves.
        from .paid_relocation import preserve_pending
        preserve_pending(self, "_typed_roll_outcome")
        outcome = (getattr(self, "_typed_roll_outcome", None) or {}).pop(actor.entity_id, None)
        failed = outcome == "failure" if outcome in ("success", "failure") else roll.total < dc
        # Forced native outcomes can raise the returned total to the DC. The
        # pre-outcome receipt, rather than that adjusted total, tells us whether
        # the earlier support actually maintained Concentration.
        if not failed and outcome_receipt.get("total_before_outcome", roll.total) < dc:
            support_sources = []
        if failed:
            if actor.concentration is not None and ext.has("concentration_save_failed"):
                # Rescue seam: one strict owner may keep this concentration (it must
                # record and later end what it kept); no owner keeps the old ending.
                answers = ext.run_strict("concentration_save_failed", self, actor, roll, dc,
                                         {"source_actor_id": source_actor_id, "damage_source_id": damage_source_id,
                                          "started_sequence": actor.concentration.started_sequence,
                                          "source_definition_id": actor.concentration.source_definition_id})
                if answers:
                    if answers != ["MAINTAIN"]:
                        raise ValueError("one concentration_save_failed plugin may answer MAINTAIN")
                    # These proposals helped the failed roll, not the accepted
                    # rescue. Until a rescuer supplies final attribution, keep
                    # its provider unknown rather than credit an earlier bonus.
                    ext.run_strict("concentration_save_resolved", self, actor, roll, dc, True, [])
                    return
            self._end_concentration(actor,"FAILED_DAMAGE_CHECK")
        ext.run_strict("concentration_save_resolved", self, actor, roll, dc, not failed, support_sources)

    def _resolve_zone_triggers(self,actor:ActorState,*,checkpoint:str) -> None:
        for zone in sorted(self.state.zones.values(),key=lambda z:z.zone_id):
            owner = self.state.actors.get(zone.owner_id)
            if zone.trigger_profile.get("kind") not in {"BLACKWATER", "SEA_RISEN"} or owner is None:
                continue
            if zone.active and self._in_zone(actor,zone) and relation(self, owner, actor) == ENEMY:
                if checkpoint=="AT_TURN_START" and zone.trigger_profile.get("kind")=="BLACKWATER":self._resolve_zone_effect(zone,actor,checkpoint=checkpoint)
                elif checkpoint=="AT_TURN_START" and zone.trigger_profile.get("kind")=="SEA_RISEN":self._resolve_zone_effect(zone,actor,checkpoint=checkpoint)

    def _resolve_zone_entry_triggers(self,actor:ActorState) -> None:
        for zone in sorted(self.state.zones.values(),key=lambda z:z.zone_id):
            if not zone.active or not self._in_zone(actor, zone):
                continue
            if zone.trigger_profile.get("kind") == "CHARGE_SPACE" and actor.entity_id != zone.owner_id:
                self._commit_damage(actor, 3, "LIGHTNING", "resource:lee_jia.lightning_charge", zone.owner_id, None, reaction_depth=0)
                self._remove_lightning_charge_zone(zone, "FIRST_ENTRY_DISCHARGE")
            elif zone.trigger_profile.get("kind") in {"BLACKWATER", "SEA_RISEN"} and \
                    (owner := self.state.actors.get(zone.owner_id)) is not None and relation(self, owner, actor) == ENEMY:
                self._resolve_zone_effect(zone,actor,checkpoint="ON_ENTER_ZONE")

    def _resolve_zone_triggers_for_owner_end(self,owner_id:str) -> None:
        for zone in sorted(self.state.zones.values(),key=lambda z:z.zone_id):
            if zone.active and zone.owner_id==owner_id and zone.trigger_profile.get("kind")=="NOCTURNE":
                for target in sorted(self.state.actors.values(),key=lambda a:a.entity_id):
                    if target.active and relation(self, target, self.state.actors[owner_id]) == ENEMY and self._in_zone(target,zone):self._resolve_zone_effect(zone,target,checkpoint="AT_TURN_END")

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
        active_allies=[a for a in self.state.actors.values() if a.active and relation(self, a, cui) == ALLY and a.primary_combatant]
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
        from .alternative_payments import options, pay
        quoted = self.effective_costs(actor, source_id, costs)
        if options(self, actor, source_id, quoted):
            pay(self, actor, source_id, quoted, getattr(self, '_active_intent', None))
            return
        for rid,amount in quoted:self._spend_resource(actor,rid,amount,source_id)

    def effective_costs(self, actor, source_id, listed_costs, *, reduced_costs=None):
        """Public pure cost query for native and plug-in affordability/payment."""
        from .technique_costs import effective
        return effective(self, actor, source_id, listed_costs, reduced_costs)

    def _spend_resource(self,actor:ActorState,resource_id:str,amount:int,source_id:str) -> None:
        current=actor.resources.get(resource_id)
        if current is None or amount<0 or current<amount:raise error("GATE2_RESOURCE_UNDERFLOW",f"{actor.display_name} cannot spend {amount} {resource_id}.",phase="RESOLUTION",subsystem="RESOURCE",entity_id=actor.entity_id,source_definition=source_id,recommended_action="Choose a legal candidate with an affordable cost.",recovery=RecoveryDisposition.RETRY)
        from . import ext
        reductions = ext.run_strict("resource_spend_reduction", self, actor, resource_id, amount, source_id)
        if any(type(value) is not int or value < 0 for value in reductions):
            raise ValueError("resource_spend_reduction must return a nonnegative integer or None")
        amount = max(0, amount - max(reductions, default=0))
        actor.resources[resource_id]=current-amount
        from .paid_relocation import payment
        payment(self, actor, resource_id, amount, source_id)
        self._append_event("RESOURCE_SPENT",source_id,actor_id=actor.entity_id,payload={"resource_id":resource_id,"amount":amount,"remaining":actor.resources[resource_id]})
        if actor.resources[resource_id] == 0 and resource_id == "resource:ling_qi.mirror_trace":
            self._remove_condition(actor, "condition:ling_qi.mirror_trace_window", source_id)
        if actor.resources[resource_id] == 0 and resource_id == "resource:bai_meizhen.moon_sea_radiance":
            self._remove_condition(actor, "condition:bai_meizhen.moon_sea_radiance_window", source_id)

    def _set_resource_maximum(self, actor: ActorState, resource_id: str, maximum: int, source_id: str) -> None:
        """Event a represented pool capacity change and clamp its held amount."""
        if resource_id not in actor.resources or type(maximum) is not int or maximum < 0:
            raise ValueError("invalid resource maximum")
        from .resource_labels import resource_name
        previous = actor.resource_maximums[resource_id]
        current = min(actor.resources[resource_id], maximum)
        if previous == maximum and actor.resources[resource_id] == current:
            return
        actor.resource_maximums[resource_id] = maximum
        actor.resources[resource_id] = current
        self._append_event("RESOURCE_MAXIMUM_CHANGED", source_id, actor_id=actor.entity_id,
                           payload={"resource_id": resource_id, "previous": previous,
                                    "maximum": maximum, "current": current,
                                    "log": f"{actor.display_name}: maximum {resource_name(resource_id)} is now {maximum}; {current} points remain."})

    def _gain_resource(self,actor:ActorState,resource_id:str,amount:int,source_id:str,*,cost_source_id:str|None=None) -> None:
        current=actor.resources.get(resource_id);maximum=actor.resource_maximums.get(resource_id)
        if current is None or maximum is None or amount<0:raise ValueError("unknown resource")
        from . import ext
        from .typed_executor import CP_POOLS, condition_rules
        allowed = ext.run_strict("resource_gain_allowed", self, actor, resource_id, amount, source_id) if ext.has("resource_gain_allowed") else []
        if any(type(answer) is not bool for answer in allowed):
            raise ValueError("resource_gain_allowed must return None or bool")
        blocked_cp = amount > 0 and resource_id in CP_POOLS and any(row.get("no_cp_regain") for row in condition_rules(actor))
        if blocked_cp or False in allowed:
            from .resource_labels import resource_name
            self._append_event("GM_RIDER", source_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                               payload={"automated": True, "rider": f"{actor.display_name} cannot regain {resource_name(resource_id)} right now: {amount} not regained."})
            return
        gained=min(amount,maximum-current);actor.resources[resource_id]=current+gained
        if cost_source_id is not None:
            from .paid_relocation import refund
            refund(self, actor, resource_id, gained, cost_source_id)
        self._append_event("RESOURCE_GAINED",source_id,actor_id=actor.entity_id,payload={"resource_id":resource_id,"requested":amount,"gained":gained,"current":actor.resources[resource_id],
            **({"cost_source_id": cost_source_id} if cost_source_id is not None else {})})

    def _consume_economy(self,actor:ActorState,action:ActionDefinition) -> None:
        if action.economy==EconomyKind.ACTION:
            if not actor.action_available:raise ValueError("action unavailable")
            actor.action_available=False
        elif action.economy==EconomyKind.BONUS_ACTION:
            if not actor.bonus_action_available:raise ValueError("bonus action unavailable")
            actor.bonus_action_available=False
        elif action.economy==EconomyKind.REACTION:
            if not actor.reaction_available:raise ValueError("reaction unavailable")
            actor.reaction_available=False

    def _set_life_state(self, target: ActorState, state: str | None, source_id: str, *, initial_damage_excess: int | None = None) -> None:
        """Evented lifecycle seam; no healing or refunded economy is implied."""
        if state not in {None, "DYING", "STABLE", "CONSCIOUS"}:
            raise ValueError("unknown life state")
        if not target.active or (state is not None and target.current_hp != 0) or (state is None and target.current_hp <= 0):
            raise ValueError("life state does not match active creature HP")
        fresh_conscious = state == 'CONSCIOUS' and target.life_state is None
        target.life_state = state
        if state in ("DYING", "STABLE"):
            target.action_available = target.bonus_action_available = target.reaction_available = False
            target.movement_remaining_ft = 0
            self._end_concentration(target, "DYING")
        self._append_event("LIFE_STATE_CHANGED", source_id, actor_id=target.entity_id,
                           payload={"life_state": state, **({'fresh_zero_hp': True,
                               'initial_damage_excess': initial_damage_excess} if fresh_conscious else {})})

    def _defeat(self,target:ActorState,source_id:str, *, final: bool = False, initial_damage_excess: int | None = None) -> None:
        from . import ext
        if not final and target.current_hp == 0 and target.life_state is None:
            answers = ext.run_strict("zero_hp", self, target, source_id, self._active_intent)
            if not answers:
                answers = ext.run_strict("zero_hp_default", self, target, source_id, self._active_intent)
            if answers:
                if len(answers) != 1 or answers[0] not in {"DYING", "STABLE", "CONSCIOUS"}:
                    raise ValueError("one zero_hp plugin must choose DYING, STABLE or CONSCIOUS")
                if target.current_hp > 0:
                    # The zero-HP resolution healed the creature (a late-entry
                    # recovery inside the granted step restores Hit Points).
                    # That committed outcome owns the result: a zero-HP state
                    # would contradict the creature's Hit Points.
                    return
                if target.life_state is None:  # a plugin may already have evented this state (No Guest Dies Alone)
                    self._set_life_state(target, answers[0], source_id, initial_damage_excess=initial_damage_excess)
                return
        if not final and target.life_state is not None:
            return  # further 0-HP damage is evented; the plugin owns death/failure rules
        target.life_state = None
        target.current_hp=0;target.active=False;target.action_available=False;target.bonus_action_available=False;target.reaction_available=False;target.movement_remaining_ft=0
        self._end_concentration(target,"ENTITY_DEFEATED")
        if target.summon is not None:
            from . import summons  # a destroyed creature leaves the map
            summons.on_defeat(self,target)
        self._append_event("ENTITY_DEFEATED",SYSTEM_DEFEAT,actor_id=target.entity_id,payload={"nonlethal":True,"defeating_source":source_id})

    @contextmanager
    def victory_deferred(self):
        """Resolve one effect for all of its recipients before deciding the match.

        Area effects are simultaneous: a recipient defeated early (including the
        effect's own user) must not end combat before the remaining recipients
        resolve. While held, victory checks are recorded as pending; when the
        outermost hold completes normally the ordinary check runs once, so a
        batch that defeats both sides ends as DRAW_SIMULTANEOUS. An exception
        (pause or rollback) discards the pending check with the transaction.
        Transient engine attributes only; no saved state.
        """
        depth = getattr(self, "_victory_hold", 0)
        self._victory_hold = depth + 1
        completed = False
        try:
            yield
            completed = True
        finally:
            self._victory_hold = depth
            if not depth:
                pending, self._victory_pending = getattr(self, "_victory_pending", False), False
                if completed and pending:
                    self._check_victory()

    def _check_victory(self) -> None:
        if getattr(self, "_victory_hold", 0):
            self._victory_pending = True
            return
        from .relations import enabled, peaceful_result
        if enabled(self):
            result = peaceful_result(self)
            if result is not None:
                self._end_match(*result)
            return
        teams={a.team_id for a in self.state.actors.values() if a.primary_combatant}
        active={team:sum(1 for a in self.state.actors.values() if a.primary_combatant and a.team_id==team and a.active) for team in teams}
        live=[team for team,count in active.items() if count>0]
        if len(live)==1:self._end_match(TerminalKind.VICTORY,live[0],"Opposing primary combatants are inactive.")
        elif len(live)==0:self._end_match(TerminalKind.DRAW_SIMULTANEOUS,None,"Both teams lost all primary combatants in one atomic resolution.")

    def _end_match(self,kind:TerminalKind,winning_team_id:str|None,reason:str) -> None:
        if self.state.terminal_result is not None:return
        # General scene lifecycle seam. Providers end only their explicitly
        # scene-bound effects before MATCH_ENDED, keeping that event terminal.
        from . import ext
        ext.run_strict("scene_end", self)
        terminal=TerminalResult(kind=kind,winning_team_id=winning_team_id,reason=reason,event_sequence=self.state.event_sequence+1)
        self.state.terminal_result=terminal
        self._append_event("MATCH_ENDED",SYSTEM_VICTORY,payload=terminal.model_dump(mode="json"))

    def _assert_invariants(self) -> None:
        from . import ext
        occupied: set[tuple[int, int, int]] = set()
        occupants = []
        for actor in self.state.actors.values():
            if not 0<=actor.current_hp<=actor.maximum_hp:raise ValueError("HP invariant")
            if actor.temporary_hp<0 or actor.movement_remaining_ft<0:raise ValueError("nonnegative invariant")
            for rid,value in actor.resources.items():
                if not 0<=value<=actor.resource_maximums[rid]:raise ValueError(f"resource invariant {rid}")
            if actor.active and self._on_battlefield(actor):
                # Destroyed/inactive actors leave the map. Their retained anchor
                # is replay data, not occupied or traversable geometry.
                actor_cells = set(self._actor_volume(actor))
                if not actor_cells:
                    raise ValueError("empty footprint invariant")
                if not self.grid.volume_legal(actor.position, footprint=self._footprint(actor)):
                    from .terrain_materials import profiles, placement_legal
                    if not any(placement_legal(self, actor, actor.position, row['mode'])
                               for row in profiles(self, actor)):
                        raise ValueError("footprint position invariant")
                if occupied & actor_cells:
                    for other in occupants:
                        if not set(self._actor_volume(other)) & actor_cells:
                            continue
                        pair = self._shared_occupancy_pair(actor.entity_id, other.entity_id)
                        general_share = any(reply is True for reply in ext.run_strict('shared_space', self, actor, other))
                        if pair is None or (not general_share and not set(self._actor_volume(pair[0])) <= set(self._actor_volume(pair[1]))):
                            raise ValueError("occupied footprint invariant")
                occupied.update(actor_cells)
                occupants.append(actor)
            if not actor.active and (actor.action_available or actor.bonus_action_available):raise ValueError("inactive economy invariant")
        if [e.sequence for e in self.events]!=list(range(1,len(self.events)+1)):raise ValueError("event sequence invariant")
        if self.state.pending_resolution and self.state.pending_resolution.reaction_depth>2:raise ValueError("reaction depth invariant")

    # ------------------------------------------------------------------
    # Utility calculations
    # ------------------------------------------------------------------
    @contextmanager
    def d20_scope(self, context):
        """Ephemeral native roll metadata; immutable stack ownership survives previews.

        A nested check scope for the same actor and reason keeps the caller's own
        metadata (check kind, purpose, hazards) that it does not restate, so a
        provider reading the current d20 context during the draw still sees it; an
        unrelated nested roll, of another kind, actor or reason, still starts from
        its own fields alone.
        """
        frame = dict(context)
        if frame.get("kind") not in {"save", "attack", "check"}:
            raise ValueError("d20_scope requires a save, attack or check kind")
        previous = getattr(self, "_d20_scopes", ())
        outer = previous[-1] if previous else None
        if (outer is not None and frame.get("kind") == "check" and outer.get("kind") == "check"
                and frame.get("actor_id") == outer.get("actor_id")
                and frame.get("reason") == outer.get("reason")):
            frame = {**outer, **frame}
            # Own receipt list: receipts of this nested check must not leak into the outer roll (review F16R2 #1).
            frame["mode_sources"] = list(outer.get("mode_sources", ()))
        self._d20_scopes = previous + (frame,)
        try:
            yield
        finally:
            self._d20_scopes = previous
            from . import ext
            ext.run("roll_context_end", self, frame)

    def d20_context(self, roll=None):
        """Read-only context for the current d20; unknown metadata stays None."""
        frames = getattr(self, "_d20_scopes", ())
        frame = frames[-1] if frames else None
        if roll is not None and frame is not None:
            expected = frame.get("reason")
            if expected is None:
                suffix = frame.get("ability") if frame["kind"] == "save" else frame.get("attack_index", 1)
                expected = (f"{frame['kind'].upper()}:{frame.get('source_id')}:{suffix}"
                            if frame["kind"] != "check" else f"CHECK:{frame.get('source_id')}")
            if frame.get("actor_id") != roll.actor_id or expected != roll.reason:
                frame = None
        if frame is None:
            if roll is None or roll.natural_result is None:
                return None
            reason = str(roll.reason or "")
            if reason.startswith("SAVE:"):
                source, _, ability = reason[5:].rpartition(":")
                frame = {"kind": "save", "actor_id": roll.actor_id, "target_id": roll.actor_id,
                         "source_id": source, "ability": ability}
            elif reason.startswith("ATTACK:"):
                source, _, _index = reason[7:].rpartition(":")
                frame = {"kind": "attack", "actor_id": roll.actor_id, "source_id": source}
            elif reason.startswith("CHECK:"):
                frame = {"kind": "check", "actor_id": roll.actor_id, "source_id": reason[6:]}
            else:
                return None
        keys = ("kind", "actor_id", "target_id", "ability", "skill", "dc", "ac", "source_id",
                "source_actor_id", "attack_index", "triggering_action_id", "triggering_actor_id",
                "include_stored_save_bonuses")
        result = {key: frame.get(key) for key in keys}
        if frame.get("check_kind") is not None:
            result["check_kind"] = frame["check_kind"]
        if "hazards" in frame:
            result["hazards"] = list(frame.get("hazards") or ())
        if frame.get('used_tool') is not None:
            result['used_tool'] = dict(frame['used_tool'])
        active = getattr(self, "_active_intent", None)
        result["triggering_action_id"] = result["triggering_action_id"] or getattr(self, "_active_action_source_id", None)
        result["triggering_actor_id"] = result["triggering_actor_id"] or (active.actor_id if active else None)
        result["named"] = list(frame.get("named") or ())
        result["save_modes"] = list(frame.get("save_modes") or ())
        result['mode_sources'] = [dict(row) for row in frame.get('mode_sources', ())]
        from copy import deepcopy
        result.update({key: deepcopy(frame.get(key)) for key in
                       ('effect_origin', 'effect_origin_cells', 'area', 'save_geometry')})
        result['effect_origin_kind'] = frame.get('effect_origin_kind', 'unknown')
        spec = frame.get("spec")
        result["spec"] = None
        result["attack_delivery"] = None
        if spec is not None:
            result["target_id"] = spec.get("resolved_target_id") or result["target_id"]
            result["spec"] = {key: spec[key] for key in ("range_ft", "reach_ft", "attack_bonus", "declaration_cover", "resolved_target_id", "critical_threshold", "attack_name")
                              if key in spec}
            actor = self.state.actors.get(result["actor_id"])
            target = self.state.actors.get(result["target_id"])
            if actor is not None:
                from .attack_provenance import describe
                result["attack_delivery"] = describe(self, actor, spec, result["source_id"])["delivery"]
            if actor is not None and target is not None:
                _, result["ac"] = self._attack_defense(actor, target, spec, result["source_id"])
        from .native_reactions import context as reaction_context
        reaction = reaction_context(self, result["actor_id"], result["source_id"])
        if reaction and result["kind"] == "attack":
            result.update(economy="REACTION", reaction_source_id=reaction["reaction_source_id"])
        return result

    def _attack_defense(self, actor, target, spec, source_id=None):
        """The shared, current AC calculation used by both d20 context and hit resolution."""
        cover = 0
        if spec.get("range_ft") is not None:
            cover = self._raw_cover_bonus_actor_to_actor(actor, target)
            if self._has_condition(target, "condition:an_eui.break_guard.no_half_cover"):
                cover = 0
        cover = max(cover, spec.get("declaration_cover", 0))
        from .directional_cover import cover_bonus
        from .attack_provenance import describe
        cover = cover_bonus(self, actor, target, ranged=spec.get("range_ft") is not None,
                            base=cover, attack=describe(self, actor, spec, source_id))
        from .shot_geometry import reduce_cover
        cover = reduce_cover(self, actor, target, cover)
        return cover, target.armor_class + cover + self._ac_modifier(target)

    def _attack_checkpoint(self, actor, target, source_id, intent, attack_index=1, context=None):
        from . import ext
        if not ext.has("before_attack"):
            return []
        return ext.run_strict("before_attack", self, actor, target, intent,
                              {**(context or {}), "actor_id": actor.entity_id, "target_id": target.entity_id,
                               "source_id": source_id, "attack_index": attack_index})

    def _dex_checkpoint(self, target, ability, dc, source_id, context=None):
        from . import ext
        if ability != "DEX" or not ext.has("before_dex_save"):
            return []
        return ext.run_strict("before_dex_save", self, target, self._active_intent,
                              {**(context or {}), "target_id": target.entity_id,
                               "source_id": source_id, "ability": ability, "dc": dc})

    def roll_check(self, *, modifier: int, actor_id: str, reason: str,
                   ability: str = "", skill: str | None = None, modes=(),
                   against_creature=None, hazards=()) -> RollRecord:
        """Draw a check after resolving native and independent mode sources together.

        Callers supply unresolved ADVANTAGE/DISADVANTAGE contributions, never a
        previously cancelled NORMAL. Unknown ability/skill stays unnamed; ALL
        rules still apply. This query never consumes conditions: the existing
        post-draw checkpoint owns next-roll consumption, including cancellation.
        Record the returned roll and outcome in the caller's existing event shape.
        """
        from .typed_executor import check_modes
        from .ext.ability_source import combine_modes

        actor = self.state.actors[actor_id]
        with self.d20_scope({'kind': 'check', 'actor_id': actor_id, 'reason': reason,
                             'ability': ability, 'skill': skill}):
            sources = check_modes(actor, ability, skill, engine=self,
                                  against_creature=against_creature, hazards=tuple(hazards))
            sources.update(m for m in modes if m in {"ADVANTAGE", "DISADVANTAGE"})
            from .roll_reasons import remember, source, condition_source
            remember(self, [source(self, m, effect='Check-specific effect') for m in modes])
            from .typed_executor import condition_rule_instances
            for condition, row in condition_rule_instances(actor, engine=self):
                table = row.get('check_mode') or {}
                for key in (ability, skill, 'ALL'):
                    mode = table.get(key) if key else None
                    if mode in {'ADVANTAGE', 'DISADVANTAGE'}:
                        remember(self, [condition_source(self, actor, row, mode,
                            f'{ability or "ability"} check', condition=condition)])
            known = {r['kind'].upper() for r in self._d20_scopes[-1].get('mode_sources', ())}
            remember(self, [source(self, m, effect='Check-specific effect') for m in sources - known])
            return self.roller.d20(modifier=modifier, actor_id=actor_id, reason=reason,
                                   mode=combine_modes(sources))

    def direct_attack_mode(self, actor: ActorState, target: ActorState | None = None, *, modes=()) -> str:
        """Resolve native modes for an auxiliary attack, including attacks on objects.

        Supply independent unresolved modes. Creature targets use the normal
        attack query; objects supply no incoming creature rules. Querying never
        consumes an allowance; an actual d20 draw uses the shared checkpoint.
        """
        from .ext.ability_source import combine_modes
        sources = set(modes)
        from .roll_reasons import ExplainedMode, source, condition_source
        receipts = [source(self, m, effect='Attack-specific effect') for m in modes if m in {'ADVANTAGE', 'DISADVANTAGE'}]
        if target is not None:
            self._attack_mode(actor, target, contributions=sources, reasons=receipts)
        else:
            from .ext.standard_conditions import roll_rules
            for condition, row in roll_rules(self, actor, with_sources=True):
                mode = row.get('attacks_have')
                sources.add(mode)
                if mode in {'ADVANTAGE', 'DISADVANTAGE'}:
                    receipts.append(condition_source(self, actor, row, mode, 'your attack roll', condition=condition))
            sources.update(m.value for m in actor.modifiers.values()
                           if m.target_field == "attack_mode" and not m.consumed)
        return ExplainedMode(combine_modes(sources), receipts)

    def _save_mode_contributions(self, target, ability, dc, source_id, context):
        """Collect independent native modes and numeric grants exactly once.

        Mode-only callers set context.mode_only so providers consume matching
        next-save modes without selecting or spending a numeric support value.
        Cancellation belongs to the caller after all sources have contributed.
        A provider may return a bare mode (or list) or an attributed dict
        reply. Both produce a receipt, so every independent grant stays listed
        on the roll (review 2026-10-16 finding 3; review F9RSC finding 1).
        """
        from . import ext
        from .roll_reasons import source
        supplied = ext.run_strict('save_mode', self, target, ability, dc, source_id, context)
        bonus = 0
        for grant in ext.run_checkpoint('save_mode_contributions', self, target, ability, dc, source_id, context):
            if (not isinstance(grant, dict) or set(grant) != {'bonus', 'modes'}
                    or type(grant['bonus']) is not int or not isinstance(grant['modes'], (list, tuple))
                    or any(mode not in ('ADVANTAGE', 'DISADVANTAGE') for mode in grant['modes'])):
                raise ext.CheckpointError('Save mode contributions require integer bonus and explicit modes')
            bonus += grant['bonus']
            supplied.extend(grant['modes'])
        modes = set()
        receipts = []
        for value in supplied:
            if value is None:
                continue
            if isinstance(value, dict):
                granted = value.get('mode')
                if granted not in ('ADVANTAGE', 'DISADVANTAGE'):
                    raise ValueError('save_mode must return None, a mode, or a list/tuple of modes')
                modes.add(granted)
                if isinstance(value.get('effect'), str) and isinstance(value.get('why'), str):
                    receipts.append(source(self, granted, effect=value['effect'],
                                           owner=value.get('owner'), why=value['why']))
                else:
                    receipts.append(source(self, granted, effect='Save-specific effect',
                                           why=f'{ability} saving throw'))
                continue
            values = value if isinstance(value, (list, tuple)) else (value,)
            if any(mode not in ('ADVANTAGE', 'DISADVANTAGE') for mode in values):
                raise ValueError('save_mode must return None, a mode, or a list/tuple of modes')
            modes.update(values)
            # An anonymous grant (bare mode) keeps its own receipt even when an
            # earlier named source already gives the same kind (review F9RSC finding 1).
            receipts.extend(source(self, mode, effect='Save-specific effect', why=f'{ability} saving throw')
                            for mode in values)
        return modes, bonus, receipts

    def direct_save_mode(self, target: ActorState, ability: str, dc: int, source_id: str, *, modes=()) -> str:
        """Native mode query for raw saves whose caller owns special outcome handling.

        Combine independent sources before cancellation. This does not introduce
        ordinary automatic failure into exceptional saves (such as a dead body's
        continuity save), nor create an extra save event. Matching next-save
        mode grants are consumed once; numeric support values are not spent.
        """
        from .ext.standard_conditions import roll_rules
        from .ext.ability_source import combine_modes
        sources = set(modes)
        from .roll_reasons import ExplainedMode, source, condition_source, unique_sources
        receipts = [source(self, m, effect='Save-specific effect') for m in modes if m in {'ADVANTAGE', 'DISADVANTAGE'}]
        for condition, row in roll_rules(self, target, with_sources=True):
            mode = (row.get('save_mode') or {}).get(ability)
            sources.add(mode)
            if mode in {'ADVANTAGE', 'DISADVANTAGE'}:
                receipts.append(condition_source(self, target, row, mode, f'{ability} saving throw', condition=condition))
        sources.intersection_update({"ADVANTAGE", "DISADVANTAGE"})
        context = {**(self.d20_context() or {}), "kind": "save", "actor_id": target.entity_id,
                   "target_id": target.entity_id, "ability": ability, "dc": dc,
                   "source_id": source_id, "save_modes": sorted(sources), "mode_only": True}
        supplied, _bonus, supplied_receipts = self._save_mode_contributions(target, ability, dc, source_id, context)
        sources.update(supplied)
        receipts.extend(source(self, m, effect='Save-specific effect', why=f'{ability} saving throw')
                        for m in supplied)
        return ExplainedMode(combine_modes(sources), unique_sources([r for r in receipts if r] + supplied_receipts))

    def _roll_save(self,target:ActorState,ability:str,dc:int,source_id:str,extra_mode:str|None=None,
                   *, checkpoint_context=None, target_check=None, roll_context=None,
                   outcome_receipt=None, receipt_source_id: str | None = None) -> RollRecord | None:
        """Resolve a native save; an optional caller-owned outcome_receipt gets
        the numeric total before a forced outcome and its provider provenance.
        This transient receipt lets settlement distinguish support from rescue
        without changing the effective total returned to legacy consumers.
        A repeat-grant may identify itself on the receipt while the actual
        saving effect keeps its native classification, caster and save hooks.
        """
        source_action = self.action_catalog.get(source_id)
        source_actor_id = ((roll_context or {}).get("source_actor_id") or (checkpoint_context or {}).get("actor_id")
                           or (source_action.owner_id if source_action is not None else None))
        with self.d20_scope({**(roll_context or {}), "kind": "save", "actor_id": target.entity_id,
                             "target_id": target.entity_id, "ability": ability, "dc": dc, "source_id": source_id,
                             "source_actor_id": source_actor_id}):
            from .roll_reasons import remember
            remember(self, (roll_context or {}).get('mode_sources', ()))
            checkpoint_results = self._dex_checkpoint(target, ability, dc, source_id, checkpoint_context)
            if checkpoint_results and target_check is not None and not target_check():
                self._append_event("GM_RIDER", source_id, target_ids=(target.entity_id,),
                                   payload={"rider": "The defender left the effect before the Dexterity save; it is no longer affected."})
                return None
            contributed_modes = set((roll_context or {}).get('save_modes') or [])
            if extra_mode in {"ADVANTAGE","DISADVANTAGE"}:
                contributed_modes.add(extra_mode)
            charge = next((c for c in target.conditions.values() if c.condition_id in {"condition:lee_jia.lightning_charge.self","condition:lee_jia.lightning_charge.willing_creature"}), None)
            if ability == "DEX" and charge is not None:
                contributed_modes.add('ADVANTAGE')
            from .typed_executor import condition_rules
            auto_fail=False
            from .ext.standard_conditions import roll_rules
            for condition, row in roll_rules(self, target, with_sources=True):
                typed_mode=(row.get("save_mode") or {}).get(ability)
                if typed_mode in {'ADVANTAGE', 'DISADVANTAGE'}:
                    contributed_modes.add(typed_mode)
                    from .roll_reasons import remember, condition_source
                    remember(self, [condition_source(self, target, row, typed_mode, f'{ability} saving throw', condition=condition)])
                if typed_mode=="AUTO_FAIL":auto_fail=True
            from . import ext
            checkpoint_modes = {r.get('mode') for r in checkpoint_results if isinstance(r, dict)
                                and r.get('mode') in {'ADVANTAGE', 'DISADVANTAGE'}}
            mode_context = {**self.d20_context(), 'save_modes': sorted(contributed_modes | checkpoint_modes)}
            supplied_modes, source_bonus, supplied_receipts = self._save_mode_contributions(target, ability, dc, source_id, mode_context)
            contributed_modes.update(supplied_modes)
            contributed_modes.update(checkpoint_modes)
            if any(ability.upper() in (row.get('no_save_advantage') or []) for row in condition_rules(target)):
                contributed_modes.discard('ADVANTAGE')
            mode = next(iter(contributed_modes)) if len(contributed_modes) == 1 else 'NORMAL'
            from .roll_reasons import remember, source
            known = {r['kind'].upper() for r in self._d20_scopes[-1].get('mode_sources', ())}
            remember(self, [source(self, m, effect='Save-specific effect', why=f'{ability} saving throw')
                            for m in contributed_modes - known])
            # Every provider grant keeps its own receipt: attributed replies
            # name their ability; anonymous grants stay listed so removing a
            # named source cannot appear to remove the only stated cause
            # (review 2026-10-16 finding 3).
            remember(self, [r for r in supplied_receipts if r])
            self._d20_scopes[-1]['mode_sources'] = [r for r in self._d20_scopes[-1].get('mode_sources', ())
                                                   if r['kind'].upper() in contributed_modes]
            self._d20_scopes[-1]['mode_sources'] = [r for r in self._d20_scopes[-1].get('mode_sources', ())
                                                   if r['kind'].upper() in contributed_modes]
            bonuses = ext.run_strict('save_bonus', self, target, ability, dc, source_id, self._active_intent) if ext.has('save_bonus') else []
            if any(type(bonus) is not int for bonus in bonuses):
                raise ValueError('save_bonus must return None or an integer')
            from .save_context import bonus_details
            detailed_bonus, contributions = bonus_details(self, target, ability, dc, source_id, self._active_intent)
            additional_bonus = (roll_context or {}).get('additional_bonus', 0)
            if type(additional_bonus) is not int:
                raise ValueError('Save additional_bonus must be an integer')
            modifier = target.saving_throws.get(ability, 0) + sum(bonuses) + detailed_bonus + source_bonus + additional_bonus
            roll=self.roller.d20(modifier=modifier,actor_id=target.entity_id,reason=f"SAVE:{source_id}:{ability}",mode=mode)
            if auto_fail:
                roll=roll.model_copy(update={"total":-1})
                self._append_event("SAVE_AUTO_FAILED",source_id,actor_id=target.entity_id,payload={"ability":ability})
            self._record_roll(roll)
            true_name_used = False
            if target.entity_id == LING and target.resources.get("resource:ling_qi.mirror_trace", 0) >= 1 and self._active_intent is not None:
                decision = self._reaction_decision(self._active_intent, "SAVE_RESULT_BEFORE_DECLARED", LING, "action:ling_qi.true_name_witness")
                if decision is not None and decision.selection == "USE":
                    from .paid_relocation import activation as relocation_activation

                    with relocation_activation(self, target, "action:ling_qi.true_name_witness", independent=True):
                        self._spend_resource(target, "resource:ling_qi.mirror_trace", 1, "action:ling_qi.true_name_witness")
                        roll = roll.model_copy(update={"modifier":roll.modifier + 3, "total":roll.total + 3})
                        true_name_used = True
                        self._append_event("REACTION_RESOLVED", "action:ling_qi.true_name_witness", actor_id=LING, target_ids=(LING,), payload={"checkpoint":"SAVE_RESULT_BEFORE_DECLARED","bonus":3,"source_save":source_id})
            if target.entity_id in getattr(self, "typed_actor_ids", set()):
                from .typed_reactions import on_save
                roll = on_save(self, target, ability, dc, roll, source_id)
            outcome_details = {}
            outcomes = ext.run_strict("save_result_outcome", self, target, ability, dc, roll, source_id, self._active_intent)
            if len(outcomes) > 1:
                raise ValueError("one provider must own a forced save outcome")
            for outcome in outcomes:
                if (not isinstance(outcome, dict) or outcome.get("outcome") not in {"success", "failure"}
                        or not isinstance(outcome.get("source_id"), str) or not outcome["source_id"]):
                    raise ValueError("save_result_outcome requires outcome and source_id")
                effective = max(dc, roll.total) if outcome["outcome"] == "success" else min(dc - 1, roll.total)
                delta = effective - roll.total
                outcome_details = {"forced_outcome": outcome["outcome"], "outcome_source_id": outcome["source_id"],
                                   "total_before_outcome": roll.total}
                # Numeric legacy consumers receive the declared outcome too;
                # the original draw remains in the recorded roll/rewrite receipt.
                roll = roll.model_copy(update={"total": effective, "modifier": roll.modifier + delta})
            if outcome_receipt is not None:
                outcome_receipt.update({"total_before_outcome": roll.total, **outcome_details})
            self._append_event("SAVE_ROLLED",receipt_source_id or source_id,actor_id=target.entity_id,payload={**roll.model_dump(mode="json"),"dc":dc,"success":((getattr(self, "_typed_roll_outcome", None) or {}).get(target.entity_id) == "success"
                if (getattr(self, "_typed_roll_outcome", None) or {}).get(target.entity_id) in ("success", "failure") else roll.total>=dc),"true_name_witness":true_name_used,
                **({'save_bonus_contributions': contributions} if contributions else {}), **outcome_details,
                **({'original_save_source_id': source_id} if receipt_source_id else {})})
            if ability == "DEX" and charge is not None:
                self._remove_lightning_charge_condition(target, charge.instance_id, "DEX_SAVE_DISCHARGE")
            return roll

    def _attack_mode(self,actor:ActorState,target:ActorState, *, removed=None, provenance=None, contributions=None, masked=None, chosen_modes=(), ranged=None, reasons=None) -> str:
        from .typed_executor import condition_rules
        from .target_knowledge import can_see
        masked = masked or {}
        from . import attack_modes
        removed = attack_modes.removed(self, actor, target) if removed is None else removed
        provenance = provenance or {}
        actor_modes = [m for mid, m in actor.modifiers.items() if provenance.get(mid) not in removed]
        target_modes = [m for mid, m in target.modifiers.items() if provenance.get(mid) not in removed]
        from .roll_reasons import source, effect_name, condition_source
        receipts = []
        for holder, modifiers, fields in ((actor, actor_modes, ('attack_mode', 'attack_mode_vs')),
                                          (target, target_modes, ('incoming_attack_mode',))):
            for modifier in modifiers:
                value = str(modifier.value)
                if modifier.consumed or modifier.target_field not in fields:
                    continue
                if modifier.target_field == 'attack_mode_vs' and value.partition(':')[2] != target.entity_id:
                    continue
                receipts.append(source(self, value.partition(':')[0],
                    effect=effect_name(self, modifier.source_definition_id), owner=holder,
                    why='attacks against this target' if holder is target else 'your attack roll'))
        disadvantage=any(m.target_field=="attack_mode" and m.value=="DISADVANTAGE" and not m.consumed for m in actor_modes)
        advantage=any(m.target_field=="incoming_attack_mode" and m.value=="ADVANTAGE" and not m.consumed for m in target_modes)
        advantage=advantage or any(m.target_field=="attack_mode" and m.value=="ADVANTAGE" and not m.consumed for m in actor_modes)
        disadvantage=disadvantage or any(m.target_field=="incoming_attack_mode" and m.value=="DISADVANTAGE" and not m.consumed for m in target_modes)
        # Vex (owner 2026-09-26): Advantage on the next attack against that one creature.
        advantage=advantage or any(m.target_field=="attack_mode_vs" and m.value==f"ADVANTAGE:{target.entity_id}" for m in actor_modes)
        # Guarding Method: its next attack against that one creature has Disadvantage.
        disadvantage=disadvantage or any(m.target_field=="attack_mode_vs" and m.value==f"DISADVANTAGE:{target.entity_id}" for m in actor_modes)
        # Grappled (2024): Disadvantage on attacks against anyone but the grappler.
        from .typed_executor import CONDITION_PREFIX, rules as typed_rules
        table=typed_rules()["conditions"]
        for c in actor.conditions.values():
            if c.condition_id.startswith(CONDITION_PREFIX) and target.entity_id!=c.source_actor_id:
                mode=table.get(c.condition_id[len(CONDITION_PREFIX):],{}).get("attacks_others_have")
                advantage=advantage or mode=="ADVANTAGE"
                disadvantage=disadvantage or mode=="DISADVANTAGE"
                receipts.append(source(self, mode, effect='Grappled', owner=actor,
                                       why='attacking a creature other than your grappler'))
        # Typed conditions: what each one does is data (combat/rules/typed_conditions.json).
        for condition, row in attack_modes.condition_rows(actor, removed, incoming=False, engine=self, masked=masked.get(actor.entity_id, ()), with_sources=True):
            receipts.append(condition_source(self, actor, row, row.get('attacks_have'), 'your attack roll', condition=condition))
            if ranged is False:
                receipts.append(condition_source(self, actor, row, row.get('melee_attacks_have'), 'your melee attack roll', condition=condition))
            advantage=advantage or row.get("attacks_have")=="ADVANTAGE"
            disadvantage=disadvantage or row.get("attacks_have")=="DISADVANTAGE"
            if ranged is False:
                advantage=advantage or row.get("melee_attacks_have")=="ADVANTAGE"
                disadvantage=disadvantage or row.get("melee_attacks_have")=="DISADVANTAGE"
        for condition, row in attack_modes.condition_rows(target, removed, incoming=True, engine=self, masked=masked.get(target.entity_id, ()), with_sources=True):
            receipts.append(condition_source(self, target, row, row.get('attacked_with'), 'attacks against this creature', condition=condition))
            advantage=advantage or row.get("attacked_with")=="ADVANTAGE"
            disadvantage=disadvantage or row.get("attacked_with")=="DISADVANTAGE"
            visible_mode = row.get('attacked_with_if_attacker_visible')
            if visible_mode and can_see(self, target, actor):
                receipts.append(condition_source(self, target, row, visible_mode, 'the target can see the attacker', condition=condition))
                advantage=advantage or visible_mode=='ADVANTAGE'
                disadvantage=disadvantage or visible_mode=='DISADVANTAGE'
            if row.get("attacked_within_5ft") or row.get("attacked_beyond_5ft"):  # Prone: Advantage only from 5 ft
                mode=row.get("attacked_within_5ft") if self._distance_actor_to_actor(actor,target)<=5 else row.get("attacked_beyond_5ft")
                receipts.append(condition_source(self, target, row, mode,
                    'target is within 5 feet' if self._distance_actor_to_actor(actor,target)<=5 else 'target is more than 5 feet away', condition=condition))
                advantage=advantage or mode=="ADVANTAGE"
                disadvantage=disadvantage or mode=="DISADVANTAGE"
        geometry_reasons = []
        for mode, cause in attack_modes.geometry_modes(self, actor, target, ranged, provenance=provenance, reasons=geometry_reasons):
            if f'{mode}:{cause}' in removed:
                continue
            advantage = advantage or mode == 'ADVANTAGE'
            disadvantage = disadvantage or mode == 'DISADVANTAGE'
            if not cause and any(r['kind'].upper() == mode for r in geometry_reasons):
                continue
            receipts.append(source(self, mode, effect='Visibility' if cause == 'obscured' else 'Attack geometry',
                why='attacker cannot see the target clearly' if mode == 'DISADVANTAGE' and cause == 'obscured'
                else 'the target cannot see the attacker' if mode == 'ADVANTAGE' else 'the attack path imposes this mode'))
        receipts.extend(geometry_reasons)
# Main's source-independent, pure mode contributions and the chosen typed
        # modes compose before cancellation.
        modes = attack_modes.contributed(self, actor, target)
        advantage = advantage or "ADVANTAGE" in modes
        disadvantage = disadvantage or "DISADVANTAGE" in modes
        advantage = advantage or "ADVANTAGE" in chosen_modes
        disadvantage = disadvantage or "DISADVANTAGE" in chosen_modes
        # The branch's singular attack_mode_contribution seam is a separate
        # documented hook, so its providers still contribute here. Both sets
        # compose before the removal pass below. A provider may return a bare
        # mode string or an explicitly attributed dict reply (mode plus effect
        # and why strings, mirroring geometry replies); attribution keeps
        # independent same-kind effects individually visible, and a bare reply
        # still records the shared generic receipt so removing the named source
        # cannot leave the roll's penalty unexplained (review 2026-10-16
        # finding 3).
        bare_contributes = set()
        from . import ext
        from .roll_reasons import source as mode_source
        for reply in ext.run_strict("attack_mode_contribution", self, actor, target):
            if isinstance(reply, dict) and reply.get('mode') in {"ADVANTAGE", "DISADVANTAGE"} and not reply.get('cause'):
                # A bare dict reply is an unattributed contribution, not a
                # geometry token; only a cause-bearing reply goes through the
                # strict typed-contribution gate.
                contribution = (reply['mode'], "")
            else:
                contribution = attack_modes.typed_contribution(reply)
            if not contribution:
                raise ValueError("attack_mode_contribution requires a roll mode or an attributed dict reply")
            mode, _cause = contribution
            advantage = advantage or mode == "ADVANTAGE"
            disadvantage = disadvantage or mode == "DISADVANTAGE"
            if isinstance(reply, dict) and isinstance(reply.get('effect'), str) and isinstance(reply.get('why'), str):
                receipts.append(mode_source(self, mode, effect=reply['effect'],
                                            owner=reply.get('owner'), why=reply['why']))
            else:
                bare_contributes.add(mode)
        if "ADVANTAGE" in removed:advantage=False
        receipts = [r for r in receipts if r and not (r['kind'] == 'advantage' and 'ADVANTAGE' in removed)]
        # Chosen and bare contributions each stay stated: unique_sources
        # collapses only literally identical rows, never a distinct same-kind
        # source (review 2026-10-16 finding 3).
        receipts.extend(mode_source(self, m, effect='Chosen attack effect', owner=actor,
                                    why='choosing this ability accepts this roll mode')
                        for m in chosen_modes)
        known = {r['kind'].upper() for r in receipts}
        for active, mode in ((advantage, 'ADVANTAGE'), (disadvantage, 'DISADVANTAGE')):
            if active and ((mode not in known and mode not in chosen_modes) or mode in bare_contributes):
                if not any(r['kind'].upper() == mode and r['effect'] == 'Attack-specific effect' for r in receipts):
                    receipts.append(source(self, mode, effect='Attack-specific effect',
                                           why='applies to this roll'))
        receipts = [r for r in receipts if r and not (r['kind'] == 'advantage' and not advantage)
                    and not (r['kind'] == 'disadvantage' and not disadvantage)]
        if reasons is not None:
            reasons.extend(r for r in receipts if r not in reasons)
        if contributions is not None:
            contributions.update(mode for active, mode in ((advantage, "ADVANTAGE"), (disadvantage, "DISADVANTAGE")) if active)
        from .roll_reasons import ExplainedMode
        return ExplainedMode('NORMAL' if disadvantage == advantage else 'ADVANTAGE' if advantage else 'DISADVANTAGE', receipts)

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
        # A printed step granted while Stable or Unconscious lifts only the zero-Speed rule of those states (and of
        # the Unconscious condition they apply) for its own resolution (granted_movement.speed_zero_exempt).
        # Every other restraint -- grappling, an independent condition's Speed 0 -- still holds.
        exempt = getattr(self, "_speed_zero_exempt", None) == actor.entity_id
        if actor.life_state in ("DYING", "STABLE") and not exempt:return 0
        if self._has_condition(actor,"condition:core.grappled"):return 0
        from .typed_executor import condition_rule_instances
        from .ext.life_state import UNCONSCIOUS
        if any(row.get("speed_zero") for condition, row in condition_rule_instances(actor)
               if not (exempt and condition.condition_id == UNCONSCIOUS)):return 0
        from .motion import speed_adjustment
        return max(0, actor.speed_ft + speed_adjustment(self, actor))

    def _has_condition(self,actor:ActorState,condition_id:str) -> bool:
        """True when the actor carries this condition, named either by instance id or by plain name.

        A parameter may name the condition ("prone") instead of pinning one instance id: the same
        stance arrives as condition:typed.prone or condition:core.prone depending on which runtime
        applied it, and an ability that declares a printed requirement (Capoeira Spin,
        combat/ext/athletics.py) has to match either without picking a runtime. A 'condition:' id
        still matches exactly; a plain name matches the carried id's name segment (never a scope
        word such as "state"). The matcher is shared with the AI planner -- see
        combat/condition_requirements.py -- so legality and planning cannot disagree.
        """
        from .condition_requirements import condition_present
        return condition_present(actor, condition_id)
    def _can_pay(self,actor:ActorState,costs:Iterable[tuple[str,int]],*,source_id:str|None=None) -> bool:
        quoted = self.effective_costs(actor, source_id, costs) if source_id is not None else tuple(costs)
        totals = {}
        for rid, amount in quoted:totals[rid] = totals.get(rid, 0) + amount
        if all(actor.resources.get(rid,0)>=amount for rid,amount in totals.items()):
            return True
        if source_id is None:
            return False
        from .alternative_payments import options
        if options(self, actor, source_id, quoted):
            return True
        from .action_legality import cannot_pay
        cannot_pay(self, actor, source_id, totals, alternatives_checked=True)
        return False
    def _target_in_range(self,actor:ActorState,target:ActorState,action:ActionDefinition) -> bool:
        from .attack_reach import maximum
        max_ft=maximum(self,actor,action)
        from .action_geometry import valid as origin_valid
        if not origin_valid(self, actor, action):
            return False
        from .shot_geometry import route, valid, length
        routed = route(self, actor, target, action)
        if routed:
            return valid(self, actor, target, routed) and (max_ft is None or length(self, routed) <= max_ft)
        return max_ft is None or self._effect_distance(actor, target) <= max_ft
    def _obscured_cells(self) -> set[tuple[int,int]]:
        zones = [zone for zone in self.state.zones.values() if zone.active and zone.trigger_profile.get("kind")=="NOCTURNE"]
        if not self.grid.finite_heights and not any(a.position.z for a in self.state.actors.values()) and not any(z.center.z for z in zones):
            return {(p.x,p.y) for zone in zones for p in zone.affected_cells}
        return {(p.x,p.y,height) for zone in zones for p in zone.affected_cells
                for height in range(max(0, zone.center.z-zone.radius_cells), zone.center.z+zone.radius_cells+1)}
    def _hostile_difficult_cells(self,actor:ActorState) -> set[tuple[int,int]]:
        cells={(p.x,p.y) for z in self.state.zones.values() if z.active and z.trigger_profile.get("kind")=="BLACKWATER" and (owner := self.state.actors.get(z.owner_id)) is not None and relation(self, owner, actor) == ENEMY for p in z.affected_cells}
        from . import zones  # a typed ability's difficult terrain, for all or for its creator's foes (owner 2026-09-27)
        # Painted map terrain is derived, not stored in state.zones; it costs extra on its own too.
        if any(z.active and z.trigger_profile.get("kind")=="TYPED" for z in self.state.zones.values()) or zones.map_zones(self):
            cells|=zones.difficult_cells(self,actor)
        return cells
    def _in_zone(self,actor:ActorState,zone:ZoneState) -> bool:
        from .spatial_areas import zone_contains
        return zone_contains(self, actor, zone)
    def _initiative_rank(self,actor:ActorState) -> int:
        try:return self.state.initiative_order.index(actor.entity_id)
        except ValueError:return len(self.state.initiative_order)+1
    def _typed_opportunity_reach(self,actor:ActorState) -> int|None:
        from . import typed_reactions
        return typed_reactions.opportunity_reach(self, actor)
    def opportunity_eligible(self, mover, previous, nxt, *, ignore_oa_from=(), free_ft=None, reactors=None, cache=None):
        """Pure shared leave-reach query at a projected mover position.

        Reuses reaction economy, waivers, plans, perception and exemptions.
        Ask-me is eligible but never asks here; execution owns that checkpoint.
        free_ft is the projected remaining per-step exemption, not a mutation.
        Native footprint distances accept explicit positions, so an isolated
        projected actor is built lazily only for an actual leave-reach edge.
        All position-sensitive protection/ability queries still receive that
        deep copy; distant route edges never copy the mover's full runtime data.
        """
        from . import ext, typed_reactions
        if (int(mover.turn_flags.get('oa_free_ft') or 0) if free_ft is None else free_ft) > 0:
            return ()
        projected = None
        cache = {} if cache is None else cache
        eligible = []
        for hostile in self.state.actors.values() if reactors is None else reactors:
            if hostile.entity_id in ignore_oa_from or not hostile.active or relation(self, hostile, mover) != ENEMY:
                continue
            if hostile.entity_id not in cache:
                row = typed_reactions.opportunity_reaction_row(self, hostile)
                reach = None
                if typed_reactions._can_react(self, hostile, row):
                    if hostile.entity_id in getattr(self, 'typed_actor_ids', set()):
                        reach = self._typed_opportunity_reach(hostile)
                    else:
                        params = self.reaction_parameters.get('reaction:core.opportunity_attack', {}) if hostile.entity_id in self.runtime_actor_ids else BASIC_MELEE.get(hostile.entity_id, {})
                        reach = params.get('reach_ft', 5)
                cache[hostile.entity_id] = reach
            reach = cache[hostile.entity_id]
            if reach is None:
                continue
            # The caller's cache belongs to one unchanged mover/menu query.
            # Each cell occurs on many DAG edges; price its footprint distance
            # once per reactor, preserving the same 3D leave-reach predicate.
            def distance(position):
                key = ('oa_distance', mover.entity_id, hostile.entity_id,
                       position.x, position.y, position.z)
                if key not in cache:
                    cache[key] = self._distance_actor_to_actor(mover, hostile, actor_position=position)
                return cache[key]
            if not distance(previous) <= reach < distance(nxt):
                continue
            if projected is None:
                projected = mover.model_copy(deep=True, update={'position': previous})
            from .opportunity_protection import disengage_protects
            if disengage_protects(self, hostile, projected):
                continue
            if projected.turn_flags.get('spark_step_ignore_oa_from') == hostile.entity_id or ext.any_false('opportunity_allowed', self, hostile, projected):
                continue
            if hostile.entity_id in getattr(self, 'typed_actor_ids', set()) and not typed_reactions.wants_opportunity_attack(self, hostile, projected, ask=False):
                continue
            eligible.append(hostile.entity_id)
        return tuple(sorted(eligible))
    def _movement_reaction_exposure(self,actor:ActorState,path:tuple[Position,...],*,cache=None) -> list[str]:
        """Pure reach preview; an optional cache belongs to ONE actor/menu query."""
        exposed=[]
        from .target_knowledge import actors_for
        if cache is None:
            cache = {}
        if 'reactors' not in cache:
            reactors = []
            for hostile in actors_for(self, actor):
                if hostile.active and relation(self, hostile, actor) == ENEMY and hostile.reaction_available:
                    if hostile.entity_id in getattr(self,"typed_actor_ids",set()):
                        reach=self._typed_opportunity_reach(hostile)
                        if reach is None:continue
                    else:
                        reach=BASIC_MELEE.get(hostile.entity_id,{}).get("reach_ft",5)
                    reactors.append((hostile, reach))
            cache['reactors'] = reactors
        for hostile, reach in cache['reactors']:
            from .opportunity_protection import disengage_protects
            # Legacy exposure is a historical coarse threat estimate. Keep
            # its bytes unless the typed per-reactor protection path applies.
            if hostile.entity_id in getattr(self, 'typed_actor_ids', set()) and disengage_protects(self, hostile, actor):
                continue
            def within(position):
                key = (hostile.entity_id, position.x, position.y, position.z)
                if key not in cache:
                    cache[key] = self._distance_actor_to_actor(actor, hostile, actor_position=position) <= reach
                return cache[key]
            if any(within(a) and not within(b) for a,b in zip(path,path[1:])):
                exposed.append(hostile.entity_id)
        return sorted(exposed)
    def _reaction_decision(self,intent:ActionIntent,checkpoint:str,reactor_id:str,reaction_id:str, *, context:dict|None=None) -> ReactionDecision|None:
        from .choice_checkpoints import dynamic_choice
        handled, decision = dynamic_choice(self, intent, checkpoint, reactor_id, reaction_id, context)
        if handled:return decision
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
                and relation(self, ally, actor) == ALLY
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
        if self._remove_condition_instance(target, instance_id, "resource:lee_jia.lightning_charge", actor_id=LEE,
                                           payload={"instance_id":instance_id,"reason":reason}):
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

    def _expire_for_checkpoint(self,checkpoint:str,actor_id:str, *, nominal: bool = False) -> None:
        actor=self.state.actors[actor_id]
        if checkpoint=="START_OF_TURN" and actor_id==LEE:
            self._expire_all_lightning_charges(actor)
        if checkpoint=="START_OF_TURN" and actor_id==BAI:
            for zone in list(self.state.zones.values()):
                if zone.active and zone.owner_id==BAI and zone.trigger_profile.get("kind")=="SEA_RISEN":
                    from .zones import remove
                    remove(self, zone, "START_OF_BAI_NEXT_TURN")
        tokens={
            "START_OF_TURN":{"START_OF_SELF_NEXT_TURN","START_OF_TARGET_NEXT_TURN",f"START_OF_{'BAI' if actor_id==BAI else 'LEE' if actor_id==LEE else 'LING' if actor_id==LING else 'AN'}_NEXT_TURN"},
            "END_OF_TURN":{"END_OF_CURRENT_TURN","END_OF_TARGET_NEXT_TURN_OR_CONSUMED",f"END_OF_{'BAI' if actor_id==BAI else 'LEE' if actor_id==LEE else 'LING' if actor_id==LING else 'AN'}_NEXT_TURN"},
        }[checkpoint]
        for target in list(self.state.actors.values()):
            for iid,c in list(target.conditions.items()):
                if c.expires_on in tokens and (c.source_actor_id==actor_id or target.entity_id==actor_id or c.expires_on=="END_OF_CURRENT_TURN"):
                    def expire_resource():
                        if c.condition_id=="condition:ling_qi.mirror_trace_window":
                            before=target.resources.get("resource:ling_qi.mirror_trace",0);target.resources["resource:ling_qi.mirror_trace"]=0
                            self._append_event("RESOURCE_EXPIRED","resource:ling_qi.mirror_trace",actor_id=target.entity_id,payload={"before":before,"after":0})
                        if c.condition_id=="condition:bai_meizhen.moon_sea_radiance_window":
                            before=target.resources.get("resource:bai_meizhen.moon_sea_radiance",0);target.resources["resource:bai_meizhen.moon_sea_radiance"]=0
                            self._append_event("RESOURCE_EXPIRED","resource:bai_meizhen.moon_sea_radiance",actor_id=target.entity_id,payload={"before":before,"after":0})
                    self._remove_condition_instance(target, iid, SYSTEM_EXPIRATION, actor_id=actor_id,
                        payload={"instance_id":iid,"condition_id":c.condition_id,"checkpoint":checkpoint},
                        expected=c, expiring=True, before_event=expire_resource)
            for mid,m in list(target.modifiers.items()):
                if m.expires_on in tokens and (m.source_actor_id==actor_id or target.entity_id==actor_id or m.expires_on=="END_OF_CURRENT_TURN"):
                    self._remove_modifier_instance(target, mid, SYSTEM_EXPIRATION, actor_id=actor_id,
                        payload={"modifier_id":mid,"checkpoint":checkpoint}, expected=m, expiring=True)
        self._expire_typed_for_checkpoint(checkpoint, actor_id, nominal=nominal)

    def _originating_save_classification(self, action: Any, condition_id: str) -> tuple[str | None, tuple[str, ...]]:
        """The sphere and printed save categories of the save that put this condition on its holder.

        A native repeat save re-rolls a condition the engine already knows the
        source of, so the resolution republishes the classification the initial
        save published to plug-ins: the originating action's ``typed.sphere`` and
        the ``category:<tag>`` names its own save row printed. Both are read from
        the reviewed row, so any sphere's talent is classified the same way and
        no ability is named here. A condition no save produced (a direct
        application, an effect without printed categories) reports no sphere and
        no categories, which leaves such repeats exactly as they were.
        """
        typed = ((getattr(action, "parameters", None) or {}).get("typed") or {})
        wanted = str(condition_id or "").rsplit(':', 1)[-1].rsplit('.', 1)[-1]

        def rows(row: Any) -> Any:
            """This row and every row nested under its outcome branches."""
            yield row
            for key in ("on_fail", "on_success", "effects"):
                nested = row.get(key) if isinstance(row, dict) else None
                if isinstance(nested, list):
                    for child in nested:
                        yield from rows(child)

        categories: list[str] = []
        for effect in typed.get("effects") or ():
            if not isinstance(effect, dict) or effect.get("type") != "save":
                continue
            if not any(isinstance(r, dict) and r.get("type") == "condition"
                       and str(r.get("condition") or "") == wanted for r in rows(effect)):
                continue  # a save whose failing branch never put this condition here
            for tag in effect.get("save_categories") or ():
                if isinstance(tag, str) and tag and "category:" + tag not in categories:
                    categories.append("category:" + tag)
        return typed.get("sphere"), tuple(categories)

    def resolve_repeat_save(self, holder: ActorState, iid: str, c: Any, repeat: dict[str, Any], checkpoint: str, *,
                            extra_mode: str | None = None, roll_source: str | None = None) -> None:
        """Resolve a condition's turn- or event-triggered repeat save.

        Public delivery seam for plug-ins: pass the exact held instance and
        its original ability/DC, plus a descriptive trigger checkpoint. The
        same final-outcome hooks apply regardless of what triggered the save;
        no subscriber needs to infer success from a preliminary SAVE_ROLLED.
        Optional extra_mode and roll_source let an external repeat grant apply
        its printed roll mode and identify the grant in the log. Original effect
        ownership, classifications and successful-save consequences are retained.

        repeat_save_scope(engine, resolution) context managers wrap the roll and
        the exact-instance removal, so deferred plug-in results run after it and
        unwind on pauses/errors. repeat_save_failed(engine, resolution) may
        answer "SUCCESS" once; the failed die is kept and the removal records
        settled_by. With no subscriber this is the historical roll and removal.
        """
        from contextlib import ExitStack
        from . import ext
        dc = int(repeat.get("dc") or 10)
        named = [c.condition_id.rsplit(':', 1)[-1].rsplit('.', 1)[-1]]
        # Serialized consequence tags belong to this exact condition's repeat,
        # not to all saves in its source action. Missing tags preserve behavior.
        tags = repeat.get('named') or []
        if not isinstance(tags, (list, tuple)) or any(not isinstance(tag, str) for tag in tags):
            raise ValueError('repeat_save.named must be a list of consequence tags')
        named = list(dict.fromkeys([*named, *tags]))
        # The originating action's own classification, so a repeat is dispatched on the same
        # sphere and printed save categories the initial save published (see the helper).
        source_sphere, source_categories = self._originating_save_classification(
            self.action_catalog.get(c.source_definition_id), c.condition_id)
        resolution = {"holder_id": holder.entity_id, "instance_id": iid, "condition_id": c.condition_id,
                      "source_definition_id": c.source_definition_id, "source_actor_id": c.source_actor_id,
                      "ability": str(repeat.get("ability") or "CON"), "dc": dc, "named": tuple(named),
                      "source_sphere": source_sphere, "source_categories": source_categories,
                      "checkpoint": checkpoint, "roll": None, "success": None, "settled_by": None}
        with ExitStack() as scopes:
            for scope in (ext.run_strict("repeat_save_scope", self, resolution) if ext.has("repeat_save_scope") else ()):
                scopes.enter_context(scope)
            roll = self._roll_save(holder, resolution["ability"], dc, c.source_definition_id,
                                   extra_mode=extra_mode,
                                   **({'receipt_source_id': roll_source} if roll_source else {}),
                                   roll_context={'source_actor_id': c.source_actor_id, 'named': named,
                                                 'include_stored_save_bonuses': True})
            resolution["roll"], resolution["success"] = roll, roll.total >= dc
            if not resolution["success"] and holder.active and iid in holder.conditions and ext.has("repeat_save_failed"):
                answers = ext.run_strict("repeat_save_failed", self, resolution)
                if answers:
                    if len(answers) != 1 or not isinstance(answers[0], dict) or answers[0].get("result") != "SUCCESS" \
                            or not isinstance(answers[0].get("settled_by"), str):
                        raise ValueError('one repeat_save_failed plugin may answer {"result": "SUCCESS", "settled_by": <source id>}')
                    resolution["success"], resolution["settled_by"] = True, answers[0]["settled_by"]
            if resolution["success"] and iid in holder.conditions:
                payload = {"instance_id": iid, "condition_id": c.condition_id, "checkpoint": checkpoint, "repeat_save": True}
                if resolution["settled_by"] is not None:
                    payload["settled_by"] = resolution["settled_by"]
                self._remove_condition_instance(holder, iid, c.source_definition_id, actor_id=holder.entity_id,
                                                payload=payload, expected=c)
            # Benefits observe the final result after rewrites and condition settlement.
            ext.run_strict("repeat_save_final", self, resolution)

    def _expire_typed_for_checkpoint(self,checkpoint:str,actor_id:str, *, nominal: bool = False) -> None:
        """Typed abilities' expiry names whose turn it is (owner 2026-09-26). The tokens above end at the source's
        *or* the holder's turn, so a Grappled put on an enemy ended with the attacker's own turn and never reached
        the enemy's. START_OF_SOURCE_NEXT_TURN: the start of the applier's next turn. END_OF_HOLDER_NEXT_TURN: the
        end of the affected creature's turn. STAND_UP (Prone): it stands at the start of its turn for half its speed,
        unless its speed is 0."""
        from .ext.effect_durations import skipped_expiry_slots
        def source_turn_over(row,holder):  # Count nominal expiry slots without counting creature turns.
            token, source_id = row.expires_on, row.source_actor_id
            return checkpoint=="END_OF_TURN" and str(token or "").startswith("END_OF_SOURCE_TURN_AT:") and source_id==actor_id and \
                self.state.actors[actor_id].turns_started + skipped_expiry_slots(holder, row)>=int(str(token).split(":")[1])
        holder_now=self.state.actors[actor_id]
        for iid,c in list(holder_now.conditions.items()):
            if nominal or iid not in holder_now.conditions or not holder_now.active:
                continue
            if checkpoint=="START_OF_TURN" and c.data.get("burn"):  # Tianxia Burn: damage at the start of its turn
                self._commit_damage(holder_now,int(c.data["burn"]),str(c.data.get("type") or "FIRE"),c.source_definition_id,c.source_actor_id,None,reaction_depth=0)
            repeat=c.data.get("repeat_save") or {}
            if repeat and {"START_OF_TURN":"start","END_OF_TURN":"end"}[checkpoint]==repeat.get("when","end") and holder_now.active:
                # "Repeats the saving throw at the end of each of its turns, ending the effect on a success."
                self.resolve_repeat_save(holder_now, iid, c, repeat, checkpoint)
        for target in list(self.state.actors.values()):
            for iid,c in list(target.conditions.items()):
                ends=(checkpoint=="START_OF_TURN" and c.expires_on=="START_OF_SOURCE_NEXT_TURN" and c.source_actor_id==actor_id) or (
                    checkpoint=="END_OF_TURN" and c.expires_on=="END_OF_HOLDER_NEXT_TURN" and target.entity_id==actor_id) or \
                    source_turn_over(c,target)
                deadline_ends = ends
                if checkpoint=="START_OF_TURN" and c.data.get("reach_ft") is not None:
                    # A grapple ends when the grappler is down or the grappled creature is out of its reach.
                    holder=self.state.actors.get(c.source_actor_id)
                    ends=ends or holder is None or not holder.active or self._distance_actor_to_actor(holder,target)>int(c.data["reach_ft"])
                if ends:
                    self._remove_condition_instance(target, iid, SYSTEM_EXPIRATION, actor_id=actor_id,
                        payload={"instance_id":iid,"condition_id":c.condition_id,"checkpoint":checkpoint},
                        expected=c, expiring=deadline_ends)
            for mid,m in list(target.modifiers.items()):
                if (checkpoint=="START_OF_TURN" and m.expires_on=="START_OF_SOURCE_NEXT_TURN" and m.source_actor_id==actor_id) or (
                        checkpoint=="END_OF_TURN" and m.expires_on=="END_OF_HOLDER_NEXT_TURN" and target.entity_id==actor_id) or \
                        source_turn_over(m,target):
                    self._remove_modifier_instance(target, mid, SYSTEM_EXPIRATION, actor_id=actor_id,
                        payload={"modifier_id":mid,"checkpoint":checkpoint}, expected=m, expiring=True)
        if checkpoint == "START_OF_TURN" and not nominal:
            # Expiring restrictions affect this turn's allowance. Standing up spends
            # that refreshed allowance, after all speed modifiers have expired.
            speed = self._effective_speed(holder_now)
            from .movement_budget import turn_allowance
            holder_now.movement_remaining_ft = turn_allowance(self, holder_now, speed)
            from .posture import stand_up
            stand_up(self, holder_now)

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
    def _update_object(self, obj, source_id: str, actor_id: str | None = None) -> None:
        """Evented upsert; the reducer uses the same validated complete record.

        Explicit component.map_marker=1 routes nonphysical image/decoy records
        to map_images, leaving physical-object occupancy and target consumers
        untouched. Absent opt-in retains the ordinary objects collection.
        """
        from .gate2_runtime_models import RuntimeObjectState

        obj = RuntimeObjectState.model_validate(obj.model_dump(mode="json"))
        collection = self.state.map_images if (obj.component or {}).get("map_marker") == 1 else self.state.objects
        collection[obj.object_id] = obj
        self._append_event("OBJECT_UPDATED", source_id, actor_id=actor_id,
                           target_ids=(obj.object_id,), payload={"object": obj.model_dump(mode="json")})
