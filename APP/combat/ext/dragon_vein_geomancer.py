"""Dragon-Vein infrastructure, sourced from the R19 five-tier progression.

One producer owns all physical Anchors. Objects are journaled with their real
positions and durability; topology is recomputed from native support and barrier
geometry. No cached 'connected' declaration can make an obstructed route legal.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import replace
import json

from . import effect, hook, note
from ..gate2_runtime_models import ActionDefinition, EconomyKind, Position, RuntimeObjectState

PREFIX = 'tianxia.subpath.qi.dragon_vein_geomancer.feature.'
READ, CIRCUIT, NETWORK, PASSAGE, IMPERIAL = [PREFIX + name for name in (
    'read_the_dragon_vein', 'ley_line_circuit', 'dragon_vein_network',
    'dragon_road_passage', 'imperial_dragon_vein')]
LEVELS = {READ: 3, CIRCUIT: 6, NETWORK: 10, PASSAGE: 14, IMPERIAL: 18}
QI = 'resource:core.qi'
BLOCK = 'dragon_vein_geomancer'
MODES = ('earth', 'water', 'wood', 'metal', 'gravity')
STATE = 'condition:typed.dragon_vein_state'
HARDEN = 'condition:typed.geomancy_harden'
HARDEN_SAVE = 'condition:typed.geomancy_harden_save'
COMMANDS = ('raise','redirect','harden','feed','ring','gravity','repair')
COMMAND_LABELS = {
    'raise': 'Raise the Road - a 20 x 10 foot bridge or platform until your next turn',
    'redirect': 'Redirect the River - move one willing ally in Claimed Ground up to 15 feet',
    'harden': 'Harden the Mountain - one ally gains +2 AC and Advantage on its next save against forced movement',
    'feed': 'Feed the Forest - one ally regains 2d8 + your Qi key ability modifier Hit Points',
    'ring': 'Ring the Metal Vein - one hostile creature makes a Dexterity save: 4d8 Slashing or Force and no Reactions',
    'gravity': 'Increase Gravity - a 15-foot area in Claimed Ground is difficult and can knock hostiles Prone',
    'repair': 'Repair the Meridian - one active Anchor regains 3d8 + your Qi key ability modifier Hit Points',
    'sense': 'Read the Dragon Vein - while touching stable ground, sense terrain and structure within 60 feet',
}


def kit(engine, actor):
    return next((r for r in engine.typed_passive_rows.get(actor.entity_id, ())
                 if r.get('block') == BLOCK), None)


def state(actor):
    held = next((c for c in actor.conditions.values() if c.condition_id == STATE), None)
    return json.loads(held.data['state']) if held else {}


def store(engine, actor, data):
    engine._remove_condition(actor,STATE,READ)
    engine._apply_condition(actor, STATE, READ, actor.entity_id,
        expires_on='UNTIL_REMOVED', data={'state': json.dumps(data, sort_keys=True),
                                        'label': 'Dragon-Vein infrastructure'})


def anchors(engine, owner, *, active=True):
    # An Imperial Anchor belongs to one Imperial field and is inert once that
    # field has ended, even before its object is torn down.
    return [o for o in engine.state.objects.values()
            if o.owner_id == owner.entity_id and (o.component or {}).get(BLOCK)
            and not o.destroyed and (not active or not o.suppressed) and live_field(engine, owner, o)]


def live_field(engine, owner, obj):
    field = (obj.component or {}).get(BLOCK, {}).get('field_id')
    if field is None:
        return True
    zone = province(engine, owner)
    return zone is not None and zone.zone_id == field


def imperial_points(engine, center):
    from .grid_radius_cache import cells_in_radius
    from .needle import cell_id
    return {cell_id(p):p for p in cells_in_radius(engine.grid,center,12)
            if stable(engine,p) and not any(p == a.position for a in engine.state.actors.values() if a.active)}


IMPERIAL_ANCHORS = 5
IMPERIAL_SPACING_FT = 15


def can_place_anchors(engine, pool, need):
    """True when `need` Imperial Anchors fit in `pool`: each on a listed space and each at least 15 feet
    from every other one (printed rule: Imperial Dragon Vein). Used by the candidate gate and by the resolver,
    so the option is only offered when a full legal set of five exists."""
    cells = list(pool)
    spaced = [[engine.grid.distance_ft(p,q) >= IMPERIAL_SPACING_FT for q in cells] for p in cells]
    memo = {}

    def fits(indices, left):
        # indices: ascending tuple of still-compatible cells; pick one, then only later compatible cells.
        if left == 0:
            return True
        if len(indices) < left:
            return False
        key = (indices, left)
        if key not in memo:
            memo[key] = any(fits(tuple(j for j in indices[k+1:] if spaced[i][j]), left-1)
                            for k,i in enumerate(indices))
        return memo[key]
    return fits(tuple(range(len(cells))), need)


def stable(engine, position):
    from ..asset_anchor_runtime import stable as supported
    return supported(engine, position)


def surface_path(engine, start, end, distance):
    """Bounded native supported route. Solid barriers never become ley lines.

    The printed distance is between Anchors; the continuous path must exist.
    Route traversal remains on stable map/roof/object surfaces and requires
    physical transmission at each step, including diagonal corner checks.
    """
    if engine.grid.distance_ft(start, end) > distance or not stable(engine, start) or not stable(engine, end):
        return False
    queue, seen = deque([start]), {(start.x, start.y, start.z)}
    while queue:
        p = queue.popleft()
        if p == end:
            return True
        for dx, dy, dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
            key = (p.x+dx,p.y+dy,p.z+dz)
            if key in seen or key[2] < 0 or not engine.grid.in_bounds(key[:2]):
                continue
            q = Position(x=key[0],y=key[1],z=key[2])
            if engine.grid.distance_ft(start,q) > distance or not stable(engine,q):
                continue
            if not engine.grid.line_of_physical_transmission(p,q):
                continue
            seen.add(key)
            queue.append(q)
    return False


def network_active(engine, owner):
    return int(state(owner).get('network_end_round', 0)) > engine.state.round_number


def province(engine, owner):
    from . import placed
    zone = next((z for z in placed.of(engine,'imperial_vein',owner_id=owner.entity_id)),None)
    if zone is None:
        # Dispersal resolves after the field has been removed; its geometry stays readable until it finishes.
        ending = state(owner).get('dispersing')
        zone = engine.state.zones.get(ending) if ending else None
    return zone


def in_province(engine, owner, position):
    z = province(engine,owner)
    if z is None:
        return False
    return (max(abs(position.x-z.center.x),abs(position.y-z.center.y))*5 <= 60
            and z.center.z <= position.z < z.center.z+12)


def connected(engine, owner, first, second):
    if first not in anchors(engine,owner) or second not in anchors(engine,owner):
        return False
    # Connectivity is transitive; a chain may contain several ordinary links.
    live = anchors(engine,owner)
    awakened = set(state(owner).get('awakened', ())) if network_active(engine,owner) else set()
    queue, seen = deque([first]), {first.object_id}
    while queue:
        current = queue.popleft()
        if current.object_id == second.object_id:
            return True
        for other in live:
            if other.object_id in seen:
                continue
            imperial = in_province(engine,owner,current.position) and in_province(engine,owner,other.position)
            reach = 120 if {current.object_id,other.object_id} <= awakened else 60
            if imperial or surface_path(engine,current.position,other.position,reach):
                seen.add(other.object_id)
                queue.append(other)
    return False


def radius(engine, owner, obj):
    if in_province(engine,owner,obj.position):
        return 20
    return 15 if network_active(engine,owner) and obj.object_id in state(owner).get('awakened',()) else 10


def covers(engine, owner, obj, cell):
    return engine.grid.distance_ft(obj.position,cell) <= radius(engine,owner,obj)


def modes(engine, owner, obj):
    if CIRCUIT not in kit(engine,owner)['owned']:
        return ()
    if in_province(engine,owner,obj.position):
        return MODES
    live = anchors(engine,owner)
    awakened = set(state(owner).get('awakened', ())) if network_active(engine,owner) else set()
    if obj.object_id in awakened:
        return tuple(sorted({o.component[BLOCK]['mode'] for o in live if o.object_id in awakened}))
    return (obj.component[BLOCK]['mode'],)


def benefits(engine, subject):
    """One contribution per owner, preserving nonstacking named benefits."""
    out = []
    for owner in engine.state.actors.values():
        source = kit(engine,owner)
        if source is None:
            continue
        data = state(owner)
        if subject.entity_id not in data.get('allies', ()):
            continue
        over = [o for o in anchors(engine,owner) if covers(engine,owner,o,subject.position)]
        if over:
            out.append((owner,source,{m for o in over for m in modes(engine,owner,o)}))
    return out


@hook('compile_passives')
def compile_ownership(rows, info):
    from ..subpath_acquisition import acquired_features
    from pathlib import Path
    levels = acquired_features(info['owner_sheet'],Path(__file__).resolve().parents[2],include_unavailable=True)
    owned = [mid for mid in LEVELS if mid in info['owned_ids']
             and int(levels.get(mid,{}).get('cl',info['numbers']['cl'])) >= LEVELS[mid]]
    if READ not in owned:
        return rows
    cl = int(levels.get(READ,{}).get('cl',info['numbers']['cl']))
    return [*rows,{'block':BLOCK,'feature_id':READ,'owned':owned,
                  'numbers':{**info['numbers'],'cl':cl},'trigger_owner':BLOCK}]


@hook('compile_actions')
def compile_actions(info):
    from ..subpath_acquisition import acquired_features
    from pathlib import Path
    levels = acquired_features(info['owner_sheet'],Path(__file__).resolve().parents[2],include_unavailable=True)
    owned = {mid for mid in LEVELS if mid in info['owned_ids']
             and int(levels.get(mid,{}).get('cl',info['numbers']['cl'])) >= LEVELS[mid]}
    if READ not in owned:
        return None
    numbers = {**info['numbers'],'cl':int(levels.get(READ,{}).get('cl',info['numbers']['cl']))}
    out = []
    def add(key,label,source,economy=EconomyKind.NONE,target='SELF',reach=None,cost=0):
        out.append(ActionDefinition(source_definition_id=f'action:typed.{info["short"]}.geomancy.{key}',
            display_name=label,owner_id=info['actor_id'],economy=economy,
            resolution_kind='TYPED',target_kind=target,range_ft=reach,
            costs=((QI,cost),) if cost else (),parameters={
                'typed':{'source':source,'effects':[{'type':'dragon_vein_command','command':key}],
                         'numbers':numbers,'duration':{'kind':'instant'},'riders':[]},
                'geomancy':key,'any_cell':True,'free_primary':True,'expected_damage':0}))
    add('place','Place Vein Anchor — Action, 1 Qi, 30 feet, lasts 8 hours',READ,
        EconomyKind.ACTION,'CELL',30,1)
    add('sense','Read the Dragon Vein - sense hollows, water, structure, anchors and pressure within 60 feet (touch stable ground)',READ)
    add('allies','Choose Grounding allies - allies who gain Grounding in your Vein Anchor ground',READ)
    if CIRCUIT in owned:
        add('mode','Ley-Line Circuit — change one Anchor mode within 120 feet, once per turn',CIRCUIT)
    if NETWORK in owned:
        add('network','Dragon-Vein Network — Bonus Action, 5 Qi, lasts 1 minute',NETWORK,
            EconomyKind.BONUS_ACTION,cost=5)
        add('adjust','Network Adjustment — one free adjustment on your turn in Claimed Ground',NETWORK)
    if PASSAGE in owned:
        add('passage','Dragon-Road Passage — Bonus Action, 2 Qi (free once per turn inside your Imperial Dragon Vein field); carrying a willing traveler costs 2 more Qi (1 more inside that field)',PASSAGE,
            EconomyKind.BONUS_ACTION)
    if IMPERIAL in owned:
        add('imperial','Imperial Dragon Vein — Action, 8 Qi, Concentration, 1 minute, once per scene',IMPERIAL,
            EconomyKind.ACTION,'CELL',120,8)
    return out


@hook('compile_action')
def publication(action, info):
    # The one owned provider replaces the old incomplete generic fragments.
    source = (action.parameters.get('typed') or {}).get('source')
    if source in LEVELS and not action.parameters.get('geomancy'):
        return action.model_copy(update={'parameters':{'typed':{'effects':[],'riders':[]}}})


@hook('candidate_allowed')
def candidates(engine, actor, candidate, action):
    # Movement/teleport previews and other plug-ins call every gate with
    # action=None. That is not one of this plug-in's actions: decline explicitly
    # instead of dereferencing a missing definition (Sol review 4F2).
    if action is None:
        return None
    command = (getattr(action,'parameters',None) or {}).get('geomancy')
    if not command:
        return None
    source = kit(engine,actor)
    if source is None:
        return False
    if command == 'place':
        p = candidate.destination
        return p is not None and stable(engine,p) and engine.grid.distance_ft(actor.position,p) <= 30
    if command == 'sense':
        return stable(engine,actor.position)
    if command == 'mode':
        return not actor.turn_flags.get('geomancy_mode') and any(
            engine.grid.distance_ft(actor.position,o.position) <= 120 for o in anchors(engine,actor,active=False))
    if command == 'network':
        return any(engine.grid.distance_ft(actor.position,o.position) <= 120 for o in anchors(engine,actor))
    if command == 'adjust':
        return network_active(engine,actor) and claimed(engine,actor,actor.position) and not actor.turn_flags.get('geomancy_adjust')
    if command == 'passage':
        free = province(engine,actor) is not None and not actor.turn_flags.get('geomancy_passage')
        return (not actor.turn_flags.get('geomancy_passage') and actor.resources.get(QI,0) >= (0 if free else 2)
                and bool(passage_routes(engine,actor)))
    if command == 'imperial':
        # The centre need not be stable; the field needs five legal anchor spaces.
        return (not state(actor).get('imperial_spent') and candidate.destination is not None
                and can_place_anchors(engine, list(imperial_points(engine,candidate.destination).values()), IMPERIAL_ANCHORS))


def choose(ctx, suffix, options, *, labels=None, prompt='', maximum=1, minimum=1, chooser=None, default='first'):
    from .needle import ask, checkpoint_id
    return ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,BLOCK,suffix),chooser or ctx.actor,
        'choice:needle.geomancy.'+suffix,list(options),labels=labels,prompt=prompt,
        maximum=maximum,minimum=minimum,default=default,name='Dragon-Vein Geomancer',feature_id=ctx.source)


def update_anchor(engine, obj, **changes):
    component = deepcopy(obj.component)
    component[BLOCK].update(changes)
    changed = obj.model_copy(update={'component':component})
    engine._update_object(changed,component['created_by'],obj.owner_id)
    return changed


COMPASS = ('N','NE','E','SE','S','SW','W','NW')
SENSE_RANGE_FT = 60


def bearing(origin, target):
    """Eight-point direction from origin to target on the table grid (north is smaller y)."""
    import math
    dx, dy = target.x - origin.x, target.y - origin.y
    if dx == 0 and dy == 0:
        return 'here'
    angle = (math.degrees(math.atan2(dx, -dy)) + 360) % 360
    return COMPASS[int((angle + 22.5) // 45) % 8]


def sense_report(engine, actor):
    """Read the Dragon Vein (CL3): presence and direction of features within 60 feet, from native geometry only.

    Mapping from native records: hollows/tunnels = material records tagged cave/tunnel/hollow; underground water =
    water material records; structural supports/weaknesses = structure objects (damaged = weakness); active formation
    anchors and portals = objects tagged formation_anchor/portal; spiritual pressure = qi-hazard cells; ley-line
    breaks = this creature's Vein Anchors that are suppressed (severed from the network); cultivated terrain effects =
    active placed zones touching the sensed area. Concealed effects needing a Source-CL check are not rolled here.
    """
    from ..object_rules import has_tag
    from . import placed
    engine_grid, origin = engine.grid, actor.position
    found = []

    def near(cell, z=None):
        point = Position(x=cell[0], y=cell[1], z=origin.z if z is None else z)
        return engine_grid.distance_ft(origin, point) <= SENSE_RANGE_FT

    def add(kind, cell, label, z=None):
        point = Position(x=cell[0], y=cell[1], z=origin.z if z is None else z)
        found.append({'kind': kind, 'direction': bearing(origin, point), 'label': label})

    for cell, records in sorted(engine_grid.material_regions.items()):
        if not near(cell):
            continue
        for row in records:
            if row['material'] in ('cave', 'tunnel', 'hollow') or str(row.get('terrain_type', '')).lower() in ('cave', 'tunnel', 'hollow'):
                add('hollow', cell, 'Hollow or tunnel')
            elif row['material'] == 'water':
                add('water', cell, 'Underground water')
    for cell in sorted(engine_grid.qi_hazard):
        if near(cell):
            add('pressure', cell, 'Significant unusual spiritual pressure')
    for obj in engine.state.objects.values():
        if obj.destroyed or obj.position is None or not near((obj.position.x, obj.position.y), obj.position.z):
            continue
        cell = (obj.position.x, obj.position.y)
        if has_tag(obj, 'structure'):
            weak = obj.current_hp is not None and obj.maximum_hp is not None and obj.current_hp < obj.maximum_hp
            add('weakness' if weak else 'support', cell, 'Major structural weakness' if weak else 'Major structural support')
        if has_tag(obj, 'formation_anchor') and not obj.suppressed:
            add('formation', cell, 'Active Formation Anchor')
        if obj.object_kind == 'portal' or (obj.component or {}).get('portal'):
            add('portal', cell, 'Active portal touching the surface')
    for anchor in anchors(engine, actor, active=False):
        if anchor.suppressed and near((anchor.position.x, anchor.position.y), anchor.position.z):
            add('ley_break', (anchor.position.x, anchor.position.y), 'Break in an active ley line', anchor.position.z)
    for zone in placed.of(engine):
        cells = [(c.x, c.y) for c in getattr(zone, 'affected_cells', ()) or ()]
        if cells and any(near(cell) for cell in cells):
            add('cultivated', cells[0], 'Cultivated effect altering the terrain')
    return found


@effect('dragon_vein_command')
def command(ctx, effect):
    engine, actor = ctx.engine,ctx.actor
    source = kit(engine,actor)
    if source is None:
        raise ValueError('This creature has not acquired Read the Dragon Vein.')
    kind = effect['command']
    if kind == 'allies':
        from ..relations import relation
        possible = [a for a in engine.state.actors.values() if relation(engine,actor,a) == 'ALLY']
        pick = choose(ctx,'allies',[a.entity_id for a in possible],labels={a.entity_id:a.display_name for a in possible},
            prompt='Choose allies who gain Grounding and Circuit benefits in your anchored ground. No action or Qi cost.',
            maximum=len(possible),minimum=0)
        store(engine,actor,{**state(actor),'allies':pick})
    elif kind == 'sense':
        if not stable(engine,actor.position):
            raise ValueError('Read the Dragon Vein requires touching a stable surface.')
        found = sense_report(engine,actor)
        store(engine,actor,{**state(actor),'sensed':found})
        if not found:
            note(engine,READ,actor,'Read the Dragon Vein: nothing unusual within 60 feet.')
        for row in found:
            note(engine,READ,actor,f"Read the Dragon Vein: {row['label']} to the {row['direction']}.")
    elif kind == 'place':
        p = ctx.intent.destination
        if p is None or not stable(engine,p) or engine.grid.distance_ft(actor.position,p) > 30:
            raise ValueError('Place a Vein Anchor on a stable surface within 30 feet.')
        mode = 'earth'
        if CIRCUIT in source['owned']:
            mode = choose(ctx,'place_mode',MODES,labels={m:m.title()+' Circuit' for m in MODES},
                prompt='Place Vein Anchor: choose its Circuit Mode. Action and 1 Qi; lasts 8 hours.')[0]
        # Imperial Anchors never count toward, or get destroyed by, the ordinary cap.
        live = [o for o in anchors(engine,actor,active=False) if 'field_id' not in o.component[BLOCK]]
        pb,cl = int(source['numbers']['pb']),int(source['numbers']['cl'])
        while len(live) >= pb:
            oldest = min(live,key=lambda o:o.component[BLOCK]['created_sequence'])
            engine._update_object(oldest.model_copy(update={'destroyed':True,'current_hp':0}),READ,actor.entity_id)
            live.remove(oldest)
        sequence = engine.state.event_sequence+1
        obj = RuntimeObjectState(object_id=f'object:vein:{actor.entity_id}:{sequence}',
            object_kind='vein_anchor',position=p,unattended=True,flammable=False,
            owner_id=actor.entity_id,ac=14,current_hp=2*cl,maximum_hp=2*cl,
            damage_immunities=('POISON','PSYCHIC'),destroyed=False,suppressed=False,
            component={'name':'Vein Anchor','size':'tiny','blocks':False,'cover':False,
                'source_cl':cl,'created_by':READ,BLOCK:{'mode':mode,'created_sequence':sequence,
                    'end_round':engine.state.round_number+4800,
                    'support':p.model_dump(mode='json')}})
        engine._update_object(obj,READ,actor.entity_id)
    elif kind == 'mode':
        eligible = [o for o in anchors(engine,actor,active=False)
                    if engine.grid.distance_ft(actor.position,o.position) <= 120]
        selected = choose(ctx,'mode_anchor',[o.object_id for o in eligible],
            labels={o.object_id:f'Vein Anchor at ({o.position.x}, {o.position.y})' for o in eligible},
            prompt='Ley-Line Circuit: change one Anchor within 120 feet. Free, once on your turn.')[0]
        mode = choose(ctx,'mode',MODES,labels={m:m.title()+' Circuit' for m in MODES},
                      prompt='Choose the new Circuit Mode.')[0]
        update_anchor(engine,engine.state.objects[selected],mode=mode)
        actor.turn_flags['geomancy_mode'] = True
    elif kind == 'network':
        eligible = [o for o in anchors(engine,actor) if engine.grid.distance_ft(actor.position,o.position) <= 120]
        awakened = choose(ctx,'awaken',[o.object_id for o in eligible],
            labels={o.object_id:f'Vein Anchor at ({o.position.x}, {o.position.y})' for o in eligible},
            prompt='Dragon-Vein Network: awaken any number of your active Anchors within 120 feet. Bonus Action and 5 Qi; lasts 1 minute.',
            maximum=len(eligible),minimum=0)
        store(engine,actor,{**state(actor),'awakened':awakened,'network_end_round':engine.state.round_number+10})
    elif kind == 'adjust':
        adjustment(ctx)
    elif kind == 'passage':
        passage(ctx)
    elif kind == 'imperial':
        imperial(ctx)


@hook('turn_start')
def anchor_clock(engine, actor):
    if kit(engine,actor) is None:
        return
    for obj in anchors(engine,actor,active=False):
        data = obj.component[BLOCK]
        if engine.state.round_number >= data['end_round'] or not stable(engine,obj.position):
            engine._update_object(obj.model_copy(update={'destroyed':True,'current_hp':0}),READ,actor.entity_id)


@hook('ac')
def metal(engine, actor):
    bonus = 1 if any('metal' in active for _,_,active in benefits(engine,actor)) else 0
    if harden_held(actor) is not None:
        bonus += 2
    return bonus or None


@hook('forced_movement_reduction')
def earth(ctx, subject):
    return max((10 if in_province(ctx.engine,o,subject.position) else 5
                for o,_,active in benefits(ctx.engine,subject) if 'earth' in active),default=0) or None


@hook('difficult_exempt')
def grounding(engine, actor):
    from ..motion import TerrainExemption
    from .grid_radius_cache import cells_in_radius
    cells = set()
    for owner,source,active in benefits(engine,actor):
        for obj in anchors(engine,owner):
            cells.update((p.x,p.y) for p in cells_in_radius(engine.grid,obj.position,radius(engine,owner,obj)//5))
    return TerrainExemption(cells,nonmagical_only=True) if cells else None


def claimed(engine, owner, position):
    return any(covers(engine,owner,o,position) for o in anchors(engine,owner))


def context(engine, owner, source, targets=()):
    from .states import context as make
    row = kit(engine,owner)
    ctx = make(engine,owner,source,list(targets),row['numbers']).with_source(source)
    ctx.intent = getattr(engine,'_active_intent',None)
    return ctx


def apply(ctx, target, rows):
    from ..typed_executor import run_effects
    run_effects(replace(ctx,targets=[target],target=target),rows)


PRINTED_NAMES = {'redirect_river': 'Redirect the River', 'harden_mountain': 'Harden the Mountain',
                 'feed_forest': 'Feed the Forest'}


def pick_ally(ctx, suffix, *, self_allowed=True):
    from ..relations import relation
    possible = [a for a in ctx.engine.state.actors.values() if a.active
                and relation(ctx.engine,ctx.actor,a) == 'ALLY'
                and (self_allowed or a is not ctx.actor) and claimed(ctx.engine,ctx.actor,a.position)]
    pick = choose(ctx,suffix,[a.entity_id for a in possible],labels={a.entity_id:a.display_name for a in possible},
        prompt='Choose an ally standing in your Claimed Ground for '+PRINTED_NAMES.get(suffix, 'this Dragon-Vein option')+'.')
    return ctx.engine.state.actors[pick[0]] if pick else None


def move_ally(ctx, target, feet, label, *, toward=None):
    from .rider_movement import routes,step
    choices = routes(ctx.engine,target,feet)
    choices = {key:path for key,path in choices.items()
               if (toward is None or all(claimed(ctx.engine,ctx.actor,p) for p in path))
               and (toward is None or ctx.engine.grid.distance_ft(path[-1],toward) < ctx.engine.grid.distance_ft(path[0],toward))}
    if not choices:
        return
    # The mover chooses, including declining. An allied relationship is never
    # used as evidence of willingness, including on another creature's AI turn.
    picked = choose(ctx,'move_'+label,choices,
        labels={key:f'Move to ({path[-1].x}, {path[-1].y})' for key,path in choices.items()},
        prompt=f'{label}: {target.display_name} may move up to {feet} feet without provoking Opportunity Attacks. Choose no movement to decline.',
        minimum=0,chooser=target)
    if picked:
        step(ctx.engine,target,choices[picked[0]],ctx.source)


def repair(ctx, dice):
    possible = anchors(ctx.engine,ctx.actor)
    picked = choose(ctx,'repair_anchor',[o.object_id for o in possible],
        labels={o.object_id:f'Vein Anchor at ({o.position.x}, {o.position.y}), {o.current_hp}/{o.maximum_hp} Hit Points' for o in possible},
        prompt=f'Repair one active Anchor for {dice}d8 plus your Qi key ability modifier Hit Points.')
    if not picked:
        return
    obj = ctx.engine.state.objects[picked[0]]
    from ..gate2_runtime_models import DiceSpec
    roll = ctx.engine.roller.roll(DiceSpec(count=dice,sides=8,modifier=int(ctx.numbers.get('key_mod',0))),
        actor_id=ctx.actor.entity_id,reason='Dragon-Vein Anchor repair')
    ctx.engine._record_roll(roll)
    ctx.engine._update_object(obj.model_copy(update={'current_hp':min(obj.maximum_hp,obj.current_hp+max(0,roll.total))}),ctx.source,ctx.actor.entity_id)


def adjustment(ctx):
    engine,actor = ctx.engine,ctx.actor
    if not network_active(engine,actor) or not claimed(engine,actor,actor.position) or actor.turn_flags.get('geomancy_adjust'):
        raise ValueError('Network Adjustment requires your active Network, your turn and your presence in Claimed Ground.')
    labels = {'redirect':'Redirect Flow — move yourself or a willing ally up to 10 feet',
              'reinforce':'Reinforce Meridian — one ally gains twice your Proficiency Bonus Temporary Hit Points',
              'momentum':'Increase Momentum — add 5 feet to one forced movement from your Qi-powered feature',
              'shift':'Shift the Anchor — move one Anchor along its stable surface up to 10 feet',
              'repair':'Stabilize the Circuit — one Anchor regains 2d8 plus your key modifier Hit Points'}
    selected = choose(ctx,'adjustment',labels,labels=labels,prompt='Dragon-Vein Network: choose your one free adjustment this turn.')[0]
    if selected in ('redirect','reinforce'):
        ally = pick_ally(ctx,'network_'+selected)
        if ally:
            if selected == 'redirect':
                move_ally(ctx,ally,10,'Redirect Flow')
            else:
                apply(ctx,ally,[{'type':'temp_hp','applies_to':'target','flat':2*int(ctx.numbers['pb'])}])
    elif selected == 'momentum':
        engine._apply_condition(actor,'condition:typed.geomancy_momentum',ctx.source,actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN',data={'label':'Increase Momentum: +5 feet to one Qi-powered forced movement'})
    elif selected == 'repair':
        repair(ctx,2)
    else:
        possible = anchors(engine,actor)
        picked = choose(ctx,'shift_anchor',[o.object_id for o in possible],
            labels={o.object_id:f'Vein Anchor at ({o.position.x}, {o.position.y})' for o in possible},
            prompt='Shift the Anchor: choose an unsecured Anchor; move it up to 10 feet along its stable supporting surface.')[0]
        obj = engine.state.objects[picked]
        from .needle import cell_id
        from .grid_radius_cache import cells_in_radius
        points = {cell_id(p):p for p in cells_in_radius(engine.grid,obj.position,2)
                  if stable(engine,p) and p != obj.position and surface_path(engine,obj.position,p,10)
                  and not any(p == a.position for a in engine.state.actors.values() if a.active)}
        choice = choose(ctx,'shift_destination',points,labels={key:f'Anchor at ({p.x}, {p.y})' for key,p in points.items()},
            prompt='Choose the Anchor’s new stable position within 10 feet.',minimum=0)
        if choice:
            engine._update_object(obj.model_copy(update={'position':points[choice[0]]}),ctx.source,actor.entity_id)
    actor.turn_flags['geomancy_adjust'] = True


@hook('forced_movement_bonus')
def momentum_bonus(ctx, subject, effect_row):
    # Increase Momentum: the next Qi-powered forced movement the geomancer causes gains 5 feet, then it is spent.
    # An ordinary (non-Qi) push or pull does not consume it.
    held = next((c for c in ctx.actor.conditions.values() if c.condition_id == 'condition:typed.geomancy_momentum'), None)
    if held is None or not _qi_powered(ctx):
        return None
    ctx.actor.conditions.pop(held.instance_id)
    ctx.engine._append_event('CONDITION_REMOVED', PREFIX+'increase_momentum', actor_id=ctx.actor.entity_id,
        target_ids=(ctx.actor.entity_id,), payload={'condition_id': held.condition_id, 'instance_id': held.instance_id, 'reason': 'CONSUMED'})
    return 5


def _qi_powered(ctx):
    typed = getattr(ctx, 'typed', None) or {}
    if type(typed.get('qi_powered')) is bool:
        return typed['qi_powered']
    source = str(typed.get('option_of') or typed.get('source') or '')
    costs = getattr(getattr(ctx, 'action', None), 'costs', ()) or ()
    return (any(pool == QI for pool, _ in costs)
            or source.startswith(('tianxia.subpath.qi.', 'tianxia.path.qi_cultivation.')))


def claimed_cells(engine, owner):
    """Every square inside one of the owner's active Anchor radii."""
    from .grid_radius_cache import cells_in_radius
    from .needle import cell_id
    out = {}
    for obj in anchors(engine, owner):
        for point in cells_in_radius(engine.grid, obj.position, radius(engine, owner, obj) // 5):
            out[cell_id(point)] = point
    return out


def hostiles_in_claimed(engine, owner):
    from ..relations import relation
    return [a for a in engine.state.actors.values() if a.active
            and relation(engine, owner, a) == 'ENEMY' and claimed(engine, owner, a.position)]


def harden_held(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == HARDEN), None)


def harden_save_held(actor):
    return next((c for c in actor.conditions.values() if c.condition_id == HARDEN_SAVE), None)


def _harden(ctx, ally):
    # Two conditions: the +2 AC lasts until the geomancer's next turn; the Advantage is spent by one save.
    ctx.engine._apply_condition(ally, HARDEN, ctx.source, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN',
        data={'label': 'Harden the Mountain: +2 AC until the start of your next turn', 'rule': {'ac': 2}})
    ctx.engine._apply_condition(ally, HARDEN_SAVE, ctx.source, ctx.actor.entity_id,
        expires_on='START_OF_SOURCE_NEXT_TURN',
        data={'label': 'Harden the Mountain: Advantage on the next save against forced movement',
              'rule': {'forced_movement_advantage': True}})


def _increase_gravity(ctx):
    engine, owner = ctx.engine, ctx.actor
    from . import placed
    cells = claimed_cells(engine, owner)
    if not cells:
        return
    picked = choose(ctx, 'gravity_centre', cells,
        labels={key: f'Area centred at ({point.x}, {point.y})' for key, point in cells.items()},
        prompt='Increase Gravity: choose the centre of a 15-foot area inside your Claimed Ground. '
               'Until the start of your next turn hostile creatures treat it as difficult terrain and a hostile '
               'entering or starting there makes a Strength save or falls Prone.')
    if not picked:
        return
    zone = placed.place(engine, owner, source=ctx.action.source_definition_id, tag='imperial_gravity',
        cells=cells[picked[0]], name='Increased Gravity - difficult ground for hostiles; Strength save or Prone',
        duration_rounds=1, difficult='hostile', shape='cylinder', size_ft=15, radial_volume=True)
    store(engine, owner, {**state(owner), 'gravity_fields': [*state(owner).get('gravity_fields', ()), zone.zone_id]})


def gravity_field_save(engine, owner, subject, *, at=None):
    """One Strength save per hostile per turn inside an owned Increase Gravity area."""
    from ..relations import relation
    from .. import zones as zone_api
    if kit(engine, owner) is None or relation(engine, owner, subject) != 'ENEMY':
        return
    for zone_id in state(owner).get('gravity_fields', ()):
        zone = engine.state.zones.get(zone_id)
        if zone is None or not zone.active or not zone_api.actor_inside_zone(engine, subject, zone, at or subject.position):
            continue
        mark = 'gravityfield:' + str(zone_id) + ':' + subject.entity_id
        data = state(owner)
        if data.get(mark) == turn_stamp(engine):
            continue
        ctx = context(engine, owner, IMPERIAL, [subject])
        dc = int(ctx.numbers['save_dc'])
        roll = engine._roll_save(subject, 'STR', dc, IMPERIAL, roll_context={'source_actor_id': owner.entity_id})
        store(engine, owner, {**data, mark: turn_stamp(engine)})
        if roll is None or roll.total < dc:
            apply(ctx, subject, [{'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}])
            note(engine, IMPERIAL, owner,
                 f'Increase Gravity: {subject.display_name} fails the Strength save and falls Prone.', (subject,))


def imperial_command(ctx):
    """Imperial Geomantic Command: two different Commands at the start of the owner's turn."""
    engine, owner = ctx.engine, ctx.actor
    picked = choose(ctx, 'imperial_command', COMMANDS, labels=COMMAND_LABELS, maximum=2, minimum=2,
        prompt='Imperial Dragon Vein: at the start of your turn choose two different Commands. '
               'They cost no action, Bonus Action or Qi. Each affects a creature or Anchor in your Claimed Ground.')
    for command in picked:
        if command == 'raise':
            _raise_road(ctx)
        elif command == 'redirect':
            ally = pick_ally(ctx, 'redirect_river')
            if ally:
                move_ally(ctx, ally, 15, 'Redirect the River')
        elif command == 'harden':
            ally = pick_ally(ctx, 'harden_mountain')
            if ally:
                _harden(ctx, ally)
        elif command == 'feed':
            ally = pick_ally(ctx, 'feed_forest')
            if ally:
                apply(ctx, ally, [{'type': 'healing', 'applies_to': 'target',
                                    'dice': {'count': 2, 'sides': 8}, 'formula': 'key_ability_modifier'}])
        elif command == 'ring':
            targets = hostiles_in_claimed(engine, owner)
            if targets:
                key = choose(ctx, 'ring_metal_vein', [a.entity_id for a in targets],
                    labels={a.entity_id: a.display_name for a in targets},
                    prompt='Ring the Metal Vein: choose one hostile creature in your Claimed Ground. '
                           'It makes a Dexterity save or takes 4d8 Slashing or Force damage and cannot take Reactions '
                           'until the start of its next turn.') 
                kind = choose(ctx, 'ring_damage', ['slashing', 'force'],
                    labels={'slashing': 'Slashing damage', 'force': 'Force damage'},
                    prompt='Ring the Metal Vein: choose Slashing or Force damage for the 4d8 on a failed save.') if key else None
                if key and kind:
                    apply(ctx, engine.state.actors[key[0]], [
                        {'type': 'save', 'applies_to': 'target', 'ability': 'dex', 'dc': int(ctx.numbers['save_dc']),
                         'on_fail': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 4, 'sides': 8},
                                      'damage_types': [kind[0]]},
                                     {'type': 'condition', 'condition': 'reaction_denied', 'applies_to': 'target',
                                      'expires_on': 'START_OF_TARGET_NEXT_TURN'}],
                         'on_success': [{'type': 'half_damage', 'applies_to': 'target',
                                         'damage_types': [kind[0]]}]}])
        elif command == 'gravity':
            _increase_gravity(ctx)
        elif command == 'repair':
            repair(ctx, 3)


def _raise_road(ctx):
    """Raise the Road places its 20x10 platform marker; walking support stays map geometry."""
    from . import placed
    engine, owner = ctx.engine, ctx.actor
    cells = claimed_cells(engine, owner) or {str(owner.position): owner.position}
    picked = choose(ctx, 'raised_road', cells,
        labels={key: f'Platform anchored at ({point.x}, {point.y})' for key, point in cells.items()},
        prompt='Raise the Road: choose where the 20-foot by 10-foot bridge, stair, ramp or platform is anchored. '
               'It lasts until the start of your next turn and supports 200 x your Qi Cultivation CL pounds.')
    if not picked:
        return
    placed.place(engine, owner, source=ctx.action.source_definition_id, tag='raised_road',
        cells=cells[picked[0]], name='Raised Road - 20 x 10 foot platform until your next turn',
        duration_rounds=1, terrain=['raised_road'], shape='cube', size_ft=20, difficult=None,
        placed={'length_ft': 20, 'width_ft': 10, 'capacity_lb': 200 * int(ctx.numbers['cl'])})


def dispersal(engine, owner):
    """Imperial Dispersal: one choice when the field ends."""
    ctx = context(engine, owner, IMPERIAL)
    picked = choose(ctx, 'imperial_dispersal', ['benevolent', 'quake'],
        labels={'benevolent': 'Benevolent Road - each willing ally inside the field may move up to 10 feet',
                'quake': 'Dragon Quake - each hostile you choose in Claimed Ground saves or takes 6d8 Force or Bludgeoning damage and falls Prone'},
        prompt='Imperial Dragon Vein ends: choose one Dispersal. Benevolent Road moves willing allies; '
               'Dragon Quake damages chosen hostiles in your Claimed Ground.')
    if not picked:
        return
    if picked[0] == 'benevolent':
        from ..relations import relation
        for ally in [a for a in engine.state.actors.values() if a.active
                     and relation(engine, owner, a) == 'ALLY'
                     and in_province(engine, owner, a.position)]:
            move_ally(ctx, ally, 10, 'Benevolent Road')
        return
    targets = hostiles_in_claimed(engine, owner)
    if not targets:
        return
    kind = choose(ctx, 'quake_damage', ['force', 'bludgeoning'],
        labels={'force': 'Force damage', 'bludgeoning': 'Bludgeoning damage'},
        prompt='Dragon Quake: choose Force or Bludgeoning damage for the 6d8 on a failed save.')
    if not kind:
        return
    chosen = choose(ctx, 'quake_targets', [a.entity_id for a in targets],
        labels={a.entity_id: a.display_name for a in targets},
        prompt='Dragon Quake: choose each hostile creature in your Claimed Ground that must make a Dexterity save. '
               'Failure: 6d8 Force or Bludgeoning damage and Prone. Success: half damage and it remains standing.',
        maximum=len(targets), minimum=0)
    for entity_id in chosen:
        apply(ctx, engine.state.actors[entity_id], [
            {'type': 'save', 'applies_to': 'target', 'ability': 'dex', 'dc': int(ctx.numbers['save_dc']),
             'on_fail': [{'type': 'damage', 'applies_to': 'target', 'dice': {'count': 6, 'sides': 8},
                          'damage_types': [kind[0]]},
                         {'type': 'condition', 'condition': 'prone', 'applies_to': 'target'}],
             'on_success': [{'type': 'half_damage', 'applies_to': 'target', 'damage_types': [kind[0]]}]}])


@hook('subject_teleport_attempt')
def seal_roads(ctx, subject, start, destination):
    """Seal the Roads: a hostile creature teleporting in, out or within the field saves or fails."""
    engine = ctx.engine
    from ..relations import relation
    for owner in engine.state.actors.values():
        source = kit(engine, owner)
        if source is None or IMPERIAL not in source['owned']:
            continue
        if subject.entity_id == owner.entity_id or relation(engine, owner, subject) != 'ENEMY':
            continue
        if province(engine, owner) is None:
            continue
        # Forced teleportation caused by the field's owner is exempt.
        if getattr(ctx, 'actor', None) is not None and ctx.actor.entity_id == owner.entity_id:
            continue
        if not (in_province(engine, owner, start) or in_province(engine, owner, destination)):
            continue
        local = context(engine, owner, IMPERIAL, [subject])
        dc = int(local.numbers['save_dc'])
        roll = engine._roll_save(subject, 'CHA', dc, IMPERIAL, roll_context={'source_actor_id': owner.entity_id})
        if roll is None or roll.total < dc:
            note(engine, IMPERIAL, owner,
                 f'Seal the Roads: {subject.display_name} fails the Charisma save, so the teleport fails; '
                 'its action and any Qi spent remain spent.', (subject,))
            return False
    return None


def passage_routes(engine, owner):
    live = anchors(engine,owner)
    result = {}
    from .grid_radius_cache import cells_in_radius
    for first in live:
        if engine.grid.distance_ft(owner.position,first.position) > 5:
            continue
        for second in live:
            if first is second or engine.grid.distance_ft(first.position,second.position) > 120 or not connected(engine,owner,first,second):
                continue
            for p in cells_in_radius(engine.grid,second.position,1):
                if p == second.position or p == owner.position or not stable(engine,p):
                    continue
                if engine.grid.placement_legal(p,footprint=engine._footprint(owner),occupied_cells=engine._occupied_cells_except(owner.entity_id)):
                    key = f'{first.object_id}|{second.object_id}|{p.x},{p.y},{p.z}'
                    result[key] = (first,second,p)
    return result


def traveler_cells(engine, owner, traveler, destination):
    """Unoccupied legal squares adjacent to the geomancer's arrival square."""
    from .grid_radius_cache import cells_in_radius
    from .needle import cell_id
    blocked = set(engine._occupied_cells_except(traveler.entity_id)) | set(engine._actor_volume(owner, destination))
    return {cell_id(point): point for point in cells_in_radius(engine.grid, destination, 1)
            if point != destination and (point.x, point.y, point.z) not in blocked
            and engine.grid.placement_legal(point, footprint=engine._footprint(traveler), occupied_cells=blocked)}


def passage(ctx):
    engine,owner = ctx.engine,ctx.actor
    routes = passage_routes(engine,owner)
    if not routes or owner.turn_flags.get('geomancy_passage'):
        raise ValueError('No legal Dragon-Road Passage route exists; no Qi is spent.')
    chosen = choose(ctx,'passage',routes,labels={key:f'Vein Anchor to ({p.x}, {p.y})' for key,(_,_,p) in routes.items()},
        prompt='Dragon-Road Passage: choose a Connected Anchor and unoccupied adjacent destination within 120 feet.')[0]
    _,second,p = routes[chosen]
    in_field = province(engine,owner) is not None
    cost = 0 if in_field else 2
    carry_cost = 1 if in_field else 2
    if owner.resources.get(QI,0) < cost:
        raise ValueError('Dragon-Road Passage requires 2 Qi (free once per turn while Imperial Dragon Road is active).')
    carry = None
    if owner.resources.get(QI,0) >= cost + carry_cost:
        possible = [a for a in engine.state.actors.values() if a.active and a is not owner
                    and engine.grid.distance_ft(owner.position,a.position) <= 5]
        if possible:
            picked = choose(ctx,'passage_traveler',[a.entity_id for a in possible],
                labels={a.entity_id:a.display_name for a in possible},
                prompt=f'Dragon-Road Passage: carry one willing creature within reach? '
                       f'That costs {carry_cost} additional Qi and it must fit in an unoccupied space beside your arrival.',
                minimum=0,maximum=1,default='decline')
            if picked:
                traveler = engine.state.actors[picked[0]]
                consent = choose(ctx,'passage_traveler_consent',[traveler.entity_id],
                    labels={traveler.entity_id:f'Yes - travel with {owner.display_name}'},chooser=traveler,
                    minimum=0,maximum=1,default='decline',
                    prompt=f'{owner.display_name} offers to carry you through Dragon-Road Passage. '
                           f'Travel with them? This uses their Bonus Action and Qi.')
                if consent:
                    cells = traveler_cells(engine,owner,traveler,p)
                    if cells:
                        landing = choose(ctx,'passage_traveler_destination',cells,
                            labels={key:f'Arrive at ({point.x}, {point.y})' for key,point in cells.items()},
                            prompt='Choose the unoccupied space beside your arrival where the carried creature lands.')[0]
                        carry = (traveler,cells[landing])
    from ..typed_executor import teleport_subject
    engine._spend_resource(owner,QI,cost+(carry_cost if carry else 0),ctx.source)
    owner.turn_flags['geomancy_passage'] = True
    teleport_subject(ctx,owner,p)
    if carry is not None and owner.position == p:
        teleport_subject(ctx,carry[0],carry[1])


def imperial(ctx):
    # The field is an ordinary concentration-linked native placement. Its
    # anchors reference that one field identity and never count toward PB.
    engine,owner = ctx.engine,ctx.actor
    center = ctx.intent.destination
    if state(owner).get('imperial_spent'):
        raise ValueError('Imperial Dragon Vein has already been used this scene.')
    from . import placed
    points = imperial_points(engine,center)
    selected = []
    for index in range(IMPERIAL_ANCHORS):
        available = {key:p for key,p in points.items()
                     if all(engine.grid.distance_ft(p,old) >= IMPERIAL_SPACING_FT for old in selected)}
        # Offer only spaces that still leave a full legal set for the remaining anchors.
        available = {key:p for key,p in available.items() if can_place_anchors(engine,
            [q for k,q in available.items() if k != key and engine.grid.distance_ft(p,q) >= IMPERIAL_SPACING_FT],
            IMPERIAL_ANCHORS-index-1)}
        if not available:
            raise ValueError('Imperial Dragon Vein requires five unoccupied stable spaces at least 15 feet apart.')
        picked = choose(ctx,'imperial_anchor_'+str(index),available,
            labels={key:f'Imperial Anchor at ({p.x}, {p.y})' for key,p in available.items()},
            prompt=f'Imperial Dragon Vein: place Anchor {index+1} of {IMPERIAL_ANCHORS}; every pair must be at least 15 feet apart.')[0]
        selected.append(available[picked])
    zone = placed.place(engine,owner,source=ctx.action.source_definition_id,tag='imperial_vein',
        cells=center,name='Imperial Dragon Vein — Concentration, 1 minute',
        duration_rounds=10,concentration=True,shape='cylinder',size_ft=60,
        placed={'height_ft':60},radial_volume=True)
    cl,pb = int(ctx.numbers['cl']),int(ctx.numbers['pb'])
    for p in selected:
        sequence = engine.state.event_sequence+1
        obj = RuntimeObjectState(object_id=f'object:imperial_vein:{owner.entity_id}:{sequence}',
            object_kind='imperial_vein_anchor',position=p,unattended=True,flammable=False,
            owner_id=owner.entity_id,ac=16,current_hp=4*cl,maximum_hp=4*cl,
            damage_threshold=pb,damage_immunities=('POISON','PSYCHIC'),destroyed=False,suppressed=False,
            component={'name':'Imperial Vein Anchor','size':'small','blocks':False,
                'source_cl':cl,'created_by':IMPERIAL,'resist':['BLUDGEONING','PIERCING','SLASHING'],
                BLOCK:{'mode':'earth','created_sequence':sequence,'end_round':engine.state.round_number+10,
                       'field_id':zone.zone_id,'support':p.model_dump(mode='json')}})
        engine._update_object(obj,IMPERIAL,owner.entity_id)
    store(engine,owner,{**state(owner),'imperial_spent':1,'field_id':zone.zone_id})
    engine._start_concentration(owner,ctx.action.source_definition_id)


@hook('event', nested=True)
def field_ended(engine, event_type, kwargs):
    """Imperial Dispersal: the field's ZONE_REMOVED is the one printed trigger."""
    if event_type != 'ZONE_REMOVED':
        return
    zone_id = (kwargs.get('payload') or {}).get('zone_id')
    if not zone_id:
        return
    for owner in list(engine.state.actors.values()):
        source = kit(engine, owner)
        if source is None or IMPERIAL not in source['owned']:
            continue
        data = state(owner)
        if data.get('field_id') != zone_id:
            continue
        store(engine, owner, {**data, 'field_id': None, 'dispersing': zone_id})
        try:
            dispersal(engine, owner)
        finally:
            store(engine, owner, {**state(owner), 'dispersing': None})
        # The field's Imperial Anchors are retired with it, not merely left inert.
        for obj in list(engine.state.objects.values()):
            if obj.owner_id == owner.entity_id and not obj.destroyed and (obj.component or {}).get(BLOCK, {}).get('field_id') == zone_id:
                engine._update_object(obj.model_copy(update={'destroyed': True, 'current_hp': 0}), IMPERIAL, owner.entity_id)


def turn_stamp(engine):
    return str(engine.state.round_number)+':'+str(engine.state.current_actor_id)


@hook('movement_step_surcharge')
def gravity_movement_surcharge(engine, actor, mode):
    """Gravity Circuit makes hostile walking through an active gravity Anchor cost an extra square."""
    if mode != 'walk':
        return None
    from ..relations import relation
    for owner in engine.state.actors.values():
        if kit(engine, owner) is None or relation(engine, owner, actor) != 'ENEMY':
            continue
        if any('gravity' in modes(engine, owner, anchor) and covers(engine, owner, anchor, actor.position)
               for anchor in anchors(engine, owner)):
            return engine.grid.square_size_ft
    return None


def gravity(engine, owner, subject, *, entering=False, at=None):
    from ..relations import relation
    if relation(engine,owner,subject) != 'ENEMY':
        return
    over = [o for o in anchors(engine,owner) if covers(engine,owner,o,at or subject.position)
            and 'gravity' in modes(engine,owner,o)]
    if not over:
        return
    awakened = network_active(engine,owner) and any(o.object_id in state(owner).get('awakened',()) for o in over)
    if not entering and not awakened:
        return
    data = state(owner)
    mark = 'gravity:'+subject.entity_id
    if data.get(mark) == turn_stamp(engine):
        return
    ctx = context(engine,owner,NETWORK if awakened else CIRCUIT,[subject])
    dc = int(ctx.numbers['save_dc'])
    roll = engine._roll_save(subject,'STR',dc,ctx.source,
        roll_context={'source_actor_id':owner.entity_id})
    failed = roll is not None and roll.total < dc
    loss = 15 if awakened and failed else 5 if awakened else 10 if failed else 0
    if loss:
        apply(ctx,subject,[{'type':'speed','applies_to':'target','amount':-loss,'duration':'until_start_of_next_turn'}])
    if awakened and failed:
        engine._apply_condition(subject,'condition:typed.geomancy_no_dash',ctx.source,owner.entity_id,
            expires_on='START_OF_TARGET_NEXT_TURN',data={'label':'Gravity Circuit: cannot Dash until your next turn',
                                                       'rule':{'no_dash':True}})
    store(engine,owner,{**state(owner),mark:turn_stamp(engine)})


@hook('turn_start_choice')
def start_benefits(engine, subject):
    contributions = benefits(engine,subject)
    wood = [(o,r) for o,r,m in contributions if 'wood' in m]
    if wood:
        owner,row = max(wood,key=lambda x:int(x[1]['numbers']['pb']))
        key = f'once_per_round:geomancy_wood:{engine.state.round_number}'
        if not subject.turn_flags.get(key):
            apply(context(engine,owner,CIRCUIT,[subject]),subject,
                  [{'type':'temp_hp','applies_to':'target','flat':int(row['numbers']['pb'])}])
            subject.turn_flags[key] = True
    for owner in engine.state.actors.values():
        row = kit(engine,owner)
        if row is None:
            continue
        gravity(engine,owner,subject)
        gravity_field_save(engine,owner,subject)
        ctx = context(engine,owner,NETWORK,[subject])
        if subject.entity_id in state(owner).get('allies',()) and claimed(engine,owner,subject.position):
            if in_province(engine,owner,subject.position):
                move_ally(ctx,subject,5,'Claimed Province')
            elif network_active(engine,owner):
                eligible = [o for o in anchors(engine,owner) if o.object_id in state(owner).get('awakened',())
                            and engine.grid.distance_ft(subject.position,o.position) > 0]
                selected = choose(ctx,'dragon_road_anchor',[o.object_id for o in eligible],
                    labels={o.object_id:f'Toward Anchor at ({o.position.x}, {o.position.y})' for o in eligible},
                    prompt=f'Dragon Road Movement: {subject.display_name} may move up to 10 feet toward another awakened Anchor, staying in Claimed Ground. No Opportunity Attacks.',
                    chooser=subject,minimum=0)
                if selected:
                    move_ally(ctx,subject,10,'Dragon Road Movement',toward=engine.state.objects[selected[0]].position)


@hook('turn_start_choice')
def imperial_command_start(engine, subject):
    """Imperial Geomantic Command at the start of the geomancer's own turn."""
    source = kit(engine, subject)
    if source is None or IMPERIAL not in source['owned'] or province(engine, subject) is None:
        return
    if engine.state.current_actor_id not in (None, subject.entity_id):
        return
    if getattr(engine, '_active_intent', None) is None:
        return  # no accepted action: never choose for a player during fresh-engine setup
    imperial_command(context(engine, subject, IMPERIAL))


@hook('save')
def earth_save(ctx, subject, ability, named):
    if not ({'prone','forced_movement'} & set(named)):
        return None
    held = harden_save_held(subject)
    if held is not None and 'forced_movement' in set(named):
        subject.conditions.pop(held.instance_id,None)
        ctx.engine._append_event('CONDITION_REMOVED', IMPERIAL, actor_id=ctx.actor.entity_id,
            target_ids=(subject.entity_id,), payload={'condition_id': held.condition_id,
            'instance_id': held.instance_id, 'reason': 'CONSUMED'})
        return {'modes':['ADVANTAGE']}
    if any('earth' in active for _,_,active in benefits(ctx.engine,subject)):
        return {'modes':['ADVANTAGE']}


@hook('event',nested=True)
def entered(engine, event_type, kwargs):
    if event_type != 'MOVEMENT_COMMITTED':
        return
    aid = kwargs.get('actor_id')
    subject = engine.state.actors.get(aid)
    if subject is None:
        return
    path = [Position.model_validate(cell) for cell in ((kwargs.get('payload') or {}).get('path') or ())]
    if len(path) < 2:
        return
    # Every square entered, in order: a creature passing through a radius or area is affected even
    # when its final square lies outside it.
    steps = list(zip(path, path[1:]))
    for owner in list(engine.state.actors.values()):
        if kit(engine,owner) is None:
            continue
        for previous, cell in steps:
            over = [o for o in anchors(engine,owner) if covers(engine,owner,o,cell)
                    and not covers(engine,owner,o,previous)]
            gravity_field_save(engine,owner,subject,at=cell)
            if not over:
                continue
            gravity(engine,owner,subject,entering=True,at=cell)
            if subject.entity_id not in state(owner).get('allies',()):
                continue
            _water_entry(engine,owner,subject,over)


def _water_entry(engine, owner, subject, over):
    if not any('water' in modes(engine,owner,o) for o in over):
        return
    # Once per creature per turn, across every geomancer covering it.
    key, stamp = 'water:'+subject.entity_id, turn_stamp(engine)
    spent = any(state(o).get(key) == stamp for o in engine.state.actors.values() if kit(engine,o) is not None)
    if spent:
        return
    data = state(owner)
    store(engine,owner,{**data,key:stamp})
    move_ally(context(engine,owner,CIRCUIT,[subject]),subject,5,'Water Circuit')
