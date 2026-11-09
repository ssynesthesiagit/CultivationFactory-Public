// Mount the unmodified board and its actual imports; only DOM geometry and time are simulated.
import assert from 'node:assert/strict';
import {installDOM} from './objects_dom_stub.mjs';
import {HOVER_OPEN_DELAY_MS} from '../static/tabletop/hovercard.js?v=tipdelay-1';

export async function runMovementHover(movement) {
  const original = {setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout};
  const doc = installDOM('<html><body><div id="board"></div></body></html>');
  let now = 0, seq = 0;
  const timers = new Map();
  globalThis.setTimeout = (fn, ms) => { timers.set(++seq, {fn, at: now + ms}); return seq; };
  globalThis.clearTimeout = id => timers.delete(id);
  function advance(ms) {
    now += ms;
    for (const [id, timer] of [...timers]) if (timer.at <= now) { timers.delete(id); timer.fn(); }
  }
  try {
    const {createBoard, movementTooltip} = await import('../static/tabletop/board.js');
    assert.equal(movementTooltip({available: false, explained_refusal: false, reasons: []}).lines[0],
      "This square isn't an available destination this turn.");
    const board = createBoard(doc.querySelector('#board'));
    board.setMap({width: 10, height: 8, background: {style: 'plain'}});
    const summary = movement.summary, moverId = summary.actor_id;
    const roster = [
      {id: moverId, x: 3, y: 4, name: 'Mover', hp: 17, maxHp: 20, temp: 3, ridingOn: 'mount',
        conditions: [{name: 'Poisoned', text: 'Disadvantage on attacks and ability checks.'}]},
      {id: 'mount', x: 3, y: 4, name: 'Horse', hp: 12, maxHp: 16, conditions: []},
      {id: 'other', x: 5, y: 4, name: 'Guard', hp: 8, maxHp: 15,
        conditions: [{name: 'Prone', text: 'Stand up by spending half your Speed.'}]},
    ];
    board.setTokens(roster);
    board.setMovementExplanation(movement);
    const card = doc.body.querySelector('.tt-hovercard'); // token and square share one node
    card.getBoundingClientRect = () => ({left: 700, top: 0, right: 800, bottom: 100, width: 100, height: 100});
    for (const id of [moverId, 'other', 'mount']) {
      const x = id === 'other' ? 320 : 192;
      board.tokenNode(id).getBoundingClientRect = () => ({left: x, top: 256, right: x + 64, bottom: 320, width: 64, height: 64});
    }
    const square = {clientX: 288, clientY: 288, buttons: 0, deltaY: 0, pointerId: 1};
    const moverPoint = {clientX: 224, clientY: 288, buttons: 0};
    async function restOn(id) {
      const token = board.tokenNode(id);
      await token.dispatch('pointerenter');
      await board.viewport.dispatch('pointermove', {target: token, ...moverPoint, clientX: id === 'other' ? 352 : 224});
      advance(HOVER_OPEN_DELAY_MS);
      return token;
    }
    const texts = node => [node.textContent, ...node.children.flatMap(child => texts(child))];
    const checkSquare = () => {
      assert.equal(card.hidden, false);
      assert.ok(card.classList.contains('tt-zone-tip'));
      const lines = texts(card);
      assert.ok(lines.includes(movement.destinations['4,4'].available ? 'Movement cost' : "You can't move here"));
      for (const reason of movement.destinations['4,4'].reasons) assert.ok(lines.includes(reason.message), reason.message);
    };
    await board.viewport.dispatch('pointermove', square);
    advance(899); assert.equal(card.hidden, true);
    advance(1); checkSquare();
    // LIVE's named terrain and the destination refusal coexist in the same
    // interactive card; retain this check from the replaced CJS renderer test.
    board.closeHoverCard(); // new map content, fresh hover; source-square travel now preserves an open card
    board.setMap({width: 10, height: 8, background: {style: 'plain'},
      ruleTerrain: [{type: 'DIFFICULT', look: 'stones', cells: [[4, 4]]}]});
    await board.viewport.dispatch('pointermove', square); advance(900); checkSquare();
    assert.ok(texts(card).includes('Difficult terrain'));
    assert.ok(texts(card).includes('Each foot of movement through it costs one extra foot.'));
    board.closeHoverCard();
    board.setMap({width: 10, height: 8, background: {style: 'plain'}});
    await board.viewport.dispatch('pointermove', square); advance(900); checkSquare();
    for (const event of ['pointermove', 'pointerdown', 'wheel', 'pointerleave']) {
      // UIREGRESS1: moving within the source square toward the card keeps it
      // open. Test an actual departure, plus explicit map press/zoom dismissal.
      await board.viewport.dispatch(event, ['pointermove', 'pointerleave'].includes(event)
        ? {clientX: 32, clientY: 32, buttons: 0} : square);
      if (event === 'pointerleave') advance(300); // shared overlay grace, not an immediate viewport close
      assert.equal(card.hidden, true, event);
      if (event === 'pointerdown') await board.viewport.dispatch('pointerup', square);
      await board.viewport.dispatch('pointermove', square); advance(900); checkSquare();
    }
    board.setMovementExplanation(null); assert.equal(card.hidden, true);
    await board.viewport.dispatch('pointermove', square); advance(900); assert.equal(card.hidden, true);
    board.setMovementExplanation(movement);
    const creatureInfo = () => {
      assert.equal(card.hidden, false);
      assert.ok(card.classList.contains('tt-token-card'));
      for (const text of ['Mover', '17 / 20 HP', '+3 temporary', 'Poisoned',
        'Disadvantage on attacks and ability checks.', 'Riding Horse', '12 / 16 HP']) assert.ok(card.innerHTML.includes(text), text);
    };
    const movementInfo = () => {
      creatureInfo(); assert.ok(card.innerHTML.includes('Your movement this turn'));
      assert.ok(card.innerHTML.includes(`Speed ${summary.effective_speed_ft} feet; ${summary.movement_remaining_ft} feet of movement left this turn`));
      for (const reason of summary.reasons) {
        const escaped = reason.message.replace(/[&<>\"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '\"': '&quot;'})[c]);
        assert.ok(card.innerHTML.includes(escaped), reason.message);
      }
    };
    const mover = await restOn(moverId);
    creatureInfo(); advance(399); assert.ok(!card.innerHTML.includes('Your movement this turn'));
    advance(1); movementInfo();
    card.scrollTop = 120;
    const originalChild = card.firstChild;
    board.setTokens(roster.map(row => row.id === 'other' ? {...row, hp: 2} : row));
    movementInfo(); assert.equal(card.scrollTop, 120); assert.equal(card.firstChild, originalChild);
    board.setTokens(roster);
    for (const event of ['pointermove', 'pointerdown', 'wheel']) {
      if (event === 'pointerdown') await mover.dispatch(event, moverPoint);
      else await board.viewport.dispatch(event, {target: mover, ...moverPoint, deltaY: 0});
      creatureInfo(); assert.ok(!card.innerHTML.includes('Your movement this turn'), event);
      await restOn(moverId); advance(900); movementInfo();
    }
    board.setMovementExplanation(null); creatureInfo(); assert.ok(!card.innerHTML.includes('Your movement this turn'));
    board.setMovementExplanation({summary, destinations: {'4,4': movement.destinations['4,4'],
      '5,4': {available: false, explained_refusal: false, reasons: []}}});
    board.closeHoverCard(); // explicit fresh hover, rather than crossing a token inside the open card's corridor
    await mover.dispatch('pointerleave', {clientX: 352, clientY: 288});
    await restOn('other');
    const otherHTML = card.innerHTML;
    assert.ok(otherHTML.includes('8 / 15 HP')); assert.ok(otherHTML.includes('Stand up by spending half your Speed.'));
    advance(899); assert.equal(card.innerHTML, otherHTML); advance(1); advance(1000);
    assert.equal(card.hidden, false); assert.equal(card.innerHTML, otherHTML);
    // Leaving now uses the interactive-card grace period, rather than instant dismissal.
    await board.tokenNode('other').dispatch('pointerleave', square);
    await board.viewport.dispatch('pointermove', square); advance(900); checkSquare();
    await board.viewport.dispatch('pointermove', {clientX: 32, clientY: 32, buttons: 0}); advance(900);
    assert.equal(card.hidden, true);
    console.log('full board hover preserves creature/companion cards: PASS');
  } finally {
    globalThis.setTimeout = original.setTimeout;
    globalThis.clearTimeout = original.clearTimeout;
  }
}
