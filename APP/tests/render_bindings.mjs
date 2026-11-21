// The table's render() helpers that the Node harnesses do not exercise, as no-ops. A harness spreads
// renderBindings first, then its own keys: an override (a spy, a value, or a forbidden stub) always wins.
// Some harnesses compile real declarations that shadow these parameters; explicit overrides also win.
const noop = () => {};

// Extracted table functions use the polling path when the test stubs transport.
export const disconnectedFightStream = Object.freeze({
  open: false, stop: noop, watch: noop, observeStatus: observe => observe(),
});

export const renderBindings = Object.freeze({
  fightStream: disconnectedFightStream,
  reconcileViewerIdentity: noop,
  renderCommitNotice: noop,
  reconcileOptionDraft: noop,
  broadcastDraftStates: noop,
  invalidateTargeting: noop,
  renderTokens: noop,
  renderZones: noop,
  renderInitiative: noop,
  renderRoster: noop,
  renderInspector: noop,
  renderActionBar: noop,
  renderItemsPanel: noop,
  renderShapePanel: noop,
  scheduleAutoPlay: noop,
  renderHighlights: noop,
  broadcastActors: noop,
  renderPip: noop,
  scheduleSeatPoll: noop,
  requestDeferredMenu: noop,
});
