"""Turn the Kaggle notebook's exam replies into label files that leg2_results.py reads.

Put exam-replies.jsonl (fine-tuned) and exam-replies-base.jsonl (same model, untrained, same
4-bit setup) into finetune/, then: uv run python scripts/finetune_score.py
"""

import json
from pathlib import Path

from judgeman.adapter import load_trajectories
from judgeman.judge import parse_verdict
from judgeman.schema import write_labels

steps = {}
for f in Path("labels/gold-files.txt").read_text().split() + ["runs/injected"]:
    for t in load_trajectories(Path(f)):
        steps |= {(t.id, s.index): (t, s) for s in t.steps}

for source, tier in (("exam-replies.jsonl", "qwen-ft"), ("exam-replies-base.jsonl", "qwen-kaggle-base")):
    path = Path("finetune") / source
    if not path.exists():
        print("missing", path)
        continue
    labels, bad, seconds = {"gold": [], "injected": []}, 0, []
    for row in map(json.loads, path.read_text().splitlines()):
        t, s = steps[row["trajectory_id"], row["step"]]
        seconds.append(row["seconds"])
        try:
            label = parse_verdict(t, s, tier, row["reply"])
        except ValueError:
            bad += 1
            continue
        labels["injected" if "+" in t.id.split("@")[0] else "gold"].append(label)
    for kind, rows in labels.items():
        write_labels(Path("labels/leg2") / f"{tier}-last5-{kind}.jsonl", rows)
    seconds.sort()
    print(f"{tier}: {len(labels['gold'])} gold + {len(labels['injected'])} planted verdicts, "
          f"{bad} unusable, median {seconds[len(seconds) // 2]}s per step on the Kaggle GPU")
