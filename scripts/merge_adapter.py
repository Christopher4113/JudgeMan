# Merge the judge LoRA adapter into Qwen3.5-9B and push full bf16 safetensors to Hugging Face,
# for benchmark hosts that cannot load adapters (TPN Bench). Needs ~30 GB RAM: run on Kaggle, not a 16 GB Mac.
#   pip install -U transformers peft accelerate && huggingface-cli login
#   python merge_adapter.py
import torch
from peft import PeftModel
from transformers import AutoProcessor, AutoTokenizer, Qwen3_5ForConditionalGeneration

BASE = "unsloth/Qwen3.5-9B"
ADAPTER = "Christopher4113/judgeman-qwen3.5-9b-judge"
OUT = "Christopher4113/judgeman-qwen3.5-9b-judge-merged"

model = Qwen3_5ForConditionalGeneration.from_pretrained(BASE, torch_dtype=torch.bfloat16, low_cpu_mem_usage=True)
model = PeftModel.from_pretrained(model, ADAPTER).merge_and_unload()
model.push_to_hub(OUT, max_shard_size="5GB")  # transformers 5 always writes safetensors
AutoProcessor.from_pretrained(BASE).push_to_hub(OUT)
AutoTokenizer.from_pretrained(ADAPTER).push_to_hub(OUT)  # adapter's tokenizer carries the judge chat template
