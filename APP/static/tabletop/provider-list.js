// Installed-model list for the fight setup "Who plays" menus (SEATLIST1, owner 2026-10-18).
// A failed fetch is not the same as "no models configured": keep the last good list when there is one; when there
// is none, say so (state.unavailable) and retry after 2 s, 5 s, then every 10 s until a fetch succeeds.
// A successful empty list is final: no models, no warning, no retry.
// Used by: tabletop.js (loadProviders, refreshSetupProviders). Fetch, timers and change callback are injected, so the
// node test (tests/test_seat_list_retry.py) runs it without a browser.
export const RETRY_DELAYS_MS = [2000, 5000, 10000];

export function createProviderList({fetchProviders, onChange = () => {}, setTimer = setTimeout, clearTimer = clearTimeout, delays = RETRY_DELAYS_MS}) {
  const state = {providers: [], known: false, unavailable: false, attempt: 0, timer: null};
  const stopRetry = () => { if (state.timer !== null) { clearTimer(state.timer); state.timer = null; } };
  const scheduleRetry = () => {
    const delay = delays[Math.min(state.attempt, delays.length - 1)];
    state.attempt += 1;
    state.timer = setTimer(() => { state.timer = null; return load(); }, delay);
  };
  // Resolves after this attempt (not after retries). Never rejects.
  async function load() {
    stopRetry();
    let providers = null;
    try {
      const response = await fetchProviders();
      if (Array.isArray(response?.providers)) providers = response.providers;
    } catch { providers = null; }
    if (providers) {
      Object.assign(state, {providers, known: true, unavailable: false, attempt: 0});
    } else if (!state.known) {
      state.unavailable = true;
      scheduleRetry();
    }
    onChange(state);
    return state;
  }
  return {state, load};
}
