import unsloth
from unsloth import FastLanguageModel
import torch

BASE_MODEL = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
ADAPTER_DIR = r"D:\Eva_Ai_brain\eva-lora-adapter-v2"

print("Loading base model and EVA LoRA adapter...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=512,
    dtype=None,
    load_in_4bit=True,
)

model.load_adapter(ADAPTER_DIR)
FastLanguageModel.for_inference(model)

questions = [
    "Explain EVA AI in simple English.",
    "RAG म्हणजे काय? मराठीत सोप्या भाषेत सांग."
]

for question in questions:
    messages = [{"role": "user", "content": question}]
    inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to("cuda")

    with torch.inference_mode():
        outputs = model.generate(
            input_ids=inputs,
            max_new_tokens=120,
            temperature=0.7,
            do_sample=True,
            use_cache=True,
        )

    answer = tokenizer.decode(
        outputs[0][inputs.shape[-1]:],
        skip_special_tokens=True,
    )
    print("\nQUESTION:", question)
    print("ANSWER:", answer)
    print("-" * 60)

