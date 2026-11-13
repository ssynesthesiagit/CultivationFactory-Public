"""Lead-only native canvas/PNG verification; never launch a GUI in the lane sandbox."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading

import pytest


@pytest.mark.skipif(os.environ.get("CF_REMEMBERED_GROUND_BROWSER") != "1",
                    reason="lead must set CF_REMEMBERED_GROUND_BROWSER=1 outside the sandbox")
def test_native_remembered_ground_pixels():
    from playwright.sync_api import sync_playwright

    static = Path(__file__).resolve().parents[2] / "APP/static"

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(static)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
            try:
                page = browser.new_page()
                base = f"http://127.0.0.1:{server.server_port}"
                page.goto(base + "/tabletop/tabletop.css")
                page.set_content(f'<link rel="stylesheet" href="{base}/themes.css">'
                                 f'<link rel="stylesheet" href="{base}/tabletop/tabletop.css">'
                                 '<body class="tt-app"><div id="host"></div></body>')
                result = page.evaluate("""async base => {
                  const {createBoard} = await import(base + '/tabletop/board.js');
                  const {paintFloor} = await import(base + '/tabletop/textures.js');
                  const board = createBoard(document.querySelector('#host'));
                  const map = {width:4, height:2, walls:[], trees:[], display:{},
                    cells:{blocked:[],cover:[],hazard:[],difficult:[],sightGhost:[]}, ruleTerrain:[]};
                  const decode = async href => {
                    const image = new Image(); image.src = href; await image.decode();
                    const canvas = document.createElement('canvas'); canvas.width=canvas.height=16;
                    const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0);
                    return Array.from(ctx.getImageData(0,0,16,16).data);
                  };
                  const raw = (style, x, y) => {
                    const source=paintFloor(style,1,4,2,{patch:true}), pps=source.width/4;
                    const canvas=document.createElement('canvas');canvas.width=canvas.height=16;
                    canvas.getContext('2d').drawImage(source,x*pps,y*pps,pps,pps,0,0,16,16);
                    return canvas.toDataURL();
                  };
                  board.setMap({...map,background:{style:'flagstone',seed:1},floors:[{style:'wood',cells:[[2,1]]}]});
                  const border=await decode(board.floorRecordAt(2,1).swatch), bareWood=await decode(raw('wood',2,1));
                  board.setMap({...map,display:{blend:1},background:{style:'grass',seed:1},floors:[{style:'sand',cells:[[2,1]]}]});
                  const blend=await decode(board.floorRecordAt(2,1).swatch), bareSand=await decode(raw('sand',2,1));
                  const neighbor=!!board.floorRecordAt(1,0).swatch;
                  board.setMap({...map,display:{blend:1},background:{style:'plain'},floors:[{style:'sand',cells:[[2,1]]}]});
                  const saved=board.floorRecordAt(2,1), pixels=await decode(saved.swatch);
                  const serialized=JSON.stringify({floor:saved,terrain:[],zones:[],tokens:[],objects:[]});
                  board.setMap({...map,background:{style:'wood'},floors:[]});
                  board.setRemembered({cells:{6:JSON.parse(serialized)},ghosts:[6],changed:[6],width:4});
                  const frozen=await decode(board.element.querySelector('.tt-remembered-floor').getAttribute('href'));
                  return {borderDiff:JSON.stringify(border)!==JSON.stringify(bareWood),
                    blendDiff:JSON.stringify(blend)!==JSON.stringify(bareSand), neighbor,
                    opaque:pixels.every((v,i)=>i%4!==3||v===255),
                    frozen:JSON.stringify(pixels)===JSON.stringify(frozen), bytes:serialized.length};
                }""", base)
                print("NATIVE PNG RESULT", result)
                assert all(result[name] for name in ["borderDiff", "blendDiff", "neighbor", "opaque", "frozen"])
                assert result["bytes"] < 2000
                uploaded = page.evaluate("""async base => {
                  const {createBoard} = await import(base + '/tabletop/board.js');
                  const host = document.createElement('div'); document.body.appendChild(host);
                  const board = createBoard(host);
                  const source = document.createElement('canvas'); source.width=4; source.height=2;
                  const src = source.getContext('2d'); src.fillStyle='#ef39c0'; src.fillRect(0,0,4,2);
                  const background = {url: source.toDataURL(), fit:'stretch', seed:1};
                  const map = {width:4,height:2,walls:[],trees:[],display:{},background,
                    cells:{blocked:[],cover:[],hazard:[],difficult:[],sightGhost:[]},ruleTerrain:[]};
                  const water = {floor:'shallows',terrain:'DIFFICULT',look:'roots',
                    area:[[0,0],[3,0],[3,2],[0,2]]};
                  const walk = {floor:'wood',area:[[1,0],[2,0],[2,2],[1,2]]};
                  const pixels = async record => {
                    const image = new Image(); image.src=record.swatch; await image.decode();
                    const c=document.createElement('canvas'); c.width=c.height=16;
                    const ctx=c.getContext('2d'); ctx.drawImage(image,0,0);
                    return Array.from(ctx.getImageData(0,0,16,16).data);
                  };
                  board.setMap({...map,features:[water,walk]});
                  await board.element.querySelector('.tt-bg-image').decode();
                  const canvas=board.element.querySelector('.tt-bg-floor');
                  const visible=!canvas.hidden && canvas.previousElementSibling.classList.contains('tt-bg-image');
                  const waterRecord=board.floorRecordAt(0,0), walkRecord=board.floorRecordAt(1,0), bareRecord=board.floorRecordAt(3,0);
                  const waterPixels=await pixels(waterRecord), walkPixels=await pixels(walkRecord), barePixels=await pixels(bareRecord);
                  const scatter=!!board.element.querySelector('mask polygon');
                  board.setMap({...map,features:[water]});
                  const withoutWalk=await pixels(board.floorRecordAt(1,0));
                  board.setMap({...map,features:[]});
                  const hidden=canvas.hidden;
                  board.setRemembered({cells:{1:{floor:walkRecord,terrain:[],zones:[],tokens:[],objects:[]}},ghosts:[1],changed:[1],width:4});
                  const frozen=await pixels({swatch:board.element.querySelector('.tt-remembered-floor').getAttribute('href')});
                  return {visible,scatter,hidden,water:JSON.stringify(waterPixels)!==JSON.stringify(barePixels),
                    walk:JSON.stringify(walkPixels)!==JSON.stringify(withoutWalk),
                    frozen:JSON.stringify(frozen)===JSON.stringify(walkPixels)};
                }""", base)
                print("UPLOADED FEATURE RESULT", uploaded)
                assert all(uploaded.values())
                saved = page.evaluate("""async base => {
                  const {createFogMemoryStore,indexedMemoryBackend}=await import(base+'/tabletop/fog_memory_store.js');
                  const key='tt-fog-memory:native-quota:viewer:80x60';
                  const swatch=document.querySelector('.tt-remembered-floor').getAttribute('href');
                  const old={version:3,cells:{0:{floor:{swatch},tokens:[{id:'old-goblin'}],objects:[{id:'old-chest'}]}}};
                  localStorage.setItem(key,JSON.stringify(old));
                  const storage={getItem:k=>localStorage.getItem(k),setItem:(k,v)=>{
                    if(v.length>4096)throw new DOMException('test quota','QuotaExceededError');
                    localStorage.setItem(k,v);
                  }};
                  const store=createFogMemoryStore({storage,backend:indexedMemoryBackend(indexedDB)});
                  await store.flush(key);
                  const next={version:3,cells:{...store.read(key).cells}};
                  for(let i=1;i<4800;i++)next.cells[i]={floor:{swatch},tokens:[{id:'seen-'+i}],objects:[]};
                  let quotaRejected=false;
                  try{storage.setItem(key,JSON.stringify(next));}catch(e){quotaRejected=e.name==='QuotaExceededError';}
                  store.save(key,next);await store.flush(key);
                  return {key,swatch,quotaRejected,bytes:JSON.stringify(next).length};
                }""", base)
                assert saved["quotaRejected"] and saved["bytes"] > 4096
                page.reload()
                reloaded = page.evaluate("""async ({base,key,swatch}) => {
                  const {createFogMemoryStore,indexedMemoryBackend}=await import(base+'/tabletop/fog_memory_store.js');
                  const store=createFogMemoryStore({storage:localStorage,backend:indexedMemoryBackend(indexedDB)});
                  await store.flush(key);const memory=store.read(key);
                  return {count:Object.keys(memory.cells).length,
                    pixels:Object.values(memory.cells).every(cell=>cell.floor.swatch===swatch),
                    unseen:memory.cells[0].tokens[0].id==='old-goblin'&&memory.cells[0].objects[0].id==='old-chest'};
                }""", {"base": base, "key": saved["key"], "swatch": saved["swatch"]})
                print("NATIVE PERSISTENCE RESULT", reloaded, "bytes", saved["bytes"])
                assert reloaded == {"count": 4800, "pixels": True, "unseen": True}
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
