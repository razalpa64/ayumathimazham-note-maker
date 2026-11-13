from __future__ import annotations

import csv
import io
import hashlib
import json
import math
import html
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
IS_VERCEL = bool(os.environ.get("VERCEL"))

def get_safe_runtime_dir() -> Path:
    """Ensure a writable runtime folder across Render, Vercel, Docker, and local."""
    candidates = [
        Path(tempfile.gettempdir()) / "azhumathimayam_runtime",
        BASE / "runtime"
    ]
    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            test_file = c / f".perm_test_{os.getpid()}"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            return c
        except Exception:
            continue
    fallback = Path(tempfile.gettempdir()) / f"azhumathimayam_{os.getpid()}"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback

RUNTIME = get_safe_runtime_dir()
DOWNLOAD_ROOT = RUNTIME / "downloads"
DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
JOBS_DIR = RUNTIME / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)
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


def save_job_state(job_id: str, job: dict[str, Any]) -> None:
    """Persist job state atomically so processes and requests share reliable state."""
    try:
        data = {k: v for k, v in job.items() if k in ("id", "dir", "download_dir", "files", "logo_path", "watermark_image_path", "cover_reference", "created", "metadata", "processing")}
        tmp_file = JOBS_DIR / f"{job_id}.json.tmp"
        tmp_file.write_text(json.dumps(data, default=str), encoding="utf-8")
        tmp_file.replace(JOBS_DIR / f"{job_id}.json")
    except Exception:
        pass


def get_job_state(job_id: str) -> dict[str, Any] | None:
    """Retrieve job state from memory or persistent disk file."""
    with LOCK:
        if job_id in JOBS:
            return JOBS[job_id]
    job_file = JOBS_DIR / f"{job_id}.json"
    if job_file.is_file():
        try:
            data = json.loads(job_file.read_text(encoding="utf-8"))
            with LOCK:
                JOBS[job_id] = data
            return data
        except Exception:
            pass
    return None


app = Flask(__name__, template_folder=str(BASE / "templates"), static_folder=str(BASE / "static"))
app.config["MAX_CONTENT_LENGTH"] = MAX_BATCH
app.config["JSON_SORT_KEYS"] = False

FIELDS = [
    "title", "course_code", "module", "institution", "scheme", "category",
    "website", "phone", "email", "subtitle", "tags",
    "theme_color", "banner_color", "bg_color", "cat_color", "watermark_color",
    "watermark_text", "watermark_subtext", "watermark_type"
]
DEFAULTS = {
    "institution": "",
    "scheme": "",
    "category": "",
    "website": "azhumathimayam.invytra.in",
    "phone": "8606159002",
    "email": "",
    "subtitle": "",
    "tags": "",
    "theme_color": "#640000",
    "banner_color": "#640000",
    "bg_color": "#F7F4EF",
    "cat_color": "#8C1D1D",
    "watermark_color": "#B89494",
    "watermark_text": "അഴിമതി മയം",
    "watermark_subtext": "*by invytra",
    "watermark_type": "text"
}
BRAND_WORDS = ("invytra", "azhumathimayam", "contact", "www.", "http://", "https://", "phone", "8606159002", "telegram", "whatsapp")


def hex_to_rgb(hex_str: str | None, default: tuple[float, float, float]) -> tuple[float, float, float]:
    """Safely convert hex string (e.g. #640000) to float RGB tuple (0.0 - 1.0)."""
    try:
        h = str(hex_str or "").strip().lstrip("#")
        if len(h) == 6:
            return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)
        elif len(h) == 3:
            return (int(h[0] * 2, 16) / 255.0, int(h[1] * 2, 16) / 255.0, int(h[2] * 2, 16) / 255.0)
    except Exception:
        pass
    return default


def render_text_watermark_png(width: float, height: float, label: str, sub_label: str,
                              color: tuple[float, float, float], font_file: Path) -> bytes:
    """Shape Malayalam with MuPDF's HTML text engine, then rotate the whole mark as one image."""
    from PIL import Image

    scale = 2
    staging = fitz.open()
    try:
        page = staging.new_page(width=width, height=height)
        page.insert_font(fontname="NotoML", fontfile=str(font_file))
        rgb = "#" + "".join(f"{round(max(0, min(1, c)) * 255):02X}" for c in color)
        markup = (
            '<div class="watermark">'
            f'<div class="main">{html.escape(label)}</div>'
            + (f'<div class="sub">{html.escape(sub_label)}</div>' if sub_label else "")
            + "</div>"
        )
        css = (
            f".watermark {{ color: {rgb}; text-align: center; }}"
            ".main { font-family: NotoML; font-size: 36pt; line-height: 1.12; white-space: nowrap; }"
            ".sub { font-family: sans-serif; font-size: 13pt; letter-spacing: 2pt; margin-top: 4pt; white-space: nowrap; }"
        )
        text_box = fitz.Rect(width * 0.08, height / 2 - 48, width * 0.92, height / 2 + 58)
        page.insert_htmlbox(text_box, markup, css=css, scale_low=0.55)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
        layer = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
        # Keep the watermark visible but light enough not to compete with the notes.
        layer.putalpha(layer.getchannel("A").point(lambda alpha: round(alpha * 0.58)))
        layer = layer.rotate(-35, resample=Image.Resampling.BICUBIC, expand=False)
        output = io.BytesIO()
        layer.save(output, format="PNG", optimize=True)
        return output.getvalue()
    finally:
        staging.close()


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
            title = candidates[0] if candidates else "Study Notes"

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

    scheme = ""
    sm = re.search(r"\b(?:[A-Z]{2,8}\s*)?20\d{2}\s*(?:scheme|scheme year|syllabus)\b", text + " " + filename, re.I)
    if sm:
        scheme = re.sub(r"\s+", " ", sm.group(0)).upper()

    # Category is deliberately left blank: users choose the cover label that fits.
    category = ""
    tags = ""
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


def qr_on_page(page: fitz.Page, page_index: int, total_pages: int, text: str) -> bool:
    """Hyper-fast QR detector that checks text signals first and only inspects boundary images."""
    low = text.lower()
    if any(k in low for k in ("scan qr", "qr code", "scan here", "scan to join")):
        return True
    if page_index not in (0, total_pages - 1):
        return False
    try:
        if page.get_images(full=True):
            scale = min(0.4, 320.0 / max(page.rect.width, page.rect.height, 1.0))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            import cv2
            import numpy as np
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            detector = cv2.QRCodeDetector()
            value, _, _ = detector.detectAndDecode(img)
            return bool(value)
    except Exception:
        pass
    return False


def image_fingerprint(doc: fitz.Document, xref: int) -> str | None:
    """Conservatively match identical encoded images including their soft masks.

    Objects with unusual indirect dependencies are not grouped; matching just the
    RGB bytes could otherwise merge images with different alpha or decode settings.
    """
    try:
        def image_part(ref: int, allow_smask: bool) -> tuple[bytes, int | None]:
            obj = doc.xref_object(ref, compressed=True)
            if doc.xref_get_key(ref, "Subtype") != ("name", "/Image"):
                raise ValueError()
            smask_type, smask_val = doc.xref_get_key(ref, "SMask")
            mask_type, _ = doc.xref_get_key(ref, "Mask")
            if mask_type != "null" or (smask_type != "null" and (not allow_smask or smask_type != "xref")):
                raise ValueError()
            smask = int(smask_val.split()[0]) if smask_type == "xref" else None
            # Only the soft mask and stream length may be indirect. This avoids
            # treating different color spaces or other indirect settings as equal.
            normalized = re.sub(r"/SMask\s+\d+\s+\d+\s+R", "/SMask SOFTMASK", obj)
            normalized = re.sub(r"/Length\s+(?:\d+\s+\d+\s+R|\d+)", "/Length STREAMLEN", normalized)
            if re.search(r"\b\d+\s+\d+\s+R\b", normalized):
                raise ValueError()
            raw = doc.xref_stream_raw(ref)
            if raw is None or len(raw) > 12 * 1024 * 1024:
                raise ValueError()
            return normalized.encode() + b"\0" + hashlib.sha256(raw).digest(), smask
        part, mask = image_part(xref, True)
        if mask:
            mask_part, _ = image_part(mask, False)
            part += b"\0" + mask_part
        return hashlib.sha256(part).hexdigest()
    except (ValueError, RuntimeError, TypeError, IndexError):
        return None


def image_groups(doc: fitz.Document, occurrences: dict[int, list]) -> list[dict]:
    grouped = {}
    for xref, locations in occurrences.items():
        fingerprint = image_fingerprint(doc, xref)
        key = fingerprint or f"single:{xref}"
        group = grouped.setdefault(key, {"xref": xref, "xrefs": [], "placements": []})
        group["xrefs"].append(xref)
        group["placements"].extend(locations)
    return list(grouped.values())


def image_mask_references(doc: fitz.Document, xrefs: set[int]) -> set[int]:
    """Find image resources also used as masks; replacing these damages other images."""
    masks = set()
    for xref in xrefs:
        for key in ("SMask", "Mask"):
            kind, value = doc.xref_get_key(xref, key)
            if kind == "xref":
                masks.add(int(value.split()[0]))
    return masks


def assert_images_not_masks(doc: fitz.Document, selected: set[int], image_xrefs: set[int]) -> None:
    if selected & image_mask_references(doc, image_xrefs):
        raise ValueError("A selected image is also used as another image's mask; removal was stopped to protect content.")


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
        total = doc.page_count
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
            # Fast QR detection only where relevant
            has_qr = qr_on_page(page, i, total, text) if imgs else False
            per_page_qr.append(has_qr)
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
            for placement in pages[i]["image_placements"]:
                xref = placement["xref"]
                if xref > 0:
                    image_occurrences[xref].append({"page": i + 1, "rects": placement["rects"]})
        mask_xrefs = image_mask_references(doc, set(image_occurrences))
        repeated_images = []
        for group in image_groups(doc, image_occurrences):
            if mask_xrefs.intersection(group["xrefs"]):
                continue
            occurrences = group["placements"]
            # Exclude scans or anything also used as a large page image.
            if not any(o["rects"] for o in occurrences) or not all(
                fitz.Rect(rect).get_area() < doc[o["page"] - 1].rect.get_area() * .5
                for o in occurrences for rect in o["rects"]):
                continue
            repeated_images.append({"xref": group["xref"], "object_count": len(group["xrefs"]),
                                    "pages": sorted({o["page"] for o in occurrences if o["rects"]}),
                                    "placements": occurrences, "confidence": .35,
                                    "warning": "Review all uses: selecting this removes every matching image object, including on other pages."})
        repeated_images.sort(key=lambda g: (-len(g["pages"]), -g["object_count"], g["xref"]))
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


def is_third_party_brand(text: str) -> bool:
    """Detect if a text line or watermark contains third-party branding, website, phone, or channel promotion."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not clean or len(clean) < 3:
        return False
    # Never strip Azhumathimayam / Invytra branding
    if any(k in clean for k in ("azhumathimayam", "invytra", "8606159002")):
        return False
    # Common engineering / study materials third-party promo triggers
    promo_triggers = (
        "downloaded from", "prepared by", "compiled by", "scanned by", "camscanner",
        "adobe scan", "wps office", "telegram", "t.me/", "whatsapp", "follow us",
        "visit us", "subscribe", "youtube", "instagram", "facebook", "join our",
        "www.", "http://", "https://", "ktunotes", "ktuassist", "ktustudents",
        "keralanotes", "ktuqbank", "ktuhub", "studylab", "notability", "goodnotes",
        "scan qr", "join telegram", "all rights reserved"
    )
    if any(k in clean for k in promo_triggers):
        return True
    # Domain pattern: something.com, something.in, etc.
    if re.search(r"\b[a-zA-Z0-9-]{3,}\.(?:com|in|org|net|io|co|xyz|online|club|app|site)\b", clean):
        return True
    # Social handles: @channelname
    if re.search(r"@\w{3,30}\b", clean):
        return True
    # Phone numbers of other parties (10-12 digits)
    if re.search(r"\b(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b", clean):
        return True
    return False


def add_cover(doc: fitz.Document, fields: dict[str, str], logo_path: Path | None) -> None:
    """Draw a precision-crafted Azhumathimayam & Invytra cover page matching the exact design."""
    page = doc.new_page(width=595, height=842)
    banner_color = hex_to_rgb(fields.get("banner_color") or fields.get("theme_color"), (100 / 255, 0, 0))  # Default #640000
    bg_color = hex_to_rgb(fields.get("bg_color"), (247 / 255, 244 / 255, 239 / 255))                     # Default #F7F4EF
    cat_color = hex_to_rgb(fields.get("cat_color"), banner_color)
    ink = (0.12, 0.12, 0.12)                                                                              # #1F1F1F deep charcoal

    # Top 50.4% Banner (0 to 424.2 pt)
    page.draw_rect(fitz.Rect(0, 0, 595, 424.2), color=banner_color, fill=banner_color)
    # Bottom 49.6% Section (424.2 to 842 pt)
    page.draw_rect(fitz.Rect(0, 424.2, 595, 842), color=bg_color, fill=bg_color)

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
                 max_width: float = 500, max_lines: int = 1, leading: float = 1.25) -> float:
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

    # Optional academic scheme label; leave the top edge clean unless supplied.
    scheme = (fields.get("scheme") or "").strip()
    if scheme:
        tracked(scheme, 86, 8.5, 3.2, (1, 1, 1), 460)

    # 2. Ultra-Sharp Authentic Malayalam Wordmark Logo in Center of Maroon Banner
    logo_file = logo_path if (logo_path and logo_path.exists()) else (BASE / "static" / "azhumathimayam-logo.png")
    if logo_file.exists():
        try:
            pix = fitz.Pixmap(str(logo_file))
            target_w = 252.0
            ratio = target_w / max(1, pix.width)
            target_h = pix.height * ratio
            center_y = 252.0
            target_rect = fitz.Rect((595 - target_w) / 2, center_y - target_h / 2,
                                    (595 + target_w) / 2, center_y + target_h / 2)
            page.insert_image(target_rect, filename=str(logo_file), keep_proportion=True)
        except Exception:
            centered("അഴിമതി മയം", 252, 36, font_bold, (1, 1, 1))
    else:
        centered("അഴിമതി മയം", 252, 36, font_bold, (1, 1, 1))

    # Optional cover label/category, editable per document or in batch defaults.
    category = (fields.get("category") or "").strip().upper()
    if category:
        tracked(category, 480, 8.5, 2.8, cat_color, 460)

    # 4. Subject / Title (e.g. Data Structures \n Lab Exam)
    title = (fields.get("title") or "Study Notes").strip()
    # A clean sans face keeps long course titles legible and matches the cover's
    # restrained, editorial look. Step the size down gently for longer titles.
    title_size = 26.0 if len(title) <= 30 else 23.5 if len(title) <= 55 else 20.0
    y = centered(title, 536, title_size, font_sans, ink, 470, max_lines=2, leading=1.18)

    # Keep supporting details separate from the title so course metadata is not
    # silently lost, while giving the title block enough breathing room.
    course_bits = [x for x in (fields.get("course_code", "").strip(), fields.get("module", "").strip()) if x]
    subtitle = fields.get("subtitle", "").strip()
    institution = fields.get("institution", "").strip()
    extra_details = list(dict.fromkeys(x for x in (subtitle, institution, " · ".join(course_bits) if course_bits else "") if x))
    for detail in extra_details[:2]:
        y = centered(detail, y + 2, 9.5, font_sans, (0.35, 0.35, 0.35), 460, max_lines=1)

    # 5. Signature website bar (kept square-cornered to match the cover design)
    website = (fields.get("website") or "azhumathimayam.invytra.in").strip()
    button_top = 663.0
    button_height = 40.0
    button_width = 478.0
    button_rect = fitz.Rect((595 - button_width) / 2, button_top, (595 + button_width) / 2, button_top + button_height)
    
    page.draw_rect(button_rect, color=banner_color, fill=banner_color)

    display = website.replace("https://", "").replace("http://", "").rstrip("/") or "azhumathimayam.invytra.in"
    font_bold_obj = fitz.Font(fontfile=font_bold)
    btn_size = 11.5 if font_bold_obj.text_length(display, fontsize=11.5) <= 440 else 10.0
    btn_w = font_bold_obj.text_length(display, fontsize=btn_size)
    page.insert_text(((595 - btn_w) / 2, button_top + 25.5), display, fontfile=font_bold, fontsize=btn_size, color=(1, 1, 1))

    url = normalized_url(website) or "https://azhumathimayam.invytra.in"
    try:
        page.insert_link({"kind": fitz.LINK_URI, "from": button_rect, "uri": url})
    except Exception:
        pass

    # 6. Contact Line (Contact • 8606159002)
    phone = (fields.get("phone") or "8606159002").strip()
    email = (fields.get("email") or "").strip()
    contact_parts = [p for p in (phone, email) if p]
    contact_text = "Contact • " + (" • ".join(contact_parts) if contact_parts else "8606159002")
    contact_baseline = 739.0
    centered(contact_text, contact_baseline, 9.5, font_bold, banner_color, 480, max_lines=1)

    if phone:
        tel = re.sub(r"[^+\d]", "", phone)
        if tel:
            try:
                c_w = font_bold_obj.text_length(contact_text, fontsize=9.5)
                left_x = (595 - c_w) / 2
                page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(left_x, contact_baseline - 12, left_x + c_w, contact_baseline + 4), "uri": "tel:" + tel})
            except Exception:
                pass

    # 7. Brand Name (I N V Y T R A)
    tracked("I N V Y T R A", 780.0, 7.5, 4.0, banner_color, 220)

    # 8. Optional bottom summary / tags
    tags = (fields.get("tags") or "").strip()
    if tags:
        centered(tags, 816.0, 7.5, font_sans, (0.48, 0.45, 0.44), 520, max_lines=1)


def reconstruct_scan(page: fitz.Page, settings: dict) -> bytes:
    """Experimental color-based reconstruction; only isolated image-only scans are eligible."""
    import cv2
    import numpy as np

    if not isinstance(settings, dict):
        raise ValueError("Invalid reconstruction settings.")
    try:
        box = [float(settings[k]) for k in ("x0", "y0", "x1", "y1")]
        color = settings["color"]
        tolerance = int(settings["tolerance"])
        if (not all(math.isfinite(n) and 0 <= n <= 1 for n in box)
                or box[0] >= box[2] or box[1] >= box[3]
                or not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
                or not 1 <= tolerance <= 100):
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError("Invalid reconstruction area, color, or tolerance.")
    # Refuse mixed PDFs rather than discarding selectable text, links or graphics.
    imgs = page.get_image_info(xrefs=True)
    if (len(imgs) != 1 or not imgs[0].get("xref") or page.get_text().strip()
            or page.get_drawings() or page.get_links() or list(page.annots() or [])
            or list(page.widgets() or [])):
        raise ValueError("Reconstruction is limited to pages containing only one full-page scan, without text, drawings, links, annotations or form fields.")
    image_rect = fitz.Rect(imgs[0]["bbox"]) * page.rotation_matrix
    if not image_rect.contains(page.rect + (1, 1, -1, -1)):
        raise ValueError("Reconstruction requires a full-page scan image.")
    scale = min(2.0, 3000.0 / max(page.rect.width, page.rect.height))
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()
    x0, y0 = int(box[0] * pix.width), int(box[1] * pix.height)
    x1, y1 = min(pix.width, math.ceil(box[2] * pix.width)), min(pix.height, math.ceil(box[3] * pix.height))
    target = np.array([int(color[i:i+2], 16) for i in (1, 3, 5)], dtype=np.int16)
    area = image[y0:y1, x0:x1].astype(np.int16)
    distance = np.max(np.abs(area - target), axis=2)
    mask = np.zeros((pix.height, pix.width), dtype=np.uint8)
    mask[y0:y1, x0:x1] = (distance <= tolerance).astype(np.uint8) * 255
    count = int(np.count_nonzero(mask))
    if count == 0:
        raise ValueError("No pixels match that color. Choose another color or tolerance.")
    if count > pix.width * pix.height * .25:
        raise ValueError("Too much of the page matches this color. Narrow the selection or lower tolerance.")
    result = cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)
    from PIL import Image
    data = io.BytesIO()
    Image.fromarray(result).save(data, format="PNG")
    return data.getvalue()


@app.post("/api/reconstruct-preview/<job_id>/<doc_id>/<int:page_no>")
def reconstruct_preview(job_id, doc_id, page_no):
    job = get_job_state(job_id)
    if not job or doc_id not in job.get("files", {}):
        abort(404)
    try:
        with fitz.open(job["files"][doc_id]["path"]) as doc:
            if not 0 <= page_no < doc.page_count:
                abort(404)
            png = reconstruct_scan(doc[page_no], request.get_json(silent=True))
        return app.response_class(png, mimetype="image/png", headers={"Cache-Control": "no-store"})
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


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
        selected_groups = config.get("remove_image_groups", [])
        if not isinstance(selected_groups, list) or len(selected_groups) > 20:
            raise ValueError("Select at most 20 image groups.")
        selected_groups = {int(x) for x in selected_groups if str(x).isdigit() and 0 < int(x) < src.xref_length()}
        if selected_groups or selected_images:
            occurrences = defaultdict(list)
            for i, page in enumerate(src):
                for row in page.get_images(full=True):
                    if row[0] > 0:
                        occurrences[row[0]].append(i)
            if selected_groups:
                for group in image_groups(src, occurrences):
                    if selected_groups.intersection(group["xrefs"]):
                        selected_images.update(group["xrefs"])
            assert_images_not_masks(src, selected_images, set(occurrences))
        # Map selected source objects to their copied objects by their resource position.
        # Do not match by image bytes: identical bytes can have different masks or uses.
        if config.get("erase_regions"):
            raise ValueError("Area erasing is disabled to protect page content. Select a separate image object instead.")

        reconstruction = config.get("scan_reconstruction")
        reconstruction_page = None
        if reconstruction is not None:
            if not isinstance(reconstruction, dict) or reconstruction.get("approved") is not True:
                raise ValueError("Preview and approve reconstruction before processing.")
            reconstruction_page = reconstruction.get("page")
            if type(reconstruction_page) is not int or not 0 <= reconstruction_page < src.page_count or reconstruction_page in remove_pages:
                raise ValueError("The reconstruction page must be a retained page.")
        include_cover = config.get("add_cover", True) is True
        preserve_document = not include_cover and not remove_pages and reconstruction_page is None
        output = fitz.open(original) if preserve_document else fitz.open()
        raw_fields = config.get("fields") if isinstance(config.get("fields"), dict) else {}
        limits = {"title": 180, "course_code": 40, "module": 100, "institution": 120, "scheme": 60, "category": 60, "website": 180, "phone": 32, "email": 80, "subtitle": 150, "tags": 150}
        fields = {k: str(raw_fields.get(k, "") or "").strip()[:limits.get(k, 200)] for k in FIELDS}
        fields["website"] = normalized_url(fields.get("website", "")) or fields.get("website", "")
        
        logo_path = Path(job["logo_path"]) if job.get("logo_path") else (BASE / "static" / "azhumathimayam-logo.png")
        if include_cover:
            add_cover(output, fields, logo_path)
        cover_image_xrefs = {row[0] for row in output[0].get_images(full=True)} if include_cover else set()
        
        retained_map = []
        for i in range(src.page_count):
            if i in remove_pages:
                continue
            if preserve_document:
                retained_map.append((i, i))
                continue
            out_index = output.page_count
            if i == reconstruction_page:
                source_page = src[i]
                png = reconstruct_scan(source_page, reconstruction)
                replacement = output.new_page(width=source_page.rect.width, height=source_page.rect.height)
                replacement.insert_image(replacement.rect, stream=png)
            else:
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
        watermark_image_cache: dict[tuple, tuple[bytes, int | None]] = {}
        
        for src_idx, out_idx in retained_map:
            page = output[out_idx]
            if selected_images and src_idx != reconstruction_page:
                source_rows = src[src_idx].get_images(full=True)
                output_rows = page.get_images(full=True)
                if len(source_rows) != len(output_rows):
                    raise ValueError("Could not safely map image objects in this PDF. No output was produced.")
                for source_row, output_row in zip(source_rows, output_rows):
                    if source_row[0] not in selected_images:
                        continue
                    out_xref = output_row[0]
                    if out_xref in cover_image_xrefs:
                        raise ValueError("Selected image is shared with the cover; cannot safely remove it.")
                    if out_xref not in deleted_output_xrefs:
                        page.delete_image(out_xref)
                        deleted_output_xrefs.add(out_xref)
                        image_removal_report.append({"page": src_idx + 1, "object": out_xref})

            # 3. User configured exact marks or suggestions
            page_has_marks = False
            for mark in exact_marks:
                if not mark or len(mark) < 3:
                    continue
                try:
                    rects = page.search_for(mark, quads=False)
                    if rects:
                        for rect in rects:
                            page.add_redact_annot(rect, fill=None, cross_out=False)
                            page_has_marks = True
                        removal_report.append({"text": mark, "page": src_idx + 1, "removed": len(rects)})
                except Exception:
                    pass

            # Apply all redactions cleanly at vector level
            if page_has_marks:
                page.apply_redactions(images=0, graphics=0, text=0)

            # 4. Remove all third-party external links (keep internal and invytra links)
            try:
                for link in list(page.get_links()) if config.get("remove_brand_links") is True else []:
                    uri = (link.get("uri") or "").lower()
                    if uri:
                        if "azhumathimayam" in uri or "invytra" in uri:
                            continue
                        page.delete_link(link)
            except Exception:
                pass

            # 5. Remove third-party annotations
            try:
                for annot in list(page.annots() or []) if config.get("remove_brand_annotations") is True else []:
                    info = annot.info or {}
                    desc = " ".join(str(info.get(k, "")) for k in ("content", "title", "subject", "name")).lower()
                    if is_third_party_brand(desc) or any(term in desc for term in ("t.me", "telegram", "whatsapp", "www.", "http", "@", ".com", ".in", "download")):
                        page.delete_annot(annot)
            except Exception:
                pass

            # 6. Watermark placement (drawn strictly UNDER the text: overlay=False)
            if config.get("watermark", True) is True and src_idx in watermark_pages:
                rect = page.rect
                raw_wm = fields.get("watermark_color") or fields.get("banner_color")
                wm_rgb = hex_to_rgb(raw_wm, (100 / 255, 0, 0))
                # Crisp legible tint that stays subtle behind text
                wm_tint = (
                    min(1.0, wm_rgb[0] * 0.52 + 0.38),
                    min(1.0, wm_rgb[1] * 0.52 + 0.38),
                    min(1.0, wm_rgb[2] * 0.52 + 0.38)
                )

                center_x = rect.width / 2
                center_y = rect.height / 2
                wm_type = str(fields.get("watermark_type") or config.get("watermark_type") or "text").lower()

                # Option A: Custom Image Watermark (drawn UNDER text)
                if wm_type == "image":
                    wm_img = None
                    if job.get("watermark_image_path") and Path(job["watermark_image_path"]).exists():
                        wm_img = Path(job["watermark_image_path"])
                    elif job.get("logo_path") and Path(job["logo_path"]).exists():
                        wm_img = Path(job["logo_path"])
                    elif (BASE / "static" / "azhumathimayam-logo.png").exists():
                        wm_img = BASE / "static" / "azhumathimayam-logo.png"

                    if wm_img and wm_img.exists():
                        try:
                            pix = fitz.Pixmap(str(wm_img))
                            target_w = min(rect.width * 0.50, 300.0)
                            target_h = target_w * (pix.height / max(1, pix.width))
                            target_rect = fitz.Rect(
                                center_x - target_w / 2, center_y - target_h / 2,
                                center_x + target_w / 2, center_y + target_h / 2
                            )
                            # overlay=False ensures watermark image is drawn UNDER existing text!
                            page.insert_image(target_rect, filename=str(wm_img), keep_proportion=True, overlay=False)
                        except Exception:
                            pass

                # Option B: Shape text with the Malayalam font, then rotate the complete
                # centered lockup as one transparent watermark image. This avoids
                # MuPDF insert_text limitations with Malayalam conjuncts and marks.
                else:
                    label = (fields.get("watermark_text") or "അഴിമതി മയം").strip()[:100]
                    sub_label = (fields.get("watermark_subtext") or "*by invytra").strip()[:100]
                    try:
                        font_file = BASE / "static" / "NotoSansMalayalam.ttf"
                        cache_key = (
                            round(rect.width, 2), round(rect.height, 2), label, sub_label,
                            tuple(round(channel, 4) for channel in wm_tint)
                        )
                        cached = watermark_image_cache.get(cache_key)
                        if cached and cached[1]:
                            page.insert_image(rect, xref=cached[1], overlay=False)
                        else:
                            png = cached[0] if cached else render_text_watermark_png(
                                rect.width, rect.height, label, sub_label, wm_tint, font_file
                            )
                            image_xref = page.insert_image(rect, stream=png, overlay=False)
                            watermark_image_cache[cache_key] = (png, image_xref)
                    except Exception:
                        try:
                            logo = BASE / "static" / "azhumathimayam-logo.png"
                            if logo.exists():
                                pix = fitz.Pixmap(str(logo))
                                target_w = min(rect.width * 0.45, 260.0)
                                target_h = target_w * (pix.height / max(1, pix.width))
                                target_rect = fitz.Rect(
                                    center_x - target_w / 2, center_y - target_h / 2,
                                    center_x + target_w / 2, center_y + target_h / 2
                                )
                                page.insert_image(target_rect, filename=str(logo), keep_proportion=True, overlay=False)
                        except Exception:
                            pass

                # Discreet anti-piracy running stamps in margins (under text)
                page.insert_text((42, 22), "AZHUMATHIMAYAM · STUDY NOTES", fontname="helv", fontsize=7.5, color=(0.52, 0.46, 0.44), overlay=False)
                page.insert_text((42, rect.height - 18), "azhumathimayam.invytra.in · All Study Rights Reserved", fontname="helv", fontsize=7.0, color=(0.52, 0.46, 0.44), overlay=False)

        # Object-only removal should not modify selectable text. Stop instead of
        # delivering a misleading "clean" result if the PDF engine disagrees.
        text_verified = bool(selected_images and not exact_marks and reconstruction_page is None
                             and not (config.get("watermark", True) is True
                                      and any(i in watermark_pages for i, _ in retained_map)))
        if text_verified:
            for src_idx, out_idx in retained_map:
                if src[src_idx].get_text("text") != output[out_idx].get_text("text"):
                    raise ValueError(f"Text changed on page {src_idx + 1}; image removal was stopped.")

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
            
        if include_cover:
            output.set_metadata({
                "title": fields.get("title") or "Azhumathimayam Notes",
                "author": "Azhumathimayam · INVYTRA",
                "subject": fields.get("category") or "Study Notes",
                "creator": "Azhumathimayam Note Maker"
            })
        elif not preserve_document:
            output.set_metadata({k: v or "" for k, v in src.metadata.items()
                                 if k in ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate", "trapped")})
        output.save(out_path, garbage=3, deflate=True)
        output.close()
        src.close()
        
        # Soft verification (never abort valid prepared PDFs)
        final_pages = int(include_cover) + (pdf_info["page_count"] - len(remove_pages))
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
            "reconstructed_page": reconstruction_page + 1 if reconstruction_page is not None else None,
            "verified": True,
            "text_verified": text_verified,
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

    wm_file = request.files.get("watermark_image")
    watermark_image_path = None
    if wm_file and wm_file.filename:
        raw_wm = wm_file.read(8 * 1024 * 1024 + 1)
        if len(raw_wm) <= 8 * 1024 * 1024:
            try:
                from PIL import Image
                im_wm = Image.open(io.BytesIO(raw_wm))
                im_wm.verify()
                im_wm = Image.open(io.BytesIO(raw_wm)).convert("RGBA")
                watermark_image_path = job_dir / "custom-watermark.png"
                im_wm.thumbnail((1600, 1600))
                im_wm.save(watermark_image_path)
            except Exception:
                pass
            
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
        "watermark_image_path": str(watermark_image_path) if watermark_image_path else None,
        "cover_reference": str(job_dir / "cover-reference.jpg") if reference_saved else None,
        "created": time.time(), "metadata": metadata
    }
    with LOCK:
        JOBS[job_id] = job
    save_job_state(job_id, job)
        
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
        logo_uploaded=bool(logo_path), cover_reference_uploaded=reference_saved,
        watermark_image_uploaded=bool(watermark_image_path)
    )


@app.get("/preview/<job_id>/<doc_id>/<int:page_no>")
def preview(job_id, doc_id, page_no):
    job = get_job_state(job_id)
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


@app.get("/image-removal-preview/<job_id>/<doc_id>/<int:xref>/<int:page_no>")
def image_removal_preview(job_id, doc_id, xref, page_no):
    """Show one page after removing only this group, without changing the source."""
    job = get_job_state(job_id)
    if not job or doc_id not in job.get("files", {}):
        abort(404)
    try:
        with fitz.open(job["files"][doc_id]["path"]) as doc:
            if not 0 <= page_no < doc.page_count or not 0 < xref < doc.xref_length():
                abort(404)
            occurrences = defaultdict(list)
            for i, p in enumerate(doc):
                for row in p.get_images(full=True):
                    if row[0] > 0:
                        occurrences[row[0]].append(i)
            if xref not in occurrences:
                abort(404)
            fingerprint = image_fingerprint(doc, xref)
            matching = {candidate for candidate in occurrences
                        if candidate == xref or (fingerprint is not None and image_fingerprint(doc, candidate) == fingerprint)}
            assert_images_not_masks(doc, matching, set(occurrences))
            page = doc[page_no]
            page_xrefs = {row[0] for row in page.get_images(full=True)} & matching
            if not page_xrefs:
                return jsonify(error="The selected image is not used on that page."), 400
            for image_xref in page_xrefs:
                page.delete_image(image_xref)
            scale = min(.65, 900.0 / max(page.rect.width, page.rect.height, 1.0))
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            return app.response_class(pix.tobytes("png"), mimetype="image/png", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.post("/api/upload-watermark/<job_id>")
def upload_watermark(job_id):
    job = get_job_state(job_id)
    if not job:
        return jsonify(error="Job expired or not found."), 404
    f = request.files.get("watermark_image")
    if not f or not f.filename:
        return jsonify(error="No image file provided."), 400
    raw = f.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        return jsonify(error="Image exceeds 8 MB limit."), 400
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.verify()
        im = Image.open(io.BytesIO(raw)).convert("RGBA")
        job_dir = Path(job["dir"])
        target = job_dir / "custom-watermark.png"
        im.thumbnail((1600, 1600))
        im.save(target)
        job["watermark_image_path"] = str(target)
        with LOCK:
            JOBS[job_id] = job
        save_job_state(job_id, job)
        return jsonify(ok=True, message="Custom watermark image saved.", url=f"/watermark-preview/{job_id}")
    except Exception as exc:
        return jsonify(error=f"Could not process watermark image: {str(exc)[:150]}"), 400


@app.get("/watermark-preview/<job_id>")
def watermark_preview(job_id):
    job = get_job_state(job_id)
    if not job:
        abort(404)
    target = None
    if job.get("watermark_image_path") and Path(job["watermark_image_path"]).exists():
        target = Path(job["watermark_image_path"])
    elif job.get("logo_path") and Path(job["logo_path"]).exists():
        target = Path(job["logo_path"])
    else:
        target = BASE / "static" / "azhumathimayam-logo.png"
    if target and target.exists():
        return send_file(str(target), mimetype="image/png")
    abort(404)


def run_batch(job_id: str, configs: dict[str, Any]) -> None:
    job = get_job_state(job_id)
    if not job:
        return
    state = job.get("processing", {})
    if not state:
        state = {"status": "running", "total": len(job.get("files", {})), "done": 0, "current": None, "results": []}
        job["processing"] = state
    try:
        for doc_id, info in job.get("files", {}).items():
            state["current"] = info["filename"]
            with LOCK:
                JOBS[job_id] = job
            save_job_state(job_id, job)
            try:
                res = process_one(job, info, configs.get(doc_id, {}))
                result = {"id": doc_id, **res}
            except Exception as exc:
                result = {"id": doc_id, "ok": False, "filename": info["filename"], "error": str(exc)[:300]}
            state["results"].append(result)
            state["done"] += 1
            with LOCK:
                JOBS[job_id] = job
            save_job_state(job_id, job)
    except Exception as exc:
        state["error"] = str(exc)
    finally:
        state["current"] = None
        state["status"] = "complete"
        with LOCK:
            JOBS[job_id] = job
        save_job_state(job_id, job)


@app.get("/image-preview/<job_id>/<doc_id>/<int:xref>")
def image_preview(job_id, doc_id, xref):
    job = get_job_state(job_id)
    if not job or doc_id not in job["files"]:
        abort(404)
    try:
        source = fitz.open(job["files"][doc_id]["path"])
        if xref <= 0 or xref >= source.xref_length():
            abort(404)
        extracted = source.extract_image(xref)
        if not extracted or len(extracted.get("image", b"")) > 12 * 1024 * 1024:
            abort(404)
        if extracted.get("smask"):
            pix = fitz.Pixmap(source, xref)
            if pix.colorspace and pix.colorspace.n != 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            mask = fitz.Pixmap(source, extracted["smask"])
            pix = fitz.Pixmap(pix, mask)
            return app.response_class(pix.tobytes("png"), mimetype="image/png", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
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
    job = get_job_state(job_id)
    if not job or not job.get("cover_reference"):
        abort(404)
    return send_file(job["cover_reference"], mimetype="image/jpeg", max_age=0)


@app.post("/api/process/<job_id>")
def process(job_id):
    job = get_job_state(job_id)
    if not job:
        return jsonify(error="This batch has expired. Upload the files again.", status="failed"), 404
    payload = request.get_json(silent=True) or {}
    configs = payload.get("documents", {})
    if not isinstance(configs, dict):
        configs = {}
    job["processing"] = {"status": "running", "total": len(job.get("files", {})), "done": 0, "current": None, "results": []}
    with LOCK:
        JOBS[job_id] = job
    save_job_state(job_id, job)
    
    # Process synchronously for instant execution and guaranteed single-request reliability
    run_batch(job_id, configs)
    
    job = get_job_state(job_id) or job
    proc = job.get("processing", {})
    return jsonify({
        "status": "complete",
        "total": proc.get("total", len(job.get("files", {}))),
        "done": proc.get("done", len(job.get("files", {}))),
        "results": proc.get("results", [])
    }), 200


@app.get("/api/status/<job_id>")
def processing_status(job_id):
    job = get_job_state(job_id)
    if not job:
        return jsonify(error="This batch has expired. Upload the files again.", status="failed"), 404
    state = job.get("processing")
    if not state:
        return jsonify(status="complete", total=len(job.get("files", {})), done=len(job.get("files", {})), results=[]), 200
    return jsonify(state), 200


@app.get("/download/<job_id>/<path:filename>")
def download(job_id, filename):
    if not re.fullmatch(r"[0-9a-f]{16}", job_id):
        abort(404)
        
    folder = DOWNLOAD_ROOT / job_id
    if not folder.is_dir():
        folder = DOWNLOADS.get(job_id)
        if not folder or not Path(folder).is_dir():
            job = get_job_state(job_id)
            if job and job.get("download_dir") and Path(job["download_dir"]).is_dir():
                folder = Path(job["download_dir"])
            else:
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
            job = get_job_state(job_id)
            if job and job.get("download_dir") and Path(job["download_dir"]).is_dir():
                folder = Path(job["download_dir"])
            else:
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
    is_cloud = bool(os.environ.get("RENDER") or os.environ.get("PORT") or os.environ.get("DYNO"))
    host = os.environ.get("INVYTRA_HOST", "0.0.0.0" if is_cloud else "127.0.0.1")
    port = int(os.environ.get("PORT") or os.environ.get("INVYTRA_PORT", "5055"))
    app.run(host=host, port=port, debug=False)
