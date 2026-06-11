"""NYC adapter — FDNY EMS + Fire Incident Dispatch, Hurricane Ida window.

The headline "real disaster" pack. Two upstream datasets, joined on the same
12-hour window (no shared incident key — time/borough alignment only):

  * EMS Incident Dispatch Data (``76xm-jjuj``) — one row PER INCIDENT already
    (``incident_id``), ordinal ``initial_severity_level_code`` 1-8, precomputed
    ``incident_response_seconds_qy`` with a ``valid_incident_rspns_time_indc``
    validity flag, a ``held_indicator`` saturation flag, and a ``borough``.
    NO unit counts — the ambulance pool is calibrated against held saturation.
  * Fire Incident Dispatch Data (``8m42-w767``) — one row PER INCIDENT
    (``starfire_incident_id``), ``incident_classification_group`` /
    ``incident_classification``, per-incident apparatus counts
    (``engines_assigned_quantity`` / ladders / other), the same response-seconds +
    validity flag, and ``incident_borough``. Fire apparatus counts ARE observed,
    so the fire_engine pool is sized from the engines-assigned p75.

Gotchas (research #2, adversarially verified 2026-06-11), all unit-tested against
committed fixture slices (no network):
  * Filter response-time rows by ``valid_*_indc`` — ~21% of Fire rows are invalid.
  * NEVER use Fire ``highest_alarm_level`` (99.4% "First Alarm" plus non-ordinal
    signal-code artifacts). Fire severity is derived from units-assigned quantiles.
  * EMS severity is a caller-information dispatch priority, rebinned 1-8 -> 1-5:
    codes 1-2 -> 5, code 3 -> 4; codes 4-8 are EXCLUDED by the filter (low-acuity
    noise). Only the high-acuity tail becomes medical_surge missions.
  * Both datasets are already per-incident (the EMS/Fire "dispatch" tables, not the
    SF per-unit "dispatched calls" table), so Aggregate is a per-row pass, not a
    group-by-call.

Boroughs map onto the six canonical POSITIONAL SLOTS with display names. Brooklyn
is the only borough split across two slots (Brooklyn West / Brooklyn East) by a
documented sub-area rule (EMS ``incident_dispatch_area``, Fire ``communitydistrict``).

The engine vocabulary is FROZEN: real EMS/Fire incident types are mapped onto the
four MissionKinds via the config tables HERE, in the offline compiler.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
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

# NYC Open Data datetimes look like "2021-09-01T18:00:06.000" (no tz). They are
# local New York wall-clock; the Ida window is in early September (EDT = UTC-04:00).
# We attach that fixed offset so the datetimes are tz-aware (deltas are
# offset-invariant — every operand shares the same zone).
_DT_FMT = "%Y-%m-%dT%H:%M:%S.%f"
_DT_FMT_NOFRAC = "%Y-%m-%dT%H:%M:%S"
_LOCAL_TZ = timezone(timedelta(hours=-4))  # EDT for the September NYC window
_TZ_SUFFIX = "-04:00"


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


def _iso_offset(naive_iso: str | None) -> str | None:
    """Render a naive NYC timestamp as a local-EDT ISO string for reference.

    NYC Open Data stamps are local wall-clock; the Ida window is EDT (-04:00). We
    attach that fixed offset for display only — math uses the naive form so it
    stays self-consistent (offset-invariant deltas)."""
    if naive_iso is None:
        return None
    dt = _parse_dt(naive_iso)
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + _TZ_SUFFIX


def _window_iso_offset(naive: str) -> str:
    """Attach the fixed EDT offset to a naive window bound (string-only)."""
    dt = _parse_dt(naive)
    if dt is None:
        return naive
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + _TZ_SUFFIX


class NYCAdapter(Adapter):
    name = "nyc"

    # ------------------------------------------------------------------ Extract
    def _ems_query_url(self, config: dict[str, Any]) -> str:
        ex = config["extract"]
        where = (
            f"incident_datetime between '{ex['window_start']}' "
            f"and '{ex['window_end']}'"
        )
        params = {
            "$where": where,
            "$order": "incident_datetime,incident_id",
            "$limit": str(ex.get("limit", 50000)),
        }
        return ex["ems_base_url"] + "?" + urllib.parse.urlencode(params)

    def _fire_query_url(self, config: dict[str, Any]) -> str:
        ex = config["extract"]
        where = (
            f"incident_datetime between '{ex['window_start']}' "
            f"and '{ex['window_end']}'"
        )
        params = {
            "$where": where,
            "$order": "incident_datetime,starfire_incident_id",
            "$limit": str(ex.get("limit", 50000)),
        }
        return ex["fire_base_url"] + "?" + urllib.parse.urlencode(params)

    def _fetch(self, url: str) -> list[dict[str, Any]]:
        req = urllib.request.Request(  # noqa: S310 — fixed https NYC SODA endpoint
            url, headers={"Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310
            body = resp.read()
        return json.loads(body)

    def extract(self, config: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
        ex = config["extract"]
        ems_url = self._ems_query_url(config)
        fire_url = self._fire_query_url(config)

        ems_rows = self._fetch(ems_url)
        fire_rows = self._fetch(fire_url)

        raw_dir.mkdir(parents=True, exist_ok=True)
        # The two datasets are stored side by side; ``rows.json`` is the JOINED
        # structure {ems, fire} (no shared incident key — time-window join).
        (raw_dir / "rows.json").write_text(
            json.dumps({"ems": ems_rows, "fire": fire_rows}, ensure_ascii=False),
            encoding="utf-8",
        )

        manifest = {
            "fetched_at": datetime.now(UTC).date().isoformat(),
            "rows_fetched": len(ems_rows) + len(fire_rows),
            "ems_rows_fetched": len(ems_rows),
            "fire_rows_fetched": len(fire_rows),
            "ems_query_url": ems_url,
            "fire_query_url": fire_url,
            "ems_resource": ex["ems_resource"],
            "fire_resource": ex["fire_resource"],
            "window_start": ex["window_start"],
            "window_end": ex["window_end"],
        }
        (raw_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        return manifest

    def load_rows(self, raw_dir: Path) -> dict[str, Any]:  # type: ignore[override]
        """Read the cached {ems, fire} join (no network)."""
        rows_path = raw_dir / "rows.json"
        return json.loads(rows_path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------- borough slots
    def _slot_for_ems(self, row: dict[str, Any], config: dict[str, Any]) -> str | None:
        borough = (row.get("borough") or "").strip().upper()
        bslot: dict[str, str] = config["borough_slot"]
        if borough == "BROOKLYN":
            return self._brooklyn_slot_ems(row, config)
        return bslot.get(borough)

    def _slot_for_fire(
        self, row: dict[str, Any], config: dict[str, Any]
    ) -> str | None:
        borough = (row.get("incident_borough") or "").strip().upper()
        bslot: dict[str, str] = config["borough_slot"]
        if borough == "BROOKLYN":
            return self._brooklyn_slot_fire(row, config)
        return bslot.get(borough)

    def _brooklyn_slot_ems(
        self, row: dict[str, Any], config: dict[str, Any]
    ) -> str:
        """EMS Brooklyn split by ``incident_dispatch_area`` (K1-K7).

        West areas -> ``market`` (Brooklyn West), East areas -> ``industrial``
        (Brooklyn East). Documented in config (``brooklyn_split``)."""
        split = config["brooklyn_split"]
        area = (row.get("incident_dispatch_area") or "").strip().upper()
        west_areas = set(split["ems_west_areas"])
        if area in west_areas:
            return split["west_slot"]
        return split["east_slot"]

    def _brooklyn_slot_fire(
        self, row: dict[str, Any], config: dict[str, Any]
    ) -> str:
        """Fire Brooklyn split by ``communitydistrict`` (3xx).

        West CDs -> ``market`` (Brooklyn West), else -> ``industrial`` (Brooklyn
        East). Documented in config (``brooklyn_split``)."""
        split = config["brooklyn_split"]
        cd = (row.get("communitydistrict") or "").strip()
        west_cds = {str(c) for c in split["fire_west_community_districts"]}
        if cd in west_cds:
            return split["west_slot"]
        return split["east_slot"]

    # ---------------------------------------------------------------- Aggregate
    def aggregate(
        self, rows: dict[str, Any], config: dict[str, Any]
    ) -> AggregateResult:
        """Pass over per-incident EMS + Fire rows -> unified Incident records.

        Both NYC dispatch tables are already one row per incident, so there is no
        group-by-call (unlike SF). We synthesize an ``Incident`` per usable row,
        carrying enough fields for Discretize: the canonical district slot, the
        source-specific type, the response latency (filtered by validity flag),
        and (Fire only) the engines-assigned count for severity/pools.
        """
        ems_rows: list[dict[str, Any]] = rows.get("ems", [])
        fire_rows: list[dict[str, Any]] = rows.get("fire", [])

        incidents: list[Incident] = []
        dropped_no_slot = 0

        # ---- EMS ----
        # Keep ALL EMS rows in the window (every severity code). The HEADLINE
        # reality baseline (held-rate + response latency) is computed over the
        # FULL EMS demand window in Discretize; the high-acuity tail (severity
        # codes in keep_severity_codes) becomes medical_surge MISSIONS. Both come
        # from this single per-incident pass.
        for r in ems_rows:
            slot = self._slot_for_ems(r, config)
            if slot is None:
                dropped_no_slot += 1
                continue
            received = _parse_dt(r.get("incident_datetime"))
            if received is None:
                continue
            sev_code = (r.get("initial_severity_level_code") or "").strip()
            held = (r.get("held_indicator") or "").strip().upper() == "Y"
            first_on_scene = _parse_dt(r.get("first_on_scene_datetime"))
            valid = (
                r.get("valid_incident_rspns_time_indc") or ""
            ).strip().upper() == "Y"
            # latency: precomputed seconds, only when the validity flag says Y.
            latency_s = (
                _to_int(r.get("incident_response_seconds_qy"), -1) if valid else -1
            )
            incidents.append(
                Incident(
                    call_number=str(r.get("incident_id") or ""),
                    received=received.strftime(_DT_FMT),
                    first_on_scene=(
                        first_on_scene.strftime(_DT_FMT)
                        if first_on_scene
                        else None
                    ),
                    units=("EMS",),
                    district_id=slot,
                    call_type="ems:" + sev_code,
                    call_type_group="EMS",
                    original_priority=("held" if held else ""),
                    number_of_alarms=(latency_s if latency_s >= 0 else -1),
                )
            )

        # ---- Fire ----
        fire_keep_groups = set(config["fire"]["keep_classification_groups"])
        for r in fire_rows:
            slot = self._slot_for_fire(r, config)
            if slot is None:
                dropped_no_slot += 1
                continue
            received = _parse_dt(r.get("incident_datetime"))
            if received is None:
                continue
            group = (r.get("incident_classification_group") or "").strip()
            if group not in fire_keep_groups:
                continue
            # Fire apparatus counts ARE observed (unlike EMS). engines_assigned
            # drives both Fire severity (quantiles) and the fire_engine pool.
            engines = _to_int(r.get("engines_assigned_quantity"), 0)
            first_on_scene = _parse_dt(r.get("first_on_scene_datetime"))
            valid = (
                r.get("valid_incident_rspns_time_indc") or ""
            ).strip().upper() == "Y"
            latency_s = (
                _to_int(r.get("incident_response_seconds_qy"), -1) if valid else -1
            )
            incidents.append(
                Incident(
                    call_number=str(r.get("starfire_incident_id") or ""),
                    received=received.strftime(_DT_FMT),
                    first_on_scene=(
                        first_on_scene.strftime(_DT_FMT)
                        if first_on_scene
                        else None
                    ),
                    units=("FIRE",),
                    district_id=slot,
                    # carry the classification group + units count in call_type
                    call_type="fire:" + group,
                    call_type_group="FIRE",
                    # original_priority encodes engines count for severity/pools
                    original_priority=str(engines),
                    # number_of_alarms encodes the latency (>=0) or -1 (no/invalid)
                    number_of_alarms=(latency_s if latency_s >= 0 else -1),
                )
            )

        # Deterministic order: by received, then call_number.
        incidents.sort(key=lambda i: (i.received, i.call_number))

        raw_unit_rows = len(ems_rows) + len(fire_rows)
        return AggregateResult(
            incidents=tuple(incidents),
            dropped_junk_battalion=dropped_no_slot,
            raw_unit_rows=raw_unit_rows,
        )

    # --------------------------------------------------------------- Discretize
    def _ems_severity(self, sev_code: str, config: dict[str, Any]) -> int:
        """EMS code 1-8 -> 1-5. Codes 1-2 -> 5, 3 -> 4 (4-8 already filtered)."""
        rebin: dict[str, int] = {
            str(k): int(v) for k, v in config["ems"]["severity_rebin"].items()
        }
        sev = rebin.get(sev_code, config["ems"].get("severity_default", 4))
        return max(1, min(5, sev))

    def _fire_severity(
        self, engines: int, quantiles: dict[str, int], config: dict[str, Any]
    ) -> int:
        """Fire severity from engines-assigned quantiles (NEVER highest_alarm_level).

        Severity buckets from the window's engines-assigned p50/p75/p90 (computed
        in discretize). engines <= p50 -> 2, <= p75 -> 3, <= p90 -> 4, else 5;
        engines == 0 (medical/MFA) -> 2. Clamp [1,5]."""
        if engines <= 0:
            base = config["fire"].get("severity_zero_engines", 2)
        elif engines <= quantiles["p50"]:
            base = 2
        elif engines <= quantiles["p75"]:
            base = 3
        elif engines <= quantiles["p90"]:
            base = 4
        else:
            base = 5
        return max(1, min(5, int(base)))

    def _fire_kind(self, group: str, config: dict[str, Any]) -> str:
        table: dict[str, str] = config["fire"]["group_kind"]
        return table.get(group, config["fire"].get("default_kind", "fire"))

    def _lives(self, kind: str, severity: int, config: dict[str, Any]) -> int:
        table = config["lives"][kind]
        lives = table[severity - 1]  # severity 1..5 -> index 0..4
        return max(1, min(64, int(lives)))

    @staticmethod
    def _quantile(sorted_vals: list[int], q: float) -> int:
        """Nearest-rank quantile of a sorted int list (q in [0,1])."""
        if not sorted_vals:
            return 0
        idx = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
        return int(sorted_vals[idx])

    @staticmethod
    def _reference_triple(c: dict[str, Any]) -> dict[str, Any]:
        """The displayed (received, first_on_scene, latency_s) popover triple.

        DESIGN.md UX delta #8 shows all three together, so they must be
        self-consistent. The EMS table is second-resolution and its
        ``incident_response_seconds_qy`` already matches first_on_scene - received,
        so EMS keeps its authoritative second-resolution ``latency_s`` unchanged.

        FIRE rows carry WHOLE-MINUTE timestamps but a second-resolution
        response-seconds value, so the two disagree by 10-40s. For a FIRE-backed
        reference mission we recompute ``latency_s = round(first_on_scene -
        received)`` from the (minute-rounded) timestamps so the displayed triple
        is internally consistent (accepting minute precision).

        For ANY mission whose response-seconds validity flag was N/invalid
        (``latency_s is None``) we never show a first_on_scene with no trustworthy
        latency, so BOTH first_on_scene and latency_s are set to null.

        The window aggregate mean/median (over the full EMS window) is computed
        elsewhere and is unaffected.
        """
        received = c["received"]
        first_on_scene = c["first_on_scene"]
        latency_s = c["latency_s"]

        if latency_s is None:
            # No trustworthy latency -> never show first_on_scene either.
            first_on_scene = None
        elif c.get("source") == "FIRE" and first_on_scene is not None:
            # Minute-rounded Fire timestamps: make the displayed triple consistent.
            rec = _parse_dt(received)
            fos = _parse_dt(first_on_scene)
            if rec is not None and fos is not None:
                latency_s = round((fos - rec).total_seconds())

        return {
            "received": _iso_offset(received),
            "first_on_scene": _iso_offset(first_on_scene),
            "latency_s": latency_s,
        }

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

        # ---- Fire engines quantiles over the whole window (for severity) ----
        fire_engine_counts = sorted(
            _to_int(i.original_priority, 0)
            for i in agg.incidents
            if i.call_type_group == "FIRE"
        )
        quantiles = {
            "p50": self._quantile(fire_engine_counts, 0.50),
            "p75": self._quantile(fire_engine_counts, 0.75),
            "p90": self._quantile(fire_engine_counts, 0.90),
        }

        # ---- EMS-window reality baseline (the HEADLINE 948s / 16.5% figures) ----
        # Computed over the FULL EMS demand window (every severity code), not the
        # mission subset: held_rate = held / all-EMS-in-window; latency mean/median
        # over EMS rows with a valid response (number_of_alarms >= 0).
        ems_incidents = [i for i in agg.incidents if i.call_type_group == "EMS"]
        ems_total = len(ems_incidents)
        ems_held = sum(1 for i in ems_incidents if i.original_priority == "held")
        ems_latencies = [
            i.number_of_alarms for i in ems_incidents if i.number_of_alarms >= 0
        ]

        # ---- Build candidate MISSIONS (high-acuity EMS + kept Fire groups) ----
        ems_keep = {str(c) for c in config["ems"]["keep_severity_codes"]}
        candidates: list[dict[str, Any]] = []
        for inc in agg.incidents:
            tick = tick_of(inc.received)
            if tick < 0:
                continue
            if inc.call_type_group == "EMS":
                sev_code = inc.call_type.split(":", 1)[1]
                # Only the high-acuity tail becomes a medical_surge mission.
                if sev_code not in ems_keep:
                    continue
                kind = "medical_surge"
                severity = self._ems_severity(sev_code, config)
                held = inc.original_priority == "held"
            else:  # FIRE
                group = inc.call_type.split(":", 1)[1]
                kind = self._fire_kind(group, config)
                engines = _to_int(inc.original_priority, 0)
                severity = self._fire_severity(engines, quantiles, config)
                held = False

            # latency: number_of_alarms carries seconds (>=0) or -1 (none/invalid)
            latency_s: int | None = (
                inc.number_of_alarms if inc.number_of_alarms >= 0 else None
            )
            candidates.append(
                {
                    "incident": inc,
                    "tick": tick,
                    "kind": kind,
                    "severity": severity,
                    "received": inc.received,
                    "first_on_scene": inc.first_on_scene,
                    "latency_s": latency_s,
                    "held": held,
                    "source": inc.call_type_group,
                }
            )

        total = len(candidates)

        # ---- Deterministic stratified sampling to target_missions ----
        from aftershock.data.adapters.sf import SFAdapter  # reuse the sampler

        samp = config["sampling"]
        target = int(samp["target_missions"])
        sample_seed = int(samp["sample_seed"])
        stratum_ticks = int(samp.get("stratum_ticks", tick_minutes))
        kept = SFAdapter()._stratified_sample(
            candidates, target, sample_seed, stratum_ticks
        )

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
            reference_missions[str(idx)] = self._reference_triple(c)

        # ---- Reference aggregates: the HEADLINE Ida reality baseline ----
        # mean/median latency + held_rate are computed over the FULL EMS demand
        # window (every severity code, validity-filtered for latency) so they
        # reproduce the verified Ida figures (≈948s mean, 16.5% held). n_incidents
        # is the mission-candidate population (matches sampling.total); n_arrived
        # is the EMS-window count with a valid response.
        aggregates: dict[str, Any] = {
            "n_incidents": total,
            "n_arrived": len(ems_latencies),
            "n_ems_window": ems_total,
            "mean_latency_s": (
                int(round(mean(ems_latencies))) if ems_latencies else None
            ),
            "median_latency_s": (
                int(round(median(ems_latencies))) if ems_latencies else None
            ),
            "held_rate": round(ems_held / ems_total, 4) if ems_total else 0.0,
        }
        aggregates.update(self._baseline_aggregates(config))

        # ---- Pools: fire_engine OBSERVED (engines p75), others calibrated ----
        pools = self._pools(quantiles, config)

        # ---- Districts ----
        districts = self._districts(config)

        # ---- Mapping (published verbatim) ----
        mapping = {
            "version": config["mapping_version"],
            "mission_kind": dict(config["fire"]["group_kind"]),
            "severity_rule": (
                "EMS code 1-2->5, 3->4 (codes 4-8 excluded by filter); "
                "Fire from engines-assigned quantiles "
                f"(p50={quantiles['p50']}, p75={quantiles['p75']}, "
                f"p90={quantiles['p90']}); NEVER highest_alarm_level"
            ),
            "lives_rule": (
                "LIVES[mission_kind][severity] lookup table "
                f"{config['mapping_version']} (inferred field); clamp [1,64]"
            ),
        }
        # EMS mapping line (medical_surge) folded into mission_kind table.
        mapping["mission_kind"]["EMS severity 1-3 (medical)"] = "medical_surge"

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
                "EMS initial_severity_level_code in {1,2,3} (codes 4-8 dropped); "
                "Fire incident_classification_group in "
                "{Structural,NonStructural Fires,NonMedical Emergencies}; "
                "boroughs only (no CW/X1 noise); response times filtered by "
                "valid_incident_rspns_time_indc=Y"
            ),
        }

        source = self._source_entries(config, fetch_manifest)
        readme = self._readme(config, source, sampling, aggregates, quantiles)

        return DiscretizeResult(
            timeline=timeline,
            pools=pools,
            reference={"missions": reference_missions, "aggregates": aggregates},
            sampling=sampling,
            mapping=mapping,
            field_provenance=field_provenance,
            districts=districts,
            extra={
                "source": source,
                "readme": readme,
                "window_offset": _TZ_SUFFIX,
            },
        )

    # ------------------------------------------------------------ helpers
    def _pools(
        self, quantiles: dict[str, int], config: dict[str, Any]
    ) -> dict[str, dict[str, Any]]:
        pcfg = config["pools"]
        clamp_min = int(pcfg["clamp_min"])
        clamp_max = int(pcfg["clamp_max"])

        pools: dict[str, dict[str, Any]] = {}

        # fire_engine: OBSERVED — engines-assigned p75 in the window.
        observed_engines = max(quantiles["p75"], 1)
        fire_size = max(clamp_min, min(clamp_max, observed_engines + clamp_min - 1))
        pools["fire_engine"] = {
            "size": int(fire_size),
            "basis": "observed",
            "note": (
                f"engines_assigned p75 = {quantiles['p75']} in the window "
                f"(8m42-w767); clamped [{clamp_min},{clamp_max}]"
            ),
        }

        # ambulance: CALIBRATED against held saturation (no EMS unit counts).
        amb = int(pcfg["calibrated"]["ambulance"])
        pools["ambulance"] = {
            "size": max(clamp_min, min(clamp_max, amb)),
            "basis": "calibrated",
            "note": (
                "no EMS unit counts in 76xm-jjuj; calibrated against "
                "held_indicator saturation (16.5% held in window)"
            ),
        }

        for rk in ("rescue_crew", "repair_crew", "supply_truck"):
            default = int(pcfg["calibrated"][rk])
            pools[rk] = {
                "size": max(clamp_min, min(clamp_max, default)),
                "basis": "calibrated",
                "note": f"no NYC analog for {rk}; calibrated default",
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
        out.sort(key=lambda d: d["id"])
        return out

    def _baseline_aggregates(self, config: dict[str, Any]) -> dict[str, Any]:
        """Ida-adjacent calm-window baseline.

        The compiler computes the baseline from a second filtered fetch when a
        baseline raw cache is supplied; otherwise the named window + the verified
        figures from the config are emitted (and never the 538s/6.9% pre-Sandy
        numbers). The values in config are the adapter-computed calm-window
        figures for 2021-08-18/19, recorded so the pack is self-contained."""
        ref = config.get("reference", {})
        return {
            "baseline_window": {
                "start": _window_iso_offset(ref.get("baseline_window_start", "")),
                "end": _window_iso_offset(ref.get("baseline_window_end", "")),
            },
            "baseline_note": ref.get("baseline_note", ""),
            "baseline_mean_latency_s": ref.get("baseline_mean_latency_s"),
            "baseline_median_latency_s": ref.get("baseline_median_latency_s"),
            "baseline_held_rate": ref.get("baseline_held_rate"),
        }

    def _source_entries(
        self, config: dict[str, Any], fetch_manifest: dict[str, Any]
    ) -> list[dict[str, Any]]:
        lic = "NYC Open Data terms (no formal license)"
        lic_url = "https://opendata.cityofnewyork.us/overview/"
        attribution = "FDNY via NYC Open Data"
        return [
            {
                "dataset": "EMS Incident Dispatch Data",
                "provider": "FDNY via NYC Open Data",
                "dataset_id": fetch_manifest.get("ems_resource", "76xm-jjuj"),
                "query_url": fetch_manifest.get("ems_query_url", ""),
                "fetched_at": fetch_manifest.get("fetched_at", ""),
                "rows_fetched": int(fetch_manifest.get("ems_rows_fetched", 0)),
                "license": lic,
                "license_url": lic_url,
                "attribution": attribution,
            },
            {
                "dataset": "Fire Incident Dispatch Data",
                "provider": "FDNY via NYC Open Data",
                "dataset_id": fetch_manifest.get("fire_resource", "8m42-w767"),
                "query_url": fetch_manifest.get("fire_query_url", ""),
                "fetched_at": fetch_manifest.get("fetched_at", ""),
                "rows_fetched": int(fetch_manifest.get("fire_rows_fetched", 0)),
                "license": lic,
                "license_url": lic_url,
                "attribution": attribution,
            },
        ]

    def _readme(
        self,
        config: dict[str, Any],
        source: list[dict[str, Any]],
        sampling: dict[str, Any],
        aggregates: dict[str, Any],
        quantiles: dict[str, int],
    ) -> str:
        caveat = (
            "Demand: real · Latency baseline: real · Lives & outcomes: simulated "
            "model."
        )
        lines = [
            f"# {config['name']}",
            "",
            f"**Scenario id:** `{config['id']}`  ·  **Hazard:** "
            f"`{config['hazard']}`  ·  **Adapter:** `{config['adapter']}`",
            "",
            "> " + caveat,
            "",
            "## Sources (EMS + Fire, joined on the Ida window)",
            "",
        ]
        for src in source:
            lines += [
                f"- **{src['dataset']}** (`{src['dataset_id']}`)",
                f"  - Provider: {src['provider']}",
                f"  - License: {src['license']} — {src['license_url']}",
                f"  - Attribution: {src['attribution']}",
                f"  - Fetched: {src['fetched_at']}  ·  Rows fetched: "
                f"{src['rows_fetched']}",
                "  - Query:",
                "",
                "    ```",
                f"    {src['query_url']}",
                "    ```",
                "",
            ]
        lines += [
            "## Window & sampling",
            "",
            f"- **Window:** {_window_iso_offset(config['extract']['window_start'])}"
            f" → {_window_iso_offset(config['extract']['window_end'])} "
            f"({config['tick_minutes']} min/tick) — the night of Hurricane Ida.",
            f"- **Sampling:** {sampling['kept']} of {sampling['total']} incidents "
            f"— {sampling['method']}, seed {sampling['sample_seed']}.",
            f"- **Filter:** {sampling['filter']}",
            "",
            "## Reality baseline",
            "",
            f"- **Ida window:** mean first-on-scene {aggregates['mean_latency_s']} s"
            f" · median {aggregates['median_latency_s']} s · held "
            f"{aggregates['held_rate']:.1%}.",
            f"- **Baseline window:** {aggregates['baseline_note']} — mean "
            f"{aggregates.get('baseline_mean_latency_s')} s · median "
            f"{aggregates.get('baseline_median_latency_s')} s · held "
            f"{_fmt_rate(aggregates.get('baseline_held_rate'))}.",
            "  The baseline is an Ida-adjacent calm window computed by the adapter "
            "— **not** the 538 s / 6.9 % pre-Sandy figures.",
            "- **Fire timestamps are minute-rounded upstream** (the Fire Incident "
            "Dispatch table stamps whole-minute `incident_datetime` / "
            "`first_on_scene_datetime`). For Fire-backed reference missions the "
            "displayed `latency_s` is recomputed as "
            "`round(first_on_scene - received)` so the popover triple "
            "(received · first-on-scene · latency) is self-consistent at minute "
            "precision; EMS keeps its authoritative second-resolution latency. A "
            "mission with no valid response time shows neither a first-on-scene nor "
            "a latency.",
            "",
            "## Provenance (REAL / MAPPED / INFERRED / SYNTHETIC)",
            "",
            "| Field | Marker |",
            "|---|---|",
            "| `tick` | REAL |",
            "| `district_id` | REAL |",
            "| `mission_kind` | MAPPED |",
            "| `severity` | MAPPED |",
            "| `lives_at_risk` | INFERRED |",
            "| `blockage` | SYNTHETIC |",
            "",
            "Real EMS/Fire incident *types* are mapped onto the four engine "
            "MissionKinds in the offline compiler (mapping "
            f"`{config['mapping_version']}`). EMS severity codes 1-8 are rebinned "
            "(1-2→5, 3→4; codes 4-8 excluded by the filter); Fire severity comes "
            f"from engines-assigned quantiles (p50={quantiles['p50']}, "
            f"p75={quantiles['p75']}, p90={quantiles['p90']}) — **never** "
            "`highest_alarm_level`. `lives_at_risk` is an **inferred** lookup, not "
            "a real casualty count. Blockages are not present in these datasets "
            "(synthetic field, none emitted).",
            "",
            "## Caveat",
            "",
            "> " + caveat,
            "",
            "Real arrival process and real first-on-scene latency (held-rate and "
            "response-seconds verified in the data); lives saved is a simulated "
            "model, **not** a claim about real outcomes. Demand is real · Latency "
            "baseline is real · Lives & outcomes are a simulated model.",
            "",
        ]
        return "\n".join(lines)


def _fmt_rate(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return str(value)
