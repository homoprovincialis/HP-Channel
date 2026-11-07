#!/usr/bin/env python3
"""Download four distinct Commons photographs, validate them, and link research cards."""
import html
import io
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from PIL import Image, ImageOps, ImageStat

ROOT=Path(__file__).resolve().parents[2]
LIB=ROOT/"Data/Images/Images for Video"
API="https://commons.wikimedia.org/w/api.php"
HEADERS={"User-Agent":"HPChannelResearchPhotoImporter/1.0 (https://github.com/homoprovincialis/HP-Channel)","Accept":"application/json,image/*"}
# Number, title, Wikimedia Commons search, required title words, descriptions.
ITEMS=[
(32,"what-makes-a-person-virtuous","volunteers helping elderly people","volunteer|help|elderly|senior","Добровольцы помогают людям","Volunteers helping other people"),
(33,"can-an-educated-person-be-immoral","Nuremberg trials defendants courtroom","nuremberg","Подсудимые на Нюрнбергском процессе","Defendants at the Nuremberg trials"),
(34,"should-philosophy-change-how-we-live","Raphael School of Athens fresco","school of athens|scuola di atene","Фреска Рафаэля «Афинская школа»","Raphael's School of Athens fresco"),
(35,"can-human-relations-be-entirely-voluntary","volunteer group community cooperation","volunteer|volunteers|community","Группа добровольцев","A group of volunteers"),
]
def request(url):
    last=None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=45) as response:
                return response.read(12_000_000)
        except Exception as e:
            last=e;time.sleep(2*(attempt+1))
    raise RuntimeError(f"Cannot download {url}: {last}")
def api(args):
    return json.loads(request(API+"?"+urllib.parse.urlencode(args)))
def clean(s):
    return re.sub("<[^>]*>","",html.unescape(s or "")).strip()
def choose(n,query,keywords,seen):
    searches=[query," ".join(query.split()[:2]),query.split()[0]]
    for q in searches:
        response=api({"action":"query","generator":"search","gsrsearch":"filetype:bitmap "+q,
                      "gsrnamespace":6,"gsrlimit":50,"prop":"imageinfo","iiprop":"url|size|extmetadata",
                      "iiurlwidth":1200,"format":"json"})
        pages=sorted(response.get("query",{}).get("pages",{}).values(),key=lambda x:x.get("index",999))
        for p in pages:
            title=p.get("title","")
            lower=title.lower()
            if not any(k in lower for k in keywords.split("|")) or title in seen:
                continue
            if not lower.endswith((".jpg",".jpeg",".png",".webp")):continue
            info=(p.get("imageinfo") or [{}])[0]
            meta=info.get("extmetadata",{})
            license=clean(meta.get("LicenseShortName",{}).get("value","")).lower()
            if not any(x in license for x in ("cc-by","cc0","public domain","pd-")):continue
            if info.get("width",0)<700 or info.get("height",0)<400:continue
            url=info.get("thumburl") or info.get("url")
            if not url:continue
            try:
                data=request(url)
                with Image.open(io.BytesIO(data)) as im:
                    im.load()
                    if im.width<700 or im.height<400:continue
                    rgb=ImageOps.exif_transpose(im).convert("RGB")
                    if max(ImageStat.Stat(rgb.resize((100,100))).stddev)<12:continue
                    rgb.thumbnail((1600,1600))
                    b=io.BytesIO();rgb.save(b,format="JPEG",quality=88,progressive=False,optimize=True)
                    payload=b.getvalue()
                    with Image.open(io.BytesIO(payload)) as verify:
                        verify.load()
                        assert verify.format=="JPEG"
            except Exception as e:
                print("Skip",title,e,flush=True);continue
            seen.add(title)
            return payload,{"title":title,"source":info.get("descriptionurl",""),
                            "author":clean(meta.get("Artist",{}).get("value","")),
                            "license":clean(meta.get("LicenseShortName",{}).get("value","")),
                            "license_url":meta.get("LicenseUrl",{}).get("value","")}
    raise RuntimeError(f"No suitable verified Commons photo for {n}: {query}")
def main():
    downloaded={}
    used=set()
    for n,slug,query,keywords,ru,en in ITEMS:
        print("Selecting photo",n,query,flush=True)
        downloaded[n]=(*choose(n,query,keywords,used),slug,ru,en)
    if len(downloaded)!=4:raise RuntimeError("Need four photos")
    changes={}
    for language in ("ru","en"):
        page=ROOT/("research.html" if language=="ru" else "research-en.html")
        content=page.read_text(encoding="utf-8")
        for n,slug,query,keywords,ru,en in ITEMS:
            pattern=r'(<article class="preview-card" id="'+re.escape(slug)+r'">)'
            replacement=(r'\1<img loading="eager" class="photo" src="Data/Images/Images%20for%20Video/'
                         +str(n)+'.jpg" alt="'+html.escape(ru if language=="ru" else en,quote=True)+'">')
            content,num=re.subn(pattern,lambda m:m.group(1)+replacement.replace(r"\1","",1),content)
            if num!=1:raise RuntimeError(f"Expected exactly one card {slug} in {page.name}, found {num}")
        changes[page]=content
    for n,(data,meta,slug,ru,en) in downloaded.items():
        (LIB/f"{n}.jpg").write_bytes(data)
        for language in ("ru","en"):
            page=ROOT/"Articles"/(slug+("-en" if language=="en" else "")+".html")
            content=page.read_text(encoding="utf-8")
            alt=html.escape(ru if language=="ru" else en,quote=True)
            marker='<h1 class="page-heading">'
            if content.count(marker)!=1:raise RuntimeError(f"Bad heading {page}")
            content=content.replace(marker,'<img loading="eager" class="photo" src="../Data/Images/Images%20for%20Video/'+str(n)+'.jpg" alt="'+alt+'">'+marker,1)
            changes[page]=content
    for path,content in changes.items():path.write_text(content,encoding="utf-8")
    catalog=LIB/"catalog.txt"
    current=catalog.read_text(encoding="utf-8")
    lines=["","", "ФОТОГРАФИИ ДЛЯ ЧЕТЫРЁХ ИССЛЕДОВАНИЙ", ""]
    for n,(data,meta,slug,ru,en) in downloaded.items():
        lines += [f"{n} - {ru}",f"    Локальный файл: {n}.jpg",
                  f"    Оригинал: {meta['title']}",f"    Источник: {meta['source']}",
                  f"    Автор: {meta['author']}",f"    Лицензия: {meta['license']}",
                  f"    Условия: {meta['license_url']}",""]
    current=re.sub(r"СЛЕДУЮЩИЙ СВОБОДНЫЙ НОМЕР:\s*\d+","СЛЕДУЮЩИЙ СВОБОДНЫЙ НОМЕР: 36",current)
    catalog.write_text(current.rstrip()+"\n"+"\n".join(lines),encoding="utf-8")
    print("SUCCESS: 4 distinct local JPEGs, 8 article pages, 2 research pages",flush=True)
if __name__=="__main__":main()
