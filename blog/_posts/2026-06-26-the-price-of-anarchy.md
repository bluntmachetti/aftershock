---
layout: post
title: "We put a number on coordination: the price of anarchy in an agent society"
date: 2026-06-26 09:00:00 -0700
description: "Someone asked whether 'society beats swarm' is really a Nash-equilibrium story. It is — Aftershock is a common-pool resource game, the swarm is the uncoordinated price-of-anarchy baseline, and the society's auction + doctrine is a coordination mechanism. So I built a ruler for it. Measured as the fraction of imperiled lives saved, both coordinated arms (society 67.3%, the scripted central heuristic 66.2%) sit ~8 points above both uncoordinated ones (solo 58.9%, swarm 58.1%) — and the expensive single big model lands at the swarm's anarchy level. The society-vs-swarm gap itself stays suggestive (+6.7 pts, p=0.118). A field report on the game theory under the sim, what we can't yet claim, the experiments that would firm it, and how a mechanism-design dispatch layer could apply to real incident response — with the related work, checked."
log: "009"
read: "11 min"
summary: "A reader asked if the society-beats-swarm theme connects to Nash equilibrium. It does, cleanly: Aftershock is a common-pool resource game (finite shared rescue units, negative externalities), the protocol-free swarm is the uncoordinated price-of-anarchy baseline, and the society's per-tick auction + written doctrine is a coordination mechanism plus a correlation device. I built `aftershock poa` to measure it as a bounded efficiency — fraction of imperiled lives saved, from the sim's exact accounting. Result: both coordinated arms (society 67.3%, scripted central heuristic 66.2%) beat both uncoordinated ones (solo 58.9%, swarm 58.1%), and the big solo model sits at the swarm's anarchy level — coordination beats raw model size here. The pairwise society-vs-swarm gap stays suggestive (+6.7 efficiency points at n=15, p=0.118). I'm honest about what we can't claim (the agents aren't equilibrium-solvers; the true optimum is intractable; on the brutal real NYC-Ida pack the order flips). Then: the experiments that would firm it (a self-enforcement test, a central-planner oracle, auction strategyproofness) and how to turn the lens on real incident-response dispatch — with verified citations."
flags:
  - text: "Price of anarchy 1.11x"
    kind: ok
  - text: "Coordinated > uncoordinated"
    kind: ok
  - text: "solo ≈ swarm"
    kind: warn
  - text: "gap still suggestive (p=0.118)"
    kind: warn
---

A reader looked at the running theme of this log — *a coordinated society of small models versus an
uncoordinated swarm* — and asked the sharp question: **isn't that a Nash-equilibrium story? Does the
hypothesis actually hold if you frame it that way?**

It's the best framing question I've gotten, because it turns out [**Aftershock**](https://github.com/bluntmachetti/aftershock)
isn't *like* a game-theory problem — it *is* one, almost on the nose. So I spent today building a ruler
for it and reading the literature to make sure I was using the words correctly. This is what the ruler
said, what it can't say yet, and where it points next.

## The game hiding under the simulation

Strip the disaster theme away and Aftershock is a **common-pool resource game**. Each tick, six role
agents claim from finite shared pools — ambulances, rescue crews, fire engines, fuel — toward missions
that have a severity, a deadline, and lives at risk. Every claim one agent makes is a unit another agent
can't use: a textbook **negative externality**. That is precisely the setting where game theory predicts
the *uncoordinated* outcome is inefficient — the classic [tragedy of the commons](https://doi.org/10.1126/science.162.3859.1243)
(Hardin, 1968) — and where structure can claw the efficiency back. Elinor Ostrom's Nobel-winning work
([*Governing the Commons*](https://doi.org/10.1017/CBO9780511807763), 1990) is the whole counter-argument:
communities don't need privatization or a central state to avoid the tragedy; they need *institutions* —
shared rules everyone follows. That is a startlingly exact description of what we call **doctrine**.

The formal object for "players sharing congested resources" is a **congestion game**
([Rosenthal, 1973](https://doi.org/10.1007/BF01737559)), and the standard way to score how much selfish
play *costs* is the **price of anarchy** — the ratio between the social optimum and the worst
equilibrium — introduced as the "coordination ratio" by [Koutsoupias & Papadimitriou (1999)](https://doi.org/10.1007/3-540-49116-3_38)
and named by [Papadimitriou (2001)](https://doi.org/10.1145/380752.380883). The canonical worked example
is selfish routing, where [Roughgarden & Tardos (2002)](https://doi.org/10.1145/506147.506153) proved
uncoordinated traffic wastes at most a 4/3 factor with linear latencies. Swap "drivers on roads" for
"agents on ambulances" and you have our benchmark.

Our four arms line up on exactly the coordination axis:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>The arms, as game-theory objects</div>
  <table class="rt">
    <thead><tr><th>Arm</th><th>Mechanism</th><th>Game-theory reading</th></tr></thead>
    <tbody>
      <tr class="lose"><td>swarm</td><td>flat agents, no arbitration (direct dispatch)</td><td>uncoordinated play — the price-of-anarchy baseline</td></tr>
      <tr class="lose"><td>solo</td><td>one big model deciding everything</td><td>centralized but single-headed</td></tr>
      <tr class="win"><td>society</td><td>per-tick auction + written doctrine</td><td>a mechanism + a correlation device</td></tr>
      <tr><td>scripted</td><td>hand-tuned central heuristic ($0)</td><td>a strong central planner</td></tr>
    </tbody>
  </table>
</div>

The society's auction is, literally, a piece of **mechanism design** — the field that runs from
[Vickrey (1961)](https://doi.org/10.1111/j.1540-6261.1961.tb02789.x), [Clarke (1971)](https://doi.org/10.1007/BF01726210)
and [Groves (1973)](https://www.jstor.org/stable/1914085) (the VCG family of efficient, strategyproof
allocation rules). And the doctrine is best read not as Nash but as a **correlated equilibrium**
([Aumann, 1974](https://doi.org/10.1016/0304-4068(74)90037-8)): a shared signal that all agents condition
on, which can beat what uncoordinated best-responses reach on their own.

## What the ruler measured

Raw "lives saved" is unbounded and trajectory-dependent, so it's a poor yardstick for *efficiency*.
Instead I measured the **fraction of imperiled lives saved**, grounded in the sim's own exact accounting:
every life that becomes at-risk is eventually saved, lost, or still-open, so

```
total_at_risk = lives_saved + lives_lost + open_remaining     (an identity, not a model)
efficiency    = lives_saved / total_at_risk                   (in [0, 1])
```

That's `aftershock poa`, computed over recorded runs — deterministic, no API spend. Here is the result:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>Efficiency = fraction of imperiled lives saved (4-arm benchmark, n=5)</div>
  <table class="rt">
    <thead><tr><th>Arm</th><th>Efficiency</th><th>Coordinated?</th></tr></thead>
    <tbody>
      <tr class="win"><td><strong>society</strong> (auction + doctrine)</td><td><strong>67.3%</strong></td><td>yes</td></tr>
      <tr class="win"><td>scripted (central heuristic)</td><td>66.2%</td><td>yes</td></tr>
      <tr class="lose"><td>solo (one big model)</td><td>58.9%</td><td>no</td></tr>
      <tr class="lose"><td>swarm (flat, no protocol)</td><td>58.1%</td><td>no</td></tr>
    </tbody>
  </table>
</div>

The headline isn't the top line — it's the **clustering**. Both *coordinated* arms land at ~66–67%; both
*uncoordinated* arms land at ~58%. The structure, not the specific agent, is what moves the number. And
the sharpest data point in the whole project is hiding in that table: **the expensive single big model
(solo) sits at the swarm's anarchy level.** For this allocation problem, *coordination beats raw model
size* — six cheap models with a protocol out-deliver one big model without one.

Pairing society against swarm directly, pooled to fifteen seeds:

<div class="readout-table">
  <div class="rt-cap"><span class="sq"></span>society vs swarm, paired efficiency (n=15)</div>
  <table class="rt">
    <thead><tr><th>Stat</th><th>Value</th></tr></thead>
    <tbody>
      <tr><td>Mean efficiency delta</td><td><strong>+6.7 points</strong></td></tr>
      <tr><td>Seeds society won</td><td>11 / 15</td></tr>
      <tr><td>Bootstrap 95% CI</td><td>[+2.6, +10.8] (excludes 0)</td></tr>
      <tr class="lose"><td>Sign-test p</td><td>0.118 — <strong>suggestive, not significant</strong></td></tr>
      <tr><td>Price of anarchy (society / swarm)</td><td>1.11×</td></tr>
    </tbody>
  </table>
</div>

So the swarm leaves roughly an eighth of the achievable lives on the table relative to the society — a
real price of anarchy — but the *pairwise* gap carries the same statistical caveat as the raw-lives
number two logs ago: the CI excludes zero, the sign test doesn't clear significance. The efficiency
reframe is more **interpretable** (it's bounded, and it cleanly separates coordinated from uncoordinated);
it does **not** manufacture significance, and I'm not going to pretend it does.

## What I can't claim (and why I'm saying so)

Three honesty bounds, because the fastest way to discredit a game-theory framing is to over-reach with it.

**The agents are not equilibrium-solvers.** They're LLMs following prompts, not utility-maximizers
computing best responses. So "the society *reaches a Nash equilibrium*" is a category error — nobody is
solving a fixed point. The honest statement is that the *game* has an inefficient uncoordinated region
and an efficient coordinated one, and we measure where each arm's *emergent* play lands. (The reason
this still works is one of my favorite results in the field: Roughgarden's
[smoothness framework](https://theory.stanford.edu/~tim/papers/robust.pdf) (2015) shows price-of-anarchy
bounds extend automatically to no-regret learning and correlated play — i.e., they bite even for messy,
non-equilibrium agents. That's the bridge from the textbook to a swarm of language models.)

**The denominator is a ceiling, not a tight optimum.** Efficiency = 1.0 means *every imperiled life
saved*. That's a rigorous upper bound, but it is not the best *achievable* outcome under finite
resources — the true optimum is a multi-tick scheduling problem over the deterministic world, and it's
intractable to compute exactly. So I report "fraction of saveable," never "fraction of optimal."

**On the hardest scenario, the order flips.** On the brutal real-data NYC Hurricane Ida pack, the
scripted central heuristic saves 32.2% and the LLM society saves 8.9%. The coordination edge is a
*synthetic-benchmark* finding; the society is not magic on a savage real scenario. That belongs in the
same paragraph as the win, not in a footnote.

This is also why I keep one skeptical paper open on my desk: Cemri et al.'s
[*Why Do Multi-Agent LLM Systems Fail?*](https://arxiv.org/abs/2503.13657) (2025) catalogs how often
multi-agent LLM setups *underperform* — exactly the null hypothesis a "society beats X" claim has to
survive. Ours survives it structurally and suggestively, not decisively.

## The experiments that would firm it

A ruler is only useful if it tells you what to build next. Three follow-ups, in order of value:

1. **A self-enforcement test.** Right now we know the society's allocation is *efficient* (it eliminates
   priority inversions — see Log 004). We don't know if it's *stable*: could any single role do better by
   deviating from the auction outcome? Replay each contested tick and check for a profitable unilateral
   deviation. If there is none, the coordinated allocation is incentive-compatible — a self-enforcing
   equilibrium, not merely an imposed rule. That's the difference between "we told them to cooperate" and
   "cooperating is their best move."

2. **A central-planner oracle for a tighter optimum.** The save-everyone ceiling is loose. A strong
   omniscient greedy planner run through the *same* deterministic engine would give an *achievable*
   social-optimum proxy, turning "society reaches 67% of saveable" into "society reaches X% of what a
   perfect coordinator achieves" — the real price-of-anarchy denominator.

3. **Auction strategyproofness.** Our auction allocates by urgency bids. Can an agent win contested units
   by *overstating* urgency? The VCG line ([Vickrey](https://doi.org/10.1111/j.1540-6261.1961.tb02789.x)/[Clarke](https://doi.org/10.1007/BF01726210)/[Groves](https://www.jstor.org/stable/1914085))
   is the theory of allocation rules where honesty is the dominant strategy. Testing whether doctrine
   conformance keeps bids truthful — or whether a strategyproof rule does it for free — is a clean
   mechanism-design question we already have the harness to answer.

## Turning the lens on real incident response

Here's the part that makes this more than a benchmark curiosity. **Real incident response already runs on
a coordination doctrine.** The U.S. [National Incident Management System](https://www.fema.gov/sites/default/files/2020-07/fema_nims_doctrine-2017.pdf)
(FEMA, 2017) and its Incident Command System exist *because* uncoordinated multi-agency response to a
disaster is a price-of-anarchy disaster: duplicated effort, contested resources, no clear allocation. ICS
is, in our vocabulary, the correlation device — a shared playbook that every responding unit conditions
on. Aftershock's "doctrine" is a toy of exactly that idea.

And the resource problem under it is a well-studied optimization target: emergency dispatch and
ambulance routing/location have a large literature (see the reviews by
[Mukhopadhyay et al., 2022](https://arxiv.org/abs/2006.04200) and
[Tassone & Choudhury, 2020](https://arxiv.org/abs/2001.05288)), and multi-agent disaster response has been
a grand challenge since [RoboCup Rescue](https://doi.org/10.1609/aimag.v22i1.1542) (Kitano & Tadokoro,
2001), with agent-based simulation used to *plan* resource allocation for major incidents
([Hawe et al., 2015](https://doi.org/10.1016/j.engappai.2015.06.023)).

So a concrete future iteration of the app: a **mechanism-design dispatch layer**. Picture an incident
commander facing several simultaneous incidents competing for the same scarce units. Today that
allocation is often made under load, ad hoc. A decision-support layer could run the *same auction +
doctrine* Aftershock uses — a transparent priority mechanism over real incident demand — and, crucially,
**report the price of anarchy of the status-quo allocation versus the coordinated one**: "this dispatch
pattern is leaving an estimated N% of saveable response-time on the table." That's the honest framing the
whole project is built on — *real demand and latency, simulated outcomes* — extended into a what-if tool.
Not a replacement for human incident command (the literature, and common sense, say the human doctrine is
the point); a ruler the commander can hold up against their own decisions.

The other half is the agents. Generative-agent societies ([Park et al., 2023](https://arxiv.org/abs/2304.03442)),
multi-agent debate ([Du et al., 2023](https://arxiv.org/abs/2305.14325)), and LLM negotiation under
mixed incentives ([Abdelnabi et al., 2023](https://arxiv.org/abs/2309.17234)) are all converging on the
same question Aftershock asks in miniature — and the open problems in getting them to cooperate reliably
are exactly the ones [Dafoe et al. (2020)](https://arxiv.org/abs/2012.08630) laid out for *Cooperative AI*.
A dispatch layer is a high-stakes, legible place to study them: the externalities are real, the doctrine
is real, and the price of anarchy is measurable.

## The honest takeaway

Coordination has a value, and now we can put a number on it: on this benchmark the protocol-free swarm
pays a ~1.11× price of anarchy (pooled over fifteen seeds; ~1.16× on the five-seed four-arm
cross-section), and — the cleaner result — *coordinated* play (whether a hand-tuned heuristic or an LLM
society) beats *uncoordinated* play (whether a swarm or one big model) by ~8 points of saveable lives. The society-vs-swarm edge itself remains suggestive, p=0.118; the order flips on the
hardest real scenario; and the agents aren't really solving for equilibrium at all. The interesting work
isn't claiming a bigger win — it's making the coordination *self-enforcing*, measuring it against a
*tight* optimum, and pointing the same ruler at a real dispatch board.

Build the ruler first, as ever. Then let it tell you what to build.

Live demo: **<https://aftershock.redoubtlabs.dev>** · Code: **<https://github.com/bluntmachetti/aftershock>**
(method + verdict in `docs/EVIDENCE.md` §3 and `docs/FIELD-NOTES.md` §25)

---

### Related work

*Every reference below was independently checked before publishing (Log 006's lesson). Foundations of
game theory and mechanism design; recent multi-agent-LLM work; and the incident-response literature the
application section draws on.*

**Price of anarchy & efficiency of equilibria**
- Koutsoupias, E. & Papadimitriou, C. (1999). *Worst-Case Equilibria.* STACS '99, LNCS 1563, 404–413. <https://doi.org/10.1007/3-540-49116-3_38>
- Papadimitriou, C. H. (2001). *Algorithms, Games, and the Internet.* STOC '01, 749–753. <https://doi.org/10.1145/380752.380883>
- Roughgarden, T. & Tardos, É. (2002). *How Bad Is Selfish Routing?* Journal of the ACM, 49(2), 236–259. <https://doi.org/10.1145/506147.506153>
- Roughgarden, T. (2015). *Intrinsic Robustness of the Price of Anarchy.* Journal of the ACM, 62(5). <https://theory.stanford.edu/~tim/papers/robust.pdf>
- Nisan, N., Roughgarden, T., Tardos, É. & Vazirani, V. (eds.) (2007). *Algorithmic Game Theory.* Cambridge University Press. <https://doi.org/10.1017/CBO9780511800481>

**Congestion games & the commons**
- Rosenthal, R. W. (1973). *A class of games possessing pure-strategy Nash equilibria.* International Journal of Game Theory, 2, 65–67. <https://doi.org/10.1007/BF01737559>
- Hardin, G. (1968). *The Tragedy of the Commons.* Science, 162(3859), 1243–1248. <https://doi.org/10.1126/science.162.3859.1243>
- Ostrom, E. (1990). *Governing the Commons.* Cambridge University Press. <https://doi.org/10.1017/CBO9780511807763>

**Mechanism design & correlated equilibrium**
- Vickrey, W. (1961). *Counterspeculation, Auctions, and Competitive Sealed Tenders.* Journal of Finance, 16(1), 8–37. <https://doi.org/10.1111/j.1540-6261.1961.tb02789.x>
- Clarke, E. H. (1971). *Multipart Pricing of Public Goods.* Public Choice, 11, 17–33. <https://doi.org/10.1007/BF01726210>
- Groves, T. (1973). *Incentives in Teams.* Econometrica, 41(4), 617–631. <https://www.jstor.org/stable/1914085>
- Aumann, R. J. (1974). *Subjectivity and Correlation in Randomized Strategies.* Journal of Mathematical Economics, 1(1), 67–96. <https://doi.org/10.1016/0304-4068(74)90037-8>

**Multi-agent LLM systems**
- Park, J. S., et al. (2023). *Generative Agents: Interactive Simulacra of Human Behavior.* UIST '23; arXiv:2304.03442. <https://arxiv.org/abs/2304.03442>
- Du, Y., et al. (2023). *Improving Factuality and Reasoning in Language Models through Multiagent Debate.* arXiv:2305.14325. <https://arxiv.org/abs/2305.14325>
- Abdelnabi, S., et al. (2023). *Cooperation, Competition, and Maliciousness: LLM-Stakeholders Interactive Negotiation.* arXiv:2309.17234. <https://arxiv.org/abs/2309.17234>
- Cemri, M., et al. (2025). *Why Do Multi-Agent LLM Systems Fail?* arXiv:2503.13657. <https://arxiv.org/abs/2503.13657>
- Dafoe, A., et al. (2020). *Open Problems in Cooperative AI.* arXiv:2012.08630. <https://arxiv.org/abs/2012.08630>

**Incident response & emergency resource allocation**
- FEMA (2017). *National Incident Management System,* 3rd ed. U.S. Dept. of Homeland Security. <https://www.fema.gov/sites/default/files/2020-07/fema_nims_doctrine-2017.pdf>
- Kitano, H. & Tadokoro, S. (2001). *RoboCup Rescue: A Grand Challenge for Multiagent and Intelligent Systems.* AI Magazine, 22(1), 39–52. <https://doi.org/10.1609/aimag.v22i1.1542>
- Mukhopadhyay, A., et al. (2022). *A Review of Incident Prediction, Resource Allocation, and Dispatch Models for Emergency Management.* Accident Analysis & Prevention, 165, 106501; arXiv:2006.04200. <https://arxiv.org/abs/2006.04200>
- Tassone, J. & Choudhury, S. (2020). *A Comprehensive Survey on the Ambulance Routing and Location Problems.* arXiv:2001.05288. <https://arxiv.org/abs/2001.05288>
- Hawe, G. I., et al. (2015). *Agent-based simulation of emergency response to plan the allocation of resources for a hypothetical two-site major incident.* Engineering Applications of Artificial Intelligence, 46, 336–345. <https://doi.org/10.1016/j.engappai.2015.06.023>
