
from pathlib import Path
import mysql.connector
from db_config import DB_CONFIG

BASE = Path(__file__).resolve().parent
FIRE_DIR = (
    BASE / "dataset" / "OrbitFlow_Collection"
    / "Fire" / "CEMS_Train" / "assembled" / "train"
)
LIMIT = 50

def main():
    if not FIRE_DIR.exists():
        print("Fire dataset folder not found:", FIRE_DIR)
        return

    images = sorted(FIRE_DIR.rglob("*.png"))[:LIMIT]

    if not images:
        print("No PNG images found.")
        return

    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()

    added = 0
    skipped = 0

    try:
        for path in images:
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
                (image_name, "Fire Dataset (CEMS)", relative_path)
            )
            added += 1

        conn.commit()

        print("\nFire dataset import complete!")
        print("New images added:", added)
        print("Existing images skipped:", skipped)
        print("Total selected:", len(images))

    except Exception as e:
        conn.rollback()
        print("Import failed:", e)

    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
