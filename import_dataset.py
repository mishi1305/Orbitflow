"""Safe bulk import of GeoTIFF images/masks into the dataset_images table.

Usage (from the project folder):
    py import_dataset.py --dry-run     # show what would happen, change nothing
    py import_dataset.py               # generate previews + insert new records

Layout it scans (anything below dataset/, any depth):
    dataset/images/*.tif   Sentinel-1 ("S1" in name) and Sentinel-2 ("S2" in name)
    dataset/masks/*.tif    flood labels ("Label" in name)
Originals are never modified. Display PNGs go to dataset/previews/<name>_preview.png.
Safe to run repeatedly: a file is skipped if its name or path is already in the table.
No rows are updated, deleted or truncated.
"""
import argparse
from pathlib import Path

import mysql.connector
import numpy as np
import rasterio
from PIL import Image

from db_config import DB_CONFIG

BASE = Path(__file__).resolve().parent


def classify(stem):
    s = stem.upper()
    if "LABEL" in s:
        return "Flood Mask"
    if "S1" in s:
        return "Sentinel-1"
    if "S2" in s:
        return "Sentinel-2"
    return None


def stretch(b):
    ok = np.isfinite(b)
    if not ok.any():
        return np.zeros(b.shape, dtype=np.float32)
    lo, hi = np.percentile(b[ok], [2, 98])
    return np.where(ok, np.clip((b - lo) / ((hi - lo) or 1), 0, 1), 0).astype(np.float32)


def render(path, kind):
    with rasterio.open(path) as src:
        if src.width == 0 or src.height == 0:
            raise ValueError("empty raster")
        d = src.read(masked=True).astype(np.float32).filled(np.nan)
    if kind == "Flood Mask":       # Sen1Floods11: -1 no data, 0 land, 1 water
        m = d[0]
        rgb = np.full(m.shape + (3,), 211, dtype=np.uint8)      # no data / unlabeled: grey
        rgb[m == 0] = (20, 30, 55)
        rgb[m == 1] = (30, 90, 255)
    elif kind == "Sentinel-2":     # true colour B4,B3,B2 when 13 bands, else first three
        idx = [3, 2, 1] if d.shape[0] >= 4 else list(range(min(3, d.shape[0])))
        ch = [stretch(d[i]) for i in idx]
        rgb = (np.dstack(ch if len(ch) == 3 else ch * 3) * 255).astype(np.uint8)
    else:                          # Sentinel-1 radar: first band (VV) greyscale
        g = stretch(d[0])
        rgb = (np.dstack([g, g, g]) * 255).astype(np.uint8)
    return Image.fromarray(rgb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--root", default=str(BASE / "dataset"))
    a = ap.parse_args()
    root, out_dir = Path(a.root), Path(a.root) / "previews"

    files = sorted([p for p in root.rglob("*") if p.suffix.lower() in (".tif", ".tiff")
                    and "previews" not in p.parts])
    print(f"Found {len(files)} GeoTIFF files under {root}")

    cnx = mysql.connector.connect(**DB_CONFIG)
    cur = cnx.cursor()
    cur.execute("SELECT image_name, image_path FROM dataset_images")
    known = cur.fetchall()
    names = {str(n).lower() for n, _ in known}
    paths = {str(p).replace("\\", "/").lower() for _, p in known}
    cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='dataset_images'",
                (DB_CONFIG["database"],))
    cols = {r[0] for r in cur.fetchall()}
    if "region_name" not in cols and not a.dry_run:
        cur.execute("ALTER TABLE dataset_images ADD COLUMN region_name VARCHAR(100) NULL")   # additive only
        cols.add("region_name")

    added = skipped = failed = 0
    for tif in files:
        kind = classify(tif.stem)
        png_rel = (out_dir / f"{tif.stem}_preview.png").relative_to(BASE).as_posix()
        tif_rel = tif.relative_to(BASE).as_posix()
        if kind is None:
            print(f"  skip (unknown type): {tif.name}"); skipped += 1; continue
        if tif.stem.lower() in names or png_rel.lower() in paths or tif_rel.lower() in paths:
            skipped += 1; continue
        region = tif.stem.split("_")[0]
        if a.dry_run:
            print(f"  would add: {tif.stem} [{kind}] region={region}"); added += 1; continue
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            png = BASE / png_rel
            if not png.exists():
                render(tif, kind).save(png)
            fields = {"image_name": tif.stem, "image_type": kind, "image_path": png_rel}
            if "region_name" in cols:
                fields["region_name"] = region
            cur.execute(f"INSERT INTO dataset_images ({','.join(fields)}) VALUES ({','.join(['%s'] * len(fields))})",
                        tuple(fields.values()))
            cnx.commit()
            names.add(tif.stem.lower()); added += 1
            print(f"  added: {tif.stem} [{kind}]")
        except Exception as e:
            cnx.rollback(); failed += 1
            print(f"  FAILED {tif.name}: {e}")
    cnx.close()
    print(f"\nDone. {'Would add' if a.dry_run else 'Added'}: {added} | skipped (already present/unknown): {skipped} | failed: {failed}")


if __name__ == "__main__":
    main()
