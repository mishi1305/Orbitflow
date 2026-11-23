
from pathlib import Path
from PIL import Image
import matplotlib.pyplot as plt

BASE = Path(__file__).resolve().parent

FIRE_DIR = (
    BASE / "dataset" / "OrbitFlow_Collection"
    / "Fire" / "CEMS_Train" / "assembled" / "train"
)

images = sorted(FIRE_DIR.rglob("*.png"))[:6]

if not images:
    print("No Fire PNG images found!")
    exit()

fig, axes = plt.subplots(2, 3, figsize=(15, 9))
axes = axes.flatten()

for ax, path in zip(axes, images):
    img = Image.open(path).convert("RGB")
    img.thumbnail((600, 600))

    ax.imshow(img)
    ax.set_title(path.stem[:35], fontsize=9)
    ax.axis("off")

for ax in axes[len(images):]:
    ax.axis("off")

plt.suptitle("OrbitFlow - Fire Dataset (CEMS) Preview", fontsize=16)
plt.tight_layout()
plt.show()
