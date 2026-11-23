from pathlib import Path

base = Path("dataset/OrbitFlow_Collection/Fire/CEMS_Train")

output_folder = base / "assembled"
output_folder.mkdir(parents=True, exist_ok=True)

output_file = output_folder / "train.tar.gz"

# Find parts recursively, including data/train/
parts = sorted(
    base.rglob("train.tar.*.gz.part"),
    key=lambda p: p.name
)

if len(parts) != 11:
    print(f"Expected 11 parts, found {len(parts)}")
    for p in parts:
        print(p)
    raise SystemExit("Merge cancelled.")

print(f"Found {len(parts)} parts.")

# Check numbering
expected = [f"train.tar.{i:04d}.gz.part" for i in range(11)]
found = [p.name for p in parts]

if found != expected:
    raise SystemExit("Part names/order do not match. Merge cancelled.")

print("Starting merge...\n")

with output_file.open("wb") as merged:
    for part in parts:
        print(f"Merging {part.name}")

        with part.open("rb") as source:
            while True:
                chunk = source.read(8 * 1024 * 1024)
                if not chunk:
                    break
                merged.write(chunk)

print("\nMerge complete!")
print(f"Output: {output_file}")
print(f"Size: {output_file.stat().st_size / (1024**3):.2f} GB")