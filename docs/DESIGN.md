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

## Demo polish + compare mode (task #3 — `web/` evolution)

Refines the observatory for the submission video. **Pure `web/` work; zero engine or API
change** — determinism and every backend contract above are untouched (compare mode is
built entirely from data already served by `/api/runs/{id}/ticks`). Provenance: a Codex
(architecture) + Gemini (visual) review, synthesized in the CCG assessment. Governing
principle: the EOC concept stays; the *execution* moves from "AI UI-kit" to "mission-control
tool" without inventing a new aesthetic. Non-negotiable invariant from the UI spec above is
preserved: **all derived map state still comes from `worlds[cursor]` — no event-folding on
the client**, applied per-side in compare mode.

Decomposed into surfaces with **disjoint file ownership** for parallel execution. Phase A is
a serial foundation (it touches shared config); Phases B–F fan out; one integration seam
(`App.tsx`) is owned by the integration pass.

| Surface | Phase | Owns (exclusive write) | Exports / seam |
|---|---|---|---|
| **A · Tokens** | A (serial, first) | `tailwind.config.js`, `src/index.css`, `src/lib/palette.ts` (NEW) | semantic classes + `palette.ts` |
| **B · Compare core** | B | `src/components/CompareTab.tsx` (NEW), `src/lib/compare.ts` (NEW), `src/lib/usePlaybackClock.ts` (NEW) | `<CompareTab/>` |
| **C · Timeline helpers** | B | `src/lib/timeline.ts` (**additive only**), `src/lib/__tests__/compare.test.ts` (NEW) | `indexForTick`, `maxComparableTick`, `selectRunningCost` |
| **D · Scrubber** | B | `src/components/Scrubber.tsx` | event-marker props (additive, optional) |
| **E · Map richness** | B | `src/components/TownMap.tsx`, `src/components/MapTab.tsx` | mission popover, inject-pulse, `effects` prop |
| **F · Legend** | B | `src/components/Legend.tsx` (NEW) | `<Legend/>` |
| **Integration** | C | `src/App.tsx`, `src/lib/deeplink.ts` (NEW), 4th nav tab | wires B/D/E/F + URL; final density sweep |

### A — Design tokens (the foundation)

Today the palette is defined **three times**: `:root` vars in `index.css`, duplicated in
`tailwind.config.js`, then re-hardcoded as `bg-[#0a0e1a]` / `border-[#243047]` literals across
14 components. Collapse to one source:

- `index.css` keeps `:root` vars but as space-separated RGB channels
  (`--eoc-ground: 10 14 26;`) so Tailwind can apply `<alpha-value>`.
- `tailwind.config.js` maps semantic names onto them:
  `eoc.{ground,surface,raised,border}`, `signal.{amber,red,green,cyan}`,
  `text-eoc-{primary,secondary,dim}`.
- `src/lib/palette.ts` (NEW) — the single JS/SVG color source (mission-kind, status, and
  **arm** colors) so `TownMap`/`BenchTab`/`RunPicker`/`LiveTab`/`AgentInspector` stop
  redefining them. **Arm coding fixed here and used everywhere: `society = cyan`, the
  comparison baseline (swarm/solo) `= amber`** — drives compare mode's "good vs baseline".

DoD: `grep -rE '#[0-9a-fA-F]{6}' src --include='*.tsx'` returns nothing (all hex lives in
`palette.ts`).

### A — Type, density & effects style contract (applied within each surface's owned files)

Not a separate pass (would collide with every surface) — a **style contract** every executor
honours in the files it owns; integration sweeps stragglers.

- **Text floor for video (1080p capture):** DOM body/controls → `text-xs` (12px); labels →
  `text-[11px]`; metadata chips → `text-[10px]` floor; **delete every `text-[8px]`** (e.g. the
  `LiveTab` memory badge). 9px stays **only inside SVG** (`<text>` in `TownMap`).
- **Hierarchy by weight, not shouting:** values are heavier/larger than their labels
  (`text-sm font-semibold` value over a dim `text-[11px]` label). **Stop UPPERCASE +
  `tracking-widest` on body and values** — reserve it for section headers and the logo only.
- **Effects restraint:** `glow-*` and `animate-ping` only on **active/hovered** elements;
  scanlines on the **map surface only**, never the rails. `TownMap` and mission markers take
  an `effects: 'normal' | 'quiet'` prop; compare mode passes `quiet`.
- **Contrast:** promote "dim" text from `#475569` → `text-eoc-secondary` (`#94a3b8`); the old
  dim turns to mud under video compression.

### B/C — Compare mode (the centerpiece)

Side-by-side synced replay of two arms on the **same seed**. A 4th nav tab `COMPARE`
(so the video has a clean shot and a stable deep link).

- **State:** two independent `timelineReducer` instances (do **not** generalise the single-run
  reducer) + one shared compare controller `{leftRunId, rightRunId, cursorTick, playing, speed}`.
- **Shared *logical tick*, not array index** — arms differ in `total`/length. Additive
  selectors in `timeline.ts` (surface C):
  ```ts
  indexForTick(ticks, tick)        // exact match, else last record with t.tick <= tick
  maxComparableTick(a, b)          // min(last tick of each side)
  selectRunningCost(ticks, cursor) // Σ ticks[≤cursor].responses[].usage?.cost_usd ?? 0
  ```
  On every shared-cursor change, mirror into both: `dispatch{Left,Right}(SET_CURSOR,
  indexForTick(side.ticks, cursorTick))`.
- **One clock:** extract `usePlaybackClock(playing, speed, onTick)` (surface B); both the
  single-map `MapTab` timer and compare use it — **never two intervals**.
- **Delta strip** (top-center, the hero readout): `Δ lives saved`, `Δ lost`, `Δ panic`,
  `Δ open/resolved`, `Δ cost` — each `left − right`, large, colored by the winner; a single
  big **LIVES-SAVED** pair is the dominant element. Lives/panic from `worlds[idx]`; cost from
  `selectRunningCost`.
- **Differing lengths:** play stops at `maxComparableTick`; the shorter side **holds its final
  frame** (greyed "FINAL" chip) while the longer finishes. If a side is under-paged, pause and
  auto-load its next page (page size 100 for compare to avoid mid-run stalls).
- **Guard:** if either side `has_world === false`, refuse compare with a clear notice (two-map
  replay is only meaningful with world data).
- Compact run headers per side: `SOCIETY · seed 42 · T31` / `SWARM · seed 42 · T31`.

### Integration — Deep links (no router; History API only)

Wired in `App.tsx` via `src/lib/deeplink.ts` (NEW):

- `?run=<run_id>&t=<tick>` — select run, page until that logical tick is loaded, set cursor.
- `?compare=<arm|run_id>,<arm|run_id>&seed=<n>&t=<tick>` — resolve both (by arm+seed, or
  exact run_ids), load both, set `cursorTick`.
- Parse **after** `api.runs()` resolves. Reflect scrub/playback with **`history.replaceState`,
  throttled** (≥250ms) so 8× playback doesn't spam history. Must **preserve existing non-secret
  params** after the existing `token` scrub in `api.ts`.

### E/D/F — Richness (each small, independent)

- **Scrubber event markers** (D): colored ticks on the timeline from `TickRecord.events`
  (spawn/inject) + mission status transitions between adjacent `worlds` (resolve/fail);
  click → jump cursor.
- **Mission popover** (E): click a `TownMap` marker → required vs assigned, deadline,
  priority, requester (from `MissionState`).
- **Inject pulse** (E): highlight the injected district for ~2s when a tick's `events` contains
  an `injected`-provenance event.
- **Legend overlay** (F): dismissible map legend (mission kinds, status colors, arm coding);
  suppressed thereafter via `localStorage`. **No fake "booting…" animation** — it's the exact
  gimmick this pass removes.

### Performance

Two SVG maps are cheap (6 districts, few markers); the cost at 8× is React re-rendering both
every 125ms. `React.memo(TownMap)`, `useMemo` mission positions on `[world.missions]`,
`effects='quiet'` in compare, throttled URL writes.

### Definition of done

`npm run build` and `npx tsc --noEmit` clean; existing vitest specs green **plus** new
`compare.test.ts` (indexForTick/maxComparableTick/selectRunningCost across mismatched
lengths). No `#rrggbb` literals outside `palette.ts`. Single-run Map/Bench/Live behaviour
unchanged (compare is additive). Backend, determinism, and the `OBSERVATORY_TOKEN`/CORS
behaviour untouched. **Deferred (explicit non-goals for the video):** full sans-serif font
migration, mission-marker redesign, design-system migration of every last component.

## Real-data scenario packs (task #4 — engine/data + observatory)

Run the existing agent society on scenarios compiled from **real open incident data**, with
real response latency as the on-screen baseline. Distinct from task #3 (arm-vs-arm compare,
same synthetic seed, `8047d54`): this is **sim-vs-reality** — real demand arrival, real
first-on-scene times, simulated outcomes. Research provenance: 14 datasets adversarially
verified 2026-06-11 (live API fetches, exact row counts) in
`.omc/research/open-datasets-compare-mode.md`. Folded here from `docs/SCENARIOS.md` (deleted
in the same commit — one spec copy at all times).

### UX contract (CCG tri-model review, 2026-06-11 — authoritative for Phase S4)

A Claude–Codex–Gemini UX review approved the spec and pinned 8 deltas; the surface table below
already encodes them. The principle: **credibility through transparency, not complexity through
labels.**

1. **District-name override is P0 and swaps immediately** — showing "OLD TOWN" during a real-NYC
   demo breaks credibility in 3 seconds.
2. **RealityStrip is scenario-level, never arm-level.** MapTab: one strip as a map *footer above
   the Scrubber*. CompareTab: **one shared band under the existing `DeltaStripView`** comparing
   *both* arms' sim latency against the *single* real baseline — **not** per-`SidePanel` (that
   double-renders the same grey number and implies two realities). Render only when both arms
   share the scenario; suppress otherwise.
3. **Honesty is always-visible, not click-only.** Always shown: the per-pack caveat line + a tiny
   inline provenance summary (`REAL demand · REAL latency · INFERRED lives`). The full
   source/license/mapping table + 4-badge grid live behind the `DATA` chip (deep dive only).
4. **Short caveat copy.** RealityStrip sub-caption is **"Same real demand; simulated dispatch &
   travel differ."** (replaces the 83-char "directionally comparable…" line, which judges won't
   read). The per-pack Invariant-4 caveat lines are unchanged (they are the data contract).
5. **Two badge tiers, neutral colors.** Solid fill = `REAL` (ground truth); ghost/dotted border =
   `MAPPED/INFERRED/SYNTHETIC`. `INFERRED` is a border-only ghost badge so it never reads as an
   *error*. Mono 9px. Provenance badges stay **out of the arm-color space** — amber already = the
   baseline arm and cyan = society; reusing them would collide on the very RealityStrip that pairs
   grey-real vs arm-color-agent. The hazard chip alone carries a signal accent (REAL) vs dim (SYN).
6. **Scenario select auto-prefills ticks and de-emphasizes the ticks input** — a presenter never
   reasons about tick counts mid-demo.
7. **Hazard chips dim in RunPicker rows, stronger only in the selected-run / header context** —
   no equal-weight stamping of every row.
8. **Mission-popover real-vs-agent latency lines are KEPT** (operator decision, against the
   reviewers' "defer" suggestion) — built with care for the popover's already-dense small SVG text
   (`TownMap.tsx` `MissionPopover`): the two lines + INFERRED ghost-badge must stay legible at
   1080p capture, so the popover height math must grow and the lines use the same 9px mono.

### Invariants (non-negotiable)

1. **No engine vocabulary change.** `MissionKind`, `ResourceKind`, district ids, dynamics,
   scoring are untouched. Real incident types map onto the existing four mission kinds *in the
   compiler*, and the mapping is published as provenance. (All-hazards vocabulary refactor is
   deferred — see "Deferred".)
2. **Determinism preserved.** The compiler runs **offline** and emits a versioned JSON artifact
   committed to the repo. The engine never touches the network. Same pack + same seed + same
   decisions = same outcome, byte for byte. `aftershock verify` must pass with `--scenario`.
3. **Bench fairness.** Scenario packs are demo/observatory surfaces only. `aftershock bench` and
   `bench/default.yaml` refuse scenario packs; the published 4-arm results stay synthetic-seed
   only. (Same spirit as the lessons-only-for-society guard in `build_arm`.)
4. **Honesty labels are part of the contract, not polish.** Every scenario surface carries the
   field-provenance markers (REAL / MAPPED / INFERRED / SYNTHETIC) and a caveat line drawn from a
   fixed approved set, **chosen per pack so it never claims a category the pack's
   `field_provenance` does not support**:
   - dispatch packs (SF, NYC): *"Demand: real · Latency baseline: real · Lives & outcomes:
     simulated model."*
   - hazard-only packs (Türkiye): *"Hazard timing: real · Demand & outcomes: simulated model."*
   Never claim agents are compared against real responders' *outcomes*.
5. **Sequencing.** Phase-S4 gate is satisfied by `8047d54` — S1–S6 are parallel-startable. S1–S3
   touch only Python/`Dockerfile`/`scenarios/`; S4 touches `web/src/**` per the surface table.

### The scenario pack (`scenarios/<id>/scenario.json`)

One self-contained JSON artifact per scenario, validated by pydantic models in
`town/scenario.py`. Canonical example (`nyc-ida-2021`, abridged where marked):

```jsonc
{
  "format_version": 1,
  "id": "nyc-ida-2021",                      // ^[a-z0-9][a-z0-9-]*$, dir name == id
  "name": "Hurricane Ida — NYC, night of 2021-09-01",
  "hazard": "hurricane_flood",               // free label: earthquake|hurricane_flood|storm|routine
  "adapter": "nyc",                          // which compiler adapter produced this pack
  "compiler_version": "<git rev of the compiler at emit time>",
  "config_sha256": "<sha256 of the adapter config YAML>",
  "tick_minutes": 12,                        // real minutes per tick (display + reference math)
  "window": { "start": "2021-09-01T18:00:00-04:00", "end": "2021-09-02T06:00:00-04:00" },

  // Canonical district ids are POSITIONAL SLOTS — the SVG map layout keys off them.
  // Packs override display names; `members` documents the real zoning.
  "districts": [
    { "id": "old_town",          "name": "Manhattan",      "members": ["M1", "M2"] },
    { "id": "harbor",            "name": "Staten Island",  "members": ["S1", "S2"] },
    { "id": "hospital_district", "name": "Bronx",          "members": ["B1", "B2"] },
    { "id": "market",            "name": "Brooklyn West",  "members": ["K1", "K2"] },
    { "id": "residential_north", "name": "Queens",         "members": ["Q1", "Q2"] },
    { "id": "industrial",        "name": "Brooklyn East",  "members": ["K3", "K4"] }
  ],

  "pools": {                                  // feeds ResourcePool(kind, total, available)
    "ambulance":   { "size": 4, "basis": "calibrated", "note": "no EMS unit counts in 76xm-jjuj; calibrated against held_indicator saturation" },
    "rescue_crew": { "size": 3, "basis": "calibrated", "note": "no real analog; synthetic default" },
    "fire_engine": { "size": 3, "basis": "observed",   "note": "engines_assigned p75 in window (8m42-w767)" },
    "repair_crew": { "size": 3, "basis": "calibrated", "note": "no real analog" },
    "supply_truck":{ "size": 3, "basis": "calibrated", "note": "no real analog" }
  },

  "timeline": [                               // exact TimelineEntry shape, sorted by tick
    // tick = floor((received − window.start) / tick_minutes): 21:04:11 → tick 15
    { "tick": 15, "kind": "mission", "mission_kind": "medical_surge",
      "district_id": "residential_north", "severity": 4, "lives_at_risk": 16 },
    { "tick": 17, "kind": "blockage", "district_id": "residential_north" }
  ],

  "field_provenance": {                       // drives the REAL/MAPPED/INFERRED/SYNTHETIC badges
    "tick": "real", "district_id": "real", "mission_kind": "mapped",
    "severity": "mapped", "lives_at_risk": "inferred", "blockage": "synthetic"
  },

  "mapping": {                                // the semantic decisions, published verbatim
    "version": "nyc-v1",
    "mission_kind": { "EMS severity 1-3 medical": "medical_surge",
                      "Fire incident_classification Structural Fires": "fire",
                      "NonStructural/utility": "infra_repair",
                      "rescue classifications + water rescue": "collapse_rescue" },
    "severity_rule": "EMS code 1-2→5, 3→4 (codes 4-8 excluded by filter); Fire by units-assigned quantile",
    "lives_rule": "LIVES[kind][severity] lookup table vNYC-1 (inferred field)"
  },

  "sampling": {                               // no silent caps — say what was dropped
    "method": "stratified by (tick-bucket, mission_kind)",
    "sample_seed": 4636,                      // compiler-only RNG; recorded, not engine rng_for
    "kept": 16, "total": "<post-filter incident count, computed by the adapter>",
    "filter": "severity codes 1-3 OR Fire structural/rescue; boroughs only (CW/X1 dropped)"
  },

  "source": [                                 // one entry per upstream dataset
    { "dataset": "EMS Incident Dispatch Data", "provider": "FDNY via NYC Open Data",
      "dataset_id": "76xm-jjuj",
      "query_url": "https://data.cityofnewyork.us/resource/76xm-jjuj.json?$where=...",
      "fetched_at": "2026-06-11", "rows_fetched": 2003,
      "license": "NYC Open Data terms (no formal license)", "license_url": "https://opendata.cityofnewyork.us/overview/",
      "attribution": "FDNY via NYC Open Data" },
    { "dataset": "Fire Incident Dispatch Data", "provider": "FDNY via NYC Open Data",
      "dataset_id": "8m42-w767",
      "query_url": "https://data.cityofnewyork.us/resource/8m42-w767.json?$where=...",
      "fetched_at": "2026-06-11", "rows_fetched": 2022,
      "license": "NYC Open Data terms (no formal license)", "license_url": "https://opendata.cityofnewyork.us/overview/",
      "attribution": "FDNY via NYC Open Data" }
  ],

  "reference": {                              // the reality baseline (only what the data proves)
    "missions": {                             // keyed by TIMELINE INDEX of the mission entry
      "0": { "received": "2021-09-01T21:04:11-04:00",
             "first_on_scene": "2021-09-01T21:19:53-04:00",
             "latency_s": 942 }               // null first_on_scene/latency when no unit arrived
    },
    "aggregates": {                           // computed over the FULL filtered window, not sample
      "mean_latency_s": 948,                  // mean AND median both emitted (Ida figures are MEANS)
      "median_latency_s": "<computed>",
      "held_rate": 0.165,
      "baseline_mean_latency_s": "<computed>", "baseline_median_latency_s": "<computed>",
      "baseline_held_rate": "<computed>",
      "baseline_note": "<adapter-computed calm window, stated explicitly, e.g. 2021-08-18/19>"
      // 538 s / 6.9 % normal-period figures are the 2012-10-15/16 pre-Sandy baseline — the NYC
      // adapter must compute an Ida-adjacent baseline rather than reuse them, and name the window.
    }
  }
}
```

**Index ↔ mission id.** Engine mission ids (`m1..`) come from a single shared counter, and live
injections consume it *before* that tick's timeline spawns (`town/events.py:217` drains
injections first; ids at `events.py:244`/`:288`). Timeline index → mission id is **not**
reconstructible by counting. The UI maps them by walking `mission_spawned` events in record order
and **skipping events whose payload has `injected: true`** (`events.py:274`); the nth non-injected
spawn is the nth mission entry in `timeline`. Injection-safe; normative for `reference.missions`.

Loader validation (pydantic, hard errors): district ids exactly the canonical six; pool kinds
exactly the five `ResourceKind`s, sizes 1–12; mission kinds in `MissionKind`; severity 1–5;
`lives_at_risk` 1–64; timeline sorted by tick; **last mission tick + max(`DEADLINE_TICKS`) (= 16)
≤ 120** (engine loop `while tick < max_ticks`, `kernel/engine.py:127`, `_MAX_TICKS_LIVE = 120`);
reference mission keys must index mission entries. The pack's SHA-256 (`pack_digest`) is computed
at load and stamped into the run manifest.

### The compiler (`src/aftershock/data/` — NEW package)

Offline CLI pipeline, one adapter per upstream dataset. Never imported by the engine.

```
aftershock compile-scenario --adapter sf --config src/aftershock/data/configs/sf-routine.yaml \
    --out scenarios/sf-routine-2018
```

Stages (shared skeleton, per the verified research mappings):

1. **Extract** — adapter-specific fetch (SODA query, CSV slice) → raw rows cached to
   `scenarios/<id>/raw/` (gitignored — add `scenarios/*/raw/` to `.gitignore`; for AFAD this is
   also a license requirement). Fetch metadata (`fetched_at`, `rows_fetched`, `query_url`) is
   recorded **once, at extract time**, into `raw/manifest.json`; Emit copies it verbatim. Tests
   use small committed fixture slices under `tests/fixtures/data/` — **tests never touch network**.
2. **Aggregate** — group unit rows to incidents; compute per-incident `received`,
   `first_on_scene = MIN(on_scene over units, nulls dropped)`, unit roster, zone, type, priority.
   Adapter gotchas live here and are unit-tested (SF: drop battalion junk B99/AMB/XXX, use
   `original_priority` not `final_priority`; NYC: filter by `valid_*_indc`, never use Fire
   `highest_alarm_level`).
3. **Discretize** — windows ÷ `tick_minutes` → ticks; zone→district lookup from config; type→kind
   mapping; severity rule; `LIVES[kind][severity]` lookup; blockage synthesis rule (or none);
   **deterministic stratified sampling** to `target_missions` (default 16) via
   `random.Random(sample_seed)` — compiler-only randomness, recorded in the pack. Pools from
   observed unit roster scaled by sampling ratio, clamped [2, 6], each marked
   `observed`/`calibrated` (`observed` only where the dataset actually counts units). Reference
   aggregates (mean **and** median, plus the named baseline window) over the **full filtered
   window**, not the sample.
4. **Emit** — `scenario.json` with sorted keys, stamped `adapter`/`compiler_version`/
   `config_sha256`, plus a per-pack human `README.md` (source, license, attribution, caveat line).

**Byte-identity scope:** recompiling from identical `raw/` + identical config hash is
byte-identical (golden test). Re-*fetching* is never byte-stable (SF refreshes daily, NYC
~quarterly) — which is why fetch metadata is frozen at extract time.

Sampling rationale: a real 12 h city window is 300–2,000 incidents; the society + pool model is
tuned for ~10–20 missions. Downscaling is stratified (preserves arrival-time distribution and kind
mix), seeded, and published (`kept`/`total`) rather than silent.

### Engine integration (single touchpoint)

- **`town/scenario.py` (NEW):** pydantic models + `load_scenario(path) -> ScenarioPack` +
  `town_from_scenario(pack, seed) -> TownState` (districts with display names from the pack, pools
  from the pack, timeline verbatim, counters zeroed). `state.py` is not modified.
- **`town/arms.py`:** `build_arm(arm, seed, provider, lessons=None, scenario: ScenarioPack | None
  = None)`; `world = town_from_scenario(scenario, seed) if scenario else new_town(seed)`
  (`town/arms.py:101`). `seed` keeps its meaning for every other `rng_for` stream and replay.
- **`cli.py`:** `aftershock run --scenario <id>` (resolves `scenarios/<id>/scenario.json`); with
  `--scenario`, `--ticks` defaults to `min(last timeline tick + 20, 120)` — an explicit
  under-budget `--ticks` is a hard error, not silent truncation. Same for `aftershock verify
  --scenario <id>` (two-run digest check). `bench` rejects `--scenario` (invariant 3).
- **Run manifest** (`run.json`) gains `"scenario": {id, name, hazard, tick_minutes, pack_digest,
  config_sha256, source, field_provenance, caveat_line, reference_aggregates}` — enough for the UI
  to render provenance without a second fetch. Absent for synthetic runs (UI treats absence as
  `SYN·QUAKE`).

Mission deadlines remain the `DEADLINE_TICKS` model constants — part of the outcome model, not the
data (at 12 min/tick, medical_surge's 8-tick deadline = 96 min, defensible). Live injection
(`/api/live/inject`) keeps working in scenario runs; injected events carry `injected: true`, and
the index↔id mapping above is injection-safe.

### Web API (`web.py` — additive)

- **`GET /api/scenarios`** — scans `scenarios/` (ids validated against `^[a-z0-9][a-z0-9-]*$`, same
  traversal-guard pattern as `_validate_run_id`), returns `[{id, name, hazard, tick_minutes,
  window, missions, sampling: {kept, total}, source: [{dataset, provider, license, attribution}]}]`.
  **Deliberately ungated** like every existing GET — only POST endpoints are token-gated.
- **`GET /api/scenarios/{id}`** — full pack including `reference` (the RealityStrip data source).
- **`POST /api/live`** — `LiveRunRequest` gains `scenario: str | None = None`, and `ticks` changes
  to `int | None = None` so the server distinguishes "omitted" (default 30 synthetic, `min(last
  timeline tick + 20, 120)` for scenario) from explicit 30. Unknown scenario id → 404. Pack loads
  server-side, passes to `build_arm`. Token gate unchanged. Manifest gains the scenario block.
- **`GET /api/runs`** — `_scan_runs` passes through compact `scenario: {id, name, hazard} | null`;
  `GET /api/runs/{id}` returns the full block.
- **Deployment:** `scenarios/` is committed and `COPY`d in the Dockerfile; no runtime network/env.

### Web UI (Phase S4 — surface table, UX-contract-applied)

Honors the task #3 style contract (text floor, hierarchy by weight, effects restraint) and its
token system; all colors via `palette.ts`. This table is the authoritative ownership map and
already folds in the 8 UX deltas above.

| Surface | Owns | What it does |
|---|---|---|
| **Trigger** | `LiveTab.tsx` (+`api.ts` additive) | SCENARIO select **above** the arm/seed/ticks controls: `SYNTHETIC QUAKE (seed N)` default + one entry per `/api/scenarios` (`IDA · NYC 2021 · 16 missions`). Selecting a real pack **auto-prefills ticks and visually de-emphasizes the ticks input** (delta 6). Seed still seeds the agents. POST includes `scenario`. Token flow unchanged. |
| **Badges** | `RunPicker.tsx`, `palette.ts` (additive), `types.ts`, `CompareTab.tsx` (additive) | Hazard chip: **dim in RunPicker rows**, **stronger in the run/side header** (delta 7). `SYN·QUAKE` (dim) vs `REAL·IDA NYC` (signal accent) from a new `palette.ts` hazard map. CompareTab renders its own per-side header inside `SidePanel` (`CompareTab.tsx:389`); add the chip there (or extract a shared `RunHeader` — implementer's choice). |
| **Provenance** | `ProvenancePanel.tsx` (NEW) | A `DATA` chip opens a **deep-dive** panel: source table (dataset · provider · license · fetched_at · query URL, monospaced, copyable), mapping version + rules verbatim, `config_sha256` + `compiler_version`, sampling line ("16 of N incidents, stratified, seed 4636"), and the field-provenance grid. **Badge tiers (delta 5): solid fill = REAL, ghost/dotted border = MAPPED/INFERRED/SYNTHETIC; neutral colors only (no amber/cyan).** Footer: attribution line(s) verbatim. The *summary* of honesty is NOT hidden here — see RealityStrip. |
| **Reality baseline** | `RealityStrip.tsx` (NEW) | **Scenario-level, one instance (delta 2).** MapTab: a **map footer pinned above the Scrubber**. CompareTab: **one shared band under `DeltaStripView`** comparing *both* arms' sim latency to the *single* real baseline — never per-`SidePanel`; render only when both sides share the scenario, else suppress. Content: REAL mean/median first-on-scene (grey, labeled **mean** or **median** to match the field) vs AGENTS mean **spawn→first-arrival** (`ticks × tick_minutes`, arm color) · held-rate pair where present · always-visible inline summary `REAL demand · REAL latency · INFERRED lives` + the pack caveat line (not dismissible) · sub-caption **"Same real demand; simulated dispatch & travel differ."** (delta 3, 4). Prefer a paired-bar chartlet (grey vs arm color) over raw numbers. |
| **Map names + popover** | `TownMap.tsx` (additive) | **P0 (delta 1):** district labels are hardcoded in `DISTRICT_LAYOUT` (`TownMap.tsx:26–32`, rendered `:396`); `world.districts[].name` reaches the frontend (`state.py:196`, `types.ts:5`) but the map ignores it. Change the label source to `world.districts[id]?.name ?? DISTRICT_LAYOUT[id].label` (geometry stays keyed by canonical id), so `nyc-ida-2021` renders "Manhattan" not "Old Town". **Mission popover (delta 8, KEPT):** two scenario lines `first on scene (real): 14 min` / `agents (sim): 24 min` from `reference.missions` via the injection-safe index map; `lives_at_risk` gets an `INFERRED` **ghost badge**. Grow the popover height math; keep 9px mono; verify 1080p legibility. |
| **Integration** | `App.tsx`, `MapTab.tsx` (mount edits) | Mounts the `DATA` chip in the app header (`App.tsx:165` area) and `RealityStrip` as the MapTab map-footer / the CompareTab shared band when `run.scenario` is present. Final density sweep. |

### Packs to ship

| Pack | Source (verified 2026-06-11) | Role | Ground truth |
|---|---|---|---|
| `sf-routine-2018` | DataSF `nuek-vuh3` (SODA, keyless, **PDDL**), 7.34 M rows | **MVP** — cleanest single source, builds the compiler | Real demand + real per-unit latency |
| `nyc-ida-2021` | NYC Open Data `76xm-jjuj` + `8m42-w767` (keyless); Ida window: 2,003 EMS incidents, 16.5 % held, **avg** 948 s (vs avg 538 s in 2012-10-15/16 normal window; adapter computes an Ida-adjacent baseline) | **Headline** — real disaster surge | Real demand + latency + held-rate |
| `tur-2023` *(optional, deferred)* | AFAD `apiv2/event/filter` + USGS ComCat/ShakeMap/PAGER for `us6000jllz` | On-theme showpiece — real M7.7→M7.6 doublet | Hazard only — demand/response synthesized; no `reference`, so RealityStrip does not render; caveat *"Hazard timing: real · Demand & outcomes: simulated model"* |

Licensing for `tur-2023`: AFAD has **no formal open license** — attribution required, **do not
commit/redistribute the raw catalog** (`raw/` gitignored). USGS products are US public domain
("Credit: U.S. Geological Survey"). SF/NYC mapping decisions (call-type → kind tables, severity
rules, null-handling) are in §2 of the research report — implemented as config YAMLs, not code.

### Testing & definition of done

- **Compiler:** unit tests per adapter against committed fixtures (no network); golden-file test
  (recompile from identical `raw/` fixture + config → byte-identical `scenario.json`); sampling
  determinism (same `sample_seed` → same `kept` set).
- **Pack loading:** pydantic rejection tests (bad district id, severity 0/6, unsorted timeline,
  unknown pool kind, reference key out of range, last-mission-tick + 16 > 120).
- **Engine:** `aftershock verify --scenario sf-routine-2018` passes (two runs, identical digests);
  scripted-arm e2e on a fixture pack resolves/fails missions and spawned count == `sampling.kept`;
  under-budget explicit `--ticks` errors; `bench --scenario` errors.
- **API:** `/api/scenarios` list + detail; `POST /api/live` unknown scenario → 404, valid →
  manifest scenario block + server-side ticks default when omitted; `/api/runs` carries the
  compact summary; path-traversal probes on scenario id → 404.
- **Web:** `npm run build` + `npx tsc --noEmit` clean; vitest for RealityStrip math
  (ticks×tick_minutes, null-latency), the injection-safe index↔mission-id map (with/without
  injected spawns), provenance badge rendering (2-tier), district-name fallback, **and the kept
  popover latency lines + INFERRED ghost-badge**; existing single-run and compare behaviour
  unchanged when `run.scenario` is null.
- **Docs:** README "Real-data scenarios" subsection with attribution lines; per-pack `README.md`
  committed alongside each `scenario.json`.

### Phasing & effort

All phases unblocked (task #3 merged). S1–S3 and S4 share no files.

| Phase | Scope | Files | Est. |
|---|---|---|---|
| **S1** | `town/scenario.py`, `town/arms.py`, `cli.py`, tests | engine-side only | 0.5–1 d |
| **S2** | compiler package + SF adapter + `sf-routine-2018` pack + fixtures | `src/aftershock/data/`, `scenarios/`, `.gitignore` | 1–2 d |
| **S3** | API endpoints + manifest plumbing + Dockerfile COPY | `web.py`, `Dockerfile` | 0.5–1 d |
| **S4** | UI per surface table (UX-contract-applied) | `web/src/**` | 1.5–2 d |
| **S5** | `nyc-ida-2021` (EMS+Fire join, computed baseline window) | adapter + pack | 1–2 d |
| **S6** *(deferred)* | `tur-2023` (AFAD+ShakeMap) | adapter + pack | 2–3 d |

This pass = **S1–S5** (headline: SF compiler + NYC Ida).

**Deferred (explicit non-goals):** all-hazards engine vocabulary (scenario-defined mission/resource
kinds, dynamics packs) — post-hackathon v2; live re-fetching of upstream data at run time (never —
invariant 2); scenario packs in `bench` (invariant 3); renaming injection kinds per hazard;
`tur-2023` pack (S6).

## After-action reports and the memory loop (`src/aftershock/llm/aar.py`)

At the end of a society run, the flagship model writes the analysis — completing the
cost-tiered cognition story (flash workers → plus commander → max analyst) — and its
lessons feed the commander's next briefing, so the society learns across disasters.

### aar.py

```python
AAR_MODEL = "qwen3-max"

def build_run_digest(manifest: dict, ticks: list[TickRecord]) -> str
    # Deterministic compact text: final scores; per-mission outcomes (kind, district,
    # severity, spawned/resolved/failed tick, response latency, lives); negotiation
    # stats (requests, grants, pool-exhausted declines with winner/loser pairs);
    # per-agent rejection patterns; injected events. Bounded (< ~3500 chars).

async def generate_aar(run_dir: Path, provider: Provider,
                       model: str = AAR_MODEL) -> dict
    # load_run -> digest -> one json_mode chat -> validate against AAR_SCHEMA ->
    # write run_dir/aar.json (canonical JSON, includes "usage" with cost) -> return it.
    # AAR_SCHEMA (pydantic): headline (str), grade (one of A/B/C/D/F),
    # what_worked (list[str]), coordination_failures (list[str]),
    # key_moments (list[{tick: int, description: str}]),
    # lessons (list[str], MAX 5, each <= 140 chars, imperative voice).

def load_lessons(memory_path: Path, max_lessons: int = 5) -> list[str]
def append_lessons(memory_path: Path, run_id: str, lessons: list[str]) -> None
    # memory_path (default <runs_root>/memory.json): append-only
    # [{"run_id", "lessons"}]; load returns the most recent max_lessons,
    # each passed through llm.digest.sanitize (LLM-generated text re-entering
    # prompts is a self-injection surface — sanitize + cap is non-negotiable).
```

### Wiring

- `build_llm_agents(roles, provider, lessons: list[str] | None = None)` — when lessons
  are given, the COMMANDER's system prompt gains a final block:
  "LESSONS FROM PREVIOUS DISASTERS (apply where relevant):" + numbered lessons.
  Other roles unchanged. `build_arm(..., lessons=None)` passes through for the
  society arm only.
- **Fairness invariant: `bench.py` never passes lessons** — benchmark arms stay
  memory-free so paired comparisons measure architecture, not accumulated hints.
  The memory loop is measured by the dedicated episodes experiment instead.
- CLI:
  - `aftershock aar <run_dir>` — generate (or `--show` an existing) AAR.
  - `aftershock run --arm society --memory` — load lessons from `<out>/memory.json`
    before the run, and afterwards generate the AAR and append its lessons.
  - `aftershock episodes --n 5 --seed-base 100 [--out runs/episodes]` — N sequential
    society runs on seeds base..base+N-1 with AAR+memory between runs (episode 1 runs
    memoryless); writes per-episode run dirs + `episodes.json` + a markdown table of
    the lives_saved / cost trajectory. This is the "does the society learn?" experiment.
- Web: `GET /api/runs/{run_id}/aar` (404 when absent); `POST /api/live` accepts
  optional `"aar": true` — on completion the server generates the AAR, appends lessons
  to `<runs_root>/memory.json`, and the next live society run with `"memory": true`
  uses them. WS emits `{"type": "aar", "report": ...}` after "done" when requested.
- UI: an After-Action Report drawer on the Map tab (visible when the loaded run has an
  AAR): headline + grade badge, lessons, key moments as clickable tick-jump chips.
  Live tab: aar/memory toggles on the start form, "[aar] generating…/done" log lines.

## Doctrine and conformance (`src/aftershock/town/doctrine.yaml`, `town/conformance.py`)

Two-tier doctrine, mirroring real incident command: one shared **team playbook**
(coordination norms — the protocol written as doctrine) plus slim **role playbooks**
(specialist duties). The rules are simultaneously the *instruction* (injected into
system prompts) and the *yardstick* (checked deterministically against run records).
No LLM judging: every check is reproducible from the NDJSON by hand.

### doctrine.yaml

```yaml
team:
  - id: T1
    text: "Acquire resources only through auction requests — never attempt direct dispatch."
    arms: [society]
  - {id: T2, text: "Request only what a mission still needs — quantity at most required minus assigned.", arms: [society]}
  - {id: T3, text: "State urgency honestly: urgency above 8 only when severity >= 4 or deadline within 4 ticks.", arms: [society]}
  - {id: T4, text: "Answer every handoff or resource request addressed to you the tick it appears.", arms: [society]}
  - {id: T5, text: "Never resubmit a rejected decision unchanged within the next 3 ticks.", arms: [society, swarm, solo]}
  - {id: T6, text: "Do not duplicate a peer: never re-request a mission+resource granted this tick or last once requirements are met.", arms: [society]}
roles:
  commander:
    - {id: C1, text: "Set a priority for every new mission within 2 ticks of its spawn.", arms: [society]}
    - {id: C2, text: "Priorities set in the same tick must not invert severity-then-deadline order.", arms: [society]}
    - {id: C3, text: "Answer every escalation the tick it arrives.", arms: [society]}
  medical:
    - {id: M1, text: "Serve medical_surge missions in priority-then-deadline order: never request for a lower-priority surge while a higher-priority one has unmet needs you ignored that tick.", arms: [society, swarm]}
    - {id: M2, text: "Escalate any medical_surge under half-staffed with 4 or fewer ticks to deadline.", arms: [society]}
  rescue:   # R1, R2 — same pattern for collapse_rescue
  fire:     # F1, F2 — same pattern for fire
  infrastructure:
    - {id: I1, text: "Attempt road repairs only on actually blocked districts with a crew available.", arms: [society, swarm, solo]}
    - {id: I2, text: "Clear blockages on districts with open missions before districts without.", arms: [society, swarm, solo]}
  comms:
    - {id: X1, text: "Broadcast within 2 ticks whenever panic crosses 0.4 upward.", arms: [society, swarm, solo]}
    - {id: X2, text: "At most one broadcast per 3 ticks.", arms: [society, swarm, solo]}
```

(rescue/fire entries are spelled out in full in the file, mirroring medical.)

### town/doctrine.py

```python
@dataclass(frozen=True)
class Rule: id: str; text: str; arms: tuple[str, ...]; role: str | None  # None = team
def load_doctrine(path: Path | None = None) -> list[Rule]   # validates unique ids
def doctrine_blocks(rules: list[Rule], role: str, arm: str) -> str
    # "TEAM DOCTRINE:\n  T1. ...\n..." + "YOUR ROLE DOCTRINE:\n  C1. ..." —
    # filtered by arm; empty sections omitted.
```

`build_llm_agents` inserts the blocks between the role prompt and the contract;
`build_arm` passes the arm name. Scripted agents are unaffected (the doctrine
describes what they already do — that is the calibration premise).

### town/conformance.py — deterministic checkers

```python
def check_run(run_dir: Path) -> dict   # writes + returns conformance.json
def render_markdown(report: dict) -> str
```

Report shape: `{arm, seed, rules: {rule_id: {agent_id: {applicable, violations:
[{tick, detail}], rate}}}, role_conformance: {agent_id: rate}, team_alignment: rate,
notes: [...]}`. Rates = 1 − violations/applicable (1.0 when applicable == 0).
Run-record conventions the checkers rely on: observations are reconstructed —
`inbox(agent, t)` = proposals sent at t−1 with `recipient == agent` (plus broadcasts);
state-dependent checks read `worlds[t−1]` (the state an agent observed at tick t);
tick 0 is exempt from state-dependent applicability; runs without world.ndjson mark
state-dependent rules `applicable: 0` with a note.

Check definitions (violations; applicability is the natural event count):
- **T1**: any agent-emitted `dispatch` decision (in `responses[].decisions`; kernel
  grants are not agent-emitted).
- **T2**: request qty > max(0, required − assigned) for that mission in worlds[t−1].
- **T3**: urgency > 8 while severity < 4 and deadline_tick − t > 4.
- **T4**: a handoff/resource_request addressed to the agent (reconstructed inbox)
  with no matching ProposalResponse that tick. Escalations to the commander are
  scored under C3 instead, never double-counted.
- **T5**: a decision with identical (decision_type, params) re-emitted by the same
  agent within 3 ticks of its rejection.
- **T6**: re-request of a (mission, resource) pair within 1 tick of an accepted
  auction grant that met the requirement (worlds check).
- **C1**: mission spawned at t still has priority 0 and status open in worlds[t+2].
- **C2**: among missions prioritized in one tick: pair where (severity, deadline
  pressure) is strictly greater on both components yet priority is strictly lower.
- **C3**: escalation in commander's reconstructed inbox with no response that tick.
- **M1/R1/F1**: agent requested for mission X of its kind while mission Y (same
  kind, strictly higher priority, unmet requirements in worlds[t−1]) got no request
  from the agent that tick.
- **M2/R2/F2**: first tick a mission of the kind is open, under half-staffed, with
  deadline_in ≤ 4 (per worlds[t−1]): no escalation from the agent within [t, t+1].
- **I1**: repair_road rejected for "not blocked" or "no repair_crew".
- **I2**: accepted repair on a district with zero open missions while another
  blocked district had open missions (worlds[t−1]).
- **X1**: panic crosses 0.4 upward between worlds[t−1] and worlds[t]: no accepted
  broadcast in [t+1, t+2].
- **X2**: two accepted broadcasts fewer than 3 ticks apart.

**Calibration invariant (the checker's own validity test):** scripted runs (seeds
42 and 7, 60 ticks) must produce zero violations on every rule — the scripted agents
*embody* the doctrine. A checker that flags them is mis-specified; the test suite
enforces this, and any genuine scripted-agent doctrine breach found this way is
fixed in heuristics.py, not waived.

### Integrations

- CLI: `aftershock conformance <run_dir> [--json]` — prints render_markdown (or raw
  JSON), writes conformance.json into the run dir.
- AAR: `generate_aar` runs `check_run` first and appends a `=== DOCTRINE ===` digest
  section (team alignment, per-rule violation counts with rule text, top 5 concrete
  violations) so lessons can cite rule ids; the AAR schema gains optional
  `doctrine_notes: list[str]` (≤ 3).
- Bench: each cell's summary.json gains `team_alignment` and `role_conformance`;
  aggregate + tables gain a team-alignment column (memoryless as ever).
- Web/UI: `GET /api/runs/{run_id}/conformance` (same validation; 404 when absent,
  generated lazily is NOT done server-side — CLI/AAR produce it); agent chips in the
  inspector show a conformance badge when data exists; the AAR drawer renders
  doctrine_notes.

## CLI

```
aftershock run    --seed 42 --ticks 60 --arm scripted|solo|swarm|society [--out runs]
                  [--quiet] [--timeout S] [--memory]
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
