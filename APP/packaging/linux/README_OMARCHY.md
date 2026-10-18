# CultivationFactory on Omarchy

This is the native Linux/source installation route. Omarchy is Arch-based and
normally includes Git and Chromium. The Factory binds only to `127.0.0.1`; it
does not expose the application or the model server to the LAN.

## Fresh installation

Clone the private repository, check out the owner branch, then run:

```bash
cd CultivationFactory
./APP/packaging/linux/install-omarchy.sh --check
./APP/packaging/linux/install-omarchy.sh --systemd-user
./APP/packaging/linux/run-factory.sh --open-browser
```

The installer uses `uv` to create a repository-local Python 3.12 environment,
installs the pinned dependencies, verifies both bundled ZIP files by SHA-256,
initializes the authenticated Factory/catalog in persistent owner state, and
optionally installs a systemd user service. It never installs Lemonade, model
weights, credentials, or a network-facing service.

If `uv` is absent, install it through Omarchy's package menu or:

```bash
omarchy pkg add uv
```

Omarchy normally provides Chromium. If it was removed:

```bash
omarchy pkg add chromium
```

The optional user service is installed but not started automatically:

```bash
systemctl --user start cultivation-factory
systemctl --user status cultivation-factory
journalctl --user -u cultivation-factory -f
```

## Persistent state

The default writable root is:

```text
~/.local/state/cultivation-factory
```

Override it with `TIANXIA_FOUNDRY_DATA`. The security directory defaults to a
mode-`0700` child named `security` and can be placed elsewhere with
`TIANXIA_FOUNDRY_SECURITY_DIR`. Do not put either directory inside the Git
checkout. Repository `.gitignore` rules intentionally exclude databases,
characters, exports, logs, credentials, screenshots, and model files.

## Gemma-only Local AI

Run the Gemma OpenAI-compatible server separately. In Factory, use **Local AI
Detect** and select the loopback endpoint and exact advertised model. Prefer a
native Linux endpoint such as `http://127.0.0.1:11437/v1`; retain `11438` only
if a separate loopback adapter is still required. The expected current model
ID is `gemma4-26b-a4b`.

Do not start or select Lemonade. Do not place a bearer token in this repository,
shell history, service template, logs, or migration archive. Linux does not use
the Windows DPAPI saved-key store; local endpoints should remain token-free, or
receive any required credential through a private runtime-only environment.

## Moving owner data from Windows

Git carries source and authenticated installation artifacts, not owner runtime
state. Before leaving Windows:

1. Stop Factory, the loopback adapter, and Gemma cleanly.
2. Preserve the complete persistent Factory data root, not anything under
   `/tmp`. Keep the database, security state, portable characters, exports,
   evidence, and retained package hashes together.
3. Preserve the external handoff and evidence directory separately from Git.
4. Copy the stopped data root to the Linux persistent root using a filesystem
   method that preserves bytes and filenames. Do not merge two live data roots.
5. Keep the Windows copy unchanged until Linux `/api/health`, Character Library,
   package import/reopen, and accepted-run identity have been verified.

The Windows DPAPI credential store is intentionally not portable. Configure the
Gemma loopback endpoint again on Linux rather than copying protected tokens.

## First Linux acceptance

After launch, verify:

```bash
curl --fail --silent http://127.0.0.1:8765/api/health
```

Then confirm the response reports
`CANONICAL_CATALOG_PRODUCT_INTEGRATION_READY`, detect Gemma without sending a
completion, open the retained Character Sheet, and verify package hashes before
any new build. A real Gemma character smoke is a later explicit owner action;
installation verification must remain provider-free.
