#!/usr/bin/env python3
"""Copy the site's existing image sources into its own repository.

Run from the HP-Channel repository root. Update <img> tags ONLY when a
real, validated local file has been saved. Never invent replacement art.
"""
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import URLError, HTTPError
from urllib.parse import urlsplit, unquote, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "Data" / "Images" / "Images for Video"
CATALOG = LIBRARY / "catalog.txt"
REPORT = LIBRARY / "download-report.txt"
USER_AGENT = "Mozilla/5.0 (compatible; HP-Channel-Archiver/1.0; +https://github.com/homoprovincialis/HP-Channel)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8"}
IMAGE_PATTERN = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.I | re.S)
SOURCE_PATTERN = re.compile(r'(?m)^\s*Источник:\s*(https?://\S+)')

def image_key(url):
    u = urlsplit(url)
    host = (u.hostname or "").lower()
    filename = unquote(u.path.rsplit("/", 1)[-1]).replace("_", " ").lower()
    if host.endswith("unsplash.com"):
        return "unsplash:" + filename
    if "wikimedia.org" in host:
        return "commons:" + filename
    return ""

def detect_extension(content):
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None

def fetch(url):
    last_error = "unknown error"
    for i in range(3):
        try:
            request = Request(url, headers=HEADERS)
            with urlopen(request, timeout=45) as response:
                payload = response.read(12 * 1024 * 1024 + 1)
            if len(payload) > 12 * 1024 * 1024:
                raise ValueError("image exceeds 12 MB")
            ext = detect_extension(payload)
            if not ext:
                raise ValueError("response is not a recognized image file")
            if len(payload) < 200:
                raise ValueError("response is too short to be an image")
            return payload, ext
        except (URLError, HTTPError, OSError, ValueError) as exc:
            last_error = str(exc)
            if i < 2:
                time.sleep(2 * (i + 1))
    raise RuntimeError(last_error)

def source_groups():
    raw = CATALOG.read_text(encoding="utf-8")
    matches = list(re.finditer(r'(?m)^(\d+)\s*-\s+', raw))
    entries = {}
    for i, match in enumerate(matches):
        part = raw[match.start() : (matches[i+1].start() if i+1 < len(matches) else len(raw))]
        found = SOURCE_PATTERN.search(part)
        if not found:
            raise RuntimeError("Catalog entry without source: " + match.group(1))
        number = int(match.group(1))
        key = image_key(found.group(1))
        if not key or key in entries:
            raise RuntimeError("Bad or duplicate image source: " + found.group(1))
        entries[key] = (number, found.group(1))
    if len(entries) != 14:
        raise RuntimeError("Expected the 14 approved images in catalog, found " + str(len(entries)))
    return entries

def local_existing(number):
    candidates = [p for p in LIBRARY.glob(str(number) + ".*")
                  if p.suffix.lower() in {".jpg", ".png", ".webp", ".gif"}]
    for path in candidates:
        if detect_extension(path.read_bytes()) is not None:
            return path
    return None

def main():
    sources = source_groups()
    html_files = sorted(ROOT.glob("*.html")) + sorted((ROOT / "Articles").rglob("*.html"))
    text_by_path = {p: p.read_text(encoding="utf-8") for p in html_files}
    seen = {}
    for content in text_by_path.values():
        for match in IMAGE_PATTERN.finditer(content):
            url = match.group(2)
            if not url.startswith(("http://", "https://")):
                continue
            key = image_key(url)
            if not key or key not in sources:
                continue
            seen.setdefault(key, set()).add(url)

    images = {}
    failures = []
    for key, (number, original) in sorted(sources.items(), key=lambda kv: kv[1][0]):
        image = local_existing(number)
        if image is None:
            urls = sorted(seen.get(key, set()), key=lambda u: ("upload.wikimedia.org" in u, "width=900" in u), reverse=True)
            # Wikimedia's direct original is reliable for the previously broken Epicurus image.
            if key == "commons:epicurus bust.jpg":
                urls.insert(0, "https://upload.wikimedia.org/wikipedia/commons/d/d6/Epicurus_bust.jpg")
            if original not in urls:
                urls.append(original)
            # For Commons, also try the original file path with no thumbnail width.
            for candidate in list(urls):
                if "commons.wikimedia.org/wiki/Special:FilePath/" in candidate:
                    plain = candidate.split("?", 1)[0]
                    if plain not in urls:
                        urls.append(plain)
            why = []
            for url in urls:
                try:
                    payload, ext = fetch(url)
                    image = LIBRARY / (str(number) + "." + ext)
                    image.write_bytes(payload)
                    print("Downloaded", image.relative_to(ROOT), len(payload), "bytes")
                    break
                except RuntimeError as exc:
                    why.append(str(exc))
            if image is None:
                failures.append(f"{number}: {original} — {'; '.join(why[-3:])}")
                print("FAILED to download image", number, ":", why[-1] if why else "no usable source")
        if image is not None:
            images[key] = image

    changed_files = []
    replacements = 0
    for path, content in text_by_path.items():
        def replace(match):
            nonlocal replacements
            key = image_key(match.group(2))
            asset = images.get(key)
            if not asset:
                return match.group(0)
            relative = os.path.relpath(asset, path.parent).replace(os.sep, "/")
            url = quote(relative, safe="/")
            replacements += 1
            return match.group(1) + url + match.group(3)

        updated = IMAGE_PATTERN.sub(replace, content)
        if updated != content:
            path.write_text(updated, encoding="utf-8")
            changed_files.append(str(path.relative_to(ROOT)))

    lines = [
        "HP CHANNEL — ПРОВЕРКА ЛОКАЛЬНЫХ ФОТОГРАФИЙ",
        "",
        f"Изображений в каталоге: {len(sources)}",
        f"Файлов реально сохранено: {len(images)}",
        f"Внешних ссылок на изображения заменено: {replacements}",
        "",
    ]
    for key, (number, origin) in sorted(sources.items(), key=lambda kv: kv[1][0]):
        image = images.get(key)
        lines.append(f"{number} — {'СОХРАНЕНО: ' + image.name if image else 'НЕ ЗАГРУЖЕНО'}")
        if not image:
            lines.append("    " + origin)
    lines += ["", "ОШИБКИ", *(failures if failures else ["Нет"])]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Localized {len(images)}/14 files; changed {len(changed_files)} pages; {replacements} image references")
    # Never replace links to absent files; report remaining dependencies accurately.
    return 0

if __name__ == "__main__":
    sys.exit(main())
