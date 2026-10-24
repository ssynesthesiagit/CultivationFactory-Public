from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .diagnostics import RecoveryDisposition, error
from .gate4_models import LocalControllerPolicy
from .gate2_runtime_content import AN, LEE, LING, BAI, CUI


POLICY_FILENAMES = {
    AN: "an_eui_local_controller_policy.json",
    LEE: "lee_jia_local_controller_policy.json",
    LING: "ling_qi_local_controller_policy.json",
    BAI: "bai_meizhen_local_controller_policy.json",
    CUI: "bai_meizhen_local_controller_policy.json",
}
FALLBACK_FILENAME = "generic_fallback_policy.json"


class PolicyLibrary:
    def __init__(self, source_root: Path, *, actor_policy: Callable[[str], dict | None] | None = None):
        self.source_root = Path(source_root)
        self.policy_root = self.source_root / "combat_gate4/policies"
        self._cache: dict[str, LocalControllerPolicy] = {}
        # Factory characters have no bespoke file; their policy is derived
        # from their Dao (factory_authoring.sphere_dao.controller_policy).
        self._actor_policy = actor_policy

    def _load(self, filename: str) -> LocalControllerPolicy:
        if filename in self._cache:
            return self._cache[filename]
        path = self.policy_root / filename
        try:
            policy = LocalControllerPolicy.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError:
            raise error(
                "CONTROLLER_POLICY_MISSING_USING_FALLBACK",
                f"Controller policy file is missing: {filename}",
                phase="CONTROLLER_POLICY_LOAD", subsystem="GATE4_CONTROLLER",
                recommended_action="Install the bespoke policy or use the generic fallback.",
                recovery=RecoveryDisposition.CONTINUE,
            )
        except Exception as exc:
            raise error(
                "CONTROLLER_POLICY_INVALID", str(exc),
                phase="CONTROLLER_POLICY_LOAD", subsystem="GATE4_CONTROLLER",
                recommended_action="Correct the typed policy file and retry.",
            )
        self._cache[filename] = policy
        return policy

    def fallback(self) -> LocalControllerPolicy:
        return self._load(FALLBACK_FILENAME)

    def for_actor(self, actor_id: str) -> tuple[LocalControllerPolicy, bool]:
        filename = POLICY_FILENAMES.get(actor_id)
        if filename is None:
            derived = None
            if self._actor_policy is not None:
                try:
                    document = self._actor_policy(actor_id)
                    derived = LocalControllerPolicy.model_validate(document) if document else None
                except Exception:
                    derived = None
            return (derived, False) if derived is not None else (self.fallback(), True)
        try:
            return self._load(filename), False
        except Exception:
            return self.fallback(), True
