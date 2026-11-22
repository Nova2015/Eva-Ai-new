import json
import re
from pathlib import Path

nb_path = Path(r"C:\Users\kesha\Downloads\battery-materials-prediction.ipynb")
out_path = Path(r"D:\Eva_Ai_brain\eva_dataset_agent\reports\notebook_code_audit_source.txt")

if not nb_path.exists():
    raise SystemExit(f"BLOCK: Notebook not found: {nb_path}")

nb = json.loads(nb_path.read_text(encoding="utf-8"))
parts = []
symbols = []

for index, cell in enumerate(nb.get("cells", [])):
    if cell.get("cell_type") != "code":
        continue

    source = cell.get("source", [])
    source = "".join(source) if isinstance(source, list) else str(source)

    if not source.strip():
        continue

    matches = re.findall(
        r"(?m)^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)",
        source
    )

    for name in matches:
        symbols.append((index, name))

    parts.append(
        f"\n{'=' * 25}\nCODE CELL {index}\n{'=' * 25}\n{source}\n"
    )

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text("\n".join(parts), encoding="utf-8")

print("NOTEBOOK EXTRACTION COMPLETE")
print("Code cells:", len(parts))
print("Functions/classes:")
for index, name in symbols:
    print(f"  Cell {index}: {name}")
print("Full source:", out_path)
