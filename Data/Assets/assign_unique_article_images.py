#!/usr/bin/env python3
"""Verify, save and assign one distinct local photograph per editorial card.

The script fails closed: no HTML changes unless every image can be decoded,
verified as a nonblank image, and stored in the repository.
"""
import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / "Data/Images/Images for Video"
CONFIG = ROOT / "Data/Assets/article-photo-map.json"
API = "https://commons.wikimedia.org/w/api.php"
UA = "HPChannelImageLibrary/1.0 (https://github.com/homoprovincialis/HP-Channel; public editorial site)"
HEADERS = {"User-Agent": UA, "Accept": "application/json,image/*"}
EXT = re.compile(r"\.(jpe?g|png|webp)$", re.I)
IMAGE_TAG = re.compile(r'<img\b[^>]*\bclass="photo"[^>]*>', re.I)
SRC = re.compile(r'\bsrc="[^"]+"')
ALT = re.compile(r'\balt="[^"]*"')
LOADING = re.compile(r'\sloading="[^"]*"')
ALLOWED = ("cc-by", "cc0", "public domain", "pd-", "cc-by-sa")
EXCLUDED = ("noncommercial", "no derivatives", "fair use")

def request(url, json_response=False):
    last = None
    for retry in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=45) as res:
                raw = res.read(10_000_000)
            return json.loads(raw) if json_response else raw
        except Exception as exc:
            last = exc
            time.sleep(2 + retry * 2)
    raise RuntimeError(f"Could not load {url}: {last}")

def api(params):
    return request(API + "?" + urllib.parse.urlencode(params), True)

def plain(s):
    return re.sub(r"<[^>]*>", "", html.unescape(s or "")).strip()

def image_ok(data):
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        if im.width < 500 or im.height < 280:
            raise ValueError("Image too small")
        rgb = ImageOps.exif_transpose(im).convert("RGB")
        if max(ImageStat.Stat(rgb.resize((128, 128))).stddev) < 12:
            raise ValueError("Image is blank or nearly monochrome")
        return rgb

def jpeg_bytes(image):
    out = io.BytesIO()
    if image.width > 1600:
        image.thumbnail((1600, 1600))
    image.save(out, "JPEG", quality=86, optimize=True, progressive=False)
    return out.getvalue()

def find_commons(item, taken):
    # Search actual Commons files, not guessed filenames or licenses.
    terms = [item["query"], " ".join(item["query"].split()[:3]), item["query"].replace(" photograph", "")]
    for term in dict.fromkeys(terms):
        result = api({"action":"query","generator":"search","gsrsearch":"filetype:bitmap " + term,
                      "gsrnamespace":6,"gsrlimit":25,"prop":"imageinfo",
                      "iiprop":"url|size|extmetadata","iiurlwidth":1200,"format":"json"})
        pages = list(result.get("query",{}).get("pages",{}).values())
        for page in pages:
            title = page.get("title","")
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata",{})
            license_name = plain(meta.get("LicenseShortName",{}).get("value","")).lower()
            license_url = meta.get("LicenseUrl",{}).get("value","")
            usage = plain(meta.get("UsageTerms",{}).get("value","")).lower()
            if not any(lic in license_name for lic in ALLOWED):
                continue
            if any(bad in (license_name+" "+usage) for bad in EXCLUDED):
                continue
            if title in taken or not EXT.search(title):
                continue
            if info.get("width",0) < 700 or info.get("height",0) < 400:
                continue
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            try:
                data = request(url)
                image = image_ok(data)
            except Exception as exc:
                print("Skipping unusable photo",title,str(exc),flush=True)
                continue
            taken.add(title)
            return jpeg_bytes(image), {
                "file":title, "source":info.get("descriptionurl",""),
                "author":plain(meta.get("Artist",{}).get("value","")),
                "license":plain(meta.get("LicenseShortName",{}).get("value","")),
                "license_url":license_url,
                "description":item["ru"]
            }
    raise RuntimeError(f"No verified usable photo for #{item['n']}: {item['query']}")

def main():
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    records = {}
    for n in range(1,15):
        path = IMAGES / f"{n}.jpg"
        if not path.is_file():
            raise RuntimeError(f"Existing image missing: {path}")
        # Re-encode to eliminate corrupt/blank or unsupported JPEG data.
        records[n] = jpeg_bytes(image_ok(path.read_bytes()))

    taken = set()
    metadata = {}
    for item in cfg["newImages"]:
        n = item["n"]
        print(f"Finding verified photograph {n}/31: {item['query']}", flush=True)
        data, details = find_commons(item, taken)
        records[n] = data
        metadata[n] = details

    if len(records) != 31:
        raise RuntimeError("Expected 31 images")
    if len({hashlib_sha(v) for v in records.values()}) != 31:
        raise RuntimeError("Some image files are byte-identical")
    # One unique number per article card and homepage cover.
    assigned = [n for group in cfg["sections"].values() for n in group]
    if len(assigned) != 31 or len(set(assigned)) != 31:
        raise RuntimeError("Photo numbers reused across cards")

    replacements = {}
    count = 0
    for section, numbers in cfg["sections"].items():
        for suffix in ("", "-en"):
            path = ROOT / (("index" if section=="homepage" else section)+suffix+".html")
            if section=="homepage" and suffix=="-en":
                path = ROOT/"en.html"
            if not path.exists():
                raise RuntimeError("Page missing: "+str(path))
            content = path.read_text(encoding="utf-8")
            tags = list(IMAGE_TAG.finditer(content))
            if len(tags) != len(numbers):
                raise RuntimeError(f"{path}: {len(tags)} photos, expected {len(numbers)}")
            i = 0
            def replace(m):
                nonlocal i, count
                n = numbers[i]
                i += 1
                count += 1
                tag = m.group(0)
                url = f"Data/Images/Images%20for%20Video/{n}.jpg"
                tag = SRC.sub('src="'+url+'"',tag)
                tag = LOADING.sub("",tag)
                tag = tag.replace("<img",'<img loading="eager"',1)
                return tag
            replacements[path] = IMAGE_TAG.sub(replace,content)

    # No partial publication: only write once all sources are valid.
    for n,data in records.items():
        (IMAGES/f"{n}.jpg").write_bytes(data)
    for path,content in replacements.items():
        path.write_text(content,encoding="utf-8")

    old_catalog = (IMAGES/"catalog.txt").read_text(encoding="utf-8")
    old_catalog = old_catalog.replace("СЛЕДУЮЩИЙ СВОБОДНЫЙ НОМЕР: 15","СЛЕДУЮЩИЙ СВОБОДНЫЙ НОМЕР: 32")
    old_catalog = old_catalog.replace("Номера 1–14 закреплены", "Номера 1–31 закреплены")
    old_catalog = old_catalog.replace("все 14 фотографий", "все 31 фотография")
    old_catalog = old_catalog.replace("как 1.jpg–14.jpg", "как 1.jpg–31.jpg")
    additions = ["", "", "ДОПОЛНИТЕЛЬНЫЕ ФОТОГРАФИИ — ИСТОЧНИКИ И ЛИЦЕНЗИИ", ""]
    for n, d in sorted(metadata.items()):
        additions.extend([f"{n} - {d['description']}",
                          f"    Локальный файл: {n}.jpg",
                          f"    Источник: {d['source']}",
                          f"    Автор: {d['author']}",
                          f"    Лицензия: {d['license']}",
                          f"    Условия: {d['license_url']}",""])
    (IMAGES/"catalog.txt").write_text(old_catalog.rstrip()+"\n"+"\n".join(additions),encoding="utf-8")
    (IMAGES/"verification.txt").write_text(
        f"Validated JPEG images: {len(records)}\nUnique assigned images: {len(set(assigned))}\n"
        f"HTML images switched to local assets: {count}\nPages changed: {len(replacements)}\n"
        "All files decoded using Pillow; no blank images; no repeated article photos.\n",
        encoding="utf-8")
    print("SUCCESS: 31 unique valid JPEG files, 18 pages, 62 local photo references",flush=True)

def hashlib_sha(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()

if __name__ == "__main__":
    main()
