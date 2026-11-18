from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from tools.rec1_p1cr1_handoff import validate_handoff_package


def _zip(entries: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return stream.getvalue()


def test_complete_handoff_requires_owner_readable_root_readme() -> None:
    manifest = json.dumps({"status": "REC1_P1CR1_READY_FOR_PHYSICAL_LINUX_OWNER_RESMOKE"}).encode()
    checksums = f"{hashlib.sha256(manifest).hexdigest()}  MANIFEST.json\n".encode()
    with pytest.raises(ValueError, match="README_START_HERE.md"):
        validate_handoff_package(_zip({"MANIFEST.json": manifest, "SHA256SUMS.txt": checksums}))


def test_complete_handoff_accepts_required_root_files() -> None:
    entries = {
        "README_START_HERE.md": b"Start here.\n",
        "MANIFEST.json": b'{"status":"REC1_P1CR1_READY_FOR_PHYSICAL_LINUX_OWNER_RESMOKE"}\n',
    }
    entries["SHA256SUMS.txt"] = b"".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n".encode()
        for name, content in sorted(entries.items())
    )
    assert validate_handoff_package(_zip(entries))["valid"] is True
