import json
from pathlib import Path

import unsloth
import torch
from datasets import Dataset
from transformers import Trainer, TrainingArguments
from unsloth import FastLanguageModel

BASE_MODEL = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
DATA_FILE = Path("eva_lora_train_v2.jsonl")
OUTPUT_DIR = Path("eva-lora-adapter-v3")
MAX_LENGTH = 512

if not DATA_FILE.exists():
    raise FileNotFoundError(f"Dataset not found: {DATA_FILE.resolve()}")

rows = []
with DATA_FILE.open("r", encoding="utf-8-sig") as f:
    for line_no, line in enumerate(f, 1):
        if not line.strip():
            continue
        item = json.loads(line)
        if not all(k in item for k in ("instruction", "input", "output")):
            raise ValueError(f"Missing required field on line {line_no}")
        rows.append(item)

if not rows:
    raise ValueError("Dataset is empty.")

print(f"Validated examples: {len(rows)}")
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CUDA unavailable")

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=MAX_LENGTH,
    dtype=None,
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=8,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_alpha=16,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=3407,
)

def tokenize_example(example):
    prompt = example["instruction"]
    if example["input"].strip():
        prompt += "\n\nContext:\n" + example["input"]

    prompt_messages = [{"role": "user", "content": prompt}]
    full_messages = prompt_messages + [
        {"role": "assistant", "content": example["output"]}
    ]

    prompt_ids = tokenizer.apply_chat_template(
        prompt_messages,
        tokenize=True,
        add_generation_prompt=True,
    )
    full_ids = tokenizer.apply_chat_template(
        full_messages,
        tokenize=True,
        add_generation_prompt=False,
    )

    if isinstance(prompt_ids, dict):
        prompt_ids = prompt_ids["input_ids"]
    if isinstance(full_ids, dict):
        full_ids = full_ids["input_ids"]

    if hasattr(prompt_ids, "tolist"):
        prompt_ids = prompt_ids.tolist()
    if hasattr(full_ids, "tolist"):
        full_ids = full_ids.tolist()

    if prompt_ids and isinstance(prompt_ids[0], list):
        prompt_ids = prompt_ids[0]
    if full_ids and isinstance(full_ids[0], list):
        full_ids = full_ids[0]

    full_ids = full_ids[:MAX_LENGTH]
    prompt_len = min(len(prompt_ids), len(full_ids))
    labels = [-100] * prompt_len + full_ids[prompt_len:]

    # Skip examples where truncation leaves no assistant target tokens.
    if not any(token != -100 for token in labels):
        labels[-1] = full_ids[-1]

    attention_mask = [1] * len(full_ids)
    return {
        "input_ids": full_ids,
        "attention_mask": attention_mask,
        "labels": labels,
    }

tokenized = Dataset.from_list(rows).map(
    tokenize_example,
    remove_columns=["instruction", "input", "output"],
)

class AssistantOnlyCollator:
    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def __call__(self, features):
        batch = self.tokenizer.pad(
            [
                {
                    "input_ids": f["input_ids"],
                    "attention_mask": f["attention_mask"],
                }
                for f in features
            ],
            padding=True,
            return_tensors="pt",
        )
        max_len = batch["input_ids"].shape[1]
        padded_labels = []
        for f in features:
            labels = f["labels"][:max_len]
            labels += [-100] * (max_len - len(labels))
            padded_labels.append(labels)
        batch["labels"] = torch.tensor(padded_labels, dtype=torch.long)
        return batch

collator = AssistantOnlyCollator(tokenizer)

args = TrainingArguments(
    output_dir="eva-lora-training-temp-v3",
    per_device_train_batch_size=1,
    gradient_accumulation_steps=2,
    num_train_epochs=3,
    learning_rate=1e-4,
    logging_steps=5,
    save_strategy="no",
    report_to="none",
    optim="adamw_torch",
    fp16=False,
    bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
    gradient_checkpointing=True,
    dataloader_num_workers=0,
    remove_unused_columns=False,
    seed=3407,
)

trainer = Trainer(
    model=model,
    args=args,
    train_dataset=tokenized,
    data_collator=collator,
)

print("Starting V3 assistant-only training...")
trainer.train()

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
model.save_pretrained(str(OUTPUT_DIR))
tokenizer.save_pretrained(str(OUTPUT_DIR))

print("\nV3 TRAINING: SUCCESS")
print("Adapter saved to:", OUTPUT_DIR.resolve())
print("Previous adapters remain unchanged.")


