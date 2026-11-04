#!/usr/bin/env python3
"""Read-only HP Channel site checks. Never downloads or rewrites files."""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = ROOT / "Data/Images/Images for Video"
MAP = ROOT / "Data/Assets/article-photo-map.json"
IMG = re.compile(r'<img\b[^>]*>', re.I | re.S)
SRC = re.compile(r'\bsrc=["\x27]([^"\x27]+)', re.I)
PHOTO = re.compile(r'\bclass=["\x27][^"\x27]*\bphoto\b')
errors = []

def check(condition, message):
    if not condition:
        errors.append(message)

def jpg(path):
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            check(image.format == "JPEG", f"Not a JPEG: {path}")
            check(image.width >= 500 and image.height >= 280, f"Small image: {path}")
            check(image.mode in ("RGB", "L"), f"Unusual image mode: {path}")
    except Exception as e:
        errors.append(f"Invalid image {path}: {e}")

def local_path(page, url):
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or url.startswith("//"):
        return None
    return (page.parent / unquote(parts.path)).resolve()

def main():
    pages = sorted(ROOT.glob("*.html")) + sorted((ROOT / "Articles").rglob("*.html"))
    check(bool(pages), "No HTML pages")
    refs = {}
    for page in pages:
        content = page.read_text(encoding="utf-8")
        check("<html" in content.lower(), f"Invalid HTML: {page}")
        for tag in IMG.findall(content):
            src = SRC.search(tag)
            if not src:
                errors.append(f"Image missing src: {page}")
                continue
            url = src.group(1)
            target = local_path(page, url)
            if target is None:
                errors.append(f"External image dependency: {page}: {url}")
            elif not target.is_relative_to(ROOT):
                errors.append(f"Image escapes repository: {page}: {url}")
            elif not target.is_file():
                errors.append(f"Missing image: {page}: {url}")
            elif target.suffix.lower() == ".jpg":
                refs.setdefault(target, set()).add(page.name)
        for attr in ("href", "src"):
            for url in re.findall(r'\b'+attr+r'=["\x27]([^"\x27]+)', content):
                if url.startswith(("http:", "https:", "//", "mailto:", "tel:", "data:", "#")):
                    continue
                target = local_path(page, url)
                if target is not None and not target.is_file():
                    errors.append(f"Broken local {attr}: {page}: {url}")
    for image in sorted(IMAGE_DIR.glob("*.jpg")):
        jpg(image)
    for image in refs:
        check(image.is_relative_to(IMAGE_DIR), f"Image outside shared library: {image}")
    try:
        mapping = json.loads(MAP.read_text(encoding="utf-8"))["sections"]
        all_ids = [n for ids in mapping.values() for n in ids]
        check(len(all_ids) == len(set(all_ids)), "Photo IDs repeated across article/homepage cards")
        for section, ids in mapping.items():
            for language in ("ru", "en"):
                page = ROOT / (("index.html" if language=="ru" else "en.html") if section=="homepage"
                               else f"{section}{'-en' if language=='en' else ''}.html")
                check(page.is_file(), f"Missing section page: {page}")
                if not page.is_file():
                    continue
                tags = [m for m in IMG.findall(page.read_text(encoding="utf-8")) if PHOTO.search(m)]
                found = []
                for tag in tags:
                    src = SRC.search(tag)
                    if src:
                        m = re.search(r"/(\d+)\.jpg(?:[?#]|$)", src.group(1))
                        if m:
                            found.append(int(m.group(1)))
                check(found == ids, f"Card photo map mismatch: {page.name}: {found} != {ids}")
        for n in all_ids:
            check((IMAGE_DIR / f"{n}.jpg").is_file(), f"Missing mapped photo #{n}")
    except Exception as e:
        errors.append(f"Photo map validation failed: {e}")

    print(f"Checked {len(pages)} HTML pages, {len(refs)} referenced JPGs, "
          f"{len(list(IMAGE_DIR.glob('*.jpg')))} local JPEG files")
    if errors:
        for e in errors:
            print("ERROR:", e)
        sys.exit(1)
    print("PASS: all local links and photos exist, JPEGs decode, no external images or duplicate card assignments")

if __name__ == "__main__":
    main()
