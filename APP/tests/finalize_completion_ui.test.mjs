// Exercise the production completion path with controllable request promises.
// No server, browser, network, model inference, or wall-clock timeout is needed.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../static/app.js', import.meta.url), 'utf8');
function declaration(name, asynchronous = false) {
  const start = source.indexOf(`${asynchronous ? 'async ' : ''}function ${name}(`);
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
const finalizeStart = source.indexOf('document.getElementById("guidedFinalize").onclick =');
assert.ok(finalizeStart >= 0);
const finalizeHandler = source.slice(finalizeStart, source.indexOf('\n};', finalizeStart) + 3);

function deferred() {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return {promise, resolve, reject};
}
const ready = (runId = 'run-a', projectId = 'project-a') => ({
  run_id: runId, project_id: projectId, status: 'READY_FOR_REVIEW', quality: {status: 'CLEAN'},
});
const finalized = (runId = 'run-a', projectId = 'project-a') => ({
  ...ready(runId, projectId), status: 'CLEAN_AND_FINALIZED', commit: {approved_candidate_identity: 'verified-candidate'},
});
async function settle() {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

function harness(respond, initialLifecycle = {persistence_state: 'temporary', is_temporary: true}) {
  const calls = [], statuses = [], diagnostics = [], renderedSheets = [], steps = [];
  const nodes = new Map();
  const document = {
    getElementById(id) {
      if (!nodes.has(id)) nodes.set(id, {
        disabled: false, textContent: '', children: [],
        replaceChildren() { this.children = []; },
        appendChild(child) { this.children.push(child); },
        scrollIntoView() {},
      });
      return nodes.get(id);
    },
    createElement() { return {textContent: '', className: ''}; },
  };
  const noop = () => {};
  const bindings = {
    document,
    api: path => {
      calls.push(path);
      if (respond) return respond(path);
      return Promise.resolve(path.endsWith('/finalize') ? finalized()
        : path.endsWith('/lifecycle') ? {is_temporary: false}
        : path.endsWith('/sheet') ? {project_id: 'project-a'} : []);
    },
    setGuidedStatus: (message, error = false) => statuses.push({message, error}),
    recordGuidedDiagnostic: (error, context) => diagnostics.push({error, context}),
    renderOwnerSheet: sheet => renderedSheets.push(sheet),
    steps,
    clearNode: node => node.replaceChildren(),
    pretty: JSON.stringify,
    parseAPIError: error => ({code: error.code, details: error.details, message: error.message}),
    plainAPIError: (error, fallback) => error.message || fallback,
    guidedResponseResultMessage: () => null,
    guidedRunOwnerMessage: run => run.status,
    guidedAIPerformanceSummary: () => null,
    ownerViewFor: () => ({}),
    isManualLineageBoundedChoiceDiagnostic: () => false,
    ...Object.fromEntries([
      'renderOwnerPrimaryActions', 'renderPlanningFreeze', 'appendTextCell',
      'renderOwnerProductionSheet', 'renderOwnerExportAvailability', 'appendCandidateLine',
      'refreshGuidedCandidateGMAuthoring', 'updateGuidedControllerResume',
      'refreshGuidedControllerProgress', 'syncManualLineageResolverForRun',
      'recordGuidedRunDiagnostics', 'renderGuidedResponseProcessing',
      'renderGuidedDescriptiveFields', 'renderGuidedRecoveryActions',
      'watchFinalizeInProgress', 'openManualLineageResolver',
    ].map(name => [name, noop])),
    initialRun: ready(),
    initialLifecycle,
  };
  const ui = Function(...Object.keys(bindings), `
    let guidedRun = initialRun, guidedProjectId = initialRun.project_id;
    let guidedProjectLifecycle = initialLifecycle, ownerCharacterSheet = null;
    let guidedFinalizeInFlight = false, guidedFinalizeRequestId = 0, guidedNavigationGeneration = 0;
    function setGuidedStep(step) { guidedNavigationGeneration++; steps.push(step); }
    ${declaration('guidedNavigationIsCurrent')}
    ${declaration('hasSubstantiveCommit')}
    ${declaration('descriptiveFieldValue')}
    ${declaration('renderGuidedPersistence')}
    ${declaration('refreshGuidedFinalizedLifecycle', true)}
    ${declaration('renderGuidedCandidate')}
    ${declaration('renderGuidedFinal')}
    ${declaration('loadFinalOwnerSheet', true)}
    ${declaration('loadProjects', true)}
    ${finalizeHandler}
    return {
      click: () => document.getElementById('guidedFinalize').onclick(),
      loadFinalOwnerSheet,
      refreshLifecycle: () => refreshGuidedFinalizedLifecycle(guidedRun),
      state: () => ({run: guidedRun, projectId: guidedProjectId, lifecycle: guidedProjectLifecycle,
        sheet: ownerCharacterSheet, inFlight: guidedFinalizeInFlight}),
      navigate: () => { guidedNavigationGeneration++; },
      replaceRun: run => {
        guidedNavigationGeneration++; guidedFinalizeRequestId++; guidedFinalizeInFlight = false;
        guidedRun = run; guidedProjectId = run.project_id;
        guidedProjectLifecycle = {is_temporary: true}; ownerCharacterSheet = null;
      },
    };
  `)(...Object.values(bindings));
  return {...ui, calls, statuses, diagnostics, renderedSheets, steps, nodes};
}

test('the committed character and sheet load appear before either metadata refresh completes', async () => {
  const commit = deferred(), lifecycle = deferred(), projects = deferred(), sheet = deferred();
  const ui = harness(path => path.endsWith('/finalize') ? commit.promise
    : path.endsWith('/lifecycle') ? lifecycle.promise
    : path.endsWith('/sheet') ? sheet.promise : projects.promise);
  const pending = ui.click();
  await ui.click(); // A second click cannot submit the mutation again.
  assert.deepEqual(ui.calls, ['/api/character-creation/runs/run-a/finalize']);
  commit.resolve(finalized());
  await pending;
  assert.equal(ui.state().run.status, 'CLEAN_AND_FINALIZED');
  assert.equal(ui.state().inFlight, false);
  // The final renderer owns the single reveal. Repeating setGuidedStep also
  // repeats the expensive owner chrome and compiled-stage renders.
  assert.deepEqual(ui.steps, [4]);
  assert.equal(ui.state().lifecycle.is_temporary, true); // Still deliberately pending.
  assert.ok(ui.statuses.some(row => row.message.startsWith('Character finalized.')));
  assert.ok(ui.calls.includes('/api/characters/project-a/sheet'));
  assert.ok(ui.calls.includes('/api/projects'));
  assert.equal(ui.calls.filter(path => path.endsWith('/lifecycle')).length, 1);
  const savedSheet = {project_id: 'project-a', verified: true};
  sheet.resolve(savedSheet);
  await settle();
  assert.deepEqual(ui.renderedSheets, [savedSheet]);
  lifecycle.resolve({is_temporary: false});
  projects.resolve([]);
  await settle();
  assert.equal(ui.state().lifecycle.is_temporary, false);
});

test('metadata refresh failures preserve the successful finalization and saved sheet', async () => {
  const ui = harness(path => path.endsWith('/finalize') ? Promise.resolve(finalized())
    : path.endsWith('/sheet') ? Promise.resolve({project_id: 'project-a'})
    : Promise.reject(new Error('refresh unavailable')));
  await ui.click();
  await settle();
  assert.equal(ui.state().run.status, 'CLEAN_AND_FINALIZED');
  assert.equal(ui.state().inFlight, false);
  assert.equal(ui.nodes.get('guidedFinalize').disabled, true);
  assert.equal(ui.renderedSheets.length, 1);
  assert.equal(ui.statuses.some(row => row.error), false);
  assert.deepEqual(ui.diagnostics.map(row => row.context).sort(), [
    'refresh_lifecycle_after_finalize', 'refresh_projects_after_finalize',
  ]);
});

test('a saved draft renders its completed lifecycle without delaying the committed result or sheet', async () => {
  const lifecycle = deferred();
  const ui = harness(path => path.endsWith('/finalize') ? Promise.resolve(finalized())
    : path.endsWith('/lifecycle') ? lifecycle.promise
    : Promise.resolve(path.endsWith('/sheet') ? {project_id: 'project-a'} : []), {
    persistence_state: 'saved_draft', is_temporary: false, display_label: 'Saved Draft',
  });
  await ui.click();
  await settle();
  assert.equal(ui.state().run.status, 'CLEAN_AND_FINALIZED');
  assert.equal(ui.state().inFlight, false);
  assert.equal(ui.renderedSheets.length, 1);
  assert.equal(ui.state().lifecycle.persistence_state, 'saved_draft');
  assert.equal(ui.calls.filter(path => path.endsWith('/lifecycle')).length, 1);

  lifecycle.resolve({
    persistence_state: 'completed', is_temporary: false, display_label: 'Completed/Built',
    plain_explanation: 'Retained as a completed or built character.',
  });
  await settle();
  assert.equal(ui.state().lifecycle.persistence_state, 'completed');
  assert.equal(ui.nodes.get('guidedPersistenceLabel').textContent, 'Completed/Built');
  assert.equal(ui.nodes.get('guidedPersistencePanel').hidden, false);
  assert.equal(ui.nodes.get('guidedSaveDraft').hidden, true);
  await ui.refreshLifecycle();
  assert.equal(ui.calls.filter(path => path.endsWith('/lifecycle')).length, 1);
});

test('switching characters prevents both late success and late failure from replacing the view', async () => {
  for (const fails of [false, true]) {
    const commit = deferred();
    const ui = harness(() => commit.promise);
    const pending = ui.click();
    const before = ui.statuses.slice();
    ui.replaceRun(ready('run-b', 'project-b'));
    if (fails) commit.reject(new TypeError('Failed to fetch'));
    else commit.resolve(finalized());
    await pending;
    assert.deepEqual(ui.statuses, before);
    assert.deepEqual(ui.steps, []);
    assert.equal(ui.state().run.status, 'READY_FOR_REVIEW');
    assert.equal(ui.state().run.run_id, 'run-b');
    assert.equal(ui.state().inFlight, false);
    assert.equal(ui.calls.length, 1);
  }
});

test('changing steps during finalization accepts the result and starts its sheet without forcing step four', async () => {
  const commit = deferred();
  const ui = harness(path => path.endsWith('/finalize') ? commit.promise
    : Promise.resolve(path.endsWith('/lifecycle') ? {is_temporary: false}
      : path.endsWith('/sheet') ? {project_id: 'project-a'} : []));
  const pending = ui.click();
  ui.navigate();
  commit.resolve(finalized());
  await pending;
  await settle();
  assert.equal(ui.state().run.status, 'CLEAN_AND_FINALIZED');
  assert.equal(ui.state().inFlight, false);
  assert.ok(ui.calls.includes('/api/characters/project-a/sheet'));
  assert.equal(ui.renderedSheets.length, 1);
  assert.deepEqual(ui.steps, []);
  assert.ok(ui.statuses.some(row => row.message.startsWith('Character finalized.')));
});

test('a previous character completion cannot clear or replace a newer finalization', async () => {
  const first = deferred(), second = deferred();
  const ui = harness(path => path.includes('/run-a/finalize') ? first.promise
    : path.includes('/run-b/finalize') ? second.promise
    : Promise.resolve(path.endsWith('/lifecycle') ? {is_temporary: false} : path.endsWith('/sheet') ? {} : []));
  const oldPending = ui.click();
  ui.replaceRun(ready('run-b', 'project-b'));
  const currentPending = ui.click();
  first.resolve(finalized());
  await oldPending;
  assert.equal(ui.state().inFlight, true);
  assert.equal(ui.state().run.run_id, 'run-b');
  assert.equal(ui.state().run.status, 'READY_FOR_REVIEW');
  second.resolve(finalized('run-b', 'project-b'));
  await currentPending;
  assert.equal(ui.state().inFlight, false);
  assert.equal(ui.state().run.run_id, 'run-b');
  assert.equal(ui.state().run.status, 'CLEAN_AND_FINALIZED');
  assert.equal(ui.calls.some(path => path.includes('/project-a/')), false);
});

test('late sheet and lifecycle reads cannot update a different active character', async () => {
  for (const fails of [false, true]) {
    const sheet = deferred(), lifecycle = deferred();
    const ui = harness(path => path.endsWith('/sheet') ? sheet.promise : lifecycle.promise);
    ui.replaceRun(finalized());
    const sheetRead = ui.loadFinalOwnerSheet(), lifecycleRead = ui.refreshLifecycle();
    ui.replaceRun(ready('run-b', 'project-b'));
    if (fails) {
      sheet.reject(new Error('old sheet failed'));
      lifecycle.reject(new Error('old lifecycle failed'));
    } else {
      sheet.resolve({project_id: 'project-a'});
      lifecycle.resolve({is_temporary: false});
    }
    assert.equal(await sheetRead, null);
    await lifecycleRead;
    assert.equal(ui.state().sheet, null);
    assert.equal(ui.state().lifecycle.is_temporary, true);
    assert.deepEqual(ui.renderedSheets, []);
    assert.deepEqual(ui.diagnostics, []);
    assert.equal(ui.nodes.has('ownerProductionSheet'), false);
  }
});

test('a real finalization failure still reports the error and allows retry', async () => {
  const ui = harness(() => Promise.reject(Object.assign(new Error('Candidate changed; review it again.'), {
    code: 'CG1_STALE_RUN',
  })));
  await ui.click();
  assert.equal(ui.state().run.status, 'READY_FOR_REVIEW');
  assert.equal(ui.state().inFlight, false);
  assert.equal(ui.nodes.get('guidedFinalize').disabled, false);
  assert.deepEqual(ui.statuses.at(-1), {message: 'Candidate changed; review it again.', error: true});
  assert.equal(ui.calls.length, 1);
});
