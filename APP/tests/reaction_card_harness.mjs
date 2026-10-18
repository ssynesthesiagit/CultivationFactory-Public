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
  const context = {app: {matchId: 'match', waitingReaction: {}},
    $: selector => root.querySelector(selector),
    escapeHtml: value => String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
    toast: text => calls.errors.push(text),
    resumeViewerDialogs: () => { if (!dialog.open) dialog.showModal(); },
    askReactionInput: () => { throw Error('A reaction must not open another chooser'); },
  };
  for (const name of ['decisionText', 'spaceOptionLabel', 'reactionMenuRows', 'reactionMenuChoice', 'reactionMenuAnswers', 'askReactionMenu']) {
    runInNewContext(functionSource(name), context);
  }
  return {root, dialog, calls, context};
}
