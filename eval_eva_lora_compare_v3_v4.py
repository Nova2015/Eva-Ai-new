
import unsloth
import torch
from unsloth import FastLanguageModel

BASE = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"
V3 = r"D:\Eva_Ai_brain\eva-lora-adapter-v3"
V4 = r"D:\Eva_Ai_brain\eva-lora-adapter-v4"

QUESTIONS = [
    "What is EVA AI?",
    "EVA AI म्हणजे काय?",
    "What is RAG?",
    "RAG म्हणजे काय?",
    "What is a dataset?",
    "Dataset म्हणजे काय?",
    "What is LoRA?",
    "LoRA म्हणजे काय?",
]

MAX_NEW_TOKENS = 90

def main():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is unavailable.")

    print("GPU:", torch.cuda.get_device_name(0))
    print("Loading base model...")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE,
        max_seq_length=512,
        dtype=None,
        load_in_4bit=True,
    )

    FastLanguageModel.for_inference(model)

    def ask(question):
        inputs = tokenizer.apply_chat_template(
            [{"role": "user", "content": question}],
            tokenize=True,
            add_generation_prompt=True,
            return_tensors="pt",
        ).to("cuda")

        with torch.inference_mode():
            outputs = model.generate(
                input_ids=inputs,
                max_new_tokens=MAX_NEW_TOKENS,
                do_sample=False,
                use_cache=True,
            )

        return tokenizer.decode(
            outputs[0, inputs.shape[-1]:],
            skip_special_tokens=True,
        ).strip()

    results = {}

    print("\nEvaluating BASE...")
    results["BASE"] = {}
    for q in QUESTIONS:
        results["BASE"][q] = ask(q)

    for name, path in [("V3", V3), ("V4", V4)]:
        print(f"\nLoading {name} adapter: {path}")
        model.load_adapter(path, adapter_name=name.lower())
        model.set_adapter(name.lower())
        FastLanguageModel.for_inference(model)

        results[name] = {}
        for q in QUESTIONS:
            results[name][q] = ask(q)

    print("\n" + "=" * 75)
    print("BASE vs V3 vs V4 — EVALUATION RESULTS")
    print("=" * 75)

    for q in QUESTIONS:
        print(f"\nQUESTION: {q}")
        for name in ("BASE", "V3", "V4"):
            print(f"\n[{name}]\n{results[name][q]}")

    print("\nEvaluation complete.")
    print("No adapter files were modified.")

if __name__ == "__main__":
    main()
