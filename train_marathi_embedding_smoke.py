from pathlib import Path
import pandas as pd
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from sentence_transformers import SentenceTransformer

ROOT = Path(r"D:\Eva_Ai_brain")
DATA = ROOT / "data" / "marathi_triplets_audit"
TRAIN_FILE = DATA / "marathi_triplets_train.parquet"
TEST_FILE = DATA / "marathi_triplets_test.parquet"
OUT = ROOT / "models" / "marathi_embedding_smoke_20261029"

if OUT.exists():
    raise RuntimeError(f"Output already exists; refusing to overwrite: {OUT}")
if not TRAIN_FILE.exists() or not TEST_FILE.exists():
    raise FileNotFoundError("Expected train/test Parquet file was not found.")

torch.manual_seed(42)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(42)

device = "cuda" if torch.cuda.is_available() else "cpu"
model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

train = pd.read_parquet(TRAIN_FILE).sample(
    n=2000, random_state=42
).reset_index(drop=True)
test = pd.read_parquet(TEST_FILE).sample(
    n=min(500, len(pd.read_parquet(TEST_FILE))), random_state=42
).reset_index(drop=True)

model = SentenceTransformer(model_name, device=device)
model.max_seq_length = 128
model.train()

def evaluate():
    model.eval()
    a = model.encode(test["anchor"].tolist(), batch_size=16,
                     convert_to_tensor=True, normalize_embeddings=True,
                     show_progress_bar=False)
    p = model.encode(test["positive"].tolist(), batch_size=16,
                     convert_to_tensor=True, normalize_embeddings=True,
                     show_progress_bar=False)
    n = model.encode(test["negative"].tolist(), batch_size=16,
                     convert_to_tensor=True, normalize_embeddings=True,
                     show_progress_bar=False)
    ps = (a * p).sum(dim=1)
    ns = (a * n).sum(dim=1)
    result = {
        "positive_similarity": ps.mean().item(),
        "negative_similarity": ns.mean().item(),
        "accuracy": (ps > ns).float().mean().item() * 100,
        "margin": (ps - ns).mean().item()
    }
    model.train()
    return result

print("Device:", device)
if device == "cuda":
    print("GPU:", torch.cuda.get_device_name(0))
print("Training triplets:", len(train))
print("Test triplets:", len(test))
print("\nEvaluating before training...")
before = evaluate()
print("BEFORE:", {k: round(v, 4) for k, v in before.items()})

optimizer = torch.optim.AdamW(model.parameters(), lr=2e-5)
batch_size = 8
epochs = 2
margin = 0.2
loader = DataLoader(train.to_dict("records"), batch_size=batch_size, shuffle=True)
total_steps = len(loader) * epochs
step = 0

for epoch in range(epochs):
    total_loss = 0.0
    for batch in loader:
        optimizer.zero_grad(set_to_none=True)

        def embed(texts):
            features = model.tokenize([str(x) for x in texts])
            features = {k: v.to(device) for k, v in features.items() if torch.is_tensor(v)}
            output = model(features)["sentence_embedding"]
            return F.normalize(output.float(), p=2, dim=1)

        anchor = embed(batch["anchor"])
        positive = embed(batch["positive"])
        negative = embed(batch["negative"])

        pos_sim = (anchor * positive).sum(dim=1)
        neg_sim = (anchor * negative).sum(dim=1)
        loss = F.relu(neg_sim - pos_sim + margin).mean()

        if not torch.isfinite(loss):
            raise RuntimeError("Non-finite loss detected; stopping training.")

        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()

        total_loss += loss.item()
        step += 1
        if step % 25 == 0 or step == total_steps:
            print(f"Epoch {epoch+1}/{epochs} | Step {step}/{total_steps} "
                  f"| Loss {loss.item():.4f}")

    print(f"Epoch {epoch+1} average loss: {total_loss/len(loader):.4f}")

print("\nEvaluating after training...")
after = evaluate()
print("AFTER:", {k: round(v, 4) for k, v in after.items()})

OUT.parent.mkdir(parents=True, exist_ok=True)
model.save(str(OUT))
print("\nSAVED MODEL:", OUT)
print("Accuracy change (percentage points):",
      round(after["accuracy"] - before["accuracy"], 2))
print("Margin change:", round(after["margin"] - before["margin"], 4))
print("SMOKE TEST COMPLETE")


