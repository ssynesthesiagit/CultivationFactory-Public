"""Persisted, elapsed-time travel outside combat.

Consumers: CombatService and travel ability plug-ins. Journey state is separate
from combat rounds. A scene supplies its base pace and mapped travel obstacles;
abilities can change those through documented journey hooks, never engine patches.
Commands use optimistic revisions plus a file lock and atomic replace. No command
can reset a spent ability by reopening the same journey.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import re
import secrets
from fractions import Fraction
from contextlib import contextmanager
from pathlib import Path

from .ext import query, run_strict, transform
from .gate2_grid import SquareGrid
from .gate2_runtime_models import Position


def require(ok, message):
    if not ok:
        raise ValueError(message)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def state_digest(state):
    """Canonical primitive-state digest for native journey command replay."""
    return hashlib.sha256(json.dumps(state, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


TRAVEL_KINDS = ('cliff', 'river', 'forest', 'broken_terrain', 'water', 'vertical_surface')


def normalize_travel_regions(regions, width, height):
    """Authored travel facts, never inferred from decorative artwork.

    Consumers: TabletopMapStore and JourneyStore. Missing data is neutral.
    Cells use map coordinates, altitude bounds use whole five-foot steps.
    movement_cost is the scene's ordinary travel surcharge; requires_support
    distinguishes a water/vertical route from terrain merely slowing a walk.
    """
    require(isinstance(regions, list), 'Travel regions must be a list.')
    result = []
    for row in regions:
        require(isinstance(row, dict) and row.get('kind') in TRAVEL_KINDS, 'Choose a known travel terrain kind.')
        require(set(row) <= {'kind', 'cells', 'movement_cost', 'ordinary', 'requires_support', 'min_z', 'max_z'}, 'Unknown travel terrain field.')
        cells = row.get('cells')
        require(isinstance(cells, list) and cells, 'A travel region needs mapped cells.')
        for cell in cells:
            require(isinstance(cell, list) and len(cell) == 2
                    and integer(cell[0]) and integer(cell[1])
                    and cell[0] < width and cell[1] < height, 'Travel terrain must stay on the map.')
        cost = row.get('movement_cost', 1)
        low, high = row.get('min_z', 0), row.get('max_z', 0)
        ordinary, support = row.get('ordinary', True), row.get('requires_support', False)
        require(integer(cost, 1) and integer(low) and integer(high, low)
                and type(ordinary) in (bool, int) and ordinary in (0, 1)
                and type(support) in (bool, int) and support in (0, 1), 'Travel terrain costs/bounds must be whole numbers and flags must be booleans.')
        result.append({'kind': row['kind'], 'cells': [list(c) for c in sorted({tuple(c) for c in cells})],
                       'movement_cost': cost, 'ordinary': int(ordinary), 'requires_support': int(support),
                       'min_z': low, 'max_z': high})
    return result


class JourneySession:
    """One cold-loadable scene session; all clocks and balances are integers."""

    def __init__(self, state):
        self.state = state
        self.grid = SquareGrid(state['battlefield'])

    def properties(self, actor_id):
        result = {}
        for reply in query('journey_properties', self, actor_id):
            if reply:
                result.update(reply)
        return result

    def emit(self, kind, actor_id, **data):
        self.state['events'].append({'kind': kind, 'actor_id': actor_id,
                                     'seconds': self.state['seconds'], **data})

    def clock(self):
        """Exact elapsed seconds, persisted as integer numerator/denominator."""
        return Fraction(self.state['seconds']) + Fraction(self.state.get('subsecond_num', 0), self.state.get('subsecond_den', 1))

    def tick(self, seconds, moving=()):
        require((integer(seconds) or isinstance(seconds, Fraction)) and seconds >= 0,
                'Elapsed time must be nonnegative.')
        # Providers see both endpoints; they must not let a benefit survive an
        # expiry crossed inside one large time advance.
        before = self.clock()
        now = before + seconds
        self.state['seconds'] = now.numerator // now.denominator
        fraction = now - self.state['seconds']
        self.state['subsecond_num'], self.state['subsecond_den'] = fraction.numerator, fraction.denominator
        for actor_id in self.state['actors']:
            run_strict('journey_elapsed', self, actor_id, before, seconds, tuple(moving))

    def menu(self, actor_id):
        require(actor_id in self.state['actors'], 'Choose a creature in this journey.')
        actor = self.state['actors'][actor_id]
        options = [row for reply in query('journey_options', self, actor_id)
                   for row in (reply or [])]
        from .map_actions import options as map_options
        options.extend(map_options(self, actor_id))
        if self.state['phase'] == 'travel' and not actor['incapacitated'] and not actor.get('carried_by'):
            for cell in self.adjacent(actor_id):
                try:
                    self.step_profile(actor_id, Position.model_validate(actor['position']), Position.model_validate(cell))
                except ValueError:
                    continue
                options.append({'id': 'move:' + ','.join(str(cell.get(k, 0)) for k in ('x', 'y', 'z')),
                                'kind': 'move', 'payload': {'path': [cell]},
                                'label': f"{actor['name']}: travel to square ({cell['x']}, {cell['y']}), {cell.get('z', 0) * 5} feet high."})
        return {'revision': self.state['revision'], 'actor_id': actor_id,
                'seconds': self.state['seconds'], 'phase': self.state['phase'],
                'options': options, 'properties': self.properties(actor_id),
                'resources': copy.deepcopy(actor['resources'])}

    def adjacent(self, aid):
        old = Position.model_validate(self.state['actors'][aid]['position'])
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if (dx or dy or dz) and old.z + dz >= 0 and self.grid.in_bounds((old.x + dx, old.y + dy)):
                        cell = {'x': old.x + dx, 'y': old.y + dy}
                        if old.z + dz:
                            cell['z'] = old.z + dz
                        yield cell

    def near_visible(self, aid, target_id):
        if target_id == aid or target_id not in self.state['actors']:
            return False
        old = Position.model_validate(self.state['actors'][aid]['position'])
        target = Position.model_validate(self.state['actors'][target_id]['position'])
        return (self.grid.distance_cells(old, target) <= 1
                and self.grid.line_of_sight(old, target)
                and self.grid.line_of_physical_transmission(old, target))

    def regions(self, cell):
        return [row for row in self.state['battlefield'].get('travel_regions', ())
                if [cell.x, cell.y] in row['cells'] and row['min_z'] <= cell.z <= row['max_z']]

    def step_profile(self, aid, old, nxt, *, occupied=True):
        actor = self.state['actors'][aid]
        require(self.grid.distance_cells(old, nxt) == 1, 'Each route step must reach an adjacent square.')
        require(self.grid.in_bounds((nxt.x, nxt.y)), 'The route must stay on this map.')
        require(not self.grid.terrain_at(nxt, 'BLOCKED'), 'A solid wall blocks this route.')
        require(self.grid.line_of_physical_transmission(old, nxt), 'A solid obstacle blocks that step.')
        if actor['control_mode'] == 'LOCAL_AUTO':
            require(self.grid.line_of_sight(old, nxt), 'Automatic travel uses only visible squares.')
        if old.z == nxt.z:
            require(self.grid.step_legal(old, nxt), 'A wall or blocked corner prevents that route.')
        if occupied:
            require(not any(other_id != aid and not other.get('carried_by')
                            and other['position'] == nxt.model_dump(mode='json')
                            for other_id, other in self.state['actors'].items()), 'Another creature occupies that square.')
        rows = self.regions(nxt)
        overrides = {}
        for reply in query('journey_step', self, aid, old, nxt, rows):
            if reply:
                overrides.update(reply)
        allowed = set(overrides.get('supported_kinds', ()))
        require(all(not row['requires_support'] or row['kind'] in allowed for row in rows), 'This terrain requires a travel capability this creature does not have.')
        require(nxt.z == 0 or self.grid.roof_supported(nxt)
                or any(row['kind'] in ('vertical_surface', 'cliff') and row['kind'] in allowed for row in rows),
                'There is no supporting surface at that altitude.')
        require(old.z == nxt.z or any(row['kind'] in ('vertical_surface', 'cliff')
                                     and row['kind'] in allowed for row in rows), 'This route needs a mapped vertical travel surface.')
        ignored = set(overrides.get('ignore_slowing', ()))
        cost = max([self.grid.base_movement_cost.get((nxt.x, nxt.y), 1),
                    *(row['movement_cost'] for row in rows if row['kind'] not in ignored)])
        # A mapped exemption cancels only that terrain's surcharge, never an
        # overlapping unrelated Difficult Terrain or solid obstacle.
        native_cost = self.grid.base_movement_cost.get((nxt.x, nxt.y), 1)
        if any(row['kind'] in ignored and row['movement_cost'] == native_cost for row in rows):
            unrelated = [r for r in self.state['battlefield']['terrain_regions']
                         if any(c['x'] == nxt.x and c['y'] == nxt.y for c in r['cells'])
                         and r.get('travel_kind') not in ignored]
            cost = max([1, *(int(r.get('movement_cost', 1)) for r in unrelated),
                        *(row['movement_cost'] for row in rows if row['kind'] not in ignored)])
        if overrides.get('ignore_nonmagical_difficult'):
            # Painted difficult ground is mundane, as in combat/zones.py. Exempt
            # only its price: authored travel rows (including magical or
            # unsupported terrain) and other map costs still apply.
            remaining = [r for r in self.state['battlefield']['terrain_regions']
                         if any(c['x'] == nxt.x and c['y'] == nxt.y for c in r['cells'])
                         and r.get('nonmagical_difficult') != 1
                         and r.get('travel_kind') not in ignored]
            cost = max([1, *(int(r.get('movement_cost', 1)) for r in remaining),
                        *(row['movement_cost'] for row in rows if row['kind'] not in ignored)])
        elif self._named_difficult(nxt):
            # Named map ground that is difficult for everyone (loose rubble,
            # terrain.json difficult "all") costs the ordinary difficult price.
            # Only the Focus waiver above exempts it.
            cost = max(cost, 2)
        return cost

    def _named_difficult(self, cell):
        from .zones import terrain_rules
        terrains = terrain_rules().get('terrains', {})
        return any([cell.x, cell.y] in row['cells']
                   and (terrains.get(row.get('terrain')) or {}).get('difficult') == 'all'
                   for row in self.state['battlefield'].get('map_terrain', ()))

    def command(self, actor_id, kind, payload):
        require(isinstance(actor_id, str) and isinstance(kind, str) and isinstance(payload, dict), 'Choose a creature, action and structured parameters.')
        require(actor_id in self.state['actors'], 'Choose a creature in this journey.')
        if kind == 'finish':
            require(not payload and (self.state['phase'] == 'travel' or
                    (self.state['phase'] == 'combat' and not self.state.get('match_id'))),
                    'Resume the completed bound fight before finishing this journey.')
            self.state['phase'] = 'finished'
            self.state.pop('carry_request', None)
            for aid, creature in self.state['actors'].items():
                creature.pop('carried_by', None)
                run_strict('journey_state_changed', self, aid)
            self.emit('JOURNEY_FINISHED', actor_id, text='Journey finished; its creatures may begin another journey.')
            return
        require(self.state['phase'] == 'travel', 'This journey has already entered combat.')
        actor = self.state['actors'][actor_id]
        from .map_actions import command as map_command
        if map_command(self, actor_id, kind, payload):
            return
        if kind == 'wait':
            require(set(payload) == {'seconds'} and integer(payload['seconds']), 'Choose whole seconds to wait.')
            self.tick(payload['seconds'])
        elif kind == 'long_rest':
            require(not payload, 'Long Rest takes eight hours; it has no instant shortcut.')
            require(not actor['incapacitated'], 'An incapacitated creature cannot start this rest.')
            self.tick(28800)
            actor['long_rests'] += 1
            # This seam recharges owned travel abilities, not arbitrary combat
            # pools or Hit Points. Rest resource recovery stays with its owner.
            run_strict('journey_rest', self, actor_id)
            self.emit('LONG_REST', actor_id, text=f"{actor['name']} finishes an eight-hour Long Rest.")
        elif kind == 'incapacitated':
            require(set(payload) == {'value'} and type(payload['value']) is bool, 'Choose the incapacitated state.')
            from .ext.journey_setup import encounter_incapacitated
            require(payload['value'] or not encounter_incapacitated(actor.get('encounter_snapshot')),
                    f"{actor['name']} is still incapacitated by their saved encounter HP or conditions. "
                    'Resolve that health or condition in combat before clearing travel incapacitation; '
                    'this action does not heal or remove conditions.')
            actor['incapacitated'] = int(payload['value'])
            run_strict('journey_state_changed', self, actor_id)
        elif kind == 'travel_exhaustion':
            require(set(payload) == {'levels', 'ordinary'} and integer(payload['levels'], 1)
                    and type(payload['ordinary']) is bool, 'Record a sourced travel exhaustion exposure.')
            ignored = payload['ordinary'] and self.properties(actor_id).get('ignore_ordinary_travel_exhaustion')
            if not ignored:
                from .ext.forged_exhaustion import MAX_LEVEL
                require(actor['exhaustion'] + payload['levels'] < MAX_LEVEL,
                        'Six levels of Exhaustion kill a creature. Resolve this lethal exposure '
                        'in combat before continuing the journey; no exposure has been saved.')
                actor['exhaustion'] += payload['levels']
            self.emit('TRAVEL_EXHAUSTION', actor_id, levels=0 if ignored else payload['levels'])
        elif kind == 'enter_combat':
            require(not payload, 'Combat entry takes no travel parameters.')
            self.state['phase'] = 'combat'
            for aid in self.state['actors']:
                run_strict('journey_state_changed', self, aid)
            self.emit('ENTER_COMBAT', actor_id)
        elif kind == 'move':
            self.move(actor_id, payload)
        else:
            handled = run_strict('journey_command', self, actor_id, kind, payload)
            require(any(reply is True for reply in handled), 'That journey action is not available.')

    def move(self, actor_id, payload):
        require(set(payload) == {'path'} and isinstance(payload['path'], list)
                and payload['path'], 'Choose a nonempty route on the map.')
        actor = self.state['actors'][actor_id]
        require(not actor['incapacitated'], 'An incapacitated creature cannot travel.')
        require(not actor.get('carried_by'), 'A carried creature must be set down before moving itself.')
        for cell in payload['path']:
            nxt = Position.model_validate(cell)
            old = Position.model_validate(actor['position'])
            self.step_profile(actor_id, old, nxt)
            distance_units = Fraction(self.grid.distance_ft(old, nxt) * 3600)
            started = self.clock()
            while distance_units > 0:
                props = self.properties(actor_id)
                cost = self.step_profile(actor_id, old, nxt)
                carrying = any(other.get('carried_by') == actor_id for other in self.state['actors'].values())
                base = actor['base_pace_ft_hour'] if props.get('carry_without_slowing') or not carrying else actor['loaded_pace_ft_hour']
                pace = base * int(props.get('pace_multiplier', 1))
                require(pace > 0, 'This creature cannot travel at a zero pace.')
                seconds = distance_units * cost / pace
                if props.get('expiry_num') is not None:
                    remaining = Fraction(props['expiry_num'], props['expiry_den']) - self.clock()
                    require(remaining > 0, 'The travel benefit has expired; refresh before moving.')
                    seconds = min(seconds, remaining)
                distance_units = max(Fraction(0), distance_units - Fraction(seconds * pace, cost))
                moving = (actor_id, *(aid for aid, other in self.state['actors'].items()
                                      if other.get('carried_by') == actor_id))
                self.tick(seconds, moving)
            duration = self.clock() - started
            seconds = duration.numerator // duration.denominator
            actor['position'] = nxt.model_dump(mode='json')
            for other in self.state['actors'].values():
                if other.get('carried_by') == actor_id:
                    other['position'] = dict(actor['position'])
            for aid in self.state['actors']:
                run_strict('journey_state_changed', self, aid)
            self.emit('TRAVEL_STEP', actor_id, position=actor['position'], seconds_taken=seconds,
                      elapsed_num=duration.numerator, elapsed_den=duration.denominator)


def plain_json(value, depth=0):
    """Only values that round-trip exactly into a replay journal: no floats, sets or objects."""
    if depth > 12:
        return False
    if value is None or type(value) in (bool, int, str):
        return True
    if type(value) is list:
        return all(plain_json(item, depth + 1) for item in value)
    if type(value) is dict:
        return all(type(key) is str and plain_json(item, depth + 1) for key, item in value.items())
    return False


class JourneyStore:
    def __init__(self, root):
        self.root = Path(root)

    @staticmethod
    def view(state, viewer_id=None):
        """Actor projection; source providers redact their own private inputs."""
        out = transform('journey_view', copy.deepcopy(state), viewer_id)
        out.pop('replay_base', None)
        out.pop('command_journal', None)
        return out

    def path(self, journey_id):
        require(isinstance(journey_id, str) and re.fullmatch(r'journey-[0-9a-f]{24}', journey_id), 'Invalid journey id.')
        return self.root / 'State.json'

    @contextmanager
    def locked(self, journey_id):
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path(journey_id).with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def load(self, journey_id):
        registry = json.loads(self.path(journey_id).read_text())
        require(journey_id in registry['sessions'], 'That journey does not exist.')
        state = registry['sessions'][journey_id]
        for reply in run_strict('journey_shared_fields'):
            for key in reply or ():
                if key in registry:
                    state[key] = copy.deepcopy(registry[key])
        return JourneySession(state)

    def journal_started(self, journey_id):
        path = self.path(journey_id)
        return path.exists() and bool(json.loads(path.read_text()).get('replays', {}).get(journey_id))

    def save(self, session, *, command=None, checkpoint=None):
        path = self.path(session.state['journey_id'])
        registry = json.loads(path.read_text()) if path.exists() else {'sessions': {}, 'actors': {}}
        require(registry['sessions'].get(session.state['journey_id'], {}).get('phase') != 'finished',
                'This journey is finished; continue the newer journey.')
        for jid, prior in registry['sessions'].items():
            require(jid == session.state['journey_id'] or prior['phase'] == 'finished'
                    or not set(session.state['actors']).intersection(prior['actors']),
                    'A creature is already in another active journey; resolve its ownership first.')
        journey_id = session.state['journey_id']
        segments = registry.setdefault('replays', {}).setdefault(journey_id, [])
        if command is None:
            # Admission and native encounter transitions are checkpoints.
            # Combat owns the intervening encounter's mechanical journal;
            # map commands replay from each durable travel boundary.
            segments.append({'initial': copy.deepcopy(session.state), 'commands': []})
        else:
            if not segments:
                # Journeys saved before replay journals existed have no admission
                # checkpoint. Their first command under this build starts one from
                # the state just before that command, so they keep accepting moves;
                # replay then covers only commands recorded from here on.
                require(checkpoint is not None, 'This journey has no replay admission checkpoint.')
                segments.append({'initial': copy.deepcopy(checkpoint), 'commands': []})
            segments[-1]['commands'].append({**copy.deepcopy(command),
                                             'state_sha256': state_digest(session.state)})
        registry['sessions'][journey_id] = session.state
        # Declared shared fields (e.g. material_sources) live at the registry's top level, so every
        # journey and later load sees one copy; a per-session copy would silently go stale.
        for reply in run_strict('journey_shared_fields'):
            for key in reply or ():
                if key in session.state:
                    registry[key] = copy.deepcopy(session.state[key])
        for aid, actor in session.state['actors'].items():
            extra = [key for reply in run_strict('journey_persistent_fields') for key in (reply or ())]
            registry['actors'][aid] = {key: copy.deepcopy(actor[key]) for key in
                                      ('resources', 'long_rests', 'travel_uses', 'exhaustion', 'incapacitated', 'encounter_snapshot', *extra)
                                      if key in actor}
        temporary = path.with_suffix('.new')
        try:
            with temporary.open('w') as stream:
                json.dump(registry, stream, ensure_ascii=False, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def replay(self, journey_id):
        """Replay committed map intents, without writes or duplicate benefits.

        Consumers: CombatService.journey_replay and native scene acceptance.
        Encounter boundary checkpoints do not certify combat: its own verify
        and mechanical replay remain authoritative for those transitions.
        Missing history fails closed instead of manufacturing a receipt.
        """
        registry = json.loads(self.path(journey_id).read_text())
        segments = registry.get('replays', {}).get(journey_id, [])
        require(bool(segments), 'This journey has no mechanical replay journal.')
        count = 0
        for segment in segments:
            session = JourneySession(copy.deepcopy(segment['initial']))
            for command in segment['commands']:
                session.command(command['actor_id'], command['kind'], copy.deepcopy(command['payload']))
                session.state['revision'] += 1
                require(state_digest(session.state) == command['state_sha256'],
                        'Journey replay diverged from its committed map state.')
                count += 1
        digest = state_digest(session.state)
        require(digest == state_digest(registry['sessions'][journey_id]),
                'Journey replay does not match the saved scene.')
        return {'status': 'PASS', 'commands': count, 'segments': len(segments), 'state_sha256': digest}

    def create(self, bundles, battlefield, positions, base_paces, control_modes=None, loaded_paces=None):
        require(bundles and len({b['actor_id'] for b in bundles}) == len(bundles), 'Choose distinct journey creatures.')
        grid = SquareGrid(battlefield)
        battlefield = copy.deepcopy(battlefield)
        battlefield['travel_regions'] = normalize_travel_regions(battlefield.get('travel_regions', []), grid.width, grid.height)
        actors = {}
        for bundle in bundles:
            aid = bundle['actor_id']
            template = bundle['actor_template']
            pos = Position.model_validate(positions[aid])
            require(pos.z == 0 and grid.placement_legal(pos, occupied_cells=set()), 'Choose an open starting square.')
            require(integer(base_paces[aid], 1), 'Supply a positive whole-foot base overland pace per hour.')
            loaded = (loaded_paces or {}).get(aid, base_paces[aid])
            require(integer(loaded, 1), 'Supply a positive sourced loaded travel pace.')
            mode = (control_modes or {}).get(aid, 'MANUAL')
            require(mode in ('MANUAL', 'LOCAL_AUTO'), 'Choose Manual or local automatic travel control.')
            actors[aid] = {'bundle': copy.deepcopy(bundle), 'name': template['display_name'],
                           'position': pos.model_dump(mode='json'), 'base_pace_ft_hour': base_paces[aid],
                           'loaded_pace_ft_hour': loaded, 'size': template.get('size_category', 'Medium'),
                           'resources': {r['resource_id']: r['initial'] for r in template['resources']},
                           'control_mode': mode, 'incapacitated': 0, 'exhaustion': 0,
                           'long_rests': 0, 'travel_effects': {}, 'travel_uses': {}}
        require(len({json.dumps(a['position'], sort_keys=True) for a in actors.values()}) == len(actors), 'Starting squares must be distinct.')
        journey_id = 'journey-' + secrets.token_hex(12)
        session = JourneySession({'schema': 'TianxiaJourney.v1', 'journey_id': journey_id,
                                  'revision': 0, 'seconds': 0, 'phase': 'travel',
                                  'battlefield': copy.deepcopy(battlefield), 'actors': actors, 'events': []})
        with self.locked(journey_id):
            path = self.path(journey_id)
            registry = json.loads(path.read_text()) if path.exists() else {'sessions': {}, 'actors': {}}
            for reply in run_strict('journey_shared_fields'):
                for key in reply or ():
                    if key in registry:
                        session.state[key] = copy.deepcopy(registry[key])
            for prior in registry['sessions'].values():
                require(prior['phase'] == 'finished' or not set(actors).intersection(prior['actors']),
                        'A creature is already in an active journey; continue that session.')
            for aid, actor in actors.items():
                actor.update(copy.deepcopy(registry['actors'].get(aid, {})))
            session.state['replay_base'] = copy.deepcopy(session.state)
            session.state['command_journal'] = []
            self.save(session)
        return self.view(session.state)

    def act(self, journey_id, revision, actor_id, kind, payload=None):
        with self.locked(journey_id):
            session = self.load(journey_id)
            require(type(revision) is int and revision == session.state['revision'], 'The journey changed; refresh before acting.')
            payload = {} if payload is None else payload
            require(plain_json(payload) and len(json.dumps(payload, sort_keys=True)) <= 4096,
                    'Journey commands take plain whole-number, text, true/false or list/object parameters within 4 KB.')
            # Only a journey without a replay journal needs its pre-command state.
            before = copy.deepcopy(session.state) if not self.journal_started(journey_id) else None
            session.command(actor_id, kind, payload)
            session.state['revision'] += 1
            self.save(session, command={'actor_id': actor_id, 'kind': kind, 'payload': payload}, checkpoint=before)
            # Same projection as journey_state/journey_resume: never the raw session
            # (replay genesis, command journal, GM material sources, other seats' inputs).
            return self.view(session.state, actor_id)

    def admit(self, journey_id, revision, actor_id, kind, payload, *, gm=False, reason=''):
        """GM-authorized typed scene fact, revision-bound and saved as a replay checkpoint.

        Consumers: CombatService.journey_admit (the only entry point; the HTTP
        surface does not expose it, because this local API has no GM sign-in).
        Providers run through the journey_admission hook; a fact no provider
        accepts is refused and nothing is written.
        """
        require(gm is True, 'Only the GM can admit a journey fact.')
        require(isinstance(reason, str) and reason.strip() and len(reason) <= 1000,
                'Give the source of this fact in up to 1000 characters.')
        with self.locked(journey_id):
            session = self.load(journey_id)
            require(type(revision) is int and revision == session.state['revision'], 'The journey changed; refresh before acting.')
            require(isinstance(actor_id, str) and actor_id in session.state['actors'], 'Choose a creature in this journey.')
            require(isinstance(kind, str) and isinstance(payload, dict), 'Choose a fact kind and structured parameters.')
            require(plain_json(payload) and len(json.dumps(payload, sort_keys=True)) <= 4096,
                    'Journey facts take plain whole-number, text, true/false or list/object parameters within 4 KB.')
            handled = run_strict('journey_admission', session, actor_id, kind, copy.deepcopy(payload), reason.strip())
            require(any(reply is True for reply in handled), 'That journey fact is not available.')
            session.state['revision'] += 1
            self.save(session)
            return copy.deepcopy(session.state)
