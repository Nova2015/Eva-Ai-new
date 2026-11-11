import os, json, random, hashlib
from pathlib import Path

os.environ["HF_HUB_OFFLINE"] = "0"
os.environ["TRANSFORMERS_OFFLINE"] = "0"

from datasets import load_dataset

ROOT = Path("data/datasets/science/sciq")
ROOT.mkdir(parents=True, exist_ok=True)

ds = load_dataset("allenai/sciq")
instruction = (
    "Answer the science multiple-choice question. "
    "Select the correct option and explain using the supplied evidence. "
    "If evidence is insufficient, clearly state uncertainty."
)

def convert(split):
    rows = []
    for i, item in enumerate(ds[split]):
        answer = str(item["correct_answer"]).strip()
        support = str(item.get("support") or "").strip()

        options = [
            str(item["distractor1"]).strip(),
            str(item["distractor2"]).strip(),
            str(item["distractor3"]).strip(),
            answer,
        ]

        rng = random.Random(3407 + i)
        rng.shuffle(options)
        correct_index = options.index(answer)
        letter = "ABCD"[correct_index]

        choices = "\n".join(
            f"{'ABCD'[j]}) {option}" for j, option in enumerate(options)
        )

        context = (
            f"Support:\n{support}\n\n" if support else ""
        )
        question = str(item["question"]).strip()

        rows.append({
            "instruction": instruction,
            "input": (
                f"{context}Question: {question}\n\nOptions:\n{choices}"
            ),
            "output": f"Answer: {letter}) {answer}"
                      + (f"\nExplanation: {support}" if support else ""),
        })
    return rows

manifest = {
    "dataset": "allenai/sciq",
    "license": "CC-BY-NC-3.0",
    "seed": 3407,
    "splits": {}
}

for split in ("train", "validation", "test"):
    rows = convert(split)
    path = ROOT / f"{split}.jsonl"

    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest["splits"][split] = {
        "count": len(rows),
        "file": str(path),
        "sha256": digest,
    }
    print(f"{split}: {len(rows)} examples | {path}")

(ROOT / "manifest.json").write_text(
    json.dumps(manifest, indent=2), encoding="utf-8"
)

(ROOT / "LICENSE.txt").write_text(
    "Dataset: SciQ (allenai/sciq)\n"
    "License: Creative Commons Attribution-NonCommercial 3.0\n"
    "Paper: Welbl, Liu, Gardner (2017), arXiv:1707.06209\n",
    encoding="utf-8"
)

print("\nSCIENCE DATASET PREPARATION COMPLETE")
