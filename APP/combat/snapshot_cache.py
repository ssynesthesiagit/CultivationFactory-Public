"""Bounded JSON projections for unchanged table reads; never caches engines.

Used only by TabletopService's compact state path. Saved inputs, display/control
sidecars, editable combat sources and the requested fog audience form the key.
Source edits, commits, restored saves, pending prompts and token changes invalidate
the projection. JSON decoding gives each caller independent mutable containers.
"""
from collections import OrderedDict
import json
from pathlib import Path
import threading


class SnapshotCache:
    def __init__(self, source_root, data_root):
        self.source_root, self.data_root = Path(source_root), Path(data_root)
        self.rows = OrderedDict()
        self.lock = threading.Lock()

    @staticmethod
    def _stamps(root, suffixes):
        stamps = []
        for path in sorted(root.rglob('*')):
            if path.suffix not in suffixes or '__pycache__' in path.parts:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            stamps.append((str(path), stat.st_size, stat.st_mtime_ns, stat.st_ino))
        return tuple(stamps)

    def key(self, combat, match_id, fog, fog_view, fog_actor_ids):
        sources = tuple(self._stamps(self.source_root / name, {'.py', '.json'})
                        for name in ('combat', 'combat_gate1', 'combat_gate4', 'authority'))
        displays = tuple(self._stamps(self.data_root / name, {'.json', '.png', '.jpg', '.webp'})
                         for name in ('tabletop_buttons', 'tabletop_tokens', 'tabletop_auto_tokens',
                                      'tabletop_pictures'))
        packages = self._stamps(self.data_root / 'portable_characters', {'.zip'})
        artwork = self._stamps(self.source_root / 'static/tabletop/summon_tokens', {'.png'})
        directory = combat._match_dir(match_id)
        sidecars = tuple(stamp for stamp in self._stamps(directory, {'.json'})
                         if Path(stamp[0]).name != 'Manifest.json')
        return (match_id, combat._fingerprint(match_id), sidecars, sources, displays, packages, artwork,
                fog, fog_view, tuple(sorted(fog_actor_ids)))

    def get(self, key):
        with self.lock:
            value = self.rows.get(key)
            if value is None:
                return None
            self.rows.move_to_end(key)
        return json.loads(value)

    def put(self, key, result):
        value = json.dumps(result, ensure_ascii=False, separators=(',', ':'))
        if len(value) > 2_000_000:
            return
        with self.lock:
            self.rows[key] = value
            self.rows.move_to_end(key)
            while len(self.rows) > 8:
                self.rows.popitem(last=False)
