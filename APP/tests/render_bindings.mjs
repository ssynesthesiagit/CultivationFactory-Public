// The table's render() helpers that the Node harnesses do not exercise, as no-ops. A harness spreads
// renderBindings first, then its own keys: an override (a spy, a value, or a forbidden stub) always wins.
// Some harnesses compile real declarations that shadow these parameters; explicit overrides also win.
const noop = () => {};

export const renderBindings = Object.freeze({
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
