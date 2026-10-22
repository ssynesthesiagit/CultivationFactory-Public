"""Opt-in Chromium compositor gate. Lead runs outside the sandbox."""
import io
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get('FOGGREY3_BROWSER') != '1',
                    reason='lead must run FOGGREY3_BROWSER=1 outside the sandbox')
def test_remembered_tree_and_object_art_without_grid(tmp_path, monkeypatch):
    pw = pytest.importorskip('playwright.sync_api')
    Image = pytest.importorskip('PIL.Image')
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    static = Path(__file__).resolve().parents[1] / 'static' / 'tabletop'
    html = '''<link rel="stylesheet" href="/tabletop.css"><style>
    body{margin:0}#host{width:384px;height:256px;position:relative}
    .tt-board{transform:none!important;width:384px!important;height:256px!important}
    </style><div id="host"></div><script type="module">
    import {createBoard} from '/board.js';
    const board=createBoard(document.querySelector('#host'));
    const map={width:6,height:4,background:{style:'snow',seed:31},display:{gridOpacity:1,gridColor:'#ff00ff'},
      walls:[],trees:[{x:2,y:1,size:1,look:'snowy_pine',seed:2}],decor:[],ruleTerrain:[],
      cells:{blocked:[],cover:[],hazard:[],difficult:[],sightGhost:[]}};
    board.setMap(map);
    const cells={};
    for(const x of [2,3]) cells[6+x]={floor:board.floorRecordAt(x,1),scenery:board.sceneryRecordAt(x,1),
      tokens:x===2?[{name:'Bandit'}]:[],objects:x===3?[{kind:'chest',name:'Chest'}]:[]};
    // JSON round trip models persistence. Today's scene no longer has the tree.
    const saved=JSON.parse(JSON.stringify(cells));
    board.setMap({...map,trees:[]});
    board.setTokens([{id:'hidden-bandit',name:'Hidden Bandit',x:3,y:1,hp:10,maxHp:10,hidden:true}]);
    const seen=new Uint8Array(24);seen[0]=1;
    const explored=new Uint8Array(24);for(const i of [0,8,9])explored[i]=1;
    board.setFog(seen,explored,{squareFog:true},explored.slice());
    board.setRemembered({cells:saved,ghosts:[8,9],changed:[8,9],width:6});
    await Promise.all([...document.querySelectorAll('.tt-remembered-floor')].map(async el=>{
      const image=new Image();image.src=el.getAttribute('href');await image.decode();
    }));
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    window.ready=true;
    </script>'''

    def serve(route):
        name = urlparse(route.request.url).path.lstrip('/')
        if not name:
            route.fulfill(body=html, content_type='text/html')
        elif '/' not in name and (static / name).is_file():
            route.fulfill(path=str(static / name), content_type='text/css' if name.endswith('.css') else 'text/javascript')
        else:
            route.abort()

    with pw.sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': 384, 'height': 256}, device_scale_factor=1)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('http://foggrey3.test/**', serve)
            page.goto('http://foggrey3.test/')
            page.wait_for_function('window.ready === true')
            assert not errors, errors
            image = Image.open(io.BytesIO(page.locator('.tt-board').screenshot())).convert('RGB')
            for x in (2, 3):
                colors = list(image.crop((x*64+8, 72, x*64+56, 120)).getdata())
                assert len(set(colors)) > 100
                assert sum(g > r + 12 for r, g, b in colors) > 20
            assert not any(r > 100 and b > 100 and g < 70 for r, g, b in image.crop((190, 64, 194, 128)).getdata()), 'remembered grid must be absent'
            assert page.locator('.tt-remembered-mark').inner_text() == 'BA'
            assert page.locator('.tt-token.is-hidden').count() == 1
            assert not page.locator('.tt-token.is-hidden').is_visible()
        finally:
            browser.close()


@pytest.mark.skipif(os.environ.get('FOGGREY3_SCRATCH') != '1',
                    reason='lead opts into scratch :8799 screenshots outside the sandbox')
def test_scratch_fight_seeded_memory(tmp_path, capsys):
    """Read-only fight repro; modifies only a new browser context's storage."""
    pw = pytest.importorskip('playwright.sync_api')
    app = Path(__file__).resolve().parents[1]
    static = app / 'static' / 'tabletop'
    origin = 'http://127.0.0.1:8799'
    script = (app.parent / 'fix' / 'FOGGREY3.seed.js').read_text()
    output = Path(os.environ.get('FOGGREY3_SCREENSHOT_DIR', str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)

    def patched_static(route):
        name = urlparse(route.request.url).path.removeprefix('/static/tabletop/')
        path = static / name
        if '/' not in name and path.is_file():
            route.fulfill(path=str(path), content_type='text/css' if name.endswith('.css') else 'text/javascript')
        else:
            route.continue_()

    def read_only_api(route):
        if route.request.method in ('GET', 'HEAD'):
            route.continue_()
        else:
            # A copied fight may have automated seats enabled. Even a normal
            # page bootstrap must not submit an auto-step during this repro.
            route.abort()

    with pw.sync_playwright() as p:
        browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page(viewport={'width': 1400, 'height': 1000})
            page.route(origin + '/static/tabletop/**', patched_static)
            page.route(origin + '/api/**', read_only_api)
            page.goto(origin + '/tabletop')
            url = page.evaluate(script)
            page.goto(origin + url)
            page.wait_for_function("document.querySelectorAll('.tt-remembered-scenery').length > 0", timeout=30000)
            page.wait_for_function("!document.body.classList.contains('is-viewer-pending')")
            page.locator('.tt-board').screenshot(path=str(output / 'foggrey3-frozen-lake.png'))
            with capsys.disabled():
                print('FOGGREY3 scratch screenshot:', output / 'foggrey3-frozen-lake.png')
        finally:
            browser.close()
