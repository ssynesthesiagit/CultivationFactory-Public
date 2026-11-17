import test from 'node:test';
import assert from 'node:assert/strict';
import {runInNewContext} from 'node:vm';
import {reactionCardHarness} from './reaction_card_harness.mjs';
import {functionSource} from './viewer_identity_harness.mjs';

const response = (name, source, checkpoint = 'TYPED:DAMAGE_APPLICATION@8') => ({
  reactor: 'Left', reaction: name, trigger: 'Right hits Left with a club.', cost: 'Reaction',
  summary: 'Reduce the damage of this hit.', context: {checkpoint, reactor_id: 'left', reaction_source_id: source},
});
const guard = () => ({...response('Stamina Guard', 'reaction:typed.guard'), cost: 'Reaction and 1–4 Stamina',
  choice: {minimum: 1, maximum: 1, allow_decline: true,
    options: [1, 2, 3, 4].map(n => ({id: String(n), label: `Spend ${n} Stamina`}))}});

test('usefulness sorts the visible card but the first displayed response binds the original second context', async () => {
  const {context, root, dialog} = reactionCardHarness();
  const alternatives = [{...response('Flat guard', 'reaction:flat'), useful_now: true, menu_priority: 14},
    {...guard(), useful_now: true, menu_priority: 44,
      expected_effect: 'Reduce 17 damage by 1d10 per Stamina (base avg 5.5 each).'}];
  const pending = context.askReactionMenu({alternatives});
  const html = root.querySelector('#ttReactionText').innerHTML;
  assert.ok(html.indexOf('Stamina Guard') < html.indexOf('Flat guard'));
  assert.match(html, /Reduce 17 damage by 1d10/);
  dialog.querySelector('[data-reaction-choice="1"] select').value = '4';
  dialog.querySelector('[data-reaction-use="0"]').onclick();
  const answers = await pending;
  assert.equal(answers[0].selection, 'DECLINE');
  assert.equal(answers[1].reaction_source_id, 'reaction:typed.guard');
  assert.deepEqual(Array.from(answers[1].option_ids), ['4']);
});

test('Other reactions is collapsed and its last legal option remains selectable; Skip still declines every response', async () => {
  const {context, dialog} = reactionCardHarness();
  const alternatives = Array.from({length: 25}, (_, i) => ({...response(`Ward ${i}`, `reaction:${i}`),
    useful_now: i === 1, menu_priority: i === 1 ? 10 : 0, expected_effect: 'No damage to reduce.'}));
  const pending = context.askReactionMenu({alternatives});
  const other = dialog.querySelector('[data-other-reactions]');
  assert.ok(other);
  assert.ok(!other.open, 'native details starts collapsed');
  assert.equal(other.querySelectorAll('[data-reaction-entry]').length, 24);
  assert.equal(dialog.querySelectorAll('[data-reaction-entry]').length, 25);
  other.open = true;
  other.querySelector('[data-reaction-use="24"]').onclick();
  const answers = await pending;
  assert.equal(answers.length, 25);
  assert.equal(answers.at(-1).reaction_source_id, 'reaction:24');
  assert.equal(answers.at(-1).selection, 'USE');
  const skip = context.askReactionMenu({alternatives});
  assert.equal(dialog.querySelector('[data-answer="DECLINE"]').textContent, 'Skip');
  dialog.querySelector('[data-answer="DECLINE"]').onclick();
  assert.equal((await skip).filter(row => row.selection === 'DECLINE').length, 25);
});

test('a useless mode stays under Other reactions and binds its original mode context', async () => {
  const {context, dialog} = reactionCardHarness();
  const alternatives = [{...response('Ward — No damage', 'reaction:ward:mode:0'), useful_now: false},
    {...response('Ward — Useful', 'reaction:ward:mode:1'), useful_now: true}];
  const pending = context.askReactionMenu({alternatives});
  assert.equal(dialog.querySelectorAll('[data-reaction-entry]').length, 2);
  const other = dialog.querySelector('[data-other-reactions]');
  other.open = true;
  other.querySelector('[data-reaction-use="1"]').onclick();
  const answers = await pending;
  assert.equal(answers.length, 1);
  assert.equal(answers[0].reaction_source_id, 'reaction:ward:mode:0');
});

test('Other reactions has one outer summary even when its entries include full rules', async () => {
  const {context, dialog, root} = reactionCardHarness();
  const pending = context.askReactionMenu({alternatives: [guard(), {
    ...response('Flat guard', 'reaction:flat'), useful_now: false,
    rules: 'Reduce the triggering damage by 0. Costs one Reaction.',
  }]});
  const other = dialog.querySelector('[data-other-reactions]');
  // A descendant summary selector is ambiguous; the browser check must select
  // the direct child so the complete printed rules remain available as well.
  assert.equal(other.querySelectorAll('summary').length, 2);
  const outer = other.children.filter(node => node.tagName === 'SUMMARY');
  assert.equal(outer.length, 1);
  assert.ok(other.querySelector('section').querySelector('summary'));
  const html = root.querySelector('#ttReactionText').innerHTML;
  assert.match(html, /<details data-other-reactions><summary>Other reactions<\/summary>/);
  assert.match(html, /<details><summary>Full rules, targets and duration<\/summary>/);
  dialog.querySelector('[data-answer="DECLINE"]').onclick();
  assert.ok((await pending).every(row => row.selection === 'DECLINE'));
});

test('one card lists hit defenses and an inline amount; picking the second never opens another dialog', async () => {
  const {context, root, dialog, calls} = reactionCardHarness();
  const alternatives = [response('Iron Forearm Guard', 'reaction:typed.forearm', 'TYPED:ATTACK_HIT_BEFORE_DAMAGE@7'), guard()];
  const pending = context.askReactionMenu({alternatives});
  assert.equal(dialog.querySelectorAll('[data-reaction-entry]').length, 2);
  assert.match(root.querySelector('#ttReactionText').innerHTML, /1–4 Stamina/);
  const amount = dialog.querySelector('[data-reaction-choice="1"]').querySelector('select');
  assert.equal(amount.options.length, 5, 'all four amounts and an explicit unchosen state');
  dialog.querySelector('[data-reaction-use="1"]').onclick();
  assert.equal(calls.errors.length, 1, 'amount required before spending');
  amount.value = '3';
  dialog.querySelector('[data-reaction-use="1"]').onclick();
  const answers = await pending;
  assert.equal(answers.length, 2);
  assert.equal(answers[0].selection, 'DECLINE');
  assert.equal(answers[1].selection, 'USE');
  assert.deepEqual(Array.from(answers[1].option_ids), ['3']);
  assert.equal(calls.opens, 1);
  assert.equal(dialog.open, true, 'card remains while the server checks for remaining responses');
});

test('modes stay inline and bind the selected mode to its own context', async () => {
  const {context, dialog, calls} = reactionCardHarness();
  const alternatives = ['Brace', 'Hold position'].map((mode, i) =>
    response(`Ward — ${mode}`, `reaction:typed.ward:mode:${i}`));
  const pending = context.askReactionMenu({alternatives});
  assert.equal(dialog.querySelectorAll('[data-reaction-entry]').length, 1);
  const mode = dialog.querySelector('[data-reaction-mode="0"]');
  mode.value = '1'; mode.onchange();
  assert.equal(dialog.querySelector('[data-reaction-detail="0"]').hidden, true);
  assert.equal(dialog.querySelector('[data-reaction-detail="1"]').hidden, false);
  dialog.querySelector('[data-reaction-use="0"]').onclick();
  const answers = await pending;
  assert.equal(answers.at(-1).reaction_source_id, 'reaction:typed.ward:mode:1');
  assert.equal(answers.at(-1).selection, 'USE');
  assert.equal(calls.opens, 1);
});

test('one ability at distinct checkpoints never becomes an empty mode selector', async () => {
  const {context, dialog} = reactionCardHarness();
  const alternatives = [response('Ward', 'reaction:typed.ward', 'TYPED:ATTACK_HIT_BEFORE_DAMAGE@7'),
    response('Ward', 'reaction:typed.ward', 'TYPED:DAMAGE_APPLICATION@8')];
  const pending = context.askReactionMenu({alternatives});
  assert.equal(dialog.querySelectorAll('[data-reaction-entry]').length, 2);
  assert.equal(dialog.querySelectorAll('[data-reaction-mode]').length, 0);
  dialog.querySelector('[data-reaction-use="1"]').onclick();
  assert.equal((await pending).at(-1).checkpoint, 'TYPED:DAMAGE_APPLICATION@8');
});

test('remaining responses update the same open card, with one Skip and Escape declining all', async () => {
  const {context, dialog, calls} = reactionCardHarness();
  const free = response('Free ward', 'reaction:typed.free');
  free.cost = 'No Reaction or resources';
  const first = context.askReactionMenu({alternatives: [free, guard()]});
  dialog.querySelector('[data-reaction-use="0"]').onclick();
  await first;
  const next = context.askReactionMenu({alternatives: [guard()]});
  assert.equal(calls.opens, 1, 'no close/reopen between remaining responses');
  assert.equal(dialog.querySelectorAll('[data-reaction-use]').length, 1);
  const footer = dialog.querySelectorAll('[data-answer]').filter(button => !button.hidden);
  assert.equal(footer.length, 1);
  assert.equal(footer[0].textContent, 'Skip');
  await dialog.dispatch('cancel');
  const answers = await next;
  assert.ok(answers.every(row => row.selection === 'DECLINE'));
  assert.equal(dialog.open, false);
});

test('Pass all answers every checkpoint, including inline choices, without choosing an amount', async () => {
  const {context, dialog} = reactionCardHarness();
  const alternatives = [response('First', 'reaction:first', 'TYPED:ATTACK_HIT_BEFORE_DAMAGE@7'), guard(),
    response('Third', 'reaction:third')];
  const pending = context.askReactionMenu({alternatives});
  dialog.querySelector('[data-answer="DECLINE"]').onclick();
  const answers = await pending;
  assert.equal(answers.length, 3);
  assert.ok(answers.every(row => row.selection === 'DECLINE' && !row.option_ids));
});

for (const fails of [false, true]) {
  test(`the action closes the retained card on ${fails ? 'transport error' : 'commit'}`, async () => {
    const {context, dialog} = reactionCardHarness();
    context.askReaction = prompt => context.askReactionMenu(prompt);
    context.playEvents = async () => {};
    runInNewContext(functionSource('appendReactionAnswer') + '\n' + functionSource('withReactions'), context);
    let sends = 0;
    const pending = context.withReactions(async answers => {
      if (++sends === 1) return {status: 'REACTION_REQUIRED', reaction: {alternatives: [response('Ward', 'reaction:ward')]}};
      assert.equal(dialog.open, true, 'same card stays open during the request');
      assert.equal(answers[0].selection, 'USE');
      if (fails) throw Error('transport unavailable');
      return {status: 'COMMITTED'};
    });
    for (let n = 0; n < 10 && !dialog.open; n++) await Promise.resolve();
    dialog.querySelector('[data-reaction-use="0"]').onclick();
    if (fails) await assert.rejects(pending, /transport unavailable/);
    else assert.equal((await pending).status, 'COMMITTED');
    assert.equal(dialog.open, false);
    assert.equal(dialog.querySelector('[data-answer="USE"]').hidden, undefined);
    assert.equal(dialog.querySelector('[data-answer="DECLINE"]').disabled, false);
  });
}
