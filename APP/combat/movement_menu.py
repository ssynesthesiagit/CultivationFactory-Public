"""Table-only route quotes. Execution and AI always use full native candidates.

The query is request-local; only the versioned service cache retains its result.
Routes keep every native mode, path and known-hazard warning, without tactical ranking metadata or
thousands of typed candidates. An endpoint quote is never execution authority.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_routes = ContextVar('table_movement_routes', default=None)


class _Rows(list):
    """Route rows for one table query. Zone hazard tests are built once per actor."""
    def __init__(self):
        super().__init__()
        self.zone_tests = {}


@contextmanager
def capture():
    rows = _Rows()
    token = _routes.set(rows)
    try:
        yield rows
    finally:
        _routes.reset(token)


def active():
    return _routes.get() is not None


@contextmanager
def suspend():
    token = _routes.set(None)
    try:
        yield
    finally:
        _routes.reset(token)


def native_routes_required(session):
    """Rare no-op boundaries need full paths for the existing progress guard."""
    from .turn_progress import requires_native_routes
    return requires_native_routes(session, verified_records=session.mechanical._records)


def rows():
    return _routes.get() or ()


def pack_grid(rows):
    """Group exact quotes by height/price/mode; every destination stays present."""
    layers = {}
    for row in rows:
        # Lazy geometry rows intentionally defer hazard disclosure; the compact
        # transport schema still has a hazard slot, defaulting to unknown/false.
        if len(row) == 6:
            x, y, z, cost, mode, drop = row
            hazard = False
        else:
            x, y, z, cost, mode, drop, hazard = row
        layers.setdefault((z, cost, mode, drop, hazard), []).extend((x, y))
    return {'format': 'layers-v2', 'layers': [[*key, cells] for key, cells in layers.items()]}


class RouteMetadata(dict):
    """Cheap native metadata keys, with tactical/path values resolved on demand."""
    expensive = {'compressed_path', 'reaction_exposure', 'hazard_exposure',
                 'zone_hazard_exposure', 'expected_opportunity_attack_count',
                 'expected_opportunity_attacks', 'cover_from_nearest_hostile', 'adjacent_hostiles'}

    def __init__(self, quote, values):
        super().__init__(values)
        self.quote = quote

    def get(self, key, default=None):
        if key in self.expensive:
            return self.quote.full().metadata.get(key, default)
        return super().get(key, default)

    def __getitem__(self, key):
        if key in self.expensive:
            return self.quote.full().metadata[key]
        return super().__getitem__(key)

    def __bool__(self):
        # Native movement metadata always contains path/exposure keys.
        return True

    def __contains__(self, key):
        if key in self.expensive:
            return key in self.quote.full().metadata
        return super().__contains__(key)

    def keys(self):
        return self.quote.full().metadata.keys()

    def items(self):
        return self.quote.full().metadata.items()

    def values(self):
        return self.quote.full().metadata.values()

    def __iter__(self):
        return iter(self.quote.full().metadata)

    def __len__(self):
        return len(self.quote.full().metadata)

    def copy(self):
        return self.quote.full().metadata.copy()

    def __eq__(self, other):
        return self.quote.full().metadata == other

    def __ne__(self, other):
        return not self == other


class RouteQuote:
    """Native veto input with lazy candidate details; never issued or serialized."""
    def __init__(self, engine, actor, destination, path, cost, mode, route_bound, can_jump_down, passage):
        from .gate2_runtime_models import CandidateKind
        self.kind = CandidateKind.MOVE
        self.actor_id = actor.entity_id
        self.source_definition_id = 'system:combat.movement'
        self.destination, self.canonical_path = destination, path
        self.movement_cost_ft = cost
        self.target_ids, self.option_ids = (), ()
        self.area = None
        self.engine, self.actor, self.mode = engine, actor, mode
        self._candidate = None
        metadata = {}
        if route_bound:
            metadata.update(explicit_movement_path=True, movement_mode=mode)
        if mode in {'fly', 'jump', 'climb', 'jump_down'} or (engine.grid.roof_surfaces and any(p.z for p in path)):
            metadata.update(movement_mode=mode, altitude_ft=destination.z * 5)
        if can_jump_down:
            metadata['can_jump_down'] = True
        if passage:
            metadata['creature_passage'] = passage
        self.metadata = RouteMetadata(self, metadata)

    def full(self):
        from types import SimpleNamespace
        if self._candidate is None:
            candidates = self.engine._movement_candidates(
                self.actor, intent=SimpleNamespace(destination=self.destination))
            self._candidate = next(c for c in candidates if c.canonical_path == self.canonical_path
                                   and c.metadata.get('movement_mode', 'walk') == self.mode)
        return self._candidate

    def __getattr__(self, name):
        return getattr(self.full(), name)


def known_hazard(engine, actor, path, rows):
    """Same known-hazard test as gate2_engine's native hazard_exposure: damaging terrain, then zone damage."""
    if engine._path_intersects_cells(actor, path[1:], engine.grid.qi_hazard):
        return True
    if actor.entity_id not in rows.zone_tests:
        from .zones import hazard_test
        rows.zone_tests[actor.entity_id] = hazard_test(engine, actor)
    zone = rows.zone_tests[actor.entity_id]
    return zone is not None and any(zone(position) for position in path[1:])


def collect(engine, actor, destination, path, cost, mode, can_jump_down, route_bound=False, passage=None):
    rows = _routes.get()
    if rows is None:
        return False
    from . import lazy_menu
    if lazy_menu.active(engine):
        # Geometry/price offer only. No per-square candidate or veto fan-out;
        # preview_destination regenerates the exact native route before use.
        from .read_queries import invariant_memo
        multiplier = invariant_memo(engine, ('menu_drag_price', actor.entity_id),
                                    lambda: engine._drag_multiplier(actor))
        rows.append((destination.x, destination.y, destination.z,
                     cost * multiplier, mode, bool(can_jump_down)))
        return True
    from . import ext
    quote = RouteQuote(engine, actor, destination, path, cost, mode, route_bound, can_jump_down, passage)
    # Preserve every plug-in veto. Nested legality probes must use native
    # candidates and must not append their routes to this table's quote list.
    token = _routes.set(None)
    try:
        denied = ext.any_false('candidate_allowed', engine, actor, quote,
                               engine.action_catalog.get(quote.source_definition_id))
    finally:
        _routes.reset(token)
    if denied:
        from .action_legality import plugin_denial
        plugin_denial('candidate_unavailability', engine, actor,
                      engine.action_catalog.get(quote.source_definition_id), quote, stage=2)
        return True
    rows.append((destination.x, destination.y, destination.z,
                 cost * engine._drag_multiplier(actor), mode, bool(can_jump_down),
                 known_hazard(engine, actor, path, rows)))
    return True
