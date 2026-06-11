# Aftershock — Design

Aftershock is a small **agent-society kernel** plus its flagship society: a disaster-response
town. The kernel is generic — it knows nothing about earthquakes; the town package supplies
the world, the decision types, and the scenario.

```
src/aftershock/
├── kernel/          # reusable agent-society kernel
│   ├── protocol.py  # frozen message types (DONE — pinned by snapshot test)
│   ├── rng.py       # seed derivation
│   ├── recorder.py  # canonical JSON, digests, NDJSON run records, replay loading
│   ├── ledger.py    # token/cost accounting
│   ├── registry.py  # decision types: validate/apply plugins
│   ├── roles.py     # roles-as-YAML with decision envelopes
│   ├── agents.py    # Agent ABC
│   ├── negotiation.py  # proposal routing + Resolver protocol
│   └── engine.py    # the tick loop
├── town/            # the disaster-response society
│   ├── state.py     # TownState, districts, missions, resource pools
│   ├── events.py    # scenario timeline + world dynamics (decay, arrivals, spread)
│   ├── decisions.py # registered decision handlers
│   ├── scoring.py   # per-tick score dict
│   ├── heuristics.py # scripted agents (the $0 baseline arm)
│   ├── society.py   # TownSociety + TownResolver (the contested-resource auction)
│   └── roles/*.yaml # one file per role
└── cli.py           # aftershock run | verify | replay
```

## Invariants

1. **Determinism.** Same seed + same agent responses ⇒ byte-identical run records.
   - All randomness flows from `rng.rng_for(seed, *parts)`. Never `random` module-level
     functions, `time.time()`, `datetime.now()`, `uuid4()`, or `os.urandom()` anywhere in
     the simulation path. IDs come from counters.
   - Iterate mappings in sorted-key order whenever order can affect outcomes.
   - Inter-agent state coupling uses values copied from the start-of-tick snapshot, never
     live mutation mid-phase.
2. **One agent's failure never kills the tick.** Timeouts and exceptions become an empty
   `AgentResponse` with `error` set; the world moves on.
3. **Every decision is validated; every rejection has a reason and is fed back** into the
   issuing agent's next observation (`Observation.rejections`).
4. **Rationale is simulation-inert.** Stored for replay, never read by the engine.
5. **Provenance.** Every tick writes a `TickRecord` (observation digests, all responses,
   rulings, accepted/rejected decisions, events, scores, world digest) as one NDJSON line.
6. **The kernel does no IO** except through `recorder.py`, and never imports from `town/`.

## Kernel module contracts

Import from submodules directly (`from aftershock.kernel.protocol import ...`).
`kernel/__init__.py` stays empty.

### rng.py

```python
def derive_seed(root_seed: int, *parts: str | int) -> int
    # blake2b over "root/part1/part2/..." → 63-bit int. Stable across runs and platforms.
def rng_for(root_seed: int, *parts: str | int) -> random.Random
    # random.Random(derive_seed(...))
```

### recorder.py

```python
def canonical_json(obj: Any) -> str
    # Pydantic models via model_dump(mode="json"); dicts with sorted keys; compact
    # separators; ensure_ascii. The single source of truth for hashing.
def digest(obj: Any) -> str           # sha256 hexdigest of canonical_json(obj)

class Recorder:
    def __init__(self, out_dir: Path, run_id: str, manifest: dict[str, Any]) -> None
        # creates out_dir/run_id/, writes run.json (manifest), opens ticks.ndjson
    def write_tick(self, record: TickRecord) -> None   # one canonical-JSON line, flushed
    def close(self) -> None                            # also a context manager
    @property
    def run_dir(self) -> Path

def load_run(run_dir: Path) -> tuple[dict[str, Any], list[TickRecord]]
```

### ledger.py

```python
class CostLedger:
    def record(self, tick: int, agent_id: str, usage: TokenUsage) -> None
    def totals(self) -> dict[str, Any]
        # {"prompt_tokens", "completion_tokens", "cost_usd",
        #  "by_agent": {agent_id: {...}}, "by_model": {model: {...}}}
```

### registry.py

```python
class DecisionHandler(ABC):
    decision_type: ClassVar[str]
    Params: ClassVar[type[BaseModel]]          # schema for Decision.params
    @abstractmethod
    def validate(self, world: Any, params: BaseModel) -> str | None
        # rejection reason, or None if valid
    @abstractmethod
    def apply(self, world: Any, params: BaseModel, tick: int, rng: random.Random) -> list[WorldEvent]

class DecisionRegistry:
    def register(self, handler: DecisionHandler) -> None      # duplicate type ⇒ ValueError
    def decision_types(self) -> tuple[str, ...]               # sorted
    def validate(self, world, decision: Decision, allowed: tuple[str, ...] | None
                 ) -> tuple[BaseModel | None, str | None]
        # Checks, in order: known decision_type; envelope (allowed=None means any);
        # Params parse (pydantic errors become the reason); handler.validate.
        # Returns (params, None) on success, (None, reason) on rejection.
    def apply(self, world, decision: Decision, params: BaseModel, tick: int,
              rng: random.Random) -> list[WorldEvent]
```

### roles.py

```python
class RoleSpec(BaseModel):       # frozen
    name: str
    display_name: str = ""
    description: str = ""
    allowed_decisions: tuple[str, ...] = ()
    system_prompt: str = ""      # consumed by LLM agents; unused by scripted agents
    model: str = ""              # model alias for LLM agents
    temperature: float = 0.3

def load_roles(path: Path) -> dict[str, RoleSpec]
    # loads every *.yaml in the directory; key = spec.name; duplicates ⇒ ValueError
```

### agents.py

```python
class Agent(ABC):
    def __init__(self, agent_id: str, role: str) -> None
    @abstractmethod
    async def act(self, observation: Observation) -> AgentResponse

class ScriptedAgent(Agent):
    # convenience base: subclass implements `act_sync(observation) -> AgentResponse`,
    # `act` wraps it. Scripted agents must be pure functions of the observation
    # (deterministic, stable tie-breaking).
```

### negotiation.py

Proposal routing rules (implemented by the engine, documented here; the Resolver is the
extension point):

- `recipient=<agent_id>` (**bilateral**): delivered to the recipient's inbox **next tick**.
  The recipient answers with a `ProposalResponse`. Answered ⇒ handed to the resolver as
  `answered`; still unanswered after one tick in the inbox ⇒ handed over as `expired`.
- `recipient=None, kind=INFO_SHARE` (**broadcast**): delivered to every other agent's inbox
  next tick; automatic accepted ruling, `decided_by="kernel:broadcast"`.
- `recipient=None`, any other kind (**arbiter-routed**): handed to the resolver in the same
  tick as `arbiter` — this is how contested-resource auctions work.

```python
class Resolver(Protocol):
    name: str
    def resolve(self, world: Any, tick: int,
                arbiter: list[Proposal],
                answered: list[tuple[Proposal, ProposalResponse]],
                expired: list[Proposal],
                rng: random.Random,
                ) -> tuple[list[ProposalRuling], list[Decision]]
        # Returns rulings for every proposal it was handed, plus zero or more
        # kernel-granted decisions (e.g. an auction win becomes a dispatch).
        # Granted decisions are validated against the full registry but are
        # exempt from role envelopes; use decision_id f"{proposal_id}-grant".

class DefaultResolver:
    # answered → ruling mirroring the response (decided_by=responder, reason=note)
    # expired  → declined, decided_by="kernel:timeout", reason="no response"
    # arbiter  → declined, decided_by="kernel:default", reason="no arbiter configured"
```

### engine.py

```python
class Society(Protocol):
    def agent_ids(self) -> tuple[str, ...]
    def role_of(self, agent_id: str) -> str
    def build_view(self, world: Any, agent_id: str, tick: int) -> dict[str, Any]
    def scheduled_events(self, world: Any, tick: int, rng: random.Random) -> list[WorldEvent]
        # world dynamics: scenario timeline, decay, arrivals. Mutates world.
    def score(self, world: Any, tick: int) -> dict[str, float]
    def is_over(self, world: Any, tick: int) -> bool
    def world_state(self, world: Any) -> dict[str, Any]   # canonical dict for digesting

@dataclass
class RunSummary:
    run_id: str; seed: int; ticks_run: int
    final_scores: dict[str, float]; cost: dict[str, Any]; run_dir: str

class Engine:
    def __init__(self, *, world, society: Society, agents: dict[str, Agent],
                 registry: DecisionRegistry, roles: dict[str, RoleSpec],
                 resolver: Resolver, recorder: Recorder, seed: int,
                 max_ticks: int, agent_timeout_s: float = 30.0) -> None
        # Boot validation (fail fast): every agent's role exists in roles; every
        # role's allowed_decisions exist in the registry; agent ids match
        # society.agent_ids().
    async def run(self) -> RunSummary
    async def step(self, tick: int) -> TickRecord
```

Tick pipeline (one `rng = rng_for(seed, "tick", tick)` threaded through in this order):

1. **OBSERVE** — for each agent in sorted order, compose
   `Observation(tick, agent_id, role, view=society.build_view(...), inbox, rulings,
   rejections, allowed_decisions=roles[role].allowed_decisions)` from the feedback buffers
   filled last tick. Record `digest(observation)` per agent.
2. **ACT** — `asyncio.gather` over `agent.act(obs)` with `agent_timeout_s` per agent.
   Timeout/exception ⇒ `AgentResponse(agent_id=..., error="timeout"|repr(exc))`.
   **Identity check:** decisions with `agent_id` ≠ the acting agent are rejected with
   reason `"identity mismatch"`; proposals/responses with mismatched `sender`/`responder`
   are dropped with a declined ruling. Duplicate `decision_id` within a tick ⇒ rejected.
3. **RESOLVE** — route this tick's proposals per negotiation.py rules; pair last tick's
   delivered bilaterals with this tick's responses; call
   `resolver.resolve(world, tick, arbiter, answered, expired, rng)`.
4. **VALIDATE** — agent decisions sorted by `(agent_id, decision_id)`, then resolver-granted
   decisions, through `registry.validate` (granted ones with `allowed=None`).
5. **APPLY** — `registry.apply` for each accepted decision, in validation order,
   accumulating `WorldEvent`s.
6. **WORLD** — `society.scheduled_events(world, tick, rng)`.
7. **SCORE** — `society.score(world, tick)`.
8. **RECORD** — ledger from `response.usage`; write `TickRecord` with
   `world_digest=digest(society.world_state(world))`; refill feedback buffers
   (next-tick inboxes, rulings, rejections).

## The town society

World dynamics constants live in `town/state.py` as module-level UPPERCASE values — round
numbers, easy to tweak.

### state.py

- `ResourceKind` (StrEnum): `ambulance, rescue_crew, fire_engine, repair_crew, supply_truck`
- `MissionKind` (StrEnum): `collapse_rescue, fire, medical_surge, infra_repair`
- `MissionStatus` (StrEnum): `open, resolved, failed`
- `District`: `id, name, road_blocked: bool`. Six districts: `old_town, harbor,
  hospital_district, market, residential_north, industrial`.
- `Mission`: `id, kind, district_id, severity (1-5), lives_at_risk, spawned_tick,
  deadline_tick, required: dict[str, int], assigned: dict[str, int], progress: float,
  status, priority: int = 0, resolved_tick: int | None = None`
- `ResourcePool`: `kind, total, available`
- `PendingArrival`: `due_tick, mission_id, resource, qty` (road-blocked dispatch delay);
  also used for repair crews returning.
- `TownState`: `tick, seed, districts, missions, pools, pending: list[PendingArrival],
  timeline: list[TimelineEntry], panic: float, lives_saved: int, lives_lost: int,
  next_mission_no: int` + `to_dict()` (canonical, sorted) used by `world_state`.
- `new_town(seed: int) -> TownState`: pools `{ambulance: 6, rescue_crew: 5, fire_engine: 4,
  repair_crew: 3, supply_truck: 4}`; precomputed timeline via `rng_for(seed, "timeline")`:
  main quake at tick 0 spawns 4-6 missions across districts; aftershocks around ticks 8-12
  and 20-26 spawn 2-4 each; 1-2 road blockages with the quake/aftershocks. Mission
  `required` by kind, scaled by severity, e.g. collapse_rescue ⇒ rescue_crew + ambulance;
  fire ⇒ fire_engine (+ ambulance at severity ≥ 3); medical_surge ⇒ ambulance +
  supply_truck; infra_repair ⇒ repair_crew.

### events.py — world dynamics, applied in `scheduled_events` in this order

1. **Arrivals**: pending entries with `due_tick <= tick` land (assign to mission / return
   crew / unblock road).
2. **Progress & decay** (missions in sorted id order): staffing ratio = min over required
   kinds of `assigned/required`; `progress += 0.25 * ratio`. Each open mission loses
   `round(0.1 * severity * (1 + panic))` lives per tick (clamped at 0).
   `progress >= 1.0` ⇒ resolved: remaining `lives_at_risk` added to `lives_saved`,
   resources return to pools. `tick >= deadline_tick` ⇒ failed: remaining lives lost,
   resources return.
3. **Timeline**: spawn this tick's missions/blockages; panic `+0.05` per spawn.
4. **Fire spread**: a fire open ≥ 6 ticks gets `severity + 1` (max 5) and
   `lives_at_risk += 5`, once per mission.
5. **Panic decay**: `-0.02`, clamp `[0, 1]`. (`+0.1` on each mission failure, in step 2.)

Every change emits a `WorldEvent` (kinds: `mission_spawned, arrival, mission_progress,
casualties, mission_resolved, mission_failed, road_blocked, road_unblocked, fire_spread,
panic_changed`).

### decisions.py — registered handlers

- `dispatch {mission_id, resource, qty}`: pool→mission (or pending arrival with +2 ticks if
  the district road is blocked). Valid only if mission open, pool has qty, resource is in
  `required`. **No role envelope includes dispatch** — it enters the world only as an
  auction grant, which keeps negotiation load-bearing rather than decorative.
- `recall {mission_id, resource, qty}`: mission→pool.
- `set_priority {mission_id, priority 0-10}`: commander only.
- `repair_road {district_id}`: consumes a repair_crew for 3 ticks, then unblocks.
- `broadcast {message ≤ 280 chars}`: comms; panic `-0.1`.

### society.py

- `TownSociety`: agents `commander, medical, rescue, fire, infrastructure, comms`
  (role name == agent id). `build_view` returns a compact dict: open missions (id, kind,
  district, severity, lives_at_risk, deadline_in, required, assigned, progress, priority),
  pool availability, blocked districts, panic, totals. Role-scoping starts coarse
  (everyone sees the compact state) and tightens when LLM agents land.
- `is_over`: timeline exhausted and no open missions, or `tick >= max_ticks`.
- `TownResolver(name="auction")`: contested `RESOURCE_REQUEST` proposals
  (body: `{mission_id, resource, qty, urgency 1-10}`) sorted by
  `(mission.priority desc, severity desc, deadline asc, urgency desc, sender asc)`;
  grant while `pool.available` lasts ⇒ accepted ruling + granted `dispatch`; otherwise
  declined with a reason naming what outbid it, e.g.
  `"pool exhausted: ambulance granted to m3 (priority 8)"` — losers learn *why*.
  Everything else falls through to `DefaultResolver` behaviour.

### heuristics.py — the scripted arm (deterministic, observation-only)

- `CommanderScripted`: assigns `priority = min(10, severity * 2 + urgency_bonus)` to
  unprioritised missions (urgency_bonus 2 if deadline within 6 ticks); accepts escalations.
- `MedicalScripted, RescueScripted, FireScripted, InfraScripted`: for open missions of
  their kind (highest priority first), request unmet resources via `RESOURCE_REQUEST`;
  infra also `repair_road` for blocked districts. Escalate to the commander when a
  mission's deadline is within 4 ticks and staffing is below half.
- `CommsScripted`: `broadcast` when panic > 0.4.

### roles/*.yaml

`commander` (set_priority), `medical`/`rescue`/`fire` (recall), `infrastructure`
(recall, repair_road), `comms` (broadcast). Dispatch is auction-granted only.

## The LLM layer (`src/aftershock/llm/`)

LLM agents are ordinary `Agent`s: they see the same observations, emit the same typed
responses, and get the same rejection feedback as scripted agents. The engine cannot tell
the difference — which is what makes arms comparable. Everything here must be fully
testable offline via `MockProvider`; no test may require a network or an API key.

### provider.py — the single chokepoint for model calls

Every model call in the project goes through `Provider.chat` so cost accounting, retries,
and request shaping live in exactly one place.

```python
DASHSCOPE_INTL_BASE = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"

# (usd_per_1M_input, usd_per_1M_output) — first price tier; our prompts stay well under it
MODEL_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "qwen3.5-flash": (0.10, 0.40),
    "qwen3.5-plus": (0.40, 2.40),
    "qwen3-max": (1.20, 6.00),
    "qwen-flash": (0.05, 0.40),
    "qwen-plus": (0.40, 1.20),
    "qwen-max": (1.60, 6.40),
    "qwen-turbo": (0.05, 0.20),
}

@dataclass(frozen=True)
class ChatResult:
    text: str
    usage: TokenUsage   # cost_usd computed from MODEL_PRICES (unknown model -> 0.0)

class Provider(Protocol):
    async def chat(self, *, model: str, system: str, user: str,
                   temperature: float, json_mode: bool = True) -> ChatResult

class QwenProvider:
    def __init__(self, api_key: str | None = None,        # default: env DASHSCOPE_API_KEY
                 base_url: str = DASHSCOPE_INTL_BASE,
                 timeout_s: float = 45.0, max_retries: int = 2,
                 transport: httpx.AsyncBaseTransport | None = None) -> None
        # missing key -> ProviderError at construction with a friendly message
    # POST {base_url}/chat/completions, Authorization: Bearer <key>.
    # json_mode=True adds response_format={"type":"json_object"} and
    # "enable_thinking": false, and never sets max_tokens (DashScope JSON-mode rules;
    # the word "JSON" in the prompt is the contract's job, asserted here defensively).
    # Retries on 429/5xx/timeouts with exponential backoff (0.5s, 1s, 2s);
    # exhausted retries raise ProviderError. transport is injectable for tests
    # (httpx.MockTransport).

class MockProvider:
    def __init__(self, script: list[str] | Callable[[str, str, str], str]) -> None
        # returns scripted texts in order (or callable of model/system/user);
        # fabricates plausible TokenUsage (len//4 tokens) with real cost math;
        # records every call as (model, system, user) in .calls
```

### parse.py — tolerant, strict-enough output parsing

```python
class LLMDecision(BaseModel):   # extra="ignore" on all three
    decision_type: str; params: dict[str, Any] = {}; rationale: str = ""
class LLMProposal(BaseModel):
    kind: str; recipient: str | None = None; body: dict[str, Any] = {}
class LLMResponse(BaseModel):
    proposal_id: str; accept: bool; note: str = ""
class LLMOutput(BaseModel):
    decisions: list[LLMDecision] = []; proposals: list[LLMProposal] = []
    responses: list[LLMResponse] = []

class LLMParseError(Exception): ...   # carries a short reason

def parse_llm_output(text: str) -> LLMOutput
    # strip markdown code fences; extract the first balanced {...} block;
    # json.loads; validate. Unknown decision_types/kinds pass through —
    # the registry/engine rejects them with reasons (that IS the feedback loop).
```

### digest.py — bounded observations for small-context models

```python
def sanitize(text: str, cap: int = 200) -> str
    # for any agent-authored text spliced into another agent's prompt:
    # strip <| ... |> control sequences and backticks, collapse whitespace,
    # neutralise leading "system:"/"assistant:"/"user:" prefixes, cap length.

def render_observation(obs: Observation, max_missions: int = 12) -> str
```

Deterministic compact text, bounded size regardless of world size. Sections, in order:
`TICK`/`PANIC`, `POOLS` (one line), `BLOCKED` districts, `MISSIONS` — open missions as a
fixed-width table (id, kind, district, sev, lives, deadline_in, priority, staffing
"assigned/required" per resource) sorted by (priority desc, deadline asc, id) and capped
at `max_missions` with a `(+N more)` suffix; `YOUR INBOX` — proposals with sanitized
bodies/notes; `RULINGS` on your past proposals (sanitized reasons); `REJECTED LAST TICK`
— each with its reason, prefixed "do not repeat these"; allowed decision types last.

### contract.py — the shared output contract appended to every system prompt

```python
def decision_contract(allowed: tuple[str, ...],
                      decision_docs: dict[str, str],
                      proposal_docs: dict[str, str]) -> str
```

Renders: the exact output JSON schema (`{"decisions": [...], "proposals": [...],
"responses": [...]}` with field names matching parse.py), one usage line per allowed
decision type (from `decision_docs`), one per proposal kind (from `proposal_docs`), and
the hard rules: output ONLY a JSON object; use exact ids exactly as they appear in the
observation (mission ids like "m3", resource names, proposal ids) and never invent ids;
answer every proposal in YOUR INBOX via "responses"; resources are granted only through
resource_request proposals, not dispatch decisions; keep each rationale under 25 words.
Must contain the word "JSON" (DashScope json_mode requirement) — pinned by a test.

### agent.py

```python
class LLMAgent(Agent):
    def __init__(self, agent_id: str, role: RoleSpec, provider: Provider, contract: str)
    async def act(self, observation: Observation) -> AgentResponse
```

- `system = role.system_prompt + "\n\n" + contract`; `user = render_observation(obs)`;
  `model = role.model`, `temperature = role.temperature`, json_mode on.
- Maps `LLMOutput` into protocol types, assigning ids `f"{agent_id}-t{tick}-{i}"`
  (decisions) / `f"{agent_id}-t{tick}-p{i}"` (proposals) and forcing
  `agent_id`/`sender`/`responder` to itself. Response entries whose `proposal_id` is not
  in the observation inbox are dropped.
- Provider or parse failure ⇒ `AgentResponse(error=<short reason>)`, with usage attached
  when the call succeeded but parsing failed. Never raises.

### Town wiring

- `town/prompts.py`: `DECISION_DOCS` / `PROPOSAL_DOCS` dicts (one usage line each, e.g.
  `"set_priority": "set_priority {mission_id, priority 0-10}: rank a mission for the
  resource auction"`), plus `build_llm_agents(roles, provider) -> dict[str, Agent]`.
- Role YAMLs gain `system_prompt` (concise role briefs: who you are, your objective,
  your lane, when to escalate), `model` (`qwen3.5-plus` for commander, `qwen3.5-flash`
  for the five others), `temperature: 0.3`.
- CLI: `--arm society` builds LLM agents (friendly fail-fast if `DASHSCOPE_API_KEY` is
  unset); `--timeout` flag for agent_timeout_s (default 5.0 scripted, 45.0 society);
  new `aftershock smoke-llm [--model qwen3.5-flash]` makes one tiny JSON-mode call and
  prints the reply, token counts, and cost — the first thing to run when credits land.

## The benchmark (`src/aftershock/town/arms.py`, `src/aftershock/bench.py`)

The central claim of this project is measured, not asserted: on identical seeded scenarios,
does a structured society of cheap models beat (a) one flagship model doing everything and
(b) the same cheap models without a coordination protocol? Four arms, same worlds:

| arm | agents | model(s) | coordination |
|---|---|---|---|
| `scripted` | 6 heuristics | none ($0) | auction protocol |
| `solo` | 1 generalist | qwen3-max | none — single agent holds every capability |
| `swarm` | 5 specialists | qwen3.5-flash | none — direct dispatch, no proposals, no commander |
| `society` | 6 roles | qwen3.5-flash ×5 + qwen3.5-plus commander | full negotiation protocol |

Fairness rules: every arm runs the same seeds (identical worlds/timelines); cost and tokens
are recorded identically through the one provider chokepoint; the swarm is NOT handicapped —
it may dispatch directly (no auction round-trip), so a society win is attributable to
coordination, not crippled baselines; per-call timeouts may differ per arm (infrastructure,
not capability).

### town/arms.py

```python
ARMS = ("scripted", "solo", "swarm", "society")

@dataclass
class ArmSetup:
    world: TownState; society: TownSociety; agents: dict[str, Agent]
    registry: DecisionRegistry; roles: dict[str, RoleSpec]; resolver: Resolver
    default_timeout_s: float

def build_arm(arm: str, seed: int, provider: Provider | None) -> ArmSetup
    # scripted: existing six heuristics + TownResolver; provider unused; timeout 5.0
    # society:  existing six LLMAgents + TownResolver; timeout 45.0
    # swarm:    five LLMAgents (medical, rescue, fire, infrastructure, comms) from
    #           town/roles_swarm/*.yaml; DefaultResolver; timeout 45.0
    # solo:     one LLMAgent "solo" from town/roles_solo/solo.yaml; DefaultResolver;
    #           timeout 90.0 (flagship latency)
    # LLM arms with provider=None -> ValueError (CLI converts to the friendly exit-2 hint)
```

- `town/roles_swarm/`: five YAMLs, `model: qwen3.5-flash`, envelopes INCLUDE `dispatch`
  (+ recall; repair_road for infrastructure; broadcast for comms). Prompts: act directly
  on the world, no negotiation exists, watch pool availability — if the pool lacks units
  the decision is rejected with a reason. No mention of proposals.
- `town/roles_solo/solo.yaml`: `model: qwen3-max`, all five decision types allowed,
  prompt = a complete one-person incident-command brief (triage, dispatch, repair,
  public comms).
- `TownSociety` accepts an explicit roster (`agent_ids`/`role_of` driven by the roles
  mapping passed in) so the same society logic serves all rosters.
- `decision_contract` renders a decisions-only contract when `proposal_docs` is empty
  (schema shows `{"decisions": [...]}` only, plus a "do not emit proposals" rule).
  `town/prompts.py` gains `DECISION_DOCS_DIRECT` (dispatch documented as directly
  usable) for swarm/solo, alongside the auction-framed `DECISION_DOCS` for society.
- `cli.py run --arm` accepts all four arms and delegates wiring to `build_arm`.

### bench.py

Manifest-driven (default `bench/default.yaml`):

```yaml
ticks: 60
seeds: [11, 23, 37, 42, 57]
arms: [scripted, solo, swarm, society]
out: runs/bench
```

```python
def run_bench(manifest: dict, provider: Provider | None,
              out_dir: Path) -> BenchResult
    # Runs each (arm, seed) cell sequentially via build_arm + Engine.
    # Resume: a cell whose <out>/<arm>-seed<seed>/summary.json exists is skipped
    # (deleted dir = rerun); each cell writes its full NDJSON run dir + summary.json
    # {arm, seed, ticks_run, scores, cost, wall_s, models}.
def aggregate(cells: list[dict]) -> dict
    # per-arm: n, mean & sample-sd of lives_saved, lives_lost, missions_resolved,
    # missions_failed, cost_usd, wall_s; lives_per_dollar = mean_lives/mean_cost
    # (omit for zero-cost arms); plus the per-seed paired table arm x seed -> lives_saved.
def render_markdown(agg: dict) -> str   # RESULTS.md: headline table + paired table
```

CLI: `aftershock bench [--manifest PATH] [--arms a,b] [--seeds 1,2] [--ticks N]
[--out DIR] [--fresh]` — flags override the manifest; prints the markdown tables and
writes `results.json` + `RESULTS.md` to the out dir. LLM arms requested without
`DASHSCOPE_API_KEY` ⇒ the friendly exit-2 hint before any cell runs.

### Engine: rejection memory

`Engine(..., rejection_memory_ticks: int = 3)` — `Observation.rejections` carries the
agent's rejections from the last N ticks (most recent first, capped at 12 entries)
instead of only the previous tick, so small models stop re-attempting refused actions.
Applies to every arm identically.

## The observatory (`src/aftershock/web.py`, `src/aftershock/mcp_server.py`, `web/`)

The visual layer: a FastAPI server that replays recorded runs and streams live ones, a
React map UI, and an MCP spectator. The same server is the Alibaba Cloud deployment
artifact.

### Kernel plumbing (additive, determinism-preserving)

- `Engine(..., tick_listener: Callable[[TickRecord], None] | None = None)` — called after
  each tick is recorded; listener exceptions are swallowed (never kill the tick).
- `Recorder` writes a second sidecar `world.ndjson` — one canonical-JSON line
  `{"tick": N, "state": <society.world_state(world)>}` per tick. The engine already
  computes that dict for the world digest; pass it through, do not recompute.
  `load_run` returns it when present: `(manifest, ticks, worlds | None)`.
- `TownSociety.inject_event(kind, district_id) -> str` queues an external event
  (`fire | aftershock | road_block`); the queue is drained at the start of the timeline
  step in `scheduled_events`, spawning the corresponding mission/blockage with normal
  WorldEvents (kind `injected` in the payload provenance). Injections are recorded in
  the tick's events, so replays of live runs remain faithful.

### web.py

```python
def create_app(runs_root: Path, bench_root: Path | None = None) -> FastAPI
```

- `GET /api/runs` → `[{run_id, seed, arm, ticks, final_scores, cost}]` (scans runs_root,
  newest first). **run_id values are validated** (`^[A-Za-z0-9._-]+$`, no path
  separators) everywhere they appear in a path — path traversal must be impossible.
- `GET /api/runs/{run_id}` → manifest + final scores + n_ticks + has_world.
- `GET /api/runs/{run_id}/ticks?start=0&limit=50` → `{ticks: [...], worlds: [...] | null,
  total}` (paged, limit ≤ 200; tick records zipped with world states when present).
- `GET /api/bench` → parsed `results.json` files under bench_root (default
  `bench/results/`), newest first.
- `POST /api/live {arm, seed, ticks}` → `{live_id}`; runs the arm in an asyncio task.
  One live run at a time (409 if busy); `ticks ≤ 120`; LLM arms without
  `DASHSCOPE_API_KEY` → 503 with the friendly hint. The live run also writes a normal
  run dir under runs_root (so it becomes replayable).
- `WS /ws/live` → streams `{"type": "tick", "record": ..., "world": ...}` per tick, then
  `{"type": "done", "summary": ...}`; on connect mid-run, sends all buffered ticks first.
- `POST /api/live/inject {kind, district}` → 200; 404 when no live run; 422 on bad kind.
- `GET /api/live` → `{running, live_id, tick, arm, seed}`.
- Static: serve `web/dist` at `/` when it exists; otherwise `/` returns
  `{"hint": "run npm install && npm run build in web/"}`.

### mcp_server.py — the spectator

FastMCP (`mcp` SDK), stdio transport, name `aftershock`. Read-only over runs_root plus
one action that proxies to a locally running server:

- `list_runs()`, `run_summary(run_id)`, `get_ticks(run_id, start, limit ≤ 20)`
- `negotiation_feed(run_id, start=0, limit=30)` — flattened proposals/rulings with
  human-readable lines ("medical requested 2 ambulance for m3 — DECLINED: pool
  exhausted, granted to m2")
- `agent_story(run_id, agent_id)` — that agent's decisions, rationales, rejections, and
  proposal outcomes across the whole run
- `bench_results()` — parsed benchmark tables
- `inject_event(kind, district)` — POSTs to `http://127.0.0.1:8788/api/live/inject`;
  returns a clear error string when no live server/run exists
Same run_id validation as web.py.

### web/ — the map UI (Vite + React 18 + TS + Tailwind, no router)

Single-page observatory with a header scoreboard and three tabs:

1. **Map** (the star): SVG town — six fixed district blocks (old_town, harbor,
   hospital_district, market, residential_north, industrial), mission markers by kind
   with severity-scaled emphasis and a lives-at-risk countdown, staffing pips
   (assigned/required), blocked-road indicators, pending arrivals, a panic gauge, and a
   resource-pool sidebar. Right rail: the negotiation feed (grants green, pool-exhausted
   declines red with the winner named) and an agent inspector (click an agent chip →
   its decisions + rationales + rejections this tick).
2. **Bench**: bar chart (lives saved mean ± sd per arm) + cost/lives-per-$ table from
   `/api/bench`, with the honest-caveat footnote rendered from the data.
3. **Live**: start a run (arm/seed/ticks), follow via WS (auto-scrub to newest), and
   inject events (kind + district picker) — disabled states when the server lacks a key.

Replay transport: `/api/runs` picker + paged ticks; a scrubber (slider + play/pause +
speed) drives a cursor over the loaded timeline; all derived map state comes from
`worlds[cursor]` (no event-folding on the client). Runs without world data fall back to
feeds-only with a notice.

Aesthetic direction: emergency-operations-center — near-black slate, amber/signal-red
accents, phosphor-green for grants, monospaced numerals, restrained glow on active
missions; distinctive and calm, not a generic dashboard. Vite dev proxies `/api` and
`/ws` to `127.0.0.1:8788`. `npm run build` and `npx tsc --noEmit` must pass; a handful
of vitest specs cover the timeline reducer/selectors. `web/node_modules` and `web/dist`
are gitignored.

## CLI

```
aftershock run    --seed 42 --ticks 60 --arm scripted|solo|swarm|society [--out runs]
                  [--quiet] [--timeout S]
aftershock bench  [--manifest bench/default.yaml] [--arms ...] [--seeds ...] [--ticks N]
                  [--out DIR] [--fresh]
aftershock serve  [--runs-dir runs] [--host 127.0.0.1] [--port 8788]
aftershock mcp    [--runs-dir runs]              # stdio MCP spectator
aftershock verify --seed 42 --ticks 60     # run twice, assert identical digest sequences
aftershock replay <run_dir>                # print scoreboard timeline from NDJSON
aftershock smoke-llm [--model qwen3.5-flash]   # one live call: reply, tokens, cost
```

`run` prints a one-line-per-tick summary and a final scoreboard (lives saved/lost,
missions, panic, cost). Exit code 1 on `verify` mismatch.

## Testing

`uv run pytest` must pass; `uv run ruff check .` must be clean. Key suites: protocol
snapshot (exists), rng stability (pin 2-3 derived values), recorder round-trip, registry
validation/rejection reasons, role loading, negotiation routing (bilateral accept/decline/
expiry, broadcast, identity spoofing), engine isolation (an agent that raises or hangs
doesn't kill the tick; rejected decisions appear in the next observation), town mechanics
(auction contention: the loser's ruling names the winner; road-block delay; mission
lifecycle), and end-to-end determinism (same seed twice ⇒ identical world-digest
sequences; different seeds differ; scripted arm saves > 0 lives).
