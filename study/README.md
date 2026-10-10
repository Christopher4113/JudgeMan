# The study behind judgeman

Everything used to produce the three reports in `../reports/`. None of it is needed to use the tool.

| Folder | What is in it |
|---|---|
| `labels/` | Every hand label and every judge's verdict on every step. `human.jsonl` is the 516-step gold set; `human2.jsonl` and `human3.jsonl` are the second labeler's passes; `rule2-*` and `flag2-*` are the labels made under the rule the two labelers agreed on; `leg2/` holds each judge tier's verdicts per context; `*-queue.json` and `*-files.txt` record which steps and runs each sample drew. |
| `scripts/` | `inject.py` plants mistakes in real runs; `leg2_subset.py` picks the 150-step subset; `leg2_results.py` prints the Leg 2 and Leg 3 result tables; `redundant_estimate.py` scores the repeat axis under the strict rule; `finetune_data.py` and `finetune_score.py` build the training files and score the Kaggle exam replies. |
| `notebooks/` | The Kaggle notebook that fine-tuned Qwen 3.5 9B with QLoRA on a free T4. |

Rebuild every table without an API key:

```bash
uv run python study/scripts/leg2_results.py
uv run python study/scripts/redundant_estimate.py
```

`inject.py`, `finetune_data.py` and `finetune_score.py` also need the downloaded runs (`judgeman fetch`,
see `../docs/demo.md`) or the Kaggle outputs, neither of which is in git.

The Leg 1 and Leg 2 reports were written before this folder existed and refer to these paths as
`labels/` and `scripts/`; add the `study/` prefix.
