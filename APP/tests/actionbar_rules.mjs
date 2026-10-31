// Relevant-only: actual bar controls plus the shared delegated hover/focus/tap binding, without a browser.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {FakeElement} from './attacklist1_dom.mjs';
import {bindTipTargets} from '../static/tabletop/hovercard.js';
import {renderBarFixture, plainRules} from './actionbar_fixture.mjs';

class Element extends FakeElement {
  set innerHTML(markup) {
    this.markup = markup;
    this.replaceChildren();
    // The renderer's fixed control shells only need tags/classes. Keep the raw
    // markup too, so an inline generated player card cannot evade the guard.
    for (const [, tag, attrs] of markup.matchAll(/<(\w+)\b([^>]*)>/g)) {
      const node = new Element(tag);
      node.className = /class="([^"]*)"/.exec(attrs)?.[1] || '';
      this.appendChild(node);
    }
  }
  get innerHTML() { return this.markup || ''; }
  get lastChild() { return this.children.at(-1); }
  hasAttribute(name) {
    if (name.startsWith('data-')) return this.matches('[' + name + ']');
    return super.hasAttribute(name);
  }
  contains(node) { return this === node || this.children.some(child => child instanceof Element && child.contains(node)); }
  getBoundingClientRect() { return {left: 0, top: 0, width: 100, height: 40}; }
}

export async function checkActionBar(hover) {
  const document = {createElement: tag => new Element(tag), createTextNode: text => String(text)};
  const bar = document.createElement('footer');
  bar.id = 'ttActionBar';
  bar.ownerDocument = document;
  const source = fs.readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const {pressed} = await renderBarFixture(document, bar, source, hover);
  const all = node => [node, ...node.children.filter(child => child instanceof Element).flatMap(all)];
  const assertControlsOnly = () => {
    for (const node of all(bar)) {
      assert.ok(!['tt-action-rules', 'player-card', 'tt-tipcard', 'tc', 'tc-full', 'lib-text']
        .some(cls => node.classList.contains(cls)), 'rules element inside #ttActionBar: ' + node.className);
      assert.doesNotMatch(node.innerHTML, /player-card|tt-action-rules|tc-full/);
      assert.doesNotMatch(node.innerHTML, /<(?:h[1-6]|summary|b)\b[^>]*>\s*(?:Effect|Choices|Rules|Full rules)\s*</i);
      assert.ok(!['Effect', 'Choices', 'Rules', 'Full rules'].includes(node.textContent.trim()));
    }
    assert.ok(!bar.textContent.includes(hover.player_card.text));
    assert.ok(!bar.textContent.includes('Final rule: every choice remains available.'));
  };
  assertControlsOnly();
  const controls = bar.querySelectorAll('button');
  assert.equal(controls.length, 7, 'move, five actions, and end turn all remain');
  const tipButtons = controls.filter(button => typeof button.tipCard === 'function');
  assert.equal(tipButtons.length, 5, 'attack, both sheet actions, and both extra actions have full help');

  const floating = document.createElement('div');
  let opened = 0;
  const card = {open({build}) { opened++; build(floating); }, releaseFocus() {}};
  const timers = [];
  bindTipTargets(card, bar, {setTimer: fn => { timers.push(fn); return timers.length; }, clearTimer() {}});
  for (const button of tipButtons) {
    assert.equal(button.disabled, false);
    for (const type of ['pointerover', 'focusin', 'click']) {
      floating.replaceChildren();
      const before = opened;
      bar.listeners[type]({target: button});
      if (type === 'pointerover') timers.pop()();
      assert.equal(opened, before + 1, type + ' must reach the shared card');
      const content = all(floating).map(node => node.innerHTML + node.textContent).join('\n');
      assert.ok(content.includes(button.dataset.tip.includes('Final rule:') ? plainRules : hover.player_card.html));
      assert.equal(bar.contains(floating), false, 'floating rules stay outside the bar');
      assertControlsOnly();
    }
    for (const key of ['Enter', ' ']) {
      let prevented = false;
      bar.listeners.keydown({target: button, key, preventDefault() { prevented = true; }});
      assert.equal(prevented, false, 'native keyboard activation must still press the action');
    }
    button.listeners.click();
  }
  assert.deepEqual(pressed.sort(), ['carded', 'plain', 'sheet-carded', 'extra-carded', 'extra-plain'].sort(),
    'help never consumes or removes a legal action');
}
