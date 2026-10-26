"""Lazy CELL menus shared by the engine, table and automatic controllers.

The default query remains exhaustive. Service menus opt into one placeholder
per action/origin. A placeholder is bound through an ordinary persisted square
choice before paying or resolving the action. Exact-cell intents remain native.
"""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar

_QUERY = ContextVar('placement_menu_query', default=False)
_RANGE = ContextVar('placement_menu_range', default=None)
CHOICE = 'choice:placement_menu.square'


def axes(grid, intent, levels):
    """Exact aims visit one square; on-demand ranges omit impossible coordinates."""
    if intent is None:
        bounded = _RANGE.get()
        frame = getattr(bounded[0], '_shot_geometry', None) if bounded is not None else None
        if (bounded is not None and bounded[0].grid is grid and frame is not None
                and not bounded[2].parameters.get('any_cell')
                and frame['actor_id'] == bounded[1].entity_id
                and frame['action'] is bounded[2]):
            engine, actor, action = bounded
            # Native distance is the minimum Chebyshev distance from the
            # activation volume. Special any_cell queries have no native
            # action frame and conservatively keep their complete axes.
            # Its x/y bounding box is a necessary, never sufficient, range
            # test. Retain every altitude and leave final legality native.
            volume = engine._effect_volume(actor)
            reach = max(0, int(action.range_ft or 0) // grid.square_size_ft)
            xs, ys = [p[0] for p in volume], [p[1] for p in volume]
            return (range(max(0, min(xs) - reach), min(grid.width, max(xs) + reach + 1)),
                    range(max(0, min(ys) - reach), min(grid.height, max(ys) + reach + 1)), levels)
        return range(grid.width), range(grid.height), levels
    pos = intent.destination
    if pos is None or not (0 <= pos.x < grid.width and 0 <= pos.y < grid.height and pos.z in levels):
        return (), (), ()
    return (pos.x,), (pos.y,), (pos.z,)


@contextmanager
def query():
    token = _QUERY.set(True)
    try:
        yield
    finally:
        _QUERY.reset(token)


@contextmanager
def exhaustive():
    """Nested native geometry queries must see concrete rows, in the same knowledge view."""
    token = _QUERY.set(False)
    try:
        yield
    finally:
        _QUERY.reset(token)


def representative(engine, actor, action, candidate, *, intent=None):
    """Return a legal placeholder, or None; absent query preserves enumeration."""
    if not _QUERY.get() or intent is not None:
        return None
    from . import ext
    if ext.any_false('candidate_allowed', engine, actor, candidate, action):
        return None
    root = engine._candidate(candidate.kind, actor, action.source_definition_id,
        action.display_name + ' — choose a square', option_ids=candidate.option_ids,
        metadata={'placement_picker': True,
                  'placement_witness': candidate.destination.model_dump(mode='json')})
    return root


def exact(engine, root, position, *, cache=None):
    """Fresh authoritative candidates at any chosen cell, without menu caches.

    ``cache`` is an optional annotation-pass dictionary. Native identity ignores
    the issuing root and its option set, so several option roots of one ability
    ask the same exact-cell question; one read-only answer serves them all for
    the unchanged state. Execution and explicit aims never pass a cache. The
    cache omits the caller's knowledge view because one annotate() pass uses a
    single view for every root; do not share one cache across views.
    """
    from .gate2_runtime_models import ActionIntent
    from .canonical import canonical_sha256
    cache_key = None
    if cache is not None:
        import json
        origin = root.metadata.get('effect_origin')
        cache_key = (engine.state.state_version, engine.state.event_sequence, root.actor_id,
                     root.source_definition_id, str(root.kind),
                     json.dumps(origin, sort_keys=True, default=str),
                     position.x, position.y, position.z)
        if cache_key in cache:
            return cache[cache_key]
    identity = engine._candidate_identity(root.kind,
        engine.state.actors[root.actor_id], root.source_definition_id, (), position)
    # Preserve the origin sealed into the placeholder identity.
    origin = root.metadata.get('effect_origin')
    if origin:
        identity['effect_origin'] = origin
    cid = 'candidate:' + canonical_sha256(identity)[:24]
    hint = ActionIntent(intent_id='intent:placement-query', candidate_id=cid,
        decision_id=root.decision_id, state_version=root.state_version,
        actor_id=root.actor_id, target_ids=(), destination=position, option_ids=())
    from . import ext
    actor = engine.state.actors[root.actor_id]
    action = engine.action_catalog[root.source_definition_id]
    # The unchanged-state placeholder has already passed the global turn,
    # loadout and action gates. Recheck this action's native costs, geometry and
    # plug-in cell gates without walking every unrelated action in its catalog.
    found = next((c for c in engine._action_candidates(actor, action, intent=hint)
                  if c.candidate_id == cid and c.destination == position
                  and not ext.any_false('candidate_allowed', engine, actor, c, action)), None)
    if cache_key is not None:
        cache[cache_key] = found
    return found


def cells(engine, root, *, origins=None, share_pass=False):
    """Exhaustive legal second-stage choices, including represented altitudes.

    ``origins`` optionally batches roots of the same source; None keeps this
    root alone. ``share_pass`` is only for an unchanged read-only candidate
    pass and retains its declared invariant caches; ordinary pickers own a
    fresh scope. Every action/origin still has its separate geometry frame.
    """
    from . import ext
    from .read_queries import candidate_pass, enumeration_cache
    actor = engine.state.actors[root.actor_id]
    action = engine.action_catalog[root.source_definition_id]
    # Full authority is needed only for a picker or a sample miss. Native bulk
    # generation shares action/origin geometry instead of reinitializing it
    # at every cell. Disable only the presentation placeholder, retaining any
    # caller's observed-knowledge scope and the native altitude/range gates.
    token = _QUERY.set(False)
    range_token = _RANGE.set((engine, actor, action))
    try:
        with (nullcontext() if share_pass and enumeration_cache(engine) is not None else candidate_pass(engine)):
            rows = engine._action_candidates(actor, action)
    finally:
        _RANGE.reset(range_token)
        _QUERY.reset(token)
    origins = (root.metadata.get('effect_origin'),) if origins is None else origins
    for row in rows:
        if (row.destination is not None and row.metadata.get('effect_origin') in origins
                and not ext.any_false('candidate_allowed', engine, actor, row, action)):
            yield row


def native_rows(engine, candidates):
    """Expand an issued complete observed query for exact presentation scoring.

    Reuses all non-CELL candidates and expands each square-picker root with
    the same exhaustive native geometry/veto path used by the player picker.
    No AI placement sample or recommendation substitutes for a legal square.
    The caller must retain the query's observed-knowledge scope. Terrain is
    scoped exactly as in Gate4 native generation; source-level loadout/cost
    gates already admitted the root. Returns native candidate order, granting
    no cached execution authority.
    """
    from .movement_routes import ordered_candidates
    from .read_queries import candidate_pass
    from . import motion
    actor = engine.state.actors.get(engine.state.current_actor_id)
    rows, roots = [], {}
    for candidate in candidates:
        if candidate.metadata.get('placement_picker'):
            roots.setdefault(candidate.source_definition_id, []).append(candidate)
        else:
            rows.append(candidate)
    with candidate_pass(engine), motion.terrain_for(engine, actor):
        for batch in roots.values():
            # _action_candidates already visits all origins. Expand a source
            # once, rather than regenerate every origin for each root.
            rows.extend(cells(engine, batch[0],
                origins=tuple(root.metadata.get('effect_origin') for root in batch), share_pass=True))
    return ordered_candidates(rows)


def search(engine, root, context, *, exact_cache=None, share_pass=False):
    """Score a rotating, well-spread sample, then refine the best's neighbors.

    The sample is a ranking heuristic, not the legal choice set. On a miss,
    enumerate the legal set unless an ability-owned proof rules out every score.
    Such a proof never changes exhaustive picker or exact-aim authority.
    Scores use the ordinary controller unchanged; exhaustive choices remain
    available through cells() and explicit aims through exact().

    ``exact_cache`` is the annotation pass's read-only exact-cell sharing (see
    exact()); None gives every probe its own fresh query. ``share_pass`` tells
    the caller (annotate()) it already owns one immutable candidate pass, so the
    option roots of every ability share declared pass-invariant perception
    instead of reopening it per root. Nothing survives the pass.
    """
    from .gate2_runtime_models import Position
    from .gate4_controller import LocalDeterministicController, _option_sets
    from .candidate_knowledge import query as observed
    actor = engine.state.actors[root.actor_id]
    action = getattr(engine, "action_catalog", {}).get(getattr(root, "source_definition_id", None))
    if action is not None and ((action.parameters.get("typed") or {}).get("area") or action.radius_ft):
        from .relations import relation, ENEMY
        # Ordinary harmful empty areas are already vetoed in probe(). With
        # no perceived/remembered enemy there can be no admissible hit. Avoid
        # rebuilding an exhaustive menu to rediscover that fact. Explicit
        # terrain/setup opt-ins and every cells()/exact() aim remain untouched.
        if (not action.parameters.get("ai_allow_empty_area") and not any(
                a.active and relation(context, actor, a) == ENEMY for a in context.actors)):
            return None
    levels = sorted({0, actor.position.z} | {a.position.z for a in context.actors})
    width, height = engine.grid.width, engine.grid.height
    count = width * height * len(levels)
    phase = engine.state.state_version % count
    indices = {(phase + i * count // min(32, count)) % count for i in range(min(32, count))}
    points = [Position(x=(i // len(levels)) % width,
                       y=i // (len(levels) * width), z=levels[i % len(levels)])
              for i in sorted(indices)]
    points += [a.position for a in sorted(context.actors, key=lambda a: a.entity_id)[:8]]
    points.append(Position.model_validate(root.metadata['placement_witness']))
    controller = LocalDeterministicController()
    from .gate4_controller import _deals_damage
    strike_available = any(_deals_damage(c) for c in context.legal_candidates)
    # Same necessary x/y range bound the lazy range query uses (axes()): a
    # sample or remembered creature square outside the acting volume's box
    # expanded by the printed range cannot be a legal aim, so its exact query
    # can only return no row. This is a filter, never an offer: every point
    # inside the box still goes through the native exact() gate.
    in_bounds = None
    if action is not None and not action.parameters.get('any_cell'):
        volume = engine._effect_volume(actor)
        reach = max(0, int(action.range_ft or 0) // engine.grid.square_size_ft)
        xs = [p[0] for p in volume]
        ys = [p[1] for p in volume]
        box = (min(xs) - reach, max(xs) + reach, min(ys) - reach, max(ys) + reach)
        in_bounds = lambda position: (box[0] <= position.x <= box[1]
                                      and box[2] <= position.y <= box[3])
    seen, scored = set(), []
    shared = next((c.metadata for c in context.legal_candidates if c.candidate_id == root.candidate_id), root.metadata)
    shared = {k: v for k, v in shared.items() if k not in {
        'placement_picker', 'placement_witness', 'placement_evaluation', 'expected_damage',
        'hostiles_in_area', 'empty_area', 'unavoidable_allies_in_area'}}
    def best_row():
        safe = [item for item in scored if item[2].metadata.get('hostiles_in_area')
                and not item[2].metadata.get('unavoidable_allies_in_area')]
        return min(safe or scored, key=lambda item: (-item[0], item[1]))[2] if scored else None
    def probe(point, row=None):
        key = (point.x, point.y, point.z)
        if key in seen or not (0 <= point.x < width and 0 <= point.y < height):
            return
        seen.add(key)
        if row is None:
            if in_bounds is not None and not in_bounds(point):
                return  # outside the printed range: no native aim can exist here
            row = exact(engine, root, point, cache=exact_cache)
        if row is None:
            return
        from . import ext
        action = engine.action_catalog[root.source_definition_id]
        if (ext.any_false('ai_candidate_allowed', engine, actor, row, action)
                or (row.metadata.get('empty_area') and not action.parameters.get('ai_allow_empty_area'))):
            return
        row = row.model_copy(update={'metadata': {**shared, **row.metadata}})
        scores = [controller._score_candidate(context, row, options, strike_available=strike_available)
                  for options in _option_sets(row)]
        scored.append((max(s.total for s in scores), row.candidate_id, row))
    from .read_queries import candidate_pass
    # One immutable ranking query: share only declared pass-invariant facts
    # across sampled aims, exactly as cells()/native_rows() do. Shot geometry
    # still owns each action/origin frame; nothing survives this search or is
    # reused by execution/the next decision. annotate() may already own the pass
    # for every root; share_pass keeps that one instead of reopening it.
    with observed(engine), (nullcontext() if share_pass else candidate_pass(engine)):
        for point in points:
            probe(point)
        if scored:
            best = best_row().destination
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if 0 <= best.x + dx < width and 0 <= best.y + dy < height:
                        probe(Position(x=best.x + dx, y=best.y + dy, z=best.z))
        else:
            from . import ext
            action = getattr(engine, 'action_catalog', {}).get(getattr(root, 'source_definition_id', None))
            if action is not None and ext.any_false('placement_search_possible', engine, actor, action, root, context):
                return None  # A plug-in proved no admissible score; authority stays exhaustive.
            for row in cells(engine, root, share_pass=share_pass):
                probe(row.destination, row)
                if scored:
                    break  # First usable fallback; ranking need not find a global optimum.
    return best_row()


def annotate(engine, context):
    """Attach a scored preview to AI placeholders; never issue a new intent."""
    candidates = []
    # Option roots of one ability ask identical exact-cell questions; share the
    # read-only answers for this pass only. One immutable candidate pass spans
    # every root, so declared pass-invariant perception (who can see whom) is
    # worked out once for the decision instead of once per option.
    from .read_queries import candidate_pass
    exact_cache = {}
    with candidate_pass(engine):
        for root in context.legal_candidates:
            if root.metadata.get('placement_picker'):
                best = search(engine, root, context, exact_cache=exact_cache, share_pass=True)
                if best is None:
                    # A completed miss (or an ability-owned impossibility proof)
                    # is not a usable preview. Retain authority for explicit
                    # seats, while the local controller can distinguish AI
                    # admission.
                    candidates.append(root.model_copy(update={'metadata': {
                        **root.metadata, 'placement_ai_unavailable': True}}))
                    continue
                root = root.model_copy(update={'metadata': {**root.metadata,
                    **best.metadata, 'placement_ai_unavailable': False,
                    'placement_evaluation': best.model_dump(mode='json')}})
            candidates.append(root)
    return context.model_copy(update={'legal_candidates': tuple(candidates)})


def context_for_payload(engine, context, payload):
    """Immutably admit a freshly validated legacy exact-cell selection."""
    if payload.get('destination') is None or any(c.candidate_id == payload.get('candidate_id')
                                                for c in context.legal_candidates):
        return context
    from .gate2_runtime_models import ActionIntent
    hint = ActionIntent(intent_id='intent:exact-placement', **{key: payload[key] for key in (
        'candidate_id', 'decision_id', 'state_version', 'actor_id', 'target_ids', 'destination', 'option_ids')})
    candidate = next((c for c in engine.candidates_for_intent(hint)
                      if c.candidate_id == hint.candidate_id and
                      engine.action_catalog.get(c.source_definition_id) is not None and
                      engine.action_catalog[c.source_definition_id].target_kind == 'CELL'), None)
    return (context.model_copy(update={'legal_candidates': (*context.legal_candidates, candidate)})
            if candidate is not None else context)


def resolve(engine, actor, action, root, intent):
    """Bind a placeholder through the existing saved player/model choice path."""
    if not root.metadata.get('placement_picker'):
        if intent.placement_destination is not None:
            raise ValueError('A placement aim requires a square-placement menu choice')
        return root, intent
    from .ext import needle, ai_controlled
    from .gate4_context import build_decision_context
    from .gate4_policy import PolicyLibrary
    def policy_for_actor():
        from .gate4_models import LocalControllerPolicy
        document = (getattr(engine, 'placement_policies', {}) or {}).get(actor.entity_id)
        return (LocalControllerPolicy.model_validate(document) if document is not None
                else PolicyLibrary(engine.source_root).for_actor(actor.entity_id)[0])
    if intent.placement_destination is not None:
        from .candidate_knowledge import query as observed
        from contextlib import nullcontext
        with observed(engine) if ai_controlled(engine, actor) else nullcontext():
            chosen = exact(engine, root, intent.placement_destination)
        if chosen is None:
            raise ValueError('The chosen placement square is not legal')
        return chosen, intent.model_copy(update={'destination': chosen.destination})
    # Enumerate only the selected ability, on demand, for every seat. Automatic
    # scoring orders this complete set; it never becomes the choice authority.
    from .candidate_knowledge import query as observed
    from contextlib import nullcontext
    with observed(engine) if ai_controlled(engine, actor) else nullcontext():
        rows = list(cells(engine, root))
    by_id = {needle.cell_id(c.destination, include_altitude=True): c for c in rows}
    if not by_id:
        raise ValueError('No legal placement remains for this action')
    preferred = []
    if rows:
        policy = policy_for_actor()
        # A recommendation uses only this creature's knowledge. Keep its full
        # observed menu for tactical comparisons (such as available strikes),
        # but score only the selected ability, without annotating every root.
        # The complete by_id set above remains the square-choice authority.
        with query(), observed(engine):
            prepared = engine.legal_candidates()
        context = build_decision_context(engine, policy, for_ai=True,
                                         prepared_candidates=prepared, placement_previews=False)
        best = search(engine, root, context)
        if best is not None:
            preferred = [needle.cell_id(best.destination, include_altitude=True)]
        else:
            # LOCAL_AUTO has no explicit second-stage decision source. Its
            # reaction controller otherwise selects the first option even
            # with an empty Needle fallback. Explicit aims above and other
            # seats' complete journaled square choices retain their authority.
            modes = getattr(engine, 'typed_control_modes', {}) or {}
            mode = modes.get(actor.owner_id) or modes.get(actor.entity_id)
            if mode == 'LOCAL_AUTO':
                raise ValueError('Choose a legal square to use this action')
    from .ext.placement_picker import area_previews
    selected = needle.ask(engine, intent, 'placement:' + intent.intent_id, actor,
        CHOICE, list(by_id), name=action.display_name,
        space_areas=area_previews(engine, actor, action, rows),
        preferred=preferred,
        labels={key: f'Square {row.destination.x}, {row.destination.y}' +
                (f', {row.destination.z * 5} feet above ground' if row.destination.z else ', at ground level')
                + (f' — {row.display_name.split(" — ", 1)[1]}' if ' — ' in row.display_name else '')
                for key, row in by_id.items()},
        prompt=f'Choose a square for {actor.display_name} to use {action.display_name}.',
        prompt_context={'source_definition_id': action.source_definition_id,
                        'action_name': action.display_name, 'affected_id': actor.entity_id})
    if not selected:
        raise ValueError('Choose a legal square to use this action')
    chosen = by_id[selected[0]]
    return chosen, intent.model_copy(update={'destination': chosen.destination})
