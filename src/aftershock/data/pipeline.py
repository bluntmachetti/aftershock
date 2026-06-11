"""Offline compiler pipeline: orchestrate Extract -> Aggregate -> Discretize ->
Emit, and write the committed ``scenario.json`` + per-pack ``README.md``.

This module is OFFLINE and is never imported by the engine. The only network
access is inside an adapter's ``extract`` (skippable via the cached ``raw/``).

Byte-identity: ``Emit`` serializes with ``sort_keys=True`` and a trailing
newline, so recompiling from an identical ``raw/`` cache + identical config hash
is byte-stable (golden test).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from aftershock.data.adapters.base import Adapter
from aftershock.data.adapters.nyc import NYCAdapter
from aftershock.data.adapters.sf import SFAdapter

# Registry of available adapters by name.
_ADAPTERS: dict[str, type[Adapter]] = {
    "sf": SFAdapter,
    "nyc": NYCAdapter,
}


def get_adapter(name: str) -> Adapter:
    try:
        return _ADAPTERS[name]()
    except KeyError as exc:
        raise ValueError(
            f"unknown adapter {name!r}; available: {sorted(_ADAPTERS)}"
        ) from exc


def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load an adapter config YAML into a plain dict."""
    text = Path(config_path).read_text(encoding="utf-8")
    return yaml.safe_load(text)


def config_sha256(config_path: str | Path) -> str:
    """SHA-256 of the adapter config YAML's raw bytes (stamped into the pack)."""
    return hashlib.sha256(Path(config_path).read_bytes()).hexdigest()


def _compiler_version() -> str:
    """The git rev of the compiler at emit time, or 'unknown' offline.

    Recorded into ``scenario.json`` (``compiler_version``). Note: a changing git
    rev does NOT break the golden byte-identity test, which pins this field to a
    fixed value via ``compiler_version_override``.
    """
    try:
        out = subprocess.run(  # noqa: S603,S607 — fixed argv, read-only
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).resolve().parent,
        )
        rev = out.stdout.strip()
        return rev or "unknown"
    except Exception:  # noqa: BLE001 — offline / no git is fine
        return "unknown"


@dataclass
class CompileResult:
    pack: dict[str, Any]
    scenario_json_bytes: bytes
    readme: str
    fetch_manifest: dict[str, Any]


def compile_scenario(
    *,
    adapter_name: str,
    config_path: str | Path,
    out_dir: str | Path,
    fetch: bool = True,
    compiler_version_override: str | None = None,
) -> CompileResult:
    """Run the full pipeline and write ``scenario.json`` + ``README.md``.

    When ``fetch`` is False, the existing ``raw/`` cache is used (offline,
    deterministic, golden-test path). When True, the adapter fetches live and
    refreshes ``raw/`` + ``raw/manifest.json``.

    ``compiler_version_override`` pins the ``compiler_version`` field (used by the
    golden test so a moving git rev does not break byte-identity).
    """
    adapter = get_adapter(adapter_name)
    config = load_config(config_path)
    out = Path(out_dir)
    raw_dir = out / "raw"

    # ---- Extract (network, unless using the cache) ----
    if fetch:
        fetch_manifest = adapter.extract(config, raw_dir)
    else:
        manifest_path = raw_dir / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"no cached raw manifest at {manifest_path}; run with fetch=True "
                "first (Extract caches raw/ + raw/manifest.json)"
            )
        fetch_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    rows = adapter.load_rows(raw_dir)

    # ---- Aggregate ----
    agg = adapter.aggregate(rows, config)

    # ---- Discretize ----
    disc = adapter.discretize(agg, config, fetch_manifest)

    # ---- Emit ----
    cfg_sha = config_sha256(config_path)
    compiler_version = compiler_version_override or _compiler_version()
    pack = _build_pack(config, disc, fetch_manifest, cfg_sha, compiler_version)

    scenario_bytes = (
        json.dumps(pack, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")

    # Adapters may supply their own README (multi-source packs like NYC); the
    # SF-default builder is the fallback for single-source packs.
    adapter_readme = getattr(disc, "extra", {}).get("readme")
    readme = adapter_readme if adapter_readme else _build_readme(pack, fetch_manifest)

    out.mkdir(parents=True, exist_ok=True)
    (out / "scenario.json").write_bytes(scenario_bytes)
    (out / "README.md").write_text(readme, encoding="utf-8")

    return CompileResult(
        pack=pack,
        scenario_json_bytes=scenario_bytes,
        readme=readme,
        fetch_manifest=fetch_manifest,
    )


def _build_pack(
    config: dict[str, Any],
    disc: Any,
    fetch_manifest: dict[str, Any],
    config_sha: str,
    compiler_version: str,
) -> dict[str, Any]:
    """Assemble the scenario.json dict (TOP-LEVEL keys EXACTLY the contract)."""
    # Adapters may supply their own ``source`` list (multi-source packs like NYC
    # join two upstream datasets); the SF-default single-source builder is the
    # fallback so SF output stays byte-identical.
    adapter_source = getattr(disc, "extra", {}).get("source")
    source = adapter_source if adapter_source else [_source_entry(config, fetch_manifest)]

    # Window bounds: a per-adapter offset may be supplied (NYC = EDT -04:00);
    # the SF-default July PDT offset (-07:00) is the fallback.
    win_offset = getattr(disc, "extra", {}).get("window_offset")
    if win_offset:
        start = config["extract"]["window_start"] + win_offset
        end = config["extract"]["window_end"] + win_offset
    else:
        start = _iso_offset(config["extract"]["window_start"])
        end = _iso_offset(config["extract"]["window_end"])

    pack = {
        "format_version": 1,
        "id": config["id"],
        "name": config["name"],
        "hazard": config["hazard"],
        "adapter": config["adapter"],
        "compiler_version": compiler_version,
        "config_sha256": config_sha,
        "tick_minutes": int(config["tick_minutes"]),
        "window": {"start": start, "end": end},
        "districts": disc.districts,
        "pools": disc.pools,
        "timeline": disc.timeline,
        "field_provenance": disc.field_provenance,
        "mapping": disc.mapping,
        "sampling": disc.sampling,
        "source": source,
        "reference": disc.reference,
    }
    return pack


def _source_entry(
    config: dict[str, Any], fetch_manifest: dict[str, Any]
) -> dict[str, Any]:
    return {
        "dataset": (
            "Fire Department and Emergency Medical Services Dispatched Calls "
            "for Service"
        ),
        "provider": "DataSF (San Francisco Open Data)",
        "dataset_id": fetch_manifest.get("resource", "nuek-vuh3"),
        "query_url": fetch_manifest.get("query_url", ""),
        "fetched_at": fetch_manifest.get("fetched_at", ""),
        "rows_fetched": int(fetch_manifest.get("rows_fetched", 0)),
        "license": "PDDL 1.0 (Public Domain Dedication and License)",
        "license_url": "http://opendatacommons.org/licenses/pddl/1.0/",
        "attribution": "DataSF",
    }


_WINDOW_BOUND_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _iso_offset(naive: str) -> str:
    """Attach the fixed July PDT offset (-07:00) to a naive window bound.

    Pure string formatting (no datetime arithmetic): the DataSF window bounds are
    local San Francisco wall-clock; the July routine window is PDT (UTC-07:00).
    """
    if _WINDOW_BOUND_RE.match(naive):
        return naive + "-07:00"
    return naive


def _build_readme(pack: dict[str, Any], fetch_manifest: dict[str, Any]) -> str:
    src = pack["source"][0]
    samp = pack["sampling"]
    caveat = (
        "Demand: real · Latency baseline: real · Lives & outcomes: simulated "
        "model."
    )
    lines = [
        f"# {pack['name']}",
        "",
        f"**Scenario id:** `{pack['id']}`  ·  **Hazard:** `{pack['hazard']}`  ·  "
        f"**Adapter:** `{pack['adapter']}`",
        "",
        "> " + caveat,
        "",
        "## Source",
        "",
        f"- **Dataset:** {src['dataset']} (`{src['dataset_id']}`)",
        f"- **Provider:** {src['provider']}",
        f"- **License:** {src['license']} — {src['license_url']}",
        f"- **Attribution:** {src['attribution']}",
        f"- **Fetched:** {src['fetched_at']}  ·  **Rows fetched:** "
        f"{src['rows_fetched']}",
        "- **Query:**",
        "",
        "  ```",
        f"  {src['query_url']}",
        "  ```",
        "",
        "## Window & sampling",
        "",
        f"- **Window:** {pack['window']['start']} → {pack['window']['end']} "
        f"({pack['tick_minutes']} min/tick)",
        f"- **Sampling:** {samp['kept']} of {samp['total']} incidents — "
        f"{samp['method']}, seed {samp['sample_seed']}.",
        f"- **Filter:** {samp['filter']}",
        "",
        "## Reality baseline",
        "",
        "- **No held/saturation ground truth.** DataSF `nuek-vuh3` has no "
        "held/saturation field, so `held_rate` is emitted as **null** — it is "
        "*not* the same measurement as the NYC pack's real `held_indicator` rate, "
        "and the no-arrival fraction is deliberately not reused under that name.",
        "- **No baseline comparison.** This is the routine (non-disaster) pack; it "
        "ships no computed baseline window, so the `baseline_*` figures stay null "
        "and no comparison is advertised.",
        "",
        "## Provenance (REAL / MAPPED / INFERRED / SYNTHETIC)",
        "",
        "| Field | Marker |",
        "|---|---|",
    ]
    for field_name, marker in pack["field_provenance"].items():
        lines.append(f"| `{field_name}` | {marker.upper()} |")
    lines += [
        "",
        "Real incident *types* are mapped onto the four engine MissionKinds in "
        "the offline compiler (mapping `"
        + pack["mapping"]["version"]
        + "`); the mapping is published above as provenance. Severity is a rule "
        "over `original_priority`/`call_type_group`/alarms; `lives_at_risk` is an "
        "**inferred** lookup, not a real casualty count. Blockages are not "
        "present in this dataset (synthetic field, none emitted for the routine "
        "pack).",
        "",
        "## Caveat",
        "",
        "> " + caveat,
        "",
        "Real arrival process and real first-on-scene latency; lives saved is a "
        "simulated model, **not** a claim about real outcomes.",
        "",
    ]
    return "\n".join(lines)
