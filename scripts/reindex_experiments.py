#!/usr/bin/env python3
"""Cross-experiment index: walk bench/results/* -> bench/results/index.json.

Stdlib-only, read-only over the result JSONs. One row per experiment directory,
read DEFENSIVELY (older pre-hardening / pre-stamp files lack keys like ``verdict``,
``ablate``, ``ci_excludes_zero``, ``lives_per_dollar``, ``mean_team_alignment``,
``arm`` — every access is guarded, so a missing key never crashes the walk).

Honesty contract (mirrors the bench's own discipline):
  * verdict stays the literal enum (noise/suggestive/credible) or ``null`` — a
    pre-hardening ablation that never carried a verdict is recorded as ``null``
    with a ``verdict_note`` ("pre-2026-06-16-hardening"), never coerced to "noise".
  * conformance / mean_team_alignment is kept as a SEPARATE field from lives —
    the two signals are never collapsed into one number.
  * cloud (dashscope-intl) and local (ollama-k12) rows stay distinguishable via
    the required ``model_endpoint`` field; they are never merged.
  * a referenced experiment dir whose run RECORDS (ticks.ndjson) are not committed
    is recorded with ``records_committed: false`` rather than dropped or crashed
    (e.g. the FIELD-NOTES §22 local-k12 runs runs/bench-1.7b, runs/run-9b are not
    in the repo).

Run from the repo root:  python scripts/reindex_experiments.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# repo_root/scripts/this_file -> repo_root
_REPO_ROOT = Path(__file__).resolve().parent.parent
_RESULTS_DIR = _REPO_ROOT / "bench" / "results"
_INDEX_PATH = _RESULTS_DIR / "index.json"

# The three canonical result-JSON names a bench experiment dir may hold. Probed in
# this order; the first present one decides the dir's ``kind``.
_RESULT_FILES: tuple[tuple[str, str], ...] = (
    ("ablation.json", "ablation"),
    ("repeats.json", "repeats"),
    ("results.json", "results"),
)

# Backfill map: experiment dir name -> FIELD-NOTES section number it backs.
# Methodology-only sections (§13/§14) and the local-k12 §22 deliberately have no
# committed run dir, so they are absent here (the parity test tolerates that).
_DIR_TO_SECTION: dict[str, int] = {
    "2026-06-11": 3,
    "2026-06-13-tool-ablation": 12,
    "2026-06-14-tier0-verification": 14,
    "2026-06-15-d2-tight": 15,
    "2026-06-15-harsh-ablation": 16,
    "2026-06-15-plus28-recheck": 17,
    "2026-06-16-doctrine-ablation": 18,
    "2026-06-16-s1-infra-fix": 19,
    "2026-06-16-s1-infra-model": 20,
    "2026-06-16-cost-contract-trim": 21,
    # Doctrine ablations link to §18 (doctrine buys conformance, not lives). Kept a
    # small explicit map — never guessed for other dirs (they stay null).
    "2026-06-22-doctrine-6seed": 18,
    # §26 whole-roster model-tier sweep (flash/plus/max): bigger model is outcome-
    # neutral; one cell per tier.
    "2026-06-30-mtier-flash": 26,
    "2026-06-30-mtier-plus": 26,
    "2026-06-30-mtier-max": 26,
    # §27 friction-necessity curve: per-arm efficiency vs pool size (abundance→extreme);
    # one cell per pool level (records lean — summaries only, like §3).
    "2026-06-30-fric-p12": 27,
    "2026-06-30-fric-p6": 27,
    "2026-06-30-fric-p4": 27,
    "2026-06-30-fric-p2": 27,
    "2026-06-30-fric-p1": 27,
    # §28 cross-family panel: one combined dir, arms keyed by MODEL id (solo arm).
    "2026-07-01-panelA-solo": 28,
}

# Dirs that predate the provenance stamp / verdict hardening — their verdict (if any)
# was not produced by the hardened CI+sign-test gate, so a missing verdict here is
# recorded as null with this note rather than coerced.
_PRE_STAMP_NOTE = "pre-2026-06-16-hardening"


def _load_json(path: Path) -> Any | None:
    """Read+parse a JSON file; return None on any read/parse error (never raise)."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _git_tracked(pattern: str) -> list[str]:
    """``git ls-files <pattern>`` from the repo root; [] on any failure."""
    try:
        out = subprocess.run(
            ["git", "ls-files", pattern],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _git_sha() -> str:
    """Current HEAD sha (write-time metadata); "unknown" outside a checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if out.returncode != 0:
        return "unknown"
    return out.stdout.strip() or "unknown"


def _records_committed(exp_dir: Path) -> bool:
    """True when this experiment has at least one git-tracked ticks.ndjson.

    Falls back to filesystem presence when git is unavailable. A dir whose run
    records are not committed (only summary JSONs, or the records live in an
    uncommitted local-k12 dir) reports False — honestly flagging that the row's
    underlying tick records cannot be replayed from the repo.
    """
    try:
        rel = exp_dir.relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        # A dir outside the repo (e.g. an uncommitted local-k12 run, or a test
        # fixture in a tmp path) can't be git-tracked under this repo — fall back
        # to a filesystem scan so the row is recorded (committed only if records
        # physically exist), never crashed/dropped.
        return any(exp_dir.rglob("ticks.ndjson"))
    tracked = _git_tracked(f"{rel}/**/ticks.ndjson")
    if tracked:
        return True
    # git fallback could be unavailable; treat any existing ticks.ndjson as present.
    return any(exp_dir.rglob("ticks.ndjson"))


def _detect_kind(exp_dir: Path) -> tuple[str | None, Path | None]:
    """Return (kind, result_json_path) for the first canonical result file present."""
    for fname, kind in _RESULT_FILES:
        p = exp_dir / fname
        if p.is_file():
            return kind, p
    return None, None


def _provenance(data: Any) -> dict[str, Any]:
    """Extract the provenance stamp from a result dict (empty dict if absent)."""
    if isinstance(data, dict):
        prov = data.get("provenance")
        if isinstance(prov, dict):
            return prov
    return {}


def _endpoint(data: Any) -> str:
    """model_endpoint for the row.

    Prefer the stamped provenance value. Pre-stamp files have none: infer "scripted"
    when the result shows no LLM cost, else default to the published cloud endpoint
    "dashscope-intl" (every committed pre-stamp experiment ran on DashScope-Intl;
    the only local-k12 runs, §22, are not committed). Never merges cloud + local.
    """
    prov = _provenance(data)
    ep = prov.get("model_endpoint")
    if isinstance(ep, str) and ep:
        return ep
    if not isinstance(data, dict):
        return "unknown"
    # results.json shape: any arm with positive cost => LLM was used.
    arms = data.get("arms")
    if isinstance(arms, dict):
        any_cost = any(
            float((s or {}).get("mean_cost_usd", 0.0) or 0.0) > 0.0
            for s in arms.values()
            if isinstance(s, dict)
        )
        return "dashscope-intl" if any_cost else "scripted"
    # ablation.json shape: a doctrine/LLM ablation always used a provider.
    if "mean_delta" in data or "ablate" in data:
        return "dashscope-intl"
    # repeats.json shape: per-arm dicts; society/swarm/solo => LLM.
    llm_arms = {"society", "swarm", "solo"}
    if any(k in llm_arms for k in data):
        return "dashscope-intl"
    return "scripted"


def _verdict(data: Any) -> tuple[str | None, str | None]:
    """Return (verdict, verdict_note).

    Only ablation results carry a verdict. The literal enum is preserved; a missing
    verdict is recorded as None with the pre-hardening note (NEVER coerced to a
    value). Non-ablation results return (None, None) — they have no verdict concept.
    """
    if not isinstance(data, dict):
        return None, None
    is_ablation = "mean_delta" in data and "per_seed" in data
    if not is_ablation:
        return None, None
    v = data.get("verdict")
    if isinstance(v, str) and v:
        return v, None
    return None, _PRE_STAMP_NOTE


def _conformance_verdict(data: Any) -> str | None:
    """The conformance-Δ verdict, READ from the doctrine ablation's conformance block.

    Pure read: returns ``data["conformance"]["verdict"]`` when the file carries it
    (a doctrine ablation written after this field was added), else None — a pre-fix
    ablation (e.g. 2026-06-16-doctrine-ablation) or a non-doctrine result simply lacks
    it. The reindex NEVER recomputes stats; an old file without the field stays null.
    The literal enum is preserved (or null); never coerced. Kept SEPARATE from the
    lives ``verdict`` field, so the two signals are never collapsed.
    """
    if not isinstance(data, dict):
        return None
    conf = data.get("conformance")
    if isinstance(conf, dict):
        v = conf.get("verdict")
        if isinstance(v, str) and v:
            return v
    return None


def _seeds(data: Any) -> list[int] | None:
    """Seed list if discoverable across the three result shapes (defensive)."""
    if not isinstance(data, dict):
        return None
    seeds = data.get("seeds")
    if isinstance(seeds, list):
        return [int(s) for s in seeds if isinstance(s, int | float)]
    # results.json: union of the paired table's seeds.
    paired = data.get("paired")
    if isinstance(paired, dict):
        found: set[int] = set()
        for arm_map in paired.values():
            if isinstance(arm_map, dict):
                for k in arm_map:
                    try:
                        found.add(int(k))
                    except (TypeError, ValueError):
                        continue
        if found:
            return sorted(found)
    return None


def _cost_usd(data: Any) -> float | None:
    """Total/representative cost in USD across the result shapes (None if absent)."""
    if not isinstance(data, dict):
        return None
    arms = data.get("arms")
    if isinstance(arms, dict):
        total = 0.0
        seen = False
        for s in arms.values():
            if isinstance(s, dict) and "mean_cost_usd" in s:
                total += float(s.get("mean_cost_usd", 0.0) or 0.0)
                seen = True
        return total if seen else None
    return None


def _conformance(data: Any) -> float | None:
    """The conformance signal (mean_team_alignment), kept SEPARATE from lives.

    results.json: mean over arms that report mean_team_alignment.
    ablation.json (doctrine): the conformance block's treatment (doctrine-on) mean.
    Never folded into the lives number.
    """
    if not isinstance(data, dict):
        return None
    arms = data.get("arms")
    if isinstance(arms, dict):
        vals = [
            float(s["mean_team_alignment"])
            for s in arms.values()
            if isinstance(s, dict) and s.get("mean_team_alignment") is not None
        ]
        if vals:
            return sum(vals) / len(vals)
    conf = data.get("conformance")
    if isinstance(conf, dict) and conf.get("mean_treatment") is not None:
        return float(conf["mean_treatment"])
    return None


def _lives_saved(data: Any) -> float | None:
    """Representative lives_saved (kept separate from conformance).

    results.json: mean_lives_saved of the society arm if present, else the max over
    arms. ablation.json: mean_treatment (the treatment side's mean lives).
    """
    if not isinstance(data, dict):
        return None
    arms = data.get("arms")
    if isinstance(arms, dict):
        soc = arms.get("society")
        if isinstance(soc, dict) and soc.get("mean_lives_saved") is not None:
            return float(soc["mean_lives_saved"])
        vals = [
            float(s["mean_lives_saved"])
            for s in arms.values()
            if isinstance(s, dict) and s.get("mean_lives_saved") is not None
        ]
        if vals:
            return max(vals)
    if data.get("mean_treatment") is not None and "per_seed" in data:
        return float(data["mean_treatment"])
    return None


def _lives_per_dollar(data: Any) -> float | None:
    """lives_per_dollar across result shapes (None when no priced arm)."""
    if not isinstance(data, dict):
        return None
    arms = data.get("arms")
    if isinstance(arms, dict):
        soc = arms.get("society")
        if isinstance(soc, dict) and soc.get("lives_per_dollar") is not None:
            return float(soc["lives_per_dollar"])
        for s in arms.values():
            if isinstance(s, dict) and s.get("lives_per_dollar") is not None:
                return float(s["lives_per_dollar"])
    return None


def _ablate(data: Any) -> str | None:
    """The ablate knob ('doctrine', ...) if this is a knob ablation, else None."""
    if isinstance(data, dict):
        a = data.get("ablate")
        if isinstance(a, str) and a:
            return a
    return None


def build_row(exp_dir: Path) -> dict[str, Any]:
    """Build one defensive index row for an experiment directory."""
    name = exp_dir.name
    kind, result_path = _detect_kind(exp_dir)
    data = _load_json(result_path) if result_path is not None else None

    verdict, verdict_note = _verdict(data)
    section = _DIR_TO_SECTION.get(name)
    prov = _provenance(data)

    return {
        "dir": name,
        "kind": kind,
        "ablate": _ablate(data),
        "verdict": verdict,
        "verdict_note": verdict_note,
        # conformance_verdict: READ from ablation.json's conformance block (null when
        # the file predates the field). Kept SEPARATE from the lives ``verdict``.
        "conformance_verdict": _conformance_verdict(data),
        "seeds": _seeds(data),
        "cost_usd": _cost_usd(data),
        # conformance kept SEPARATE from lives (never collapsed):
        "mean_team_alignment": _conformance(data),
        "lives_saved": _lives_saved(data),
        "lives_per_dollar": _lives_per_dollar(data),
        # required so cloud vs local rows are never merged:
        "model_endpoint": _endpoint(data),
        "field_notes_section": section,
        "records_committed": _records_committed(exp_dir),
        "schema_version": prov.get("schema_version"),
        "git_sha": prov.get("git_sha"),
    }


def build_index() -> dict[str, Any]:
    """Walk bench/results/* and assemble the full index document."""
    rows: list[dict[str, Any]] = []
    if _RESULTS_DIR.is_dir():
        for exp_dir in sorted(_RESULTS_DIR.iterdir()):
            if not exp_dir.is_dir():
                continue
            kind, _ = _detect_kind(exp_dir)
            if kind is None:
                # No canonical result JSON (e.g. a nested sub-batch handled by its
                # parent) — skip silently rather than emit a contentless row.
                continue
            rows.append(build_row(exp_dir))
    return {
        "schema_version": 1,
        "generated_by_git_sha": _git_sha(),
        "n_experiments": len(rows),
        "experiments": rows,
    }


def main() -> int:
    index = build_index()
    _INDEX_PATH.write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"wrote {_INDEX_PATH.relative_to(_REPO_ROOT)} "
        f"({index['n_experiments']} experiments)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
