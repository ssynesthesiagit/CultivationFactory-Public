// Lead-only visual acceptance. Never launch in the worker sandbox.
// SOL219_BROWSER=1 SOL219_PLAYWRIGHT_MODULES=/path/to/node_modules node --test --test-isolation=none static/tabletop/roofs.browser.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {readFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {resolve, sep, join} from 'node:path';
import {fileURLToPath} from 'node:url';

const enabled = process.env.SOL219_BROWSER === '1';
test('roof outside/inside/GM contact sheets using the production board', {skip: !enabled}, async()=>{
  const root = fileURLToPath(new URL('../../',import.meta.url));
  const require = createRequire(process.env.SOL219_PLAYWRIGHT_MODULES ? join(process.env.SOL219_PLAYWRIGHT_MODULES,'noop.js') : import.meta.url);
  const {chromium} = require('playwright');
  const out = process.env.SOL219_BROWSER_OUT || '/var/tmp/auto-audit/fix/SOL219-evidence/browser';
  await mkdir(out,{recursive:true});
  const server = createServer(async(req,res)=>{
    const url = new URL(req.url,'http://localhost');
    if (url.pathname==='/scene') {
      res.setHeader('Content-Type','text/html');
      res.end(`<!doctype html><link rel="stylesheet" href="/static/tabletop/tabletop.css?v=rel6-2">
        <style>body{margin:0;background:#171b21}#view{width:1400px;height:950px}h3{color:#eee;font:18px sans-serif}</style>
        <h3 id="label"></h3><div id="view"></div><script type="module">
        import {createBoard} from '/static/tabletop/board.js?v=rel6-2';
        import {detectRoofRegions} from '/static/tabletop/roof-regions.js?v=rel6-2';
        import {fogViewers} from '/static/tabletop/fog_view.js?v=ocf6';
        import {perceivedCells,tokenHiddenByFog} from '/static/tabletop/vision.js?v=rel6-2';
        window.loadScene=async name=>{
          const d=await(await fetch('/combat/maps/'+name+'.json')).json();
          const map={...d,width:d.width_squares,height:d.height_squares,
            floors:d.materials.filter(r=>r.material.startsWith('floor:')).map(r=>({style:r.material.slice(6),cells:r.cells}))};
          document.querySelector('#view').replaceChildren();
          window.board=createBoard(document.querySelector('#view'));board.setMap(map);board.fit();
          const region=detectRoofRegions(map)[0];window.inside=region?{x:region.x,y:region.y}:{x:10,y:10};
          board.setTokens(d.objects.map(o=>({...o,id:'prop-'+o.id,object:true,hp:o.hp||27,maxHp:o.hp||27})).concat([
            {id:'fighter',...inside,name:'Inside creature',label:'IN',hp:10,maxHp:10},
            {id:'unseen',x:inside.x+1,y:inside.y,name:'Hidden creature',label:'H',hp:10,maxHp:10,hidden:true}]));
          window.sceneView=mode=>{
            // Closed view is a spectator outside the building; Jade occupies its
            // whole map, so its outside observer is intentionally off-map here.
            const owner={entity_id:'owner',position:mode==='inside'?inside:{x:-2,y:-2},active:true};
            const otherSeat={entity_id:'other-seat',position:inside,active:true};
            const viewers=fogViewers('own',[owner,otherSeat],{owned:[owner]});
            const perception={owner:{cells:[[inside.x,inside.y]],creatures:['fighter']},
              'other-seat':{cells:[],creatures:[]}};
            const seen=perceivedCells(map.width,map.height,viewers,perception);
            board.setTokens(d.objects.map(o=>({...o,id:'prop-'+o.id,object:true,hp:o.hp||27,maxHp:o.hp||27})).concat([
              {id:'fighter',...inside,name:'Perceived creature',label:'IN',hp:10,maxHp:10,
                hidden:tokenHiddenByFog({entity_id:'fighter'},viewers,perception,mode!=='gm')},
              {id:'unseen',x:inside.x+1,y:inside.y,name:'Hidden creature',label:'H',hp:10,maxHp:10,
                hidden:tokenHiddenByFog({entity_id:'unseen'},viewers,perception,mode!=='gm')}]));
            // A real non-null fog mask exercises perceived tokens above roofs.
            // The second creature remains unperceived even when the roof fades.
            board.setFog(mode==='gm'?null:seen,null,{squareFog:true});
            board.setRoofView({viewers,gm:mode==='gm',enabled:mode!=='off',seen:mode==='gm'?null:seen});
            document.querySelector('#label').textContent=name+' — '+mode;
          };return detectRoofRegions(map).length;
        };window.ready=true;</script>`);
      return;
    }
    const file=resolve(root,'.'+decodeURIComponent(url.pathname));
    if (!file.startsWith(resolve(root)+sep)) {res.writeHead(404);res.end();return;}
    try {
      const data=await readFile(file);
      res.setHeader('Content-Type',file.endsWith('.html')?'text/html':file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'application/json');res.end(data);
    } catch {res.writeHead(404);res.end();}
  });
  let browser;
  try {
    await new Promise(r=>server.listen(0,'127.0.0.1',r));
    browser=await chromium.launch({headless:true,executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
    const page=await browser.newPage({viewport:{width:1400,height:1000}});
    const errors=[];page.on('pageerror',e=>errors.push(String(e)));
    await page.goto('http://127.0.0.1:'+server.address().port+'/scene');
    await page.waitForFunction(()=>window.ready);
    for (const [name,count] of [['builtin-willow-village-compound',5],['builtin-jade-sutra-hall',1],
      ['builtin-emerald-canopy',0],['builtin-cloudwater-crossing',0],['builtin-mist-courtyard',0]]) {
      assert.equal(await page.evaluate(name=>loadScene(name),name),count);
      for (const mode of ['outside','inside','gm','off']) {
        await page.evaluate(mode=>sceneView(mode),mode);
        await page.waitForTimeout(230);
        const values=await page.locator('[data-roof]').evaluateAll(nodes=>nodes.map(n=>Number(getComputedStyle(n).opacity)));
        if (count) assert.equal(values[0],mode==='inside'||mode==='off'?0:mode==='gm'?.28:1);
        assert.equal(await page.locator('.tt-token.is-hidden').count(),mode==='gm'?0:1);
        if(count && mode==='outside') {
          assert.equal(await page.evaluate(()=>board.tokenNode('fighter').parentElement.classList.contains('tt-roof-interior')),false);
          assert.equal(await page.evaluate(()=>board.tokenNode('unseen').classList.contains('is-hidden')),true);
        }
        await page.screenshot({path:join(out,name+'-'+mode+'.png')});
      }
    }
    // Height hover acceptance (lead only, outside the sandbox).
    await page.evaluate(async()=>{await loadScene('builtin-willow-village-compound');board.setTokens([]);});
    const point=await page.evaluate(()=>{
      const box=board.viewport.getBoundingClientRect(),v=board.view;
      return {x:box.left+v.x+(4+.5)*48*v.zoom,y:box.top+v.y+(4+.5)*48*v.zoom};
    });
    await page.mouse.move(point.x,point.y);
    await page.waitForFunction(()=>document.querySelector('.tt-zone-tip')?.textContent.includes('Roof · 15 ft'));
    assert.match(await page.locator('.tt-zone-tip').textContent(),/Building · 10 ft high/);
    // Actual editor entry point: save/reopen independent roof fields and heights.
    const original=JSON.parse(await readFile(join(root,'combat/maps/builtin-willow-village-compound.json'),'utf8'));
    let saved=original;
    await page.route('**/api/**',async route=>{
      const path=new URL(route.request().url()).pathname;
      let body;
      if(path==='/api/session') body={token:'roof-browser-test'};
      else if(path==='/api/tabletop/terrains') body={terrains:[],ground:{}};
      else if(path==='/api/tabletop/maps' && route.request().method()==='POST') {
        saved={...route.request().postDataJSON().map,map_id:'roof-copy'};body=saved;
      } else if(path==='/api/tabletop/maps') body={maps:[],builtin:[],object_defaults:{presets:{},groups:{},materials:{},sizes:{}}};
      else if(path==='/api/tabletop/maps/roof-copy') body=saved;
      else throw Error('Unexpected editor API '+path);
      await route.fulfill({json:body});
    });
    await page.goto('http://127.0.0.1:'+server.address().port+'/static/tabletop/mapeditor.html');
    await page.waitForFunction(()=>window.mapEditor);
    await page.evaluate(()=>window.mapEditor.open('map:roof-copy'));
    await page.selectOption('#meRoofBuilding','all');await page.uncheck('#meRoofEnabled');
    await page.selectOption('#meRoofBuilding','30,5');await page.selectOption('#meRoofStyle','red');
    await page.evaluate(async()=>{await window.mapEditor.save();await window.mapEditor.open('map:roof-copy');});
    assert.deepEqual(saved.roofs.regions.find(r=>r.x===30),{x:30,y:5,style:'red'});
    await page.selectOption('#meRoofBuilding','all');await page.check('#meRoofEnabled');
    await page.selectOption('#meRoofBuilding','15,4');await page.uncheck('#meRoofEnabled');await page.check('#meRoofEnabled');
    await page.evaluate(async()=>{await window.mapEditor.save();await window.mapEditor.open('map:roof-copy');});
    assert.deepEqual(saved.roofs.regions.find(r=>r.x===15),{x:15,y:4,enabled:true});
    await page.selectOption('#meRoofBuilding','all');await page.selectOption('#meRoofStyle','red');
    await page.evaluate(async()=>{await window.mapEditor.save();await window.mapEditor.open('map:roof-copy');});
    await page.selectOption('#meRoofBuilding','15,4');
    assert.equal(await page.inputValue('#meRoofStyle'),'red');
    await page.locator('.me-wall-height').first().fill('23');
    await page.locator('.me-wall-height').first().dispatchEvent('change');
    await page.selectOption('#meRoofBuilding','4,4');
    await page.fill('#meBuildingHeight','20');await page.locator('#meBuildingHeight').dispatchEvent('change');
    await page.fill('#meRoofHeight','32');await page.locator('#meRoofHeight').dispatchEvent('change');
    await page.evaluate(async()=>{await window.mapEditor.save();await window.mapEditor.open('map:roof-copy');});
    await page.selectOption('#meRoofBuilding','4,4');
    assert.equal(await page.inputValue('#meBuildingHeight'),'20');
    assert.equal(await page.inputValue('#meRoofHeight'),'32');
    assert.equal(saved.walls[0].height_ft,23);
    await page.screenshot({path:join(out,'editor-inherited-overrides.png')});
    assert.deepEqual(errors,[]);
  } finally {await browser?.close();await new Promise(r=>server.close(r));}
});
