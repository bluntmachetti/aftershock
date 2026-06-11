"""Canonical JSON, content digests, and NDJSON run records.

The single source of truth for hashing is canonical_json. Every tick writes
one line to ticks.ndjson, flushed immediately for crash safety.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from aftershock.kernel.protocol import TickRecord


def canonical_json(obj: Any) -> str:
    """Serialize obj to compact, sorted-key JSON.

    Pydantic models are serialized via model_dump(mode="json"). Dicts use
    sorted keys recursively. ensure_ascii=True for byte-stable hashing.
    """
    if isinstance(obj, BaseModel):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(obj: Any) -> str:
    """SHA-256 hexdigest of canonical_json(obj)."""
    return hashlib.sha256(canonical_json(obj).encode()).hexdigest()


class Recorder:
    """Writes run.json (manifest), ticks.ndjson (one TickRecord per line),
    and world.ndjson (one world-state dict per line)."""

    def __init__(self, out_dir: Path, run_id: str, manifest: dict[str, Any]) -> None:
        self._run_dir = out_dir / run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        (self._run_dir / "run.json").write_text(
            canonical_json(manifest), encoding="utf-8"
        )
        self._ticks_file = (self._run_dir / "ticks.ndjson").open("w", encoding="utf-8")
        self._world_file = (self._run_dir / "world.ndjson").open("w", encoding="utf-8")

    def write_tick(self, record: TickRecord, world_state: dict[str, Any] | None = None) -> None:
        """Append one canonical-JSON line for record, flushed immediately.

        If world_state is provided, also appends a line to world.ndjson.
        The caller should pass the already-computed world_state dict so we
        never recompute it here.
        """
        self._ticks_file.write(canonical_json(record) + "\n")
        self._ticks_file.flush()
        if world_state is not None:
            line = canonical_json({"tick": record.tick, "state": world_state})
            self._world_file.write(line + "\n")
            self._world_file.flush()

    def close(self) -> None:
        self._ticks_file.close()
        self._world_file.close()

    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @property
    def run_dir(self) -> Path:
        return self._run_dir


def load_run(
    run_dir: Path,
) -> tuple[dict[str, Any], list[TickRecord], list[dict[str, Any]] | None]:
    """Load manifest, tick records, and optional world states from a run directory.

    Returns:
        (manifest, ticks, worlds) where worlds is a list of world-state dicts
        when world.ndjson is present, or None when absent (old run dirs load fine).
    """
    manifest: dict[str, Any] = json.loads(
        (run_dir / "run.json").read_text(encoding="utf-8")
    )
    ticks: list[TickRecord] = []
    ndjson_path = run_dir / "ticks.ndjson"
    if ndjson_path.exists():
        for line in ndjson_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                ticks.append(TickRecord.model_validate_json(line))

    worlds: list[dict[str, Any]] | None = None
    world_path = run_dir / "world.ndjson"
    if world_path.exists():
        worlds = []
        for line in world_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                worlds.append(json.loads(line))

    return manifest, ticks, worlds
