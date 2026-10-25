"""Builds ../notebooks/finetune.ipynb from the cells below (uv run python models/text2sql-3b-v3/tools/build_notebook.py).
Cells starting with '#md' are markdown."""
import json, sys
from pathlib import Path

CELLS = [
'''#md
# Fine-tune Qwen2.5-Coder for Indonesian → ClickHouse Text-to-SQL

**Runtime → Change runtime type → T4 GPU**, then run top to bottom.

Upload `colab_upload.zip` when asked (contains `text2sql-spec.md`, `seed.sql`, `train.jsonl`, `eval.jsonl`).

Output: `text2sql-q4_k_m.gguf` + `Modelfile` for Ollama (~2 GB for 3B, ~1 GB for 1.5B).''',

'''!pip install -q unsloth chdb''',

'''import os, zipfile
from google.colab import files
uploaded = files.upload()  # pick colab_upload.zip
zipfile.ZipFile(next(iter(uploaded))).extractall()
assert all(os.path.exists(f) for f in ["text2sql-spec.md", "seed.sql", "train.jsonl", "eval.jsonl"]), os.listdir()''',

'''MODEL = "unsloth/Qwen2.5-Coder-3B-Instruct"  # ~2 GB as Q4; or unsloth/Qwen2.5-Coder-1.5B-Instruct (~1 GB)
MAX_LEN = 2048
EPOCHS = 3  # eval loss per epoch is printed during training; it was still falling at epoch 2 last time''',

'''#md
## Load model + LoRA''',

'''from unsloth import FastLanguageModel, is_bfloat16_supported

model, tokenizer = FastLanguageModel.from_pretrained(MODEL, max_seq_length=MAX_LEN, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16, lora_dropout=0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    use_gradient_checkpointing="unsloth", random_state=3407)''',

'''#md
## Data''',

'''import json
from datasets import Dataset

def load(path):
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]

train_rows, eval_rows = load("train.jsonl"), load("eval.jsonl")
to_ds = lambda rows: Dataset.from_list([{"text": tokenizer.apply_chat_template(r["messages"], tokenize=False)} for r in rows])
train_ds, eval_ds = to_ds(train_rows), to_ds(eval_rows)
longest = max(len(tokenizer(t).input_ids) for t in train_ds["text"])
print(len(train_rows), "train,", len(eval_rows), "eval, longest sample", longest, "tokens")
assert longest < MAX_LEN''',

'''#md
## Evaluation: execution accuracy on embedded ClickHouse

Builds the same schema + seed data with `chdb`, then a generated query counts as correct when it returns the same rows as the reference query.''',

'''import re
import json
from chdb import session as chs

spec = open("text2sql-spec.md", encoding="utf-8").read()
ddl = re.search(r"```sql\\n(.*?)```", spec, re.S).group(1)

def statements(text):
    text = re.sub(r"--[^\\n]*", "", text)
    return [s.strip() for s in text.split(";") if s.strip()]

ch = chs.Session()
ch.query("DROP DATABASE IF EXISTS crm")  # safe to re-run this cell
ch.query("CREATE DATABASE crm")
ch.query("USE crm")
for s in statements(ddl) + statements(open("seed.sql", encoding="utf-8").read()):
    ch.query(s)
ch.query("SET readonly = 1")  # generated SQL can't modify the data
print(ch.query("SELECT count() FROM deals", "CSV"))

def run(sql):
    """Rows as a sorted list (order-insensitive), floats rounded; None if the query fails."""
    try:
        b = ch.query(sql, "JSONCompact").bytes()
        if not b:  # some chdb versions return an empty result instead of raising on bad SQL
            return None
        data = json.loads(b)["data"]
    except Exception:  # invalid SQL from the model or JSON decoding failure
        return None
    canon = lambda row: json.dumps([round(v, 4) if isinstance(v, float) else v for v in row])
    return sorted(map(canon, data))  # ponytail: ignores ORDER BY; compare in order if ranking accuracy matters

def clean(text):
    m = re.search(r"```(?:sql)?\\s*(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip().rstrip(";")

def generate_sql(messages):
    prompt = tokenizer.apply_chat_template(messages[:2], tokenize=False, add_generation_prompt=True)
    ids = tokenizer(prompt, return_tensors="pt").to("cuda")
    out = model.generate(**ids, max_new_tokens=512, do_sample=False)
    return clean(tokenizer.decode(out[0][ids.input_ids.shape[1]:], skip_special_tokens=True))

def evaluate(rows, show=3):
    from collections import defaultdict
    FastLanguageModel.for_inference(model)
    per_cat, wrong = defaultdict(lambda: [0, 0]), []
    for r in rows:
        gold, pred = r["messages"][2]["content"], generate_sql(r["messages"])
        if (g := run(gold)) is None:  # chdb's ClickHouse version rejects the reference query
            print("GOLD FAILS on chdb:", gold[:120])
            continue
        ok = run(pred) == g
        per_cat[r["category"]][0] += ok
        per_cat[r["category"]][1] += 1
        if not ok: wrong.append((r["messages"][1]["content"], pred, gold))
    total, n = sum(c[0] for c in per_cat.values()), sum(c[1] for c in per_cat.values())
    print(f"execution accuracy: {total}/{n} = {total / n:.1%}")
    for cat, (ok, n) in sorted(per_cat.items()):
        print(f"  {cat:10s} {ok}/{n}")
    for q, p, g in wrong[:show]:
        print("\\nQ:", q, "\\nPRED:\\n", p, "\\nGOLD:\\n", g)''',

'''#md
### Baseline (optional, ~5–10 min): the untrained model, for comparison''',

'''evaluate(eval_rows)''',

'''#md
## Train (~2 h on T4 for 3B with ~4,250 samples x 3 epochs, ~1 h for 1.5B)

Each epoch ends with an eval loss on `eval.jsonl`: if it rises from epoch 1 to 2, the model is overfitting and fewer epochs or less data repetition is the fix.''',

'''from trl import SFTTrainer, SFTConfig
from unsloth.chat_templates import train_on_responses_only

FastLanguageModel.for_training(model)
trainer = SFTTrainer(
    model=model, tokenizer=tokenizer, train_dataset=train_ds, eval_dataset=eval_ds,
    args=SFTConfig(
        dataset_text_field="text", max_seq_length=MAX_LEN,
        per_device_train_batch_size=4, gradient_accumulation_steps=2,
        num_train_epochs=EPOCHS, learning_rate=2e-4, warmup_steps=10,
        lr_scheduler_type="linear", optim="adamw_8bit", weight_decay=0.01,
        fp16=not is_bfloat16_supported(), bf16=is_bfloat16_supported(),
        eval_strategy="epoch", per_device_eval_batch_size=2,  # eval loss is only reported, it does not change training
        logging_steps=10, seed=3407, output_dir="outputs", report_to="none"))
# Loss only on the SQL, not on the system prompt / question.
trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\\n", response_part="<|im_start|>assistant\\n")
trainer.train()''',

'''#md
## Evaluate the fine-tuned model''',

'''evaluate(eval_rows, show=5)''',

'''#md
## Export for Ollama''',

'''import glob, shutil

model.save_pretrained("lora_adapter"); tokenizer.save_pretrained("lora_adapter")
model.save_pretrained_gguf("gguf", tokenizer, quantization_method="q4_k_m")
gguf = [p for p in glob.glob("gguf*/**/*.gguf", recursive=True) if "Q4_K_M" in p.upper()][0]
shutil.copy(gguf, "text2sql-q4_k_m.gguf")

system = train_rows[0]["messages"][0]["content"]
open("Modelfile", "w", encoding="utf-8").write(f\'\'\'FROM ./text2sql-q4_k_m.gguf
TEMPLATE """{{{{- if .System }}}}<|im_start|>system
{{{{ .System }}}}<|im_end|>
{{{{ end }}}}<|im_start|>user
{{{{ .Prompt }}}}<|im_end|>
<|im_start|>assistant
"""
SYSTEM """{system}"""
PARAMETER temperature 0
PARAMETER stop "<|im_end|>"
PARAMETER num_ctx 2048
\'\'\')
!ls -lh text2sql-q4_k_m.gguf Modelfile''',

'''#md
Download (browser download of ~2 GB is slow; the Drive cell below is the alternative). Then locally:
```
ollama create text2sql -f Modelfile
ollama run text2sql "berapa omset bulan ini?"
```''',

'''files.download("Modelfile")
files.download("text2sql-q4_k_m.gguf")''',

'''# Alternative: copy to Google Drive
from google.colab import drive
drive.mount("/content/drive")
!mkdir -p /content/drive/MyDrive/text2sql && cp text2sql-q4_k_m.gguf Modelfile /content/drive/MyDrive/text2sql/ && cp -r lora_adapter /content/drive/MyDrive/text2sql/''',
]


def cell(src):
    md = src.startswith("#md\n")
    src = src[4:] if md else src
    lines = src.splitlines(keepends=True)
    c = {"cell_type": "markdown" if md else "code", "metadata": {}, "source": lines}
    if not md:
        c.update(outputs=[], execution_count=None)
    return c


nb = {"nbformat": 4, "nbformat_minor": 0,
      "metadata": {"accelerator": "GPU", "colab": {"provenance": [], "gpuType": "T4"},
                   "kernelspec": {"name": "python3", "display_name": "Python 3"}},
      "cells": [cell(s) for s in CELLS]}
out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "notebooks" / "finetune.ipynb"
json.dump(nb, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
