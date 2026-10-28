// Production reaction card with the repository's deterministic DOM. No browser.
import {runInNewContext} from 'node:vm';
import {Element} from './objects_dom_stub.mjs';
import {functionSource} from './viewer_identity_harness.mjs';

export function reactionCardHarness() {
  const root = new Element('div');
  root.innerHTML = '<dialog id="ttReaction"><h2 id="ttReactionTitle"></h2><div id="ttReactionText"></div>'
    + '<button data-answer="USE">Use</button><button data-answer="DECLINE">Pass</button></dialog>';
  const dialog = root.querySelector('#ttReaction');
  const calls = {opens: 0, closes: 0, errors: []};
  dialog.showModal = () => { calls.opens++; dialog.open = true; };
  dialog.close = () => { calls.closes++; dialog.open = false; };
  // The card answers a prompt the table saved with the action (auto-step, a submitted
  // choice or a reload), so Escape is the same Pass as the Skip button: the shipped
  // cancelAbilityChoice declines a reserved prompt instead of abandoning the action.
  const context = {app: {matchId: 'match', waitingReaction: {reserved: true}},
    $: selector => root.querySelector(selector),
    escapeHtml: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    toast: text => calls.errors.push(text),
    resumeViewerDialogs: () => { if (!dialog.open) dialog.showModal(); },
    askReactionInput: () => { throw Error('A reaction must not open another chooser'); },
    // wireReactionDialog (the production dialog wiring) reads these ability-choice helpers.
    // The card tests have no ability choice open, so they stand as inert stubs.
    abilityChoiceActive: () => false, abilityReserved: () => false, hint: () => {},
    // The card tests are always on a visible table, so cancellation is never refused.
    currentViewer: () => ({ready: true, status: 'player'}), refuseCoveredView: () => false,
    cancelTargeting: () => {}, renderShapePanel: () => {}, renderActionBar: () => {},
  };
  for (const name of ['decisionText', 'spaceOptionLabel', 'reactionMenuRows', 'reactionMenuChoice', 'reactionMenuAnswers', 'reactionMenuMapAnswer', 'wireReactionDialog', 'releaseMapPick', 'cancelAbilityChoice', 'askReactionMenu']) {
    runInNewContext(functionSource(name), context);
  }
  return {root, dialog, calls, context};
}
