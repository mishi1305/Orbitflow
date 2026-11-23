
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import mysql.connector
from db_config import DB_CONFIG

BASE_DIR = Path(__file__).resolve().parent

class OrbitFlowImageViewer:
    def __init__(self, root):
        self.root = root
        self.root.title("OrbitFlow - Satellite Imaging Dataset")
        self.root.geometry("1050x780")
        self.photo = None
        self.images = []

        tk.Label(
            root,
            text="OrbitFlow | Satellite Imaging Dataset",
            font=("Arial", 20, "bold")
        ).pack(pady=12)

        self.buttons_frame = tk.Frame(root)
        self.buttons_frame.pack(pady=10)

        self.heading = tk.Label(root, text="Loading images...", font=("Arial", 14))
        self.heading.pack(pady=8)

        self.image_label = tk.Label(root, text="Image preview")
        self.image_label.pack(expand=True, fill=tk.BOTH, padx=15, pady=10)

        self.status = tk.Label(root, text="", anchor="w")
        self.status.pack(fill=tk.X, padx=10, pady=8)

        self.load_from_database()

    def load_from_database(self):
        connection = None
        try:
            connection = mysql.connector.connect(**DB_CONFIG)
            cursor = connection.cursor(dictionary=True)

            cursor.execute("""
                SELECT image_id, image_name, image_type, image_path
                FROM dataset_images
                ORDER BY image_id
            """)

            self.images = cursor.fetchall()
            cursor.close()

            if not self.images:
                self.heading.config(text="No image records found")
                self.status.config(text="dataset_images table is empty.")
                return

            for image in self.images:
                tk.Button(
                    self.buttons_frame,
                    text=image["image_type"],
                    command=lambda item=image: self.show_image(item),
                    padx=10,
                    pady=8
                ).pack(side=tk.LEFT, padx=5)

            self.status.config(
                text=f"Loaded {len(self.images)} image records from MySQL."
            )

            self.show_image(self.images[0])

        except mysql.connector.Error as error:
            messagebox.showerror("Database Error", str(error))
            self.status.config(text="Could not load image records from MySQL.")

        finally:
            if connection and connection.is_connected():
                connection.close()

    def show_image(self, item):
        path = BASE_DIR / Path(item["image_path"])

        if not path.exists():
            messagebox.showerror(
                "Image Not Found",
                f"Database record found, but file is missing:\n{path}"
            )
            return

        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((950, 560), Image.Resampling.LANCZOS)
                self.photo = ImageTk.PhotoImage(img.copy())

            self.heading.config(
                text=f'{item["image_name"]} ({item["image_type"]})'
            )
            self.image_label.config(image=self.photo, text="")
            self.status.config(text=f"Loaded from database: {item['image_path']}")

        except Exception as error:
            messagebox.showerror("Image Error", str(error))


if __name__ == "__main__":
    root = tk.Tk()
    app = OrbitFlowImageViewer(root)
    root.mainloop()
