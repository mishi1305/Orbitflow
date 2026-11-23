
from pathlib import Path

import numpy as np
import rasterio
import matplotlib.pyplot as plt

BASE = Path(__file__).resolve().parent
IMAGE_DIR = BASE / "dataset" / "images"
MASK_DIR = BASE / "dataset" / "masks"
OUT_DIR = BASE / "dataset" / "previews"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def stretch_band(band):
    """Stretch pixel values for visual display."""
    band = band.astype(np.float32)
    valid = np.isfinite(band)

    if not valid.any():
        return np.zeros(band.shape, dtype=np.float32)

    low, high = np.percentile(band[valid], [2, 98])
    if high <= low:
        high = low + 1

    result = np.zeros(band.shape, dtype=np.float32)
    result[valid] = np.clip(
        (band[valid] - low) / (high - low), 0, 1
    )
    return result


def save_satellite_image(path, output_path):
    with rasterio.open(path) as src:
        print(f"\nImage: {path.name}")
        print(f"Size: {src.width} x {src.height}")
        print(f"Bands: {src.count}")
        print(f"Data type: {src.dtypes}")

        data = src.read(masked=True).astype(np.float32)
        data = data.filled(np.nan)

        if src.count >= 3:
            # Use the first three bands for a quick preview.
            rgb = np.dstack([
                stretch_band(data[0]),
                stretch_band(data[1]),
                stretch_band(data[2]),
            ])
            plt.imsave(output_path, rgb)
        else:
            plt.imsave(
                output_path,
                stretch_band(data[0]),
                cmap="gray"
            )

    print(f"Saved preview: {output_path}")


def save_mask(path, output_path):
    with rasterio.open(path) as src:
        mask = src.read(1, masked=True)
        mask_data = mask.filled(0)

        print(f"\nMask: {path.name}")
        print(f"Size: {src.width} x {src.height}")
        print("Unique values:", np.unique(mask_data)[:30])

        plt.figure(figsize=(8, 6))
        plt.imshow(mask_data, cmap="viridis", interpolation="nearest")
        plt.colorbar(label="Mask pixel value")
        plt.title(path.name)
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        plt.close()

    print(f"Saved mask preview: {output_path}")


try:
    save_satellite_image(
        IMAGE_DIR / "Spain_7370579_S2Hand.tif",
        OUT_DIR / "satellite_preview.png",
    )

    save_satellite_image(
        IMAGE_DIR / "Spain_7370579_S1Hand.tif",
        OUT_DIR / "sentinel1_preview.png",
    )

    save_mask(
        MASK_DIR / "Spain_7370579_LabelHand.tif",
        OUT_DIR / "flood_mask_preview.png",
    )

    print("\nDone! Open the dataset/previews folder.")

except Exception as error:
    print("\nSomething went wrong:", error)
    print("Check the file paths and Python library installation.")
