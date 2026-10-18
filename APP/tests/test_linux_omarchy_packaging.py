from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINUX = ROOT / "packaging" / "linux"


def test_omarchy_shell_entrypoints_are_syntax_valid_and_owner_safe() -> None:
    scripts = [LINUX / "install-omarchy.sh", LINUX / "run-factory.sh"]
    for script in scripts:
        if os.name == "nt":
            translated = subprocess.run(
                ["wsl.exe", "wslpath", "-a", str(script)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            subprocess.run(["wsl.exe", "bash", "-n", translated], check=True)
        else:
            subprocess.run(["bash", "-n", str(script)], check=True)
        source = script.read_text(encoding="utf-8")
        assert "set -euo pipefail" in source
        assert "rm -rf" not in source
        assert "0.0.0.0" not in source
        assert "bearer" not in source.lower()
        assert "token=" not in source.lower()


def test_linux_launcher_uses_persistent_private_state_and_loopback_only() -> None:
    launcher = (LINUX / "run-factory.sh").read_text(encoding="utf-8")
    assert "XDG_STATE_HOME" in launcher
    assert "TIANXIA_FOUNDRY_DATA" in launcher
    assert "TIANXIA_FOUNDRY_SECURITY_DIR" in launcher
    assert "chmod 700" in launcher
    assert "--host 127.0.0.1" in launcher
    assert "TIANXIA_FACTORY_PORT:-8765" in launcher
    ignore = (ROOT.parent / ".gitignore").read_text(encoding="utf-8")
    assert ".venv/" in ignore
    assert "runtime_data/" in ignore


def test_omarchy_installer_verifies_bundled_authority_and_keeps_models_external() -> None:
    installer = (LINUX / "install-omarchy.sh").read_text(encoding="utf-8")
    assert "sha256sum --check --status" in installer
    assert "requirements/requirements.txt" in installer
    assert "uv python install" in installer
    assert "ProductBootstrapService" in installer
    assert "omarchy pkg add uv" in installer
    assert "lemonade" not in installer.lower()


def test_user_service_is_local_owner_scoped_and_not_auto_started() -> None:
    service = (LINUX / "cultivation-factory.service.in").read_text(encoding="utf-8")
    installer = (LINUX / "install-omarchy.sh").read_text(encoding="utf-8")
    assert "WantedBy=default.target" in service
    assert "NoNewPrivileges=true" in service
    assert "UMask=0077" in service
    assert "systemctl --user daemon-reload" in installer
    assert "systemctl --user enable" not in installer
    assert not any(
        line.lstrip().startswith("systemctl --user start")
        for line in installer.splitlines()
    )


def test_migration_document_excludes_git_runtime_state_and_reauthorizes_local_ai() -> None:
    guide = (LINUX / "README_OMARCHY.md").read_text(encoding="utf-8")
    assert "not anything under\n   `/tmp`" in guide
    assert "Do not merge two live data roots" in guide
    assert "Windows DPAPI credential store is intentionally not portable" in guide
    assert "gemma4-26b-a4b" in guide
    assert "Do not start or select Lemonade" in guide
    assert "provider-free" in guide
