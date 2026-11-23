
from pathlib import Path
import mysql.connector
from db_config import DB_CONFIG

BASE = Path(__file__).resolve().parent

TRAFFIC_DIR = (
    BASE / "dataset" / "OrbitFlow_Collection"
    / "Traffic" / "DLR-MVDA"
)

def main():
    if not TRAFFIC_DIR.exists():
        print("Traffic folder not found:", TRAFFIC_DIR)
        return

    images = [
        p for p in TRAFFIC_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png")
    ]

    if not images:
        print("No traffic images found!")
        return

    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()

    added = 0
    skipped = 0

    try:
        for path in sorted(images):
            relative_path = path.relative_to(BASE).as_posix()
            image_name = path.stem

            cur.execute(
                """
                SELECT image_id FROM dataset_images
                WHERE image_name = %s OR image_path = %s
                LIMIT 1
                """,
                (image_name, relative_path)
            )

            if cur.fetchone():
                skipped += 1
                continue

            cur.execute(
                """
                INSERT INTO dataset_images
                (task_id, image_name, image_type, image_path)
                VALUES (NULL, %s, %s, %s)
                """,
                (image_name, "Traffic Dataset (DLR-MVDA)", relative_path)
            )

            added += 1

        conn.commit()

        print("\nTraffic dataset import successful!")
        print("New images added:", added)
        print("Duplicates skipped:", skipped)
        print("Total images found:", len(images))

    except Exception as e:
        conn.rollback()
        print("Import error:", e)

    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
