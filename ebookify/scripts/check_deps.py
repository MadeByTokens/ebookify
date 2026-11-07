"""Report which tools the skill can use on this machine. Run with the skill's venv python."""
import importlib
import shutil
import subprocess
import sys

ok = True


def row(name, good, note=""):
    global ok
    print(f"  [{'x' if good else ' '}] {name:<16} {note}")


print(f"python: {sys.executable}")
print("required:")
pandoc = shutil.which("pandoc")
ver = ""
if pandoc:
    ver = subprocess.run([pandoc, "--version"], capture_output=True, text=True).stdout.split("\n")[0]
row("pandoc", bool(pandoc), ver or "MISSING: install pandoc (apt install pandoc / brew install pandoc)")
ok &= bool(pandoc)
for mod, why in [("trafilatura", "web article extraction"), ("pymupdf4llm", "PDF -> markdown"),
                 ("PIL", "images, covers"), ("requests", "downloads"), ("defusedxml", "safe RSS parsing"),
                 ("yt_dlp", "YouTube / podcast download, captions")]:
    try:
        importlib.import_module(mod)
        row(mod, True, why)
    except ImportError:
        row(mod, False, f"MISSING ({why}): run scripts/setup.sh")
        ok = False

print("optional:")
try:
    importlib.import_module("faster_whisper")
    try:
        import ctranslate2
        gpu = ctranslate2.get_cuda_device_count()
    except Exception:  # noqa: BLE001
        gpu = 0
    row("faster_whisper", True, f"local transcription ({'CUDA GPU' if gpu else 'CPU only, slow for long audio'})")
except ImportError:
    row("faster_whisper", False, "no local transcription: only existing captions/transcripts usable")
ff = shutil.which("ffmpeg")
row("ffmpeg", bool(ff), "audio extraction / thumbnail conversion" if ff else "MISSING: needed for Whisper fallback")
mk = shutil.which("marker_single")
row("marker_single", bool(mk), "OCR for scanned PDFs" if mk else "not found: scanned PDFs cannot be OCRed")
ec = shutil.which("epubcheck")
row("epubcheck", bool(ec), "strict EPUB validation" if ec else "not found: build_epub.py does its own basic checks")
sys.exit(0 if ok else 1)
