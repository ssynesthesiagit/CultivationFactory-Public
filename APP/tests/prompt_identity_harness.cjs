// Shared by the prompt/space and rider-choice extraction fixtures. Their own
// DOM observes the real readiness helper; a missing binding never becomes GM.
const vm = require('node:vm');
exports.installPromptIdentity = async function(context, {role}) {
  if (role !== 'gm') throw Error('This fixture must explicitly choose Game Master view');
  const {memoryStorage, functionSource, constSource} = await import('./viewer_identity_harness.mjs');
  const {createViewerStore, resolveViewerIdentity} = await import('../static/tabletop/viewer-identity.js');
  const viewerStore = createViewerStore({viewId: 'prompt-fixture', storage: memoryStorage()});
  viewerStore.bindGM(context.app.matchId);
  Object.assign(context, {viewerStore, resolveViewerIdentity});
  context.app.state = {presentation: {actors: []}};
  context.app.seatStatus = {seats: {}};
  vm.runInContext([constSource('presentation'), functionSource('currentViewer'),
    functionSource('resumeViewerDialogs')].join('\n'), context);
};
