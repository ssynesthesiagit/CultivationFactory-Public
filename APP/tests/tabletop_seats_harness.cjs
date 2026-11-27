// Supply the real seats module to extracted page functions without starting a browser.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const seats = fs.readFileSync(path.join(__dirname, '../static/tabletop/seats.js'), 'utf8')
  .replace(/^export /mg, '');
const identity = fs.readFileSync(path.join(__dirname, '../static/tabletop/viewer-identity.js'), 'utf8')
  .replace(/^export /mg, '');

function createSeatContext(bindings) {
  // These controller/coordination fixtures are explicit GM sessions. Player
  // identity and fog use their separate real-table harness, with no such default.
  const context = vm.createContext({reconcileViewerIdentity:()=>false, resumeViewerDialogs:()=>{},
    loadSeats:async()=>{}, ...bindings});
  vm.runInContext(seats, context, {filename: 'seats.js'});
  vm.runInContext(identity, context, {filename:'viewer-identity.js'});
  if (!bindings.currentViewer) vm.runInContext(`
    const coordinationViewer = createViewerStore({viewId:'coordination-test'});
    coordinationViewer.bindGM('coordination-test');
    function currentViewer() { return resolveViewerIdentity(coordinationViewer.read('coordination-test'), [], {seats:{}}); }
    function isGMView() { return true; }
  `, context);
  return context;
}

module.exports = {createSeatContext};
