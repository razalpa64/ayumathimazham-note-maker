# അഴിമതി മയം (Azhumathimayam) — Note Maker

A high-performance, local-first study and engineering note studio designed for all universities, colleges, academic boards, and syllabus schemes (KTU, Calicut, MG University, Anna University, VTU, CUSAT, Autonomous Colleges, and more).

Powered by a deterministic rules-based vector engine, Azhumathimayam Note Maker cleans up watermark clutter, trims old promotional pages, and generates covers with Malayalam typography, custom color themes, and signature pill navigation.

---

## Highlights

- **Signature Cover Design**: Precision split-layout for any academic scheme:
  - Top half (50.4%): Deep maroon (`#640000`) or custom color theme banner featuring the authentic white **"അഴിമതി മയം"** (Azhumathimayam) wordmark and letter-spaced scheme headers.
  - Bottom half (49.6%): Warm ivory/cream (`#F7F4EF`) section with bold serif subject titles, structured course tags, and a rounded pill link button.
- **🎨 Brand Color Theme Selector**: Choose between Azhumathimayam Maroon, Royal Navy, Imperial Emerald, Obsidian Slate, Crimson Ruby, or pick any custom color.
- **🛡️ Custom Watermarking (Under Text)**: Watermarks (custom text or image/stamp) are rendered strictly *behind* notes (`overlay=False`), keeping formulas, diagrams, and text 100% sharp and readable.
- **Interactive PDF Links**: Embeds native clickable links inside the PDF for `azhumathimayam.invytra.in`, phone calls (`tel:`), and emails (`mailto:`).
- **⚡ Smart Auto-Clean**: Suggestions help identify possible branding; review items before choosing removal.
- **100% Reliable Batch Downloads**: Direct single-click PDF downloads and instant **Download All as ZIP** for multi-document batches.
- **Deterministic & Private**: 100% local processing. No cloud telemetry, no remote model calls, and zero data leakage. Original uploaded PDFs are never overwritten.

---

## Quickstart

### Prerequisites
- Python 3.10+
- `pip`

### Installation

```bash
# Clone the repository
git clone https://github.com/razalpa64/ayumathimazham-note-maker.git
cd ayumathimazham-note-maker

# Create and activate a virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the studio
python app.py
```

Open your browser at **http://127.0.0.1:5055**.

---

## Configuration & Environment Variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `INVYTRA_PORT` | `5055` | Port to bind the local server |
| `INVYTRA_HOST` | `127.0.0.1` | Host address (leave on loopback for security) |

---

## Workflow

1. **Upload**: Drag and drop up to 12 study PDFs (up to 60 MB each). Optionally provide CSV/JSON metadata or a custom logo.
2. **Review & Auto-Clean**: Review each document's suggested title, scheme, and page layout. Use **Apply cover suggestions** to fill missing cover details; choose any removals manually.
3. **Live Cover Preview**: Preview the generated cover page in real time with exact A4 proportions, authentic Malayalam logo, and styled pill button.
4. **Prepare & Download**: Process the batch into pristine output PDFs (`Azhumathimayam_<Topic>_Notes.pdf`) and download individually or as a single ZIP archive.

---

## Cloud Deployment

### Deploying on Vercel
This repository is configured out-of-the-box for Vercel using `vercel.json` and `api/index.py`:

1. Push this repo to your GitHub account.
2. Go to [Vercel](https://vercel.com) and click **"Add New Project"**.
3. Select this repository and click **Deploy**.
4. Vercel automatically detects the Python runtime and routes all traffic to Flask.

> [!NOTE]
> **Vercel Serverless Limits**: Vercel Free has a strict **4.5 MB request body limit** for serverless function uploads and a 10s timeout. It works great for single study notes under 4.5 MB.
> For large multi-file batches (up to 60 MB each), deploy as a continuous web service on **Render** or **Railway**.

### Deploying on Render (Free, supports large files up to 60 MB)
1. Go to [Render.com](https://render.com) and create a **Web Service**.
2. Connect your GitHub repository.
3. Configure:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py` (or `gunicorn app:app -b 0.0.0.0:$PORT`)
4. Click **Deploy**. Render gives you a free URL with no 4.5 MB upload limit!

---

## Technical Stack

- **Backend**: Python 3, Flask, PyMuPDF (Fitz)
- **Frontend**: Vanilla ES6 JavaScript, Responsive CSS3
- **Typography**: Bundled DejaVu Serif Bold, DejaVu Sans Bold, DejaVu Sans
- **Asset Processing**: Transparent RGBA vector & PNG rasterization with GDI+/Pillow

---

## License

MIT License. Designed with care for students and educators.

### Fixed branding and preserving content
The review panel suggests separate image objects, including single-page images, for you to inspect. Select an image only if all its uses are watermarks: removal affects every use of that PDF image object. No pages, text, links, or images are selected for removal by default. Exact-text removal is optional and may remove overlapping text. Area erasing is disabled because it destroys underlying content.

This is object-based detection, not AI reconstruction. A watermark flattened into a scan, vector outlines, or overlapping text cannot reliably be removed without risking content; use an unwatermarked original where possible. Review the output and edit only documents you have permission to modify.

### Experimental local scan reconstruction
For a mark baked into a scan, select one page in **Experimental scan reconstruction**, drag a rectangle, choose the mark's color and tolerance, and preview the proposed result. Approve only after comparing it with the original. The algorithm uses color matching and OpenCV inpainting on the app server, with no external AI service; it is not a generative AI model. If the app is hosted, the PDF is uploaded to that server. It can change similarly colored notes and guess incorrectly where marks overlap content; an unwatermarked original remains the only reliable source. The tool replaces the chosen page with a rendered scan and is limited to single full-page image-only pages without text, drawings, links, annotations or form fields; other pages are rejected. Only one reconstruction per document is supported per batch. Output resolution is bounded, so the reconstructed page may be downsampled. The uploaded original is unchanged.
