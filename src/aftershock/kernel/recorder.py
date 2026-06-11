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
    """Writes run.json (manifest) and ticks.ndjson (one TickRecord per line)."""

    def __init__(self, out_dir: Path, run_id: str, manifest: dict[str, Any]) -> None:
        self._run_dir = out_dir / run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        (self._run_dir / "run.json").write_text(
            canonical_json(manifest), encoding="utf-8"
        )
        self._ticks_file = (self._run_dir / "ticks.ndjson").open("w", encoding="utf-8")

    def write_tick(self, record: TickRecord) -> None:
        """Append one canonical-JSON line for record, flushed immediately."""
        self._ticks_file.write(canonical_json(record) + "\n")
        self._ticks_file.flush()

    def close(self) -> None:
        self._ticks_file.close()

    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    @property
    def run_dir(self) -> Path:
        return self._run_dir


def load_run(run_dir: Path) -> tuple[dict[str, Any], list[TickRecord]]:
    """Load manifest and all tick records from a run directory."""
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
    return manifest, ticks
