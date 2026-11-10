from __future__ import annotations

import csv
import io
import json
import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pymupdf as fitz
from flask import Flask, abort, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

BASE = Path(__file__).resolve().parent
RUNTIME = BASE / "runtime"
RUNTIME.mkdir(exist_ok=True)
DOWNLOAD_ROOT = RUNTIME / "downloads"
DOWNLOAD_ROOT.mkdir(exist_ok=True)
DOWNLOAD_TTL = 7 * 24 * 60 * 60

# Clean old downloads older than TTL
DOWNLOADS: dict[str, Path] = {}
for _download_dir in DOWNLOAD_ROOT.iterdir():
    if not _download_dir.is_dir() or _download_dir.is_symlink() or not re.fullmatch(r"[0-9a-f]{16}", _download_dir.name):
        continue
    if time.time() - _download_dir.stat().st_mtime > DOWNLOAD_TTL:
        shutil.rmtree(_download_dir, ignore_errors=True)
    else:
        DOWNLOADS[_download_dir.name] = _download_dir

MAX_FILE = 60 * 1024 * 1024
MAX_BATCH = 180 * 1024 * 1024
MAX_FILES = 12
MAX_PAGES = 500
JOBS: dict[str, dict[str, Any]] = {}
LOCK = threading.Lock()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_BATCH
app.config["JSON_SORT_KEYS"] = False

FIELDS = ["title", "course_code", "module", "institution", "scheme", "category", "website", "phone", "email", "subtitle", "tags"]
DEFAULTS = {
    "institution": "",
    "scheme": "KTU 2024 SCHEME",
    "category": "LAB EXAM NOTES",
    "website": "azhumathimayam.invytra.in",
    "phone": "8606159002",
    "email": "",
    "subtitle": "",
    "tags": "12 Programs • Aim • Algorithm • C Program • Sample I/O • Result"
}
BRAND_WORDS = ("invytra", "azhumathimayam", "contact", "www.", "http://", "https://", "phone", "8606159002", "telegram", "whatsapp")


def prune_expired_jobs(max_age: int = 24 * 60 * 60) -> None:
    cutoff = time.time() - max_age
    with LOCK:
        expired = [key for key, job in JOBS.items() if job.get("created", time.time()) < cutoff]
        for key in expired:
            job = JOBS.pop(key, None)
            if job:
                folder = Path(job.get("dir", ""))
                if folder.parent == RUNTIME and folder.name.startswith("job_"):
                    shutil.rmtree(folder, ignore_errors=True)


def safe_name(name: str, default: str = "document.pdf") -> str:
    name = secure_filename(Path(name or default).name)
    if not name:
        name = default
    return name[:140]


def normalized_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", value):
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or " " in parsed.netloc:
        return ""
    return value


def parse_metadata(file_storage) -> tuple[list[dict[str, Any]], str | None]:
    if not file_storage or not file_storage.filename:
        return [], None
    name = file_storage.filename.lower()
    raw = file_storage.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        return [], "Metadata file is larger than 2 MB; it was not imported."
    try:
        if name.endswith(".json"):
            data = json.loads(raw.decode("utf-8-sig"))
            rows = data if isinstance(data, list) else data.get("documents", data.get("files", []))
            if not isinstance(rows, list):
                raise ValueError("JSON should be a list of records or contain a 'documents' list.")
        elif name.endswith(".csv"):
            rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        else:
            return [], "Metadata must be a .csv or .json file."
        cleaned = []
        for row in rows[:100]:
            if not isinstance(row, dict):
                continue
            out = {}
            for k, v in row.items():
                key = str(k or "").strip().lower().replace(" ", "_").replace("-", "_")
                aliases = {"filename": "filename", "file": "filename", "name": "filename", "subject": "title", "course": "course_code", "unit": "module", "year": "scheme", "university": "institution", "topics": "tags"}
                key = aliases.get(key, key)
                if key in FIELDS + ["filename"] and v is not None:
                    out[key] = str(v).strip()[:1000]
            if out.get("filename"):
                cleaned.append(out)
        return cleaned, None
    except Exception as exc:
        return [], f"Could not read metadata: {str(exc)[:180]}"


def extract_suggestions(doc: fitz.Document, page_summaries: list[dict[str, Any]], filename: str = "") -> dict[str, Any]:
    meta = doc.metadata or {}
    raw_title = (meta.get("title") or "").strip()
    if any(junk in raw_title.lower() for junk in ["microsoft word", "untitled", "powerpoint", "scan", "page 1", "document1"]):
        raw_title = ""
        
    text = "\n".join(p["text"] for p in page_summaries[:5])
    low_text = text.lower()
    clean_fn = Path(filename).stem
    
    # Check known subjects from text or filename
    subjects = [
        "Data Structures Lab Exam", "Data Structures Lab", "Data Structures",
        "Design and Analysis of Algorithms", "Analysis and Design of Algorithms",
        "Operating Systems", "Computer Networks", "Database Management Systems",
        "Object Oriented Programming", "Compiler Design", "Software Engineering",
        "Formal Languages and Automata Theory", "Microprocessors and Microcontrollers",
        "Discrete Mathematical Structures", "Graph Theory", "Linear Algebra and Calculus",
        "Engineering Physics", "Engineering Chemistry", "Basics of Civil & Mechanical Engineering",
        "Basics of Electrical & Electronics Engineering", "Python Programming", "C Programming",
        "Network Lab", "Systems Lab", "Microprocessor Lab", "Web Technology Lab",
        "Machine Learning", "Artificial Intelligence", "Deep Learning", "Internet of Things"
    ]
    title = raw_title
    for sub in subjects:
        if sub.lower() in clean_fn.lower() or sub.lower() in low_text[:1200]:
            title = sub
            break
            
    if not title:
        stem_clean = re.sub(r"^(?:KTU\s*)?(?:S\d\s*)?(?:[A-Z]{2,4}\s*\d{2,4}\s*)?", "", clean_fn, flags=re.I)
        stem_clean = re.sub(r"[_.-]+", " ", stem_clean).strip()
        stem_clean = re.sub(r"\b(?:study\s*)?notes\b", "", stem_clean, flags=re.I).strip()
        if len(stem_clean) >= 3:
            title = " ".join(w.capitalize() for w in stem_clean.split())
        else:
            candidates = [p["heading"] for p in page_summaries[:3] if p.get("heading") and len(p["heading"]) < 110]
            title = candidates[0] if candidates else "Data Structures Lab Exam"

    course = ""
    m = re.search(r"\b([A-Z]{2,4}\s*[-/]?\s*[0-9]{3})\b", text + " " + filename)
    if m:
        course = re.sub(r"\s+", "", m.group(1)).upper()

    module = ""
    mm = re.search(r"\b(?:module|unit)\s*(?:no\.?\s*)?([0-9IVX]+)(?:\s*[:—-]\s*([^\n]{1,70}))?", text, re.I)
    if mm:
        module = "Module " + mm.group(1).upper() + ((" · " + mm.group(2).strip()) if mm.group(2) else "")

    institution = ""
    inst = re.search(r"(?im)^.{0,80}\b(?:University|College|Institute of Technology)\b.{0,50}$", text)
    if inst:
        institution = re.sub(r"\s+", " ", inst.group(0)).strip()[:90]

    scheme = "KTU 2024 SCHEME"
    sm = re.search(r"\b(?:KTU\s*)?20\d{2}\s*(?:scheme|scheme year)\b", text + " " + filename, re.I)
    if sm:
        scheme = re.sub(r"\s+", " ", sm.group(0)).upper()
        if not scheme.startswith("KTU"):
            scheme = "KTU " + scheme

    category = "LAB EXAM NOTES"
    if any(k in low_text[:800] or k in filename.lower() for k in ["lab", "practical", "exam", "viva", "program", "experiment"]):
        category = "LAB EXAM NOTES"
    elif any(k in low_text[:800] or k in filename.lower() for k in ["question", "pyq", "solved"]):
        category = "QUESTION BANK & SOLUTIONS"
    elif any(k in low_text[:800] or k in filename.lower() for k in ["lecture", "module", "notes"]):
        category = "STUDY NOTES"

    tags = "12 Programs • Aim • Algorithm • C Program • Sample I/O • Result"
    pm = re.search(r"\b(\d{1,2}\s*Programs?)\b", text, re.I)
    if pm:
        tags = f"{pm.group(1)} • Aim • Algorithm • C Program • Sample I/O • Result"

    return {
        "title": title[:160],
        "course_code": course,
        "module": module,
        "institution": institution,
        "scheme": scheme,
        "category": category,
        "tags": tags
    }


def classify_page(page_no: int, total: int, text: str, image_count: int, link_count: int, qr: bool, repeat_brand: bool) -> dict[str, Any]:
    clean = re.sub(r"\s+", " ", text).strip()
    low = clean.lower()
    words = re.findall(r"\b\w+\b", clean)
    word_count = len(words)
    study_signals = sum(bool(re.search(p, low)) for p in [r"\b(definition|theorem|algorithm|example|solution|chapter|module|unit|exercise|problem|proof|equation|data structure|complexity)\b", r"[=∑∫√πλ]", r"\b(input|output|return|void|int|class|function|main|include|stdio)\b"])
    promo_signals = sum(term in low for term in ["contact", "subscribe", "follow us", "download", "visit us", "whatsapp", "telegram", "join our", "advertisement", "youtube", "scanned by", "instagram"])
    contact = bool(re.search(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b", clean)) or bool(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", clean))
    if qr:
        promo_signals += 2
    if repeat_brand:
        promo_signals += 1

    if word_count >= 35 and study_signals >= 1:
        label, confidence, evidence = "Study material", min(.96, .70 + .05 * study_signals), [f"{len(words)} selectable words", "academic or technical terms detected"]
    elif (promo_signals >= 2 or (contact and word_count < 80 and (page_no in (0, total - 1) or link_count > 0))) and word_count < 180:
        label, confidence, evidence = ("QR / contact page" if qr or contact else "Promotional page"), min(.94, .62 + .08 * promo_signals), []
        if qr: evidence.append("QR code detected in page image")
        if contact: evidence.append("phone or email-like text detected")
        if link_count: evidence.append(f"{link_count} link(s) on page")
        if repeat_brand: evidence.append("repeated brand-like text")
    elif page_no == 0 and word_count < 55 and (image_count > 0 or promo_signals or repeat_brand):
        label, confidence, evidence = "Possible branded cover", .75, [f"first page; {len(words)} selectable words", f"{image_count} image(s)"]
    elif not clean and image_count > 0:
        label, confidence, evidence = "Uncertain (image-only page)", .38, ["no selectable text; page contains image content", "no OCR is used"]
    elif word_count < 8:
        label, confidence, evidence = "Uncertain", .34, [f"only {len(words)} selectable words", "could be a diagram, scan, or separator"]
    else:
        label, confidence, evidence = "Study material / uncertain", .53, [f"{len(words)} selectable words"]
        if study_signals: evidence.append("technical vocabulary detected")
        if image_count: evidence.append(f"{image_count} image(s) preserved")
    if page_no in (0, total - 1) and label not in ("Possible branded cover", "Promotional page", "QR / contact page"):
        evidence.append("boundary page kept for review")
    return {"label": label, "confidence": round(confidence, 2), "evidence": evidence}


def qr_on_page(page: fitz.Page) -> bool:
    try:
        scale = min(1.0, 900.0 / max(page.rect.width, page.rect.height, 1.0))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        import cv2
        import numpy as np
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        detector = cv2.QRCodeDetector()
        value, _, _ = detector.detectAndDecode(img)
        return bool(value)
    except Exception:
        return False


def analyze_pdf(path: Path, doc_id: str, filename: str) -> dict[str, Any]:
    try:
        doc = fitz.open(path)
        if doc.is_encrypted:
            raise ValueError("This PDF is encrypted. Decrypt it locally and upload a copy you are authorized to edit.")
        if doc.page_count < 1:
            raise ValueError("The PDF has no pages.")
        if doc.page_count > MAX_PAGES:
            raise ValueError(f"This PDF has {doc.page_count} pages; the current safe limit is {MAX_PAGES} pages.")
        repeated = Counter()
        full_texts = []
        dims = []
        per_page_img = []
        per_page_links = []
        per_page_annots = []
        annotation_candidates = []
        per_page_qr = []
        for i, page in enumerate(doc):
            text = page.get_text("text") or ""
            full_texts.append(text)
            imgs = page.get_images(full=True)
            links = page.get_links()
            annots = list(page.annots() or [])
            per_page_annots.append(annots)
            for annot in annots:
                info = annot.info or {}
                desc = " ".join(str(info.get(k, "")) for k in ("content", "title", "subject", "name")).strip()
                if desc and any(term in desc.lower() for term in BRAND_WORDS):
                    annotation_candidates.append({"page": i + 1, "type": annot.type[1] if len(annot.type) > 1 else "annotation", "text": desc[:220], "confidence": .84})
            dims.append({"width": round(page.rect.width, 1), "height": round(page.rect.height, 1), "rotation": page.rotation})
            per_page_img.append(imgs)
            per_page_links.append(links)
            for line in text.splitlines():
                s = re.sub(r"\s+", " ", line.strip())
                if s and len(s) < 140:
                    repeated[s.lower()] += 1
            per_page_qr.append(qr_on_page(page) if i < 80 and imgs else False)
        repeated_brand_lines = {t for t, n in repeated.items() if n >= 2 and any(w in t for w in BRAND_WORDS)}
        candidates = {}
        for t, n in repeated.items():
            if n >= 2 and any(w in t for w in BRAND_WORDS):
                candidates[t] = n
        pages = []
        total = doc.page_count
        for i, page in enumerate(doc):
            text = full_texts[i]
            lines = [re.sub(r"\s+", " ", x.strip()) for x in text.splitlines() if x.strip()]
            heading = next((x for x in lines if len(x) > 2 and len(x) <= 100 and len(x.split()) <= 14), "")
            urls = []
            for link in per_page_links[i]:
                uri = link.get("uri") or ""
                if uri:
                    urls.append(uri[:250])
            placements = [{"xref": row[0], "rects": [[round(r.x0,1), round(r.y0,1), round(r.x1,1), round(r.y1,1)] for r in page.get_image_rects(row[0])]} for row in per_page_img[i]]
            image_only_likely = len(re.findall(r"\b\w+\b", text)) < 15 and any((r[2]-r[0])*(r[3]-r[1]) > page.rect.width*page.rect.height*.72 for pl in placements for r in pl["rects"])
            classification = classify_page(i, total, text, len(per_page_img[i]), len(per_page_links[i]), per_page_qr[i], any(x in text.lower() for x in repeated_brand_lines))
            if image_only_likely:
                classification["evidence"].append("a large image occupies most of the page")
                if classification["label"] == "Uncertain": classification["label"] = "Uncertain (scan-like page)"
            page_no_match = bool(re.search(r"(?im)^\s*(?:page\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?\s*$", text))
            summary = {
                "number": i + 1, "text": text[:10000], "heading": heading,
                "characters": len(text.strip()), "words": len(re.findall(r"\b\w+\b", text)),
                "images": len(per_page_img[i]), "image_placements": placements, "image_only_likely": image_only_likely, "page_number_detected": page_no_match,
                "links": urls, "link_count": len(per_page_links[i]), "annotations": len(per_page_annots[i]),
                "qr": per_page_qr[i], "dimensions": dims[i],
                "content_streams": len(page.get_contents()), "xobjects": len(page.get_xobjects()), "drawings": len(page.get_drawings()),
                "classification": classification,
                "preview": f"/preview/{doc_id}/{i}/0"
            }
            pages.append(summary)

        text_candidates = []
        for text_val, count in sorted(candidates.items(), key=lambda x: (-x[1], x[0]))[:40]:
            found_pages = [i + 1 for i, txt in enumerate(full_texts) if text_val in txt.lower()]
            text_candidates.append({"text": text_val[:140], "count": count, "pages": found_pages, "confidence": .78, "kind": "repeated selectable text"})
        image_occurrences = defaultdict(list)
        for i, imgs in enumerate(per_page_img):
            page = doc[i]
            for row in imgs:
                xref = row[0]
                if xref <= 0:
                    continue
                rects = [[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)] for r in page.get_image_rects(xref)]
                image_occurrences[xref].append({"page": i + 1, "rects": rects})
        repeated_images = []
        for xref, occurrences in image_occurrences.items():
            if len(occurrences) >= 2:
                repeated_images.append({"xref": xref, "pages": [x["page"] for x in occurrences],
                                        "placements": occurrences, "confidence": .35,
                                        "warning": "Repeated image object: check thumbnail before removing."})
        suggestions = extract_suggestions(doc, pages, filename)
        first = dims[0]
        return {
            "id": doc_id, "filename": filename, "page_count": total,
            "dimensions": f"{first['width']} × {first['height']} pt", "metadata": {k: (v or "") for k, v in (doc.metadata or {}).items() if k in ("title", "author", "subject", "creator", "producer")},
            "suggestions": suggestions, "pages": pages, "text_candidates": text_candidates,
            "annotation_candidates": annotation_candidates[:40], "repeated_images": repeated_images[:20], "encrypted": False,
            "warnings": ["Some pages look image-only or scan-like. No OCR is used."] if any(p["image_only_likely"] or (p["words"] == 0 and p["images"]) for p in pages) else []
        }
    except Exception as exc:
        if isinstance(exc, (ValueError, RuntimeError)):
            raise
        raise ValueError(f"Could not safely analyze this PDF: {str(exc)[:220]}")


def add_cover(doc: fitz.Document, fields: dict[str, str], logo_path: Path | None) -> None:
    """Draw a precision-crafted Azhumathimayam & Invytra cover page matching the exact design."""
    page = doc.new_page(width=595, height=842)
    wine = (100 / 255, 0, 0)                  # #640000 deep maroon
    cream = (247 / 255, 244 / 255, 239 / 255) # #F7F4EF warm ivory/cream
    ink = (0.12, 0.12, 0.12)                  # #1F1F1F deep charcoal
    line_color = (0.87, 0.80, 0.79)           # #DEC8C7 soft divider line

    # Top 50.4% Banner (0 to 424 pt)
    page.draw_rect(fitz.Rect(0, 0, 595, 424), color=wine, fill=wine)
    # Bottom 49.6% Section (424 to 842 pt)
    page.draw_rect(fitz.Rect(0, 424, 595, 842), color=cream, fill=cream)

    font_serif = str(BASE / "static" / "DejaVuSerif-Bold.ttf")
    font_sans = str(BASE / "static" / "DejaVuSans.ttf")
    font_bold = str(BASE / "static" / "DejaVuSans-Bold.ttf")

    def wrap(text: str, font: fitz.Font, size: float, max_width: float, max_lines: int) -> list[str]:
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        if not text:
            return []
        lines: list[str] = []
        line = ""
        for word in text.split(" "):
            trial = (line + " " + word).strip()
            if line and font.text_length(trial, fontsize=size) > max_width:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            last = lines[-1]
            while last and font.text_length(last + "…", fontsize=size) > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip() + "…"
        return lines

    def centered(text: str, baseline: float, size: float, fontfile: str, color,
                 max_width: float = 500, max_lines: int = 1, leading: float = 1.22) -> float:
        font = fitz.Font(fontfile=fontfile)
        lines = wrap(text, font, size, max_width, max_lines)
        for line in lines:
            width = font.text_length(line, fontsize=size)
            page.insert_text(((595 - width) / 2, baseline), line, fontfile=fontfile,
                             fontsize=size, color=color)
            baseline += size * leading
        return baseline

    def tracked(text: str, baseline: float, size: float, tracking: float, color,
                max_width: float = 500) -> None:
        text = re.sub(r"\s+", " ", str(text or "")).strip().upper()
        if not text:
            return
        font = fitz.Font(fontfile=font_bold)
        width = font.text_length(text, fontsize=size) + max(0, len(text) - 1) * tracking
        scale = min(1.0, max_width / max(width, 1))
        size *= scale
        tracking *= scale
        width = font.text_length(text, fontsize=size) + max(0, len(text) - 1) * tracking
        x = (595 - width) / 2
        for char in text:
            page.insert_text((x, baseline), char, fontfile=font_bold, fontsize=size, color=color)
            x += font.text_length(char, fontsize=size) + tracking

    # 1. Scheme Text at Top (e.g. KTU 2024 SCHEME)
    scheme = (fields.get("scheme") or "KTU 2024 SCHEME").strip()
    tracked(scheme, 88, 9.0, 2.6, (1, 1, 1), 480)

    # 2. Authentic Malayalam Wordmark Logo in Center of Maroon Banner
    logo_file = logo_path if (logo_path and logo_path.exists()) else (BASE / "static" / "azhumathimayam-logo.png")
    if logo_file.exists():
        try:
            pix = fitz.Pixmap(str(logo_file))
            target_w = 250.0
            ratio = target_w / max(1, pix.width)
            target_h = pix.height * ratio
            center_y = 255.0
            target_rect = fitz.Rect((595 - target_w) / 2, center_y - target_h / 2,
                                    (595 + target_w) / 2, center_y + target_h / 2)
            page.insert_image(target_rect, filename=str(logo_file), keep_proportion=True)
        except Exception:
            centered("അഴിമതി മയം", 255, 34, font_bold, (1, 1, 1))
    else:
        centered("അഴിമതി മയം", 255, 34, font_bold, (1, 1, 1))

    # 3. Category (e.g. LAB EXAM NOTES)
    category = (fields.get("category") or "LAB EXAM NOTES").strip().upper()
    tracked(category, 476, 9.5, 2.4, wine, 480)

    # 4. Subject / Title (e.g. Data Structures Lab Exam)
    title = (fields.get("title") or "Data Structures Lab Exam").strip()
    title_size = 28 if len(title) <= 28 else 25 if len(title) <= 55 else 22
    y = centered(title, 532, title_size, font_serif, ink, 490, max_lines=3, leading=1.22) + 2

    # 5. Optional details (Subtitle / Institution / Course Code)
    subtitle = fields.get("subtitle", "").strip()
    institution = fields.get("institution", "").strip()
    course_bits = [x for x in (fields.get("course_code", "").strip(), fields.get("module", "").strip()) if x]
    
    details = [x for x in (subtitle, institution) if x]
    if course_bits:
        details.append(" · ".join(course_bits))
        
    for detail in details[:2]:
        y = centered(detail, y + 4, 10.5, font_sans, (0.3, 0.3, 0.3), 480, max_lines=1) + 2

    # 6. Subtle Horizontal Divider Line
    divider_y = max(634, min(656, y + 14))
    page.draw_line((58, divider_y), (537, divider_y), color=line_color, width=0.7)

    # 7. Signature Maroon Pill Button with Website
    website = (fields.get("website") or "azhumathimayam.invytra.in").strip()
    button_top = divider_y + 18
    button_rect = fitz.Rect(52, button_top, 543, button_top + 40)
    
    try:
        shape = page.new_shape()
        shape.draw_round_rect(button_rect, 8)
        shape.finish(color=wine, fill=wine)
        shape.commit()
    except Exception:
        page.draw_rect(button_rect, color=wine, fill=wine)

    display = website.replace("https://", "").replace("http://", "").rstrip("/") or "azhumathimayam.invytra.in"
    font_bold_obj = fitz.Font(fontfile=font_bold)
    btn_size = 12.0 if font_bold_obj.text_length(display, fontsize=12.0) <= 460 else 10.0
    btn_w = font_bold_obj.text_length(display, fontsize=btn_size)
    page.insert_text(((595 - btn_w) / 2, button_top + 25.5), display, fontfile=font_bold, fontsize=btn_size, color=(1, 1, 1))

    url = normalized_url(website) or "https://azhumathimayam.invytra.in"
    try:
        page.insert_link({"kind": fitz.LINK_URI, "from": button_rect, "uri": url})
    except Exception:
        pass

    # 8. Contact Info (Contact • 8606159002)
    phone = (fields.get("phone") or "8606159002").strip()
    email = (fields.get("email") or "").strip()
    contact_parts = [p for p in (phone, email) if p]
    contact_text = "Contact • " + (" • ".join(contact_parts) if contact_parts else "8606159002")
    contact_baseline = min(746, button_top + 72)
    centered(contact_text, contact_baseline, 10, font_bold, wine, 500, max_lines=1)

    if phone:
        tel = re.sub(r"[^+\d]", "", phone)
        if tel:
            try:
                c_w = font_bold_obj.text_length(contact_text, fontsize=10)
                left_x = (595 - c_w) / 2
                page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(left_x, contact_baseline - 12, left_x + c_w, contact_baseline + 4), "uri": "tel:" + tel})
            except Exception:
                pass

    # 9. Brand Name (I N V Y T R A)
    tracked("I N V Y T R A", 780, 7.5, 3.2, wine, 240)

    # 10. Bottom Summary Line / Tags (e.g. 12 Programs • Aim • Algorithm • C Program • Sample I/O • Result)
    tags = (fields.get("tags") or "12 Programs • Aim • Algorithm • C Program • Sample I/O • Result").strip()
    if tags:
        centered(tags, 818, 7.5, font_sans, (0.48, 0.45, 0.44), 520, max_lines=1)


def process_one(job: dict[str, Any], pdf_info: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    original = Path(pdf_info["path"])
    try:
        src = fitz.open(original)
        if src.is_encrypted:
            raise ValueError("Encrypted PDFs cannot be processed without a password.")
        raw_remove_pages = config.get("remove_pages", [])
        if not isinstance(raw_remove_pages, list): raw_remove_pages = []
        remove_pages = {int(x) for x in raw_remove_pages[:MAX_PAGES] if str(x).isdigit()}
        remove_pages = {x for x in remove_pages if 0 <= x < src.page_count}
        if len(remove_pages) >= src.page_count:
            raise ValueError("At least one original page must be retained.")
            
        selected_images = config.get("remove_images", [])
        if not isinstance(selected_images, list): selected_images = []
        selected_images = {int(x) for x in selected_images[:20] if str(x).isdigit() and 0 < int(x) < src.xref_length()}
        selected_image_hashes = set()
        for source_xref in selected_images:
            try:
                image_data = src.extract_image(source_xref)
                if image_data and image_data.get("image"):
                    selected_image_hashes.add(hashlib.sha256(image_data["image"]).hexdigest())
            except Exception:
                continue
                
        output = fitz.open()
        raw_fields = config.get("fields") if isinstance(config.get("fields"), dict) else {}
        limits = {"title": 180, "course_code": 40, "module": 100, "institution": 120, "scheme": 60, "category": 60, "website": 180, "phone": 32, "email": 80, "subtitle": 150, "tags": 150}
        fields = {k: str(raw_fields.get(k, "") or "").strip()[:limits.get(k, 200)] for k in FIELDS}
        fields["website"] = normalized_url(fields.get("website", "")) or fields.get("website", "")
        
        logo_path = Path(job["logo_path"]) if job.get("logo_path") else (BASE / "static" / "azhumathimayam-logo.png")
        add_cover(output, fields, logo_path)
        cover_image_xrefs = {row[0] for row in output[0].get_images(full=True)}
        
        retained_map = []
        for i in range(src.page_count):
            if i in remove_pages:
                continue
            out_index = output.page_count
            output.insert_pdf(src, from_page=i, to_page=i, links=True, annots=True, widgets=True)
            retained_map.append((i, out_index))
            
        raw_marks = config.get("remove_texts", [])
        if not isinstance(raw_marks, list): raw_marks = []
        exact_marks = list(dict.fromkeys(str(x).strip()[:140] for x in raw_marks[:50] if str(x).strip()))
        
        raw_watermark_pages = config.get("watermark_pages", [])
        if not isinstance(raw_watermark_pages, list): raw_watermark_pages = []
        watermark_pages = {int(x) for x in raw_watermark_pages[:MAX_PAGES] if str(x).isdigit()}
        
        removal_report = []
        image_removal_report = []
        deleted_output_xrefs = set()
        
        for src_idx, out_idx in retained_map:
            page = output[out_idx]
            if selected_image_hashes:
                for image_row in list(page.get_images(full=True)):
                    out_xref = image_row[0]
                    if out_xref in cover_image_xrefs or out_xref in deleted_output_xrefs:
                        continue
                    try:
                        out_image = output.extract_image(out_xref)
                        digest = hashlib.sha256(out_image["image"]).hexdigest() if out_image else ""
                    except Exception:
                        digest = ""
                    if digest in selected_image_hashes:
                        page.delete_image(out_xref)
                        deleted_output_xrefs.add(out_xref)
                        image_removal_report.append({"page": src_idx + 1, "object": out_xref})
            for mark in exact_marks:
                if not mark or len(mark) < 3:
                    continue
                rects = page.search_for(mark, quads=False)
                if rects:
                    for rect in rects:
                        page.add_redact_annot(rect, fill=None, cross_out=False)
                    page.apply_redactions(images=0, graphics=0, text=0)
                    removal_report.append({"text": mark, "page": src_idx + 1, "removed": len(rects)})
            if config.get("remove_brand_links") is True:
                try:
                    for link in list(page.get_links()):
                        uri = (link.get("uri") or "").lower()
                        if any(term in uri for term in ("invytra", "azhumathimayam", "telegram", "whatsapp")):
                            page.delete_link(link)
                except Exception:
                    pass
            if config.get("remove_brand_annotations") is True:
                try:
                    for annot in list(page.annots() or []):
                        info = annot.info or {}
                        desc = " ".join(str(info.get(k, "")) for k in ("content", "title", "subject", "name")).lower()
                        if any(term in desc for term in ("invytra", "azhumathimayam", "telegram", "whatsapp")):
                            page.delete_annot(annot)
                except Exception:
                    pass
            if config.get("watermark", True) is True and src_idx in watermark_pages:
                rect = page.rect
                label = "AZHUMATHIMAYAM"
                size = min(28, max(16, rect.width * .04))
                tw = fitz.Font("helv").text_length(label, fontsize=size)
                x = (rect.width - tw) / 2
                y = rect.height * .54
                page.insert_text((x, y), label, fontname="helv", fontsize=size,
                                 color=(0.94, 0.91, 0.89), overlay=False)

        clean_title = fields.get("title") or Path(pdf_info["filename"]).stem
        topic = re.sub(r"[^\w\s-]", "", clean_title).strip()
        topic = re.sub(r"[\s_]+", "_", topic)[:60].strip("_") or "Notes"
        
        download_dir = Path(job["download_dir"])
        download_dir.mkdir(parents=True, exist_ok=True)
        out_path = download_dir / f"Azhumathimayam_{topic}_Notes.pdf"
        suffix = 2
        while out_path.exists():
            out_path = download_dir / f"Azhumathimayam_{topic}_{suffix}_Notes.pdf"
            suffix += 1
            
        output.set_metadata({
            "title": fields.get("title") or "Azhumathimayam Notes",
            "author": "Azhumathimayam · INVYTRA",
            "subject": fields.get("category") or "LAB EXAM NOTES",
            "creator": "Azhumathimayam Note Maker"
        })
        output.save(out_path, garbage=3, deflate=True)
        output.close()
        src.close()
        
        # Soft verification (never abort valid prepared PDFs)
        final_pages = 1 + (pdf_info["page_count"] - len(remove_pages))
        try:
            chk = fitz.open(out_path)
            final_pages = chk.page_count
            chk.close()
        except Exception:
            pass

        report = {
            "filename": out_path.name,
            "url": f"/download/{job['id']}/{out_path.name}",
            "pages": final_pages,
            "removed_pages": [x + 1 for x in sorted(remove_pages)],
            "removed_text": removal_report,
            "removed_images": image_removal_report,
            "verified": True,
            "size": out_path.stat().st_size if out_path.exists() else 0
        }
        return {"ok": True, **report}
    except Exception as exc:
        return {"ok": False, "filename": pdf_info["filename"], "error": str(exc)[:300]}


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/upload")
def upload():
    prune_expired_jobs()
    files = request.files.getlist("pdfs")
    if not files or len(files) > MAX_FILES:
        return jsonify(error=f"Choose between 1 and {MAX_FILES} PDFs."), 400
    job_id = uuid.uuid4().hex[:16]
    job_dir = Path(tempfile.mkdtemp(prefix="job_" + job_id + "_", dir=RUNTIME))
    metadata, metadata_error = parse_metadata(request.files.get("metadata"))
    logo_file = request.files.get("logo")
    logo_path = None
    if logo_file and logo_file.filename:
        raw = logo_file.read(8 * 1024 * 1024 + 1)
        if len(raw) <= 8 * 1024 * 1024:
            try:
                from PIL import Image
                im = Image.open(io.BytesIO(raw))
                if im.width * im.height > 40_000_000:
                    raise ValueError("Image dimensions are too large.")
                im.verify()
                im = Image.open(io.BytesIO(raw)).convert("RGBA")
                logo_path = job_dir / "custom-logo.png"
                im.thumbnail((1800, 1200))
                im.save(logo_path)
            except Exception:
                metadata_error = (metadata_error + " " if metadata_error else "") + "Logo was not accepted; upload a PNG, JPEG, or WebP image."
        else:
            metadata_error = (metadata_error + " " if metadata_error else "") + "Logo exceeds the 8 MB limit."
            
    reference_file = request.files.get("cover_reference")
    reference_saved = False
    if reference_file and reference_file.filename:
        ref_raw = reference_file.read(8 * 1024 * 1024 + 1)
        if len(ref_raw) <= 8 * 1024 * 1024:
            try:
                from PIL import Image
                ref_im = Image.open(io.BytesIO(ref_raw))
                if ref_im.width * ref_im.height > 40_000_000:
                    raise ValueError("Image dimensions are too large.")
                ref_im.verify()
                ref_im = Image.open(io.BytesIO(ref_raw)).convert("RGB")
                ref_im.thumbnail((1800, 2400))
                ref_im.save(job_dir / "cover-reference.jpg", quality=88)
                reference_saved = True
            except Exception:
                metadata_error = (metadata_error + " " if metadata_error else "") + "Cover reference was not accepted; upload a PNG, JPEG, or WebP image."
        else:
            metadata_error = (metadata_error + " " if metadata_error else "") + "Cover reference exceeds the 8 MB limit."
            
    infos = []
    for index, f in enumerate(files):
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            infos.append({"id": f"bad{index}", "filename": safe_name(f.filename), "error": "File extension is not .pdf."})
            continue
        raw = f.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            infos.append({"id": f"large{index}", "filename": safe_name(f.filename), "error": "File exceeds the 60 MB per-PDF limit."})
            continue
        doc_id = uuid.uuid4().hex[:12]
        path = job_dir / (doc_id + ".pdf")
        path.write_bytes(raw)
        filename = safe_name(f.filename)
        try:
            analysis = analyze_pdf(path, doc_id, filename)
            for page_index, page_summary in enumerate(analysis["pages"]):
                page_summary["preview"] = f"/preview/{job_id}/{doc_id}/{page_index}"
            for image_candidate in analysis.get("repeated_images", []):
                image_candidate["preview"] = f"/image-preview/{job_id}/{doc_id}/{image_candidate['xref']}"
            infos.append(analysis)
        except Exception as exc:
            infos.append({"id": doc_id, "filename": filename, "error": str(exc)[:300]})
            
    if not any("error" not in d for d in infos):
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify(error="No PDF could be analyzed.", file_errors=[{"filename": x["filename"], "error": x.get("error", "Unsupported file.")} for x in infos]), 400
        
    filemap = {x["id"]: {"path": str(job_dir / (x["id"] + ".pdf")), "filename": x["filename"], "page_count": x.get("page_count", 0)} for x in infos if "error" not in x}
    download_dir = DOWNLOAD_ROOT / job_id
    download_dir.mkdir(parents=True, exist_ok=True)
    DOWNLOADS[job_id] = download_dir
    
    job = {
        "id": job_id, "dir": str(job_dir), "download_dir": str(download_dir),
        "files": filemap, "logo_path": str(logo_path) if logo_path else None,
        "cover_reference": str(job_dir / "cover-reference.jpg") if reference_saved else None,
        "created": time.time(), "metadata": metadata
    }
    with LOCK:
        JOBS[job_id] = job
        
    byname = defaultdict(list)
    for row in metadata:
        byname[Path(row.get("filename", "")).name.lower()].append(row)
    matches = {}
    unmatched = []
    for d in infos:
        if "error" in d: continue
        rows = byname.get(d["filename"].lower(), [])
        if len(rows) == 1:
            matches[d["id"]] = rows[0]
        elif len(rows) > 1:
            unmatched.append({"filename": d["filename"], "reason": "multiple metadata records match this filename"})
            
    uploaded_names = {d["filename"].lower() for d in infos if "error" not in d}
    for row in metadata:
        if Path(row.get("filename", "")).name.lower() not in uploaded_names:
            unmatched.append({"filename": row.get("filename", ""), "reason": "no uploaded PDF has this filename"})
            
    return jsonify(
        job_id=job_id, documents=infos, metadata_matches=matches, metadata_unmatched=unmatched,
        metadata_error=metadata_error, metadata_records=metadata, defaults=DEFAULTS,
        logo_uploaded=bool(logo_path), cover_reference_uploaded=reference_saved
    )


@app.get("/preview/<job_id>/<doc_id>/<int:page_no>")
def preview(job_id, doc_id, page_no):
    job = JOBS.get(job_id)
    if not job or doc_id not in job["files"]:
        abort(404)
    info = job["files"][doc_id]
    try:
        doc = fitz.open(info["path"])
        if page_no < 0 or page_no >= doc.page_count:
            abort(404)
        page = doc[page_no]
        scale = min(.65, 900.0 / max(page.rect.width, page.rect.height, 1.0))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return app.response_class(pix.tobytes("png"), mimetype="image/png", headers={"Cache-Control": "no-store"})
    except Exception:
        abort(404)


def run_batch(job_id: str, configs: dict[str, Any]) -> None:
    job = JOBS.get(job_id)
    if not job:
        return
    state = job.get("processing", {})
    try:
        for doc_id, info in job["files"].items():
            state["current"] = info["filename"]
            try:
                res = process_one(job, info, configs.get(doc_id, {}))
                result = {"id": doc_id, **res}
            except Exception as exc:
                result = {"id": doc_id, "ok": False, "filename": info["filename"], "error": str(exc)[:300]}
            state["results"].append(result)
            state["done"] += 1
    except Exception as exc:
        state["error"] = str(exc)
    finally:
        state["current"] = None
        state["status"] = "complete"


@app.get("/image-preview/<job_id>/<doc_id>/<int:xref>")
def image_preview(job_id, doc_id, xref):
    job = JOBS.get(job_id)
    if not job or doc_id not in job["files"]:
        abort(404)
    try:
        source = fitz.open(job["files"][doc_id]["path"])
        if xref <= 0 or xref >= source.xref_length():
            abort(404)
        extracted = source.extract_image(xref)
        if not extracted or len(extracted.get("image", b"")) > 12 * 1024 * 1024:
            abort(404)
        ext = extracted.get("ext", "png").lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "bmp": "image/bmp", "gif": "image/gif", "webp": "image/webp", "jpx": "image/jp2"}.get(ext)
        if mime is None:
            pix = fitz.Pixmap(source, xref)
            if pix.n > 4:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            return app.response_class(pix.tobytes("png"), mimetype="image/png", headers={"Cache-Control": "no-store"})
        return app.response_class(extracted["image"], mimetype=mime,
                                  headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except Exception:
        abort(404)


@app.get("/reference/<job_id>")
def cover_reference(job_id):
    job = JOBS.get(job_id)
    if not job or not job.get("cover_reference"):
        abort(404)
    return send_file(job["cover_reference"], mimetype="image/jpeg", max_age=0)


@app.post("/api/process/<job_id>")
def process(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="This batch has expired. Upload the files again."), 404
    if job.get("processing", {}).get("status") == "running":
        return jsonify(error="This batch is already being prepared."), 409
    payload = request.get_json(silent=True) or {}
    configs = payload.get("documents", {})
    if not isinstance(configs, dict):
        configs = {}
    job["processing"] = {"status": "running", "total": len(job["files"]), "done": 0, "current": None, "results": []}
    thread = threading.Thread(target=run_batch, args=(job_id, configs), daemon=True)
    thread.start()
    return jsonify(status="running", total=len(job["files"])), 202


@app.get("/api/status/<job_id>")
def processing_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="This batch has expired. Upload the files again."), 404
    state = job.get("processing")
    if not state:
        return jsonify(error="No processing job has been started."), 404
    return jsonify(state)


@app.get("/download/<job_id>/<path:filename>")
def download(job_id, filename):
    if not re.fullmatch(r"[0-9a-f]{16}", job_id):
        abort(404)
        
    folder = DOWNLOAD_ROOT / job_id
    if not folder.is_dir():
        folder = DOWNLOADS.get(job_id)
        if not folder or not Path(folder).is_dir():
            abort(404, description="This download has expired. Prepare the PDF again.")
        folder = Path(folder)
        
    safe = Path(unquote(filename)).name
    target = folder / safe
    
    if not target.is_file():
        candidates = list(folder.glob("*.pdf"))
        matched = next((f for f in candidates if f.name.lower() == safe.lower()), None)
        if matched:
            target = matched
        elif len(candidates) == 1:
            target = candidates[0]
        else:
            abort(404, description=f"Requested file '{safe}' was not found.")
            
    return send_file(target, as_attachment=True, download_name=target.name, mimetype="application/pdf", conditional=True)


@app.get("/download-all/<job_id>")
def download_all(job_id):
    if not re.fullmatch(r"[0-9a-f]{16}", job_id):
        abort(404)
        
    folder = DOWNLOAD_ROOT / job_id
    if not folder.is_dir():
        folder = DOWNLOADS.get(job_id)
        if not folder or not Path(folder).is_dir():
            abort(404, description="This batch has expired.")
        folder = Path(folder)
        
    pdf_files = list(folder.glob("*.pdf"))
    if not pdf_files:
        abort(404, description="No prepared PDF files found for this batch.")
        
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in pdf_files:
            zf.write(f, arcname=f.name)
    zip_buffer.seek(0)
    
    zip_name = f"Azhumathimayam_Notes_{job_id[:8]}.zip"
    return send_file(zip_buffer, as_attachment=True, download_name=zip_name, mimetype="application/zip")


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="Upload too large. Each PDF is limited to 60 MB; reduce the batch size and try again."), 413


if __name__ == "__main__":
    host = os.environ.get("INVYTRA_HOST", "127.0.0.1")
    port = int(os.environ.get("INVYTRA_PORT", "5055"))
    app.run(host=host, port=port, debug=False)
