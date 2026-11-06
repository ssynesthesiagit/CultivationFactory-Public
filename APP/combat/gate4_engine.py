from __future__ import annotations

from typing import Any, Callable

from .gate2_engine import Gate2Engine
from .gate2_runtime_content import ACTIONS, AN, BAI, LING
from .gate2_runtime_models import ActionIntent, CandidateKind, Position, ReactionDecision
from .read_queries import candidate_pass

ReactionProvider = Callable[[dict[str, Any]], tuple[ReactionDecision | None, dict[str, Any] | None]]


class Gate4ControllerEngine(Gate2Engine):
    """Gate 2 mechanics with a controller-owned checkpoint reaction seam.

    No Gate 2 mutation or legality code is replaced. Scripted embedded reactions
    remain authoritative when present. A configured provider is consulted only
    when the accepted ActionIntent did not embed the exact reaction decision.
    """

    turn_start_via_events = True
    # _generate_legal_candidates below applies candidate_allowed itself, with
    # availability journaling; the base pass must not run it a second time.
    applies_plugin_candidate_vetoes = False

    def __init__(self, *args, **kwargs):
        self._gate4_reaction_provider: ReactionProvider | None = None
        self._gate4_reaction_cache: dict[tuple[str, str, str], ReactionDecision | None] = {}
        self.gate4_reaction_decision_records: list[dict[str, Any]] = []
        self._gate4_pending_damage: int | None = None
        self._gate4_damaged_target_id: str | None = None
        super().__init__(*args, **kwargs)

    # Walls raised in the fight (owner 2026-09-27, combat/zones.py sync_walls): the grid follows the fight's zones. A
    # zone can end inside the engine (a broken Concentration), so the grid is brought up to date whenever a zone ends
    # and before the moves are listed (a clone or a reloaded fight starts from the map's own grid).
    def _append_event(self, event_type: str, *args: Any, **kwargs: Any) -> Any:
        result = super()._append_event(event_type, *args, **kwargs)
        from .effect_endings import is_ending_event
        depth = getattr(self, "_ext_event_depth", 0)
        suppressed = depth == 0 and getattr(self, "_ext_in_event", False)
        if is_ending_event(self, result):
            pass  # Gate2 delivered every ending subscriber, including nested endings.
        elif not suppressed and depth < 8:
            from . import ext  # plug-ins (combat/ext): every event, and turn boundaries

            if depth == 0:
                self._ext_event_limit_logged = False
            self._ext_event_depth = depth + 1
            self._ext_in_event = True
            try:
                if depth == 0:
                    ext.run("event", self, event_type, {**kwargs, "source_definition_id": result.source_definition_id,
                                                      "originating_event": result})
                else:
                    ext.run_nested("event", self, event_type, {**kwargs, "source_definition_id": result.source_definition_id,
                                                             "originating_event": result})
                actor = self.state.actors.get(kwargs.get("actor_id") or "")
                if depth == 0 and actor is not None and event_type in ("TURN_STARTED", "TURN_ENDED"):
                    ext.run("turn_start" if event_type == "TURN_STARTED" else "turn_end", self, actor)
            finally:
                self._ext_event_depth = depth
                self._ext_in_event = depth > 0
        elif not suppressed and not getattr(self, "_ext_event_limit_logged", False):
            self._ext_event_limit_logged = True
            super()._append_event("GM_RIDER", result.source_definition_id, actor_id=result.actor_id,
                                 target_ids=result.target_ids,
                                 payload={"rider": "Nested event delivery stopped at depth 8.", "depth_limit": 8})
        if event_type == "RESOURCE_GAINED" and (kwargs.get("payload") or {}).get("resource_id") == "resource:named.black_vein_strain":
            from . import unmaking  # Ruin Backlash at 6 Black Vein Strain (owner 2026-09-28)

            actor = self.state.actors.get(kwargs.get("actor_id") or "")
            if actor is not None:
                unmaking.after_strain_gained(self, actor, str(args[0]) if args else "strain")
        if event_type == "CONDITION_REMOVED" and (kwargs.get("payload") or {}).get("condition_id") == "condition:typed.ruin_channel" \
                and (kwargs.get("payload") or {}).get("checkpoint"):
            from . import unmaking  # a Ruin Channel that ends unspent costs PB self-damage

            actor = self.state.actors.get(kwargs.get("actor_id") or "")
            if actor is not None:
                unmaking.channel_fizzled(self, actor, int(actor.turn_flags.get("ruin_channel_round_pb") or 2))
        if event_type in ("DAMAGE_COMMITTED", "TURN_ENDED"):
            from . import pressure  # Foundation resources: Golden Sea Pulse (owner 2026-09-28)

            if event_type == "DAMAGE_COMMITTED" and self.events:
                pressure.after_damage(self, result)
                if self.__dict__.get("_typed_after_commit"):
                    from .typed_reactions import flush_after_commit

                    for target_id in result.target_ids or ():
                        flush_after_commit(self, target_id)  # a hold-at-1-HP reaction's Temporary HP, after the hit
            elif event_type == "TURN_ENDED" and (kwargs.get("actor_id") or "") in self.state.actors:
                pressure.on_turn_ended(self, self.state.actors[kwargs["actor_id"]])
                from . import stances

                stances.on_turn_ended(self, self.state.actors[kwargs["actor_id"]])  # the Second Ruin Form's Strain
                # turn_end_settled: after the whole native turn-end aftermath (including upkeep that harms, which
                # stamps reveals above). Plug-ins that must settle last (Vanishing Technique) subscribe here.
                ext.run("turn_end_settled", self, self.state.actors[kwargs["actor_id"]])
        # Zone and summon aftermath is part of the native ending checkpoint.
        from .paid_relocation import observe_falls
        observe_falls(self)
        return result

    def legal_candidates(self):
        # A pure enumeration owns transient extension/query indexes. Execution
        # and each later menu always get a fresh scope, including direct callers.
        with candidate_pass(self):
            return self._generate_legal_candidates()

    def action_candidates_for_sources(self, sources):
        """Fresh legal action options for a chooser; no moves, ranking or state projection.

        Uses the same native generation and vetoes as the complete menu. Sources
        narrow discovery only; ownership, loadouts, costs and targets still apply.
        """
        from .placement_menu import exhaustive
        with candidate_pass(self), exhaustive():
            return self._generate_legal_candidates(sources=frozenset(sources))

    def _generate_legal_candidates(self, intent=None, *, sources=None):
        """Apply the native loadout/terrain/veto rules to fresh targeted queries."""
        from . import loadout
        from .zones import breachable, sync_walls

        sync_walls(self)
        # Only the augment combination each fighter has chosen (combat/loadout.py): the others stay out of the list the
        # engine builds, so many augments don't multiply the squares an area ability is offered at.
        narrowed = {}
        from .action_legality import deny, plugin_denial
        for actor in self.state.actors.values():
            drop = loadout.hidden(self, actor)
            if drop:
                for source in drop:
                    deny(source, 'LOADOUT', 'This version is not in your chosen set of ability improvements; use the selected version or change your selection.')
                narrowed[actor.entity_id] = actor.action_ids
                actor.action_ids = tuple(action_id for action_id in actor.action_ids if action_id not in drop)
        from . import motion

        try:
            with motion.terrain_for(self, self.state.actors.get(self.state.current_actor_id or "")):  # Unimpeded Positioning
                out = super()._generate_legal_candidates(intent, sources=sources)
        finally:
            for actor_id, action_ids in narrowed.items():
                self.state.actors[actor_id].action_ids = action_ids
        # "Force through the wall" / "Work the Puzzle Wall" only beside a wall the fighter may try; "Drop" what it holds,
        # "Pick up" what it dropped within 5 feet (combat/carry.py).
        # Hide only when no enemy can see it; Search only while an enemy is hidden (combat/stealth.py); a talent choice for
        # an area only when it can pay for it (combat/zones.py _shaped).
        from . import carry, ext, stealth

        vetoes = ext.has("candidate_allowed")  # plug-ins that narrow what a fighter may do now (combat/ext)
        keep = []
        for candidate in out:
            if candidate.metadata.get('lazy_action'):
                # An action header has no selected target/origin. Candidate
                # vetoes run on its exact native expansion, never this offer.
                keep.append(candidate)
                continue
            if vetoes and not candidate.metadata.get('placement_picker') and (actor_ := self.state.actors.get(candidate.actor_id)) is not None and \
                    ext.any_false("candidate_allowed", self, actor_, candidate, self.action_catalog.get(candidate.source_definition_id)):
                plugin_denial('candidate_unavailability', self, actor_, self.action_catalog.get(candidate.source_definition_id), candidate, stage=2)
                continue
            parameters = getattr(self.action_catalog.get(candidate.source_definition_id), "parameters", None) or {}
            wanted, item, sneak, shape = (parameters.get("requires_wall"), parameters.get("item_action"), parameters.get("stealth"),
                                          parameters.get("shape_costs"))
            actor = self.state.actors.get(candidate.actor_id) if (wanted or item or sneak or shape) else None
            if sneak == "hide" and (actor is None or not stealth.can_hide(self, actor, parameters.get("hide_inside"))):
                deny(candidate.source_definition_id, 'HIDE', 'You cannot hide here while an enemy can see you.', stage=2)
                continue
            if sneak == "search" and (actor is None or not stealth.can_search(self, actor)):
                deny(candidate.source_definition_id, 'SEARCH', 'There is no hidden enemy you can search for now.', stage=2)
                continue
            if shape and (actor is None or any(actor.resources.get(resource, 0) < int(amount) for resource, amount in shape.items())):
                from .action_legality import cannot_pay
                if actor is not None:
                    cannot_pay(self, actor, candidate.source_definition_id, shape, stage=2)
                continue
            if wanted and (actor is None or breachable(self, actor, wanted) is None):
                deny(candidate.source_definition_id, 'WALL', 'There is no suitable wall within reach to work on.', stage=2)
                continue
            if item == "drop" and (actor is None or not carry.holds(self, actor, parameters.get("item_key"))):
                deny(candidate.source_definition_id, 'DROP', 'You are not carrying this item.', stage=2)
                continue
            if item == "pickup" and (actor is None or not carry.can_pick_up(self, actor, parameters.get("item_key"))):
                deny(candidate.source_definition_id, 'PICKUP', 'This item is not available for you to pick up here.', stage=2)
                continue
            keep.append(candidate)
        return tuple(keep)

    def _effective_speed(self, actor):
        from .speed_contributions import effective_speed

        return effective_speed(self, actor)

    def _attack_mode(self, actor, target, *, removed=None, provenance=None, contributions=None, chosen_modes=(), ranged=None, reasons=None):
        # Senses (combat/senses.py, docket 2026-09-28): a Hidden or Invisible creature's Advantage and Disadvantage do not
        # count against a creature that sees it with Blindsight or Truesight, nor a Blinded creature's toward one its
        # Blindsight reaches. Pass a pure projection; visibility reads the real state.
        from . import senses

        masked = senses.masked_conditions(self, actor, target) if (actor.conditions or target.conditions) else {}
        return super()._attack_mode(actor, target, masked=masked, removed=removed, provenance=provenance, contributions=contributions, chosen_modes=chosen_modes, ranged=ranged, reasons=reasons)

    def _grant_temp_hp(self, target, *args, **kwargs):
        if any(c.condition_id == "condition:typed.no_temp_hp" for c in target.conditions.values()):
            return None  # Empty Vitality, Nullifying Strike (owner 2026-09-28)
        return super()._grant_temp_hp(target, *args, **kwargs)

    def _ac_modifier(self, target):
        # Always-on Armor Class from a character's passives (owner 2026-09-28): Body Conditioning's +1 while holding Martial
        # Focus; armour-bound ones (Mountain-Pattern Shell, Tempered Flesh) are filtered when the character is compiled.
        from . import typed_reactions

        bonus = 0
        for row in typed_reactions._rows(self, target.entity_id, "defense"):
            if row.get("kind") == "ac" and (not row.get("martial_focus") or target.resources.get("resource:core.martial_focus", 0) >= 1):
                bonus += int(row.get("amount") or 0)
        from . import ext

        return super()._ac_modifier(target) + bonus + sum(int(value) for value in ext.run("ac", self, target))

    def _resolve_leave_reach(self, mover, previous, nxt, intent, *, ignore_oa_from=()):
        from . import motion

        motion.leaving_reach(self, mover, previous, nxt)  # Current Between Steps
        return super()._resolve_leave_reach(mover, previous, nxt, intent, ignore_oa_from=ignore_oa_from)

    def _raw_cover_bonus_actor_to_actor(self, actor, target):
        # Three-Quarters Cover (docket 2026-09-28): a line through a Dune Wall or Wind Wall gives +5, not the grid's +2
        # (combat/zones.py sync_walls); the attacker still takes its best clear line. A plug-in may give cover of its own
        # (Yokozuna Presence: an ally's body in the way; combat/ext hook "cover"); the best cover counts.
        bonus = super()._raw_cover_bonus_actor_to_actor(actor, target)
        deep = self.__dict__.get("_cover_three_quarters")
        if bonus and deep:
            from .shot_geometry import source_cells
            from .effect_cover import terrain_bonus
            cells = self._actor_volume if actor.position.z or target.position.z or self.grid.finite_heights else self._actor_cells
            bonus = terrain_bonus(self, source_cells(self, actor, target), cells(target), deep=True)
        from . import ext

        if ext.has("cover"):
            bonus = max([bonus, *[int(value) for value in ext.run("cover", self, actor, target)]])
        return bonus

    def _action_candidates(self, actor, action, *, intent=None):
        from . import lazy_menu
        if (intent is None and lazy_menu.active(self)
                and not (action.resolution_kind == 'TYPED' and action.target_kind == 'CELL'
                         and (action.parameters or {}).get('any_cell'))):
            return super()._action_candidates(actor, action)
        if action.resolution_kind == "TYPED" and action.target_kind == "CELL" and (action.parameters or {}).get("any_cell"):
            return self._any_cell_candidates(actor, action, intent=intent)
        # Teleport uses the native self candidate as a template. CELL wall
        # queries can score one explicit placement without rebuilding a menu.
        typed = (action.parameters or {}).get('typed') or {}
        from .typed_executor import teleport_reach
        fallback = intent is not None and (
            action.resolution_kind == 'TYPED' and teleport_reach(self, actor, action) is not None)
        if fallback and intent is not None:
            from .action_geometry import activate, origins
            with activate(self, actor, action.source_definition_id, None):
                choices = [None, *origins(self, actor, action)]
            matches = False
            for origin in choices:
                with activate(self, actor, action.source_definition_id, origin):
                    matches |= any(self._identity_matches(intent, kind, actor, action.source_definition_id)
                                   for kind in (CandidateKind.ACTION, CandidateKind.BONUS_ACTION))
            if not matches:
                return []
        out = super()._action_candidates(actor, action, intent=None if fallback else intent)
        if out and action.resolution_kind == "TYPED" and ((action.parameters or {}).get("typed") or {}).get("zone_spec", {}).get("wall"):
            from .ext import docket_walls

            out = docket_walls.tactical(self, actor, action, out)  # where the built-in AI would raise a wall (docket 2026-09-28)
        reach = teleport_reach(self, actor, action) if out and action.resolution_kind == "TYPED" else None
        if reach is None:
            return out
        # A self-teleport (owner 2026-09-28, Empty Step) is aimed at an unoccupied square the user can see within reach.
        base = out[0]
        from .candidate_knowledge import active as knowledge_query
        if knowledge_query(self):
            # AI uses the same legal landings as the player's picker. Keep the
            # historical enumeration below for canonical/save-bound menus.
            from .ext.teleport_steps import destinations, teleport_requirement, self_teleport_action
            if not self_teleport_action(action):
                return []  # Shared placement flags are not self teleports.
            from .zones import hazard_test
            cells = destinations(self, actor, reach, where=teleport_requirement(action.parameters.get('typed') or {}))
            hazard = hazard_test(self, actor, movement_mode="teleport")
            return [self._candidate(base.kind, actor, action.source_definition_id,
                                    f'{action.display_name} to {pos.x},{pos.y}',
                                    target_ids=(actor.entity_id,), destination=pos, option_ids=base.option_ids,
                                    metadata={'expected_damage': 0, 'teleport': True,
                                              **({'hazard_exposure': True} if hazard and hazard(pos) else {})}) for pos in cells]
        from . import motion

        typed_ = (action.parameters or {}).get("typed") or {}
        where = typed_.get("teleport_where") or next((row.get("where") for row in typed_.get("effects") or []
                                                      if isinstance(row, dict) and row.get("type") == "teleport" and row.get("where")), None)
        if where == "darkness" and not motion.obscured(self, actor):
            from .action_legality import deny
            return deny(action.source_definition_id, 'DARKNESS', 'You must be standing in darkness to use this movement.')
        occupied = self._occupied_cells_except(actor.entity_id)
        footprint = self._footprint(actor)
        squares = []
        for y in range(self.grid.height):
            for x in range(self.grid.width):
                pos = Position(x=x, y=y)
                if (pos == actor.position or self._distance_actor_to_cell(actor, pos) > reach
                        or not self.grid.placement_legal(pos, footprint=footprint, occupied_cells=occupied)
                        or not self._line_of_sight_actor_to_cell(actor, pos)
                        or (where == "darkness" and not motion.obscured_at(self, pos))):
                    continue
                squares.append(self._candidate(base.kind, actor, action.source_definition_id, f"{action.display_name} to {x},{y}",
                                               target_ids=(actor.entity_id,), destination=pos, option_ids=base.option_ids,
                                               metadata={"expected_damage": 0, "teleport": True}))
        if not squares:
            from .action_legality import deny
            return deny(action.source_definition_id, 'TELEPORT_DESTINATION', 'There is no unoccupied destination within range and sight that meets this movement’s requirements.')
        return squares

    def _any_cell_candidates(self, actor, action, *, intent=None):
        """A typed ability aimed at any square in range and sight, creature or not (Rolling Blackout moves a Darkness
        there); a plug-in narrows the squares (combat/ext candidate_allowed)."""
        from .gate2_runtime_models import CandidateKind, EconomyKind

        from .action_legality import deny, cannot_pay
        if action.economy == EconomyKind.ACTION and not actor.action_available:
            return deny(action.source_definition_id, 'ACTION', 'Your action has already been used this turn.')
        if action.economy == EconomyKind.BONUS_ACTION and not actor.bonus_action_available:
            return deny(action.source_definition_id, 'BONUS_ACTION', 'Your Bonus Action has already been used this turn.')
        if not self._can_pay(actor, action.costs):
            totals = {}
            for rid, amount in action.costs:
                totals[rid] = totals.get(rid, 0) + amount
            cannot_pay(self, actor, action.source_definition_id, totals)
            return []
        kind = CandidateKind.ACTION if action.economy == EconomyKind.ACTION else CandidateKind.BONUS_ACTION
        from . import lazy_menu
        if intent is None and lazy_menu.active(self):
            return [lazy_menu.header(self, actor, action, kind)]
        from .candidate_knowledge import aim_allowed
        out = []
        from .placement_menu import axes
        xs, ys, _ = axes(self.grid, intent, (0,))
        for y in ys:
            for x in xs:
                pos = Position(x=x, y=y)
                if intent is not None and (pos != intent.destination or not self._identity_matches(intent, kind, actor, action.source_definition_id)):
                    continue
                if self._distance_actor_to_cell(actor, pos) <= int(action.range_ft or 0) and self._line_of_sight_actor_to_cell(actor, pos):
                    if not aim_allowed(self, actor, pos):
                        continue
                    # Non-area cell actions may opt out of the AI-only empty-area marker.
                    metadata = ({"expected_damage": 0, "hostiles_in_area": 0, "empty_area": True}
                                if action.parameters.get("ai_empty_area_filter", True) else {})
                    from . import ext
                    replies = ext.run_strict("cell_candidate_metadata", self, actor, action, pos)
                    if replies:
                        if len(replies) != 1 or not isinstance(replies[0], dict):
                            raise ValueError("one provider must own cell candidate metadata")
                        supplied = replies[0]
                        if (set(supplied) != {'expected_damage', 'hostiles_in_area', 'empty_area'} or type(supplied['empty_area']) is not bool
                                or any(type(supplied[k]) is not int or supplied[k] < 0
                                       for k in ('expected_damage', 'hostiles_in_area'))):
                            raise ValueError("invalid cell candidate metadata")
                        metadata = supplied
                    out.append(self._candidate(kind, actor, action.source_definition_id, f"{action.display_name} at {x},{y}", destination=pos,
                                               metadata=metadata))
                    from .placement_menu import representative
                    root = representative(self, actor, action, out[-1], intent=intent)
                    if root is not None:
                        return [root]
        return out

    def set_reaction_provider(self, provider: ReactionProvider | None) -> None:
        self._gate4_reaction_provider = provider

    def execute_intent(self, intent: ActionIntent) -> None:
        self._gate4_reaction_cache = {}
        self.gate4_reaction_decision_records = []
        from . import motion

        try:
            with motion.terrain_for(self, self.state.actors.get(intent.actor_id)):
                super().execute_intent(intent)
        finally:
            self._gate4_pending_damage = None
            self._gate4_damaged_target_id = None

    def _reaction_decision(
        self,
        intent: ActionIntent,
        checkpoint: str,
        reactor_id: str,
        reaction_id: str,
        *, context: dict | None = None,
    ) -> ReactionDecision | None:
        from .choice_checkpoints import dynamic_choice

        # Carry the active event receipt into extension choices opened by a
        # reaction consent call, just as the ordinary reaction provider does.
        dynamic_context = context
        trigger = getattr(self, "_reaction_trigger", None)
        if dynamic_context is None and isinstance(trigger, dict) and checkpoint.split("@", 1)[0] in (
                trigger.get("checkpoint"), "TYPED:" + str(trigger.get("checkpoint") or "")):
            dynamic_context = {key: value for key, value in trigger.items() if key != "checkpoint"}
        handled, decision = dynamic_choice(self, intent, checkpoint, reactor_id, reaction_id, dynamic_context)
        if handled:
            return decision
        embedded = super()._reaction_decision(intent, checkpoint, reactor_id, reaction_id)
        if embedded is not None or self._gate4_reaction_provider is None:
            return embedded
        key = (checkpoint, reactor_id, reaction_id)
        if key in self._gate4_reaction_cache:
            return self._gate4_reaction_cache[key]
        target_id = None
        attacker_id = None
        provisional_hit = None
        if self._active_intent is not None:
            attacker_id = self._active_intent.actor_id
            if self._active_intent.target_ids:
                target_id = self._active_intent.target_ids[0]
        if checkpoint == "DAMAGE_APPLICATION":
            target_id = self._gate4_damaged_target_id or target_id
        if checkpoint == "LEAVE_REACH":
            target_id = intent.actor_id
        if checkpoint == "ATTACK_HIT_BEFORE_DAMAGE":
            provisional_hit = True
        spend_options: list[int] = []
        if reaction_id == "reaction:core.stamina_guard":
            reactor = self.state.actors[reactor_id]
            maximum = min(
                reactor.proficiency_bonus,
                reactor.resources.get("resource:an_eui.stamina", 0),
            )
            spend_options = list(range(1, maximum + 1))
        legal_option_ids: list[str] = []
        if reaction_id == "reaction:bai_meizhen.sea_moon_interposition":
            legal_option_ids = ["DIRECT_CONTEST"]
        elif reaction_id == "reaction:bai_meizhen.spirit_intercession":
            legal_option_ids = ["SPEND_QI"]
        request = {
            "checkpoint": checkpoint,
            "reactor_id": reactor_id,
            "reaction_source_id": reaction_id,
            "protected_target_id": target_id,
            "damaged_target_id": target_id if checkpoint == "DAMAGE_APPLICATION" else None,
            "attacking_actor_id": attacker_id,
            "provisional_hit": provisional_hit,
            "pending_damage": self._gate4_pending_damage,
            "legal_reaction_ids": [reaction_id],
            "spend_options": spend_options,
            "legal_option_ids": legal_option_ids,
        }
        from .reaction_trigger import contextual_request
        decision, record = self._gate4_reaction_provider(contextual_request(self, request))
        if decision is not None and (
            decision.checkpoint != checkpoint
            or decision.reactor_id != reactor_id
            or decision.reaction_source_id != reaction_id
        ):
            raise self._intent_error(
                "CONTROLLER_REACTION_CONTEXT_INVALID",
                "The controller returned a reaction for another checkpoint or reactor.",
                intent,
            )
        self._gate4_reaction_cache[key] = decision
        if record is not None:
            self.gate4_reaction_decision_records.append(record)
        return decision


    def _resolve_optional_rider(self, actor, candidate, intent: ActionIntent) -> None:
        # Gate 4 exposes Spark Step to autonomous control. The accepted Gate 2
        # implementation dereferenced a target before entering its targetless
        # Spark Step branch; handle that exact typed rider before delegating.
        if candidate.source_definition_id == "talent:lee_jia.spark_step":
            pending = self.state.pending_resolution
            if pending is None or candidate.source_definition_id not in pending.follow_up_candidates:
                raise self._intent_error(
                    "GATE2_OPTIONAL_RIDER_WINDOW_CLOSED",
                    "The optional rider trigger window is closed.", intent,
                )
            if candidate.destination is None:
                raise self._intent_error(
                    "GATE2_SPARK_STEP_DESTINATION_REQUIRED",
                    "Spark Step requires an offered destination.", intent,
                )
            ignored = intent.option_ids[0] if intent.option_ids else None
            if ignored:
                actor.turn_flags["spark_step_ignore_oa_from"] = ignored
            actor.movement_remaining_ft += candidate.movement_cost_ft
            self._resolve_movement(actor, candidate, intent)
            actor.turn_flags.pop("spark_step_ignore_oa_from", None)
            self._complete_follow_up(candidate.source_definition_id)
            return
        super()._resolve_optional_rider(actor, candidate, intent)

    def _resolve_damage_reaction(
        self,
        target,
        pending: int,
        intent: ActionIntent,
        reaction_depth: int,
    ) -> int:
        self._gate4_pending_damage = pending
        self._gate4_damaged_target_id = target.entity_id
        try:
            return super()._resolve_damage_reaction(target, pending, intent, reaction_depth)
        finally:
            self._gate4_pending_damage = None
            self._gate4_damaged_target_id = None
