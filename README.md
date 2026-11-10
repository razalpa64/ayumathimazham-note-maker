# അഴിമതി മയം (Azhumathimayam) — Note Maker

A high-performance, local-first engineering note studio designed for KTU (APJ Abdul Kalam Technological University) 2024 Scheme study materials, lab exam records, and academic notes.

Powered by a deterministic rules-based engine, Azhumathimayam Note Maker cleans up watermark clutter, trims old promotional pages, and generates covers with Malayalam typography and signature pill navigation.

---

## Highlights

- **Signature Maroon Cover Design**: Exactly reproduces the KTU 2024 Scheme split-layout:
  - Top half (50.4%): Deep maroon (`#640000`) banner featuring the authentic white **"അഴിമതി മയം"** (Azhumathimayam) wordmark and letter-spaced scheme headers.
  - Bottom half (49.6%): Warm ivory/cream (`#F7F4EF`) section with bold serif subject titles, structured course tags, and a rounded maroon pill link button.
- **Interactive PDF Links**: Embeds native clickable links inside the PDF for `azhumathimayam.invytra.in`, phone calls (`tel:`), and emails (`mailto:`).
- **⚡ Smart Auto-Clean**: One-click intelligence that automatically identifies old branded covers, promotional/contact pages, QR codes, and watermarks for removal.
- **100% Reliable Batch Downloads**: Direct single-click PDF downloads and instant **Download All as ZIP** for multi-document batches.
- **Deterministic & Private**: 100% local processing. No cloud telemetry, no remote model calls, and zero data leakage. Original uploaded PDFs are never overwritten.
- **Gentle Watermarking**: Optional subtle, elegant background watermark layer on retained study pages that protects notes without obstructing math formulas, circuit diagrams, or code.

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
2. **Review & Auto-Clean**: Review each document's suggested title, scheme, and page layout. Click **⚡ Smart Auto-Clean** to instantly deselect old covers and promo pages.
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
