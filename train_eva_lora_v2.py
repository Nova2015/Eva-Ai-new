import json
from pathlib import Path

import unsloth
import torch
from datasets import Dataset
from transformers import Trainer, TrainingArguments, DataCollatorForLanguageModeling
from unsloth import FastLanguageModel

BASE_MODEL = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
DATA_FILE = Path("eva_lora_train_v2.jsonl")
OUTPUT_DIR = Path("eva-lora-adapter-v2")
MAX_LENGTH = 512

if not DATA_FILE.exists():
    raise FileNotFoundError(f"Training data not found: {DATA_FILE.resolve()}")

rows = []
with DATA_FILE.open("r", encoding="utf-8-sig") as f:
    for line_no, line in enumerate(f, 1):
        if not line.strip():
            continue
        item = json.loads(line)
        for key in ("instruction", "input", "output"):
            if key not in item:
                raise ValueError(f"Missing '{key}' on line {line_no}")
        rows.append(item)

if not rows:
    raise ValueError("Training dataset is empty.")

print(f"Dataset validated: {len(rows)} examples")
print("GPU:", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "Not available")

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=MAX_LENGTH,
    dtype=None,
    load_in_4bit=True,
)

if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

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
    use_rslora=False,
)

def format_and_tokenize(example):
    user_text = example["instruction"]
    if example["input"].strip():
        user_text += "\n\nContext:\n" + example["input"]

    messages = [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": example["output"]},
    ]
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )
    return tokenizer(
        text,
        truncation=True,
        max_length=MAX_LENGTH,
    )

dataset = Dataset.from_list(rows)
tokenized = dataset.map(
    format_and_tokenize,
    remove_columns=dataset.column_names,
)

collator = DataCollatorForLanguageModeling(
    tokenizer=tokenizer,
    mlm=False,
)

args = TrainingArguments(
    output_dir="eva-lora-training-temp-v2",
    per_device_train_batch_size=1,
    gradient_accumulation_steps=2,
    max_steps=10,
    learning_rate=2e-4,
    logging_steps=1,
    save_strategy="no",
    report_to="none",
    optim="adamw_torch",
    fp16=torch.cuda.is_available() and not torch.cuda.is_bf16_supported(),
    bf16=torch.cuda.is_available() and torch.cuda.is_bf16_supported(),
    gradient_checkpointing=False,
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

print("Starting LoRA training...")
trainer.train()

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
model.save_pretrained(str(OUTPUT_DIR))
tokenizer.save_pretrained(str(OUTPUT_DIR))

print("\nTRAINING: SUCCESS")
print("Adapter saved to:", OUTPUT_DIR.resolve())
print("Base model remains unchanged.")


