# Episodes v1: does AAR memory help? (2026-06-11)

Five sequential society runs (seeds 100-104) with qwen3-max after-action lessons fed
to the commander between episodes, against a paired memoryless control on identical
seeds (the bench harness, which is structurally memory-free).

| ep | seed | memory | control | diff |
|----|------|--------|---------|------|
| 1  | 100  | 113    | 113     | +0   |
| 2  | 101  | 108    | 108     | +0   |
| 3  | 102  | 71     | 81      | -10  |
| 4  | 103  | 134    | 141     | -7   |
| 5  | 104  | 114    | 124     | -10  |

Mean diff (memory − control): **−5.4 lives**; episodes 3–5 (two-plus lessons
accumulated): **−9.0**. Memory wins 0, control wins 3, ties 2 (sign test p≈0.125
one-sided — suggestive, not conclusive at n=5).

## Reading

The accumulated lessons were strategically plausible but mechanically unactionable
("pre-position crews before disaster onset" — there is no pre-disaster phase;
"track utilization metrics" — meta-commentary). Vague advice appears to act as a
distractor in the commander's context rather than guidance: performance was flat
while lessons were few and degraded as they accumulated.

## Next (v2)

Doctrine-grounded lessons: the AAR will cite playbook rule ids with concrete,
in-action-space directives (priorities, escalation responses, urgency thresholds),
and episodes will track team-alignment trajectory alongside lives saved — discipline
is a less noisy signal than outcomes.
