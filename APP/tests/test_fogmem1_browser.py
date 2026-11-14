"""Lead-only Chromium composition check; never enabled by the sandbox lane."""
import io
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get('FOGMEM1_BROWSER') != '1',
                    reason='lead must run FOGMEM1_BROWSER=1 outside the sandbox')
def test_maple_last_seen_canopy(tmp_path, monkeypatch):
    pw = pytest.importorskip('playwright.sync_api')
    Image = pytest.importorskip('PIL.Image')
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    static = Path(__file__).resolve().parents[1] / 'static' / 'tabletop'
    html = '''<link rel="stylesheet" href="/tabletop.css"><style>
    body{margin:0}#host{width:256px;height:128px;position:relative}
    .tt-board{transform:none!important;width:256px!important;height:128px!important}
    </style><div id="host"></div><script type="module">
    import {createBoard} from '/board.js';
    const board=createBoard(document.querySelector('#host'));
    const map={width:4,height:2,background:{style:'grass_autumn',seed:6401},
      display:{gridOpacity:1,gridColor:'#00ffff'},walls:[],
      trees:[{x:2,y:1,look:'maple',size:2,seed:7043}],decor:[],ruleTerrain:[],
      cells:{blocked:[],cover:[],hazard:[],difficult:[],sightGhost:[]}};
    board.setMap(map);
    const cells={};
    for(const x of [1,2,3])cells[4+x]={floor:board.floorRecordAt(x,1),
      scenery:board.sceneryRecordAt(x,1),terrain:[],zones:[],objects:[],
      tokens:x===2?[{name:'Ding Shanlan'}]:[]};
    // Rebuild saved ground after a zone vanished. Today's trees are unchanged.
    const seen=new Uint8Array(8);seen[0]=1;
    const explored=new Uint8Array(8);for(const i of [0,5,6,7])explored[i]=1;
    board.setFog(seen,explored,{squareFog:true},explored.slice());
    board.setRemembered({cells:JSON.parse(JSON.stringify(cells)),ghosts:[5,6,7],changed:[5,6,7],width:4});
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
            page = browser.new_page(viewport={'width': 256, 'height': 128}, device_scale_factor=1)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('http://fogmem1.test/**', serve)
            page.goto('http://fogmem1.test/')
            page.wait_for_function('window.ready === true')
            assert not errors, errors
            assert page.locator('.tt-remembered-mark').inner_text() == 'DS'
            assert page.locator('.tt-remembered-scenery').count() == 3
            assert page.locator('.tt-remembered-tile, .tt-remembered-scenery').evaluate_all(
                "els=>els.every(el=>getComputedStyle(el).stroke==='none')")
            png = page.locator('.tt-board').screenshot()
            image = Image.open(io.BytesIO(png)).convert('RGB')
            for x in (1, 2):
                colors = list(image.crop((x*64+8, 72, x*64+56, 120)).getdata())
                assert sum(r > g*1.3 and r > b*1.6 for r, g, b in colors) > 80
            # The diagnostic cyan grid must not trace any remembered tile.
            assert not any(g > r+60 and b > r+60 for r, g, b in image.crop((126, 65, 130, 127)).getdata())
            output = Path(os.environ.get('FOGMEM1_SCREENSHOT_DIR', str(tmp_path)))
            output.mkdir(parents=True, exist_ok=True)
            (output / 'fogmem1-maple-memory.png').write_bytes(png)
        finally:
            browser.close()
