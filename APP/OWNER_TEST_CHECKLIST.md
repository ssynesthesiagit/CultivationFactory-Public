# Tianxia current owner-test checklist

## Safety

- Confirm the shortcut says `Tianxia Current Owner Test`.
- Confirm the title or About surface identifies an owner-test build.
- Confirm the data directory is `OwnerTestData`, not the existing production
  UserData.
- Keep the existing Tianxia installation closed during testing.

## Character creation

### Manual Chat

1. Create or open the bundled current fixture project.
2. Select `Manual Chat — no API key required`.
3. Generate the complete request ZIP.
4. Load the bundled accepted response.
5. Review the complete candidate.
6. Confirm the project has not committed before Finalize.
7. Test Finalize, Revise Plan, and Cancel on separate disposable copies.

### Standard API

1. Open provider settings.
2. Confirm the API key is hidden after entry.
3. Build a preview.
4. Confirm no commit occurs before Finalize.
5. Confirm errors are readable if no provider/key is configured.

### Auto-Finalize

1. Confirm it is off by default.
2. Confirm explicit opt-in is required.
3. Confirm a warning or blocker falls back to review.
4. Confirm a clean bundled deterministic test can finalize.

## Completed Character and GM Screen

1. Import the bundled current ordinary Character ZIP.
2. Reimport it and confirm identical/idempotent handling.
3. Open it in the bundled GM Screen.
4. Confirm the character is populated rather than blank.
5. Check the 18 tabs.
6. Save and reopen.

## Combat smoke

1. Import the accepted runtime-ready Fire/Qi package.
2. Confirm it registers as Combat Ready.
3. Open Create New Fight.
4. Confirm Manual is the default.
5. Do not run a long battle during the first UI review.
6. Open the accepted completed historical match and confirm it is read-only.

## Owner workflow and polish

- Check contrast, hover, selected, disabled, warning, error, and success states.
- Confirm Xiang says `Stage 1 Plan Sealed`.
- Confirm Developer/Diagnostics is hidden by default.
- Confirm Advanced Details is read-only.
- Test native Save As destinations.
- Record confusing labels, missing descriptions, awkward steps, and anything
  that feels too technical.

## Removal

Close the test application, remove the desktop shortcut, and delete only the
isolated owner-test application folder and OwnerTestData folder.
