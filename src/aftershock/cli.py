"""Aftershock CLI: run | verify | replay.

aftershock run    --seed 42 --ticks 60 --arm scripted [--out runs] [--quiet]
aftershock verify --seed 42 --ticks 60
aftershock replay <run_dir>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

from aftershock.kernel.engine import Engine
from aftershock.kernel.recorder import Recorder, load_run
from aftershock.kernel.registry import DecisionRegistry
from aftershock.kernel.roles import load_roles
from aftershock.town.decisions import register_all
from aftershock.town.heuristics import (
    CommanderScripted,
    CommsScripted,
    FireScripted,
    InfraScripted,
    MedicalScripted,
    RescueScripted,
)
from aftershock.town.society import TownResolver, TownSociety
from aftershock.town.state import new_town

_ROLES_DIR = Path(__file__).parent / "town" / "roles"


def _build_scripted_agents(roles: dict) -> dict:
    return {
        "commander": CommanderScripted("commander", "commander"),
        "medical": MedicalScripted("medical", "medical"),
        "rescue": RescueScripted("rescue", "rescue"),
        "fire": FireScripted("fire", "fire"),
        "infrastructure": InfraScripted("infrastructure", "infrastructure"),
        "comms": CommsScripted("comms", "comms"),
    }


def _build_engine(seed: int, ticks: int, out_dir: Path, run_id: str) -> Engine:
    world = new_town(seed)
    society = TownSociety(max_ticks=ticks)
    registry = DecisionRegistry()
    register_all(registry)
    roles = load_roles(_ROLES_DIR)
    agents = _build_scripted_agents(roles)
    resolver = TownResolver()
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "seed": seed,
        "ticks": ticks,
        "arm": "scripted",
    }
    recorder = Recorder(out_dir, run_id, manifest)
    return Engine(
        world=world,
        society=society,
        agents=agents,
        registry=registry,
        roles=roles,
        resolver=resolver,
        recorder=recorder,
        seed=seed,
        max_ticks=ticks,
    )


def _run_id(seed: int, arm: str) -> str:
    return f"seed{seed}-{arm}"


def cmd_run(args: argparse.Namespace) -> int:
    seed: int = args.seed
    ticks: int = args.ticks
    arm: str = args.arm
    out_dir = Path(args.out)
    quiet: bool = args.quiet

    run_id = _run_id(seed, arm)
    engine = _build_engine(seed, ticks, out_dir, run_id)

    async def _run() -> Any:
        return await engine.run()

    summary = asyncio.run(_run())

    if not quiet:
        print(f"Run {summary.run_id}  seed={summary.seed}  ticks={summary.ticks_run}")
        print("-" * 60)
        s = summary.final_scores
        print(f"  Lives saved:  {int(s.get('lives_saved', 0))}")
        print(f"  Lives lost:   {int(s.get('lives_lost', 0))}")
        print(f"  Missions resolved: {int(s.get('missions_resolved', 0))}")
        print(f"  Missions failed:   {int(s.get('missions_failed', 0))}")
        print(f"  Missions open:     {int(s.get('missions_open', 0))}")
        print(f"  Panic:        {s.get('panic', 0.0):.3f}")
        print(f"  Cost USD:     {summary.cost.get('cost_usd', 0.0):.4f}")
        print(f"  Run dir:      {summary.run_dir}")

    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    seed: int = args.seed
    ticks: int = args.ticks

    async def _run_into(tmp: Path, tag: str) -> list[str]:
        run_id = f"verify-{tag}"
        engine = _build_engine(seed, ticks, tmp, run_id)
        await engine.run()
        _, records = load_run(tmp / run_id)
        return [r.world_digest for r in records]

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        async def _both() -> tuple[list[str], list[str]]:
            a = await _run_into(tmp / "a", "a")
            b = await _run_into(tmp / "b", "b")
            return a, b

        digests_a, digests_b = asyncio.run(_both())

    if digests_a == digests_b:
        print("PASS — both runs produced identical world-digest sequences")
        return 0
    else:
        print("FAIL — digest mismatch")
        for i, (da, db) in enumerate(zip(digests_a, digests_b, strict=False)):
            if da != db:
                print(f"  tick {i}: run1={da[:16]}… run2={db[:16]}…")
        return 1


def cmd_replay(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"error: run directory not found: {run_dir}", file=sys.stderr)
        return 1

    manifest, records = load_run(run_dir)
    print(f"Replay: {run_dir.name}  seed={manifest.get('seed')}  arm={manifest.get('arm')}")
    print(f"{'Tick':>5}  {'Saved':>6}  {'Lost':>6}  {'Open':>5}  {'Res':>5}  {'Fail':>5}  {'Panic':>7}")  # noqa: E501
    print("-" * 50)

    for record in records:
        s = record.scores
        tick = record.tick
        saved = int(s.get("lives_saved", 0))
        lost = int(s.get("lives_lost", 0))
        open_m = int(s.get("missions_open", 0))
        res = int(s.get("missions_resolved", 0))
        fail = int(s.get("missions_failed", 0))
        panic = s.get("panic", 0.0)
        print(f"{tick:>5}  {saved:>6}  {lost:>6}  {open_m:>5}  {res:>5}  {fail:>5}  {panic:>7.3f}")

    if records:
        s = records[-1].scores
        print("-" * 50)
        print(f"Final: lives_saved={int(s.get('lives_saved', 0))}  "
              f"lives_lost={int(s.get('lives_lost', 0))}  "
              f"panic={s.get('panic', 0.0):.3f}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="aftershock")
    sub = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = sub.add_parser("run", help="Run a simulation")
    p_run.add_argument("--seed", type=int, required=True)
    p_run.add_argument("--ticks", type=int, required=True)
    p_run.add_argument("--arm", default="scripted", choices=["scripted"])
    p_run.add_argument("--out", default="runs")
    p_run.add_argument("--quiet", action="store_true")

    # verify
    p_verify = sub.add_parser("verify", help="Verify determinism")
    p_verify.add_argument("--seed", type=int, required=True)
    p_verify.add_argument("--ticks", type=int, required=True)

    # replay
    p_replay = sub.add_parser("replay", help="Print scoreboard from a run dir")
    p_replay.add_argument("run_dir")

    args = parser.parse_args()

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "verify":
        sys.exit(cmd_verify(args))
    elif args.command == "replay":
        sys.exit(cmd_replay(args))
