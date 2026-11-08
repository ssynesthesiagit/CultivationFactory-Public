"""Opt-in canvas pixel check. The lead runs this outside the sandbox."""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get('RUN_FOGALT_BROWSER_TESTS') != '1',
                   reason='lead must run RUN_FOGALT_BROWSER_TESTS=1 outside the sandbox')
def test_80ft_continuous_fog_canvas_pixels(tmp_path, monkeypatch):
    playwright=pytest.importorskip('playwright.sync_api')
    monkeypatch.setenv('TMPDIR',str(tmp_path))
    static=Path(__file__).resolve().parents[1]/'static/tabletop'
    html='''<canvas id="fog" width="768" height="512"></canvas><script type="module">
import {altitudeVisibilityPolygons} from '/fog-altitude.js';
import {paintFogMask,fogPointVisible} from '/fog_polygon.js';
const eye={entity_id:'eye',position:{x:1.5,y:3.5,z:16}};
const geometry={volumes:[{x:4,y:3,bottom_ft:0,top_ft:15,mode:'cell',solid:true}],
  roofs:[{x:6,y:2,top_ft:23},{x:7,y:2,top_ft:23}]};
const p=altitudeVisibilityPolygons([eye],geometry,12,8);
const c=document.querySelector('canvas').getContext('2d');
paintFogMask(c,12,8,[],{polygons:p});
window.pixel=(x,y)=>c.getImageData(Math.floor(x*64),Math.floor(y*64),1,1).data[3];
window.draw=(geometry,viewer=eye,width=12)=>{
  c.canvas.width=width*64;c.canvas.height=512;
  const polygons=altitudeVisibilityPolygons([viewer],geometry,width,8);
  paintFogMask(c,width,8,[],{polygons});
  return (x,y)=>fogPointVisible(x,y,width,8,[],polygons);
};
window.crossCheck=()=>{
  const row={x:10,y:3,mode:'centerline',bottom_ft:0,top_ft:8};
  const visible=draw({volumes:[row]},eye,14);
  return {blocked:visible(11.5,3.5),alpha:pixel(11.5,3.5),
    beside:pixel(11.5,3.5+2/64),beyond:pixel(13.5,3.5)};
};
window.exclusiveTopCheck=()=>{
  // Same 8-ft exclusive top at both cross arms, touched diagonally.
  // Use a taller canvas so the exact review case fits inside the board.
  c.canvas.height=768;
  const viewer={position:{x:1.5,y:1.5,z:16}};
  const polygons=altitudeVisibilityPolygons([viewer],
    {volumes:[{x:10,y:10,mode:'centerline',bottom_ft:0,top_ft:8}]},12,12);
  paintFogMask(c,12,12,[],{polygons});
  return {visible:fogPointVisible(11.5,11.5,12,12,[],polygons),alpha:pixel(11.5,11.5)};
};
window.lineCheck=(scale)=>{
  c.canvas.width=12*scale;c.canvas.height=12*scale;
  const shadow=Object.assign([[3.5,2.5],[3.5,7.5]],{closed:true,openEnds:true});
  const plane={points:[[0,0],[12,0],[12,12],[0,12]],shadows:[shadow]};
  const at=(x,y)=>c.getImageData(Math.floor(x*scale),Math.floor(y*scale),1,1).data[3];
  paintFogMask(c,12,12,[],{polygons:[plane]},scale);
  const result={blocked:at(3.5,4.5),beside:at(3.5+2/scale,4.5),
    start:at(3.5,2.5),end:at(3.5,7.5)};
  // A second viewer and service-authorized tokens still union visibility.
  paintFogMask(c,12,12,[],{polygons:[{...plane,shadows:[]}]},scale);
  result.ally=at(3.5,4.5);
  c.clearRect(0,0,c.canvas.width,c.canvas.height);
  paintFogMask(c,12,12,[],{polygons:[plane],tokenCells:[[3,4]]},scale);
  result.token=at(3.5,4.5);
  return result;
};
window.vegetationCheck=()=>{
  c.canvas.width=c.canvas.height=16*64;
  const polygons=altitudeVisibilityPolygons([{position:{x:1.5,y:1.5,z:8}}],{
    volumes:[{x:4,y:4,mode:'centerline',bottom_ft:0,top_ft:25}],
    treeCells:['4,4'],trees:[{x:4,y:4,size:1}],roofs:[]},16,16);
  paintFogMask(c,16,16,[],{polygons});
  return [pixel(7.5,4.5),pixel(8.5,8.5),pixel(12.5,12.5)];
};
window.ready=true;
</script>'''
    def serve(route):
        name=urlparse(route.request.url).path.lstrip('/')
        if not name:
            route.fulfill(body=html,content_type='text/html')
        elif name in {'fog-altitude.js','fog_polygon.js'}:
            route.fulfill(path=str(static/name),content_type='text/javascript')
        else:
            route.abort()
    with playwright.sync_playwright() as p:
        browser=p.chromium.launch(executable_path='/usr/bin/chromium',args=['--no-sandbox'])
        try:
            page=browser.new_page()
            page.route('http://fogalt.test/**',serve)
            page.goto('http://fogalt.test/')
            page.wait_for_function('window.ready === true')
            assert page.evaluate('pixel(5.1,3.5)')==0
            assert page.evaluate('pixel(9.5,3.5)')==255
            assert page.evaluate('pixel(5.5,5.5)')==255  # clear around the wall corner
            assert page.evaluate('pixel(4.5,3.5)')==255
            assert page.evaluate('pixel(6.5,2.5)')==255
            assert page.evaluate('pixel(7.5,2.5)')==255
            assert page.evaluate('crossCheck()')=={
                'blocked':False,'alpha':0,'beside':255,'beyond':255}
            assert page.evaluate('exclusiveTopCheck()')=={'visible':True,'alpha':255}
            for scale in (32,64,96):
                assert page.evaluate('(scale)=>lineCheck(scale)',scale)=={
                    'blocked':0,'beside':255,'start':255,'end':255,'ally':255,'token':255}
            assert page.evaluate('vegetationCheck()')==[255,0,255]
        finally:
            browser.close()
