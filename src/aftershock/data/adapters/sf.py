"""SF adapter — DataSF Fire/EMS Dispatched Calls (nuek-vuh3).

Source: https://data.sfgov.org/Public-Safety/...-Di/nuek-vuh3 (SODA, keyless,
PDDL public domain, 7,340,535 rows verified 2026-06-11). One row per dispatched
unit; group by ``call_number``.

Gotchas (research shortlist #1 + section 3), all unit-tested against a small
committed fixture slice (no network):
  * ~22% of unit rows lack ``on_scene_dttm`` (cancelled units) — drop nulls when
    taking MIN per incident; an incident with *all* on-scene null has
    ``first_on_scene = None`` (no unit arrived).
  * junk battalion codes (B99, AMB, XXX, 3E, B100) are dropped.
  * use ``original_priority`` (values {1,2,3,A,B,C,E,I,T}), NOT ``final_priority``
    (collapses to {2,3}).
  * ``call_type_group`` is null on a few rows — severity falls back to base_low.

The engine vocabulary is FROZEN: real ``call_type`` values are mapped onto the
four MissionKinds via the config table HERE.
"""

from __future__ import annotations

import json
import random
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

from aftershock.data.adapters.base import (
    Adapter,
    AggregateResult,
    DiscretizeResult,
    Incident,
)

# DataSF datetimes look like "2018-07-04T06:02:32.000" (no tz). They are local
# San Francisco wall-clock; the routine window is in July (PDT = UTC-07:00). We
# attach that fixed offset so the datetimes are tz-aware (deltas are
# offset-invariant — every operand shares the same zone).
_DT_FMT = "%Y-%m-%dT%H:%M:%S.%f"
_DT_FMT_NOFRAC = "%Y-%m-%dT%H:%M:%S"
_LOCAL_TZ = timezone(timedelta(hours=-7))  # PDT for the July SF window


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in (_DT_FMT, _DT_FMT_NOFRAC):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=_LOCAL_TZ)
        except ValueError:
            continue
    return None


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class SFAdapter(Adapter):
    name = "sf"

    # ------------------------------------------------------------------ Extract
    def extract(self, config: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
        ex = config["extract"]
        where = (
            f"received_dttm between '{ex['window_start']}' "
            f"and '{ex['window_end']}'"
        )
        params = {
            "$where": where,
            "$order": "received_dttm,call_number,unit_id",
            "$limit": str(ex.get("limit", 50000)),
        }
        query_url = ex["base_url"] + "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(  # noqa: S310 — fixed https DataSF endpoint
            query_url, headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            body = resp.read()
        rows = json.loads(body)

        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "rows.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8"
        )

        manifest = {
            "fetched_at": datetime.now(UTC).date().isoformat(),
            "rows_fetched": len(rows),
            "query_url": query_url,
            "resource": ex["resource"],
            "window_start": ex["window_start"],
            "window_end": ex["window_end"],
        }
        (raw_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return manifest

    # ---------------------------------------------------------------- Aggregate
    def aggregate(
        self, rows: list[dict[str, Any]], config: dict[str, Any]
    ) -> AggregateResult:
        junk = set(config.get("junk_battalions", []))
        bat_district: dict[str, str] = config["battalion_district"]

        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        dropped_junk = 0
        for row in rows:
            battalion = (row.get("battalion") or "").strip()
            if battalion in junk or battalion not in bat_district:
                dropped_junk += 1
                continue
            call_number = row.get("call_number")
            if not call_number:
                continue
            groups[call_number].append(row)

        incidents: list[Incident] = []
        for call_number, unit_rows in groups.items():
            # received = MIN(received_dttm) across units.
            received_dts = [
                _parse_dt(r.get("received_dttm")) for r in unit_rows
            ]
            received_dts = [d for d in received_dts if d is not None]
            if not received_dts:
                continue
            received = min(received_dts)

            # first_on_scene = MIN(on_scene_dttm) over units, NULLS DROPPED.
            on_scene_dts = [
                _parse_dt(r.get("on_scene_dttm")) for r in unit_rows
            ]
            on_scene_dts = [d for d in on_scene_dts if d is not None]
            first_on_scene = min(on_scene_dts) if on_scene_dts else None

            # unit roster (sorted set of unit_type), battalion -> district.
            unit_types = tuple(
                sorted({(r.get("unit_type") or "").strip() for r in unit_rows})
            )
            # battalion is consistent within a call; take the first unit's.
            battalion = (unit_rows[0].get("battalion") or "").strip()
            district_id = bat_district[battalion]

            # call_type/group/priority/alarms from the first unit row (shared).
            call_type = (unit_rows[0].get("call_type") or "").strip()
            call_type_group = (unit_rows[0].get("call_type_group") or "").strip()
            original_priority = (
                unit_rows[0].get("original_priority") or ""
            ).strip()
            alarms = max(
                (_to_int(r.get("number_of_alarms"), 1) for r in unit_rows),
                default=1,
            )

            incidents.append(
                Incident(
                    call_number=str(call_number),
                    received=received.strftime(_DT_FMT),
                    first_on_scene=(
                        first_on_scene.strftime(_DT_FMT)
                        if first_on_scene
                        else None
                    ),
                    units=unit_types,
                    district_id=district_id,
                    call_type=call_type,
                    call_type_group=call_type_group,
                    original_priority=original_priority,
                    number_of_alarms=alarms,
                )
            )

        # Deterministic order: by received, then call_number.
        incidents.sort(key=lambda i: (i.received, i.call_number))
        return AggregateResult(
            incidents=tuple(incidents),
            dropped_junk_battalion=dropped_junk,
            raw_unit_rows=len(rows),
        )

    # --------------------------------------------------------------- Discretize
    def _severity(self, inc: Incident, config: dict[str, Any]) -> int:
        sev = config["severity"]
        base = (
            sev["base_high"]
            if inc.call_type_group in set(sev["high_groups"])
            else sev["base_low"]
        )
        if inc.original_priority in set(sev["priority_bump"]):
            base += 1
        if sev.get("alarm_bump") and inc.number_of_alarms > 1:
            base += inc.number_of_alarms - 1
        return max(sev["min"], min(sev["max"], base))

    def _mission_kind(self, inc: Incident, config: dict[str, Any]) -> str | None:
        if inc.call_type in set(config.get("drop_call_types", [])):
            return None
        table: dict[str, str] = config["mission_kind"]
        return table.get(inc.call_type, config.get("default_mission_kind", "fire"))

    def _lives(self, kind: str, severity: int, config: dict[str, Any]) -> int:
        table = config["lives"][kind]
        # severity 1..5 -> index 0..4
        lives = table[severity - 1]
        return max(1, min(64, int(lives)))

    def discretize(
        self,
        agg: AggregateResult,
        config: dict[str, Any],
        fetch_manifest: dict[str, Any],
    ) -> DiscretizeResult:
        tick_minutes: int = config["tick_minutes"]
        window_start = _parse_dt(config["extract"]["window_start"])
        if window_start is None:
            raise ValueError(
                f"unparseable window_start: {config['extract']['window_start']!r}"
            )

        def tick_of(received_iso: str) -> int:
            dt = _parse_dt(received_iso)
            assert dt is not None
            delta = (dt - window_start).total_seconds() / 60.0
            return int(delta // tick_minutes)

        # Build candidate missions (post-filter): drop unmapped/dropped call_types.
        candidates: list[dict[str, Any]] = []
        for inc in agg.incidents:
            kind = self._mission_kind(inc, config)
            if kind is None:
                continue
            severity = self._severity(inc, config)
            tick = tick_of(inc.received)
            if tick < 0:
                continue
            latency_s: int | None = None
            if inc.first_on_scene is not None:
                fos = _parse_dt(inc.first_on_scene)
                rec = _parse_dt(inc.received)
                if fos is not None and rec is not None:
                    latency_s = int((fos - rec).total_seconds())
                    if latency_s < 0:
                        latency_s = None
            candidates.append(
                {
                    "incident": inc,
                    "tick": tick,
                    "kind": kind,
                    "severity": severity,
                    "received": inc.received,
                    "first_on_scene": inc.first_on_scene,
                    "latency_s": latency_s,
                }
            )

        total = len(candidates)

        # ---- Deterministic stratified sampling to target_missions ----
        samp = config["sampling"]
        target = int(samp["target_missions"])
        sample_seed = int(samp["sample_seed"])
        stratum_ticks = int(samp.get("stratum_ticks", tick_minutes))
        kept = self._stratified_sample(
            candidates, target, sample_seed, stratum_ticks
        )

        # Sort kept by (tick, received, call_number) for a stable timeline.
        kept.sort(
            key=lambda c: (c["tick"], c["received"], c["incident"].call_number)
        )

        # ---- Timeline + per-mission reference ----
        timeline: list[dict[str, Any]] = []
        reference_missions: dict[str, dict[str, Any]] = {}
        for idx, c in enumerate(kept):
            kind = c["kind"]
            severity = c["severity"]
            lives = self._lives(kind, severity, config)
            timeline.append(
                {
                    "tick": c["tick"],
                    "kind": "mission",
                    "mission_kind": kind,
                    "district_id": c["incident"].district_id,
                    "severity": severity,
                    "lives_at_risk": lives,
                }
            )
            reference_missions[str(idx)] = {
                "received": _iso_offset(c["received"]),
                "first_on_scene": _iso_offset(c["first_on_scene"]),
                "latency_s": c["latency_s"],
            }

        # ---- Reference aggregates over the FULL filtered window (not sample) ----
        # held_rate is NULL for SF: nuek-vuh3 has NO held/saturation field. The
        # no-arrival fraction is NOT a held/saturation measurement, and reusing the
        # "held_rate" name (which means a REAL held_indicator rate in the NYC pack)
        # would be a from-absence metric masquerading as a real one. We expose
        # n_incidents / n_arrived (honest counts) but emit held_rate: null.
        full_latencies = [
            c["latency_s"] for c in candidates if c["latency_s"] is not None
        ]
        arrived = len(full_latencies)
        aggregates: dict[str, Any] = {
            "n_incidents": total,
            "n_arrived": arrived,
            "mean_latency_s": int(round(mean(full_latencies))) if full_latencies else None,
            "median_latency_s": int(round(median(full_latencies))) if full_latencies else None,
            "held_rate": None,
        }
        aggregates.update(
            self._baseline_aggregates(config)
        )

        # ---- Pools from observed unit roster, scaled + clamped ----
        pools = self._pools(agg, total, len(kept), config)

        # ---- Districts (display names + members from config) ----
        districts = self._districts(config)

        # ---- Mapping (published verbatim) ----
        mapping = {
            "version": config["mapping_version"],
            "mission_kind": dict(config["mission_kind"]),
            "severity_rule": (
                "base 3 if call_type_group in {Potentially Life-Threatening, Fire} "
                "else 2; +1 if original_priority in {E,3}; +1 per alarm above 1; "
                "clamp [1,5]"
            ),
            "lives_rule": (
                "LIVES[mission_kind][severity] lookup table sf-v1 (inferred field); "
                "clamp [1,64]"
            ),
        }

        field_provenance = {
            "tick": "real",
            "district_id": "real",
            "mission_kind": "mapped",
            "severity": "mapped",
            "lives_at_risk": "inferred",
            "blockage": "synthetic",
        }

        sampling = {
            "method": "stratified by (tick-bucket, mission_kind)",
            "sample_seed": sample_seed,
            "kept": len(kept),
            "total": total,
            "filter": (
                "battalion in B01-B10 (junk B99/AMB/XXX dropped); call_type mapped "
                "to a MissionKind (Alarms/Citizen Assist/Other dropped)"
            ),
        }

        return DiscretizeResult(
            timeline=timeline,
            pools=pools,
            reference={"missions": reference_missions, "aggregates": aggregates},
            sampling=sampling,
            mapping=mapping,
            field_provenance=field_provenance,
            districts=districts,
        )

    # ------------------------------------------------------------ helpers
    def _stratified_sample(
        self,
        candidates: list[dict[str, Any]],
        target: int,
        sample_seed: int,
        stratum_ticks: int,
    ) -> list[dict[str, Any]]:
        """Deterministic stratified downsample to ``target`` missions.

        Strata = (tick // stratum_ticks, mission_kind). Within each stratum the
        candidates are shuffled with ``random.Random(sample_seed)``; we then draw
        round-robin across strata (in sorted stratum order) so the arrival-time
        distribution and kind mix are preserved. Same seed -> same kept set.
        """
        if len(candidates) <= target:
            return list(candidates)

        strata: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for c in candidates:
            key = (c["tick"] // stratum_ticks, c["kind"])
            strata[key].append(c)

        rng = random.Random(sample_seed)
        # Deterministic stratum order; deterministic in-stratum shuffle.
        ordered_keys = sorted(strata.keys())
        for key in ordered_keys:
            bucket = strata[key]
            # stable pre-sort so the shuffle input order is config-independent
            bucket.sort(
                key=lambda c: (c["tick"], c["received"], c["incident"].call_number)
            )
            rng.shuffle(bucket)

        kept: list[dict[str, Any]] = []
        cursors = {key: 0 for key in ordered_keys}
        while len(kept) < target:
            progressed = False
            for key in ordered_keys:
                if len(kept) >= target:
                    break
                bucket = strata[key]
                cur = cursors[key]
                if cur < len(bucket):
                    kept.append(bucket[cur])
                    cursors[key] = cur + 1
                    progressed = True
            if not progressed:
                break
        return kept

    def _pools(
        self,
        agg: AggregateResult,
        total: int,
        kept: int,
        config: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        pcfg = config["pools"]
        unit_kind: dict[str, str] = pcfg["unit_kind"]
        observed_kinds: list[str] = pcfg["observed_kinds"]
        clamp_min = int(pcfg["clamp_min"])
        clamp_max = int(pcfg["clamp_max"])

        # Distinct unit-types observed per ResourceKind across all incidents.
        kind_units: dict[str, set[str]] = defaultdict(set)
        for inc in agg.incidents:
            for ut in inc.units:
                rk = unit_kind.get(ut)
                if rk:
                    kind_units[rk].add(ut)

        # The advertised sampling ratio (kept/total ~= 0.08) is NEVER actually
        # applied: the scale factor is floored at max(ratio, 0.5), and with the
        # small observed unit-type diversity every "observed" pool collapses to a
        # single clamped constant (size 3) that does NOT vary with the real data.
        # That is a calibrated default dressed up as an observation, so we mark
        # these pools `calibrated` and state the truth (no misleading 0.08 figure).
        # An `observed` basis is reserved for a size genuinely derived from a real
        # observed unit count (none qualify for SF -> all SF pools are calibrated).
        ratio = (kept / total) if total else 1.0
        scale = max(ratio, 0.5)

        pools: dict[str, dict[str, Any]] = {}
        for rk in observed_kinds:
            observed = len(kind_units.get(rk, set()))
            scaled = max(observed, 1) * scale
            size = max(clamp_min, min(clamp_max, round(scaled) + clamp_min))
            pools[rk] = {
                "size": int(size),
                "basis": "calibrated",
                "note": (
                    f"{observed} distinct unit_type(s) mapped to {rk} in the "
                    f"window, but the size collapses to a clamped default "
                    f"({size}) within [{clamp_min},{clamp_max}] — not a real "
                    f"observed unit count, so calibrated"
                ),
            }

        for rk, default in pcfg["calibrated_defaults"].items():
            size = max(clamp_min, min(clamp_max, int(default)))
            pools[rk] = {
                "size": size,
                "basis": "calibrated",
                "note": f"no SF analog for {rk}; calibrated default {size}",
            }
        return pools

    def _districts(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        dcfg = config["districts"]
        out: list[dict[str, Any]] = []
        for did, info in dcfg.items():
            out.append(
                {
                    "id": did,
                    "name": info["name"],
                    "members": list(info.get("members", [])),
                }
            )
        # Stable order by canonical id for byte-identity.
        out.sort(key=lambda d: d["id"])
        return out

    def _baseline_aggregates(self, config: dict[str, Any]) -> dict[str, Any]:
        """SF is the ROUTINE (non-disaster) pack and ships no computed baseline.

        We deliberately do NOT declare a baseline window/note: advertising a
        named comparison while every numeric baseline figure is null would imply a
        comparison the pack does not actually provide. The baseline_* figures stay
        null and unadvertised (no baseline_window / baseline_note keys)."""
        return {
            "baseline_mean_latency_s": None,
            "baseline_median_latency_s": None,
            "baseline_held_rate": None,
        }


def _iso_offset(naive_iso: str | None) -> str | None:
    """Render a naive DataSF timestamp as a local-PDT ISO string for reference.

    DataSF stamps are local San Francisco wall-clock; the routine window is in
    July (PDT = -07:00). We attach that fixed offset for display only — math uses
    the naive form so it stays self-consistent."""
    if naive_iso is None:
        return None
    dt = _parse_dt(naive_iso)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "-07:00"
