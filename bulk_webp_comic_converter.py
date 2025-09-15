#!/usr/bin/env python3
import tkinter as tk
from tkinter import ttk, filedialog
from PIL import Image, ImageTk
import zipfile, rarfile, os, tempfile, shutil, subprocess
from concurrent.futures import ThreadPoolExecutor
import queue
import time

MAX_THREADS = os.cpu_count() or 8
THUMB_LIMIT = 10

class ComicConverterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("CBR/CBZ to WebP Converter")
        #self.root.geometry("950x700")
        self.root.minsize(950, 650) 

        self.progress_queue = queue.Queue()
        self.executor = None
        self.comic_progress_bars = {}  # {comic_path: (label, progressbar)}
        self.thumbnails = []

        self.pending_comics = []
        self.active_threads = 0

        self.target_dir = tk.StringVar()
        self.quality = tk.IntVar(value=85)
        self.use_half_cores = tk.BooleanVar(value=False)
        self.is_converting = False

        self.total_comics = 0
        self.completed_comics = 0
        self.overall_label = None

        self.setup_ui()
        self.check_dependencies()
        self.root.after(100, self.check_queue)

    # ---------------- UI ----------------
    def setup_ui(self):
        # Top frame
        top_frame = ttk.Frame(self.root)
        top_frame.pack(fill="x", padx=5, pady=5)

        ttk.Label(top_frame, text="Target Directory:").pack(side="left")
        ttk.Entry(top_frame, textvariable=self.target_dir, width=60).pack(side="left", padx=5)
        ttk.Button(top_frame, text="Browse", command=self.browse_dir).pack(side="left", padx=5)
        ttk.Label(top_frame, text="Quality:").pack(side="left", padx=(10,0))
        ttk.Spinbox(top_frame, from_=1, to=100, textvariable=self.quality, width=5).pack(side="left", padx=5)

        # Thumbnail frame
        thumb_frame = ttk.LabelFrame(self.root, text="Last 10 Thumbnails")
        thumb_frame.pack(fill="x", padx=5, pady=5)
        canvas = tk.Canvas(thumb_frame, height=160)
        canvas.pack(side="left", fill="x", expand=True)
        self.thumb_scroll = ttk.Scrollbar(thumb_frame, orient="horizontal", command=canvas.xview)
        self.thumb_scroll.pack(side="bottom", fill="x")
        canvas.configure(xscrollcommand=self.thumb_scroll.set)
        self.thumb_container = ttk.Frame(canvas)
        canvas.create_window((0,0), window=self.thumb_container, anchor="nw")
        self.thumb_container.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Active conversions frame (with scroll)
        self.active_frame_container = ttk.Frame(self.root)
        self.active_frame_container.pack(fill="both", expand=True, padx=5, pady=5)
        self.active_canvas = tk.Canvas(self.active_frame_container)
        self.active_scroll = ttk.Scrollbar(self.active_frame_container, orient="vertical", command=self.active_canvas.yview)
        self.active_scroll.pack(side="right", fill="y")
        self.active_canvas.pack(side="left", fill="both", expand=True)
        self.active_canvas.configure(yscrollcommand=self.active_scroll.set)
        self.progress_frame = ttk.Frame(self.active_canvas)
        self.active_canvas.create_window((0,0), window=self.progress_frame, anchor="nw")
        self.progress_frame.bind("<Configure>", lambda e: self.active_canvas.configure(scrollregion=self.active_canvas.bbox("all")))

        # Log
        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text = tk.Text(log_frame, height=10)
        self.log_text.pack(fill="both", expand=True)

        # Bottom controls
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(side="bottom",fill="x", padx=5, pady=5)
        ttk.Button(bottom_frame, text="Start Conversion", command=self.start_conversion).pack(side="left", padx=5)
        ttk.Button(bottom_frame, text="Stop Conversion", command=self.stop_conversion).pack(side="left", padx=5)
        ttk.Checkbutton(bottom_frame, text="Use Half Cores", variable=self.use_half_cores).pack(side="left", padx=10)

    # ---------------- Browse ----------------
    def browse_dir(self):
        directory = filedialog.askdirectory()
        if directory:
            self.target_dir.set(directory)

    # ---------------- Start Conversion ----------------
    def start_conversion(self):
        target = self.target_dir.get()
        if not os.path.isdir(target):
            self.log(f"Directory invalid: {target}")
            return

        if self.is_converting:
            self.log("Already converting.")
            return
        
        if self.active_threads > 0 or self.pending_comics:
            self.log("Already convertring, please wait or press stop")
            return

        self.is_converting = True
        max_workers = (MAX_THREADS // 2) if self.use_half_cores.get() else MAX_THREADS
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

        # build list of comics recursively
        self.pending_comics = self.find_comics(target)
        if not self.pending_comics:
            self.log("No CBR/CBZ comics found.")
            self.is_converting = False
            return
        
        self.total_comics = len(self.pending_comics)
        self.completed_comics = 0

        self.log(f"Found {len(self.pending_comics)} comics. Starting conversion...")
        self.update_overall_progress()
        self.start_next_comics()

    # ---------------- Stop Conversion ----------------
    def stop_conversion(self):
        self.is_converting = False
        self.pending_comics.clear()
        self.log("Conversion stopped by user.")

    # ---------------- Manage active threads ----------------
    def start_next_comics(self):
        # Fill available worker slots
        while self.active_threads < (MAX_THREADS // 2 if self.use_half_cores.get() else MAX_THREADS) and self.pending_comics and self.is_converting:
            comic = self.pending_comics.pop(0)
            self.active_threads += 1
            self.create_progress_bar(comic)
            self.executor.submit(self.process_comic, comic)

    # ---------------- Comic processing ----------------
    def process_comic(self, comic_path):
        try:
            base_dir = os.path.dirname(comic_path)
            temp_dir = os.path.join(base_dir, f".{os.path.basename(comic_path)}_extracted_{next(tempfile._get_candidate_names())}")
            os.makedirs(temp_dir, exist_ok=True)
            extract_dir = os.path.join(temp_dir, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
    
            # Measure original file size
            if os.path.exists(comic_path):
                original_size = os.path.getsize(comic_path)
            else:
                original_size = 0
            # ✅ Pre-check for images
            image_files = self.list_images_in_archive(comic_path)
            if not image_files:
                self.progress_queue.put(("log", f"No images found in {os.path.basename(comic_path)}"))
                self.progress_queue.put(("done", comic_path))
                shutil.rmtree(temp_dir, ignore_errors=True)
                return
    
            # ✅ Extract only images
            self.extract_only_images(comic_path, extract_dir, image_files)
    
            # Sort images by filename
            images = sorted([os.path.join(extract_dir, f) for f in image_files])
    
            # Thumbnail first
            try:
                with Image.open(images[0]) as thumb:
                    thumb.thumbnail((100, 150))
                    tk_thumb = ImageTk.PhotoImage(thumb.copy())
                    self.progress_queue.put(("thumbnail", tk_thumb))
            except Exception as e:
                self.progress_queue.put(("log", f"Thumbnail error for {os.path.basename(comic_path)}: {e}"))
    
            # Convert to WebP
            total = len(images)
            for i, img_path in enumerate(images):
                webp_path = os.path.splitext(img_path)[0] + ".webp"
                try:
                    with Image.open(img_path) as im:
                        im.save(webp_path, "WEBP", quality=self.quality.get())
                    os.remove(img_path)
                except Exception as e:
                    self.progress_queue.put(("log", f"Error converting {img_path}: {e}"))
    
                percent = int((i + 1) / total * 100)
                self.progress_queue.put(("progress", comic_path, percent))
    
            # Repack using only WebP files
            new_cbz = os.path.splitext(comic_path)[0] + ".cbz"
            with zipfile.ZipFile(new_cbz, "w", zipfile.ZIP_DEFLATED) as zipf:
                for f in sorted(os.listdir(extract_dir)):
                    if f.lower().endswith(".webp"):
                        zipf.write(os.path.join(extract_dir, f), f)

                    # Measure new file size and compute reduction
            if os.path.exists(new_cbz):
                new_size = os.path.getsize(new_cbz)
                size_diff_kb = (original_size - new_size) / 1024
            else:
                new_size = 0
                size_diff_kb = 0
    
            # Replace original
            if comic_path != new_cbz and os.path.exists(new_cbz):
                os.remove(comic_path)
    
            shutil.rmtree(temp_dir, ignore_errors=True)
            self.progress_queue.put(("log", f"Finished {os.path.basename(comic_path)} | Size reduced: {size_diff_kb:.2f} KB"))
            self.progress_queue.put(("done", comic_path))
    
        except Exception as e:
            self.progress_queue.put(("log", f"Error {os.path.basename(comic_path)}: {e}"))
            self.progress_queue.put(("done", comic_path))
    

    # ---------------- Extraction ----------------
    # ---------------- Extraction / Pre-check ----------------
    def list_images_in_archive(self, archive_path):
        """Return a list of image filenames inside the archive without extracting everything."""
        image_exts = ('.jpg', '.jpeg', '.png')
        images = []

        try:
            if archive_path.lower().endswith('.cbz'):
                with zipfile.ZipFile(archive_path, 'r') as zipf:
                    images = [f for f in zipf.namelist() if f.lower().endswith(image_exts)]
            elif archive_path.lower().endswith('.cbr'):
                try:
                    with rarfile.RarFile(archive_path, 'r') as rarf:
                        images = [f.filename for f in rarf.infolist() if f.filename.lower().endswith(image_exts)]
                except Exception:
                    # fallback: use 7z if rarfile fails
                    subprocess.run(['7z', 'l', archive_path], capture_output=True, text=True)
                    # optional: parse output if you want
            else:
                self.progress_queue.put(("log", f"Unsupported archive type: {archive_path}"))
        except Exception as e:
            self.progress_queue.put(("log", f"Error reading archive {os.path.basename(archive_path)}: {e}"))

        return images

    def extract_only_images(self, archive_path, extract_dir, image_files):
        """Extract only the files in image_files from the archive."""
        try:
            if archive_path.lower().endswith('.cbz'):
                with zipfile.ZipFile(archive_path, 'r') as zipf:
                    for f in image_files:
                        zipf.extract(f, extract_dir)
            elif archive_path.lower().endswith('.cbr'):
                with rarfile.RarFile(archive_path, 'r') as rarf:
                    for f in image_files:
                        rarf.extract(f, extract_dir)
        except Exception as e:
            self.progress_queue.put(("log", f"Extraction error for {os.path.basename(archive_path)}: {e}"))

    def extract_archive(self, archive_path, extract_dir):
        try:
            if archive_path.lower().endswith('.cbz'):
                try:
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extractall(extract_dir)
                    return True
                except zipfile.BadZipFile:
                    # fallback to 7z
                    try:
                        subprocess.run(['7z', 'x', archive_path, f'-o{extract_dir}'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return True
                    except Exception as e:
                        self.progress_queue.put(("log", f"CBZ extraction failed for {os.path.basename(archive_path)}: {e}"))
                        return False
            elif archive_path.lower().endswith('.cbr'):
                try:
                    with rarfile.RarFile(archive_path, 'r') as rar_ref:
                        rar_ref.extractall(extract_dir)
                    return True
                except Exception as e_rar:
                    try:
                        subprocess.run(['unrar', 'x', archive_path, extract_dir], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        return True
                    except Exception as e_unrar:
                        try:
                            subprocess.run(['7z', 'x', archive_path, f'-o{extract_dir}'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            return True
                        except Exception as e_7z:
                            self.progress_queue.put(("log", f"Failed to extract CBR ({os.path.basename(archive_path)}): rarfile:{e_rar} unrar:{e_unrar} 7z:{e_7z}"))
                            return False
            else:
                self.progress_queue.put(("log", f"Unsupported archive type: {archive_path}"))
                return False
        except Exception as e:
            self.progress_queue.put(("log", f"Extraction error for {os.path.basename(archive_path)}: {e}"))
            return False

    # ---------------- Queue handling ----------------
    def check_queue(self):
        try:
            while True:
                msg = self.progress_queue.get_nowait()
                if msg[0] == "log":
                    self.log(msg[1])
                elif msg[0] == "progress":
                    comic, val = msg[1], msg[2]
                    if comic in self.comic_progress_bars:
                        label, bar = self.comic_progress_bars[comic]
                        bar['value'] = val
                elif msg[0] == "thumbnail":
                    self.add_thumbnail(msg[1])
                elif msg[0] == "done":
                    comic = msg[1]
                    self.remove_progress_bar(comic)
                    self.active_threads -= 1
                    self.completed_comics += 1
                    self.update_overall_progress()
                    self.start_next_comics()

                    if self.active_threads == 0 and not self.pending_comics:
                        self.log("All conversions finished")
                        self.total_comics = 0
                        self.completed_comics = 0
                        self.pending_comics = []
        except queue.Empty:
            pass
        self.root.after(100, self.check_queue)

    # ---------------- Progress bars ----------------
    def create_progress_bar(self, comic):
        label = ttk.Label(self.progress_frame, text=os.path.basename(comic))
        label.pack(fill="x")
        bar = ttk.Progressbar(self.progress_frame, length=500, maximum=100)
        bar.pack(fill="x", padx=5, pady=2)
        self.comic_progress_bars[comic] = (label, bar)

        if not self.overall_label:
            self.overall_label = ttk.Label(self.progress_frame, text="")
            self.overall_label.pack(pady=5)

    def update_overall_progress(self):
        if self.overall_label:
            self.overall_label.config(
                text=f"Processed {self.completed_comics} / {self.total_comics}"
            )

    def remove_progress_bar(self, comic):
        if comic in self.comic_progress_bars:
            label, bar = self.comic_progress_bars.pop(comic)
            try:
                label.destroy()
                bar.destroy()
            except Exception:
                pass

    # ---------------- Find comics ----------------
    def find_comics(self, directory):
        result = []
        for root, _, files in os.walk(directory):
            for f in files:
                if f.lower().endswith(('.cbr', '.cbz')):
                    result.append(os.path.join(root, f))
        return result

    # ---------------- Thumbnails ----------------
    def add_thumbnail(self, tk_img):
        label = ttk.Label(self.thumb_container, image=tk_img)
        label.image = tk_img
        label.pack(side="left", padx=2)
        self.thumbnails.append(label)
        while len(self.thumbnails) > THUMB_LIMIT:
            old_label = self.thumbnails.pop(0)
            try:
                old_label.destroy()
            except Exception:
                pass

    # ---------------- Logging ----------------
    def log(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{timestamp}] {msg}\n")
        self.log_text.see("end")

    # ---------------- Dependencies ----------------
    def check_dependencies(self):
        try:
            subprocess.run(['unrar'], capture_output=True)
        except FileNotFoundError:
            try:
                subprocess.run(['7z'], capture_output=True)
            except FileNotFoundError:
                self.log("Warning: Missing unrar or 7zip; some CBR may fail.")


def main():
    root = tk.Tk()
    app = ComicConverterGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
