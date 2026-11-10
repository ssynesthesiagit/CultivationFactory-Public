// powering_picker.js
// Optimistic, debounced, in-order batched saves for the "Which pool pays" sheet dropdowns
// (owner 2026-09-25, Q19). Consumed by sheet.js's powering panel (renderPowering).
//
// A multi-Path character has more than one cultivation pool (Qi, Stamina, ...) and the player
// picks which pool powers each choosable ability. The pool is baked into the ability's printed
// cost at compile time, so a saved choice takes effect for fights started after it is saved; a
// fight already under way keeps the bundle it began with.
//
// The picker owns the per-action pool choice (action_id -> pool display name, e.g. "Qi") for one
// character. It is inert until `seed` (or `adopt`) has given it the current choices.
//
// Behaviour:
//  * A change is applied to the local choice immediately -- the dropdown already shows it, so the
//    interaction is instant and never blocks on the network.
//  * Several quick changes are coalesced and sent as ONE request after a debounce.
//  * While a request is in flight, further changes queue and go out on the next request, in order.
//  * If the server rejects, the un-acked edits roll back to the last saved choice and the sheet
//    republishes the saved dropdowns; `toast` reports the clear failure message.
//
// sheet.js drives it like this: renderPowering reads picker.choices for the selected pool; a
// dropdown change calls picker.set(); "Set all to ..." calls picker.setAll(); on a successful save
// it schedules a single debounced reloadSheet (so the action list's printed costs catch up once),
// and on rollback it calls renderPowering() to undo the optimistic picks.

export const POWERING_DEBOUNCE_MS = 300;

const DEFAULT_CLOCK = { setTimeout, clearTimeout };

export class PoweringPicker {
  constructor({ choices = null, post, debounceMs = POWERING_DEBOUNCE_MS, clock = null, onSaved, onRollback, toast } = {}) {
    if (typeof post !== "function") throw new Error("PoweringPicker requires a `post` function");
    this.post = post;                       // async (choices: {action_id: pool}) => ackChoices | throws
    this.debounceMs = debounceMs;
    this.clock = clock || DEFAULT_CLOCK;
    this.onSaved = onSaved || (() => {});    // (saved) called after a successful request
    this.onRollback = onRollback || (() => {}); // () called after a rejected request
    this.toast = toast || (() => {});       // (message, ms) called only on rejection
    this.choices = {};                       // current (optimistic) action_id -> pool
    this.saved = {};                         // last server-acknowledged action_id -> pool
    this.pending = {};                       // edits waiting for the next request
    this.inFlight = false;                   // a request is outstanding
    this.timer = null;                       // id of the pending debounce timer
    this._apply = null;                      // promise of the in-flight request (for flush())
    this._seeded = false;
    this._sent = null;                       // the payload of the in-flight request
    if (choices && Object.keys(choices).length) this.seed(choices);
  }

  seed(choices) {
    this.choices = { ...(choices || {}) };
    this.saved = { ...(this.choices) };
    this.pending = {};
    this._seeded = true;
    this._cancelTimer();
  }

  set(actionId, pool) {
    if (!this._seeded || this.choices[actionId] === pool) return false;
    this.choices[actionId] = pool;
    this.pending[actionId] = pool;
    this._schedule();
    return true;
  }

  setAll(pool) {
    if (!this._seeded) return false;
    let changed = false;
    for (const actionId of Object.keys(this.choices)) {
      if (this.choices[actionId] !== pool) {
        this.choices[actionId] = pool;
        this.pending[actionId] = pool;
        changed = true;
      }
    }
    if (changed) this._schedule();
    return changed;
  }

  get hasPending() {
    return Object.keys(this.pending).length > 0 || this.inFlight;
  }

  // Resolves only when every queued save has settled, including edits made while an earlier save was in flight
  // (each settled save drains the next one), so a reload after flush() never renders stale choices.
  async flush() {
    this._cancelTimer();
    this._drain();
    while (this._apply) {
      const current = this._apply;
      await current.catch(() => {});
      if (this._apply === current && !this.inFlight) break;
    }
  }

  adopt(choices) {
    this._cancelTimer();
    this.choices = { ...(choices || {}) };
    this.saved = { ...(this.choices) };
    this.pending = {};
    this._seeded = true;
    // A request may still be in flight; let its handler reconcile on return.
  }

  _schedule() {
    this._cancelTimer();
    this.timer = this.clock.setTimeout(() => {
      this.timer = null;
      this._drain();
    }, this.debounceMs);
  }

  _cancelTimer() {
    if (this.timer != null) {
      this.clock.clearTimeout(this.timer);
      this.timer = null;
    }
  }

  _drain() {
    if (!this._seeded || this.inFlight) return;
    if (Object.keys(this.pending).length === 0) return;
    this.inFlight = true;
    const payload = { ...this.choices };   // the full, coalesced current state
    this._sent = payload;
    this.pending = {};
    this._apply = this.post(payload).then(
      (saved) => {
        this.inFlight = false;
        this.saved = { ...this.saved, ...payload };   // the sent values are now confirmed saved
        this._sent = null;
        this.onSaved(saved);
        this._drain();                       // send anything queued while the request was in flight
      },
      (error) => {
        this.inFlight = false;
        this._rollback(payload);
        this._sent = null;
        this.onRollback();
        this.toast(error?.message ? `Not saved: ${error.message}` : "Not saved: the server rejected your choice.", 3400);
        this._drain();
      },
    );
  }

  // Revert the rejected payload to the last saved values. A dropdown the player changed again while
  // the request was in flight is kept as it is (still pending), so that newer pick goes out next.
  _rollback(payload) {
    for (const actionId of Object.keys(payload)) {
      if (actionId in this.pending) continue;
      if (actionId in this.saved) this.choices[actionId] = this.saved[actionId];
      else delete this.choices[actionId];
    }
  }
}
