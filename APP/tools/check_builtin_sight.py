#!/usr/bin/env python3
"""Audit builtin map art -> bound sight -> thin markers, in both directions.

Run from APP: python tools/check_builtin_sight.py [--json]. No browser, fight,
service or model is started. Size policy lives in scenery-sight.json. Ordinary
look-only decor (including potted bonsai) is low/small decorative foliage;
object presets explicitly declaring blocks=False are open furniture, not walls.

This audit reads only the current checkout. To compare a historical map
compiler against today's art manifest use tools/check_builtin_sight_history.py,
which is the only place that reads a past revision out of Git.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_content import AN, LEE
from combat.scenery_sight import bamboo_culms, bamboo_groups, plant_blocks_sight, terrain_occluder, tree_trunks, trunk_cross, terrain_blocks_sight
from combat.tabletop import BAMBOO, normalize_map, to_battlefield, wall_cells
from combat.map_openings import placed_wall_cells
from combat.terrain_occlusion import sight_geometry
from combat.sight_lines import cross_segments, source
from combat.object_geometry import target_cells
from combat import object_rules


def segment_key(segment, scale=100):
    # Integer input; canonical hundredths permit comparison to legacy scale=2.
    return tuple(sorted(tuple(round(n*100/scale) for n in p) for p in segment))


def art_sources(document):
    """Inventory physical art independently of the arena's emitted regions."""
    out = []
    for i, tree in enumerate(document['trees']):
        for j, p in enumerate(tree_trunks(tree)):
            if plant_blocks_sight(p, tree['height_ft']):
                out.append((f'tree {i+1} trunk {j+1}', trunk_cross(p)))
    for i, row in enumerate(document['materials']):
        if row['material'] != BAMBOO:
            continue
        for group in bamboo_groups(row['cells']):
            for j,p in enumerate(bamboo_culms(group['x'], group['y'], group['size'])):
                if plant_blocks_sight(p, row['height_ft']):
                    out.append((f'bamboo {i+1} at {group["x"]},{group["y"]} stalk {j+1}', trunk_cross(p)))
    for i,row in enumerate(document['terrain']):
        if not terrain_blocks_sight(row):
            continue
        for x,y in row['cells']:
            if row.get('look') == 'bamboo_clump':
                for j,p in enumerate(bamboo_culms(x,y,clump=True,rotation=row.get('rotation',0))):
                    if plant_blocks_sight(p,row['height_ft']):
                        out.append((f'cover bamboo {i+1} at {x},{y} stalk {j+1}', trunk_cross(p)))
            else:
                # A tall scenery square is seen through the shared centre plus (owner 2026-10-23; the
                # same answer combat/scenery_sight.py gives the fight), unless its look fills the square.
                if terrain_occluder(row) == 'cell':
                    out.append((f'tall terrain {i+1} at {x},{y}',
                        [[[x*100,(y*100+50)],[(x+1)*100,y*100+50]],
                         [[x*100,y*100],[x*100,(y+1)*100]],
                         [[(x+1)*100,y*100],[(x+1)*100,(y+1)*100]]]))
                else:
                    out.append((f'tall terrain {i+1} at {x},{y}',
                        [[[n*50 for n in p] for p in s] for s in cross_segments([(x,y)])]))
    return out


def audit_maps(root=APP/'combat/maps', *, compiler=to_battlefield):
    results, payload = [], []
    for path in sorted(root.glob('*.json')):
        doc = normalize_map(json.loads(path.read_text()))
        arena = compiler(doc)
        # Construct an in-memory engine through normal match_start providers,
        # so destructible doors/furniture are included by their real plug-in.
        initial_grid=SquareGrid(arena)
        occupied={(r['x']+dx,r['y']+dy) for r in arena['map_objects']
                  for dx in range(max(r.get('width_cells',1),r.get('length_cells',1)))
                  for dy in range(max(r.get('width_cells',1),r.get('length_cells',1)))}
        free=[{'x':x,'y':y} for y in range(initial_grid.height) for x in range(initial_grid.width)
              if (x,y) not in initial_grid.blocked|initial_grid.opaque|occupied]
        engine = Gate4ControllerEngine(APP,match_seed='BUILTIN-SIGHT-CHECK',battlefield=arena,
            roster_setup={'primary_actor_ids':[AN,LEE],'starting_positions':dict(zip((AN,LEE),free[:2]))})
        geometry = sight_geometry(engine.grid)
        expected = art_sources(doc)
        for wall in doc['walls']:
            if wall.get('height_ft',1)==0:
                continue
            cells=placed_wall_cells(wall,doc,wall_cells)
            # A round scenery wall is resolved to the centre plus (combat/tabletop.py wall_sight_class);
            # a wall keeps its centre runs and end caps.
            plus = wall.get('occluder') == 'centerline'
            row = source(cells,'BLOCKED',segments=cross_segments(cells)) if plus else source(cells,'BLOCKED')
            expected.append(('wall '+wall['id'], [
                [[n*50 for n in p] for p in s] for s in row['segments']]))
        object_cells = set()
        for obj in engine.state.objects.values():
            cells=[(p.x,p.y) for p in target_cells(engine,obj)]
            object_cells.update(cells)
            if (obj.component or {}).get('blocks') and obj.height_ft != 0:
                # Placed objects take their sight shape from combat/object_rules.py sight (owner 2026-10-23).
                sight = object_rules.sight((obj.component or {}).get('kind') or obj.object_kind)
                row = (source(cells,'BLOCKED',segments=cross_segments(cells)) if sight['occluder'] == 'centerline'
                       else source(cells,'BLOCKED'))
                expected.append(('object '+obj.object_id, [
                    [[n*50 for n in p] for p in s] for s in row['segments']]))
        segments = {segment_key(s,row.get('scale',2)) for row in geometry['lines']
                    if row['top_ft'] is None or row['top_ft']>row['bottom_ft'] for s in row['segments']}
        for v in geometry['volumes']:
            if v['mode']=='centerline' and (v['top_ft'] is None or v['top_ft']>v['bottom_ft']):
                x,y=v['x'],v['y']
                segments.update(segment_key(s) for s in trunk_cross({'x':x*100+50,'y':y*100+50,'r':50}))
        missing = [name for name,segs in expected if not all(segment_key(s) in segments for s in segs)]
        art_cells = {c for wall in doc['walls'] for c in placed_wall_cells(wall,doc,wall_cells)}
        art_cells.update((t['x']+dx,t['y']+dy) for t in doc['trees'] for dx in range(t['size']) for dy in range(t['size']))
        art_cells.update(tuple(c) for r in doc['materials'] if r['material']==BAMBOO for c in r['cells'])
        art_cells.update(tuple(c) for r in doc['terrain'] for c in r['cells'])
        art_cells.update(object_cells)
        # For explicit segments, check exact geometry in reverse too: an extra
        # authored cross inside a valid art cell is still an orphan. Every
        # expected item (plants, scenery plus, wall/object rows) is art here.
        art_keys={segment_key(s) for _,segs in expected for s in segs}
        phantom_segments=[segment_key(s,row['scale']) for row in geometry['lines'] if 'scale' in row
                          for s in row['segments'] if segment_key(s,row['scale']) not in art_keys]
        orphans = sorted({(v['x'],v['y']) for v in geometry['volumes'] if (v['x'],v['y']) not in art_cells})
        results.append({'map':path.stem,'art_without_geometry':len(missing),
                        'geometry_without_art':len(orphans)+len(phantom_segments),'geometry_without_marker':0,
                        'missing':missing,'orphans':orphans,'phantom_segments':phantom_segments})
        payload.append({'geometry':geometry,'segments':list(segments), 'map':{
            'width':doc['width_squares'],'height':doc['height_squares'],
            'walls':doc['walls'],'objects':doc['objects'],'background':doc['background'],
            'floors':arena['tabletop']['floors'],'roofs':doc.get('roofs') or {}}})
    # Exercise production marker builder, not a second drawing implementation.
    probe = subprocess.run(['node','--input-type=module','-e',"""
import {readFileSync} from 'node:fs';
import {sightBlockerLines} from './static/tabletop/los-lines.js';
import {surfaceEdges} from './static/tabletop/sight-lines.js';
import {detectRoofRegions,roofSettings} from './static/tabletop/roof-regions.js';
const key=s=>JSON.stringify(s.map(p=>p.map(n=>Math.round(n*100))).sort((a,b)=>a[0]-b[0] || a[1]-b[1]));
console.log(JSON.stringify(JSON.parse(readFileSync(0,'utf8')).map(({geometry,segments,map})=>{
 const drawn=new Set(sightBlockerLines({sources:geometry.lines},[],geometry).map(l=>key([l.a,l.b])));
 const holes=new Set((map.roofs.openings || []).filter(o=>o.open===true || o.kind==='skylight').map(o=>o.x+','+o.y));
 const roofArt=new Set(detectRoofRegions(map).filter(r=>roofSettings(r,map.roofs).enabled)
   .flatMap(r=>r.footprint.map(c=>c.join(','))).filter(c=>!holes.has(c)));
 const roofGeometry=new Set(geometry.roofs.map(r=>r.x+','+r.y));
 return {unmarked:segments.filter(s=>!drawn.has(JSON.stringify(s))).length
   +surfaceEdges(geometry.roofs).filter(s=>!drawn.has(key(s))).length,
   roofOrphans:[...roofGeometry].filter(c=>!roofArt.has(c)).length,
   roofMissing:[...roofArt].filter(c=>!roofGeometry.has(c)).length};
})));
"""],cwd=APP,input=json.dumps(payload),text=True,capture_output=True,timeout=60)
    if probe.returncode:
        raise RuntimeError(probe.stderr)
    for result,counts in zip(results,json.loads(probe.stdout)):
        result['geometry_without_marker']=counts['unmarked']
        result['geometry_without_art']+=counts['roofOrphans']
        result['art_without_geometry']+=counts['roofMissing']
        result['roof_without_geometry']=counts['roofMissing']
        result['roof_without_art']=counts['roofOrphans']
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json',action='store_true')
    args=parser.parse_args()
    return report(audit_maps(compiler=to_battlefield), args.json)


def report(results, as_json=False):
    """Print one audit result per map (JSON when AS_JSON) and return its exit code."""
    if as_json:
        print(json.dumps(results,indent=2))
    else:
        for r in results:
            print(f"{r['map']}: art_without_geometry={r['art_without_geometry']} geometry_without_art={r['geometry_without_art']} geometry_without_marker={r['geometry_without_marker']}")
            for name in r['missing']:
                print('  missing: '+name)
            for cell in r['orphans']:
                print('  orphan: '+str(cell))
    return int(any(r[k] for r in results for k in ('art_without_geometry','geometry_without_art','geometry_without_marker')))


if __name__=='__main__':
    raise SystemExit(main())
