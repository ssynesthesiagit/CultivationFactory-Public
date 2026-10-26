"""Lead runs outside the sandbox: N4_BROWSER=1 pytest this file.

Self-contained static board fixture on loopback. Never uses a live match/server.
"""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading

import pytest

pytestmark = pytest.mark.skipif(os.getenv('N4_BROWSER') != '1',
                              reason='Lead must run browser checks outside the sandbox')


def test_zone_overlay_transfer_and_pending_summary_dismissal():
    """Real hit-testing sequences for SOLFMMX100r3; never run inside the sandbox."""
    from playwright.sync_api import sync_playwright, expect

    root = Path(__file__).resolve().parents[1]
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            try:
                page = browser.new_page(viewport={'width': 1100, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/static/tabletop/')
                for outside in (False, True):
                    page.set_content('''<link rel="stylesheet" href="/static/tabletop/tabletop.css">
                        <div id="board" style="width:340px;height:300px"></div>''')
                    page.evaluate('''async () => {
                        const {createBoard} = await import('/static/tabletop/board.js');
                        window.testBoard = createBoard(document.querySelector('#board'));
                        testBoard.setMap({width:10, height:8, background:{style:'plain'}});
                        testBoard.setZones([{zone_id:'dark', name:'Darkness', affected_cells:[[4,3]]}]);
                    }''')
                    viewport = page.locator('.tt-viewport').bounding_box()
                    x, y = viewport['x'], viewport['y']
                    page.mouse.move(x + 288, y + 224)
                    card = page.locator('.tt-zone-tip')
                    expect(card).to_be_visible(timeout=1500)
                    # Put the sibling overlay at two deterministic positions. Events are produced by browser
                    # hit testing and real mouse movement, rather than dispatching viewport leave by hand.
                    card.evaluate('''(node, outside) => {
                        const r = testBoard.viewport.getBoundingClientRect();
                        Object.assign(node.style, {left:`${r.left + (outside ? 350 : 80)}px`,
                            top:`${r.top+20}px`, width:'200px', height:'140px'});
                        node.append(document.createTextNode(' Long rules.'.repeat(400)));
                        window.transferEvents = [];
                        testBoard.viewport.addEventListener('pointerleave', () => transferEvents.push('leave'));
                        node.addEventListener('pointerenter', () => transferEvents.push('enter'));
                        document.addEventListener('pointermove', e => {
                            if (node.contains(e.target)) transferEvents.push('move-on-card');
                        });
                    }''', outside)
                    if outside:
                        page.mouse.move(x + 330, y + 120)  # bridge, inside viewport
                        page.mouse.move(x + 360, y + 120)  # card, outside viewport
                    else:
                        page.mouse.move(x + 150, y + 170)  # bridge, below card
                        page.mouse.move(x + 150, y + 150)  # sibling overlay covering viewport
                    expect(card).to_be_visible()
                    events = page.evaluate('transferEvents')
                    assert events.index('leave') < events.index('enter') < events.index('move-on-card')
                    page.wait_for_timeout(1100)
                    expect(card).to_be_visible()
                    page.mouse.wheel(0, 80)
                    page.wait_for_function('document.querySelector(".tt-zone-tip").scrollTop > 0')
                    page.keyboard.press('Escape')

                page.evaluate('''() => {
                    testBoard.setZones([]);
                    testBoard.setTokens([{id:'mover', x:3, y:3, name:'Mover', hp:12, maxHp:12, conditions:[]}]);
                    testBoard.setMovementExplanation({summary:{actor_id:'mover', effective_speed_ft:30,
                        movement_remaining_ft:20, reasons:[]}, destinations:{}});
                }''')
                for dismissal in ('escape', 'outside-press'):
                    page.mouse.move(1000, 700)
                    page.get_by_role('button', name='Mover, 12 of 12 hit points', exact=True).hover()
                    card = page.locator('.tt-token-card')
                    expect(card).to_be_visible()
                    expect(card).not_to_contain_text('Your movement this turn')
                    if dismissal == 'escape':
                        page.keyboard.press('Escape')
                    else:
                        # Document press outside the viewport, without a mousemove cancelling the rest timer.
                        page.evaluate('document.body.dispatchEvent(new PointerEvent("pointerdown", {bubbles:true, clientX:1000, clientY:700}))')
                    expect(card).to_be_hidden()
                    page.wait_for_timeout(1100)
                    expect(card).to_be_hidden()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_rest_delay_refused_square_and_moving_token():
    from playwright.sync_api import sync_playwright, expect

    root = Path(__file__).resolve().parents[1]
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            try:
                page = browser.new_page(viewport={'width': 1100, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/static/tabletop/')
                page.set_content('''<link rel="stylesheet" href="/static/tabletop/tabletop.css">
                  <div id="board" style="position:relative;width:900px;height:650px"></div>''')
                page.evaluate('''async () => {
                  const {createBoard} = await import('/static/tabletop/board.js');
                  const board = createBoard(document.querySelector('#board'));
                  board.setMap({width: 10, height: 8, background: {style: 'plain'}});
                  const reason = {code: 'FRIGHTENED_CLOSER', blocks_destination: true,
                    message: "You are Frightened of Liu Yao Zisheng: you can't move closer to them while you can see them."};
                  const summary = {actor_id: 'mover', effective_speed_ft: 30, movement_remaining_ft: 20, reasons: [reason]};
                  board.setTokens([
                    {id: 'mover', x: 3, y: 4, name: 'Mover', hp: 17, maxHp: 20, temp: 3, ridingOn: 'mount',
                      scale: 0.8, movementSummary: summary,
                      conditions: [{name: 'Poisoned', text: 'Disadvantage on attacks and ability checks.'}]},
                    {id: 'mount', x: 3, y: 4, name: 'Horse', hp: 12, maxHp: 16, conditions: []},
                    {id: 'other', x: 5, y: 4, name: 'Guard', hp: 8, maxHp: 15,
                      conditions: [{name: 'Prone', text: 'Stand up by spending half your Speed.'}]}
                  ]);
                  board.setMovementExplanation({summary, destinations: {
                    '4,4': {...summary, available: false, explained_refusal: true},
                    '5,4': {available: false, explained_refusal: false, reasons: []}}});
                  window.testBoard = board;
                }''')
                tip = page.locator('.tt-zone-tip')
                card = page.locator('.tt-token-card')
                mover = page.get_by_role('button', name='Mover, 17 of 20 hit points', exact=True)
                other = page.get_by_role('button', name='Guard, 8 of 15 hit points', exact=True)
                def expect_creature_info():
                    expect(card).to_be_visible()
                    for text in ('17 / 20 HP', '+3 temporary', 'Poisoned',
                                 'Disadvantage on attacks and ability checks.', 'Riding Horse', '12 / 16 HP'):
                        expect(card).to_contain_text(text)
                await_square = page.locator('.tt-board').bounding_box()
                x, y = await_square['x'] + 4.5 * 64, await_square['y'] + 4.5 * 64
                page.mouse.move(x, y)
                page.wait_for_timeout(400)
                expect(tip).to_be_hidden()
                expect(tip).to_be_visible(timeout=1500)
                expect(tip).to_contain_text("You can't move here")
                expect(tip).to_contain_text('while you can see them')
                page.mouse.move(x + 2, y)
                expect(tip).to_be_hidden()
                expect(tip).to_be_visible(timeout=1500)
                page.mouse.down()
                expect(tip).to_be_hidden()
                page.mouse.up()
                mover.hover()
                expect_creature_info()
                page.wait_for_timeout(400)
                expect(tip).to_be_hidden()
                expect(card).not_to_contain_text('Your movement this turn')
                expect(card).to_contain_text('Your movement this turn', timeout=1500)
                expect(card).to_contain_text('20 feet of movement left this turn')
                expect(card).to_contain_text('while you can see them')
                expect_creature_info()
                page.mouse.wheel(0, 5)
                expect(tip).to_be_hidden()
                expect(card).not_to_contain_text('Your movement this turn')
                expect_creature_info()
                page.mouse.move(10, 10)
                mover.hover()
                expect(card).to_contain_text('Your movement this turn', timeout=1500)
                page.evaluate('window.testBoard.setMovementExplanation(null)')
                expect(tip).to_be_hidden()
                expect(card).not_to_contain_text('Your movement this turn')
                expect_creature_info()
                # The occupied square has a refusal card, but cannot displace Guard's card.
                page.evaluate('window.testBoard.setMovementExplanation({summary: {actor_id: "mover"}, destinations: {"5,4": {available: false, reasons: []}}})')
                other.hover()
                for _ in range(2):
                    expect(card).to_be_visible()
                    expect(card).to_contain_text('Guard')
                    expect(card).to_contain_text('8 / 15 HP')
                    expect(card).to_contain_text('Prone')
                    expect(card).to_contain_text('Stand up by spending half your Speed.')
                    expect(card).not_to_contain_text('Your movement this turn')
                    expect(tip).to_be_hidden()
                    page.wait_for_timeout(1100)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_focused_cards_allow_selection_and_token_refresh_preserves_reading():
    """Opt-in rendered checks for SOLFMMX100r2; lead runs outside the sandbox."""
    from playwright.sync_api import sync_playwright, expect

    root = Path(__file__).resolve().parents[1]
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(root)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            try:
                page = browser.new_page(viewport={'width': 1100, 'height': 800})
                page.goto(f'http://127.0.0.1:{server.server_port}/static/tabletop/')
                page.set_content('''<link rel="stylesheet" href="/static/tabletop/tabletop.css">
                    <div id="board" style="width:900px;height:650px"></div>
                    <button id="action" data-tip="Spend 1 Stamina to move 5 feet.">Move</button>
                    <div id="resource" tabindex="0" data-tip="Stamina pays for actions and movement.">Stamina</div>''')
                page.evaluate('''async () => {
                    const {createBoard} = await import('/static/tabletop/board.js');
                    const {createHoverCard, bindTipTargets} = await import('/static/tabletop/hovercard.js?v=r24');
                    window.testBoard = createBoard(document.querySelector('#board'));
                    testBoard.setMap({width:10, height:8, background:{style:'plain'}});
                    window.testRoster = [
                        {id:'reader', x:3, y:3, name:'Reader', hp:12, maxHp:12,
                         conditions:Array.from({length:30}, (_,i) => ({name:`Effect ${i}`, text:'Long rules text about this effect.'}))},
                        {id:'other', x:6, y:3, name:'Other', hp:12, maxHp:12, conditions:[]}
                    ];
                    testBoard.setTokens(testRoster);
                    bindTipTargets(createHoverCard(), document);
                }''')

                def drag_select(card, text_selector=None):
                    # Use a real mouse drag across visible text, including the press that blurs the trigger.
                    points = card.evaluate('''(node, selector) => {
                        const text = selector ? node.querySelector(selector).firstChild : node.firstChild;
                        const range = document.createRange();
                        range.setStart(text, 0); range.setEnd(text, Math.min(12, text.length));
                        const r = range.getBoundingClientRect();
                        return {x:r.left+1, y:r.top+r.height/2, end:r.right-1};
                    }''', text_selector)
                    page.mouse.move(points['x'], points['y'])
                    page.mouse.down()
                    page.mouse.move(points['end'], points['y'], steps=8)
                    page.mouse.up()
                    expect(card).to_be_visible()
                    assert page.evaluate('getSelection().toString().length') > 0

                for control in ('action', 'resource'):
                    page.locator(f'#{control}').focus()
                    card = page.locator('.tt-hovercard:not([hidden])')
                    expect(card).to_be_visible()
                    drag_select(card)
                    page.keyboard.press('Escape')
                    page.evaluate('getSelection().removeAllRanges()')

                page.get_by_role('button', name='Reader, 12 of 12 hit points', exact=True).focus()
                card = page.locator('.tt-token-card')
                drag_select(card, 'b')
                selected = page.evaluate('getSelection().toString()')
                page.mouse.wheel(0, 180)
                page.wait_for_function('document.querySelector(".tt-token-card").scrollTop > 0')
                scroll = card.evaluate('node => node.scrollTop')
                page.evaluate('''() => {
                    window.originalCardChild = document.querySelector('.tt-token-card').firstChild;
                    testRoster[1].hp = 3; testBoard.setTokens(testRoster);
                }''')
                assert card.evaluate('node => node.firstChild === originalCardChild')
                assert card.evaluate('node => node.scrollTop') == scroll
                assert page.evaluate('getSelection().toString()') == selected
                page.evaluate('testRoster[0].hp = 5; testBoard.setTokens(testRoster)')
                expect(card).to_contain_text('12 / 12 HP')
                assert page.evaluate('getSelection().toString()') == selected
                page.evaluate('getSelection().removeAllRanges()')
                expect(card).to_contain_text('5 / 12 HP')
                assert card.evaluate('node => node.scrollTop') == scroll
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
