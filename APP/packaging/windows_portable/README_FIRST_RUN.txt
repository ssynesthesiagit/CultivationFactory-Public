TIANXIA CURRENT OWNER TEST — FIRST RUN

1. Keep the complete "Tianxia Factory" folder together.
2. Double-click "START_TIANXIA_CURRENT_OWNER_TEST.cmd", or use the desktop
   shortcut named "Tianxia Current Owner Test".
3. A dedicated window titled "Tianxia Current Owner Test" opens. It does not
   use your normal browser.
4. Wait while the local Factory, database, catalog, and content registry start.
5. Open Character Sheets. Use Import Character ZIP to drag a portable Character
   ZIP from anywhere on the computer, or select it with Choose ZIP. Preview
   before importing.
6. Browse Rules, Manage Content, and Advanced Status always show content,
   initialization, empty, or recoverable error states rather than a blank panel.
7. Close the main window when finished; this also stops the loopback service.

The local service binds only to 127.0.0.1.

OWNER DATA

The owner-test launcher forces persistent data to:

    OwnerTestData

This directory is inside the staged owner-test folder beside the launcher. The
launcher does not use an existing installation, production UserData, or the
default `%LOCALAPPDATA%\Tianxia Factory` location. Paths with spaces and
non-ASCII user names are supported.

Back up the complete OwnerTestData folder if you want to retain test work.
Replacing Runtime or BundledContent must never replace it.

The Microsoft Edge WebView2 Runtime must already be installed. When unavailable,
Tianxia Factory reports a repair message instead of silently opening a browser.
Optional AI provider operation remains off until configured.

For startup problems, collect:

    OwnerTestData\Logs\Tianxia_Factory_Launcher.log
    OwnerTestData\Logs\launcher_state.json
