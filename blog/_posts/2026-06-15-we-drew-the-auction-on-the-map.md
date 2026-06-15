---
layout: post
title: "We drew the agent auction on the map. A review caught it pointing at the wrong district."
date: 2026-06-15 09:00:00 -0700
description: "Aftershock's whole result rests on one mechanic: an auction that resolves resource contention between Qwen agents before they act. We rebuilt the observatory's map into a Mission Control view that draws that auction live — and a code review caught the overlay blaming the wrong winning district. Making the mechanism visible meant holding the picture to the same honesty bar as the numbers."
log: "003"
read: "6 min"
summary: "We rebuilt the observatory map into a Mission Control view that draws the agent society's resource auction live — contested districts linked, loser to winner. Then a code review caught it pointing each loss at the wrong winning district. Making the mechanism visible meant making the picture honest."
flags:
  - text: Observability
    kind: ok
  - text: Caught in review
    kind: warn
  - text: Frontend
  - text: Honesty
---

The headline number in [**Aftershock**](https://github.com/bluntmachetti/aftershock) is that a
coordination protocol is worth +28 lives a run — the same five `qwen3.5-flash` workers save 103
lives instead of 75 once you put an auction between them and the shared pool of ambulances, rescue
crews, and fire engines. The protocol-less swarm burns its turns racing for resources that are
already gone; the society resolves that contention *before* anyone acts.

That sentence is the entire project. And until last week you could only read it — in a scrolling
text feed of `granted` / `pool exhausted` rulings off to the side of the map. The thing that
matters most was the thing you couldn't see happen.

So this build was about making the mechanism legible: a Mission Control rebuild of the map that
draws the auction itself, live, on the city. It's also a small parable about how a *picture* can
lie exactly as easily as a number — and on a project whose whole pitch is honesty, the picture
doesn't get a pass.

## From "map" to mission control

The old map was honest but generic: district blocks, mission pins, a panic gauge. Fine. But it
read like a dashboard, not an emergency operations center — and it buried the one event you'd want
a commander watching for.

The rebuild is an EOC command view. A condition state up top (RED/AMBER/BLUE/GREEN, driven by the
nearest deadline, worst severity, and public panic), a tile map of the city, and — the point of the
whole exercise — a **contention overlay**.

When two incidents reach for the last unit of a resource in the same tick, the map draws it: a
dashed line from the district that *lost* to the district that *won*, labeled with the resource
(`AMB CONTESTED`, `RPR CONTESTED`), a halo on both incidents. You watch the auction arbitrate the
Qwen agents' requests in real time. The `qwen3.5-plus` commander and the kernel's auction stop
being a feed you skim and become a thing you see resolve, tick by tick.

And it's derived from data that was already there. Every tick record carries the agents' typed
`resource_request` proposals and the auction's rulings. The overlay is a pure function of those —
no new engine state, no new field, nothing for the deterministic core to even notice. Same pack,
same seed, byte-identical run, now with the contention drawn on top.

## The part a review caught

Here's where it gets honest. The first version of that overlay was subtly wrong, and it took an
automated code review on the pull request to catch it.

The auction can grant the same resource to several incidents before the pool runs dry. Picture one
tick, three incidents reaching for ambulances against a pool that can only cover two of them:

| incident | district | ambulance |
|---|---|---|
| m1 | Harbor | **granted** |
| m2 | Hospital | **granted** (the last one) |
| m3 | Market | **lost** |

m3 lost. But *to whom?* My first cut linked every loser to the **first** winner it happened to
process — here, m1 in Harbor. So the map drew Market's "you lost this" arrow at Harbor, when the
auction's own ruling says plainly: `pool exhausted: ambulance granted to m2` — m3 lost the *last*
unit to m2, in Hospital. The picture pointed at the wrong district.

The reviewer flagged it as a misattribution, and it wasn't theoretical — it was live in the demo
data. The very first contested tick of our headline society run drew the contention line at the
wrong district. A plausible-looking arrow, confidently wrong.

The fix was to stop guessing and read what the auction already said: parse the winner named in each
loser's own ruling, and link to *that* district. It also made the code simpler — the whole
"figure out who the winner probably was" scaffolding just deleted.

I keep a rule for the benchmark: never claim a number you didn't measure on identical worlds. This
was the same rule, wearing a different hat. **A visualization is an inference too, and it earns the
same scrutiny as a number** — more, even, because a clean line on a map *feels* like ground truth
in a way a table never does. The map can be confidently, beautifully wrong. On a project that puts
`REAL / MAPPED / INFERRED / SYNTHETIC` labels on every field precisely so nothing overclaims, an
overlay that quietly fingers the wrong district is the same sin in a prettier font.

## Keeping a reskin honest

It's "just frontend," but the failure modes of a frontend change on a project like this are
specific, so it got the engine treatment:

- **The color contract is frozen.** Society stays cyan, the baselines stay amber — the same coding
  the side-by-side compare view leans on. The redesign added exactly one new color (a caution
  yellow for contention) and reused the existing signals for everything else, so no other view
  shifted a pixel.
- **The honesty surfaces stayed first-class.** The reality strip — real first-on-scene latency vs.
  the agents' simulated response, the `INFERRED` badge on lives-at-risk, the never-fabricated-when-
  null rule — all survived untouched, including on the live NYC Hurricane Ida pack with its borough
  names and provenance.
- **The blast radius was provable.** I pulled the rich incident markers into a shared module so the
  compare view's two synced maps render from the *exact same code* but never inherit the overlay —
  the one map that should change changed, and the one that shouldn't was untouched by construction,
  not by hope.
- **Determinism never moved.** Frontend-only, so the `aftershock verify` digest check couldn't
  regress — and it didn't.

Then it went out the way everything does: local → staging → production, verified at each hop, live
now at the public demo.

## The takeaway

The benchmark exists to make the *result* falsifiable: here's the baseline, here are the identical
worlds, here's the measured gain. This build was the same instinct aimed at the *mechanism*: make
the coordination you can't otherwise see legible enough to watch — and then hold the picture to the
same bar as the numbers, including the part you only find when someone reviews it and asks "wait,
who actually won?"

Make the mechanism visible. Then make sure the visible thing is telling the truth.

**Try it live:** <https://aftershock.redoubtlabs.dev> — load a society run and scrub to a contested
tick · **Read the code:** <https://github.com/bluntmachetti/aftershock>

*Built with Qwen Cloud (`qwen3.5-flash` / `qwen3.5-plus` / `qwen3-max` via DashScope) and Alibaba
Cloud ECS, for the Qwen Cloud Global AI Hackathon.*
