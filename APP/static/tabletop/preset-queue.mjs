/* Revision-aware absolute preferences. The DOM changes synchronously; transport
 * is debounced and serialized, independent of combat's busy state. */
export class PresetQueue {
  constructor({send, changed = () => {}, error = () => {}, pending = () => {}, delay = 60}) {
    Object.assign(this, {send, changed, error, pending, delay});
    this.entries = new Map(); this.next = new Map(); this.running = null; this.timer = null;
    this.revision = 0; this.failedScopes = new Set();
  }
  value(key, authoritative) {
    const entry = this.entries.get(key);
    if (!entry) return authoritative;
    if (!this.next.has(key) && !entry.inflight && entry.value === authoritative) this.entries.delete(key);
    return entry.value;
  }
  acceptRefresh(scope, version) {
    const failed = this.failedScopes.has(scope) && Number.isInteger(version);
    for (const [key,e] of this.entries) if (e.scope === scope && !e.inflight && !this.next.has(key)
        && (failed || (Number.isInteger(e.acceptedVersion) && version >= e.acceptedVersion))) this.entries.delete(key);
    if (failed) this.failedScopes.delete(scope);
  }
  // A restored document has a new transport identity. Reannounce every scope
  // that still needs a save barrier, including requests suspended in flight.
  announcePending() {
    const scopes = new Set(this.failedScopes);
    for (const e of this.next.values()) scopes.add(e.scope);
    for (const e of this.entries.values()) if (e.inflight) scopes.add(e.scope);
    for (const scope of scopes) this.pending(scope, true);
  }
  edit(key, value, baseline, scope) {
    const old = this.entries.get(key);
    const entry = {key, value, baseline: old?.baseline ?? baseline, scope, revision: ++this.revision};
    this.entries.set(key, entry); this.next.set(key, entry); this.failedScopes.delete(scope);
    this.changed(key, value); this.pending(scope, true);
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.flush().catch(() => {}); }, this.delay);
  }
  async flush(onlyScope) {
    clearTimeout(this.timer);
    if (this.running) { await this.running; return this.flush(onlyScope); }
    const waiting = [...this.next.values()].filter(e => onlyScope === undefined || e.scope === onlyScope);
    if (!waiting.length) {
      if (onlyScope === undefined ? this.failedScopes.size : this.failedScopes.has(onlyScope))
        throw new Error('A preset was not saved. Choose it again before attacking.');
      return;
    }
    // A scope is frozen at edit time, never silently reassigned to a new fight.
    const scope = waiting[0].scope;
    const batch = waiting.filter(e => e.scope === scope).slice(0, 64);
    for (const e of batch) { this.next.delete(e.key); e.inflight = true; }
    this.running = Promise.resolve().then(async () => {
      try {
        const response = await this.send(scope, batch.map(e => e.value));
        for (const e of batch) {
          const current = this.entries.get(e.key);
          if (current?.revision === e.revision) {
            current.baseline = e.value; current.inflight = false; current.acceptedVersion = response?.state_version;
          }
          else if (current) current.baseline = e.value;
        }
        this.pending(scope, false, response);
      } catch (err) {
        for (const e of batch) {
          const current = this.entries.get(e.key);
          if (current?.revision !== e.revision) continue;
          current.value = current.baseline; current.inflight = false;
          this.changed(e.key, current.baseline); this.error(e.key, err);
          this.failedScopes.add(scope);
        }
        this.pending(scope, false, null, err);
      } finally { this.running = null; }
    });
    await this.running;
    return this.flush(onlyScope);
  }
}
