"""FOGGREY real Chromium compositor check; lead runs outside the sandbox."""
import io
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


# Kept separate so the replacement stimulus can also be checked without a GUI.
REPLACE_UNSEEN_JS = """() => {
 const floor = document.querySelector('.tt-bg-floor');
 const ctx = floor.getContext('2d');
 ctx.fillStyle = '#ff0000';
 ctx.fillRect(0, 0, floor.width, floor.height);
}"""


@pytest.mark.skipif(os.environ.get("FOGGREY_BROWSER") != "1",
                    reason="lead must run FOGGREY_BROWSER=1 outside the sandbox")
def test_mixed_remembered_sources_have_no_tone_seams(tmp_path, monkeypatch):
    playwright = pytest.importorskip("playwright.sync_api")
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    static = Path(__file__).resolve().parents[1] / "static" / "tabletop"
    html = '''<link rel="stylesheet" href="/tabletop.css">
<style>body{margin:0}#host{width:384px;height:256px;position:relative}
.tt-board{transform:none!important;width:384px!important;height:256px!important}
.tt-grid{display:none}</style><div id="host"></div><script type="module">
import {createBoard} from '/board.js';
import {paintFloor} from '/textures.js';
const board=createBoard(document.querySelector('#host'));
board.setMap({width:6,height:4,background:{style:'flagstone',seed:1,opacity:1},
 display:{},walls:[],trees:[],decor:[],objects:[],ruleTerrain:[],
 cells:{blocked:[],cover:[],hazard:[],difficult:[],sightGhost:[]}});
const raw=paintFloor('flagstone',1,6,4,{patch:true});
const reference=document.createElement('canvas');reference.width=384;reference.height=256;
const rc=reference.getContext('2d');rc.drawImage(raw,0,0,384,256);
window.expectedMeans=[1,2,3].map(x=>{
 const data=rc.getImageData(x*64+8,72,48,48).data;let sum=0;
 for(let i=0;i<data.length;i+=4)sum+=data[i]+data[i+1]+data[i+2];
 return 0.6*sum/(48*48*3)+0.4*(7+9+14)/3;
});
const pps=raw.width/6,crop=document.createElement('canvas');
crop.width=crop.height=pps;
crop.getContext('2d').drawImage(raw,pps,pps,pps,pps,0,0,pps,pps);
const cells={7:{floor:{swatch:crop.toDataURL()}},
 8:{floor:{style:'flagstone',seed:1,patch:true}},9:{floor:null}};
const seen=new Uint8Array(24),explored=new Uint8Array(24).fill(1);
board.setFog(seen,explored,{polygons:[]},new Uint8Array(24).fill(1));
board.setRemembered({cells,ghosts:[7,8,9],changed:[7,8,9],width:6});
await Promise.all([...document.images].map(i=>i.decode().catch(()=>{})));
await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
window.ready=true;
window.replaceUnseen=__REPLACE_UNSEEN_JS__;
</script>'''
    html = html.replace("__REPLACE_UNSEEN_JS__", REPLACE_UNSEEN_JS)

    def serve(route):
        name = urlparse(route.request.url).path.lstrip("/")
        if not name:
            route.fulfill(body=html, content_type="text/html")
        elif "/" not in name and (static / name).is_file():
            route.fulfill(path=str(static / name),
                          content_type="text/css" if name.endswith(".css") else "text/javascript")
        else:
            route.abort()

    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 384, "height": 256}, device_scale_factor=1)
            page.route("http://foggrey.test/**", serve)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto("http://foggrey.test/")
            page.wait_for_function("window.ready === true")
            assert not errors, errors
            png = page.locator(".tt-board").screenshot()
            image = Image.open(io.BytesIO(png)).convert("RGB")
            # Whole-cell means avoid mistaking intentional flagstone texture for a
            # wash seam. Shared-border strips catch hard bands from SVG masks.
            def mean(box):
                pixels = list(image.crop(box).getdata())
                return sum(sum(pixel) for pixel in pixels) / (len(pixels) * 3)
            means = [mean((x * 64 + 8, 72, (x + 1) * 64 - 8, 120)) for x in (1, 2, 3)]
            expected = page.evaluate("expectedMeans")
            for actual, target in zip(means, expected):
                assert abs(actual - target) < 3, f"ground must receive exactly one common wash: {means}, {expected}"
            assert max(means) - min(means) < 6, f"captured/floor/neutral tone mismatch: {means}"
            for border in (128, 192):
                left = mean((border - 6, 72, border - 2, 120))
                right = mean((border + 2, 72, border + 6, 120))
                assert abs(left - right) < 8, f"hard brightness seam at {border}: {left}, {right}"
            # Ensure darkened detail, not a uniformly black false positive.
            assert 25 < min(means) < max(means) < 150
            assert len(set(image.crop((72, 72, 120, 120)).getdata())) > 20
            isolation = page.locator('.tt-remembered-layer')
            isolation.evaluate("layer => { layer.style.visibility = 'hidden'; }")
            exposed_before = Image.open(io.BytesIO(page.locator(".tt-board").screenshot())).convert("RGB")
            isolation.evaluate("layer => { layer.style.visibility = ''; }")
            page.evaluate("replaceUnseen()")
            after = Image.open(io.BytesIO(page.locator(".tt-board").screenshot())).convert("RGB")
            saved_region = (72, 72, 248, 120)
            assert image.crop(saved_region).tobytes() == after.crop(saved_region).tobytes(), \
                "unseen floor replacement leaked through remembered artwork"
            # This control must fail for a hidden CSS-background replacement:
            # remove saved isolation and prove the changed live floor is visible.
            isolation.evaluate("layer => { layer.style.visibility = 'hidden'; }")
            exposed_after = Image.open(io.BytesIO(page.locator(".tt-board").screenshot())).convert("RGB")
            assert exposed_before.crop(saved_region).tobytes() != exposed_after.crop(saved_region).tobytes(), \
                "replacement must change visible pixels when remembered isolation is removed"
            red, green, blue = exposed_after.getpixel((96, 96))
            assert red > green + 100 and red > blue + 100, \
                "control must expose the contrasting red floor under the common fog wash"
        finally:
            browser.close()
