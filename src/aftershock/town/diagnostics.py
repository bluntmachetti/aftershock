"""Free diagnostics over existing run records (Tier-0 M5; $0, no new compute).

Three lenses that post-process ``ticks.ndjson`` + ``world.ndjson`` to show *where*
lives leak, all reproducible by hand from the recorded data (like conformance.py):

1. ``classify_auction_losses`` — every auction defeat bucketed as priority-inversion
   (a higher-priority mission lost to a lower-priority winner — the pathology the
   partial-grant lever S2 targets) vs pure shortage vs displacement vs redundant.
2. ``pipeline_latency`` — per-mission spawn → first-request → first-arrival →
   resolution timing, split by outcome, to tell "lives lost to slow asking" from
   "lives lost to slow granting" from "lives lost to raw scarcity".
3. ``conformance_calibration`` — runs the conformance checker across arms and
   asserts the scripted anchor reads ~1.0 (a checker-bug smoke test; note 11 found
   real measurement bugs in the checker).

Nothing here imports or touches the simulation path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from aftershock.kernel.protocol import ProposalKind, TickRecord
from aftershock.kernel.recorder import load_run

# Auction loss-reason patterns (emitted by town.society.TownResolver).
_RE_CONTESTED = re.compile(
    r"pool exhausted: (?P<res>\S+) granted to (?P<winner>\S+) \(priority (?P<wp>-?\d+)\)"
)
_RE_SHORTAGE = re.compile(
    r"pool exhausted: (?P<res>\S+) has (?P<avail>\d+) available, need (?P<need>\d+)"
)
# society.py emits the redundant resource with {resource!r}, so it is single-quoted
# ('ambulance') unlike the bare resource in the contested/shortage forms — strip them.
_RE_REDUNDANT = re.compile(r"already has sufficient '?(?P<res>[^'\s]+)")
_RE_UNKNOWN = re.compile(r"unknown resource")

_AUCTION = "kernel:auction"

# Categories, in the order they are reported.
LOSS_CATEGORIES = (
    "priority_inversion",
    "displacement",
    "pure_shortage",
    "redundant",
    "unknown_resource",
    "unparsed",
)


def _worlds_by_tick(worlds: list[dict[str, Any]] | None) -> dict[int, dict[str, Any]]:
    if not worlds:
        return {}
    return {entry["tick"]: entry["state"] for entry in worlds}


def _mission_priority(world: dict[str, Any] | None, mission_id: str) -> int | None:
    if world is None:
        return None
    m = world.get("missions", {}).get(mission_id)
    if m is None:
        return None
    return int(m.get("priority", 0))


def _proposal_bodies(record: TickRecord) -> dict[str, dict[str, Any]]:
    """Map proposal_id -> body for every proposal emitted this tick."""
    out: dict[str, dict[str, Any]] = {}
    for resp in record.responses:
        for prop in resp.proposals:
            out[prop.proposal_id] = dict(prop.body)
    return out


def classify_auction_losses(run_dir: Path) -> dict[str, Any]:
    """Bucket every auction loss to separate priority-inversion from raw shortage.

    The auction sorts priority-desc, yet all-or-nothing granting lets a high-qty,
    high-priority bid lose a pool to a *later, lower-priority* bid that fits the
    remainder — a *priority inversion*, the exact pathology the partial-grant lever
    (S2) targets. Crucially this inversion is NOT visible in the loser's reason
    string: the high-priority bid is ranked first, loses before any grant exists,
    and the resolver emits the bare shortage form ("has N available, need M") with
    no winner named. So we reconstruct the contest from the *recorded outcome*: per
    (tick, resource) we compare each pool-exhausted loser's priority against the
    priorities of the missions that actually won that resource that tick (the
    accepted auction grants in ``record.accepted``), reading priorities from the
    world the auction observed (``world[t-1]``). A loser strictly above every
    winner is an inversion; otherwise it is legitimate displacement, or — when no
    mission won the resource at all — pure shortage (the pool was already empty).
    """
    run_dir = Path(run_dir)
    manifest, ticks, worlds = load_run(run_dir)
    wmap = _worlds_by_tick(worlds)
    has_world = len(wmap) > 0

    categories: dict[str, int] = dict.fromkeys(LOSS_CATEGORIES, 0)
    by_resource: dict[str, dict[str, int]] = {}
    examples: dict[str, list[dict[str, Any]]] = {c: [] for c in LOSS_CATEGORIES}
    accepted = 0
    losses = 0
    notes: list[str] = []
    if not has_world:
        notes.append(
            "world.ndjson absent — priorities unknown; pool-exhausted losses fall "
            "back to displacement/shortage (inversions cannot be flagged)"
        )

    def _bump(category: str, resource: str, tick: int, detail: str) -> None:
        categories[category] += 1
        by_resource.setdefault(resource, dict.fromkeys(LOSS_CATEGORIES, 0))
        by_resource[resource][category] += 1
        if len(examples[category]) < 3:
            examples[category].append({"tick": tick, "resource": resource, "detail": detail})

    for record in ticks:
        t = record.tick
        # The auction at tick t ranks by mission.priority as of the end of t-1.
        world_seen = wmap.get(t - 1) if t > 0 else None
        bodies = _proposal_bodies(record)

        # Winners per resource this tick = accepted auction dispatch grants
        # (resolver issues decision_id "{proposal_id}-grant"). Direct dispatches in
        # other arms are excluded, so this stays auction-specific.
        winners_by_res: dict[str, list[int | None]] = {}
        for dec in record.accepted:
            if dec.decision_type != "dispatch" or not dec.decision_id.endswith("-grant"):
                continue
            res = dec.params.get("resource", "")
            mid = dec.params.get("mission_id", "")
            winners_by_res.setdefault(res, []).append(_mission_priority(world_seen, mid))

        for ruling in record.rulings:
            if ruling.decided_by != _AUCTION:
                continue
            if ruling.accepted:
                accepted += 1
                continue
            losses += 1
            reason = ruling.reason

            m_redundant = _RE_REDUNDANT.search(reason)
            if m_redundant:
                _bump("redundant", m_redundant.group("res"), t, reason)
                continue
            if _RE_UNKNOWN.search(reason):
                _bump("unknown_resource", "?", t, reason)
                continue

            # Pool-exhausted loss (contested or shortage textual form). Classify by
            # the reconstructed contest, NOT by the reason string.
            m = _RE_CONTESTED.search(reason) or _RE_SHORTAGE.search(reason)
            if m is None:
                _bump("unparsed", "?", t, reason)  # never silently drop
                continue
            resource = m.group("res")
            winners = winners_by_res.get(resource)
            if not winners:
                # No mission won this resource this tick → the pool was already empty.
                _bump("pure_shortage", resource, t, reason)
                continue
            loser_mid = bodies.get(ruling.proposal_id, {}).get("mission_id", "")
            loser_prio = _mission_priority(world_seen, loser_mid)
            known_winner_prios = [p for p in winners if p is not None]
            if (
                loser_prio is not None
                and known_winner_prios
                and loser_prio > max(known_winner_prios)
            ):
                _bump("priority_inversion", resource, t,
                      f"{loser_mid} (prio {loser_prio}) lost {resource} to a "
                      f"lower-priority winner (max winner prio {max(known_winner_prios)})")
            else:
                _bump("displacement", resource, t, reason)

    return {
        "run_dir": str(run_dir),
        "arm": manifest.get("arm", "unknown"),
        "seed": manifest.get("seed", 0),
        "has_world": has_world,
        "total_auction_rulings": accepted + losses,
        "accepted": accepted,
        "losses": losses,
        "categories": categories,
        "by_resource": by_resource,
        "examples": examples,
        "notes": notes,
    }


def _summary(values: list[float]) -> dict[str, Any] | None:
    """count / mean / median / p90 / max for a list of gap values (None if empty)."""
    if not values:
        return None
    xs = sorted(values)
    n = len(xs)

    def _pct(p: float) -> float:
        if n == 1:
            return xs[0]
        idx = max(0, min(n - 1, int(round(p * (n - 1)))))
        return xs[idx]

    return {
        "count": n,
        "mean": sum(xs) / n,
        "median": _pct(0.5),
        "p90": _pct(0.9),
        "max": xs[-1],
    }


def pipeline_latency(run_dir: Path) -> dict[str, Any]:
    """Per-mission spawn → first-request → first-arrival → resolution latency.

    Gaps (in ticks), aggregated and split by final outcome:
      * ask        = first_request − spawn   (how long before anyone bid)
      * deliver    = first_arrival − first_request (auction + travel pipeline)
      * resolve    = end − spawn             (total time to resolved/failed)
    Comparing resolved vs failed missions shows whether failures came from slow
    asking, slow delivery, or raw scarcity (no arrival at all).
    """
    run_dir = Path(run_dir)
    manifest, ticks, worlds = load_run(run_dir)
    wmap = _worlds_by_tick(worlds)
    notes: list[str] = []
    if not wmap:
        notes.append("world.ndjson absent — latency cannot be computed")
        return {
            "run_dir": str(run_dir),
            "arm": manifest.get("arm", "unknown"),
            "seed": manifest.get("seed", 0),
            "missions": 0,
            "by_outcome": {},
            "notes": notes,
        }

    # First RESOURCE_REQUEST tick per mission, from the decision records.
    first_request: dict[str, int] = {}
    for record in ticks:
        for resp in record.responses:
            for prop in resp.proposals:
                if prop.kind != ProposalKind.RESOURCE_REQUEST:
                    continue
                mid = prop.body.get("mission_id", "")
                if mid and mid not in first_request:
                    first_request[mid] = record.tick

    # Mission trajectory from the world snapshots (sorted by tick).
    traj: dict[str, dict[str, Any]] = {}
    for t in sorted(wmap):
        for mid, m in wmap[t].get("missions", {}).items():
            rec = traj.setdefault(
                mid, {"spawn": t, "arrival": None, "end": None, "outcome": "open"}
            )
            if rec["arrival"] is None and sum(m.get("assigned", {}).values()) > 0:
                rec["arrival"] = t
            status = m.get("status", "open")
            if rec["end"] is None and status in ("resolved", "failed"):
                rec["end"] = t
                rec["outcome"] = status

    # Bucket gaps by outcome.
    buckets: dict[str, dict[str, list[float]]] = {
        oc: {"ask": [], "deliver": [], "resolve": []}
        for oc in ("resolved", "failed", "open")
    }
    n_no_arrival_failed = 0
    for mid, rec in traj.items():
        oc = rec["outcome"]
        spawn = rec["spawn"]
        req = first_request.get(mid)
        arr = rec["arrival"]
        end = rec["end"]
        if req is not None:
            buckets[oc]["ask"].append(float(req - spawn))
            if arr is not None:
                buckets[oc]["deliver"].append(float(arr - req))
        if end is not None:
            buckets[oc]["resolve"].append(float(end - spawn))
        if oc == "failed" and arr is None:
            n_no_arrival_failed += 1

    by_outcome: dict[str, Any] = {}
    for oc, gaps in buckets.items():
        n_missions = sum(1 for r in traj.values() if r["outcome"] == oc)
        by_outcome[oc] = {
            "n_missions": n_missions,
            "ask": _summary(gaps["ask"]),
            "deliver": _summary(gaps["deliver"]),
            "resolve": _summary(gaps["resolve"]),
        }

    if n_no_arrival_failed:
        notes.append(
            f"{n_no_arrival_failed} failed mission(s) never received any resource "
            "(raw scarcity / starvation, not slow delivery)"
        )

    return {
        "run_dir": str(run_dir),
        "arm": manifest.get("arm", "unknown"),
        "seed": manifest.get("seed", 0),
        "missions": len(traj),
        "by_outcome": by_outcome,
        "notes": notes,
    }


# Scripted is the deterministic, doctrine-following anchor — its team_alignment
# should read 1.0. Anything below this tolerance is a checker bug or a real
# scripted violation worth investigating (see FIELD-NOTES note 11).
_ANCHOR_TOLERANCE = 0.999


def conformance_calibration(run_dirs: list[Path]) -> dict[str, Any]:
    """Run the conformance checker across runs; verify the scripted anchor ≈ 1.0."""
    from aftershock.town.conformance import check_run

    runs: list[dict[str, Any]] = []
    warnings: list[str] = []
    scripted_alignments: list[float] = []

    for rd in run_dirs:
        rd = Path(rd)
        report = check_run(rd)
        arm = report.get("arm", "unknown")
        ta = report.get("team_alignment")
        anchor_ok: bool | None = None
        if arm == "scripted":
            anchor_ok = ta is not None and ta >= _ANCHOR_TOLERANCE
            if ta is not None:
                scripted_alignments.append(ta)
            if not anchor_ok:
                warnings.append(
                    f"{rd.name}: scripted team_alignment={ta} < {_ANCHOR_TOLERANCE} "
                    "— checker bug or real scripted violation"
                )
        runs.append({
            "run_dir": str(rd),
            "arm": arm,
            "seed": report.get("seed", 0),
            "team_alignment": ta,
            "role_conformance": report.get("role_conformance", {}),
            "scripted_anchor_ok": anchor_ok,
        })

    return {
        "runs": runs,
        "scripted_anchor": {
            "present": bool(scripted_alignments),
            "all_ok": all(
                r["scripted_anchor_ok"]
                for r in runs
                if r["scripted_anchor_ok"] is not None
            ) if scripted_alignments else None,
            "min_team_alignment": min(scripted_alignments) if scripted_alignments else None,
        },
        "warnings": warnings,
    }


def diagnose_run(run_dir: Path) -> dict[str, Any]:
    """Combined per-run diagnostics: auction-loss classification + latency."""
    return {
        "auction_losses": classify_auction_losses(run_dir),
        "latency": pipeline_latency(run_dir),
    }


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------


def _fmt_summary(s: dict[str, Any] | None) -> str:
    if s is None:
        return "—"
    return (
        f"n={s['count']} mean={s['mean']:.1f} "
        f"med={s['median']:.0f} p90={s['p90']:.0f} max={s['max']:.0f}"
    )


def render_diagnostics_markdown(report: dict[str, Any]) -> str:
    """Render diagnose_run output (one run) as markdown."""
    al = report["auction_losses"]
    lat = report["latency"]
    lines: list[str] = []
    lines.append(f"# Diagnostics — {al['arm']} seed={al['seed']}")
    lines.append("")

    # Auction losses
    lines.append("## Auction losses")
    lines.append("")
    lines.append(
        f"{al['accepted']} grants · {al['losses']} losses "
        f"of {al['total_auction_rulings']} auction rulings"
    )
    lines.append("")
    lines.append("| category | count |")
    lines.append("|---|---|")
    for cat in LOSS_CATEGORIES:
        cnt = al["categories"].get(cat, 0)
        if cnt:
            lines.append(f"| {cat} | {cnt} |")
    lines.append("")
    if al["categories"].get("priority_inversion"):
        lines.append(
            f"> **{al['categories']['priority_inversion']} priority inversions** — "
            "higher-priority missions lost a pool to lower-priority winners "
            "(the all-or-nothing pathology partial-grant / S2 targets)."
        )
        lines.append("")
    for note in al["notes"]:
        lines.append(f"- _{note}_")
    if al["notes"]:
        lines.append("")

    # Latency
    lines.append("## Pipeline latency (ticks)")
    lines.append("")
    lines.append(f"{lat['missions']} missions tracked.")
    lines.append("")
    if lat["by_outcome"]:
        lines.append(
            "| outcome | n | ask (spawn→req) | deliver (req→arrive) "
            "| resolve (spawn→end) |"
        )
        lines.append("|---|---|---|---|---|")
        for oc in ("resolved", "failed", "open"):
            ob = lat["by_outcome"].get(oc)
            if not ob or ob["n_missions"] == 0:
                continue
            lines.append(
                f"| {oc} | {ob['n_missions']} | {_fmt_summary(ob['ask'])} "
                f"| {_fmt_summary(ob['deliver'])} | {_fmt_summary(ob['resolve'])} |"
            )
        lines.append("")
    for note in lat["notes"]:
        lines.append(f"- _{note}_")
    if lat["notes"]:
        lines.append("")
    return "\n".join(lines) + "\n"


def render_calibration_markdown(report: dict[str, Any]) -> str:
    """Render conformance_calibration output as markdown."""
    lines: list[str] = []
    lines.append("# Conformance calibration")
    lines.append("")
    anchor = report["scripted_anchor"]
    if anchor["present"]:
        verdict = "PASS" if anchor["all_ok"] else "FAIL"
        lines.append(
            f"Scripted anchor: **{verdict}** "
            f"(min team_alignment={anchor['min_team_alignment']:.3f}; "
            "the deterministic anchor should read 1.000)."
        )
    else:
        lines.append("No scripted run supplied — anchor calibration skipped.")
    lines.append("")
    lines.append("| run | arm | seed | team_alignment | anchor |")
    lines.append("|---|---|---|---|---|")
    for r in report["runs"]:
        ta = r["team_alignment"]
        ta_str = f"{ta:.3f}" if ta is not None else "—"
        anchor_str = (
            "—" if r["scripted_anchor_ok"] is None
            else ("ok" if r["scripted_anchor_ok"] else "BUG?")
        )
        name = Path(r["run_dir"]).name
        lines.append(f"| {name} | {r['arm']} | {r['seed']} | {ta_str} | {anchor_str} |")
    lines.append("")
    for w in report["warnings"]:
        lines.append(f"- ⚠️ {w}")
    if report["warnings"]:
        lines.append("")
    return "\n".join(lines) + "\n"
