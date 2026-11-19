// Lead-only DevTools recipe on the scratch origin http://127.0.0.1:8799.
// Paste this whole async expression into its console, then follow the returned URL.
// It reads the scratch fight, writes only this synthetic browser view's storage,
// and does not move actors, submit combat actions or contact a model server.
(async () => {
  const match = 'match:1f1374ebd31eceac9efd4a39';
  const actor = 'actor:factory.2ff3d22c-9024-4142-a7c3-54a32623f1b2';
  const view = 'foggrey3-repro';
  const response = await fetch(`/api/tabletop/matches/${encodeURIComponent(match)}/state?fog=true&fog_view=own&fog_actor_ids=${encodeURIComponent(actor)}`);
  if (!response.ok) throw new Error(`Scratch state read failed: ${response.status}`);
  const payload = await response.json(), state = payload.state || payload;
  const table = state.map, battlefield = state.presentation.battlefield;
  const {createBoard} = await import('/static/tabletop/board.js?v=foggrey3');
  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;left:-100000px;width:640px;height:480px';
  document.body.append(host);
  const board = createBoard(host);
  try {
    const bg = table.background || {}, scale = table.scale || 1;
    const map = {width: battlefield.width_squares, height: battlefield.height_squares,
      background: bg.asset ? {url: `/api/tabletop/map-assets/${bg.asset}`, fit: bg.fit, opacity: (bg.opacity_pct ?? 100) / 100}
        : {style: bg.style || 'flagstone', seed: bg.seed || 1, opacity: 1},
      display: {blend: (table.display?.blend_pct ?? 0) / 100, gridOpacity: 0},
      trees: table.trees || [], decor: table.decor || [], floors: table.floors || [],
      walls: (table.walls || []).map(w => ({...w, points: w.points.map(([x,y]) => [x/scale,y/scale])})),
      openings: table.openings || [], ruleTerrain: table.terrain || [], roofs: table.roofs,
      cells: {blocked: [], cover: [], hazard: [], difficult: [], sightGhost: []}};
    board.setMap(map);
    board.setZones(state.presentation.zones || [], {round: state.round || 1});
    if (bg.asset) {
      const image = host.querySelector('.tt-bg-image');
      await image.decode();
    }
    const cells = {};
    // Synthetic earlier sight of the whole map. An obsolete faint zone forces
    // the changed-cell renderer without editing the scratch fight. Labels are
    // fictional last-known positions; no current hidden actor data is used.
    for (let y=0;y<map.height;y++) for (let x=0;x<map.width;x++) {
      cells[y*map.width+x] = {floor: board.floorRecordAt(x,y), scenery: board.sceneryRecordAt(x,y),
        terrain: board.terrainAt(x,y), zones: [{id:'foggrey3-old-mist',owner:null,name:'Earlier mist',color:'#aab3c0'}],
        tokens: [], objects: []};
    }
    for (const [x,y,name] of [[3,4,'Bandit'],[5,6,'Lying Yeti'],[6,8,'Crab']])
      cells[y*map.width+x].tokens = [{id:`foggrey3-marker-${x}-${y}`,name,label:name.slice(0,2).toUpperCase()}];
    // Authored props, rather than the fight's current hidden object list.
    for (const row of table.objects || []) {
      const record = cells[row.y*map.width+row.x];
      if (record) record.objects.push({id:row.id || `prop-${row.x}-${row.y}`,name:row.name || row.kind,kind:row.kind,x:row.x,y:row.y});
    }
    const memory = {version:3,cells};
    const key = `tt-fog-memory:${match}:${view}:own:${map.width}x${map.height}`;
    const db = await new Promise((resolve,reject) => {
      const request = indexedDB.open('tt-fog-memory',1);
      request.onupgradeneeded = () => request.result.createObjectStore('snapshots');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    await new Promise((resolve,reject) => {
      const tx = db.transaction('snapshots','readwrite');
      tx.objectStore('snapshots').put(memory,key);
      tx.oncomplete = resolve; tx.onabort = () => reject(tx.error);
    });
    db.close();
    sessionStorage.setItem(`tt-viewer:v1:${JSON.stringify([view,match,'binding'])}`,JSON.stringify({version:1,role:'player',actor_ids:[actor]}));
    sessionStorage.setItem(`tt-viewer:v1:${JSON.stringify([view,match,'fog'])}`,JSON.stringify({actor_ids:[actor],mode:'own'}));
    const url = `/tabletop?match=${encodeURIComponent(match)}&view=${view}`;
    console.log({url, memoryKey:key, cells:Object.keys(cells).length});
    return url;
  } finally { host.remove(); }
})()
