import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PresetQueue} from '../static/tabletop/preset-queue.mjs';

const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => {resolve=a; reject=b;}); return {promise,resolve,reject}; };
const queue = options => new PresetQueue({delay: 100000, ...options});

// Exercise preparation through remapping, before the action reserves the UI.
function actionPreparationSource(source) {
  const start = source.indexOf('async function act(');
  const end = source.indexOf('  if (app.busy) { toast', start);
  assert.ok(start >= 0 && end > start);
  return 'const document = {body: {classList: {add() {}}}}; const hint = () => {};\n'
    + source.slice(start, end) + 'return candidateId; } finally { app.abilityChoice = null; } }';
}

// act() refuses a submission while the table view is covered. These tests drive an available
// view, so the real guard stands aside; it is carried in the slice rather than replaced, so a
// change to it stays visible here instead of being stubbed away.
const coveredGuard = () => {
  const source = readFileSync(new URL('../static/tabletop/tabletop.js', import.meta.url), 'utf8');
  const start = source.indexOf('function refuseCoveredView(');
  assert.notEqual(start, -1, 'refuseCoveredView is present');
  return source.slice(start, source.indexOf('\n}', start) + 2);
};

test('optimistic synchronous value; nine edits coalesce into one request, last value wins', async () => {
  const calls = [], changed = [];
  const q = queue({send: async (scope, values) => {calls.push([scope,values]);}, changed: (...v) => changed.push(v)});
  for (let i=0;i<9;i++) q.edit('a', `value-${i}`, 'old', 'fight');
  q.edit('b', 'other', 'before', 'fight');
  assert.equal(q.value('a', 'old'), 'value-8');
  assert.equal(changed.length, 10);
  assert.equal(calls.length, 0);
  await q.flush();
  assert.deepEqual(calls, [['fight',['value-8','other']]]);
});

test('refresh during a request preserves optimism; controls remain editable', async () => {
  const wait = deferred(), calls=[];
  const q=queue({send: async (_scope,values) => {calls.push(values); if(calls.length===1) await wait.promise;}});
  q.edit('a','new','old','fight'); const flush=q.flush();
  assert.equal(q.value('a','old'),'new');
  q.edit('b','other','before','fight'); q.edit('a','newer','old','fight');
  assert.equal(q.value('a','old'),'newer');
  wait.resolve(); await flush;
  assert.deepEqual(calls,[['new'],['other','newer']]);
  assert.equal(q.value('a','old'),'newer');
});

test('failure rolls back only the failed revision with a plain error; flush blocks an attack', async () => {
  const errors=[], changed=[];
  const q=queue({send: async () => {throw Error('Could not save');}, error: (...v)=>errors.push(v), changed:(...v)=>changed.push(v)});
  q.edit('a','new','old','fight');
  await assert.rejects(q.flush(),/not saved/);
  assert.equal(q.value('a','old'),'old');
  assert.equal(changed.at(-1)[1],'old'); assert.equal(errors.length,1);
  q.send=async()=>{}; q.edit('a','retry','old','fight'); await q.flush();
});

test('older failure never rolls back a newer edit; later failure restores last accepted value', async()=>{
  const wait=deferred(); let n=0; const errors=[];
  const q=queue({send:async()=>{if(++n===1) await wait.promise;}, error:(...v)=>errors.push(v)});
  q.edit('a','one','old','fight'); const flush=q.flush();
  q.edit('a','two','old','fight'); wait.reject(Error('older')); await flush;
  assert.equal(q.value('a','old'),'two'); assert.equal(errors.length,0);
  q.send=async()=>{throw Error('latest');}; q.edit('a','three','old','fight');
  await assert.rejects(q.flush()); assert.equal(q.value('a','old'),'two');
});

test('scope changes cannot send old preferences to another fight; outside combat uses same queue', async()=>{
  const calls=[]; const q=queue({send:async(...v)=>calls.push(v)});
  q.edit('a','one','old','fight-one'); q.edit('b','two','old',''); await q.flush();
  assert.deepEqual(calls,[['fight-one',['one']],['',['two']]]);
});

test('accepted newer refresh clears settled optimism, preserving edits still in flight',async()=>{
  const q=queue({send:async()=>({state_version:12})});
  q.edit('a','one','old','fight'); await q.flush();
  q.acceptRefresh('fight',11); assert.equal(q.value('a','old'),'one');
  q.acceptRefresh('fight',12); assert.equal(q.value('a','remote'),'remote');
  const wait=deferred(); q.send=async()=>wait.promise;
  q.edit('a','pending','old','fight'); const flush=q.flush();
  q.acceptRefresh('fight',20); assert.equal(q.value('a','old'),'pending');
  wait.resolve({state_version:21}); await flush;
});

test('failed old fight never blocks a new fight; an authoritative refresh reconciles a lost reply',async()=>{
  const q=queue({send:()=>{throw Error('lost reply');}});
  q.edit('old/key','new','before','old'); await assert.rejects(q.flush('old'));
  q.send=async()=>({state_version:3}); q.edit('new/key','other','before','new'); await q.flush('new');
  assert.equal(q.value('old/key','server-accepted'),'before');
  q.acceptRefresh('old',5); assert.equal(q.value('old/key','server-accepted'),'server-accepted');
  await q.flush('old');
});

test('restoration announces queued, in-flight and failed scopes without reviving settled edits',async()=>{
  const saved=deferred(), announced=[];
  const q=queue({send:async()=>saved.promise,pending:(scope,pending)=>{if(pending) announced.push(scope);}});
  q.edit('inflight','one','old','first');
  const flush=q.flush('first');
  q.edit('queued','two','old','second');
  announced.length=0;
  try {
    q.announcePending();
    assert.deepEqual(new Set(announced),new Set(['first','second']));
  } finally {saved.resolve(); await flush; await q.flush();}
  announced.length=0; q.announcePending(); assert.deepEqual(announced,[]);
  q.send=async()=>{throw Error('offline');};
  q.edit('failed','three','old','third'); await assert.rejects(q.flush('third'));
  announced.length=0; q.announcePending(); assert.deepEqual(announced,['third']);
});

test('actual table synchronization waits for the sheet queue, refreshes once and ignores other fights',async()=>{
  const code=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  const start=code.indexOf('const pendingPresets = new Map();');
  const fragment=code.slice(start,code.indexOf('function openSheetFor',start));
  const posted=[]; let refreshed=0;
  const app={matchId:'current',channel:{postMessage:msg=>posted.push(msg)}};
  const sync=new Function('app','refresh','crypto',fragment+';return {pendingPresets,presetWaiters,synchronizePresets,dirty:()=>{presetsDirty=true;}};')(app,async()=>{refreshed++;},{randomUUID:()=> 'receipt'});
  sync.pendingPresets.set('elsewhere',{actorId:'actor',matchId:'old'});
  sync.pendingPresets.set('sheet',{actorId:'actor',matchId:'current'}); sync.dirty();
  let done=false; const wait=sync.synchronizePresets().then(()=>{done=true;});
  assert.equal(done,false); assert.equal(refreshed,0); assert.equal(posted.length,1);
  assert.equal(posted[0].sheet_id,'sheet'); sync.presetWaiters.get('receipt')({ok:true});
  await wait; assert.equal(refreshed,1); assert.equal(done,true);
  assert.equal(sync.pendingPresets.has('elsewhere'),true);
});

test('explicitly closed failed sheet reconciles settings before the next table action',async()=>{
  const code=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  const start=code.indexOf('const pendingPresets = new Map();');
  const fragment=code.slice(start,code.indexOf('function openSheetFor',start));
  for (const close of [true,false]) {
    const posted=[]; let refreshed=0; let failRefresh=true;
    let receive;
    const app={matchId:'fight',channel:{postMessage:msg=>posted.push(msg),addEventListener:(_type,fn)=>{receive=fn;}}};
    const channelStart=code.indexOf('app.channel?.addEventListener("message", async event => {');
    const channel=code.slice(channelStart,code.indexOf('\n});',channelStart)+4);
    const sync=new Function('app','refresh','crypto','actorById',fragment+channel+';return {pendingPresets,presetWaiters,synchronizePresets};')(
      app,async()=>{if(failRefresh) throw Error('offline'); refreshed++;},{randomUUID:()=> 'flush'},()=>null);
    const msg=(type,sheet_id='old',extra={})=>receive({data:{type,sheet_id,match_id:'fight',actor_id:'me',...extra}});
    msg('sheet-hello'); msg('settings-pending'); msg('settings-saved','old',{ok:false,unsaved:true});
    const waiting=sync.synchronizePresets();
    assert.equal(posted.length,1);
    if(close) msg('sheet-closed');
    msg('sheet-hello','new');
    const olderStillPending=sync.pendingPresets.has('old');
    if(!close) {
      msg('sheet-closed');
    }
    await assert.rejects(waiting,/offline/);
    if(!close) assert.equal(olderStillPending,true,'another live sheet does not close the failed sheet');
    failRefresh=false;
    await sync.synchronizePresets();
    assert.equal(refreshed,1,'authoritative settings are refreshed before action is allowed');
    msg('settings-saved','old',{ok:false,unsaved:true});
    msg('sheet-hello','old');
    assert.equal(sync.pendingPresets.size,0,'late response cannot resurrect a closed sheet');
    msg('settings-pending','new');
    const next=sync.synchronizePresets();
    assert.equal(posted.at(-1).sheet_id,'new');
    msg('settings-flushed','new',{request_id:'flush',ok:true}); await next;
  }
  const sheet=readFileSync(new URL('../static/tabletop/sheet.js',import.meta.url),'utf8');
  assert.match(sheet,/sheet-hello[^\n]*sheet_id: presetWindow/);
  assert.match(sheet,/pagehide[\s\S]*?sheet-closed/);
});

test('two live same-actor sheets both flush; an older sheet delayed save blocks a table action',async()=>{
  const code=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  const start=code.indexOf('const pendingPresets = new Map();');
  const fragment=code.slice(start,code.indexOf('function openSheetFor',start));
  const channelStart=code.indexOf('app.channel?.addEventListener("message", async event => {');
  const channel=code.slice(channelStart,code.indexOf('\n});',channelStart)+4);
  const saved=deferred(), sent=deferred(), sheets=new Map(), posted=[];
  let receive, receipt=0, refreshed=0, persisted='old', acted=false;
  const msg=(type,sheet_id,extra={})=>receive({data:{type,sheet_id,match_id:'fight',actor_id:'me',...extra}});
  const app={matchId:'fight',channel:{addEventListener:(_type,fn)=>{receive=fn;},postMessage:message=>{
    posted.push(message);
    if(message.type==='settings-flush') sheets.get(message.sheet_id).flush(message.match_id).then(
      ()=>msg('settings-flushed',message.sheet_id,{request_id:message.request_id,ok:true}));
  }}};
  const sync=new Function('app','refresh','crypto','actorById',fragment+channel+';return {pendingPresets,synchronizePresets};')(
    app,async()=>{refreshed++;},{randomUUID:()=>`flush-${++receipt}`},()=>null);
  for(const id of ['older','newer']) {
    sheets.set(id,queue({send:async(_scope,values)=>{
      if(id==='older') {sent.resolve(); await saved.promise;}
      persisted=values[0];
    },pending:(_scope,pending,_response,error)=>msg(pending?'settings-pending':'settings-saved',id,
      {ok:!error,unsaved:Boolean(error)})}));
    msg('sheet-hello',id);
  }
  // Both windows remain editable after the second hello. The older edit has not
  // reached its debounced HTTP save when the table action requests a flush.
  sheets.get('older').edit('rider','older-choice','old','fight');
  const actionStart=code.indexOf('async function act(');
  const beforeSubmit=actionPreparationSource(code);
  const act=new Function('app','synchronizePresets','toast','currentViewer',coveredGuard()+beforeSubmit+';return act;')(
    app,sync.synchronizePresets,message=>assert.fail(message),()=>({ready:true}));
  const action=act('attack').then(candidate=>{assert.equal(candidate,'attack'); acted=true; return persisted;});
  try {
    await Promise.resolve();
    await Promise.resolve();
    assert.equal(acted,false,'table action must wait for the older live sheet');
    assert.equal(posted[0]?.sheet_id,'older');
    await sent.promise;
    assert.equal(persisted,'old','the delayed save has not committed');
    assert.equal(refreshed,0);
    sheets.get('newer').edit('rider','newer-choice','old','fight');
    saved.resolve();
    const result=await action;
    assert.equal(result,'newer-choice');
    assert.deepEqual(posted.map(message=>message.sheet_id),['older','newer']);
    assert.equal(refreshed,1);
    assert.equal(sync.pendingPresets.size,0);
  } finally {
    saved.resolve();
    await Promise.all([...sheets.values()].map(sheet=>sheet.flush()));
    await action;
  }
});

test('cached sheet restoration reannounces pending edits and blocks actions until deferred saves finish',async()=>{
  const code=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  const start=code.indexOf('const pendingPresets = new Map();');
  const fragment=code.slice(start,code.indexOf('function openSheetFor',start));
  const channelStart=code.indexOf('app.channel?.addEventListener("message", async event => {');
  const channelCode=code.slice(channelStart,code.indexOf('\n});',channelStart)+4);
  const sheetCode=readFileSync(new URL('../static/tabletop/sheet.js',import.meta.url),'utf8');
  const lifecycleStart=sheetCode.indexOf('function hello() {');
  const lifecycle=sheetCode.slice(lifecycleStart,sheetCode.indexOf('function onMessage',lifecycleStart));
  for(const pendingBeforeHide of [false,true]) {
    const saved=deferred(), events=new Map(), posted=[];
    let receive, restoredId, refreshed=0, acted=false, persisted='old', uuid=0;
    const state={projectId:'project',sheet:{actor_id:'me'},actor:{match_id:'fight'},connected:true};
    const channel={addEventListener:()=>{},postMessage:message=>{posted.push(message); receive({data:message});}};
    const q=queue({send:async(_scope,values)=>{await saved.promise; persisted=values[0];},
      pending:(_scope,pending,_response,error)=>channel.postMessage({type:pending?'settings-pending':'settings-saved',
        sheet_id:restoredId(),actor_id:'me',match_id:'fight',ok:!error,unsaved:Boolean(error)})});
    const app={matchId:'fight',channel:{addEventListener:(_type,fn)=>{receive=fn;},postMessage:message=>{
      q.flush(message.match_id).then(()=>channel.postMessage({...message,type:'settings-flushed',ok:true}));
    }}};
    const sync=new Function('app','refresh','crypto','actorById',fragment+channelCode+';return {pendingPresets,synchronizePresets};')(
      app,async()=>{refreshed++;},{randomUUID:()=>`flush-${++uuid}`},()=>null);
    const setup=new Function('state','presetQueue','post','BroadcastChannel','CHANNEL_NAME','document','window',
      'setTimeout','setInterval','clearTimeout','clearInterval','renderLive','HELLO_WAIT_MS','REHELLO_MS','crypto',
      'let channel, presetWindow="original", helloTimer, rehelloTimer; function onMessage() {} '+lifecycle+
      ';startChannel(); return ()=>presetWindow;');
    restoredId=()=> 'original';
    restoredId=setup(state,q,message=>channel.postMessage(message),function(){return channel;},'test',
      {addEventListener:()=>{}},{addEventListener:(type,fn)=>events.set(type,fn)},
      ()=>1,()=>2,()=>{},()=>{},()=>{},1,1,{randomUUID:()=>`restored-${++uuid}`});
    if(pendingBeforeHide) q.edit('rider','before-hide','old','fight');
    events.get('pagehide')({persisted:true});
    assert.equal(sync.pendingPresets.size,0,'suspended sheet releases its old pending identity');
    events.get('pageshow')?.({persisted:true});
    try {
      if(pendingBeforeHide) assert.equal(sync.pendingPresets.has(restoredId()),true,'restoration reannounces queued edits');
      else q.edit('rider','after-restore','old','fight');
      const actionStart=code.indexOf('async function act(');
      const prefix=actionPreparationSource(code);
      const act=new Function('app','synchronizePresets','toast','currentViewer',coveredGuard()+prefix+';return act;')(
        app,sync.synchronizePresets,message=>assert.fail(message),()=>({ready:true}));
      const action=act('attack').then(()=>{acted=true; return persisted;});
      await Promise.resolve(); await Promise.resolve();
      assert.equal(acted,false,'restored sheet deferred save must block table action');
      assert.notEqual(restoredId(),'original','restored sheet must use a live synchronization identity');
      assert.equal(persisted,'old');
      saved.resolve();
      assert.equal(await action,pendingBeforeHide?'before-hide':'after-restore');
      assert.equal(refreshed,1);
      assert.equal(sync.pendingPresets.size,0);
      events.get('pagehide')({persisted:false});
      channel.postMessage({type:'settings-pending',sheet_id:restoredId(),match_id:'fight',actor_id:'me'});
      assert.equal(sync.pendingPresets.size,0,'final close still suppresses late messages');
    } finally {saved.resolve(); await q.flush();}
  }
});

test('actual table action remapping preserves targets and movement, and cannot end another actors turn',async()=>{
  const source=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  const start=source.indexOf('async function act(');
  const prefix=actionPreparationSource(source);
  const old={actor_id:'me',state_version:1,end_turn:'old-end',moves:[{candidate_id:'old-move',destination:{x:2,y:3}}],
    actions:[{source_definition_id:'strike',options:[{candidate_id:'old-hit',target_ids:['foe'],option_ids:[],destination:null,label:'Foe'}]}]};
  const current={...old,state_version:2,end_turn:'new-end',moves:[{candidate_id:'new-move',destination:{x:2,y:3}}],
    actions:[{source_definition_id:'strike',options:[{...old.actions[0].options[0],candidate_id:'new-hit'}]}]};
  const run=async(id,next)=>{
    const app={state:{menu:old}}, messages=[];
    const act=new Function('app','synchronizePresets','toast','currentViewer',coveredGuard()+prefix+';return act;')(
      app,async()=>{app.state.menu=next;},msg=>messages.push(msg),()=>({ready:true}));
    return [await act(id),messages];
  };
  assert.equal((await run('old-hit',current))[0],'new-hit');
  assert.equal((await run('old-move',current))[0],'new-move');
  assert.equal((await run('old-end',current))[0],'new-end');
  const other=await run('old-end',{...current,actor_id:'other'});
  assert.equal(other[0],false); assert.match(other[1][0],/Choose your action again/);
  const changed={...current,actions:[{source_definition_id:'strike',options:[{...current.actions[0].options[0],target_ids:['different foe']}]}]};
  assert.equal((await run('old-hit',changed))[0],false);
});

test('sheet dropdown uses the queue without a combat button or blocking toast; table flushes before attacks',()=>{
  const sheet=readFileSync(new URL('../static/tabletop/sheet.js',import.meta.url),'utf8');
  const start=sheet.indexOf('const select = event.target.closest("[data-rider-select]")');
  const dropdown=sheet.slice(start,sheet.indexOf('for (const tab of document.querySelectorAll("#tablist',start));
  assert.match(dropdown,/presetQueue.edit/); assert.doesNotMatch(dropdown,/type: "button"|Not allowed|busy/);
  const table=readFileSync(new URL('../static/tabletop/tabletop.js',import.meta.url),'utf8');
  assert.match(table,/async function act\(candidateId[,)]\s*[\s\S]*?await Promise.race\(\[synchronizePresets\(\), choice.cancellation\]/);
  assert.match(sheet,/async function activate[\s\S]*?await presetQueue.flush/);
});

test('browser check: instant edit and other controls usable (lead runs outside sandbox)', {skip: process.env.SOL157_BROWSER !== '1'}, async()=>{
  const {chromium}=await import('playwright');
  const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
  try {
    const page=await browser.newPage();
    assert.ok(process.env.SOL157_SHEET_URL,'Set SOL157_SHEET_URL to an isolated test sheet');
    await page.goto(process.env.SOL157_SHEET_URL);
    const controls=page.locator('[data-rider-select]'); await controls.first().waitFor();
    assert.ok(await controls.count()>=2);
    await page.route('**/settings',async route=>{await new Promise(r=>setTimeout(r,500)); await route.fulfill({json:{rows:[]}});});
    const first=controls.first(); const second=controls.nth(1);
    const value=await first.locator('option').last().getAttribute('value');
    const start=Date.now(); await first.selectOption(value); assert.equal(await first.inputValue(),value);
    assert.ok(Date.now()-start<100,'selection visible under 100ms');
    assert.equal(await second.isEnabled(),true);
    await second.selectOption({index:1});
    assert.equal(await page.getByText('Still working on your last action…',{exact:false}).count(),0);
  } finally {await browser.close();}
});
