
import gc
import torch
import unsloth
from unsloth import FastLanguageModel

BASE = "unsloth/Qwen2.5-1.5B-Instruct-bnb-4bit"

ADAPTERS = {
    "BASE": None,
    "V3": r"D:\Eva_Ai_brain\eva-lora-adapter-v3",
    "V4": r"D:\Eva_Ai_brain\eva-lora-adapter-v4",
    "V5": r"D:\Eva_Ai_brain\eva-lora-adapter-v5",
}

QUESTIONS = [
    "What is EVA AI?",
    "EVA AI \u092e\u094d\u0939\u0923\u091c\u0947 \u0915\u093e\u092f?",
    "What is RAG?",
    "RAG \u092e\u094d\u0939\u0923\u091c\u0947 \u0915\u093e\u092f?",
    "What is LoRA?",
    "LoRA \u092e\u094d\u0939\u0923\u091c\u0947 \u0915\u093e\u092f?",
]

def evaluate(name, adapter_path):
    print(f"\n{'=' * 65}\n{name}\n{'=' * 65}")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE,
        max_seq_length=512,
        dtype=None,
        load_in_4bit=True,
    )

    try:
        if adapter_path is not None:
            model.load_adapter(adapter_path, adapter_name="eval_adapter")
            model.set_adapter("eval_adapter")

        FastLanguageModel.for_inference(model)

        for question in QUESTIONS:
            inputs = tokenizer.apply_chat_template(
                [{"role": "user", "content": question}],
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
            ).to("cuda")

            with torch.inference_mode():
                output = model.generate(
                    input_ids=inputs,
                    max_new_tokens=90,
                    do_sample=False,
                    use_cache=True,
                )

            answer = tokenizer.decode(
                output[0, inputs.shape[-1]:],
                skip_special_tokens=True,
            ).strip()

            print(f"\nQ: {question}\nA: {answer}")

    finally:
        del model, tokenizer
        gc.collect()
        torch.cuda.empty_cache()

if __name__ == "__main__":
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU unavailable")

    print("GPU:", torch.cuda.get_device_name(0))

    for name, path in ADAPTERS.items():
        evaluate(name, path)

    print("\nClean evaluation complete.")
