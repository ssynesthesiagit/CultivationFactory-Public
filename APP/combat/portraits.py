"""Character tokens for the table (owner 2026-09-27: "Id like to be able to have the ability to put a custom image in and
have it cut a circle making a token, and also use the model to create a token as well").

The sheet's token dialog (static/tabletop/portrait.js) crops an uploaded or generated picture to a circle in the browser
and sends the finished PNG; it is kept per character under <data>/tabletop_tokens/<project_id>.png and drawn on the
character's token at the table. "Make with Anima" asks the owner's local Anima Studio (ComfyUI on 127.0.0.1:8189,
~/.local/opt/anima-character-trial) for a portrait with the graph its accepted trial images used (Anima Turbo v1.1,
768x768, 12 steps; receipts/01_reference_turbo.json), prompted from the character's sheet and the owner's own words.
Generation is local; nothing leaves the machine.
"""

from __future__ import annotations

import json
import os
import re
import struct
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .tabletop import TabletopError, _atomic_write

ANIMA_URL = os.environ.get("TIANXIA_ANIMA_URL", "http://127.0.0.1:8189")
MAX_TOKEN_BYTES = 4 * 1024 * 1024
_PNG = b"\x89PNG\r\n\x1a\n"
NEGATIVE = ("blurry, low quality, malformed hands, extra limbs, duplicate person, multiple people, multiple views, character sheet, "
            "grid, collage, text, calligraphy, kanji, chinese characters, letters, title, logo, watermark, signature, frame, border, "
            "cropped head")
# What a Sphere looks like on a person (the rest are named as an aura of that Sphere).
_SPHERE_LOOKS = {
    "death": "pale bone ornaments, faint ghostly green wisps", "ash": "ash-grey embers drifting around them", "fire": "flickering flame motifs",
    "magma": "glowing molten cracks on dark stone ornaments", "ice": "frost crystals, cold blue breath", "water": "flowing water ribbons",
    "lightning": "crackling blue-white lightning", "air": "wind-swept robes and hair", "earth": "stone and jade ornaments",
    "smoke": "curling grey smoke", "dark": "deep shadows, dim violet light", "radiance": "soft golden radiance", "poison": "green venom sheen",
    "blood": "crimson blood-red accents", "sand": "desert sand and sun-bleached cloth", "ink": "flowing black calligraphy ink",
    "sword": "an elegant jian sword", "sabers": "a curved dao saber", "spear": "a long spear", "axes": "a heavy war axe",
    "iron fist": "wrapped iron-knuckled fists", "music": "a guqin or bamboo flute", "beauty": "graceful ornate silk and flowers",
    "flowers": "blossoms woven in the hair", "verdant growth": "leaves and vines", "stars": "starlight motifs", "moon": "silver moonlight",
    "yin": "cool silver-black tones", "yang": "warm golden-red tones", "puppetry": "fine puppet strings", "glass": "shards of glass",
    "wax": "melted candle wax and candlelight", "unmaking": "void-black cracks of light", "beastmastery": "a beast companion's fur trim",
}


def png_size(raw: bytes) -> tuple[int, int]:
    """(width, height) of a PNG, or TabletopError when it isn't one."""
    if len(raw) < 24 or raw[:8] != _PNG or raw[12:16] != b"IHDR":
        raise TabletopError("TABLETOP_TOKEN_INVALID", "A token must be a PNG image.", 422)
    return struct.unpack(">II", raw[16:24])


class TokenStore:
    """Round tokens (512 px) -- and, with ``kind="picture"``, the character's full picture the token is cut from
    (owner 2026-09-27: "I think we should do a full picture in creation ... the token can be created from the main
    picture. Probably just a little circle frame we can put over the head part")."""

    def __init__(self, root: Path, kind: str = "token"):
        self.root = Path(root)
        self.kind = kind

    def path(self, project_id: str) -> Path:
        if not re.match(r"^[0-9a-f-]{8,64}$", project_id or ""):
            raise TabletopError("CHARACTER_UNKNOWN", "Unknown character.", 404)
        return self.root / f"{project_id}.png"

    def save(self, project_id: str, raw: bytes, *, overwrite: bool = True) -> str:
        """Save a PNG; ``overwrite=False`` atomically preserves a concurrent owner's save."""
        limit = MAX_TOKEN_BYTES * (3 if self.kind == "picture" else 1)
        if not raw or len(raw) > limit:
            raise TabletopError("TABLETOP_TOKEN_INVALID", f"A {self.kind} image must be at most {limit // (1024 * 1024)} MB.", 422)
        width, height = png_size(raw)
        if not (64 <= width <= 4096 and 64 <= height <= 4096):
            raise TabletopError("TABLETOP_TOKEN_INVALID", f"A {self.kind} must be between 64 and 4096 pixels across.", 422)
        self.root.mkdir(parents=True, exist_ok=True)
        if overwrite:
            _atomic_write(self.path(project_id), raw)
        else:
            # Publish a complete image with link(2)'s atomic no-replace semantics.
            descriptor, name = tempfile.mkstemp(dir=self.root, prefix=".token-")
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(temporary, self.path(project_id))
                except FileExistsError:
                    pass
            finally:
                temporary.unlink(missing_ok=True)
        return self.url(project_id) or ""

    def delete(self, project_id: str) -> None:
        self.path(project_id).unlink(missing_ok=True)

    def url(self, project_id: str) -> str | None:
        path = self.path(project_id)
        return f"/api/tabletop/characters/{project_id}/{self.kind}.png?v={path.stat().st_mtime_ns}" if path.is_file() else None


FRAMINGS = {  # the full picture's framing -> (words, width, height)
    "portrait": ("character token portrait, head and shoulders, face centered, looking at viewer", 768, 768),
    "upper": ("character art, upper body, waist up, three-quarter view, face clearly visible", 768, 1152),
    "full": ("character art, full body, standing, whole figure visible from head to feet", 768, 1152),
}


def portrait_prompt(sheet: dict[str, Any], look: str | None = None, framing: str = "portrait") -> str:
    """An anime picture of the character, from its sheet and the owner's own words (``look`` comes first: it wins)."""
    identity = sheet.get("identity") or {}
    block = sheet.get("spheres_and_talents") or {}
    spheres = [str(sphere).split(".")[-1].replace("_", " ") for sphere in block.get("sphere_record_ids") or []]
    cues = [_SPHERE_LOOKS.get(name) or f"a subtle {name} aura" for name in spheres[:3]]
    species = str(identity.get("species") or "human").lower()
    title = str(identity.get("title") or "").strip()
    concept = re.sub(r"\s+", " ", str(identity.get("concept") or "")).strip()
    parts = ["anime illustration", "solo", "single character", FRAMINGS.get(framing, FRAMINGS["portrait"])[0],
             *([look.strip()] if look and look.strip() else []), f"{species} xianxia cultivator",
             *([f"known as {title}"] if title else []), *cues,
             *([concept[:220]] if concept else []), "traditional hanfu robes",
             "simple dark background" if framing == "portrait" else "atmospheric xianxia background", "soft rim light", "detailed face"]
    return ", ".join(part for part in parts if part)


def _graph(prompt: str, seed: int, size: int = 768, prefix: str = "tianxia_token", height: int | None = None) -> dict[str, Any]:
    """The text-to-image graph of the accepted Anima trial (receipts/01_reference_turbo.json)."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "anima-turbo-v1.1.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen_3_06b_base.safetensors", "type": "stable_diffusion", "device": "cpu"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": NEGATIVE}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {"width": size, "height": height or size, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
                                                   "seed": int(seed), "steps": 12, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecodeTiled", "inputs": {"samples": ["7", 0], "vae": ["3", 0], "tile_size": 256, "overlap": 64,
                                                         "temporal_size": 16, "temporal_overlap": 4}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": prefix}},
    }


def _call(url: str, body: dict[str, Any] | None = None, *, timeout: float = 15.0, raw: bool = False) -> Any:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                     headers={"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - the owner's local Anima server
        data = response.read()
    return data if raw else json.loads(data)


def anima_generate(prompt: str, seed: int, *, base_url: str = ANIMA_URL, timeout: float = 240.0, framing: str = "portrait") -> bytes:
    """One picture from Anima Studio: queue the graph, wait for it, fetch the PNG."""
    _, width, height = FRAMINGS.get(framing, FRAMINGS["portrait"])
    graph = _graph(prompt, seed, width, "tianxia_token" if framing == "portrait" else "tianxia_picture", height)
    try:
        queued = _call(f"{base_url}/prompt", {"prompt": graph, "client_id": f"tianxia-{uuid.uuid4().hex[:12]}"})
    except (urllib.error.URLError, OSError) as exc:
        raise TabletopError("TABLETOP_ANIMA_UNAVAILABLE",
                            "Anima Studio isn't running (127.0.0.1:8189). Start it with: systemctl --user start anima-character-trial", 503) from exc
    prompt_id = queued.get("prompt_id")
    if not prompt_id:
        raise TabletopError("TABLETOP_ANIMA_FAILED", f"Anima did not accept the job: {json.dumps(queued)[:300]}", 502)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        history = _call(f"{base_url}/history/{prompt_id}", timeout=10.0).get(prompt_id) or {}
        status = history.get("status") or {}
        if status.get("status_str") == "error":
            raise TabletopError("TABLETOP_ANIMA_FAILED", "Anima could not make the image (see its console).", 502)
        for output in (history.get("outputs") or {}).values():
            for image in output.get("images") or []:
                query = urllib.parse.urlencode({"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "output")})
                return _call(f"{base_url}/view?{query}", timeout=30.0, raw=True)
    raise TabletopError("TABLETOP_ANIMA_TIMEOUT", "Anima took too long; try again once it has warmed up.", 504)
