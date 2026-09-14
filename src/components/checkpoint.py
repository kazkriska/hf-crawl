from __future__ import annotations
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class CheckpointManager:
    """Per-phase checkpoint persistence using JSON files."""

    def __init__(self, checkpoint_dir: str, phase: str):
        self._dir = Path(checkpoint_dir) / phase
        self._dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self._dir / "state.json"
        self._failed_path = self._dir / "failed_models.json"
        self._state = self._load_state()
        self._failed = self._load_failed()

    @property
    def cursor(self) -> str | None:
        return self._state.get("cursor")

    @cursor.setter
    def cursor(self, value: str | None):
        self._state["cursor"] = value

    @property
    def page(self) -> int:
        return self._state.get("page", 0)

    @page.setter
    def page(self, value: int):
        self._state["page"] = value

    @property
    def count(self) -> int:
        return self._state.get("count", 0)

    @count.setter
    def count(self, value: int):
        self._state["count"] = value

    @property
    def last_model_id(self) -> str | None:
        return self._state.get("last_model_id")

    @last_model_id.setter
    def last_model_id(self, value: str | None):
        self._state["last_model_id"] = value

    @property
    def total_models(self) -> int | None:
        return self._state.get("total_models")

    @total_models.setter
    def total_models(self, value: int | None):
        self._state["total_models"] = value

    @property
    def failed_models(self) -> list[str]:
        return self._failed

    def has_checkpoint(self) -> bool:
        return self._state_path.exists()

    def _load_state(self) -> dict:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _load_failed(self) -> list[str]:
        if self._failed_path.exists():
            try:
                return json.loads(self._failed_path.read_text())
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def save(self, force: bool = False, save_every: int = 1) -> None:
        """Save state. Only saves if forced or page is a multiple of save_every."""
        if not force and self._state.get("page", 0) % save_every != 0:
            return
        try:
            self._state_path.write_text(json.dumps(self._state, indent=2))
            self._failed_path.write_text(json.dumps(self._failed, indent=2))
        except OSError:
            pass

    def add_failed(self, model_id: str) -> None:
        if model_id not in self._failed:
            self._failed.append(model_id)

    def clear(self) -> None:
        self._state = {}
        self._failed = []
        try:
            self._state_path.write_text("{}")
            self._failed_path.write_text("[]")
        except OSError:
            pass
