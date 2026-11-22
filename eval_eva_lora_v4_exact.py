import unsloth
from unsloth import FastLanguageModel
import torch

BASE = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
ADAPTER = r"D:\Eva_Ai_brain\eva-lora-adapter-v4"

questions = [
    "What is EVA AI?",
    "EVA AI म्हणजे काय?",
    "What is RAG?",
    "RAG म्हणजे काय?",
    "What is a dataset?",
    "Dataset म्हणजे काय?"
]

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE,
    max_seq_length=512,
    dtype=None,
    load_in_4bit=True,
)
FastLanguageModel.for_inference(model)

def ask(q):
    messages = [{"role": "user", "content": q}]
    x = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to("cuda")
    with torch.inference_mode():
        y = model.generate(
            input_ids=x,
            max_new_tokens=90,
            do_sample=False,
            use_cache=True,
        )
    return tokenizer.decode(
        y[0][x.shape[-1]:], skip_special_tokens=True
    ).strip()

print("\n========== BASE MODEL ==========")
for q in questions:
    print(f"\nQ: {q}\nA: {ask(q)}")

print("\nLoading V4 adapter...")
model.load_adapter(ADAPTER)
FastLanguageModel.for_inference(model)

print("\n========== V4 ADAPTER ==========")
for q in questions:
    print(f"\nQ: {q}\nA: {ask(q)}")

print("\nV4 exact-question evaluation complete.")

