"""Lead-only Chromium pixels and full-size before/after fog paint timings."""
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get('FOGLOOK_BROWSER') != '1',
                   reason='lead runs FOGLOOK_BROWSER=1 outside the sandbox')
def test_foglook_chromium_pixels_and_biggest_map(tmp_path, monkeypatch, capsys):
    pw = pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    app = Path(__file__).resolve().parents[1]
    static = app / 'static/tabletop'
    source = (static / 'board.js').read_text()
    start = source.index('  function setFog(')
    body = source[start:source.index('\n  }', start) + 4]
    # Compare to actual main, not a source replacement that could silently stop
    # bypassing a renamed helper. The benchmark prints the baseline commit.
    main = subprocess.check_output(['git', 'show', 'main:APP/static/tabletop/board.js'], cwd=app, text=True)
    baseline = subprocess.check_output(['git', 'rev-parse', 'main'], cwd=app, text=True).strip()
    main_start = main.index('  function setFog(')
    before = main[main_start:main.index('\n  }', main_start) + 4]
    maps = [json.loads(p.read_text()) for p in (app / 'combat/maps').glob('*.json')]
    biggest = max(maps, key=lambda m: m.get('width_squares', 0)*m.get('height_squares', 0))
    html = '''<link rel="stylesheet" href="/tabletop.css"><script type="module">
import {paintFogMask, fogTokenCells, roofPresentationPolygons, blockerSegments, visibilityPolygons} from '/fog_polygon.js';
import {createBoard} from '/board.js';
import {softFogCut, fogPresentationCut} from '/fog_presentation.js';
const make = (body, width, height) => {
 const fog=document.createElement('canvas'); fog.width=width*64;fog.height=height*64;
 const names=['fog','map','CELL','document','tokens','setRoofView','zoneMask','zoneClouds','gridSvg','openRoofCells',
  'closedRoofTops','roofPresentationPolygons','paintFogMask','fogTokenCells','softFogCut','fogPresentationCut'];
 const values=[fog,{width,height},64,document,new Map(),()=>{},()=> 'none',{style:{}},{style:{}},new Set(),new Map(),
  roofPresentationPolygons,paintFogMask,fogTokenCells,softFogCut,fogPresentationCut];
 const setFog=new Function(...names, 'let zoneSeen;'+body+';return setFog;')(...values);
 return {fog,draw:(geometry,explored=null)=>setFog(new Uint8Array(width*height),explored,geometry)};
};
window.check=(body)=>{
 const r=make(body,8,6), rect=(l,r)=>({points:[[l,0],[r,0],[r,6],[l,6]]});
 r.draw({polygons:[rect(0,3),rect(2,6)]});
 const c=r.fog.getContext('2d'), a=c.getImageData(0,0,512,384).data;
 const at=x=>a[(192*512+x)*4+3];
 const gradient=Array.from({length:128},(_,i)=>at(320+i)).filter(a=>a>24 && a<214).length;
 const edge=at(383), hidden=at(400), rgb=Array.from(a.slice((192*512+400)*4,(192*512+400)*4+3));
 r.draw({polygons:[rect(0,6)]});
 const b=c.getImageData(0,0,512,384).data;
 const same=a.every((v,i)=>v===b[i]);
 const host=document.createElement('div');document.body.append(host);
 const board=createBoard(host);
 board.setMap({width:8,height:6,background:{url:null,style:'flagstone',seed:1},display:{},walls:[],trees:[],
  ruleTerrain:[],cells:{blocked:[],cover:[],hazard:[],difficult:[],sightGhost:[]}});
 board.setTokens([{id:'unseen',x:7,y:3,hidden:true}]);
 const hiddenTokens=[...host.querySelectorAll('.tt-token')].filter(n=>getComputedStyle(n).display!=='none').length;
 return {gradient,edge,hidden,rgb,same,hiddenTokens,lit:at(340)};
};
window.bench=(body,map,changed=false)=>{
 const width=map.width_squares,height=map.height_squares,r=make(body,width,height);
 const geometry={polygons:visibilityPolygons([{x:2.5,y:2.5}],
  blockerSegments({walls:map.walls,trees:map.trees,width,height}),width,height)};
 const explored=new Uint8Array(width*height);
 const states=Array.from({length:7},(_,i)=>({polygons:visibilityPolygons([{x:2.5+i*0.2,y:2.5}],
  blockerSegments({walls:map.walls,trees:map.trees,width,height}),width,height)}));
 r.draw(geometry,explored);
 const samples=[];
 for(let i=0;i<7;i++) {const t=performance.now();r.draw(changed?states[i]:geometry,explored);
  // Readback forces raster completion, including filter work.
  r.fog.getContext('2d').getImageData(0,0,r.fog.width,r.fog.height);
  samples.push(performance.now()-t);}
 return samples.sort((a,b)=>a-b)[3];
};
window.ready=true;
</script>'''

    def serve(route):
        name = urlparse(route.request.url).path.lstrip('/')
        if not name:
            route.fulfill(body=html, content_type='text/html')
        elif (static / name).is_file() and name.endswith(('.js', '.css')):
            route.fulfill(path=str(static / name), content_type='text/css' if name.endswith('.css') else 'text/javascript')
        else:
            route.abort()

    with pw.sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.route('http://foglook.test/**', serve)
            page.goto('http://foglook.test/')
            page.wait_for_function('window.ready === true')
            pixels = page.evaluate('(body)=>window.check(body)', body)
            assert 64 * 0.25 <= pixels['gradient'] <= 64 * 0.4, pixels
            assert 85 < pixels['edge'] < 150 and pixels['hidden'] > 230, pixels
            assert pixels['lit'] == 0, pixels
            assert any(pixels['rgb']), pixels
            assert pixels['same'] and pixels['hiddenTokens'] == 0, pixels
            for changed in (False, True):
                before_ms = page.evaluate('([body,map,changed])=>bench(body,map,changed)', [before, biggest, changed])
                after_ms = page.evaluate('([body,map,changed])=>bench(body,map,changed)', [body, biggest, changed])
                with capsys.disabled():
                    print(f"FOGLOOK3 main={baseline} {biggest['map_id']} {biggest['width_squares']}x{biggest['height_squares']} "
                          f"{'changed' if changed else 'cached'} median paint+readback main={before_ms:.2f}ms "
                          f"round3={after_ms:.2f}ms ratio={after_ms/before_ms:.2f}", flush=True)
        finally:
            browser.close()
