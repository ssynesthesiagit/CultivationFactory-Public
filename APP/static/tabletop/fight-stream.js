// One transport, existing apply paths. Polls run only while SSE is unavailable.
export function createFightStream({poll, seatStatus, events, changed,
  EventSource: Source = globalThis.EventSource, timers = globalThis,
  onConnection = () => {}}) {
  let source, matchId, cursor, retry, pollTimer, opened = false, stopped = false;
  let delay = 1000, generation = 0, serial = Promise.resolve();
  let latestStatus, statusVersion = 0, observedVersion = 0;
  const waiters = new Set();
  function wake(value) {
    for (const done of waiters) done(value);
    waiters.clear();
  }
  function polling() {
    if (!pollTimer) pollTimer = timers.setInterval(poll, 3000);
  }
  function disconnected() {
    opened = false;
    wake(null);
    polling();
    onConnection(false);
  }
  function connect() {
    if (!Source || stopped || !matchId) return;
    const version = generation;
    try { source = new Source(`/api/tabletop/matches/${encodeURIComponent(matchId)}/stream?after=${cursor()}`); }
    catch { fail(); return; }
    const live = source;
    live.onopen = () => {
      if (version !== generation || source !== live) return;
      opened = true; delay = 1000;
      timers.clearInterval(pollTimer); pollTimer = null;
      onConnection(true);
    };
    function receive(kind, event) {
      if (version !== generation || source !== live) return;
      serial = serial.then(async () => {
        if (version !== generation) return;
        const payload = JSON.parse(event.data);
        if (kind === 'seat-status') {
          await seatStatus(payload);
          latestStatus = payload; statusVersion++;
          wake(payload);
        }
        else if (kind === 'events') await events(payload);
        else await changed(payload);
      }).catch(() => { if (version === generation && source === live) fail(); });
    }
    for (const kind of ['events', 'seat-status', 'menu-ready', 'fight-changed'])
      live.addEventListener(kind, event => receive(kind, event));
    live.onerror = () => { if (source === live) fail(); };
  }
  function fail() {
    source?.close(); source = null;
    disconnected();
    if (!stopped && !retry && Source) {
      retry = timers.setTimeout(() => { retry = null; connect(); }, delay);
      delay = Math.min(delay * 2, 30000);
    }
  }
  function stop() {
    stopped = true; generation++;
    source?.close(); source = null; opened = false;
    timers.clearTimeout(retry); retry = null;
    timers.clearInterval(pollTimer); pollTimer = null;
    wake({running: false});
  }
  return {
    get open() { return opened; },
    watch(id, after) {
      stop(); stopped = false; matchId = id; cursor = after;
      serial = Promise.resolve(); delay = 1000;
      latestStatus = null; statusVersion = observedVersion = 0;
      polling(); connect();
    },
    stop,
    // automaticTurn retains its 100ms fallback. Open streams wait for status.
    async observeStatus(observe) {
      if (opened) {
        if (statusVersion > observedVersion) {
          observedVersion = statusVersion;
          return latestStatus;
        }
        const value = await new Promise(resolve => waiters.add(resolve));
        if (value) { observedVersion = statusVersion; return value; }
      }
      return observe();
    },
  };
}
