# R6.6 Battle Map Visual History — Native Windows Source Change List

This bounded successor preserves the R6.5 Gate 5.1 combat engine, journal authority, hostile-target correction, Hold suppression, WebView2 host, 90-second initialization allowance, clean shutdown checks, and Windows-safe evidence paths.

R6.6 adds only:

- an explicit visual manifest under `static/combat_visuals`; provenance-uncertain legacy raster art is excluded and the UI uses the CSS-grid/initials fallback;
- a visual-only manifest with centered square-art calibration and initials fallback;
- a read-only `/api/combat/matches/{match_id}/history` endpoint reconstructed from genesis plus ordered COMMIT records through the existing Gate 3 reducer;
- an owner-facing replay slider, previous/next controls, round/turn jump list, explicit Return to Live mode, and recorded mechanical feed;
- focused R6.6 tests and native packaging checks for the new assets and history surface.

No owner UserData belongs in the source or build-execution package. Native Windows and owner acceptance remain unclaimed until performed on the returned build.

## R6.6.3 native runtime correction

- launcher-state JSON publication now uses a unique same-directory temporary file, flushes and closes it before replacement, and retains atomic replacement;
- only transient Windows sharing/access replacement errors are retried for a short bounded interval with backoff;
- persistent or unrelated filesystem failures are re-raised and owned temporary files are cleaned without touching unrelated files;
- a secondary failure while publishing `FAILED` is logged without masking the original startup diagnostic;
- the native acceptance reader remains tolerant of a temporarily unavailable or not-yet-valid state file.

No combat, character, visual asset, replay, storage identity, WebView2 host, or external `UserData` behavior changed.

## R6.6.5 Sphere/Talent authority correction

- Adds a pinned-source-backed `catalog/sphere_talent_authority_v1.json` classification manifest.
- Enforces genuine selectable Talent roles and exact Sphere relationships in `catalog/service.py`.
- Adds honest per-Sphere authority coverage and legacy non-Talent draft findings in `character_builder/service.py`.
- Updates the owner-facing Sphere/Talent workspace without altering combat, launcher, storage, replay, battle-map, or token behavior.
- Adds focused R6.6.5 authority tests to the native Windows build test list.
