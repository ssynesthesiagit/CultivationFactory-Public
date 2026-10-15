"""Optional artwork after a committed Factory build; never part of its transaction.

Uses the installed owner sheet and the same prompt/generator/stores as the table.
Publication takes the finalize lock so another finalize's snapshot/restore cannot
interleave with our saves. Anima work itself never holds that lock or uses the DB.
"""

from __future__ import annotations

import io
import json
import logging
import os
import secrets
import threading
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from combat import portraits
from combat.tabletop import ButtonStore, _atomic_write

LOG = logging.getLogger(__name__)
HEAD = {"x": 0.5, "y": 0.42, "r": 0.36}


def enabled() -> bool:
    return os.environ.get("TIANXIA_AUTO_TOKEN", "1").strip().lower() not in {"0", "false", "no", "off"}


def reachable() -> bool:
    """Bound wall time too: DNS/redirects need not respect urllib's socket timeout."""
    done = threading.Event()
    available = []

    def probe() -> None:
        try:
            with urllib.request.urlopen(f"{portraits.ANIMA_URL.rstrip('/')}/system_stats", timeout=0.5):
                available.append(True)
        except Exception:
            pass
        finally:
            done.set()

    try:
        threading.Thread(target=probe, name="auto-token-probe", daemon=True).start()
    except Exception:
        return False
    return done.wait(0.75) and bool(available)


def circle_token(raw: bytes, *, circle: dict[str, float] | None = None) -> bytes:
    """portrait.js cut(): portrait HEAD circle, transparent 512px RGBA PNG.

    Pillow's resampling/edge antialiasing differs from Canvas; geometry, size,
    alpha and format match. No border is drawn by the browser's save path.
    """
    from PIL import Image, ImageDraw

    with Image.open(io.BytesIO(raw)) as source:
        width, height = source.size
        x, y, radius = (HEAD["x"] * width, HEAD["y"] * height, HEAD["r"] * width) if circle is None else (
            circle["x"] * width, circle["y"] * width, circle["r"] * width)
        image = source.convert("RGBA").resize(
            (512, 512), Image.Resampling.BICUBIC,
            box=(x - radius, y - radius, x + radius, y + radius),
        )
    mask = Image.new("L", (2048, 2048))
    ImageDraw.Draw(mask).ellipse((0, 0, 2047, 2047), fill=255)
    mask = mask.resize((512, 512), Image.Resampling.LANCZOS)
    from PIL import ImageChops

    image.putalpha(ImageChops.multiply(image.getchannel("A"), mask))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _status_path(root: Path, project_id: str) -> Path:
    # Reuse TokenStore's project-id validation for all paths, including status.
    return portraits.TokenStore(root / "tabletop_auto_tokens").path(project_id).with_suffix(".json")


def _status(root: Path, project_id: str, note: str) -> None:
    _atomic_write(_status_path(root, project_id), json.dumps({"note": note}).encode())


def add_notes(root: Path, result: dict[str, Any]) -> None:
    """Expose eventual job outcome on finalized-run reloads without changing its receipt."""
    try:
        pid = result["project_id"]
        path = _status_path(Path(root), pid)
        note = json.loads(path.read_text())["note"] if path.is_file() else None
        if portraits.TokenStore(Path(root) / "tabletop_tokens").url(pid):
            note = "Token: made with Anima" if note == "Token: made with Anima" else "Token: saved; shown on the sheet and table"
        if note:
            result["notes"] = [*(result.get("notes") or []), note]
    except Exception:
        LOG.exception("Could not read automatic token note")


def _work(root: Path, project_id: str, lock: Any) -> None:
    try:
        tokens = portraits.TokenStore(root / "tabletop_tokens")
        with lock:
            if tokens.url(project_id):
                return
        if not reachable():
            LOG.info("Automatic token skipped: Anima not running (%s)", project_id)
            with lock:
                _status(root, project_id, "Token: Anima not running, make one from the sheet")
            return
        with lock:
            # Installed by the production release before finalize returns. No
            # database connection or full combat-service startup in this thread.
            with zipfile.ZipFile(root / "portable_characters" / project_id / "current.zip") as package:
                sheet = json.loads(package.read("Tianxia_Owner_Character_Sheet_v1.json"))
            look = ButtonStore(root / "tabletop_buttons").get(project_id).get("token_look")
        raw = portraits.anima_generate(portraits.portrait_prompt(sheet, look, "portrait"),
                                      secrets.randbelow(2**31), framing="portrait")
        cropped = circle_token(raw)
        with lock:
            if tokens.url(project_id):
                return
            pictures = portraits.TokenStore(root / "tabletop_pictures", kind="picture")
            # Keep an existing picture for re-cutting; do not replace owner art.
            # If it exists, crop that picture instead so picture and token agree.
            pictures.save(project_id, raw, overwrite=False)
            saved_picture = pictures.path(project_id).read_bytes()
            width, height = portraits.png_size(saved_picture)
            buttons = ButtonStore(root / "tabletop_buttons")
            circle = {**HEAD, "y": round(HEAD["y"] * height / width, 4)}
            if saved_picture != raw:
                # Reopen the original picture at its remembered circle, or the
                # dialog's square/upper-body default when no circle was saved.
                circle = buttons.get(project_id).get("token_circle") or (
                    circle if abs(width - height) < 8 else {"x": 0.5, "y": round(0.21 * height / width, 4), "r": 0.19})
                cropped = circle_token(saved_picture, circle=circle)
            tokens.save(project_id, cropped, overwrite=False)
            if tokens.path(project_id).read_bytes() != cropped:
                return  # A concurrent manual save won; keep its circle too.
            # The saved coordinates use width for y, as portrait.js saveToken does.
            buttons.save_token_look(project_id, buttons.get(project_id).get("token_look") or "",
                                    circle=circle)
            _status(root, project_id, "Token: made with Anima" if saved_picture == raw else "Token: saved from the existing picture")
        LOG.info("Automatic token saved with Anima (%s)", project_id)
    except Exception:
        LOG.exception("Automatic token failed (%s); finalized character is unchanged", project_id)
        try:
            with lock:
                _status(root, project_id, "Token: could not make one with Anima, make one from the sheet")
        except Exception:
            LOG.exception("Could not save automatic token note (%s)", project_id)


def start(root: Path, result: dict[str, Any], lock: Any) -> None:
    """Called ONLY after successful finalize; even thread startup is best effort."""
    try:
        if not enabled():
            return
        root = Path(root)
        pid = result["project_id"]
        if portraits.TokenStore(root / "tabletop_tokens").url(pid):
            return
        worker = threading.Thread(target=_work, args=(root, pid, lock), name=f"auto-token-{pid}", daemon=True)
        worker.start()
        result["notes"] = [*(result.get("notes") or []), "Token: Anima will make one in the background if running; reload the sheet to see it"]
    except Exception:
        LOG.exception("Could not start automatic token; finalized character is unchanged")
