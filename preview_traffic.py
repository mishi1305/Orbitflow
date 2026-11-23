
from pathlib import Path
from PIL import Image
import matplotlib.pyplot as plt

BASE = Path(__file__).resolve().parent

TRAFFIC_DIR = (
    BASE / "dataset" / "OrbitFlow_Collection"
    / "Traffic" / "DLR-MVDA"
)

images = sorted([
    p for p in TRAFFIC_DIR.rglob("*")
    if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png")
])[:6]

if not images:
    print("No images found")
    exit()

fig, axes = plt.subplots(2, 3, figsize=(15, 9))
axes = axes.flatten()

for ax, path in zip(axes, images):
    img = Image.open(path).convert("RGB")
    img.thumbnail((600, 600))
    ax.imshow(img)
    ax.set_title(path.name[:30], fontsize=8)
    ax.axis("off")

for ax in axes[len(images):]:
    ax.axis("off")

plt.suptitle("OrbitFlow - Traffic Dataset Preview", fontsize=16)
plt.tight_layout()
plt.show()
