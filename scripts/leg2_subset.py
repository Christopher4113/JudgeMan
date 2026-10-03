"""Leg 2: pick the 150 gold steps the frontier judge sees in the context ablation, and the 90
of them that get a fresh hand label for `redundant` under the strict rule.

Half of each list is steps that some source once called a repeat, so there are enough yes
answers to score; the rest is random. The stratum of every step is saved for weighting.
Run: uv run python scripts/leg2_subset.py
"""

import json
import random
from pathlib import Path

from judgeman.schema import read_labels

L = Path("labels")
gold = {(x.trajectory_id, x.step) for x in read_labels(L / "human.jsonl")}
suspected = set()
for name in ("human", "checks", "judge-claude-opus-5.5", "judge-claude-opus-5.5-deepseek",
             "judge-gemini-3.5-flash-lite"):  # fmt: skip
    suspected |= {(x.trajectory_id, x.step) for x in read_labels(L / f"{name}.jsonl") if x.redundant}
suspected &= gold
rng = random.Random(2)
flagged = rng.sample(sorted(suspected), min(60, len(suspected)))
plain = rng.sample(sorted(gold - suspected), 150 - len(flagged))
relabel = rng.sample(flagged, 45) + rng.sample(plain, 45)

subset = {"suspected_repeat": sorted(flagged), "random": sorted(plain),
          "pool": {"suspected_repeat": len(suspected), "random": len(gold - suspected)}}  # fmt: skip
(L / "leg2-subset.json").write_text(json.dumps(subset, indent=1))
(L / "leg2-subset-queue.json").write_text(json.dumps(sorted(flagged + plain)))
(L / "redundant-strict-queue.json").write_text(json.dumps(sorted(relabel)))
print(f"{len(suspected)} suspected repeats in {len(gold)} gold steps")
print(f"subset: {len(flagged)} suspected + {len(plain)} random; relabel queue: {len(relabel)}")
