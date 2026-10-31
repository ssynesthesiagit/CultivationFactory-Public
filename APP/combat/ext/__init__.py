"""Public test documentation omitted."""

# Typed save support attribution (Spirit Dew parent): the existing save hook
# may also return support_sources=[{actor_id, source_id}], naming the creator
# and source of a benefit actually supplied by that reader. typed_save_modifiers
# validates/freezes the list on Context.save_support_sources for this one save;
# save_final receives it after overrides. An independent override rescuing a
# failed save clears the original providers; an opaque rescue has no accepted
# support attribution of its own. No list means no attribution. The
# stored save_against reader produces receipts only for a matching, active
# Advantage grant, excluding native no-save-Advantage suppression. foundations3
# queues generation after a final successful save resists a hostile
# fear/curse/explicit pressure effect with an actual matching protection provider,
# until the enclosing technique settles. Success without that provider is inert.
# Final Concentration support attribution (Spirit Dew parent):
# concentration_save_sources(engine, subject) -> None or list[{actor_id,
# source_id}] is a pure proposal queried before a native Concentration roll.
# Providers name only a benefit they actually supply to that save; Music's
# Opening Phrase publishes its numeric bonus from the same condition used by
# save_bonus_details. combat.concentration.support_sources also freezes live
# native condition-rule Advantage grants before one-use consumption, excluding
# suppressed conditions, native CON no_save_advantage and mode-removal policy.
# This filtering applies only to Advantage receipts; independent numeric
# providers remain attributed. No source-name/affinity guesses.
# concentration_save_resolved(engine, subject, roll, dc, maintained, sources)
# is called by gate2_engine._concentration_check after final outcome/rescue
# settlement. Return None; absent subscribers change neither dice nor state.
# Sources are primitive actor/source identifiers, transient until settlement;
# consumers persist only their own ordinary evented results. foundations3
# credits outward maintained support after the enclosing action completes;
# no generation for a failed save, self support, or an unowned generation row.
# A forced success after a failed numeric save, or an opaque MAINTAIN rescue,
# reports no provider: the failed roll's earlier
# benefits are not attributed to the rescue. A future accepted rescue producer
# must supply its own final attribution before it can receive support credit.
from __future__ import annotations

# observer_information(engine, observer) -> list[dict] | None: pure, default-inert
# private fact projection. information_results.for_observer consumes it in the
# native senses.perception query and the active actor's player/AI DecisionContext.
# Providers enforce ownership, source/range/visibility/expiry and return only
# entitled facts, never complete enemy records, source identities or diagnoses.
# This hook grants no sight, targeting, team knowledge or public journal notes.
# Authored provenance may use encounter_sources' sealed sensory_sources: medium,
# kind, entity_id/object_id/position, source_key, occurred_at_seconds,
# expires_at_seconds, studied_by. Bloodsense adds circulation/exposed/obvious
# integer flags, likely_blood_loss (0/1), and fresh_until_seconds (exclusive).
# Missing timestamps/identity/cause remain unknown; one-hour spills do not imply
# the separately authored freshness required for Invisible creatures.

# REL5 composed OA permission query: opportunity_permitted_against(...,
# uses_reaction=True) retains ordinary Reaction-denial checks. A printed free
# granted attack passes False; creature-specific no-OA, charm, visibility and
# other admission gates still apply. This pure query never pays or asks.

# A2DEATH: Death's state queries reuse existing hooks. Newly sealed
# bone_ward_remains reaction effects opt into the proximity +PB query through
# damage_reduction_bonus; absent flags preserve historical reactions. The
# death_sovereign self effect grants an evented ten-round condition; flight,
# damage_defenses (mundane_only), attack_damage/types and sealed free Hand
# variants read it. candidate_allowed/technique_used enforce one free use during
# each owner turn. Ordinary characters and retained catalogs have no such state.
# death_anchors on a self teleport narrows candidate_allowed, reused by the
# shared teleport destination chooser at resolution, to perceived grave anchors.
# Explicit RuntimeObjectState kinds corpse/remains/bone_pile/grave_marker/
# funerary_object identify remains for Bone Ward; death_anchor_owner identifies
# the caster's marked funerary object or Ghost Lantern for Deathly Passage.
# Unknown scenery, inactive nonlethal actors and another caster's marked object
# confer no benefit. These queries require no lock edit or core special case.
# corpse_explosion_source selects a perceived corpse/undead servant at the aimed
# center before the save resolves; candidate_allowed disallows empty origins.
# technique_final consumes that exact corpse or owned Death servant through evented updates;
# actor corpses retain an UNTIL_REMOVED corpse_consumed flag (destruction is
# permanent, not a temporary combat penalty). Old unflagged saves remain inert.
# Corpse Explosion uses the damage_type_choice contract documented above.

# SOL168 uses existing contracts only: charge_marks' compile_action adds the
# lightning_gather_second effect to owned Gather Charge options. It asks for
# one extra legal placement without another economy payment; creature, weapon
# and space Charges share the printed cap.
# mark_apply also preserves oldest-Charge replacement when a later Lightning
# effect encounters a cap occupied by weapon/space Charges; creature-only
# placement remains on the existing path. Map water may declare
# significant_water_source=true for River Passage's CL15 mile route.
# water_passage's compile_action,
# candidate_allowed and water_river_passage effect restrict the owned River
# Passage variant to recorded connected water and owner's Basin landings.
# Passenger variants target any creature and ask a non-self passenger's consent
# through the existing choice transport (manual owners may decline, AI decides).
# The CL15 route uses water-component membership in a significant source;
# Gather Charge's second picker applies and rechecks all candidate_allowed vetoes.
# rider_outcomes' unresolved_roll_mode_text uses printed evidence for incomplete generated
# roll-mode rows (no `on` descriptor), preserving their GM-only semantics.
# All three providers return early outside their opted-in rows.
# unresolved_roll_mode_text(ctx, effect, mode) -> plain str or None replaces only
# an unresolved Advantage/Disadvantage GM summary. It changes no roll, payment,
# expiry or once-per-turn bookkeeping. None/no provider retains the old summary;
# the provider is used by every incomplete generated roll-mode row, not one ability.

# AI placement query seam (combat/candidate_knowledge.py): query(engine) scopes
# observed actor estimates and perceived/last-observed area aims while Gate 2/4
# generate candidates. roster(engine) returns that tuple or None (real roster);
# aim_allowed(engine, actor, Position, action=None) returns a boolean, True
# outside the scope. A self-originating line/cone does not require a perceived
# aim cell; the position only chooses direction and physical area clipping still
# stops its effect at solid obstacles.
# No engine/state/class mutation or execution hook is involved. Area safety uses
# the executor's explicit actors= geometry query; execution never enters this
# scope. Teleport plug-ins retain candidate_allowed for owning restrictions and
# the shared teleport_steps.destinations/destination_allowed legality contract.
# zones.hazard_test(engine, actor, movement_mode="walking") returns an endpoint
# damage predicate or None. "teleport" and "forced" retain entry/start and line
# crossing estimates while excluding distance-based terrain triggers, matching
# forced execution. Default walking queries and fights without hazards are unchanged.
# prepared_binding(engine, generated_candidates) scopes immutable AI acceptance:
# binding_candidates(engine) returns that menu only for an identical full-state
# hash, otherwise None. It never changes engine functions or execution rosters.

# Search policy: ai_search_policy's existing match_start(engine)->None hook
# stamps integer ai_search_policy=1 in MATCH_CREATED. combat.ai_search derives
# a legal walking candidate from public terrain, projected knowledge and the
# mover's own journal. gate4_context supplies its optional id only for ordinary
# AI decisions; controller representatives retain it and record its integer
# search score. Missing stamps/fields are inert. Continuations preserve stamps.
# The documented target_observation_refresh hook renews perceived same-square
# sightings for stamped fights without new event numbers or fight-state fields.
# Neutral policy phases: combat.relations.ordinary_turn(candidates) is the
# shared pure guard for context filtering and controller scoring. Setup and
# accepted OPTIONAL_RIDER / TAKE_NO_OPTIONAL_ACTION windows retain their
# candidate sets; retreat/Dodge and neutral-target policy starts only on ordinary
# turns. No new saved field, event or hook; ordinary two-team behavior is unchanged.

# Spirit Companions sealing family (AUTO5 2026-10-04, corrected by AUTO5f1). All default-inert: nothing answers for a
# creature without the owning compiled rows, and a fight saved before the lane keeps its old paths.
#   Effect types: seal_strain (the owner's own Bond Strain counter, never the spirit's; combat/ext/spirit_seals.py),
#     seal_release (break a Binding Seal: every mark and matching condition the creature wears go together, older
#     mark-only saves included), seal_suppress (a spirit cannot be commanded, is not tethered and may attack its
#     binder for a printed window). Registered by combat/ext/spirit_seals.py. A spirit_guard row's own
#     "nature_bonus" key ({"temp_hp": "pb", "natures": [...], "evidence": ...}) is the printed rider that asks the
#     player for a spirit's Nature (Guardian Spirit Posture, combat/ext/spirit_bonds.py).
#   Feature blocks (combat/rules/feature_blocks.d/auto5_spirit.json): {"block": "spirit_seal", "kind": "violent" |
#     "painful" | "punish" | "name"} per seal talent. A "punish" row carries trigger_owner, so the compiler omits the
#     generic reaction row it could never deliver (the printed trigger is a summon disobeying, which no event reports)
#     and the plug-in's own prompt is the whole delivery. Absent a block a character owns none of them.
#   Typed record key target: {"any_side": true} widens ONE owned action to any creature through the existing
#     compile_action seam (spirit_seals.widen_any_side): the compiler reads a harmful saving throw or contest as
#     hostile-only, and "a Binding Seal restrains or compels a spirit" prints no side. The flag lives in the talent's
#     own typed record, so any ability can use it; range, costs and effects are untouched. A printed outcome that
#     depends on a check nests under that check's on_success, so a failed check changes nothing.
#   Shared core addition, typed_executor.resolve_opposed_check target_check {"kind": "dc", "of": "<name>"}: the
#     actor's check must meet a printed Difficulty Class and the defender rolls no die ("Make a Cultivation Check
#     against the binder's Cultivation Save DC"). The DC comes from the new dc_of() seam, which asks the check_dc
#     hook (ctx, target, spec) and otherwise reads the target's own Cultivation Save DC
#     (combat/ext/end_effect.cultivation_dc); an unnamed, unanswerable or legacy name all fall back to that same
#     target DC, never to a flat 10. A DC is met by matching it (outcome_override total >= dc), where an opposed
#     contest's tie still preserves the defended situation. OpposedCheckResult.target carries the DC as a no-die
#     RollRecord ("DC n"), so margin/tied/events keep their ordinary shape. CHECK_ROLLED retains the actor's
#     label/skill (or "Cultivation Check" for that kind); DC history names the affected creature and printed DC.
#     Any other kind is unchanged.

# Table-only movement projection (combat/movement_menu.py): a context-local
# capture records every native legal endpoint, price, mode and drop permission
# after native path restrictions.
# capture() -> request-local quote list; collect(engine, actor, destination,
# path, cost, mode, can_jump_down, route_bound=False, passage=None) -> bool:
# True consumes this table quote; False retains ordinary candidate generation.
# candidate_allowed receives a RouteQuote exposing the
# same public candidate fields; expensive metadata resolves lazily to the native
# candidate. Missing capture is inert. AI, replay and execution retain full
# candidates; movement-destination/preview resolves a chosen route afresh and
# movement-path/commit validates it through the existing exact-path authority.
import importlib
import pkgutil

# Ash Garden consumes compile_passives, confirmed_hit_damage_bonus, event,
# hit_final and the public
# foundation_context source/scene facts. ash_garden.active_garden(engine, owner,
# subject=None) returns the actual active owned Garden zone, optionally requiring
# current native membership, or None. Ash-generation/ending consumers may use
# this public query; it never creates state. damage_receipt_facts captures field
# membership before HP changes; transaction_settled delivers optional ending credit
# through pressure.generate after all same-event spending opportunities finish.
# Absent compiled Garden ownership all callbacks are inert; cap/round/expiry
# remain owned by the existing Funeral Ash pressure row.
# General damage_receipt_facts(engine, target, source_id, source_actor_id) ->
# None or a dictionary of unique non-reserved str keys and primitive int/str
# values or lists thereof. Pure query before HP changes; values are journaled
# on DAMAGE_COMMITTED. Absent handlers preserve the original damage receipt.
# ash_garden.owns_zero_drop(engine, owner, event) -> bool is the shared pure
# query for Garden/base Funeral Ash consumers: an owned Garden's pre-damage
# membership and genuine hostile zero-drop receipt delegate that drop to the
# optional Garden choice, including decline. Absent ownership is inert.
# General transaction_settled(engine, source_id, actor_id, intent, first_sequence)
# -> None runs after action/turn resolution and falling, within the transaction.
# intent is the actual accepted intent or None for system boundaries; consumers
# must preserve unknown facts when no answer transport exists. Choice pauses
# roll back. Generation subscribers and Garden consume this same seam; no
# subscribers means no events/choices/state changes. first_sequence bounds the
# actual resolved receipts, including nested reactions and turn consequences.
# Its additional damage uses public life_state.additional_hit_component, shared
# with Censure, so one damaging hit cannot add extra death-save failures. Sealed
# numbers come from public needle.numbers_of, also used by Needle and Core
# Tempering. Source-policy consumers share foundation_context.source_method_facts,
# ash_aligned, hostile_zero_drop and adjudicated_event_context. No source is
# inferred from an action label or damage colour; unknown judgments stay unknown.
# foundation_context seals method category from the action source mechanic's
# canonical sphere and printed text hash (never from the actor's sphere list).
# Conditioned/custom unclassified sources retain printed-text adjudication;
# automatic owners cannot assert an unknown category. ash_aligned is alignment
# only: generation callers separately enforce danger/helplessness exclusions.
# observed_residue(engine, owner, target) -> 'battlefield' or 'unknown' is a
# pure sight-gated query of existing native Ashen Brand/Ash Terrain, shared by
# Meridian/Garden. public_event_context(engine, owner, event, intent, route) ->
# dict reads testimony only for the exact event sequence/source/targets/intent
# and recorded perceiving observer. Primitive observer_ids are journaled on
# existing foundation_event_context receipts; another execution/private observer
# cannot reuse them. Absent testimony/residue returns unknown, never assumed real.
# foundation_context.has_unconscious_condition(condition_ids) -> bool is a pure
# shared query of native unconscious/sleep ids, including Dream Sleep's own
# condition (which need not add a separate unconscious id). conscious(actor)
# applies it to live owner state; helpless_before(event) applies it to pre-damage
# receipt ids, even when damage has since awakened the target. Stunned/paralyzed
# owners remain conscious; paralysis separately makes a target helpless.
from collections import defaultdict
from typing import Any, Callable
from ..read_queries import enumeration_cache, invariant_memo

_EFFECTS: dict[str, Callable[..., Any]] = {}
_EFFECT_HARM: dict[str, bool | None] = {}
_EFFECT_FORGE_REJECTION: dict[str, str] = {}
_HOOKS: dict[str, list[Callable[..., Any]]] = defaultdict(list)
_HOOK_PRIORITIES: dict[tuple[str, Callable[..., Any]], int] = {}
_HOOK_PRESENT: dict[tuple[str, Callable[..., Any]], Callable[..., bool]] = {}
_HOOK_QUERY_KEYS: dict[tuple[str, Callable[..., Any]], Callable[..., Any]] = {}
_STABLE_QUERIES: set[tuple[str, Callable[..., Any]]] = set()
_FILTERED_POINTS: set[str] = set()
_NESTED_HOOKS: dict[str, set[Callable[..., Any]]] = defaultdict(set)
_LOADED = False


class ControllerPause(BaseException):
    """Raised by a choice provider to stop a preview until the player has answered (an Ask-me reaction, see
    combat/gate5_service.py _ReactionRequired). It is control flow, not a bug: code that catches Exception to keep a
    broken row or hook from ending a fight must re-raise it, or the player is never asked (owner playtest 2026-09-29:
    Flowing Response was auto-declined by the policy controller because its pause was swallowed as "could not run"). A
    BaseException, so every ``except Exception`` guard lets it through; only throwaway probe engines raise it."""


def effect(name: str, *, harmful: bool | None = None, forge_rejection: str = "") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register an effect handler. Optional forge_rejection is a plain menu reason
    when a handler depends on its original action/source and cannot be transplanted.
    Pure metadata, read by effect_forge_rejection(name); empty by default, with no
    change to execution, ownership checks, or existing saved techniques.
    """
    if harmful is not None and type(harmful) is not bool:
        raise ValueError("effect harmful must be bool or None")
    def register(function: Callable[..., Any]) -> Callable[..., Any]:
        _EFFECTS[name] = function
        _EFFECT_HARM[name] = harmful
        _EFFECT_FORGE_REJECTION[name] = forge_rejection
        return function
    return register


# General own-knowledge/analytic AI seams (default-inert):
# target_personal_knowledge(engine, viewer, target) -> Knowledge | False | None.
# Pure personal targeting override inside candidate_knowledge.query only,
# after native sight/field checks; False means unknown, None retains legacy
# knowledge. Native/manual targeting and execution never consume this hook.
# personal_observation_receipt(engine) -> dict[str, primitive] | None. Runs only
# at committed target observation, including creation. Its personal memories
# are stamped into the final event; no new sequence or query-side writes.
# ai_observation_frame(engine, actor, candidates, policy) -> OwnKnowledgeFrame
# | None. Pure personal projection; exclude hidden truth and global revisions.
# Frames may carry the actor's own relative occupied-volume offsets; movement
# and menu evaluators translate them with occupied_at(anchor), including every
# cell when checking perceived area boundaries. Absent frames retain native
# behavior. Directly perceived allies retain authorized support/mobility facts;
# remembered allies and opponents never supply their current private sheets.
# Search consumes the same frame's projected roster and sighting sequences via
# ai_search.search_move(sightings=...). Team journal hints are excluded when a
# frame exists; absent frames retain native team receipts and redacted hints.
# ai_observed_objectives(engine, viewer) -> tuple[Position, ...] | None. Pure
# scenario objective suggestions, rechecked against personal square perception.
# No provider means no fabricated objective or pressure toward unknown cells.
# ai_movement_hazards(engine, viewer, candidates, frame) -> dict[candidate_id,
# dict[str, bool]] | None. Pure perceived hazard_exposure/zone_hazard_exposure
# estimates; no candidate removal or mechanics changes. No reply retains native
# metadata. Providers reuse zones.hazard_test's projected zone_states seam.
# ai_policy_enrichment(policy, sheet) -> dict[str, Any] | None. Pure optional
# policy field additions from the owner sheet and optional package guidance.
# Called through ai_policy.enrich_policy for both installed package paths;
# absent/invalid optional guidance is neutral. No reply retains the base policy.
# ai_movement_order(context, rows) -> tuple[candidate_id, ...] | None. Pure
# destination ordering before optional-choice expansion; MUST be a permutation,
# keeping the complete native menu. Consumers may show five then More.
# ai_score_components(context, candidate, option_ids) -> tuple[ComponentScore,
# ...] | None. Pure additive analytic value after ordinary scoring; emergency
# early returns retain precedence. No rolling/spending/engine copies.
# Used by ai_movement, opt-in CF_COMBAT_AI_SLICES_1_2=1. No hook answer means
# byte-identical legacy context, events, scores and movement representatives.
# attack_target_interception(engine, attacker, target, source_id, intent, index)
# -> {source_id, recipient_object_id, condition_instance_id} or None. Strict
# checkpoint before creature defender hooks/d20; the provider resolves successful
# targeting of a noncreature decoy and its evented lifecycle. No answer leaves
# the original attack intact. A receipt may add optional "text" (the plain line the provider wrote; without
# it history gives a generic line), "roll_id" (its die, linked to the table's dice row), and must name its
# die reason head "TARGET_INTERCEPT:<source>:<index>" so the table labels it generically.
# attack_declaration.intercepted caches both answers
# and abstentions in the transient per-strike spec, keyed by primitive actor,
# target, source, intent and index, so typed/native boundaries never roll twice.
# Economy is already paid and is never refunded; intercepted strikes deliver
# no creature roll, damage or on-hit effects. A provider must check ownership
# and perception of the actual recipient, not visibility of its creature owner.
# Receipts name stored physical objects or nonphysical state.map_images markers;
# the record remains valid after the provider commits its destruction.
# Afterimage's public perceived_image/destroy_image helpers share its sourced
# condition/object identity with nonattack consumers; they do not create images.
# Elapsed-time journeys (combat/journey.py), separate from combat turn clocks:
# journey_options(session, actor_id) -> list[option] | None, owned legal actions.
# journey_command(session, actor_id, kind, payload) -> True | None, validates and
# applies one owned action inside the store's revision-checked transaction.
# journey_properties(session, actor_id) -> dict | None, pure owned travel benefits.
# Supported keys: pace_multiplier (positive int), carry_without_slowing (int flag),
# ignore_ordinary_travel_exhaustion (int flag), expiry_num/expiry_den (absolute
# second deadline, integer fraction). Unset keys retain ordinary scene behavior.
# journey_auto_blocked(session, actor_id) -> True | None pauses an automatic actor
# while its owned trigger awaits a player's decision. It consumes no revision,
# movement, cost or clock. None/default preserves automatic menu selection.
# journey_options may supply auto_select=0 to decline default automatic use of
# an option after a player refusal. Every option remains explicitly selectable;
# if all options decline automatic use, auto-step pauses without a new prompt.
# journey_step may return ignore_nonmagical_difficult=True: waive only painted
# difficult prices marked nonmagical_difficult=1 by tabletop.to_battlefield.
# Missing/False is inert. Native JourneySession.step_profile
# retains travel-row costs, other map prices, support and obstacle checks.
# JourneyStore journals admitted map commands and replays them through these
# same strict hooks. Queries/commands must be deterministic from sealed input
# and session state; replay never saves or emits external side effects.
# Athletics reads compiled motion rows via motion.resource_motion_rows, whose
# resource_gate is also used by combat motion queries; no ownership is granted.
# journey_step(session, actor_id, previous_position, next_position, regions)
# -> {ignore_slowing: terrain kinds, supported_kinds: terrain kinds} | None.
# Pure, default-inert; authored terrain only, never bypasses physical walls.
# journey_elapsed(session, actor_id, previous_seconds, seconds, moving_ids) -> None,
# receives exact Fraction values transiently. Persist only integer numerators and
# denominators; updates deadlines/stop clocks at each elapsed-time boundary.
# moving_ids includes carriers AND transported creatures, not only the mover.
# journey_state_changed(session, actor_id) -> None, observes combat/incapacitation.
# journey_rest(session, actor_id) -> None, observes a completed eight-hour rest.
# journey_command/elapsed/state_changed/rest use run_strict: any provider failure
# aborts the cold session before its revision or disk state is saved. Presentation
# options/properties/step/auto_blocked remain pure queries.
# All hooks are default-inert; nonowners receive no benefits, actions or edits.
# journey_ability compile_block rows seal travel declarations in owned bundles.
# match_initialize(engine) -> True | None: strict genesis initialization after the full
# roster/state exists, before observation, setup tasks and the first turn. Errors
# abort creation; absent providers make no edits. True requests first-turn hook
# delivery in genesis engines without event-based turn dispatch. Consumers include continuation
# health/life-state/condition restoration and pre-encounter exhaustion binding.
# Gate4 advertises turn_start_via_events=True and already delivers turn_start
# after TURN_STARTED. Gate2's initial boundary delivers it only when requested
# by match_initialize, once; ordinary fights preserve their legacy genesis.
# journey_setup uses match_initialize with an explicitly sealed
# bundle.journey_setup={incapacitated: integer flag, exhaustion: integer levels,
# encounter_snapshot?: {current_hp, maximum_hp, temporary_hp, active: integers,
# life_state: string, conditions: dict[instance_id, JSON string],
# death_saves: {ok: integer successes, bad: integer failures}}}.
# ext.journey_setup.encounter_snapshot(actor) captures supported permanent
# conditions/health/life state; unsupported timed effects reject continuation.
# ext.journey_setup.encounter_incapacitated(snapshot | None) -> bool is a pure
# shared check for zero HP or surviving incapacitating conditions; absent
# snapshots return False. Journey resume derives its flag from this check,
# and the incapacitated command rejects clearing it while the snapshot still
# requires incapacitation. Independently imposed travel flags remain clearable;
# this command never heals or removes an encounter condition.
# Optional effects_ended=True is an explicit GM checkpoint, never automatic
# expiry: omit timed conditions/modifiers/concentration/transformation, restore
# base maximum HP without healing, retain permanent conditions/death saves.
# CombatService.journey_resume(effect_resolutions={actor_id: nonempty reason})
# records that adjudication plus the pre-resolution actor JSON in journey events;
# the terminal combat is immutable. This is available after terminal fights only.
# life_state.encounter_death_saves(actor) -> {ok, bad};
# restore_encounter_death_saves(actor, record) -> None validates/restores those
# integer counts only, without changing HP or life state. Journey setup consumes
# these public helpers; absent journey snapshots remain inert.
# Absent snapshots are inert; travel benefits never enter combat replay.
def hook(point: str, *, nested: bool = False, priority: int = 0,
         present: Callable[..., bool] | None = None,
         query_key: Callable[..., Any] | None = None,
         stable: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a hook; lower priorities run first, ties retain registration order.

    Default 0 preserves existing ordering. Use negative priorities for transient
    scope bookkeeping that must precede ordinary observers (granted movement).

    Pure query opt-ins during candidate_pass only:
      present(engine) -> bool: False promises the provider is neutral throughout
        this revision, based on owned rows/conditions/objects actually present.
        Each hook's active index retains registration/priority order. Predicate
        failures conservatively retain the provider and its usual error policy.
      query_key(*args, **kwargs) -> hashable: declares ALL query dependencies
        beyond engine revision. Successful replies (including None/False) can
        be reused; exceptions, ControllerPause and CheckpointError never cache.
        Providers must be pure and include transient positions/origins in keys.
        Invalid key metadata falls back to the actual provider, never bypasses
        its veto/error policy.
      stable=True: a pure provider depends only on unchanged map/catalog/input
        records, not temporary actor/shot projections. Computational consumers
        can ask stable_subscribers(point, engine) before sharing derived values.
        Unknown/dynamic providers default False; this flag never caches by itself.
    Defaults are unfiltered/uncached. No gameplay hook is implicitly pure; no
    index/reply survives enumeration or enters saved state. Registration changes
    invalidate active indexes. These opt-ins must not be used for spend/event,
    sequential transform, or player-choice providers.
    """
    if type(priority) is not int:
        raise ValueError("hook priority must be an integer")
    if type(stable) is not bool:
        raise ValueError("hook stable must be a boolean")
    if nested and point != "event":
        raise ValueError("nested subscriptions are supported only for event hooks")
    def register(function: Callable[..., Any]) -> Callable[..., Any]:
        _HOOK_PRIORITIES[(point, function)] = priority
        _HOOKS[point].append(function)
        _HOOKS[point].sort(key=lambda subscriber: _HOOK_PRIORITIES.get((point, subscriber), 0))
        if present is not None:
            _HOOK_PRESENT[(point, function)] = present
            _FILTERED_POINTS.add(point)
        if query_key is not None:
            _HOOK_QUERY_KEYS[(point, function)] = query_key
        if stable:
            _STABLE_QUERIES.add((point, function))
        else:
            _STABLE_QUERIES.discard((point, function))
        if nested:
            _NESTED_HOOKS[point].add(function)
        return function
    return register


def _selected(point, args):
    """Build an ordered active index once per hook/fight enumeration revision."""
    functions = _HOOKS.get(point, ())
    if point not in _FILTERED_POINTS or not args:
        return functions
    cache = enumeration_cache(args[0])
    if cache is None:
        return functions
    key = ('hook_index', point, id(functions), len(functions))
    cache.setdefault(('hook_registry', point, id(functions)), functions)
    selected = cache.get(key)
    if selected is None:
        active = []
        for function in functions:
            predicate = _HOOK_PRESENT.get((point, function))
            if predicate is not None:
                try:
                    if predicate(args[0]) is False:
                        continue
                except Exception:
                    pass  # the actual provider retains its original error policy
            active.append(function)
        selected = cache[key] = tuple(active)
    return selected


def stable_subscribers(point, engine):
    """Ordered active query providers, or None if any has dynamic dependencies.

    Consumers include the returned tuple in their memo key so registration
    changes invalidate derived values. Default-inert: an unannotated provider
    forces ordinary evaluation. Never infer stability from a function's body.
    """
    _load()
    functions = tuple(_selected(point, (engine,)))
    return functions if all((point, function) in _STABLE_QUERIES for function in functions) else None


# Recovery/defense seams (H203FIX1): typed_reactions.on_healing_pending(engine,
# subject, integer amount, healer, source, kind) dispatches only instantaneous
# recovery-reduction rows before HP/temp HP commitment; ordinary healed and
# temp_hp_gained listeners retain their committed-gain timing. The transient
# _pending_healing frame is restored on nested resolution and controller pause.
# reaction_rows(engine, actor_id, block, rows) can specialize an owned benefit
# response to an exact event receipt (erode_technique); absent that ownership it
# returns None. benefit_gained is dispatched with the gaining creature/source.
# reaction_defense_amount(engine, actor, row, amount) reads the accepted frame's
# integer numeric_reduction after counters; returns the original amount when
# none is present. Shared by AC, damage, shield and movement-prevention consumers.
# Benefit receipts (H203FIX1F1, erode_technique): "benefit_gained" answers are
# classified by the gain classifier, and the exacted decision's wording rides
# the documented trigger keys a generic row names in "decision_details"
# (typed_reactions.inherit_decision_details: affected_id, action_name,
# display_trigger, display_summary). reaction_rows replacements chain in
# subscriber order (ext.strict_chain) so a row one provider specialized survives
# another provider's pass (reaction_menus) instead of being erased. Nested child
# receipts (a benefit made inside another handler, e.g. a Stamina Guard soak's
# +1 AC) reach benefit_gained only through the event hook's nested= opt-in, with
# the subscriber refusing its own reduced replacement ("erode:" application id /
# own source) so the response cannot erode itself, and the concentration-bound
# original's early ending takes the stored substitution with it
# (erode_technique.expire_concentrated).
def _load() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    for module in sorted(pkgutil.iter_modules(__path__), key=lambda row: row.name):
        importlib.import_module(f"{__name__}.{module.name}")


def effects() -> dict[str, Callable[..., Any]]:
    _load()
    return _EFFECTS


def effect_harm(name: str) -> bool | None:
    """Pure registration metadata used by combat.effect_harm's shared contract."""
    _load()
    return _EFFECT_HARM.get(name)


def effect_forge_rejection(name: str) -> str:
    """Pure, default-inert portability metadata for construction menus."""
    _load()
    return _EFFECT_FORGE_REJECTION.get(name, "")


def transform(point: str, value: Any, *args: Any, **kwargs: Any) -> Any:
    """Compose pure replacements sequentially; None retains the current value."""
    _load()
    for function in _HOOKS.get(point, []):
        replacement = function(value, *args, **kwargs)
        if replacement is not None:
            value = replacement
    return value

def transform_reduction(point: str, amount: int, *args: Any) -> int:
    """Strict sequential integer reduction; reject before the next provider runs."""
    if type(amount) is not int or amount < 0:
        raise ValueError(f"{point} requires a nonnegative integer amount")
    for function in subscribers(point):
        replacement = function(amount, *args)
        if replacement is None:
            continue
        if type(replacement) is not int or not 0 <= replacement <= amount:
            raise ValueError(f"{point} must retain or reduce the nonnegative integer amount")
        amount = replacement
    return amount


def iter_strict(point: str, *args: Any, **kwargs: Any):
    """Transactional lazy dispatch: callers may stop before another provider spends."""
    _load()
    for function in _HOOKS.get(point, []):
        result = function(*args, **kwargs)
        if result is not None:
            yield result

def iter_strict_all(point: str, *args: Any, **kwargs: Any):
    """Ordered lazy transactional dispatch, including None replies.

    The caller can validate state and stop between subscribers, before the next
    one runs. Exceptions propagate for normal transaction rollback. Snapshot the
    registered order so nested registration cannot change this dispatch.
    """
    _load()
    for function in tuple(_HOOKS.get(point, ())):
        yield function(*args, **kwargs)

def subscribers(point: str) -> tuple[Callable[..., Any], ...]:
    """Snapshot strict providers for lifecycle points with per-provider rechecks."""
    _load()
    return tuple(_HOOKS.get(point, ()))
class CheckpointError(ValueError):
    """A paid checkpoint failed; observational guards must let it roll back."""


class OptionalFollowupTargetConflict(ValueError):
    """More than one plug-in answered the one-owner optional_followup_target seam.

    Transactional: the caller rolls back. A discovery pass that answers prompts
    with a synthetic decline may catch exactly this rejection, because the
    decline can leave another consumer as the only apparent answer; every other
    error still surfaces (combat/gate5_service.py).
    """


def run_checkpoint(point: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Strict paid-effect hooks retain rollback through nested observational hooks."""
    try:
        return run_strict(point, *args, **kwargs)
    except CheckpointError:
        raise
    except Exception as exc:
        raise CheckpointError(f'{point}: {exc}') from exc


def run_strict(point: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Transactional hooks: errors (including a choice-provider pause) must unwind.

    Unlike observational hooks, swallowing an error could commit half an effect.
    Only call inside an engine transaction, preview clone, cold-store transaction
    or uncommitted match genesis; the caller discards state on failure.
    """
    _load()
    return [result for function in _selected(point, args)
            if (result := function(*args, **kwargs)) is not None]


def strict_chain(point: str, *args: Any, **kwargs: Any) -> Any:
    """Sequential transactional dispatch for row-shaping providers (reaction_rows).

    Each subscriber receives the previous subscriber's replacement of the LAST positional argument,
    in the same selection and error policy as run_strict; None retains the current value. A
    last-wins read of every reply silently erased every earlier specialization once a second
    provider existed (H203FIX1F1). Returns the final value.
    """
    _load()
    value = args[-1]
    for function in _selected(point, args):
        replacement = function(*args[:-1], value, **kwargs)
        if replacement is not None:
            value = replacement
    return value


def effect_permitted(ctx: Any, effect: dict[str, Any], subjects: Any, *, exclude=None) -> bool:
    """Strict permission query for effects folded into another effect's delivery.

    Calls effect_allowed(ctx, effect) and effect_subject_allowed(ctx, effect, subject)
    for every supplied recipient. False vetoes delivery; no subscribers permits it.
    ``exclude`` is the caller's suppression callback, omitted to avoid recursively
    suppressing the very effect being queried. Other providers and errors retain
    their normal contract. This query does not consume use clocks.
    """
    replies = [function(ctx, effect) for function in subscribers("effect_allowed")
               if function is not exclude]
    return not any(reply is False for reply in replies) and all(
        not any(reply is False for reply in run_strict("effect_subject_allowed", ctx, effect, subject))
        for subject in subjects)


def reduce_amount(point: str, engine: Any, subject: Any, amount: int) -> int:
    """Fold a transactional amount-reduction hook over the surviving integer amount.

    Shared by the healing restriction and assignment stages in typed_executor.
    A hook cannot increase the amount; zero prevents later hooks spending a denied
    offer. Errors and player-choice pauses unwind the owning transaction.
    """
    _load()
    amount = max(0, int(amount))
    for function in _HOOKS.get(point, []):
        if amount == 0:
            break
        result = function(engine, subject, amount)
        if result is not None:
            amount = min(amount, max(0, int(result)))
    return amount


def query(point: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Read-only presentation hooks: skip failures without writing fight events.

    Handlers must be pure. Used by status_description for condition, mark and
    terrain descriptions; transactional/gameplay hooks still use their own paths.
    """
    import logging

    _load()
    out = []
    for function in _HOOKS.get(point, []):
        try:
            result = function(*args, **kwargs)
            if result is not None:
                out.append(result)
        except Exception:
            logging.getLogger(__name__).exception("Presentation hook %s failed: %s", point, function.__name__)
    return out


def remember_recorded_event(engine: Any, event: Any) -> None:
    """Shared identity seam for prepared_actions.on_event and extension event dispatch.

    Gate 2 supplies the actual recorded Event to prepared_actions before Gate 4
    dispatches it. Remember it before Ready delivery and again in that delivery's
    finally block: children dispatch their own identity, then the parent resumes
    with its original identity even when Ready appended events or paused.
    Holds one transient reference on the engine; never serialized, never changes
    event bytes or delivery order, and performs no ability behavior.
    """
    engine._ext_recorded_event = event


# Human lazy discovery (combat.lazy_menu) emits source-only action headers and
# priced movement geometry, not issued candidates. candidate_allowed and all
# destination/target-specific providers run on action_candidates_for_sources or
# the existing movement-destination preview, then again in native commit binding.
# A header must never be submitted, cached as an AI candidate, or used as proof
# that a particular target is legal. Default/native enumeration is unchanged.
def callbacks(point: str) -> tuple[Callable[..., Any], ...]:
    """Stable subscriber order for native checkpoints that recheck between replies.

    Callers invoke within a transaction and propagate errors/ControllerPause,
    just like run_strict. Taking the snapshot does not invoke any subscriber.
    """
    _load()
    return tuple(_HOOKS.get(point, ()))


def invoke(point: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """One registered observational callback; shared by run and hit defenses."""
    try:
        key = _HOOK_QUERY_KEYS.get((point, function))
        if key is not None and args:
            cache = enumeration_cache(args[0])
            if cache is not None:
                try:
                    cache_key = ('hook_reply', point, function, key(*args, **kwargs))
                    hash(cache_key)
                except Exception:
                    return function(*args, **kwargs)
                if cache_key not in cache:
                    cache[cache_key] = function(*args, **kwargs)
                return cache[cache_key]
        return function(*args, **kwargs)
    except (ControllerPause, CheckpointError):
        raise
    except Exception as exc:  # noqa: BLE001 -- preserve observational hook policy
        from ..gate5_service import _ReactionRequired
        if isinstance(exc, _ReactionRequired):
            raise
        _log(point, function, exc, args)
        return None


def run(point: str, *args: Any, _nested_only: bool = False, _transform_last: bool = False,
        _with_handlers: bool = False, **kwargs: Any) -> list[Any]:
    """Every registered hook's result for this point (None results dropped). A hook that raises is skipped."""
    if point == "event":
        from .retained_updates import is_retained_update
        from .setting_choices import setting_intent_event

        if is_retained_update(args[1], args[2].get("payload") or {}):
            return []
        if setting_intent_event(args[0], args[1]):
            return []
        # Ready may already have appended events before Gate 4 reaches us.
        # Snapshot the preserved recorded identity, never the mutable log tail.
        engine, event_type, event_kwargs = args
        event = event_kwargs.get("originating_event") or getattr(engine, "_ext_recorded_event", None)
        args = (engine, event_type, {**event_kwargs, "originating_event": event})
    _load()
    out = []
    for function in _selected(point, args):
        if _nested_only and function not in _NESTED_HOOKS.get(point, ()):
            continue
        result = invoke(point, function, *args, **kwargs)
        if result is not None:
            out.append((function, result) if _with_handlers else result)
            if point == "compile_action":
                args = (result, *args[1:])
            if _transform_last:
                args = (*args[:-1], result)
    return out


def transform_last(point: str, *args: Any) -> Any:
    """Sequential pure transforms of the last argument in registration order.

    Subscribers return a replacement or None to retain the current value.
    Use only for documented transformation contracts (currently wall_defenses).
    Failures use run's ordinary skip/log policy and retain the previous value.
    """
    results = run(point, *args, _transform_last=True)
    return results[-1] if results else args[-1]


def has(point: str) -> bool:
    """Whether any module registered this hook point (lets a hot path skip the call)."""
    _load()
    return bool(_HOOKS.get(point))


def any_false(point: str, *args: Any, **kwargs: Any) -> bool:
    if (point in ("event", "compile_action") or run is not _RUN
            or kwargs.keys() & {"_nested_only", "_transform_last", "_with_handlers"}):
        return any(result is False for result in run(point, *args, **kwargs))
    # Hot path (candidate_allowed runs every subscriber for every legal candidate): the same subscribers and order as
    # run(), with invoke()'s single error policy, but no result list per subscriber. Every subscriber still runs; there
    # is no short-circuit. run()'s dispatch-control keywords and special points always go through run() itself.
    _load()
    vetoed = False
    for function in _selected(point, args):
        result = invoke(point, function, *args, **kwargs)  # the one shared error policy
        if result is False:
            vetoed = True
    return vetoed


_RUN = run


def vetoing_hooks(point: str, *args: Any) -> tuple[str, ...]:
    """Pure diagnostic query used by system_bookkeeping and Gate 5 recovery.

    Return sorted qualified handler names whose ordinary hook result is False;
    use the same exception/skip semantics as run. Never append a fight event.
    """
    return tuple(sorted({f'{function.__module__}.{function.__name__}'
                         for function, result in run(point, *args, _with_handlers=True)
                         if result is False}))


_LISTING = {"legal_candidates", "_action_candidates", "_candidates", "_move_candidates", "_pending_candidates",
            "vetoing_hooks"}


def _while_listing() -> bool:
    """Whether the engine is listing legal choices right now: a fight event written then changes every candidate id, so
    every button the table shows is refused as stale (round14 reconcile, 2026-09-30: one failing hook, 436 events)."""
    import sys

    frame = sys._getframe(2)
    while frame is not None:
        if frame.f_code.co_name in _LISTING:
            return True
        frame = frame.f_back
    return False


def run_nested(point: str, *args: Any, **kwargs: Any) -> list[Any]:
    """Ordered observational dispatch to explicitly opted-in nested subscribers."""
    return run(point, *args, _nested_only=True, **kwargs)


def floored(engine: Any, actor: Any, roll: Any, dc: int | None = None, *, ability: str | None = None,
            skill: str | None = None) -> Any:
    """``roll`` (a d20 check the actor just rolled) with its total raised to a d20 floor a plug-in sets, or ``roll``
    itself. The natural die stays as rolled (a natural 1 is still shown as a 1); only the total changes. ``dc`` is what
    the check must reach when the caller knows it (a plug-in may spend something only when the floor turns a failure into
    a success). Callers compare ``roll.total`` afterwards, as they always did.
    Grapple, Binding and granted escape options share ext.escape_checks.resolve_escape_check:
    (ctx, effect, dc, grips, against=(), *, check_name="", target_id=None,
    source_id=None, source_actor_id=None, check_ability=None, check_skill=None)
    -> bool, resolving modes/check_bonus,
    the evented roll, this floor/Release checkpoint and CHECK_ROLLED. Callers
    retain removal policy; absent owned check effects, legacy resolution is unchanged.
    check_ability/check_skill keywords select a specific check with hazard-scoped modes;
    omitted keywords keep legacy effect-based resolution. Optional metadata identifies
    the helped target and originating hold; defaults keep ctx.actor/ctx.source metadata.
    ctx.actor is always the roller. Existing hook signatures and persistent state
    remain unchanged.
    ``ability=``/``skill=`` name the check being floored for a caller that rolls outside a ``d20_scope``; they publish
    that on the roll's own frame, so ``check_floor`` plugs-in can narrow a floor to the printed "one *such* ability check"
    (combat/ext/d20_floor.py). Omitting them reads whatever the active scope already carries, which is what every caller
    inside ``d20_scope`` did before."""
    if not has("check_floor") or roll is None or roll.natural_result is None:
        return roll
    if ability or skill:
        with engine.d20_scope({"kind": "check", "actor_id": actor.entity_id, "source_id": str(roll.reason or ""),
                               "ability": ability, "skill": skill, "dc": dc}):
            return floored(engine, actor, roll, dc)
    floors = [int(value) for value in run("check_floor", engine, actor, roll, dc) if isinstance(value, int) and not isinstance(value, bool)]
    if not floors or roll.natural_result >= max(floors):
        return roll
    return roll.model_copy(update={"total": roll.total + max(floors) - roll.natural_result})


def ai_controlled(engine: Any, actor: Any) -> bool:
    """Whether ``actor`` is run by a computer instead of a person at the table.

    Who controls a creature is a saved fact about the match, not a guess: the table records each
    participant's control mode when the match is created (``gate5_service``'s
    ``participant_control_modes``) and the engine keeps it on ``typed_control_modes``. A
    LOCAL_AUTO/API_AUTO participant has nobody to press a button, so a plug-in that must ask that
    creature a question decides for it; a MANUAL/SUGGESTED/MANUAL_AI_BRIDGE participant is the
    table's to answer, and the service asks them (see ``gate5_service.answer_pending_choice``).

    A creature is looked up by its controlling participant -- the table drives summons, companions
    and other dependents through the character that owns them -- and a match with no recorded mode
    for it is read as MANUAL, the same default gate2_engine and gate5_service use.

    For a Needle choice, pass this as ``ask(..., automatic=...)``: ``automatic=True`` lets the
    controller take the preferred option (``gate4_controller.choose_reaction`` reads
    ``automatic_use or not allow_decline``), ``automatic=False`` leaves the question to the person
    at the table. Team membership is not a control mode -- allies are not automatic, and an
    enemy is not the reason a creature's own choice is made for it. Used by d20_floor's replacement
    and keep-cost questions, life_state's soul-return and continuity prompts, and any other plug-in
    whose "may" or "choose" text has to be decided for a computer-run creature.
    """
    modes = getattr(engine, "typed_control_modes", None)
    if modes is None:
        modes = (getattr(engine, "_roster_setup", {}) or {}).get("participant_control_modes", {}) or {}
    if actor is None or not modes:
        return False
    for key in (getattr(actor, "owner_id", None), getattr(actor, "entity_id", None)):
        if key and modes.get(key) in {"LOCAL_AUTO", "API_AUTO"}:
            return True
    return False


def note(engine: Any, source: str, actor: Any, text: str, targets: Any = (), **payload: Any) -> None:
    """One plain log line for the table's history (sys-resources-states 2026-09-29): a PASSIVE_TRIGGERED event whose
    payload carries the sentence, which combat/history_feed.py shows as it is. The reducer treats the event as
    non-mutating, so it is safe in a saved fight."""
    engine._append_event("PASSIVE_TRIGGERED", source, actor_id=getattr(actor, "entity_id", actor),
                         target_ids=tuple(getattr(target, "entity_id", target) for target in targets), payload={"log": text, **payload})


def _log(point: str, function: Callable[..., Any], exc: Exception, args: tuple[Any, ...]) -> None:
    import logging

    logging.getLogger("combat.ext").warning("%s.%s (%s) failed: %s: %s", function.__module__, function.__name__, point, type(exc).__name__, exc)
    engine = next((getattr(arg, "engine", None) or (arg if hasattr(arg, "_append_event") else None) for arg in args
                   if hasattr(arg, "engine") or hasattr(arg, "_append_event")), None)
    if engine is None or _while_listing():
        return  # logged above; never a fight event while choices are being listed
    seen = engine.__dict__.setdefault("_ext_failures_logged", set())
    key = (function.__module__, function.__name__, point, type(exc).__name__)
    if key in seen:
        return  # once per fight for each failing hook, not once per call
    seen.add(key)
    if not getattr(engine, "_ext_logging", False):
        engine._ext_logging = True
        try:
            engine._append_event("GM_RIDER", f"ext:{function.__module__}", actor_id=engine.state.current_actor_id,
                                 payload={"rider": f"{function.__module__}.{function.__name__} ({point}) failed: {type(exc).__name__}: {exc}"[:400]})
        finally:
            engine._ext_logging = False

# AUTO41: figment.py reuses compile_actions, match_start, additional_actions,
# candidate_allowed and save; no new hook point. figment_study spends the normal
# Action on one perceived placement. Recognition/study/immunity are per-zone
# creature IDs recorded through placed.update. figment_create's minor flag
# gives the owned 5-foot, 100-round image without Concentration or paid setup;
# figment_minor_detail and the minor figment_move retain Bonus Action economy.
# illusion_sting_premise in illusion_riders.py is Phantom Sting's optional hit
# follow-up. All choices use Needle; unrelated actors/zones leave hooks inert.
# Ordinary Study checks set escape_checks.resolve_escape_check(escape_hooks=False)
# to keep hold-only Advantage separate while sharing check bonuses, scopes and
# floors. ability_checks.ordinary_check_bonus returns None for missing ordinary
# statistics: optional check actions must not substitute saving-throw totals.
# Phantom Sting queries senses.perceives_cell at its hit stimulus, not its caster.


# AUTO42: stars.py uses the existing flight hook for active Star-Sovereign
# conditions and source-owned Star Shadow summons. stars_starbolt_mark resolves
# the optional once-per-turn on-hit mark through Needle. stars_spark_pick chooses
# one actual marked area recipient before the existing save hook penalizes it.
# stars_impact_terrain
# creates persistent, evented difficult ground from the actual impact aim;
# Falling Star requires known caster alignment, Heaven-Falling Star uses the
# impact point. Meteor's enlarged variant uses ordinary compilation/candidate
# gates and the caster's known Domain alignment. No core or lock seam changed.

# CW1r1: karma_causes.harmful_condition/inflicted_harm are public shared
# classification helpers for Karma imprint and consequence event consumers.
# They use actual typed negative mechanics/explicit harmful kinds, excluding
# presentation-only colour, beneficial/defense/structural rules and self-costs.
# No new hook, runtime patch or lock integration is introduced.

# AUTO44: poison.py reuses flight, damage_defenses, escape_mode, compile_block,
# compile_actions, save_final, after_hit_choice and event. No new core seam.
# poison_delivery_save gates the actual delivery save once per turn;
# poison_next_check consumes its evented condition on that holder's next check.
# poison_dose_followup resolves saved, reviewed failure/success branches via
# optional Needle choices after the final save, including actual-paid CP pricing.
# All hooks require an owned Poison row/active source; native flight uses the
# existing altitude and concentration lifecycle. Unknown physical provenance
# never gains the nonmagical resistance.



# AUTO45: riders_metal.py reuses compile_action, effect, save_final, zone_recipient_allowed,
# turn_start and turn_end. metal_needle_seal resolves reviewed per-recipient
# post-hit/failure choices and one optional Nascent second seal per activation.
# metal_filings_cloud gathers actual final saves before one placement; its
# terrain policy uses the existing zone recipient veto, so a successful save
# exempts only that cloud during the casting turn. Owner-start/end clocks are
# stored in evented placement data. Other zones and old sealed rows are inert.
# metal_needle_interference requires the actual recipient's active Concentration.
# metal_needle_targets reuses the bounded roster chooser, including explicit
# self recipients. Automatic harmful selections stop at the hostile count.



# AUTO46: magma_crust.py reuses before_target_reactions, attack_damage, effect, candidate_allowed,
# zone_recipient_allowed and turn_start. Only reviewed Magma Glob rows choose
# an actual post-hit expression and spend the integer global-turn allowance.
# Active Volcano-Sovereign marks replace Glob dice; ownership alone is inert.
# Shape the Crust's saved ally/patch receipt vetoes only that patch's terrain
# and hazards, and expires on the source's next start. Other zones are inert.
# Shape's reviewed editing_existing marker removes inferred new terrain from
# the fresh action-local context. Its sealed catalogue retains aim eligibility;
# existing patches are edited without creating both named terrains at the aim.

# AUTO47: iron_forms.py reuses attack_result and after_hit_choice. The reviewed
# hundred_forms ownership marker counts actual Unarmed Strikes in one Attack
# action, including misses and nonterminal defeating strikes. Two distinct supported Forms are stored in an
# evented owner-end condition. Uses share the existing per-strike Form ledger,
# so ordinary/Court/Sovereign choices cannot repeat a Form on the same strike.
# Old bundles without the marker retain the prior helper behavior.

# AUTO61: river_riders uses save_final for newly sealed rider_response_fail
# declarations with final_save=true. It matches the actual selected Response
# talent and failed final save within physical melee reach, independent of a
# spent Reaction. Soft Body, Hard Floor reuses the shared rider menu and native
# cannot_stand/Speed/no_dash effects with target-next-start expiry. Legacy
# declarations without the marker keep their after_save path; ordinary saves
# and unowned rows are inert. No new core seam or runtime patch.
# Low River Stance additionally supplies stand_cost=5 only for its newly owned
# flowing_river/low_river_stance row, through the existing native posture path.
# It does not bypass standing vetoes, budget or Speed; old/unowned rows are inert.

# AUTO62: destruction_blast/destruction_shapes reuse compile_action, existing
# effect dispatch and candidate_allowed; no core or lock-file changes.
# New reviewed destruction_shape_save pays/freezes Deepen before saving throws,
# uses final CP (including existing Engine/Incarnation discounts) for success
# damage, and asks an optional self exclusion without excluding other creatures.
# compile_action preserves CELL/single-creature delivery and AI damage estimates.
# prepare_release is the public helper shared by finite saves, distinct rays and
# newly bound tethers. The reviewed distinct_rays/bind_target markers opt in new
# sealed actions; markerless saves/rays/tethers retain their old behavior.
# damage_required checks actual committed HP/temp-HP damage before type/reward
# riders. Returning Calamity's cost/range correction is typed-data only.
# Tether candidate_allowed is a pure target/active-condition query. New tether
# condition data freezes target id, type id, dice count, save DC and final CP;
# Concentration-end owns its lifetime. No engine mutation or private cross-plugin
# calls. New self-exclusion ownership rows are absent from historical bundles.
# Caster exclusion uses before_target_reactions to narrow the live area roster
# before reaction admission. Shared rider_targets accepts an optional prompt;
# absent text preserves its existing prompt. New single_collision_die ownership
# rows give Hammer exactly one d8; old compiled Hammer rows keep their old pool.

# AUTO109/AUTO109r1f1: destruction_break_guard_option (destruction_blast.py) resolves
# "Break the Guard: a creature can suffer only one option at a time". Arguments:
# ctx (the failed Fracturing/Scouring save, already narrowed to the one subject)
# and eff {"option": "ac"|"advantage"|"cover", "type_id": the Blast Type that
# resolved this release}. It first removes exactly what the creature's recorded
# earlier option left -- the exact condition/modifier instance ids named by its
# destruction_break_guard_active marker, which also records the caster that put
# them there -- then applies the ordinary typed effect for the new option
# (ac_bonus / advantage / destruction_no_half_cover) and re-records the marker
# with the option, those instance ids, the caster, the activation and the Blast
# Type in force. Same-option instance lifecycle is unchanged.
# Two owners of the talent are handled: the rule is about the creature, so a
# second caster replacing an option removes the first caster's instance, located
# by the marker the first wrote rather than by the caster now acting. Because the
# marker names exact instances, Fracturing Break's own Advantage survives an
# option change even though it rides the same release and source as the guard's
# (AUTO109r1f1; an earlier version matched by field and had to leave it alone).
# "type_id" is the Type that actually resolved, never the live sticky choice:
# Ruin-Binding Tether and Calamity Mantle freeze their Type, so a Pulse records
# the Type it froze. Marker data is strings only (option/caster/origin/type_id/
# mods/conds/label) so it survives a commit and reload. A marker from before the
# instance ids were recorded falls back to matching the marker's source actor
# and recorded activation. Inert unless the actor owns Break the Guard and has an option
# chosen. No new hook point, no core or lock file change; reached through the
# existing effect dispatch.

# AUTO113: River Breaks the Charge is GM-resolved; charge_approach and its event
# subscription were withdrawn. MOVEMENT_COMMITTED reports completed movement, not
# the reach-entry step at which this Response must resolve. Any future automation
# must resolve at reach entry after the qualifying voluntary approach, before the
# mover continues, and preserve the printed Reaction, save and choice requirements.
# LOW_RIVER_STANCE (stand_cost) and river_riders' final-save rider_response_fail declarations
# came from cloud worker AUTO61; they are documented in their own modules.


# AUTO47: iron_forms.py reuses attack_result and after_hit_choice. The reviewed
# hundred_forms ownership marker counts actual Unarmed Strikes in one Attack
# action, including misses and nonterminal defeating strikes. Two distinct
# supported Forms are stored in an
# evented owner-end condition. Uses share the existing per-strike Form ledger,
# so ordinary/Court/Sovereign choices cannot repeat a Form on the same strike.
# Old bundles without the marker retain the prior helper behavior.


# AUTO102: magma_crust.py adds magma_furnace_step for Furnace Step's own printed
# exemptions, reusing candidate_allowed, difficult_exempt and zone_recipient_allowed.
# It pays no new hook point: the effect asks which one creature gets no opportunity
# attack (rider_choices.pick, Needle) and denies that creature an opportunity attack
# against the mover through the existing reaction_denied path, so every other creature
# keeps its own. The turn's receipt is one evented condition, and the two ground hooks
# read only that condition, so the plug-in is inert for anyone who does not own Furnace
# Step and for old saved fights. The printed clause waives movement cost, so
# difficult_exempt returns squares of your own Molten Terrain and of ordinary ground
# painted on the battlefield (combat/rules/terrain.json's map terrains) -- never ground
# an ability conjured, and Fire Terrain never at all. The engine subtracts those squares
# from the whole board, so the exemption is computed per source: a square is returned only
# when every area on it is one the clause names and no other area still charges that
# creature for it, which keeps another caster's lava or Obsidian Terrain difficult where it
# overlaps yours. "Still charges that creature" is asked of the engine's own per-area answer,
# zones.zone_is_difficult (the public seam difficult_cells itself uses), rather than reading the
# area's difficulty policy again: ground whose policy does not reach this creature -- aimed at
# other creatures, needing a mark this creature does not bear, or ignored as nonmagical --
# leaves the printed waiver standing. zone_recipient_allowed is narrower still: only your own
# Molten Terrain stops dealing you its hazards, so hostile Fire Terrain and Ash Terrain still
# save, burn and obscure. No core, gate2/gate3 MatchLock or saved-fight lock file is touched.

#
# AUTO122: riders_metal.py adds one consumer of the existing target_eligibility
# hook (no new hook point, no core change, no saved-state field).
# metal_damaged_this_turn(engine, owner, target) is a public shared helper that
# reports whether the owner dealt this target real damage from a Metal-catalogued
# attack or technique during the owner's own turn, read from committed
# DAMAGE_COMMITTED events (actor, target, non-zero committed damage, Metal source).
# glance_target_eligibility uses it to enforce White Tiger Glance's printed
# prerequisite "one creature you can see that you damaged this turn with a Metal
# attack or technique": it returns False (a pure strict target veto) for a
# creature the owner has not Metal-damaged this turn, and None for one it has,
# so the printed "you can see" is left to the ordinary knowledge, range and
# line-of-sight checks. It must not answer True, which is the documented owned
# visibility exception and would reach Glance through cover or blocked sight.
# The helper is the reusable piece; other "damaged by you this turn"
# prerequisites may adopt it. Delivery through a weapon carrying Metal Qi is a
# later provenance contract (M1/M2) and is deliberately not inferred here. The
# gate is inert for actors who do not own Glance and for every other action.

# AUTO123: poison.py adds one owned effect and reuses five existing seams for Coated Weapon, Venom in the Wound and the
# save-success Temporary HP riders; no new hook point and no core change.
#   poison_coating is the new effect: it places the owner's own coating condition, carrying the printed Proficiency Bonus
#     charge count and the printed 1-minute deadline, bound to one chosen held item's identity.
#     after_hit(ctx, target, kind) reads it and runs the printed once-per-turn damage and Constitution save; only an
#     applied Dose Mark spends a charge. Default inert -- with no coating condition the handler returns at once.
#   after_hit_choice(ctx, target, kind) is not used by these riders; see damage_dealt below.
#   damage_dealt(ctx, subject, amount) is Venom in the Wound's optional 2 CP rider. The engine reports this hook only for
#     damage it actually committed (hit points lost plus Temporary HP absorbed), on the attack path and on the
#     save-resolved path alike, so the printed "when you damage a creature" excludes a hit a Resistance or immunity kept
#     at 0 while a save-based poison effect still offers it.
#   save_mode(engine, target, ability, dc, source_id, mode_context) is Venom in the Wound's Blood-sphere Disadvantage for a
#     bleeding target. Disadvantage is a d20 mode, not an integer modifier: this is the seam that rolls two d20s and keeps
#     the lower, while save_bonus returns are summed into the single roll's modifier. It fires only on a Constitution save and
#     only while that creature really carries a Bleeding condition, and only for the saving throw the printed rider itself
#     makes -- its own source id, not any other toxin save -- with the "If you have the Blood sphere" half read from this
#     fight's own catalog (the owner-bound Blood Thread action granted only to Blood sphere owners). A Poison-only
#     character imposes no Disadvantage. Forged Poison + Blood provenance remains explicitly deferred.
#   after_save_resolved(ctx, subject, ability, named, failed) is Venom Body Method's and Thousand-Poison Immunity's
#     Temporary HP. The reward belongs to the creature that saved, so ownership is read on `subject`, the amount uses that
#     creature's own Proficiency Bonus (ext/spirit_traditions.numbers), a save whose own condition names no toxin pays
#     nothing, and each rider keeps its own limit in the engine's turn-flag "once_per_round:" clock (which the owner's turn
#     start retains). Thousand's optional "you may" is a Needle choice on either side's turn, and declining spends nothing.
#   compile_actions adds Coated Weapon's Bonus Action, because the typed row's action is marked automated in
#     combat/rules/feature_blocks.d/auto44_poison.json and would otherwise not be built.

# AUTO93 Retribution: existing retribution_dug_in accepts opt-in choose_instance.
# It stores integer choose_instance=1 with the original target id on its native
# owner-next-start condition. The existing incoming_damage hook asks that owner
# on each positive B/P/S packet from that target; decline preserves protection,
# accept consumes it once. Player ownership is unchanged on an enemy AI turn;
# automatic owners choose automatically. Missing flag keeps the old automatic
# first-packet reduction. This uses public needle.ask/checkpoint_id only, with
# no new core seam. Native non-stacking Resistance integration remains a written
# blocker; the existing reduction is not certified as a complete Resistance rule.
# Terrifying Hook and Violent Pressure newly compiled Frightened rows use native
# recipient-next-end expiry. Older sealed special durations are not rewritten.
# AUTO126 (corrected by AUTO126r1f1): retribution_haymaker asks combat/physiology.trait
# whether the target has a voice_and_breath_channel before it damages it, so a printed
# "a creature without a meaningful mouth, throat, breath channel, or equivalent anatomy
# is immune" resolves from a fact the creature's own printed record states. That trait
# has no default and no creature-type default: an unstated record reads as unknown and
# the hit lands as it always did, and not needing to breathe (breath_dependent) is a
# different fact, so an undead or construct with a working mouth can still be silenced.
# physiology.trait is the shared documented query; it changes nothing unless an ability
# asks for it, and only a character owning Haymaker reaches this check.

# AUTO92 Sabers: existing after_hit(ctx, target, kind) consumes only the newly
# sealed sabers_rider/battleline_shove_cut_v2 hit_effects row and a Sabers action.
# Native if_moved, paid_option and save/menu effects own movement, payment and
# final outcomes. No marker means no new behavior. if_size_at_most now accepts
# optional absolute max_size (Tiny..Gargantuan); missing max_size preserves the
# old relative-footprint behavior. Consumers: Battleline Shove-Cut, Horse Arc.
# Existing cone_passage accepts opt-in choose_allies; it records chosen live ally
# ids once per activation and native line cells/owner-start expiry. Its existing
# opportunity_allowed hook narrows to recorded allies; markerless Army passage
# keeps its team-wide behavior. Native Infantry no_opportunity_attacks is target
# next-end only; no core hook/seam or serialized lock format changes.
# The same AUTO92 paid_saber_hit hook now reads explicit sealed source_mechanics
# lists (including generic reactions, whose Context lacks a sphere tag). Ten-Step
# Pursuit is its second data consumer: Red Trail hit, optional2CP, native next-end
# slow. No hit_effects/source list means no new behavior in old passive rows.
# The aggregate Secret Saber Manuals heading is passive text for newly compiled
# fighters; four independently gated manuals require separate acquisition rows.
# compile_actions seals resource_id=primary in these two new paid hit rows to
# the owner's declared CP pool before bundle hashing; old rows are untouched.
# AUTO127r1f1: Forward Cut's printed "you may also move 5 feet after the hit without
# provoking Opportunity Attacks from that target" is now the existing rider_step row with
# no_oa_from_target, not ignore_oa_from_target. The step is asked for, moves at most the
# printed 5 feet through native granted movement, and its exemption covers that step and
# that one creature only: the old turn_flags spark_step_ignore_oa_from outlived the five
# feet for the rest of the turn, and the older no_opportunity_attacks flag waived every
# creature's Opportunity Attack. Typed data only; no new hook and no core change.
# if_size_at_most's optional max_size reads dynamic_size.current_category, so recorded
# growth and a wide sealed footprint are the creature's current size; a markerless row
# keeps the relative-footprint reading. Saber Scare's critical receipt is one key written
# on every settled result (a miss or an ordinary hit clears it), so the printed trigger
# applies to the attack that just resolved and only for an owner of the row.

# AUTO90: shadow.py adds only declared effects, no core seams.
# shadow_fang_mark offers the hit's optional owner choice through Needle, then
# delegates the actual source-owned mark and owner-next-start expiry to native
# effects. Historical sealed plain mark effects remain automatic.
# shadow_grasping and shadow_lingering_trace(choose_older=true) reuse the public
# mark_applied_in_use helper: a committed CONDITION_APPLIED receipt for this
# source/target after this intent began is required, including actual refreshes.
# A retained mark cannot turn a later miss into a new Imprint. The new Lingering
# flag chooses older marked creatures before removing their instance IDs and
# uses the native eight-hour round-clock deadline. Flagless saved effects keep
# their oldest-first/UNTIL_REMOVED behavior. All stored data is JSON primitives.
# Reviewed Court/World zone.inside rows own ally Stealth Advantage and native
# movement/Concentration removal. Court uses rider_menu after each final failed
# save; World declares enter/start triggers sharing native per-turn usage.
# No inferred unconditional difficult ground is granted by Court. Sovereign
# flight is declared native condition data (60-ft Fly Speed/Hover, one minute).
# Seize/Sever target.requires_mark uses the existing compiler admission rule;
# old compiled catalogs keep their own targeting and area/flight declarations.

# stars_impact_terrain creates persistent, evented difficult ground from the
# actual impact aim; Falling Star requires known caster alignment,
# Heaven-Falling Star uses the impact point. Meteor's enlarged variant uses
# ordinary compilation/candidate gates and the caster's known Domain alignment.
# No core or lock seam changed.

# AUTO130 / SOLFAUTO130r2: stars.py implements the reviewed Star-Drawn Projectile
# benefits and Starlight Ward's known-alignment bonus on existing seams. No new
# hook point or core/lock file change. The printed
# "Choose one benefit" is the compiler's own one-action-per-option menu, so the row
# arrives at the new effect "stars_drawn_state" already chosen; it leaves one of three
# standing states (stars_drawn_cover / stars_drawn_range / stars_drawn_push) for the next
# line attack this turn. compile_actions adds a 60-foot-longer variant of the owner's own
# ranged/thrown attacks (typed range, never melee reach), including ordinary variants
# but excluding its own clones. Normal and long ranges each gain 60 feet. The variant
# says it affects the next attack only and costs no extra points. It is admitted by
# requires_condition while that one state stands; the existing
# candidate_allowed revalidates it. attack_sequence_start spends whichever state the
# attack reaches and records it in transient resolution scratch; the attack_mode
# subscriber binds Half Cover and the marked-target push to the creature the attack
# actually strikes -- that hook is the earliest general seam that already carries the
# redirected recipient and runs before the roll and the defence it is measured against,
# so a benefit follows a retargeted attack rather than the originally aimed target.
# It returns None, so the roll and every other subscriber are untouched. attack_roll_finished
# releases Half Cover at the end of the roll and effect_resolution_scope's finally
# releases it again on the way out of the attack block, so an attack negated by an
# attacked reaction, or whose defender moved out of reach or sight before the roll,
# cannot leave cover suppressed for later attacks or other attackers. A later strike's
# attack_mode also drops a cancelled first strike's pending benefit. Release removes
# only this attack's own instance (ext/owned_effects.remove_conditions), so a cover
# exception another caster applied, or one already standing, is preserved. The
# marked-target push runs on after_hit; after_miss and the scope's finally drop it on
# misses, cancellations, pauses and errors. Nested attack scopes shadow and restore
# their parent's record. No pending benefit is saved to the fight.
# later_reach_ft preserves ordinary reach for subsequent strikes; attack_resolved
# restores ordinary normal/long range metadata and effect_resolution_scope restores
# it for subsequent attack effects. Unannotated saved actions remain unchanged.
# compile_actions also composes the two printed range bonuses on Starbolt itself: a
# character owning both Star-Drawn Projectile and Starbolt gets a sibling at +30 +60
# feet, admitted for a marked (Aligned) target beyond the range the ordinary siblings
# already cover. Composition lives in the Stars plug-in because every compile_actions
# subscriber receives the same snapshot of the fighter's own actions and never another
# subscriber's output.
# The fourth printed benefit, the reroll of a
# miss, is not re-implemented: it stays the one shared d20 rewrite in d20_rewrite_attacks.py.
# Starlight Ward uses the documented damage_reduction_bonus query (the seam Ash Ward uses)
# to add the printed Proficiency Bonus when the protected creature is Aligned. Every hook
# is inert without the owning character, the chosen state, or Starlight Ward's own row.
# Meteor Shower's Aligned 20-foot option names its own availability on the button (inside
# your own Stars Domain) instead of the word "Aligned" alone.

# AUTO91 Void: the existing pure flight(engine, actor) hook reads only a newly
# sealed void_sovereign_flight condition carrying void_sovereign_flight=1. It
# returns integer fly_speed_ft equal to current effective walking Speed and
# flight_hover=1; missing/legacy conditions return None. Native condition expiry,
# movement, hover and saves remain engine-owned. Void Field uses explicit native
# enter/start zone triggers sharing the native per-actual-turn allowance; old
# sealed cast-save rows are not rewritten on load. No new hook or core seam.
#
# AUTO133 Void: No-Purchase Body's two standing clauses ride the existing hooks rather
# than a new seam. "Opportunity Attacks against you have Disadvantage" is answered by
# attack_mode(ctx, target), which is already called before each typed attack roll and
# already reports "ADVANTAGE"/"DISADVANTAGE" (see Fragrant Mirage and Shadow's
# Silhouette Veil); the hook returns "DISADVANTAGE" only for an actual Opportunity Attack
# (ctx.typed['opportunity_of'] or an opportunity source) aimed at a creature that both
# compiled the printed row and holds a live Void Shell. "forced movement against you is
# reduced by 10 feet" is answered by forced_movement_reduction(ctx, subject), whose
# nonnegative return is already added before typed push/pull (see Berserker's Unyielding
# and Brute's Sovereign Weight); the hook returns the printed 10 feet only for the same
# owner. Both default to None, so a creature without No-Purchase Body, or whose Shell has
# ended, is untouched, and every ordinary attack and voluntary movement is unaffected.

# Star-Walking Immortal uses the existing immutable compile_action transform:
# native owned_ids plus its exact source hash extend the base self-movement
# row of Starpath Step by 20 feet, including the sovereign free variant.
# Conditional alignment is unchanged. The action seals source provenance;
# unowned/different-source characters and other movement talents are inert.
# One CORE_WITH_RIDERS reviewed record and a source-matched feature row admit
# native ownership and describe only this bonus; remaining printed map clauses
# stay in the generated manual riders. compile_block seals that passive row.
# This range clause introduces no scene/passenger/Star Anchor implementation.
# A2STARS: stars_insights uses existing compile_block/compile_passives to seal
# ownership (Cold Star Heart decorates its one defense row), damage_roll_bonus and
# confirmed_hit_roll_bonus for Comet Adept's actual roll, and damage_dealt for
# its optional marked-target push. resistance_ignored reads pending_damage's
# current/packet_scratch only during a positive Cold packet; preview queries are
# inert and Immunity is preserved. technique_used grants Battle Rhythm's
# END_OF_CURRENT_TURN condition; attack_bonus queries it without mutation,
# attack_roll_finished consumes it only with an actual roll id, and
# after_hit_choice offers the existing rider_step. No new engine seam or lock.
# All persisted counters are integers; markerless saved bundles are inert.
# Comet's turn allowance commits only on positive damage_dealt, including
# Temporary HP absorbed; a wholly negated roll does not spend it.
# Its shared-roll eligibility checks the whole area roster; damage_roll_resolved
# binds the bonus to each actual delivery, including direct save-for-half paths.
# Sealed passive rows may set player_outcome to a plain, complete description;
# the compiler uses it for Insight automation text before generic kind labels.
# Absent/empty leaves historical labels unchanged; all three Stars Insights use it.
# Weather sphere (Sphere of Weather), automation lane AUTO13 r25 -- combat/ext/weather_signs.py, weather_mantle.py, weather_shroud.py:
#   The six printed Weather Sign talents (Wind, Rain, Cold, Heat, Dry, Thunder) have no canonical-catalog record, so their
#   printed Mantle and Shroud rows live in combat/ext/weather_signs.py (one table, read by both Weather modules). Every hook
#   returns early unless the creature owns the row or carries one of its own Sky Mantles / Cloud Shrouds, so a character
#   with no Weather feature and an old saved fight (a sign_supply with no data["sign"]) behave exactly as before.
#   Effect types: weather_sky_mantle (spec refresh/quick/free/lingering/shared_favor; asks the sign and active-or-forced,
#   defers Concentration until consent, stores sign, forced, realm, speed_ft, rule, save_advantage, temp_hp as integers and
#   strings); weather_cloud_shroud (spec persistent/cracking; asks the sign, stores sign, dc, save, fail, success,
#   successes, persistent); weather_thunder_shroud_move (no action, once per round, within 30 feet of the original target).
#   Condition data read back: sign, forced, sign_supply, realm, speed_ft, rule {"damage_resistances", "death_save_mode"},
#   save_advantage, death_save_advantage, escape_advantage, temp_hp, opportunity_disadvantage_ft on a Sky Mantle; sign, dc,
#   save, fail, success, successes, persistent, speed_halved_below_ft, expiry_round, expiry_slot,
#   concentration_started_sequence on a Cloud Shroud. Both are integers and strings (the fail/success rows are
#   ordinary typed effect rows), so a table commit and reload keeps them.
#   Feature blocks: "weather" kinds weatherproof_mantle / weather_backlash / shared_weather_favor / persistent_shroud /
#   pressure_cracking_shroud / lightning_chooses_the_rod / quick_mantle / lingering_mantle
#   (combat/rules/feature_blocks.d/auto13_weather.json). Only weather_shroud.py answers the block, so one talent is one row;
#   weather_signs.rows_of / owns is the shared reader.
#   Hooks: compile_action (give Cloud Shroud its saving throw), compile_actions (any-creature target, Persistent and
#   Pressure-Cracking casts, Move Thunder Shroud, the Shared Weather Favor recipients), compile_resources (one free
#   Quick-Mantle cast a short rest), candidate_allowed, turn_start (the Mantle's and the Shroud's own minute, Heat's
#   temporary Hit Points), turn_end (the repeated Shroud throw), attack_mode (Wind Shroud's ranged Disadvantage on the
#   attacker carrying its marker, and the Mantle's Opportunity-Attack Disadvantage), save (Defensive Weather, each sign's
#   own printed hazards, Rain's and Dry's next-save Disadvantage), damage_defenses (Weatherproof Mantle's Wind, "Resistance
#   to nonmagical ranged weapon damage"), condition_attempt (Dry's poison immunity), escape_mode (Rain's escape checks),
#   event (MOVEMENT_COMMITTED, the feet moved this turn Wind reads), button_description. Each is default-inert.
#   One cast is one sign: the Sky Mantle sign, the point that forces it and its Concentration are settled on the first
#   recipient of a cast, so Shared Weather Favor's extra recipients share one question, one payment and one Concentration
#   ("All targets must receive the same Weather Sign").
#   Weatherproof Mantle is for one sign per purchase ("Choose one Weather Sign talent you know ... choosing a different
#   Weather Sign each time"). The chosen sign is asked once and written on the owner as a modifier on the plug-in's own
#   field "weatherproof_sign" (integers/strings, survives commit and reload; nothing else reads it), so a later cast of a
#   different sign gains nothing from that purchase. Its named Resistances are condition rule data read by the shared
#   damage_defenses path (combat/ext/standard_conditions.py), so suppression and penetration behave as for every other
#   Resistance; the one benefit that is about the attack rather than the damage type (Wind) is answered through the
#   damage_defenses hook itself, and Dry's "necrotic damage from desiccation" is stated for the table because the engine's
#   Resistances cannot tell desiccation from any other necrotic damage.
#   Defensive Weather reads the pending save's sign from the conditions and damage types typed_executor already names for
#   it ("damage:cold", "deafened", ...), through weather_signs.SIGNS_OF, plus the sign a Cloud Shroud throw writes on its
#   own context (typed["weather_sign"]); a sign's own printed save advantage applies only to the hazard it names, through
#   weather_signs.HAZARDS. A save whose sign cannot be read is left alone.
#   A hazard whose printed line is limited to one cause ("by thunder, lightning or storm effects", "against cold weather
#   hazards") additionally requires that cause, read by weather_signs.source_kinds from the effect that caused the save:
#   the save's own source id, plus the action's display name only when the save is that action's own (a named rider's
#   Context.effect_source replaces it, so a parent action's weather name is never borrowed for an unrelated rider), plus
#   the hazard name the engine gave the save and the Weather Sign it names. Cold weather is claimed only from an
#   unambiguous hazard phrase ("cold weather", "blizzard", "ice storm", "cold front", "freezing wind") or a printed
#   Weather Sign effect of the cold category, never from a bare "frost"/"freezing"/"glacial" in an ordinary technique's
#   name. Anything the engine cannot place is left to the table's own rider, which says to establish the cause first.
#   The printed "up to 1 minute" of a Mantle and a Shroud is each swept on turn_start by expiry_round/expiry_slot, and a
#   Concentration-backed one releases exactly the Concentration it took (concentration_started_sequence), leaving any other
#   held state alone. A Shroud row that waits for "the start of your next turn" is anchored on the Shroud owner's own turn
#   clock (weather_signs.owner_start), worked out again at every throw.
#   Pressure-Cracking Shroud uses the engine's own "resistance_suppressed" modifier (typed_reactions.defend), so the target's
#   Resistance returns by itself when the printed duration ends.
#   The Shroud's repeated throw is rolled by this plug-in, not by the engine's repeat_save: a printed Shroud's successful save
#   prevents that round's effect without ending the Shroud. The Persistent Shroud's success counter is recorded with
#   retained_updates.record_instance_update so a replay reproduces it.

# Hunger second pass (A2HUNG): lane9_hunger rows may seal runtime=1 and
# choice_owner=True. A mantle_policy row opts newly compiled Digestive Mantles
# into complete standing-benefit replacement; old bundles without it retain
# their prior behavior. hunger_runtime is an attribution marker: its owned
# passive executes the reviewed mechanic, rather than a second generic action.
# Stored Mantle data adds runtime, secondary, fang_type, marrow_debt and
# additional_impure (Maw checks every additional meal), all
# primitive values. Hundred-Flavour uses effect_durations.token for the owner's
# next-turn end; effect_expiring removes only the recorded secondary benefit.
# Standing check/speed/resistance instances use the same bounded expiry; native
# saves query the active benefits through save/save_mode. Winged Hunger's
# expiry sentinel clears the Mantle flight key before removal/native falling.
# Devour the Venom chooses one qualifying meal type at activation. Its initial
# resistance is native; final_damage asks before HP commit, uses public
# can_use_reaction/open_reaction, pays 1 CP and grants PB temporary HP. It halves
# only packets not already resisted. Choices retain ordinary transactional
# rollback, saved actor ownership and manual/Ask-me enrollment. No
# per-ability core branch, saved schema, policy lock or runtime authority lookup is added.
# Iron Belly Foundation registers a d20_rewrite Rule with the owning sealed
# hunger_iron_belly kind: CON, named Poisoned, failed, 1 CP, once per fight
# (printed once per scene). Standard d20 checkpoints retain mode/modifier,
# require the new result, prompt manual holders and persist the usage receipt.
# Level-selection ability-score increase remains character creation text.
# Hunger's choice_reactors query enrolls only owners of the new Iron Belly row
# for manual/Ask-me choices on another creature's turn; it never spends or asks.
# A2FIRE: activation_resistance_choice is a general typed effect naming damage_types.
# It asks for one known recipient of the accepted activation through Needle, then
# shares its answer in that activation's Context.damage_cache. Public helper
# activation_resistance.bypass_scope(ctx, target_id, damage_types) uses the existing
# effect_resolution_scope and resistance_ignored hooks to scope the bypass to
# the source, attacker, target and named damage type. ContextVar tokens restore
# on nested blocks, errors and player pauses; no pending bypass is serialized.
# Immunity stays native. Missing rows/scopes are inert. Incinerating Lance uses
# the typed choice; White-Hot Focus opens the same scope from its bound state.
# Focus's attack_mode reader spends Advantage on its first actual matching roll,
# using activation-local scratch. All four states retain activation binding,
# turn expiry and technique_used cleanup. No new core seam or lock field.

# Newly reviewed fire_focus_state stores integer backlash on its ordinary state.
# technique_used removes the bound benefit before dealing that unpaid self-damage.
# action_completed settles a countered attempt by its recorded bound_source;
# legacy states without backlash retain their sealed immediate-payment behavior.
# attack_roll_finished spends Advantage only when it receives an actual roll_id.
# A2FIREr1: an empty Focus target answer matches no creature. Attack Advantage
# uses the accepted action's target knowledge (including remembered aims and
# owned sight exceptions); an area's hidden occupants stay out of its picker.
# Both unpaid backlash completion paths construct Context from the owning Focus
# catalog action, so the next talent's Overheat identity cannot change defenses.
# Poison delivery (A2POISON): compile_block seals hit_delivery_policy=1 on new
# owned strike rows. after_hit_choice uses the attack kind and sealed Poison
# source (including the forged_from primary), or the coating condition plus
# shared weapon_identity, to admit the
# printed delivery. Native physical .natural. identities admit natural weapons
# independently; plain unarmed packets require Poison provenance. Unstamped rows retain Deliver-only
# behavior. The existing choice/payments, turn stamp and target-next-turn
# conditions own payment, frequency and expiry; no new engine hook or lock
# payload is introduced. A coating on another weapon grants no eligibility.
# A2METAL: metal_second_pass registers Hard-Meridian Breathing on the existing
# d20_rewrite Rule API. Pending save named consequences gate STR/CON failures;
# the shared transport owns optional consent, 1 CP payment, once-fight state,
# the replacement die, rollback, replay and reload.
# General save_roll_tags(ctx, subject, ability, pending_named) may return a
# list/tuple/set/frozenset of strings already present in pending_named. It runs
# strictly inside typed_save_modifiers, for block saves and defending contests,
# and augments their native d20 consequence metadata without altering rolls or
# outcomes. Invalid/unestablished tags fail the transaction. None/no subscriber
# preserves historical condition-only metadata. Providers own eligibility;
# Hard-Meridian Breathing carries forced_movement only for its newly compiled
# STR/CON owner. Native repeat saves already carry their condition identity.
from . import save_recipient_choices, sword_second_pass  # noqa: F401
# A2VOID: Void's new sealed Shell condition / No-Purchase hit_policy=1 row use
# the existing hit_snapshot and hit_final contract. Snapshots retain eligibility
# and caster numbers before damage ends Concentration; hit_final runs once per
# confirmed hit, including zero damage, never save damage or provisional hits.
# Pressure is optional and has an independent actual-turn allowance. Old packets
# without these opt-ins retain their damage-event behavior. Incarnation's sealed
# void_sovereign_outcomes=1 uses after_miss rather than provisional roll events;
# its two-target Needle is a compile_actions sibling gated by that same saved
# marker, and uses rider_targets' perception, range and player-choice transport.
# No new hook, engine seam, lock file, event schema or runtime patch is needed.
# Incarnation's saved void_sovereign_free_turn receipt uses the current actor's
# turns_started clock, so a repeated initiative slot is a new actual turn. Its
# ordinary costless step and settled-miss step share this allowance; later miss
# steps offer the normal one-point pool choice and never spend a Reaction.
# No-Purchase Pressure explicitly excludes Cost-Denying Needle's Needle-hit-only
# recovery reminder. Its own allowance is independent of the Needle allowance.
# Incarnation reads the sealed form's source action profile; suppressing its
# flight condition alone leaves its other benefits available. compile_actions
# also seals a temporary Empty Step when the actor has not learned that talent,
# using the existing target compiler and effects rather than adding ownership.
# A2DRUNK: reviewed drunken_rhythm_gate rows sit inside native if_marked at:hit
# gates, which snapshot owner-scoped marks before damage/reactions/riders.
# Context.damage_cache retains one new Rhythm selection per victim/strike;
# declines leave that slot available. Legacy rows remain unchanged.
# drunken_missing_beat and drunken_slipping_palm ask only after their save,
# then use native condition expiry, mode removal and movement. Afterimage Sway
# opts in through the drunken_afterimage compiled marker; the next incoming
# roll consumes its owned condition even if range/perception deny the benefit.
# Wrong-Hand Strike seals legal ability scores in compile_action and chooses in
# attack_spec_choice, editing only that strike's prepared specification.
# The general seam adds no core ability branch or saved-fight schema change.
# The shared maneuver provider treats only actual attack effects as existing
# physical templates. Reminder-only rows no longer hide unarmed/natural strikes.
# Wrong-Hand occupies the same new-style attack slot as the reviewed hit gates
# only for an ability not already legal ordinarily. The shared compiler option
# query seals ordinary abilities; each strike gets its own choice and allocation.
# The allocation flag lives only in current_strike scratch, never saved state.

# A2ASH: field_rules.py reads opt-in native continuous zone condition rules:
# terrain_immunity={names:[terrain names], owner:'source'|'any'} excuses only
# those named areas' difficult ground and terrain traversal, preserving other
# overlapping sources and ability damage triggers. healing_minus_source_pb
# reduces received healing by each distinct source owner's PB while inside.
# concentration_disadvantage_if names a required typed condition and contributes
# only to system:combat.concentration saves. suppress_hide_invisibility masks
# only the native Hide result, preserving independent Invisible techniques.
# step_after_enemy_miss_ft offers the defender an optional native no-OA step.
# hide_concealment_allowed(engine, actor) -> True|False|None is a strict pure
# query in stealth.concealment_permission, shared by Hide admission and movement
# reveal. It grants lesser-concealment permission only, never immunity to Search,
# attack reveal, or superior senses. Missing opt-in preserves historical behavior.
# hide_in_light_obscurement consumes this seam only while actually obscured.
# summons.json sources may declare appearance_traits, deep-copied into sealed
# summon records. summon_appeared applies evented fly_speed_ft/flight_hover and
# destroyed_terrain={name,terrain,radius_ft,until_owner_next_start}. Destruction
# at zero HP creates one placed terrain patch at the actual destroyed position;
# dismissal/concentration expiration do not. The condition is consumed, avoiding
# repeated defeat delivery; the patch ends at its owner's next turn start or
# omitted nominal START_OF_TURN slot (expiry only, without turn effects).
# Old summon records have no appearance_traits and gain no new behavior.

# A2AXES second pass: escape_option rows may opt into help_mode="advantage".
# The adjacent helper spends their Action to grant the held creature's next
# selected-hold escape check Advantage, rather than rolling an escape for them.
# The assistance references the exact escape record and guarded instances;
# consumption/expiry and cleanup are evented. skill_proficiency=true reads the
# roller's sealed skill bonus with ordinary ability-modifier fallback. Omitted
# fields preserve historical escape-option behavior and payloads.
# New axes_deep_bite_extend rows set escape_policy=1 to bind this complete
# escape record to the refreshed owner-specific Bite. Old rows are unchanged.
# needle_reposition's optional on_blocked effect list runs only after an
# eligible-size reposition has no legal destination or a selected move fails.
# No list preserves its original path. general_next_opportunity_penalty uses
# attack_mode/native_reaction_roll_mode and nested event to affect and consume
# only an actual Opportunity Attack roll, not an ordinary attack or reaction.
# axes_knee_descent reuses native flight profiles, supported surfaces and
# rider_movement.volume_route without falling damage; it affects only the
# failed-save row of newly reviewed Knee effects. The shared route validates
# every 3-D segment and full landing volume before moving, then uses the public
# needle.step_to seam to retain forced zone enter/leave and following geometry.
# Initial route/landing failure preserves position and logs a manual reminder;
# subsequent zone effects may interrupt travel and are never overwritten.
# Hover and height are gates. Assistance and opportunity penalty labels state
# their benefit and start-of-source-next-turn deadline by creature name.
# No new hook, saved-state schema or saved-fight lock file is introduced.
# Selected-area rows may also bind automatic_side=ALLY|ENEMY and
# automatic_perceived_only=true. The existing recipient picker then builds its
# automatic selectable roster from live relations and DIRECT perception before
# asking; permitted sides are eligibility gates. Manual selections retain the
# printed roster. Absent metadata retains old saved selections. Newly reviewed
# Falling Mountain Judgment rows opt into ENEMY and direct perception.
# needle_reposition rows may opt into size_category_gate=true to compare actual
# native size categories (Small and Medium occupy the same footprint), and a
# plain label for their prompt/log. Missing keys retain historical footprint
# gating and Repositioning Strike text; Bearded Hook opts in to both fields.

# A2BRUTE: creature_passage.grant_named(ctx, target) records one named creature's
# difficult-terrain crossing until END_OF_CURRENT_TURN. Entry consumes it through
# pass_through_entered; exit denies re-entry, including forced/teleport exits.
# Querying paths never spends it; native movement retains walls, occupied-endpoint,
# Speed, cost, contact, OA and recovery checks. Overrun seals named_passage=True;
# historical actions without that field retain their prior behavior.
# rolled_condition_rounds {condition, duration_dice:{count,sides,modifier}} rolls
# one lifetime per activation and applies native conditions to failed recipients,
# using effect_durations.round_token. damage_ability on a damage row opts into
# damage_roll_bonus from the named actual STR/DEX score, otherwise the actor
# summon ability_mods or ctx.numbers ability_mods, before shared-roll/half damage.
# Missing ordinary statistics contribute zero; saving throws and key_mod are
# never used as damage modifiers by this contract.
# Both contracts are default-inert and ability-independent.
from . import rolled_conditions  # noqa: E402,F401
# Newly sealed brute_bowling/perceived_chain rows follow the actual collision
# ray through native occupied volumes, including multi-cell bodies and altitude.
# Only perceived enemies with line of effect receive free Prone-only contests;
# a gap, ally, unseen/blocked creature or failed shove ends the chain. Historical
# unmarked rows retain their previous cap and projected-coordinate behavior.

# A2DESTRUCT uses existing compile_actions/candidate_allowed, typed effect and
# turn_start hooks. Newly sealed Calamity Mantle rows opt in with runtime=1;
# markerless saved actions retain their original aura behavior. Native
# Concentration owns early removal, round_token owns the full-round/minute
# deadline, and retained_updates records the no-action release without a new
# application or refreshed lifetime. Persisted type/dice/save/CP and exact
# concentration sequence freeze each activation. A pulse affects every other
# creature (including allies), with ordinary area LoE and paid-save rules.
# Ruin-Crossing Step's choose_landing row seals grid-length augments and uses
# the existing teleport_destination choice transport/map picker to choose legal
# squares along the line or nearest to its end. Native teleport checks, zone
# entry and Opportunity Attack immunity remain in typed_executor._teleport.
# Shared placement helpers area_cells and needle.cell_id offer opt-in altitude
# layers/IDs. Crossing uses them for nonplanar directions; legacy planar
# callers retain their aim-plane cells and two-coordinate option IDs.
# No new hook, saved schema, or policy/authority lock changes.
# Mantle pulse contexts also carry destruction_frozen_type for the existing
# collision hook; Hammer Through the Line reads the actual locked release type,
# rather than a later sticky choice. This transient key is opt-in and never saved.
# Newly declared Mantle pulses use spatial_areas.actor_in_area for native
# footprint/LoE membership and typed_executor.simultaneous for one area batch,
# so dropping the last enemy cannot skip damage to later allied recipients.

# A2DUALWIEL: readied_pair_roll(ctx, row) is an opt-in typed preparation effect.
# It queries current physical grips and ordinary catalogue dice, asks which pair
# to use if necessary, records one unmodified die per weapon (a Paired item has
# two), and seeds id(damage-row) in Context.damage_cache for tagged
# readied_pair_total rows in this activation only. Native saves reuse that full
# roll for every recipient, then apply ordinary half damage/Evasion/defenses.
# No weapon attack, critical, ability/refinement bonus or on-hit rider is copied.
# Missing preparation/tag metadata preserves the predecessor dice path.
# area.explicit_harmful_recipients = other_creatures | every_creature seals an
# explicit printed creature-wide harm scope into newly reviewed action geometry.
# It precedes the default hostility policy; other_creatures excludes the user,
# every_creature includes them. Generic creatures_in_area geometry alone never
# permits friendly fire: unscoped harm affects enemies only. Compilation seals
# each/every/all-creature wording here; chosen_harmful_recipients preserves the
# full roster for a printed player-selected recipient list. Helpful/opaque
# payloads keep their geometric roster and explicit self costs remain separate.
# No automatic recipient choice is made: these are mandatory printed recipients;
# AI risk previews still use native perceived creature projections.
# harmful_payload_scopes seals permissions per top-level harmful payload (keys
# are SHA-256 hashes of canonical compiled JSON; values are all, other_creatures,
# hostile or allies). Context.area_harmful_scope carries the parent's printed
# permission into save/attack branches and is restored after each sibling row.
# It is resolution-local and never persisted; identical child rows cannot collide.
# Reaction eligibility carries the same resolved parent permission separately
# from raw recipient tokens, retaining original payloads for hash lookups.
# Unrelated sibling effects keep their own scope. Geometry may include everyone
# while individual harmful packets remain hostile-only. Compilation, execution,
# reactions and delayed zones share combat.area_recipients; no hook is added.
# User-origin cones/lines always exclude their user, regardless of printed
# inclusivity; remotely placed shapes and explicit self costs keep their rules.
# rider_choose_area_recipients filters pure harm's choices through the same
# per-payload policy. Its own selector row is bookkeeping, not a friendly benefit;
# mixed helpful/opaque payloads retain all their legal friendly choices.
# dw_asynchronous_exact is a compiled owning passive marker. Existing
# attack_sequence_start/attack_damage/attack_damage_types hooks track attacks
# with the two readied weapons, ask their owner for a normal die and normal type
# while Martial Focus is held, and retain scalar JSON in native turn_flags until
# turn reset. Only normal weapon damage changes; counts, modifiers, enchantment
# packets, mastery, reach and individual weapon identities remain their own.
# No owning row means no tracking, question, replacement or historical change.

# A2DUALWIEL High-Low Combination: dw_highlow_exact opts into the existing
# after_hit_effects(ctx,target,kind) boundary, after that hit's attached effects
# and before the next strike. Scalar turn_flags track actual Lead/Answer weapon
# IDs per hit target; the current readied pair must contain both. One accepted
# choice spends its quoted Focus payment and runs exactly the first save of an
# owned native Shove option, with its Strength DC, reach, size gate and Push/Prone
# outcome. Target-owned target_choice uses existing choice_reactors transport
# for Strength or Dexterity even during an AI source's turn. No Attack-action
# follow-ups or extra economy are borrowed. AI additionally requires an enemy
# currently located by its own senses. No marker means no tracking or question.
# Asynchronous Swing has no printed once-per-turn choice limit: each eligible
# weapon sequence while Focus is held may refresh the selected pair's die/type.
# The scalar JSON flag stores the latest choice per physical weapon; previously
# affected weapons retain their choice to turn end even after swapping grips or
# losing Focus. High-Low admission compares native actual size categories plus
# existing effective_size purpose/role steps before offering a paid Shove, then
# uses native save resolution. Category and footprint are distinct saved facts.

# compile_weapon_traits seals normal_weapon_die_sides (positive integer) on the
# owning pair mechanics' weapon rows from the same ordinary/special weapon
# definitions the compiler used, before Versatile grip resizing. readied_pairs
# reads only the saved weapon metadata at runtime; carried spares, refinement
# bonuses and extra on-hit dice do not change the normal die. Old unannotated
# weapons retain their saved ordinary damage metadata fallback.
# A2FLOWINGR: flowing_second_pass consumes newly sealed river_second_pass
# declarations through compile_actions, action_completed, event, hit_response,
# attack_mode, attack_result, evasion and effect_resolution_scope. Legacy rows have no
# declaration and retain their previous interpreter. Draw Past opts in through
# river_draw_past, selecting a visible adjacent square with a legal physical
# route and native forced-movement reductions. Optional self steps use native
# granted paths and exempt only the triggering creature's Opportunity Attacks.
# Ten Thousand Edges publishes unconditional_miss for the first actual melee hit
# each round after Dodge, then offers movement after the attack settles; it
# never changes the die, AC or Response state. Current Between Steps records a
# chosen reach exit and consumes one target-bound melee attack penalty. Empty
# Bank's new declaration owns consent/payment, uses the shared evasion damage
# pipeline and offers its successful-save movement after its typed block resolves.
# Its ContextVar scope isolates nested saves and also covers generic typed
# reactions and custom blocks calling block_save directly, which do not publish
# technique_used. Unscoped direct calls do not offer/pay incomplete automation.
# Pauses/errors discard only
# transient scope data; table intent replay owns payment and movement commit.
# Selected retaliation instances use condition_events.drop_condition, retaining
# every other defender's mark and the exact removal identity for replay.
# Newly compiled Flowing Response yield effects also seal second_pass=true.
# flowing_river's after_hit/after_miss notifications then remove this attack's
# AC bonus and finish native Response successes; older pending markers do not
# opt in. Reed in Storm's new declaration reads settled typed/native melee
# misses while Dodging and regains Focus only when absent. The choice_costs
# Payment object supplies Empty Bank Evasion's displayed and charged price.
# flowing_river also consumes flowing_second_pass.step for new sealed Response
# movement. Players choose the native physical path before the selected talent
# runs, as printed; old bundles keep their previous automatic step and order.
# Flowing Response's new row also uses before_attack for native melee declarations;
# it applies the same sight/subject, per-round, consent and Reaction gates as the
# typed route. The typed attack_scope prevents double ownership. No opt-in flag
# on the sealed row means no native declaration or completion behavior changes.
# A2SAND: Sand's existing compile_block/compile_action, turn_start, technique_used,
# attack_mode and before_attack hooks seal new Ward/Glass Edge rows and new storm
# profile.sand_designation=1. Frozen rows/profiles without these markers retain
# predecessor behavior. sand_riders.ward_damage_type(engine, owner, target) is a
# public adapter shared with gu_sand: it offers Slashing/Piercing only for the
# owning newly compiled glass_edge row, otherwise returns Slashing. ward_choice
# also seals the printed CL 5 prerequisite for Scouring grain triggers. Glass-grain
# numbers are copied from that row, never a guessed default for direct Ward damage.
# Storm profile.ranged_exempt is a JSON list of explicitly designated actor ids;
# technique_used records it in ZONE_CREATED, and typed/native attacks read it.
# Designation options contain currently perceived creatures only. The creator is
# always exempt; team membership is not an exemption for a newly sealed storm.
# New Ward rows query current relations (hostile only); legacy rows keep their
# original team rule. Storm preferences query current relations; Needle's optional
# automatic_options pool restricts AI designations to perceived current allies,
# including nobody when there are none. Players retain the full perceived menu.
# New storms classify explicit weapon delivery and typed range: null/melee
# profiles stay melee even when the catalog permits a distant target; five-foot
# ranged weapons still qualify. Frozen storms retain their old range heuristic.
# Light obscurement's per-creature choice remains a printed rider (CORE).
# A2SAND Glass-Cutting Palm: sand_glass_palm compile_block seals Insight ownership,
# CL/PB/key modifier. Pure hit_snapshot captures actual-target contact and the
# hit-time Buried damage amount before damage can end Concentration or move a
# creature. hit_final consumes that per-attack JSON receipt and confirms melee
# weapon/unarmed delivery through attack_notifications.is_melee_hit. No callbacks
# or eligibility receipts enter saved state; nested hits retain independent copies.
# sand_terrain.touching_created_glass(engine, creator_id, creature) is a public
# pure footprint query for Glass Terrain from any sphere; source action ownership
# proves creation independently of terrain control. Unrecorded glass-object
# contact remains a printed prerequisite rider (Palm is CORE).
# An optional Needle choice adds flat Piercing damage, once per actual creature turn
# (typed_once_turn prefix), attributed to the Insight with Context.effect_source.
# The existing turn_uses reset and committed damage receipt preserve the allowance
# across session execute_intent, cold reload and replay. Legacy bundles have no row.
# Level-selection Ability Increase stays on the finalized sheet, never applied twice.

# A2SCOUNDRE: rider_choose_area_recipients accepts optional count (positive
# integer or "pb"). The bound is applied before target reactions and saves;
# absent count retains the entire allowed roster. hostile_only filters manual
# and automatic recipients by team, not by preference.
# scoundrel_area_object seals the owning printed area result and uses existing
# rider_menu per-recipient save choices and transfer_object. transfer_object's
# optional landing_range_ft selects every legal visible square in that radius
# with line of effect; object identity binds a distinct placement checkpoint.
# Missing keys retain legacy reach/16-square choice and checkpoint identity.
# Subject movement uses existing subject_repositioning ground paths, reductions,
# and controller-owned destination choices. No new engine hook or lock field.

# transfer_object accepts optional object_location ("carried" or "hand:<part>")
# after a parent has chosen both the object and its destination. The public
# effect rechecks possession and current free/resting hands, without a second
# prompt; an invalid explicit location is inert. Omission keeps the normal
# location choice. Shadow Step uses it for one optional draw/stow after the
# existing teleport_settled hook confirms a real landing in this resolution.
# No landing, no benefits. Its distinct next-Stealth condition uses the normal
# check_mode consumer and CHECK_ROLLED consumption, with end-of-current-turn expiry.
#
# New Steal scoundrel_check rows opt into object_locations=true. Its object
# menu adds reposition; transfer_object asks the owner for a free hand or an
# accessible carried location. The existing evented identity record stores
# object_location plus held_by/hand for ordinary objects. Same-owner weapons
# journal equipment readiness through equipment_hands.set_weapon_readiness;
# they remain possessed and drawable and occupy one weapon grip when drawn.
# Their transfer location describes the relocation; later Draw/Stow readiness
# is authoritative. Lost weapons still use disables_action. Explicit-radius
# landings use object_placement.destinations with the object's one-cell footprint,
# shared cell perception and line of effect, independent of controller size.
# carry.weight preserves the weight of same-owner records only with this marker;
# absent markers keep historical load accounting and object choices unchanged.
# Area selector perceived_only_for_automatic=true restricts its automatic choice
# roster to can_see before counting/picking. Missing flag retains old behavior;
# manual choices retain their printed roster, while hostile_only still applies.

# Shadow second pass (A2SHADOW): newly sealed shadow_ambush_policy version=1
# rows delegate the existing generic Ambush reaction to shadow.py's movement
# event, attack_completed and turn_end hooks. row_allowed prevents duplicate
# generic delivery; legacy unstamped rows keep their former dispatch. One saved
# per-recipient owner turn flag holds the actual turn token across all triggers,
# including a reaction refresh on the owner's turn. Admission uses public
# can_use_reaction, payment precedes open_reaction/spend_reaction, and the sealed
# save/damage/reaction-denial rows execute through the native typed interpreter.
# Owner-controlled choice pauses unwind through the existing hook transport.
# AI harmful responses require an enemy bearing the owner's mark, a perceived
# location, line of effect and 60-foot range. No current authority is read in a saved fight.
# Shadow Mantle's new concentration condition seals shadow_mantle_sight=1 and
# shadow_mantle_opportunity=1; attack_mode applies the latter only to OAs;
# darkness_lifted answers only darkness zones classified as ordinary by the
# shared darkness_scope helper. Supernatural darkness/fog are unchanged. Native
# concentration and duration expiry remove sight together with the other benefits.
# Newly compiled Shadow travel rows seal recipient_policy=1: automatic companion
# invitation options contain perceived allies only. Manual owners may invite
# perceived non-allies for Two Shadows Crossing with a separate willingness
# question; Long Road admits only allies as printed. Legacy
# unstamped travel retains its prior behavior. No new general engine seam.

# Shadow companion arrival() uses destination_allowed with the caster as viewer;
# the caster selects the offered open square and native teleport owns landing
# gates/arrivals. Legacy travel preserves its nearest-square arrival. This does
# not resolve the retained CORE gap of reserving arrival before activation cost.

# New Shadow travel records its already selected CELL/companion landing in the
# public Context.hop_destination / teleport_steps.Destination contract before
# native block_movement. This prevents a second zero-range picker from making
# preview stop while headless commit moves. Native seals, teleport gates and
# movement/zone receipts still own delivery; legacy rows use the old helper.

# Ambush's printed "a creature" permits an explicitly answered manual ally
# trigger. Automatic/AI triggers admit enemies only; an unanswered manual
# checkpoint declines, including during cold replay without an embedded answer.

# New reviewed trap packets seal physical_3d: their dart ray starts at the actual
# trap altitude and intersects solid volumes and creature volumes. Markerless
# saved traps retain their historical planar collision behavior.

# A2VERDANTG: explicit zone-effect profile dictionaries are deep-copied by the
# compiler into sealed zone_spec, then retained by zones.create. Missing profile
# preserves old bundles. clearable_growth consumes profile.clear_square_action=1
# on square/cube areas: an Action for any creature clears one perceived square
# within 5 feet and line of effect. The native affected_cells footprint owns
# terrain and triggers; retained zone updates keep identity, concentration and
# replay. Empty areas end normally. No marker means no added action or choice.
# typed save rows may carry save_categories: a list of nonempty descriptive
# strings. typed_save_modifiers supplies category:<value> to existing save hooks
# only for that particular save; absent metadata leaves historical names intact.
# Newly compiled Medicinal Sprout rows stamp medicinal_categories=1 on their
# short-lived grant. The save hook consumes it for CON saves against Poisoned,
# disease, category:environmental_exposure_exhaustion or
# category:ongoing_poison_damage. It never infers provenance from an action name
# or treats all exhaustion/poison damage as these narrower printed categories.
# Newly compiled Verdant Incarnation fire_stunts_claim=1 rows opt into the
# nested committed-damage consumer. Positive Fire damage while the state is
# active applies one evented short-lived scorched marker; the next owner start
# removes it and skips only Incarnation's free claim. Grove Domain remains an
# independent grant. Zero damage, other types and unmarked historical rows are
# inert. The marker survives cold reload and repeated Fire refreshes it once.
# select_zone_terrain_enemies runs after its zone effect, selects only currently
# seen hostile creatures inside that activation's area, and records
# difficult_target_ids using the retained zone update. Manual owners can choose
# a subset or none; AI options and picks are hostile-only. This changes terrain
# recipients only: start/entry Growth Mark triggers still apply to every enemy.
# save_effects(ctx, subject, ability, fail_effects, success_effects, categories)
# -> {bonus: int, modes: [ADVANTAGE|DISADVANTAGE]} or None. The generic typed
# save reader combines replies with existing save hooks. Subscribers inspect
# this save's direct outcomes and actual recipient; nested saves are separate
# checkpoints. Empty/default metadata and no matching grants are inert.
# Fresh Medicinal Sprout uses direct Poisoned/disease failure rows that select
# the saving creature, or an explicit supported category. The old named-only
# provider and label remain for historical unmarked grants. Native CON repeat
# saves against Poisoned/disease use existing save_mode named metadata and consume
# the same boon once; active_save_pending prevents typed/native double handling.
# Native untagged environmental/recurring-poison provenance remains a lock-round
# producer gap, explicitly retained in Medicinal Sprout's CORE reminder.

# Fresh Forest Remembers perceived_response=1 uses current can_see and
# perceives_cell for LOCAL_AUTO owners: only arrival footprint squares are
# legal AI options when within the printed 60-foot trigger distance. This
# never uses an unseen intermediate path to establish the trigger. Hidden movers
# receive no automatic response. This is a
# conservative strategy for the optional printed response, not a rule restricting
# player choices. Manual owners and unstamped historical rows keep prior choices.

# Wrestling second pass: wrestling_piledriver uses existing maneuvers,
# candidate_allowed, effect and choice_reactors hooks. Its reviewed marker
# opts fresh catalogs into a paid-before-roll ordinary Unarmed Strike, with
# hit-only Prone and a CON save against the Wrestling Strength DC. Stunned
# expires at source-next-turn end. Twin Tie-Up offers at most one additional
# currently held enemy, using live relations and AI perception as admission
# rules. Players may decline. Each attack revalidates the grapple and target
# legality. Old catalogs lacking the reviewed marker retain sealed behavior.
# wrestling_twin uses compile_action to freeze the reviewed Twin Tie-Up marker
# and opt newly compiled Apply-a-Slam rows into pair sharing. The effect asks
# for exactly one second enemy within reach, with sight/line of effect and AI
# perception gates. Existing physical_grapple allocates one part per failed
# save; condition_data carries a primitive activation group. escape_mode
# grants Advantage only while both source-qualified group members are held.
# turn_start records held pairs for Work the Hold; gu_wrestling calls public
# slam_targets only for opted-in rows. It does not share Establish-the-Hold or
# Punish-the-Escape Slams. Releasing either grip leaves the other untouched.
# Twin Tie-Up also compiles a free Release-one-grapple action using the existing
# wrestling_release effect. The all-grapples release remains available. The new
# action's saved source retains the release_grapple suffix so voluntary-release
# consumers (Slip and Strike and grapple cleanup) receive the ordinary event.
# Piledriver copies the strongest ordinary compiled unarmed profile, including
# Iron Fist. Remaining Extra Attacks retain the original on-hit rows and do not
# get Piledriver's free repeated stun/save or another Martial Focus payment.

# Water second pass: ext.water_second_pass uses existing compile_block/resources,
# before_attack, mark_apply and turn_boundary_start hooks. water_second_pass rows
# own Still Surface Method and Tidal Body. The PB free-use resource follows the
# table's per-fight rest convention; optional CP uses spend their quoted pool.
# Still Surface checks actual owned Mist Basin volumes and current special senses;
# automatic protection requires a perceived ally and perceived enemy attacker.
# before_attack context.effect.requires_sight=False or action.parameters.requires_sight=False
# declares a sight-independent attack for visual defensive consumers; absent means
# ordinary sight-based delivery. This opt-in changes no core targeting or senses.
# water_lash_shift asks the caster for a legal optional 5-foot forced route and
# passes the real Context to native movement. Pull of the River replaces that
# whole already-Soaked branch, so the two movements cannot both resolve.
# Tidal Body accepts only self-Soaked placement from an owned Water action. Its
# primitive mark data binds consent to the next real turn start; before expiry,
# turn_boundary_start grants PB Temporary HP once. An ended mark grants nothing.
# Tide-Court Footwork uses compile_actions/compile_action to offer explicit ally
# selection at Court creation and a player-only, free reselection action while a
# Court lasts. water_tide_footwork_select records JSON ally IDs on the actual
# owned Court profile. Both manual and automatic pools exclude self/enemies;
# automatic_options further restricts AI to current perceived allies.
# Native pass_through/pass_through_grant/pass_through_entered_cells supply actual transit
# and forbid occupied endpoints. The Court states one (cost, scope) grant so it cannot
# narrow another ability's grant, and the entered-voxel notice bills each owner only for
# the Court voxels actually entered. The owner round flag limits the automatic hostile
# Soaked application to one actual crossing per round, using the ordinary mark default.
# General native attack-spec seam (transient; never serialized):
# prepare_damage_roll(engine, attacker, confirmed_target, spec) -> None.
# The producer may shape spec["damage"] in place, preserving existing modifiers.
# Called once per confirmed strike after critical resolution, critical-hit choices
# and hit snapshots, immediately before damage dice are drawn. Fixed and absent
# damage bypass it. Typed attacks use it to query damage_roll_bonus from live state
# per packet, rather than capturing removable contributions before the attack d20.
# Native specs without this callback are inert. No ability IDs belong in this seam.

# A2BLACKSMI: blacksmith_second_pass reuses compile_block/actions,
# candidate_allowed, attack_miss_correction, attack_miss_outcome, hit_response, d20_bonus,
# skill_check_mode, mark_spent, event and turn_start/end. No new engine seam.
# Its equipment-family declaration is factual and player-only. AI never
# invents it. AI attack corrections target current enemies via relations;
# defensive corrections protect the smith. No perceived-list recipient pick.
# Incarnation free marks and repeated Temporary HP require its own timed state.
# Tool proficiency is read from sealed skill_proficiency, never inferred totals.

# T13 physical inventory provenance (general, default-inert):
# combat.item_uses.carried_item(engine, original_owner_id, item_key) returns a
# copied identity/current carrier/item descriptor, or None for absent, consumed,
# dropped or unavailable items. inventory() and attack_item() query the same
# records. carry.item_carrier(engine, original_owner, item_key) -> actor id or
# None is a pure shared query for item_key and disables_action relocation forms;
# only the current carrier must be active, not the original storage owner.
# attack_item uses attack_provenance.describe's packet delivery and shared
# weapon_delivery.weapon_identity ancestry. It then maps native borrowed
# requires_held_weapon bindings to the original inventory action without
# changing actor-local catalogue/grip identities. Unarmed packets are ineligible; no
# inventory_key shortcut creates weapon-use provenance or possession.
# skill_check effects may supply tool_item_key and optional tool_owner_id.
# The native skill_check consumer resolves that carried identity for its checked
# creature and scopes used_tool={owner,key} through d20_scope/d20_context.
# d20_bonus subscribers see it only during that actual check; missing metadata
# remains unknown and keeps the original unscoped roll route. No tool name,
# skill label or actor mark creates provenance.
# Blacksmith mark_row/mark_count/set_marks accept optional item_key; empty keys
# preserve the original actor workpiece. Item rows keep the same per-mark clocks,
# smith ownership and expiry consumer. The current-item setting selects existing
# inventory only, does not equip/mark it, and the Hammer mark_apply consumer
# places/spends on this identity. Steady brackets that work once using the native
# granted movement API with exactly its actual carrier in ignore_oa_from.
# Item-key Forge payment/placement accepts an inactive storage owner only while
# carried_item resolves that existing item to a living current bearer. Ordinary
# actor marks keep their active-subject gate; no item is created or transferred.
# Item-key per-mark expiry continues on inactive storage anchors, and the smith's
# any-workpiece query counts their item only while its current carrier is active.
# The existing compile_action transform seals Hammer's selected carrier target;
# candidate_allowed binds it to the current item, retaining original targeting
# without an item selection. Two-Beat's optional item_key keeps its existing
# choices/cap/payment and lock on this same workpiece; empty keys stay unchanged.
# workpiece_locked(smith, storage_subject, item_key='') is the shared pure
# placement/admission query. Selected physical Hammer candidates use the same
# original-owner/item-key lock as execution, rather than the carrier's actor lock.
# spend_item_marks(ctx, smith, original_owner_id, item_key, number, source) -> int
# pays only existing carried item marks and returns the actual count spent.
# Successful payments emit existing mark_spent(ctx, name, subject) with the
# spending smith in ctx.actor and the CURRENT CARRIER in subject. The transient
# ctx.typed['spent_workpiece']={owner,key,carrier,kind} identifies the physical
# item and storage anchor for subscribers; no saved field or new hook is added.
# Missing items/nonpositive payments emit nothing. Empty-key actor payments and
# their existing mark_spent subject semantics remain unchanged.

# Steady Hammer selections are consumed only by an actual scoped CHECK_ROLLED
# receipt. Querying a mode without rolling never spends the short-rest benefit.
# A2GBODSUB1: nine_star constellation_flight reads an owned Constellation row
# and current Marks >=3 through native flight; airborne_constellation vetoes
# Prone only while that conditional benefit is active. Incarnation uses the
# general_flight effect. nine_star_impact_ground records persistent, non-
# Concentration rubble only on impacted supporting surfaces with line of effect.
# sky_treading uses native flight, falling, opportunity_allowed and turn_end.
# Owned Body Crosses Heaven derives Fly Speed from current walking Speed while
# conscious. sky_tread is an optional one-Stamina no-action use during the
# owner's airborne turn, offered by a player button or before a native fall.
# The source-owned condition records its activation turn: flight/Hover only in
# that turn, suspension through the next turn, removal at its end unless renewed.
# Native prohibitions remain authoritative. No new core hook or ability case.
# General temporary resource_capacity effect: an existing pool, positive bonus
# and recognized duration create a source-owned resource_capacity condition.
# Independent sources add their bonuses; the same source refreshes. Expiry
# restores the base capacity and clamps excess current points without refund.
# RESOURCE_CAPACITY_CHANGED carries resource_id, maximum and current integers;
# the general reducer restores both fields. No ability identifier enters core.
# Calamity Briar declares +3 capacity before filling Spines, native Large growth
# and the existing healing_pending seam's temporary six-Spine threshold.
# subpath_pools.match_start performs initiative grants against the fully built
# roster; the initial turn may occur before self.state is assigned. Its existing
# grant flag prevents duplicate grants on later turn starts.
# Flesh Crucible uses flesh_frame_growth for the printed native replacement size
# and Titanic Frame's explicit Large/Huge choice; native dynamic_size owns fit,
# geometry and expiry. compile_actions seals the 40-foot Huge Stomp variant;
# candidate_allowed admits exactly the current-size variant. forced_movement_bonus
# adds five feet only to printed Body pushes during Mountain-Demon Might.
# Forest of Impalement records suspension on its exact native restraint and a
# linked lift receipt; thorn_forest_lift resolves the vertical path through the
# shared forced-movement path executor with its Context, so protections, movement
# reactions, and distance reductions apply. Removal/repeat-save success releases the linked receipt and
# records a safe supporting landing, with no falling damage from its own lift.
# Native ceilings, occupied volumes and spatial restrictions remain in force.
# General physical descent recipient timing: move_to_aim.chosen_after_arrival
# re-derives effect-reachable other creatures from the actual landing space,
# including unseen creatures for manual printed choices. Automatic selectors
# still use perceived enemies only. A selector's after_arrival skips the early
# roster choice and selects immediately after arrival; Markerless descents preserve
# their legacy hostile roster and early selectors preserve their usual timing.
# Resource capacity application/removal uses strict native state_event so expiry,
# suppression and restoration work even inside nested turn callbacks. A retained
# baseline in an _round_ flag survives native turn resets; the final removal
# deletes it. Constellation's Mark state_event settles immediately outside an
# activation and uses resolution_final within one, so replacement flight can be
# established before native falling is settled; Nine-Star Incarnation grants
# its replacement flight before applying the settling condition. forced_movement_bonus is the
# shared additive query for all implementations of printed physical pushes;
# non-typed route effects query it explicitly where they bypass typed_executor.
# Mountain-Demon Might's removal/expiry ends both its linked Frame state and
# Frame's source-owned occupied growth; suppression does not leave a Huge body.

# Flight lifecycle projection: flight.profile(..., excluding_conditions=(iid,))
# omits only the selected recorded capability data without mutating conditions.
# Providers, native flight and effective-speed restrictions still apply. A
# release consumer uses this query to detect independent suspension before its
# removal event triggers native falling. Forest keeps its linked receipt until
# safe landing when it is the final suspension, and preserves altitude otherwise.

# Named rider provenance: a paid on-hit feature uses Context.with_source to name
# its own save/condition/physical rider while retaining the triggering damage
# packet. Body push bonuses query explicit effect_source first, then the typed
# activation source. A plain triggering strike does not erase the paid feature's
# identity. This uses the existing general Context seam, with no core ability case.

# A2GTRA4 consumers use existing contracts only; no ability identifiers enter core.
# Miko's recorded Descent Movement supplies fly_speed_ft/flight_hover on the
# Descent condition, and Seraphic Molter's pure flight provider reads its sealed
# Ascension Anatomy. Native walking/flying payment, collision, Hover and falling
# remain shared. Watchful Guest uses the additive sense_range contract; Revelation
# records gain_sense at the printed fixed range (thin-wall perception remains open).
# Sacred Ground reads explicit creature_kinds and 3D zone_contains. before_attack
# spends the creature's first-attack-per-turn flag only at actual declaration.
# Welcoming Ground uses strict zone_arrival, once per creature/zone/turn, with a
# normal Charisma save. Its recorded condition gates hostile candidates and OAs,
# and -- because a generic *triggered* reaction has its own admission and does not
# pass through candidate_allowed -- the general row_allowed seam as well, so a
# welcomed spirit's bystander counterattack or penalty on the attacker is refused
# too while a reaction that helps anyone stays open. ATTACK_ROLLED removes it even
# when that attack misses, as the printed exception says "unless attacked". The
# ban lasts on the spirit's own turn clock (effect_durations.holder_next_turn, the
# general name for "until the start of the affected creature's next turn"), never
# START_OF_TARGET_NEXT_TURN, which the engine also sweeps at the applier's turn and
# would free a spirit welcomed on its own turn before that turn came round again.
# Neither pure candidate enumeration nor merely starting in the Ground rolls an
# entry save. Source/team gates leave allied spirits free.
# Asset component.resist uses existing object damage resolution. Scythe uses the
# existing if_creature_kind on-hit branch; no kind is inferred from a name.
# Soul Drain records no_cp_regain with target-turn expiry; the native CP gain gate
# applies to every recovery pipeline and records automated denial receipts.
# Lost Trail records the existing no_approach condition on the affected
# creature's own turn clock. The printed rule reads "a creature you designate"
# and imposes no alliance, team or perception limit, so every active creature but
# the affected one is offered to a human player; the automatic chooser only
# *prefers* one of the walker's allies, which is a preference and not an
# eligibility rule. Harmful Hyphal/Bloom recipient menus filter enemy side before
# automatic preference selection via needle.ask automatic_options. Human menus
# retain printed creature choices; automatic choices decline when no enemy qualifies.

# Manifest Messenger supplies existing effect_origins for non-hostile touch/30-ft
# support only, one delivery each owner turn; the core binds the chosen origin.
# A player records the pre-existing willing contact via a choice whose
# automatic_options is empty. AI never manufactures that narrative agreement.

# Kami Descent carries save_against on its own evented condition, so the Ward
# shares the Descent scene lifetime and cannot fall back to a one-turn clock.

# A2ALCHEMY reviewed menu target domain (2026-10-11):
# An action menu option may carry its own `target` object, using the same
# reviewed domain vocabulary as a standalone mechanic (currently
# {"kind": "any_creature"}). The compiler uses that option's domain alongside
# its own effects/area/range; absent target retains the parent's domain and
# normal inference. Native recipients, sight, line of effect and range still
# enforce eligibility. No option grants a visibility exception.
#
# Alchemy immediate poison rechecks and residue (alchemy_field_effects):
# `alchemy_repeat_poison` runs only for the effect's actual beneficiary.
# optional=true permits declining; requires_repeat=true requires a stored
# repeated-save contract. The beneficiary chooses one condition instance;
# its original ability/DC and source actor are retained by native _roll_save.
# `alchemy_corrosive_residue` stores integer PB on an evented condition after
# initial damage, for the effect's printed expiry. A positive DAMAGE_COMMITTED
# receipt (including Temporary HP absorption) consumes the condition before
# native Acid damage delivery. Zero damage does not consume it. Overlapping
# identical residue effects use the strongest coating, without stacking.
# Native save_against bridge (A2ALCHEMY): the existing save_mode hook now reads
# the same evented save_against conditions for native immediate/repeated saves.
# Typed wrappers already consume their next-save packets, so the native reader
# cannot consume them twice. Persistent grants contribute the same mode to the
# native set. Separate mode callbacks preserve cancellation; named/ability
# filters and no_save_advantage remain enforced. No matching grant is inert.
# A typed wrapper that rolls through _roll_save must hand it the whole settled
# mode set in roll_context["save_modes"], not only a collapsed single mode: the
# native reader re-reads whatever is still held, so an opposed save that settled
# Advantage and Disadvantage together would otherwise drop to the one surviving
# persistent grant instead of rolling NORMAL. This is a general engine contract
# (block_save already does it), not a per-ability allowance.
# resistance_profile(..., excluded_feature_ids=()) is a pure optional defense
# query excluding named feature rows, including extension rows; default is
# unchanged. Native resistances/modifiers remain eligible. This lets an Insight
# ask whether another resistance exists without removing its own live row.
# alchemy_stomach decorates only the existing compiled Poison Resistance row:
# final_damage returns a PB reduction only for its owner's own Alchemy Poison
# packet; save_mode grants Advantage against Poisoned only with another ordinary
# effective Poison Resistance. Immunity or next-packet resistance alone is not
# that standing Resistance. Neither query consumes a defense.
# Medicine Saint common-pill administration (alchemy_medicine_saint): new owned
# bundles gain Bonus Action touch administration of their Healing, Antidote and
# Calming Heart Pill actions. Preparation and unsupported medicinal recipes
# remain explicit; Medicinal Smoke is not a pill. Copies retain the original
# recipe costs/numbers/riders; consumer effects target the administered creature.
# Healing adds the owner's key modifier and shares the actual consumer's exact
# Healing Pill benefit cap across sources. The optional CON-save grant belongs
# to that consumer, whose choice may retain it for a later save; it expires at
# the end of that creature's next turn. Automatic administration admits allies
# and self only; human choices retain the printed creature domain.
# Native saving throws enforce no_save_advantage after collecting all mode
# providers and checkpoint contributions, matching typed saves. This generic
# condition rule cannot be bypassed by a native/repeated save or a mode hook.
# A next-save grant is still consumed by that next matching save; Medicine
# Saint's optional grant is not offered when Advantage is forbidden.
# The Medicine Saint question names the save it is actually spending on, through
# the shared choice_prompt.action_context of the roll's own source and actor (a
# nested reaction included), because the extension-choice renderer reads its
# action only from explicit trigger metadata. Poison recheck options likewise
# name the poison and its lifetime rather than printing an ability/DC pair that
# makes two different poisons the same button.

# A2BARRAGE: barrage_second_pass consumes reviewed declarations through the
# existing maneuvers/effect, attack_mode, native_reaction_roll_mode,
# attack_completed and d20_bonus hooks. Suppressing Fire opens its own Bonus
# Action replacement; its target owns Evade/Ignore. Covering Volley offers
# perceived allies excluding self, consumes protection only on a settled first
# Opportunity Attack, and lets that ally choose the optional non-provoking step.
# Mobile Barrage uses native granted_movement.resolve_path(use_movement=True):
# ordinary movement is charged by native traversal, and only actual primary-hit
# creatures are exempt from Opportunity Attacks. Scalar conditions/turn flags
# preserve choices and expiry across table commits and cold replay.
# ammunition.spend_unrolled_projectile(ctx) consumes one ordinary projectile
# belonging to this weapon when the printed result requires no attack roll.
# Callers first validate attack_allowed; untracked stock and Ceaseless retain
# their normal behavior. Physical throws use thrown_equipment.release and
# return_inscription with the confirmed miss. No alternative ammo pool is used.
# Quick-Draw Arsenal's sealed quick declaration offers one atomic weapon swap:
# one carried stowed thrown weapon plus optionally one drawn ranged/thrown
# weapon. Native occupancy validates the resulting hand load; readiness is
# journaled through equipment_hands.set_weapon_readiness and a turn flag limits
# this talent to one use. Loose ammunition/container handling remains CORE text.
# Suppressing Fire's choice_reactors provider exposes perceived in-range
# potential targets to the service's AI probe; a manual target keeps its
# Evade/Ignore choice during an automated archer turn. This advertises decision
# ownership only and never selects an attack recipient.
# Covering Volley's reviewed modifier seals _choice=true, the compiler's
# existing explicit-choice flag: sacrificing the follow-up is a real trade even
# though its protection is beneficial and resource-free. It is never silently
# applied to every primary Barrage attack.

# A2BARRAGEr1: Suppressing Fire seals the complete barrage_common.follow_up
# effects in its resolver row, then copies them for Ignore the Pressure. Only
# attack count and roll mode change; enchantments, passives, mastery hit/miss
# branches and the follow-up weapon damage modifier stay compiled as usual.
# Quick-Draw uses the general ai_free_preparation metadata (zero damage),
# ai_candidate_allowed and needle.ask automatic preferences.
# Its AI query reads only owned equipment/action economy: keep a usable drawn
# ranged/thrown weapon, otherwise prefer a legal pair with the least stowing.
# Manual Ask me transport keeps every legal pair and the ability to decline.
# Covering's prompt and condition label both name the archer's next-turn start.

# General AI free preparation seam: action.parameters.ai_free_preparation=True
# opts a compiled EconomyKind.NONE action into sequencing before paid actions.
# gate4_context copies the marker into AI-only candidate metadata; the built-in
# controller gives it a separate 10000 free_preparation sequencing component.
# It never adds damage/finish value, changes economy, grants legal choices or
# selects a player's action. Providers must bound repetition via ordinary
# candidate_allowed/ai_candidate_allowed (readiness, once-per-turn flags, etc.).
# Unmarked/non-free actions and manual decision contexts retain prior behavior.
# Quick-Draw is one consumer; the seam contains no source/ability-ID cases.

# A2BARRAGEr3: Quick-Draw's AI preservation query uses the shared pure ordinary
# ammunition_choice gate as well as weapon_allowed. Empty tracked stock is not
# a usable readied weapon; only the chooser's own equipment is queried.
# General weapon_actions.unrolled_weapon_misses(ctx, target, attack, count)
# returns actual fired shots after ordinary attack_allowed, projectile spending,
# physical release and return checks on every strike. Partial shots stay spent;
# whole-volley consumers must require the returned count to match their cost.
# Suppressing Fire's Evade consumer requires both shots before applying Speed
# or pressure penalties, and logs only shots actually fired on an incomplete
# volley. The target still owns the choice; manual and AI transport are unchanged.

# A2DAEMON: existing hooks only. bloodless_devouring's a2_packets compiled row
# replaces its typed-only damage_dealt delivery with nested DAMAGE_COMMITTED
# receipts, carrying owned pb/key_mod and choice_owner. The shared turn gate is
# stamped by initiative slot. Old rows remain on their original delivery.
# daemonic_riders' a2_second_furnace row owns turn_start_choice (optional empty
# CP/Stamina Corruption trade) and nested RESOURCE_SPENT (seed-gated once-turn
# Temporary HP). The second pass adds evented capacity while Seed lasts.
# rider_inner_incarnation seals an ordinary timed condition; nested RESOURCE_GAINED
# reads its actual positive gain for one extra Essence per round, setting the flag
# before the child gain; CONDITION_REMOVED settles ending Corruption once.
# attack_magical reads that lifetime condition. Old actions lacking the effect
# never create this ledger. All stored data and turn flags are primitive values.
# A2DAEMON Heaven-Spiting Recovery: fresh a2_heaven_spiting block replaces generic
# compilation. lethal_damage asks for one affordable printed pool; passing is inert.
# A rest-use flag uses the retained _round_ namespace (there is no in-fight rest).
# A primitive pending condition binds source/attacker; nested DAMAGE_COMMITTED
# consumes it before granting Temporary HP, removing Prone and adding Corruption.
# Older saved generic rows still use their compiled effects/cost/limits.
# A2DAEMON: Bloodless reads pending_damage.current's bound HP-before receipt,
# including overkill, and can label packets lacking a catalogue action through
# ability_source.source_label. Its benefits have their own delivery identity.
# Demon Bone's newly compiled a2_cl_gate row enforces CL 10 and enrolls choices;
# legacy sealed rows retain their old level/ownership shape. Rest-only regrowth
# stays in printed text/notes and is never applied during combat.

# A2DAEMONIC general resource contract:
# engine._set_resource_maximum(actor, pool, maximum, source) emits
# RESOURCE_MAXIMUM_CHANGED with previous/maximum/current. It atomically clamps
# the held amount; the reducer restores both fields. resource_capacity effects
# specify resource_id, positive amount and an explicit condition-id anchor on
# the owner. An UNTIL_REMOVED ledger seals the original base and delta. Different
# sources stack; same-source grants do not stack. Condition events recompute the
# maximum and remove ledgers whose anchors ended; lost excess is not restored.
# No capacity is inferred for unknown/unrepresented pools.
# damage_type_override(ctx, kinds, targets) -> str | None runs before the
# single-type early return in choose_damage_type. Exactly one owning provider
# may replace the packet's type without changing its dice, target or defenses.
# None preserves all existing choices; conflicting replies reject the transaction.
# Devil-Qi Circulation owns only its selected, freshly compiled Insight state.
# Its no-action setting requires active Seed; the selected type lasts the scene,
# and the persistent _round_devil_qi_reward flag limits its failed-damaging-save
# Essence reward to once per scene (a combat match is one scene).
# Original packet types remain optional alternatives. Non-damaging saves do
# not award Essence; cached damage receipts check the actual type and failure.
# Seed rider attribution resolves the source action before examining its type.
# rider_targets accepts automatic_side=enemies|allies|allies_and_self. When no
# player owns the choice, eligible recipients are filtered by that side before
# options/defaults are built. Visibility, range, area and condition gates still
# apply. Player choices retain the printed broader eligibility. Unscoped harm
# producers must declare enemies; sides are eligibility, never just preferences.
# Circulation uses technique_start for the initial choice before the next
# eligible Daemonic talent if no setting exists, including AI-controlled owners.

# A2DAEMONICr1 general deferred-damage contract: a typed damage effect may carry
# resolved_damage_type=<nonempty named type> when a prior application already
# finalized its type. _damage_roll uses it for both weapon and ordinary damage,
# bypassing selection/substitution hooks; dice, defenses and receipts are normal.
# Omission preserves ordinary choice. Do not use this field for unresolved menus.
# General condition removal receipt: data.retain_removal_data opts an instance
# into a primitive removed_condition snapshot on CONDITION_REMOVED, emitted by
# engine._remove_condition and condition_events.drop_condition. Event subscribers
# may recompute after removal using its original source/target/data. Opted-in
# UNTIL_REMOVED conditions must use these removal helpers; direct dictionary
# deletion without the receipt is outside this contract. Other events are inert.
# resource_capacity enrolls its ledgers and folds a withdrawn ledger's saved base
# with remaining active grants, including the last removal; clamping is evented.

# A2DREAMS: newly reviewed Symbolic Shelter shape_spec carries an ally-only
# continuous row with rule.dream_nightmare_resistance=1. dreams_core's pure
# damage_defenses consumer reads zones.current_inside_grants and the packet's sealed
# Nightmare-category source, using ordinary Resistance (non-stacking/bypass).
# Dream-Sovereign body is a one-minute typed condition with native fly_speed_ft
# and flight_hover; pass_through grants difficult creature passage only while
# its dream_creature_passage=1 marker remains. Walls, free landings and OAs stay
# native. The separate stance retains Needle and start-turn Seed benefits.
# Start-turn automatic Seeds admit only seen enemies with line of effect;
# manual owners retain the visible printed creature menu.
# New Sleep condition_data.awaken_action=1 publishes one match_start shared
# Action for all creatures through additional_actions. candidate_allowed gates
# another reachable sleeper; AI admission is seen allies only. Removing each
# opted-in sleep instance journals its identity and leaves Prone/other effects
# intact. Markerless sealed matches publish no action. No new core hook.

# Shared d20_rewrite.Rule.before_outcome is an optional presentation contract:
# the original die/total remain visible at consent, but roll_scope withholds DC,
# result and guaranteed outcome. Default False leaves existing rules unchanged.
# Dream Ward opts in and its automatic policy spends on a perceived qualifying
# allied save without consulting its hidden DC/result. Its new Shelter row also
# uses zone_recipient_allowed to exclude the creator: "Allies", unlike Court's
# explicit "You and Allies". No automatic choice admits a hostile beneficiary.

# Dream Ward also requests established damage:psychic/category tags through
# save_roll_tags when a compiled allied Ward owner is within 30 feet. Only
# tags proved by this save's own branches travel to its d20; no name inference.
# Its Rule uses team/range/line-of-effect gates and additional AI perception. Ordinary reaction
# consent, resource affordability, save_bonus and preserved natural die own
# the result, with no per-ability core code or new hook.

# A2GBODSUB3 uses existing native flight/pass_through/stand_cost/stand-cost-offer/
# critical_range contracts for Kensei, Kukishin, Serpent Coils, Shinobi and Gate benefits.
# Hollow Step follows its normalized first-attack procedure: a miss consumes
# both the attack Advantage and the additional damage allowance.
# empty_strike_spiritual_save is a timed one-save penalty. The save/after_save_resolved
# consumers recognize established possession, forced_transformation and soul_affecting
# condition identities or explicit save_categories; ordinary damage and unrelated
# saves do not qualify. Hollow Immortal uses possession, forced_transformation and
# unwilling_teleportation categories only. Marker expiry and consumption use native
# condition events. Physical hold immunity requires the shared source-qualified
# ordinary_physical declaration, not just a Grappled/Restrained name.
# Gate posts supply their printed physical/Force resistance via object_damage_defenses;
# only posts named by a live owner Gate receive it. Shelter's pure standing offer
# quotes five feet for allied recipients, excluding the owner and hostile creatures;
# its owner accepts or declines through the shared stand transaction checkpoint.
# If declined, the acting creature must separately approve the ordinary movement
# fallback through stand_cost_fallback_decision; missing approval leaves it prone.

# Critical-range weapon selectors may use unarmed_or_blade. The Blade branch
# requires a matching compiled #integrated_ weapon variant in the actor catalog,
# preserving the concrete integration selection even on its ordinary attack
# profile and excluding merely carried Blade weapons.
# Empty-World creature emergence observes movement_step_settled after leaving
# a real creature footprint. It adds the existing evented NEXT_ATTACK modifier,
# expiring at END_OF_CURRENT_TURN; a real attack consumes it even on a miss.

# A2GBODSUB4: terrain_repair consumes retained zone profile.repair_tools, an
# explicit list of suitable catalogue item IDs. A currently possessed, nonempty
# inventory item is required; dropping or exhausting it removes the Action.
# The actor chooses one perceived square within five feet and line of effect.
# Removing that exact cell uses retained_updates and ordinary zone membership;
# no repair profile means no new action or change to existing plant clearing.
# next_weapon_attack_penalty is a source-owned, refreshable typed condition.
# Native d20_context.attack_delivery is a read-only descriptor of the actual
# resolving spec, computed by attack_provenance.describe (weapon, unarmed,
# cultivation, unknown; None outside an attack). This general seam avoids
# classifying a mixed action from its catalogue or sanitized spec.
# before_attack queries this descriptor;
# only physical weapon delivery contributes Disadvantage. ATTACK_ROLLED
# consumes it on a real weapon roll (hit or miss), including native attacks.
# Spell/unarmed rolls and canceled attacks leave it intact. Native expiry
# handles the declared deadline. Both modules reuse documented hooks.

# A2GBODSUB4: directional_signals.readings(engine, observer) returns only coarse
# direction and relative Realm, to creatures whose native creature_types match
# the saved signal audience. Encounter actors share the battlefield's plane.
# It grants no can_see, located-cell, identity, range or targeting knowledge;
# unseen Hell-Signaled subjects cannot become legal AI attack targets.
# match_start/additional_actions/candidate_allowed expose a free informational
# action only for an eligible observer when a signal exists. Asura's Rage
# declares signal_audience in its compiled state row and its state_event
# removal listener records Exhaustion, cooldown and signal exactly once per
# instance, including expiry and early removal. Cooling/Cultivation Sessions
# are out-of-combat procedures. The only core addition is the general read-only attack_delivery descriptor.

# A2GMISSUB4: general packet and declaration contracts
# before_attack responses may add disadvantage_penalty (a nonpositive integer)
# alongside mode=DISADVANTAGE. When the attack's pre-checkpoint mode already is
# DISADVANTAGE, core substitutes that flat attack-roll penalty for this response's
# mode contribution. Every response tests the same initial mode; inputs are not
# mutated. Natural rolls, criticals and other contributions keep their contracts.
# Standalone typed damage rows may set bypass_temporary_hp=True. Delivery carries
# that source flag in PendingDamage for the exact packet (including save-for-half),
# with nested packets restoring their enclosing context. Temporary HP remains
# untouched; defenses, reductions, concentration, death and HP floors still run.
# Only the flagged packet's lethal/floor accounting ignores the temporary buffer.
# Context.damage_source_flags is transient and must not be persisted. Absent flags
# and absent disadvantage_penalty introduce no behavioral or event change.

# life_state.failed_death_saves(actor) and erase_failed_death_save(engine, actor,
# source, owner_id) are public restoration helpers. Erasure removes one recorded
# failure with a PASSIVE_TRIGGERED receipt (rule=failed_death_save_erased); it never revives, heals, stabilizes,
# or alters successful saves. Dead/inactive/no-failure creatures return False.
# Echo Scribe's Chronicle records actual failed Death Saving Throw CHECK_ROLLED
# receipts and consumes the corresponding Living Entry for this restoration.

# A2GQISUB1: next_d20_mode is an opt-in, source-owned union of native attack,
# check and save mode rules. Pure mode queries do not consume it; d20_bonus
# consumes its exact condition instance after the qualifying actual d20 draw.
# Source_condition_relief selects exact active non-Secret, nonpermanent condition
# instances by name or represented categories. Source CL comes from end_effect's
# public source_cl helper. Repeated saves use the stored original ability/DC and
# native Advantage; success removes only that selected instance with an event.
# qi_subpaths_1 uses these effects for Heartmend and Nine-Temperature Service.
# Heartbreak admits only targets with this caster's Pulse scene receipt, adds PB
# for this caster's Charmed/Frightened source, and retains native save-for-half.
# Nine-Temperature chooses up to PB recipients, allies/self only for automatic
# owners and current perception/line of effect. Players may offer it to enemies,
# who must accept. Benefits are distinct per activation; exact source-owned scene
# receipts prevent another service from any caster in that combat match.
# No new core hook, core ability branch, runtime patch or resource alias is used.
# Emotional Pulse now seals seven distinct hostile/willing expression rows.
# Sorrow uses d20_bonus for one signed penalty after an actual attack/save draw,
# never a preview query. Rage's before_attack and movement_attempt hooks consult
# only current perceived hostile creatures, allowing the bearer to choose either
# tied nearest creature through its attack/step. Calm vetoes Opportunity Attacks;
# emotional_escalation is stamped from explicit printed Rage/Fury/Berserk/Frenzy
# feature names at compile_action, never from a sphere/style name. Unclassified
# comparable escalation remains disclosed until represented in typed metadata.

# The next-save union includes native death-save modes. Death saving throws
# pass through the existing general rewrite_d20 checkpoint before recording,
# so roll adjustments and next-roll consumption apply to all saving throws. Hostile Pulse asks the target whether
# to accept a failed save, defaults to resisting, and Fear immunity still wins.
# Rage movement compares occupied footprints, including elevation.

# Rage uses teleport_gate for self-owned voluntary teleports as well; foreign
# relocations retain their own forced/willing movement rules.

# A2GQISUB2: native zone trigger_profile.lightly_obscured_viewer_ids is an
# optional list of actor-id strings. Those observers treat this particular
# heavy cloud as Lightly Obscured in zone sight and attack-mode queries. Other
# clouds, walls, Invisible and independent sense restrictions remain effective.
# Missing/empty metadata preserves previous sight. choose_zone_viewers uses
# before_target_reactions to choose perceived recipients before creating smoke,
# narrowing automatic choices to allies, then records the roster by the native
# retained ZONE_CREATED protocol. alchemical_venom_save scopes the existing save
# hook to its own CON save and gives nonbreathers Advantage, without Immunity.

# General directed_forced_movement supports optional_distance_ft=True. The
# forced_movement_distance provider asks its source owner for a zero-to-maximum
# distance in five-foot increments before the direction query. Other rows are
# inert. Native restrictions/reductions and legal movement remain authoritative.

# A2GQISUB4: qi_subpaths_four uses existing compile_action/compile_passives,
# speed/save/falling_damage/forced_movement_reduction/ac hooks and native typed effects.
# Newly reviewed qi_subpaths_scaling rows seal the printed CL11/17 dice counts.
# Wind Walker seals its own CL and marker; its contextual movement reduction reads
# explicit Air/Wind/Weather tags or the Air/Weather sphere, never display names.
# Character of Push uses the public controller-chosen straight displacement;
# Mend keeps an evented recipient-wide per-actual-turn allowance; Shield uses
# native source-clock conditions, refreshing the same caster and reading only
# the strongest overlapping Character of Shield.
# No new hook, core ability case or live-authority read is introduced.

# A2GQISUB5: reviewed qi5_delivery rows opt into hearing/vibration eligibility.
# Deafened/sound_blocked prevents hearing; vibration_blocked prevents vibration.
# Explicit equal sound_medium condition markers model connected media; ordinary
# arena ground (both z=0) also carries vibration after native LoE admission.
# Resonant Note stores its rolled d4 and consumes exact instances only when an
# ATTACK_ROLLED event commits, using attack_bonus for typed rolls and d20_bonus
# for native rolls with the shared resolver-scope guard against double counting.
# qi5_concentration is an ordinary source-timed concentration_mode rule;
# Shattering Note brackets only its damage with the grant and exact removal.
# qi5_melody uses native healing, source-authority removal, an original Charmed
# save with Advantage, and recipient-owned rider_step movement. AI heals allies.
# Requiem uses rider_choose_area_recipients before target reactions; automatic
# choices are perceived enemies while players may choose any eligible creature.
# Song of Fear is a native moving concentration zone with hostile enter/start
# saves once per turn, hearing admission, native end-turn repeats and exact
# cleanup outside the field. Cloud rows use general_flight's native finite clock.
# Feather is a sealed passive consumed by falling_damage and jump_bonus_ft.
# object_damage rows may specify packet_types (case-insensitive damage names).
# Such rows decline packets outside that list; absent lists preserve historical
# behavior. This makes Thunder-only object damage rules independent of abilities.
# qi5_chain condition_state attaches CL cadence, creator DC, preparation marker
# and a no_teleport rule to native Restrained. turn_end rolls exact owned saves;
# condition_attempt/candidate_allowed/teleport_gate block phasing and possession.
# The generic Break Chains Action is legal only while held and uses the ordinary
# resolve_opposed_check against the recorded creator DC, then exact removal.
# No new core engine seam or live authority lookup is required.
# qi5_defensive_form seals excluded damage names and protected condition names
# into an ordinary finite source-owned grant. damage_defenses answers the current
# packet's type, so future damage names obey the printed all-except rule.
# condition_attempt rejects only explicitly listed represented conditions from
# a lower CL source. Demon King's unrelated Chain/Corruption systems remain text.
# Cloud Step's source-qualified native flight grant also supplies attack_mode
# DISADVANTAGE for an Opportunity Attack only; other attacks are unchanged.

# A2GQISUB7 Hearthfire uses existing compile_block/compile_action, effect,
# candidate_allowed, save_effects, choice_reactors, final_damage, turn_start,
# zone_arrival, nominal_slot_boundary and nested event hooks. Only freshly reviewed qi_hearth_asset,
# qi_carry_hearth and the owned qi_hearthfire shield row opt in. An evented
# RuntimeObjectState is the real flame; its identity is sealed on one native
# zone. Destruction/replacement ends that aura. Carry records one carrier ID
# and an integer owner-turn deadline on that same zone. The shared custom expiry
# clock counts omitted source slots without triggering fire or bloom; object identity remains
# intact. Side-aware beneficial save/Temporary-HP recipients are allies, while
# Defensive Flame starts/entries harm enemies only, once per actual table turn.
# Shield the Flame asks the owner, pays real Qi/Reaction after consent, and
# returns additive final_damage reduction after Resistance and before HP loss.
# Declining changes no economy, resource, roll or round allowance. All saved
# data is primitive JSON and native zone/object/condition events own replay.
# Historical unstamped catalogs and other actors are inert. Light, environmental
# discomfort and Pavilion/Domain-Armament carry integration remain printed text.

# A2GQISUB8: furnace_core uses compile_passives/resources/actions, voluntary
# payment_substitution and strict state_event. Its free persisted setting
# quotes a one-for-one Qi/Devil Qi split; native payment owns atomic spending,
# choices, rollback and receipts. Furnace Motion after every positive Devil Qi spend
# uses the ordinary per-table-turn clock and native expiry. Suppression and
# consecrated ward authority remain partial.
# devil_heart_second_furnace.move_armament_choice(ctx, target, distance_ft=15,
# feature_id=..., name=...) is shared optional armament positioning. Augment and
# Core reuse its native saved movement state/events. No new core seam.
# shugenja_prayer uses effect, cover_reduction and turn_boundary_start. The
# saved Patron selects one native attack/save branch. Wood's saved five-foot
# difficult area expires at the caster's next turn start.
# A2GQISUB8 source correction: shugenja_prayer.py uses fight_setup_tasks/fight_setup
# to record the already chosen Patron before turns, and damage_defenses to grant
# its narrow Resistance. Earth/Metal/Water/Wood require an explicit reviewed
# source_tags element; damage type never implies an elemental tag. Prayer emits
# that printed tag on its native packet and presents the allowed damage choices.
# Furnace Core's compile_resources caps the visible Devil Qi pool at PB, starts
# it at zero, and bounds the free payment setting by the same printed maximum.
# A2GQISUB8 Terrain Attunement: shugenja_terrain owns its complete initiative
# trigger through compile_passives(trigger_owner) and fight_setup_tasks/setup.
# Manual confirmation records qualifying, preexisting terrain; automatic
# controllers decline unknown scene provenance. One exclusive benefit uses
# native gain_resource/temp_hp/granted movement or saved armament positioning.
# qi_path.move_armament(..., distance_ft=15) now accepts a keyword grant bound;
# shared callers pass their printed distance. The default and ordinary control
# range, placement, event and saved-position checks remain in that helper.
# A2GQISUB8 general roll metadata: resolve_opposed_check supplies check_kind in
# its existing ephemeral d20_scope before final rewrite/floor hooks. The public
# d20_context reader projects check_kind only when supplied. Values are
# the selected ordinary check spec's kind (check/cultivation/key_ability), default
# check. Providers can distinguish a Cultivation Check from an unrelated skill
# check without parsing source IDs or ability names. No provider is required,
# and no event, saved field or die changes merely because the metadata exists.
# A2GQISUB10: opted-in typed opposed checks also carry their declared hazards in
# the ephemeral d20_scope and d20_context. Hazard providers can consume a one-use
# benefit on the exact rolled check; omitted hazards remain absent and inert.
# d20_context returns a copied hazards list so readers cannot mutate the scope.

# A2GQISUB9: qi_subpaths_dust uses only existing effect/save hooks.
# dust_choking_save seals mode=breathing|corporeal and a native nested save.
# It gates explicit physiology, rolls an owned Dust Cloud's 1d4 penalty once
# per activation recipient, and scopes it to the nested Context. Native damage
# handles CL scaling, defenses and half damage; native source-turn expiry and
# canonical feature modifier refresh handles cross-caster AC loss; native
# expiry handles Poisoned. ANY_CREATURE preserves player targeting, while the
# ai_candidate_allowed hook limits harmful automatic choices to enemies. No core seam,
# persistent schema, action duplication or global save override is added.
# A2GQISUB9: qi_subpaths_mason uses compile_actions to seal
# emergency_repair actions. object_targets and object_action retain native
# range/sight/payment and commit complete OBJECT_UPDATED records. Reinforcement
# stores integer bonuses plus an exact owner condition instance on the object;
# CONDITION_REMOVED restores those additions. save queries current adjacent
# allies only, with no recipient selection from hidden enemy state. Construct
# repair uses the existing native healing path; ordinary creatures are gated.

# A2HUNGERSE: hunger_second_pass extends the existing Mantle owner through public
# begin_courses(ctx), end_courses(engine, actor, mantle) and
# scale_cut(engine, actor, mantle, ordinary_cut). The owner calls them after
# standing benefits, once at actual ending, and after Thick Hide's round gate.
# Newly sealed second_pass=1 Dragon/Demon-King rows suppress inferred standalone
# modifiers and own their two basic benefits. Primitive retained Mantle fields
# bind signs, gifts, source declarations and once-per-Mantle uses. Sky/Resistance
# children use native source-turn expiry and end with their Mantle. Breath uses
# compile_action's sealed sphere provenance and the shared damage_bonus_eligible
# defense preview; an ordinary weapon, unqualified packet or immune recipient
# cannot consume it. The preview follows the same immunity bypass precedence as
# damage delivery, and the player choice remains attached to the actual packet.
# Demon-King pressure uses turn_start_choice, current ENEMY relations, explicit
# lower Realm, physical line of effect and (for automatic owners) current perception. Its next-attack
# penalty queries attack_mode and consumes only an actual ATTACK_ROLLED event.
# Scholar uses the existing check_bonus hook during Taste the Qi's actual
# opposed Hunger Check. Players or a controller with recorded knowledge declare a qualifying target;
# the default automatic policy declines unknown sources and never reads hidden creature types. Character-sheet
# proficiency/ability choices and meal preparation stay outside this combat path.
# The printed unstable-Mantle save has no ability/DC/result definition; Flood
# Swim Speed and Majesty's social check remain explicit Dragon rider gaps.

# A2ILLUSION second pass (existing hooks; no new core dispatch):
# illusion_second_pass.illusion_phantom_prison uses the native condition repeat
# save and escape_option (Investigation Study). An exact prison-instance link
# removes its own Speed 0 and False Premise on any ending. Speed 0 has its
# printed holder-next-turn deadline, separately from the one-minute prison.
# Permanent Illusion is a creation choice: figment setup pays 8 CP and creates
# a placement without a duration/concentration link; permanent glamer variants
# retain their original activation endings and can be dismissed by source and
# recipient. Missing glamer creation rules remain explicit manual text.
# Unreliable Witness registers d20_rewrite.Rule for successful represented
# Perception/Insight/Investigation checks. It repeats with the same mode and
# modifier, then a Wisdom save selects the original or lower check result and
# attaches the owner's next-turn premise. Late floor-created success remains
# unresolved. AI considers only perceived hostile rollers.
# save_bonus_status reuses repeat_save_scope + save_bonus for native repeat
# saves: a ContextVar identifies exactly the engine/holder/source resolution.
# Matching statuses add their existing ability/category-scoped bonus once;
# nested unrelated saves and direct typed saves do not receive this contribution.
# The context resets on success, error or a player pause. No state is persisted.
# Selective Premise and Substantial Phantasm use needle.ask automatic_options
# to restrict AI exemptions to allies (including self) and holds to enemies.
# The mechanical Substantial Phantasm creation is available to AI; ordinary
# narrative figment and minor-image placement retain player_only choices.
# cell_candidate_metadata(engine, actor, action, destination) -> None or exactly
# {expected_damage: nonnegative int, hostiles_in_area: nonnegative int,
#  empty_area: bool}. Strict single-provider, pure estimates for any_cell
# actions whose footprint is supplied by an extension. Absent providers keep
# the legacy empty-placement metadata exactly. This does not change legality,
# recipients, geometry or execution. Providers must use candidate_knowledge.roster
# for an AI query and their action's actual footprint; hidden current positions
# are never an estimate input. Substantial Phantasm uses the public
# figment.creation_cells(engine, owner, destination) footprint preview.

# Custom-effect consequence metadata: pending_effects
# A typed custom effect may carry "pending_effects": a list of ordinary effect
# dictionaries describing consequences that its handler applies on failure.
# Example: {"type": "my_custom_hold", "pending_effects": [
#     {"type": "speed", "applies_to": "target", "becomes": 0},
#     {"type": "condition", "applies_to": "target", "condition": "frightened"}]}
# These are classification previews only: they are never dispatched, executed,
# charged, rolled or persisted as effects by this metadata seam. The custom
# handler remains responsible for applying and ending the actual consequences.
# typed_executor.typed_save_modifiers walks the failure branch recursively via
# on_fail/on_success/on_hit/on_miss/effects. For each row found in that original
# walk, it walks that row's pending_effects via those same branch keys. It does
# not recursively expand pending_effects inside preview rows; use ordinary
# branch nesting there, or put the preview on an original executable row.
# Consumers: condition names feed pending-save reactions, pressure save bonuses
# and Advantage, and the typed save hook's named condition context. Speed rows
# (halved, becomes, or negative amount/flat) add speed_reduced; reaction_denied
# rows add reaction_denied to pending-save reaction classification. Other fields
# retain the ordinary row shape, but this seam does not extend forced-movement
# or damage classification: those consumers still inspect executable branches.
# Metadata must describe the real consequences on the saving creature. Omitted
# or empty pending_effects preserves the existing classification path exactly.

# A2JESTER uses the documented pass_through/pass_through_entered, event,
# row_allowed, after_miss and save_final seams. jester_passage_move scopes
# size-limited enemy passage to an immediate native granted route; queries
# cannot spend Dancing Fool's once-turn crossing. Its recorded entry flag
# lasts through exit but forbids another enemy-space crossing that turn.
# jester_outcomes owns stamped Court-Hermit/Whole Court outcome dispatch,
# suppressing approximate generic copies with row_allowed. Standard consent,
# reaction activation, costs and limits still govern each offer. Whole Court
# reads a real Foil d20 receipt, final save failure margin and settled miss AC;
# saved Flustered packets opt into explicit effect durations/check_penalty.
# Masks uses source-owned delayed choose_effects, hard ally/enemy zone rosters,
# continuous inside save benefits and speed, and each ally's own saved choice
# for a once-round 5-foot Flustered step. Its Help action remains explicit text.

# Native AttackNotice.roll_id now receives the current strike's actual receipt
# for misses as well as hits. Native strike entry clears transient receipts
# before declaration so a later cancelled strike cannot reuse a prior roll.
# Native A Fine Display/Banquet Escape publish REACTION_RESOLVED after their
# effects and scene cleanup, matching generic Punchline completion dispatch.
# Dancing Fool's turn_end consumer closes its Disengage/pass-through grant
# at the end of the current turn, including an off-turn Disengage.
# Whole Court's AI watcher and Masks' AI allies require current perception of
# the triggering enemy/foil via target_knowledge.located; remembered positions
# alone cannot expose a concealed creature's d20 or condition changes.
# Whole Court also reads real SAVE receipts on CHECK_ROLLED (death saves and
# opposed-save sides), without treating bonus dice as d20 Tests.
# Court-Hermit Step accepts settled concealment misses without an attack d20
# and automatic successful harmful saves; Whole Court's d20 predicates do not.

# Karma combat Insights (A2KARMASEC) use source-hashed karma_insights rows and
# existing event/choice/roll hooks. Debt transfer preserves the original Cause;
# scene limits are evented conditions and round/owner-turn limits are integer flags.
# d20_rewrite.Rule.accept(engine, holder, roll_context) optionally obtains another
# participant's consent AFTER the rule holder consents and BEFORE payment/limits.
# It returns bool and may raise ControllerPause; False is inert. No registered
# callback preserves the previous single-participant contract. Rewrite-attached Rule.bonus
# now applies to native attacks as well as checks using d20_bonus, preserving the
# original natural die and critical/miss rules; saves retain native save_bonus.

# General additive Rule seam (A2KARMASECr5): d20_rewrite.Rule(op="bonus") uses
# the existing d20_bonus checkpoint after the exclusive rewrite and ordinary
# numeric bonuses (priority 100). It lazily offers additive rules using
# the usual holder/trigger/cost/limit/AI contract and optional Rule.accept.
# Holder consent then participant consent both precede payment and on_use;
# callbacks may pause and must unwind transactionally. Rule.bonus must return
# int; each yield is recorded before testing the next holder on the updated total.
# The checkpoint preserves natural/mode and events each resulting total.
# No bonus rule is eligible for d20_result; defaults retain one actual rewrite.
# Additive rules do not support unwilling saves, forced outcomes or after riders.
# Rule.after_bonus(engine, holder, original_roll_context, final_roll, signed_bonus)
# optionally settles an accepted additive contribution through d20_finalized,
# after every numeric provider and before the native caller consumes the result.
# The original context is the effective roll immediately before this contribution;
# final_roll is the exact same roll_id after all bonuses. Return None; errors and
# player pauses unwind the native transaction. Nested roll_id queues and causal
# receipts isolate callbacks. Default None creates no pending state. This is
# resolution-local scratch, never persisted objects. Native callers are every
# roller.d20 path using roll_checkpoints (attack, save, check); fixed-DC callers
# may use it for result-dependent riders. Opposed contests still need their
# later settled-result contract and must not infer success from an interim DC.
# foundations3 Feed the Living Circuit is the first additive-rider consumer:
# only the native _concentration_check's explicit SYSTEM_CONCENTRATION source
# (CON save) qualifies. No ordinary attack, damage, skill, or untagged save does.
# Existing prior_event_resources.cost_available and Rule.accept provide payment
# provenance and affected-player consent. Generation/range policy stays unchanged.
# Its after_bonus records primitive owner/subject/source/PB scratch for the exact
# roll_id. The existing nested event hook consumes SAVE_ROLLED.success only after
# native on_save/save_result_outcome settlement; roll_context_end clears abandoned
# scratch. Thus a later declared failure earns no temporary HP. No save wrapper,
# forced success, core ability dispatch or persisted pending object is introduced.
# D20_ROLL_BONUS is a general consent checkpoint label for optional additive
# rules; table text names the roll kind without describing a bonus as a reroll.

# A2 Lightning second pass: lightning_second_pass uses compile_actions to add
# Thousand-Spark Volley's alternate Cultivation Attack from sealed Lash damage,
# and compile_action to cap weapon range at its printed 120 feet. Existing Arc
# filters select visible enemies for both deliveries. lightning_grounding seals
# recorded save proficiency on its passive and asks its owner before consuming
# the once-per-next-turn benefit, using the existing save/choice hooks.
# Meridian's existing save implementation is reused by charged_needle_choice
# and actual melee Conductive Strike resolution; per-hit cache prevents double
# intensification when the same hit also uses Electric Fist. Charged Needle
# snapshots its existing Charge before choosing to place or consume one.
# Wings Burst uses movement_scope + movement_step for voluntary fly paths only;
# its automatic damage subset contains visible enemies. Electric Fist Adept
# uses after_save_resolved with exact Fist attribution, optional shock and native
# granted_movement for its once-per-scene step. Sky-Fire's automatic recipient
# subset contains visible enemies, while humans retain the printed creature menu.
# Charged Needle's sealed choice row includes its own Lightning save numbers;
# weapon maneuver DC never replaces them. effect_player_text describes both
# Charge choices and the CP recovery deadlines in ordinary player language.

# General Shield equipment bonus quotation (A2SHIELD):
# compile_shield_bonus(bonus, info) -> replacement nonnegative integer or None.
# Pure transform, shared by factory compilation and armour.sheet_facts. info
# includes owner_sheet, owned_ids (None for sheet projection), kit and owner_items.
# The compiler uses the same quote for ActorTemplate AC and shield_ac passive
# receipt; armour_class's optional shield_override retains the original default.
# No provider preserves the previous bonus. shield_training supplies explicit
# training permission, never an ability-name branch in core or runtime migration.
# Shield don/doff and returning throws reuse carry's journaled owned location:
# carried grants no Shield Bonus; hand:<part> occupies that exact free hand.
# shield_disc uses the native attack and special_attacks remainder contracts.
# directed_forced_movement may set direction_axis='area_path': the accepted
# directed area's origin/aim supplies two lateral grid headings. Off-axis targets
# may move only farther onto their current side. No aim fails the transaction;
# ordinary direction choices are unchanged. A constrained provider with no legal heading may return (0, 0)
# to explicitly stop movement; None still means use the ordinary printed route. Native movement owns obstructions,
# reductions, defense and events; choices use the caster's observed occupancy.

# Stars second pass: Cold Star Mantle consumes its shared once-per-turn allowance
# through confirmed_hit_roll_bonus for a confirmed native or typed attack's actual resolved
# damage_type, and damage_roll_bonus for standalone/shared damage rolls. Decline
# and miss preserve it. The beneficiary owns the choice; the stored bonus is the
# caster's PB. Its save provider reads actual lost/disoriented/misdirected
# consequences or explicit save_categories (magical_misdirection included).
# Unrelated saves receive no mode. No new engine hook or saved-state seam.
# Native attacks use a transient decision Context only when their attacker is
# mantled. Preliminary attack dice shaping never requests this confirmed-hit
# bonus. Independent reaction child attacks read the public actor/source-scoped
# technique_interception.frame action when no typed attack frame exists; the
# explicit action is also passed to choice_prompt.action_context so transient
# reactions retain their readable name. These contexts are never persisted.
# Aligned Meteor Shower clones synchronize action radius, typed area
# and any zone geometry; other actions retain their existing geometry.

# A2TALISMAN: object_damage direct rows may opt into typed_activation=True.
# Their object delivery then runs technique_accepted (shared activation limits
# remain spent on cancellation), technique_start (a True veto stops delivery),
# the shared typed_executor.activation_reactions checkpoint (an empty creature
# roster still offers technique_used reactions; countering stops all effects),
# selected top-level before_effects (a list of effect types), the attack, existing
# after_effects, and technique_used. Before effects share the delivery Context,
# including activation-local numbers and damage cache. Context.target_display()
# includes the selected object's name for player prompts without treating it as
# a creature recipient. Pending activation metadata is cleared on choice pauses.
# attack_damage_types folds
# over the direct attack's copied damage row before its roll; catalog rows remain
# unchanged. The engine owns Action and explicit costs; start providers own their
# additional consumables. An absent/false flag preserves legacy object deliveries.
# Talismans uses this for Ember's object target with its prepared-talisman cost,
# Elemental crafting choice and Talisman Affinity prelude. No object is a creature
# target, and no creature hit riders or creature-only conditions are synthesized.
# talisman_preparation uses existing compile_resources/prefight_setup_choices/
# match_start hooks to record long-rest choices and optional initiative readying.
# library_available(actor, formula) and library_read_mode(ctx) are public helpers
# for talismans' consumable availability and its printed inscription-check effect.

# Warleader second pass uses movement_step, compile_block, compile_action and the
# existing choice_options transport. warleader_second_pass.standard_set, fulfilled
# and voice_audience are public helpers consumed by warleader (documented there).
# General granted-OA contract: typed_reactions.wants_opportunity_attack(...,
# uses_reaction=False) checks OA prohibitions, action capacity and consent even after
# the Reaction is spent. The owning creature's Ask-me consent stays independent of
# whether the granted attack pays a Reaction; a leader's choice of attacker cannot
# answer for a manually controlled ally. typed_reactions.opportunity_attack(..., uses_reaction=False)
# resolves the native weapon/unarmed OA without publishing REACTION_USED. The
# granting caller owns costs, limits and admission; no Reaction is spent/refunded.
# Optional consent_display carries the grant's name, trigger, target and cost into
# the standard Ask-me prompt; it is presentation metadata, not an answer bypass.

# Free granted attacks ignore Reaction-only prohibitions and reservation priorities;
# unconscious/incapacitated actors and explicit no-Opportunity-Attack effects remain
# ineligible. The default uses_reaction=True retains native Reaction admission.

# A2YANGSECO: yang_recovery extends its existing ownership and mark_spent hooks
# for Overbright Trail and Seal-Breaking Warmth. Trail's observer-specific
# condition expires at the owner's next turn; the visual-only seam above keeps
# solid cover, magical fog and independent invisibility intact. Warmth quotes
# and pays the owner's Path pool, then lets the bearer decline/choose exactly
# one represented ordinary save-imposed suppression. Known stronger sources
# and unknown/excluded provenance remain manual; failure grants the printed
# PB + key Temporary HP. Rising Thread uses attack_damage_type_choice before
# the roll. All choices use existing off-turn transactional transport.


# A2FORCE: created_durability_bonus(ctx, kind) -> nonnegative integer or None.
# Pure creation-time query; typed destructible walls pass kind="barrier";
# bound_objects.place passes explicit creation_kind/kind, otherwise "object".
# durability.creation_bonus validates and adds replies. Actual creation freezes
# the result in the ZONE_CREATED wall object's hp / OBJECT_UPDATED HP. Queries,
# later damage, repairs and cold load never query it. No provider means identical
# bytes. World-Bracing Incarnation answers only from its new sealed, timed
# force_bracing_barriers condition; old Incarnations never acquire the marker.
# force_geometry seals native effect_origins for Impact, Force Wall and the two
# ground lines. Perception is always measured from the caster's actual body;
# effect geometry never relocates it. Markerless actions keep prior origins.
# force_sundering is a paid Impact augment: one additional actual Impact die
# against explicit Construct creatures (confirmed_hit_damage_dice), map objects
# and destructible wall sections (object_action / force_impact_wall). Thresholds,
# defenses and critical rules remain shared. force_shockwave_objects pushes
# explicitly weighed unattended loose map objects with evented OBJECT_UPDATED;
# fixed structures have no legal route, unknown weight is never guessed.
# confirmed_hit_damage_dice(engine, attacker, target, spec, intent, source, critical)
# -> DiceSpec or None. Strict sequential query after final hit/critical prevention,
# before confirmed_hit_roll_bonus and the native damage roll. Replacement dice
# compose through spec['damage']; native critical doubling remains authoritative.
# Resolved recipient/source are explicit. Misses never call it; None/no provider
# retains the original spec without adding fields or changing recorded bytes.
# Sundering Pressure uses it only for a new paid marker against an explicit Construct.

# New sealed Impact uses forced_movement_distance for its optional post-hit push;
# the decision is local to that hit. force.incarnation_push reads the same
# decision through force_second_pass.allows_impact_push, so declining the base
# push also declines its Incarnation extension. Markerless actions retain their
# previous behavior. The choice never changes ordinary movement or targeting.


# Guardian second pass: guardian_second_pass.py uses the existing strict
# turn_boundary_start checkpoint. guardian_adamant stamps its own timed state,
# so old bundles retain their original interpretation. attack_reach_bonus reads
# that live condition for melee attacks; forced_movement_restriction asks its
# holder whether to allow a push/pull. Shelter the Weak admits perceived allies
# other than the owner, bounded by PB, before manual/AI choices. Native grouped
# damage_resistance_next modifiers consume all types on the first positive
# committed packet and expire at the Guardian's next start across cold reload.
# physical_melee_reach now applies the same condition-bound attack_reach_bonus
# query as opportunity_reach after resolving the base weapon profile. It remains
# pure and independent of Reaction availability; no provider retains base reach.


# Weather second pass (A2WEATHER): weather_fields uses existing typed-zone
# profile state. profile.weather_field=1 opts newly cast Gather into primitive
# sign/severity state; old zones without it are inert. fields/signs/severity are
# public plug-in readers. severity uses occupied cells and native in_area (volume
# and LoE), deriving Thunder from Wind and Rain/Dry. Native concentration and expiry
# own zone lifetime. Movement asks for visible points and records retained zone
# snapshots. Weather Cut only sees weather_shroud_roll-stamped contexts, once
# per actual turn. Storm Birth offers visible failed-save targets; automatic
# harm excludes allies. Severe records first_save_done before its roll and its
# optional rider expires at source next start. Dry temp-HP absorption is stopped
# at the native lock; no gain-only denial substitutes for that printed effect.
# Field cancellation is cell-local and shared by creature and aim-point queries.
# Weather Cut reserves its bonus at damage_roll_bonus and commits its per-turn
# allowance only on positive damage_dealt (including absorbed temporary HP).
# Stormlord's Finger uses native CELL candidates, narrowed to maintained storm
# severity >=2, and native area saves at the chosen visible point. Its printed
# 6d10/8d10 bolt targets enemies only and retains a turns_started allowance.
# gather_action clears the inferred zone_spec: weather_gather is the one owner
# of zone placement, so the generic pre-effect zone pass cannot create it twice.
# Field relocation uses senses.perceives_cell plus LoE, including altitude;
# Blinded owners cannot choose terrain they cannot perceive. Rain Mantle's
# gathered-weather fire Resistance is a dynamic damage_defenses query, so
# leaving, moving or ending the actual Rain field removes that benefit.
# Finger's numeric CELL reach is an internal battlefield-wide candidate bound;
# its public description and actual gate are a visible point in a maintained
# storm. No numeric range is added to the printed rule.
# Unscoped matching-weather bonuses read any gathered field (owner=None).
# Own-storm abilities retain owner-scoped queries. Repeated same-sign fields
# use maximum category severity; opposing categories reduce it only in overlap.
# Storm Birth uses a separate typed damage Context attributed to its talent,
# preserving defenses/reactions without inheriting a Shroud's damage-roll bonus.
# New compiled Sky Mantles opt into weather_field_policy for removal of the
# Rain manual reminder; old action bundles retain their original text.
# Sky-Bound Range composes the printed 30/60/120-foot bonus onto newly compiled
# Gather and Cloud Shroud actions by realm. Its reviewed row clears the old
# fixed 30-foot modifier to avoid double application. Old bundles keep reach.
# Sudden Shift asks which maintained field when several copies exist, then
# which sign to replace. Merging into an already gathered compatible sign
# retains the higher category severity and removes the replaced sign.

# A2SOUNDSEC: sound_second_pass uses only existing hooks. Name-Striking Tone's
# technique_declared qualification happens before action/resource payment.
# Perceived voiced techniques record PASSIVE_TRIGGERED observation receipts;
# automatic candidates require such a receipt, while manual users may attest
# their meaningful-name or last-24-hours voice knowledge. The effect chooses
# damage type before its save, then the failed-save penalty. save_mode reads
# caster-scoped pending grants; actual SAVE_ROLLED receipts consume exactly the
# next Sound save, including nested/native repeat saves, and turn hooks clean
# consumed conditions. No save, event schema or controller lock is added.
# Zones opt in through inside.rule.sound_hostile_thunder = check/zero;
# final_damage checks live containment and the damage source's hostility to
# the zone owner. Allied sources retain their damage; recipients gain no blanket
# immunity. The source chooses its eligible check against the sealed zone DC.
# Silent Step's compiled marker watches action_completed and Focus spending;
# resolution_final catches nested event spending. Hearing-tracker attestation
# is an optional opportunity-attack exemption: AI declines it without inventing
# auditory dependence, and a declined/empty choice still allows the step. Native
# granted movement enforces terrain, reachable destinations, selective
# opportunity-attack exemption and an actual-turn allowance; owned Dampen Sound
# doubles the grant. Bell-Bone uses the existing defense reduction/round clock.

from . import ink_second_pass  # noqa: F401
from . import ink_base_actions  # noqa: F401
# Ink Lash uses compile_action + an owned declaration effect, damage_type_override,
# and objects' existing typed_activation/before_effects direct-delivery contract.
# Its player choice precedes creature and object d20s; AI defaults to the first
# printed type without consulting hidden defenses. Other actions remain inert.
# A2INK: mark_duration may also return {kind, amount, minimum?: bool}. kind
# must be a native counted clock unit and amount a positive integer. minimum
# requires the same existing unit and floors its own amount; Concentration
# expiry is preserved. Missing consumers/string marker replies retain prior
# behavior. Master Calligrapher floors hour-based Ink Marks at 8 hours and adds
# 2 to their native chassis cap. Brush-Armed Guard reads actual Shield
# reduction receipts through hit_absorbed/event and uses the shield owner's
# follow_up_scope and compiled numbers. Vermilion Correction uses the existing
# d20_bonus seam before a check's outcome is consumed: native payment/Reaction,
# explicit signed d4, and one recipient receipt per round shared by all writers.
# AI picks add for allies/self and subtract for enemies, from perceived targets.
# A2INK: generic includes_self hit guards consume both self and ally reduction
# rows when the user is the protected recipient. The ordinary subject gates
# already establish this is a self-protection trigger; effects on other roles
# keep their existing handling. No per-ability core branch is introduced.

# A2EARTHSEC: pinpoint_target(engine, viewer, target) -> bool | None is a strict,
# pure additive location query in senses.pinpoints. It grants current location,
# never sight, condition masks or LoE. None/False add nothing; True locates only
# that target. Providers gate geometry, range, ownership and live duration.
# Invalid values fail the query. With no provider native pinpointing is unchanged.
# surface_contact.connected is a pure shared floor/finite-column/roof contact query;
# no x/y projection grants contact to an airborne creature or another platform.
# Earth mark spending uses block_spend_mark (including the existing mark_spent
# hook) for accepted Responses, Blade and Landslide. Adept's native mark_cap +1
# and Earth's secondary cap use the same effective capacity. Its optional step
# excludes only the spent mark's bearer from OA and records one accepted step
# per round. Player pauses unwind through the ordinary session transaction.

# earth_responses exposes response_context, response_available, save_dc and
# spend_mark for sibling Earth response consumers; no sibling-private calls.
# Flying Thing's vertical route is admitted only if native support is within
# 60 feet and no nearer solid surface requires a lateral route. In other cases
# its remaining rider applies and no mark or round allowance is consumed.
# Earth record automation (MMXAUTO-EARTH1): Weight-Seal Strike's printed same surface
# is decided by combat/surface_contact.connected, the shared contact query, and not by a
# height test: two creatures on one raised platform touch one surface, while a creature
# that is not touching a surface touches none. The Ground Keeps Score (after_miss and
# save_final) moves a Burden Mark off a creature that missed an attack or failed a
# Strength or Dexterity saving throw; the owner chooses among the creatures it can see
# within 30 feet that touch the same continuous surface, and the mark keeps its
# remaining duration. Load-Bearing Back (carrying_capacity_scale) doubles the compiled
# carrying capacity, so the encumbrance Speed decision reads the printed scale. Each
# answer is default-inert for a character without the talent.

# Foundations combat conversions (A2GFOU4): foundations4 owns base generation and
# conversions through compile_block, completed attacks, damage_response_reduction,
# event and turn_start. Light-Body Recovery uses posture's shared optional standing
# transition. The existing escape-check resolver now publishes its caller-supplied
# `against` hazards as `named` on the ordinary transient d20 context, allowing
# post-roll consumers to establish the exact resisted hazard. Empty `against`
# carries no scope; consumers must never infer hazards from unrelated conditions.
# This metadata is default-inert without a subscriber, and adds no saved state.
# foundations4_rolls uses it for the base scoped +PB post-roll choices; unexpressed
# narrative/challenge scopes and selected stage improvements remain player text.
# Preserving Moon Breath / Spring Renewal Pulse use foundations4_support on one
# allied selected target. The save subscriber consumes its source-owned condition
# only for a save with an explicit printed hazard in SUPPORT_SCOPES;
# unrelated saves preserve it. Missing descriptors never imply a qualifying fear,
# drain, contamination, or stillness source. Expiry uses the source-next-turn token.

# A2GTREENH continuation: resistance_profile accepts optional source_id and
# source_actor_id, preserving the actual packet's penetration/suppression and
# source-qualified defenses while excluding a querying property's own rows.
# Omitted identities preserve the existing hypothetical profile query.
# Typed condition repeat_save.named inherits explicit save_categories from its
# immediate origin save, including delayed conditions via origin_save. Only
# explicit categories propagate; no effect name or whole-action inference.
# Treasure armor uses native save_mode as well as save for this retained named
# metadata. Iron Rain uses before_attack with the actual attack_delivery query:
# ranged weapon delivery only, >=30 feet, excluding explicit siege_weapon or
# ignore_cover flags on parameters/typed/effect and native total cover removal.
# Both flags describe the resolving packet; range/name never implies a weapon.

# Deflecting Shield Face uses final_damage only for a confirmed attack packet,
# allies/self within 5 feet, one real Path CP plus Reaction, with manual choice
# ownership and perceived recipients for AI. The damage reduction is additive;
# it never changes the attack roll or grants protection to an enemy.

# Glass body and shell contracts (A2GLASS):
# glass_body uses existing compile_action to append glass_body_guard {count: 1|2,
# heavy: bool} only to an owned Temper Glass Surface. The effect asks whether to
# temper the body and stores distinct chosen benefits with that effect's expiry.
# ac and final_damage read the selection; positive settled physical reduction
# consumes the once-per-round receipt. after_hit places hostile melee marks.
# glass_coffin uses compile_actions/candidate_allowed for the caster's touch
# Action and glass_open_coffin to remove only bound_objects' guarded instances.
# Neither extension changes hook signatures, core dispatch or generic defaults.
# A2GQISUB10: reviewed great_mantra_aura is one concentration-linked following
# placement. Chosen recipients are allies; automatic choices also require
# perception. attack_bonus/d20_bonus, save, speed, stand_cost, difficult_exempt
# and damage_defenses read live membership; Precision is a non-stacking boolean.
# dream_ward declarations seal owned passive rows. Native save_mode/d20_bonus
# provide Advantage and an optional evented once-per-scene failed-save rescue.
# lucid_horizon is a source-owned next-start marker, read by masked_conditions.
# Lucid Strike uses native CL dice, five options and ordinary delivery/expiry.

# A2GPAT: golden_core_choices reviewed declarations seal golden_core_choices on
# owned action catalogs. qi_path's technique_used offers one Circulating benefit,
# or two distinct benefits at CL17. Native granted movement owns routes, terrain,
# Speed, hazards and interruptions; move exempts all OAs, shift exempts only the
# selected perceived creature and keeps the destination in the owner's reach.
# move_armament(..., max_distance_ft=15) is the public evented Armament adapter;
# Circulating passes its printed 10/20 feet; other callers keep 15. Selections
# preserve the Armament's mode/control data and revalidate placement and range.
# Guard automatic_options admits perceived allies only; manual choices retain
# the printed one-creature roster. No ally means no automatic guard recipient.
# Repelled Heart uses the native no_approach rule (physical paths and voluntary
# teleports; forced movement exempt). pressure_slot records only its owner's
# package slot; replacement drops exactly that movement bar, leaving unrelated
# no_approach conditions and another owner's Spiritual Pressure intact.

# A2GPAT Body Perfected benefits: forced_movement_restriction reads the actual
# typed push's source CL, the defender's selected/active Golden Bell and the
# optional effect.ignores_bodily_anchoring boolean. Absent exemption is ordinary
# anchoring; equal/higher Source CL and an inactive Bell leave distance unchanged.
# Perfected Blood Furnace offers one source-qualified Bleeding removal only
# after actual HP restoration, never merely Temporary HP. Source CL is sealed
# condition data, the source action's numbers, or the represented source actor's
# numbers; unknown sources are not silently assigned a CL. Mountain-Rending
# readiness now records the source's next-turn-end clock; misses do not consume it.

# Circulating new catalogs read actual accepted-intent Qi-spend receipts (net
# of recorded refunds), not merely the listed price. Their saved use stamp is
# the current creature turn, so another creature's turn has a distinct allowance.
# Armament menus use perceived occupancy; automatic point picks require current
# cell perception. move_armament defaults require_clear_route=False for existing
# consumers; Circulating explicitly asks for a clear route and its 10/20-foot cap.
# Domain Pressure's reviewed area selector stamps automatic_side=ENEMY and
# automatic_perceived_only=True; current relations and direct perception own
# automatic recipients, while manual owners retain the printed creature choice.

# A2GFOU3: foundations3 uses existing reviewed effect, save_roll_tags, save_mode,
# attack_roll_modes, ability_check_mode, nested event,
# attack_completed, save_final and action_completed hooks. Scoped one-roll
# boons carry only explicit consequence tags on source-owned native conditions;
# they consume after the actual qualifying roll even if opposing modes cancel.
# save_roll_tags carries only pending-save-established names into native saves.
# No action-name or affinity-sphere classifier broadens those consequences.
# Normal pressure.generate rows own cap/once-per-round/holder-next-end expiry
# and the existing prior_event_resources provider prevents same-event payment.
# Positive outward HP/temp-HP support is read from committed support events; denied,
# capped and self-only offers do not generate. Spirit Dew also reads native
# typed_reactions._offer_ally_damaged REACTION_RESOLVED receipts: actor_id is
# the paid reactor, source_definition_id its owned generic ally_damaged row,
# payload.protects the supported creature (target_ids names the attacker),
# checkpoint DAMAGE_APPLICATION, and integer pending_before/pending_after the
# settled damage. Only positive direct reduction qualifies; redirection and
# HP-floor substitution remain unrepresented. This nested event subscriber
# returns None and is inert without owned Spirit generation. It reuses the
# same generator, cap, clock and prior-event payment restriction, adds no seam
# or persisted state, and never changes the underlying reaction's reach.
# Remaining scene/protection triggers remain visible riders.
# attack_roll_modes and explicit chosen_attack_modes are general seams;
# no saved schema is added.
# compile_block also seals the Refined Open Channels
# ownership row (foundations3_open_channels): its open_channels_range helper
# widens only the Spirit-Source Dew outward support/generation reach to 60 feet
# with a clear line of effect, never the support action's own range.

# A2GINS2: damage_reduction_bonus is also queried once for an accepted native
# damage_reduction feature block, after its dice and before subtraction. The
# query stays strict/pure: nonnegative integers add, no provider preserves the
# old reduction, and previews or declined reactions never dispatch it.
# insights_second seals Dao Guard Veteran ownership for that query. Debt
# Collector observes fresh_zero_hp (not every damage-at-zero event); Dragon-
# Pearl Release observes actual positive typed-source Lightning/Thunder damage.
# Its fly capability uses the existing END_OF_CURRENT_TURN and native falling.
# Scene use markers use ordinary UNTIL_REMOVED conditions, never turn flags;
# the current fight is one scene. No new saved-field or expiry name is added.
# Cut the Snare uses source-qualified physical_holds, evented escape_checks and
# end_hold so linked hold bookkeeping is removed along with the chosen binding.
# Bindings lacking a recorded physical classification/DC and the 10-minute
# out-of-combat recovery remain explicitly partial.
# Dual Mandate Adept uses the existing imbuement_mandate load sum (+1) and a
# hash-gated compile_action decoration of Layered Mandate's Path-pool cost.
# The composite keeps its ordinary one Action, two distinct options, single
# willing recipient, Concentration and unchanged vessel-choice transport.
# Cut the Snare seals the sheet's actual key ability in its own typed action.
# Its Cultivation Check uses that ability for scoped check modes, retaining the
# usual PB + key modifier; no current sheet is consulted on replay.

# A2GTRA3 extends existing tradition providers. Bite suppression stores bite_source
# and bite_dc on the existing typed_round_suppressed row; its turn_end consumer
# repeats the saved DC and restores only that live expression. Maw's independent
# three-success scene clock remains separate. Root Opening supplies the existing
# pure stand_cost query; native posture owns legality, payment and the transition.
# Heart Restoration reads origin_save before repeat_save and suppresses a failed
# symptom through end_effect's source-start clock. Chain members and Ten Thousand
# Hands strike recipients use native Needle choices: beneficial recipients are
# perceived marked allies, harmful recipients are perceived enemies in the field.
# handspan_draw is an opt-in reviewed effect: forced_destination routes constrain
# each step toward the owner for the printed reduced 10 feet, and for the printed
# full move they enumerate every legal space adjacent to the owner (goals=, no
# travel cap, since the 30 feet above is the action's Range); ask the owner for that
# endpoint and preserve native reductions with the original Context. Two actual size categories grant the printed secondary Strength save; protected
# authority-based anchoring remains a separate unresolved procedure. Collapse arrival
# uses teleport_steps.destinations and typed_executor.teleport_subject, so chosen
# cells retain the normal teleport gates, zones and event ledger.
# Gentle Knife seals mercy_edge=1 on its one-use save_against condition. The
# existing save_effects hook recognizes a direct Spiritual Pressure failure;
# either that save or the named fear-save consumer retires the same instance.
# No per-ability core branches or new engine seam are introduced.

# A2GINS1: insights_defenses uses retained path_passive/insight_defense rows,
# compile_actions, candidate_allowed, ac, event, and damage_reduction. Only a
# positive Stamina Guard packet reduced to zero grants Bell-Skin's reward;
# round flags survive turn resets. Body Like Water resolves selected holds with
# shared escape_options/escape_checks and exact-instance removal. No core seam.
# path_riders native_passive_save_mode extends save_advantage to explicit native
# roll_context.named hazards; it never guesses hazard scope from source names.

# A2GFOU1: foundations1 uses existing compile_block/compile_actions, event and
# strict attack_completed hooks. Only sealed dragon_wind_hit generation rows
# count owner-controlled walked path edges on any turn; forced movement and
# teleport do not count. The accumulator belongs to the owner and resets at the
# owner's next turn boundary.
# The settled attack boundary gains the pool after all same-hit conversions.
# pressure owns max 1, refresh, once-per-round and end-of-next-turn expiration.
# foundations1_conversion no-action catalog choices pay once before effects;
# Momentum Step offers the player walking or existing flying speed. Banked Coals grants one
# PB + key-modifier temporary-HP offer, with one Perfected PB per round.

# General flight capability: optional fly_speed_bonus_ft is a nonnegative integer
# added to an existing positive native/granted Fly Speed before percent/zero
# policies. It never creates flight or preserves a removed flight grant. Missing
# keys retain old profiles. Recorded condition rows use normal expiry; pure
# flight hook replies may supply the same key. foundations1 is its first user.
# Walking Momentum Step is a labelled GM reminder: the existing shared pool
# cannot recover unused base allowance after Dash, paid standing and separate
# grants. No second ordinary-movement counter, global Speed reconciliation or
# new movement replay events are installed. Unrelated movement payments and
# immobilized-turn restoration use main's existing contracts byte for byte.
# The reminder pays the selected conversion once and explicitly states that
# walking Speed/remaining movement need GM resolution. Flying uses only the
# additive capability above; the player still chooses the speed mode.

# A2GINS5: insights_five seals printed numbers and choice ownership only on
# hash-gated new rows. turn_boundary_start performs optional paid Flesh healing
# through the ordinary healing policy and automatic below-half Qi recovery.
# state_event observes actual positive DAMAGE_COMMITTED receipts for Hidden
# Reserves and hostile Lightning recovery; per-session/round flags persist.
# Independent Resistance grants are counted without counting the Insight itself;
# duplicate Bludgeoning reduction is per packet and Lightning reduction per round.
# after_hit_choice owns the paid unarmed hit rider and directed push choices.
# Strict state_event RESOURCE_SPENT grants Music Temporary HP only to hearing
# allies after actual CP payment, even if the talent is later countered.
# Save replacements/rerolls register with d20_rewrite's shared Rule API, never
# a second d20-result provider. No new core hook, lock file or runtime patch.
# General carrying-capacity compilation query (A2GINS5):
# carrying_capacity_scale(info) -> positive integer | None. info carries the
# source/hash-admitted owned_ids, numbers and owner_sheet. Pure providers must
# not mutate these inputs. The compiler multiplies each accepted scale into
# ordinary capacity before the encumbrance Speed decision, recomputes over from
# the existing textual load, and seals only integers/strings. Invalid replies
# fail compilation; absent providers preserve the original capacity and Speed.
# Native item pickup/drop continues to read that sealed capacity. Existing
# saved bundles are not recompiled. insights_five supplies Immortal's Sinews
# and Titan's Grip; independent printed capacity scales compound normally.
# A2GINS5's new Heart Demon action seals harmful=True and an enemy-auto
# recipient policy. Existing candidate_allowed keeps manual ANY_CREATURE legal;
# automatic actors admit current enemies only, through ordinary perception and
# range/line-of-effect gates. Unstamped saved actions retain their policy.
# Titan's carrying scale respects Small -> Medium's unchanged native capacity.
# Purchased-consumable movement uses the public rider_movement.routes/step helpers:
# reachable normal physical paths, immediate player/controller choice, no normal
# movement payment or exit Opportunity Attacks, with hazards/interruption retained.
# Persistent consumable ground uses native zones.create; its source-owned numbers,
# trigger clocks, Difficult Terrain, recipient policy and duration persist unchanged.
# objects.ignite(engine, object_id, source_id, actor_id) is the shared evented ignition
# primitive. Both runtime engines use the same unattended/flammable checks and
# OBJECT_IGNITED snapshot. Ignition alone introduces no damage or destruction.

# Lazy CELL menu seam (combat/placement_menu.py): query() scopes one placeholder
# per ability/variant/origin in service menus. representative(engine, actor,
# action, candidate, intent=None) returns a placeholder after native legality and
# candidate_allowed approve a witness; absent query or explicit cell intent is
# inert. resolve(engine, actor, action, candidate, intent) returns the selected
# native candidate/aim before payment. choice_options and choice_map_pick are
# owned by placement_picker only for choice:placement_menu.square. Humans retain
# every native legal cell and altitude, as do automatic on-demand square choices
# through cells(engine, root). Automatic scoring uses the ordinary evaluator on
# a rotating spread sample plus local refinement, with exhaustive fallback when
# no usable sample exists. Sampling only ranks; it does not seal the choice set.
# Exhaustive cells() uses one native bulk action query with placeholders off,
# preserving the caller's knowledge scope, selected origin and candidate gates.
# Its existing candidate_pass scope shares pure reads within each native action
# frame and ends before rows are offered or any intent executes.
# Only on-demand cells() bounds axes by native range around the current origin
# volume, in that exact actor/action frame. Special any_cell queries and nested
# queries for another actor/action retain full axes. Every altitude and native
# gate remains intact. Both scopes end before choices or execution.
# Second-stage recommendations retain the complete observed AI context, with
# build_decision_context(..., placement_previews=False), then rank only the
# selected placeholder. They never use player/full-roster knowledge or rank all
# other abilities; complete square authority remains separate from preferences.
# exact(engine, root, position) and exact cell intents
# and the separate placement_destination hint regenerate legality, never grant it.
# placement_search_possible(engine, actor, action, root, context) -> False only
# to prove that no native square can pass the current AI scoring filter; None
# by default. Called after a sample miss inside the observed-query scope.
# It skips exhaustive ranking, never an ability, legal square, picker or aim.
# Proofs must be owned by their ability plug-in and use only observed creatures.
# No ability IDs, runtime method replacements, new expiry names or private
# plug-in dependencies are introduced. free_uses merges identical effects while
# retaining independent grant states/flags and alternative state-range gates.
# exhaustive() temporarily disables deferred roots for nested native geometry
# queries (notably Vessel's existing concrete AI gate), preserving knowledge.
# AI root admission postpones ai_candidate_allowed to search's concrete rows.
# annotate retains all roots but stamps placement_ai_unavailable when search
# exhausts admission or receives an owned impossibility proof. The local
# controller neither scores them as useful effects nor treats them as strikes,
# and excludes them only from its automatic selection. Human/model/API square
# and exact-aim authority stays complete. LOCAL_AUTO rejects an unaimed
# second-stage miss before payment instead of defaulting to the first square;
# other seats' journaled answers and all explicit aims retain native authority.
# API_AUTO advertises a second on-demand complete observed placement frame;
# its provider selects placement_destination, validated against native authority.
# Placement labels retain native per-cell ally warnings; map confirmation and
# height selection display these labels before submitting the chosen square.
# Needle.ask(..., space_areas=None) optionally transports option-id -> native
# affected-cell lists as a JSON string captured before pause rollback. Absent
# data is inert; legal ids, AI knowledge and fight state are never changed.
# placement_picker.area_previews(engine, actor, action, rows) uses native area
# geometry at the active origin for only the selected on-demand action; its
# existing choice_map_pick hook returns these as map_pick.areas for hover
# shading, filtered to offered option ids. Each altitude retains its footprint.
# Shared-space seams (MGR-T16-athletics-1-s):
# pass_through_stop(engine, mover, occupant) -> True | None is a pure opt-in
# query allowing a passage-granted endpoint in that occupant's footprint.
# It never removes terrain, hidden contacts or any other occupant's collision;
# movement_attempt still owns transactional entry checks before the step.
# shared_space(engine, left, right) -> True | None validates a live explicit
# sharing relationship, allowing partial/equal-size overlap and mutual collision
# exemption. Without a reply, existing rider/mount validation is unchanged.
# cover_miss_recipient(engine, attacker, target, spec, roll, intent, total, cover)
# -> another active actor id | None runs once only for an original-roll miss
# caused by cover (not natural 1, forced miss or an unrelated AC defense).
# The provider owns recipient eligibility/knowledge/geometry. The resolver
# reuses the d20 and modifier total, recomputes recipient AC/cover, and runs its
# ordinary hit defenses and damage; it never recursively redirects that roll.
# Typed aftermath hooks (attack_result, after_hit/after_miss, choices,
# attack_resolved and completion) receive that resolved recipient in both
# their target argument and Context.target/targets. Roll events retain the
# original declaration; subsequent sequence strikes retain their declared aim.
# No subscriber changes movement, occupancy or attacks. Close Quarters uses
# these seams plus movement_attempt, directional_cover and attack scopes.
# Its relationship is stored as strings/integers and ends on separation;
# current geometry is always rechecked, including during reload.
# Scene catch difficulties (MGR-T16-athletics-1-s): map/battlefield catch_dc
# is an optional nonnegative integer, persisted to SquareGrid.catch_dc.
# Roof settings/regions may override catch_dc for a named physical face;
# RoofSurface.catch_dc retains that value. Omitted difficulty is inert: no
# consumer invents a DC. Adjacent solid terrain without a roof can use the
# scene DC. Sure Grip uses falling, can_use_reaction, open_reaction, ordinary
# hazard-tagged checks and support_surface. Primitive catch anchor/position
# data supplies support only at the recorded position while the anchor is
# capable, reachable and natively supported. A self-catch also requires the
# recorded solid face to remain present. A transient recursion guard rejects
# cyclic catch chains and is never exported as fight state.
# free_uses' existing technique_used hook asks choice:free_uses.funding through
# the journaled choice_options transport when multiple grants are available.
# The choice spends exactly one active grant; automatic preference spends the
# least flexible grant first. No free_use declaration means all hooks are inert.
# Shared Circuit Memory (foundations3): consumes native Guard REACTION_RESOLVED
# after payment through event(nested=True), using current PendingDamage source
# and the originating event's sequence. No positive reduction/owned row = inert.
# Public shared_circuit_protection_succeeded(engine, receipt) -> None consumes a
# primitive settled receipt: protection_id (Guard/Feed), beneficial=1, eligible=1,
# owner_id, protected_id, source_actor_id, trigger_source_id, receipt_id (strings).
# Feed's separate rescue producer must establish eligible failed -> successful
# settlement before calling; this helper never produces or rewrites that result.
# Missing native source/actor facts return without inferring a source.
# Catalog membership is not required: exact native attacker/source/target
# provenance supplies Opportunity Attack's public name. Other settled sources
# use "triggering effect" when display metadata is absent; identity stays intact.
# The actual protected ally chooses through Needle; choice_reactors enrolls
# eligible allied players on AI turns. Native granted_movement.candidates and
# _resolve_movement(granted_ft=5, ignore_oa_from=(source,)) keep all legal moves,
# other hostile OAs and ordinary movement. PASSIVE_TRIGGERED choice receipts
# deduplicate committed delivery and persist strings only. Advantage conditions
# use native owner next-start expiry; save_mode/SAVE_ROLLED and native typed
# contest_check_mode/opposed_check_resolved apply/consume only same-source saves
# and explicitly typed Cultivation Checks. Unidentified ordinary checks are inert.

# Reviewed conditional zone clocks (ZONETICK1): zone_tick_producers uses the
# existing zone_created, zone_recipient_allowed, movement_step, forced_movement_step
# and state_event hooks. Its reviewed profile flags select a recorded Patron/formula
# payload, require a real grappler/creature kind, or dispatch grappler_start, cp_spent,
# fire_damage and center_approach through zones.fire_trigger. The center_approach
# producer subscribes to both step hooks: voluntary and forced steps move the printed
# center the same way, and the two hook points never double-fire one step.
# Construction never fires them.
# Movement receipts are integer zone usage data recorded via retained_updates;
# unflagged areas and characters are inert. No engine method is replaced.
# A reviewed zone effect may set terrain to an explicit list of terrain.json
# names (including []); omitted retains legacy text inference. This separates
# terrain actually created from terrain mentioned only as an exemption.
#
# Explicit reactions may call typed_reactions.reaction_activation(engine,
# reactor, subject, row, range_subject=subject): native declaration, cancellation
# and range transaction. pay_reaction_costs(engine, actor, row) -> bool settles
# substitutions, once limits and completion/refund hooks after admission.
# triggered_context accepts reaction_attack/target_kind row overrides; omitted
# values keep ordinary reaction attacks. Helpers have no effects until called.
# forced_destination.routes(..., vertical=True) admits every finite 3D forced
# route; default False preserves horizontal callers, infinite searches reject.
# Authored route_regions survive native map normalization/grid loading;
# route_environment.permits is an opt-in edge query, inert for ordinary movement.
#
# Committed teleport distance: committed_teleport_receipt(engine, receipt) -> None
# is a strict transactional notification after native placement, arrival zones
# and teleport_settled. combat.movement_receipts.teleport_committed publishes a
# flat int/string dict: receipt_id (match + movement event sequence), intent_id,
# source_definition_id/source_feature_id, actor_id/source_actor_id, previous and
# destination x/y/z, distance_ft, round_number/turn_slot/turn_actor_id, own_turn,
# self_teleport, movement_context and willing (0/1). Original landing anchors
# remain evidence even if an arrival reaction subsequently moves the creature.
# Derived hops can pass settlement_source_id/settlement_feature_id to the public
# teleport_subject API: these override only receipt provenance, retain the
# triggering intent and default to the context source/action feature when absent.
# The derived hop's context actor identifies its source actor; no core ability
# dispatch is involved. Anchored Soul supplies its own identity for a return.
# Failed/refused/same-square attempts never reach it; native duplicate child
# suppression remains in teleport_steps. No subscriber means no persisted change.
# motion_status persists PASSIVE_TRIGGERED with receipt_kind=motion_distance_receipt
# only for a compiled Athletics
# Afterimage owner making a willing self teleport. It creates no condition and
# changes no threshold/turn admission. Progress consumers may use this public
# hook or event, deduplicating by receipt_id and checking own_turn; off-turn
# receipts describe actual motion but never authorize own-turn progress.
# The persisted receipt includes a plain distance log for history presentation;
# this describes the teleport only, never creation of an Afterimage.

# Native source-expression contracts (SEAMFIX Palm): source_records.acquire
# records an owner-authored classification alongside an acquired source feature.
# compile_bundle seals only owned source/condition bindings. source_records.live
# returns exact currently active condition instances, with explicit scope,
# ordinary status, Source CL and owner/known_to visibility; names and sphere
# membership never imply classifications. apply_expression(ctx, holder,
# condition_id, category, ordinary, source=None, expires_on, data) is the shared
# native producer used by Mudang Guest Seat. The source_expression typed effect
# exposes it to other source-authored conditions. Suppressing its condition
# disables that condition's original native consumers, not an entire Path/body.
# Without a source record and its active native condition this seam is inert. Owner classifications
# override the built-in source/condition binding; unknown facts stay unknown.
# source_records.cultivation_check(ctx, condition, label) records a native check
# against the identified source actor's Cultivation Save DC; missing sources
# cannot silently lose their expression. contact_allowed respects explicitly
# scoped contact denials, independently of physical line of effect.
# declare_damage_type is a typed effect placed before a saving throw. It asks
# the action's owner through the transactional checkpoint, caches one legal type
# only in that activation's Context.damage_cache, and shares it across full and
# half damage through damage_type_override. Automatic actors use their first
# legal type without inspecting target defenses; no declaration is inert.
# forced_destination.directional_routes(engine, mover, origin, feet, away=False,
# nearest=False, stay=False) returns every legal body-aware destination/path;
# nearest preserves ties and stay adds the zero-distance choice for 'up to'.
# identity.effective_cultivation_level is optional owner admission data. The
# compiler validates 1 <= effective <= acquired and seals effective Source CL;
# absent data preserves existing compilation. source_acquisition.acquire_feature
# records actor-bound/source-hashed combat_acquisitions with explicit access
# facts. SourceAcquisitionStore persists those receipts under the supplied user
# data root; compilation validates them and seals their provenance in the fight.
# The Foundry's sealed display-only earned_feature_occurrences is untouched.
# scene_end(engine) -> None is a strict transactional notification before the
# final MATCH_ENDED event. With no provider the hook is inert. source_records removes only
# conditions with explicit data.ends_with_scene=1, so scene-bound relationships
# and source-authored scene expressions can share the lifecycle. It never
# changes unrelated UNTIL_REMOVED conditions or emits post-terminal events.
# source_protection is an opt-in typed producer of a named source condition
# with explicit category, ordinary status and forced_movement/spiritual_contact
# scope. Its original condition_data.rule retains its printed numerical effect;
# no classification is inferred. effective_source_cl=true uses the existing
# effect_resolution_scope to bind current effective CL only during resolution.
# relationship_status recomputes explicitly spiritual relationships' current
# source availability, scoped contact denial and physical line of effect.
# object_subjects validates map spiritual_profile (explicit external Anchor or
# Cultivation Asset, affectable, internal exclusion, known_to, assigned saves).
# Native SPIRIT_ASSET creation is another eligible producer. Its persisted
# source_relationships use OBJECT_UPDATED and source start/end/scene clocks,
# including nominal slots. Objects with no assigned scores fail saves per the
# 5.5e default; ordinary objects are not thereby admitted to spiritual targeting.
# object_source_expression is an opt-in object action producer of exact named
# permissions; requires_object_expression metadata gates the original source's
# native action against object_id/expression_id/source_actor_id. Suppression
# disables only that recorded instance, and restoration never recreates it if
# its source/lifetime ended. Independent expressions remain selectable.
# Packets containing object_source_expression admit native object targets only;
# source_protection packets alone retain their existing creature consumer too.
# typed_executor.damage_roll(ctx, effect) is the public scaled/cached roll seam
# for alternate native recipients; the caller owns their defenses/commit.
# native_actor_footprint derives native and portable default volumes from
# admitted size; explicit footprints retain precedence. Unobserved occupancy
# supports native object ids; observed occupancy still requires a creature.
# zones.query_grid(excluded_zone_ids=...) returns an independent derived grid
# retaining map terrain and every other wall. forced_destination's optional
# grid argument permits source-qualified collision queries without live masks.
# Source expression producers may declare an exclusive_group. A replacement
# retires both active and suppressed prior copies in that source actor's group,
# preventing an expired suppression from restoring an obsolete second slot.
# A source-authored condition with data.persists_while_inactive=1 may restore
# after nonlethal defeat if its original lifetime still exists; defaults retain
# the prior inactive-holder behavior. Scene cleanup also retires suppressed
# snapshots whose original source condition has ends_with_scene=1.
# Object source_protection rows share actor classification/authority validation
# and support explicit source-start/source-end/scene clocks. Derived object
# geometry exposes those exact live source records to the shared consumers;
# relationship status refreshes on native movement and source-condition edits.
# That derived geometry uses objects.rectangular_footprint: an object's sealed
# width_cells/length_cells/rotation, when present, is the same body route and
# destination validation uses, so a pull/push cannot squeeze a rectangle
# through an undersized gap or leave its far edge off the battlefield.
# Fate Insights use existing preparation, fight_setup, save/check and d20_rewrite
# hooks. Preparation imports unspent earlier-session facts, never performs a rite.
# Companion/Talisman optionally seal a beneficiary number before match creation:
# 1 is the owner; 2 onward are other roster actors sorted by display name (stable
# roster order breaks ties). Human seats can instead declare through fight setup;
# automatic seats require the sealed fact and never guess a prior beneficiary.
# Receipts retain spent state through replay/reload. Cross-fight/session/scene
# lifecycle, recognition cause production and ordinary ambush prevention remain
# manual riders; all five parent entries remain partial.

# Lotus-Root Recovery extends the existing foundations3_boon provider.
# compile_action seals its side-neutral creature domain; technique_declared asks
# the supporter's recovery purpose and the actual recipient's willingness inside
# the native accepted-intent transaction before economy/resource payment. These
# subjective choices never establish clinical facts or generate Dew. Refusal or
# corruption-preserving intent cancels without payment. choice_reactors preserves
# recipient-owned manual/Ask consent on automatic turns. All three hooks are
# inert without the exact owned source's compiled action; native targeting,
# ordinary temp HP, save scope/consumption and grantor clock remain authoritative.
# Source-backed contraindications: combat.recovery_admission.exclusion(engine,
# subject) reads actual native conditions with a literal authored
# condition_data.recovery_support_exclusion='preserves_corruption', revalidating
# that declaration against the originating owned action/effect. Lotus-Root calls
# it before payment. Mere contamination, names, teams and absent data establish
# no clinical fact. Native condition production, clocks and replay are reused;
# no new persistent fact schema or GM-completion flag is introduced.

# Lotus-Root target_eligibility also calls the same public source contraindication
# query, so automatic menus never repeatedly offer an explicitly forbidden
# recipient. technique_declared retains the pre-payment recheck. Missing source
# classification is still unclassified, not an inferred healthy/corrupt fact.


# Flowing Step's owned water_return implementation uses existing compile_block,
# compile_action, candidate_allowed, opportunity_allowed, turn_boundary_start,
# stand_cost_offer/decision and STOOD_UP event contracts. Its passive row is
# required for every benefit; other actors and markerless saved catalogs remain
# inert. water_return reads granted_movement.routes(engine, actor, 10), whose
# cell -> (path, cost_ft, mode) query enforces native voluntary terrain/footprint/
# movement restrictions. It passes Route(path, mode) to movement_paths.resolve
# with kind='granted', feet=10 and provokes=True, spending only that explicit
# grant. opportunity_allowed checks the public movement_scope(actor_id) query
# {actor_id, source_id, mode, granted}, so only this grant exempts Soaked or
# owner-Current/Basin reactors, evaluated at the actual OA edge. The selected
# Water effect is retained. Turn-start permission is latched from sealed map
# terrain / native owned Basins with the actor's actual turns_started integer;
# native posture owns standing legality and STOOD_UP consumes the one free use.
# Its environmental reader also consumes weather_fields.severity(engine, None,
# actor, 'rain') -> nonnegative integer, the same public occupied-volume/LoE and
# opposing-sign query used by Weather Shroud and Rain Mantle. Any creator's
# actual Rain field qualifies; missing/inactive weather returns 0. This query is
# read-only and creates no weather, clock or environmental flag.
# Explicit authored rain/mist/wet-ground material facts also come from the
# existing terrain_materials.query(engine, cell) -> tuple of independent native
# material records, shared with map/material movement consumers. Flowing Step
# reads each actor_positions(engine, actor) cell and grants no traversal
# capability. Unknown material is not treated as wet; wet ground requires a
# ground-level cell. No helper interface or default behavior changes.
# Basin/Current membership uses spatial_areas.zone_contains(engine, actor, zone)
# -> bool, sharing native volume, suppression and line-of-effect geometry.
# Automatic Return effect choices use target_knowledge.located(engine, owner,
# holder) for creature-attached effects; placed owned Water stays known. Human
# options remain complete, with unlocated creature names omitted from labels.
# Flowing Step's turn_start subscriber closes the offer after native posture's
# pre-TURN_STARTED standing checkpoint; a later mid-turn Prone cannot claim it.
# A future qualifying genuine owner start refreshes the native turn stamp.

# Target-specific next-roll mode consumption (MGR-T15-close-sudden-flank):
# combat.attack_modes.consume_targeted_next_attack(engine, actor, target)
# -> tuple of removed modifier IDs. Gate2._resolve_attack_spec passes its
# notify flag as consume_target_modes to _resolve_attack_packet (its only
# caller): native rolls consume immediately after recording the real d20,
# against the actual recipient, before damage/nested aftermath can earn more;
# typed_executor._use_vex retains its existing post-result/replacement timing.
# Only attack_mode_vs / NEXT_ATTACK entries for that recipient are removed,
# regardless of final roll-mode cancellation. Existing MODIFIER_REMOVED events
# carry the original source and CONSUMED reason. No matching modifier is inert;
# other targets, expiry clocks, new hit-earned modifiers and other providers'
# state are preserved. Vex, Sudden Flank, Feint and Guarding Method share this
# modifier contract. No new hook, ability-ID core case or persisted field.
