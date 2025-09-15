# Bulk WebP Comic Convertor

**Bulk WebP Comic Convertor** is a cross-platform comic batch converter with a simple GUI.  
It supports `.cbz` and `.cbr` archives and multi-threaded image conversion to **WebP**, helping you reduce storage while keeping comics readable.

---

## ✨ Features

- 📂 Batch processing of entire folders of comics  
- 🖼️ Converts images inside `.cbz` and `.cbr` archives to WebP  
- ⚡ Multi-threaded image conversion (uses half or all CPU cores)  
- 🎚️ Adjustable quality settings  
- 📉 Reports before/after file sizes for each comic  

---

<img width="416" height="340" alt="image" src="https://github.com/user-attachments/assets/935eba7a-66cc-4750-8473-edc79f8beaac" />


## 📦 Dependencies

- [Python 3.8+](https://www.python.org/downloads/)  
- [Pillow](https://pypi.org/project/pillow/)  
- [rarfile](https://pypi.org/project/rarfile/)  
- A `rar` or `unrar` binary installed on your system for handling `.cbr` archives  

Install Python dependencies via:

```bash
pip install -r requirements.txt
