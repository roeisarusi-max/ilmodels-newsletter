"""
IL Models — Newsletter Builder
Hosted on Railway. Accessible from anywhere.
"""

import io, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, jsonify, request, render_template, make_response

# ── Auto-install deps ──────────────────────────────────────────────────────────
def _install(pkg):
    os.system(f"{sys.executable} -m pip install {pkg} -q")

try: import requests as req
except ImportError: _install("requests"); import requests as req

try: from reportlab.pdfgen import canvas as rl; from reportlab.lib.pagesizes import A4; from reportlab.lib.colors import HexColor; from reportlab.lib.units import mm; from reportlab.lib.utils import ImageReader; PDF_OK = True
except ImportError: _install("reportlab"); from reportlab.pdfgen import canvas as rl; from reportlab.lib.pagesizes import A4; from reportlab.lib.colors import HexColor; from reportlab.lib.units import mm; from reportlab.lib.utils import ImageReader; PDF_OK = True

try: from PIL import Image as PILImage; PIL_OK = True
except ImportError: _install("pillow"); from PIL import Image as PILImage; PIL_OK = True

# ── App ────────────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder='.')
PORT = int(os.environ.get("PORT", 8765))

# ── Scraping config ────────────────────────────────────────────────────────────
BASE    = "https://www.ilmodel.com"
LOGO_ID = "6239eb49c2313f518f27d95c"
UA      = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

CATEGORIES = {
    "WOMEN":    "/models",
    "MEN":      "/men",
    "CURVE":    "/plus-size",
    "NEW FACES":"/development",
    "CLASSIC":  "/classic-women",
}

SKIP_SLUGS = {
    "models","men","plus-size","development","classic-women","influencer",
    "about","contact","become-a-model","index2","women","curve","classic",
    "news","talent","blog",
}

CDN = "https://images.squarespace-cdn.com/content/v1/6238add85aa64242d8a6f491"

# Static influencer data
INFLUENCERS = [
  {"name":"LIOR MARS","insta":"liormars","stats":"TIKTOK 284K | IG 104K","thumb":f"{CDN}/c493a6a6-b5aa-4b5e-941a-e88b674edbc5/WhatsApp+Image+2022-12-15+at+13.08.06.jpeg","url":f"{BASE}/influencer"},
  {"name":"MILANA VINO","insta":"milana.vino","stats":"IG 323K | TIKTOK 160K","thumb":f"{CDN}/c94632d6-1f36-4f71-82ef-0558b37714e1/Screenshot+2024-08-01+at+11.01.05.png","url":f"{BASE}/influencer"},
  {"name":"ELLA NETZER","insta":"ella_netzer8","stats":"IG 279K | TIKTOK 205K","thumb":f"{CDN}/575c7607-9393-4c15-8c48-eb828b0553a3/Screenshot+2025-04-23+at+8.51.41.png","url":f"{BASE}/influencer"},
  {"name":"YARDEN EDRI","insta":"iyardenedri","stats":"IG 211K | TIKTOK 50K","thumb":f"{CDN}/188810f3-1219-40c1-90a7-d0766e48f6ca/PHOTO-2026-03-24-19-45-15.jpg","url":f"{BASE}/influencer"},
  {"name":"MICHELLE ALGRABLI","insta":"michelle_algrabli","stats":"TIKTOK 46.6K | IG 31K","thumb":f"{CDN}/ee730cb4-5c07-4374-90a3-fe8474b8547c/2.jpg","url":f"{BASE}/influencer"},
  {"name":"NAAMA AGAY SHAY","insta":"naamaagayshay","stats":"IG 34K | TIKTOK 282K","thumb":f"{CDN}/c3639cc4-6526-42b4-a993-450423667bc1/PHOTO-2026-04-01-13-47-04.jpg","url":f"{BASE}/influencer"},
  {"name":"GAL GAHALY","insta":"gal.gahaly","stats":"IG 68.8K | TIKTOK 447K","thumb":f"{CDN}/4c89a64c-b2f0-4acd-93e0-64847bd1d3e7/PHOTO-2026-01-07-13-39-51.jpg","url":f"{BASE}/influencer"},
  {"name":"EMILY GOMBERG","insta":"emily_gomberg","stats":"IG 207K | TIKTOK 180K","thumb":f"{CDN}/75879b77-9fe6-420a-b390-2d79b8b025e1/1.jpg","url":f"{BASE}/influencer"},
  {"name":"ARIEL BEN ATAR","insta":"arielbenattar","stats":"IG 221K","thumb":f"{CDN}/1c68ca67-929a-46c4-91a9-819b14ade2be/Screenshot+2025-06-08+at+18.39.31.png","url":f"{BASE}/influencer"},
  {"name":"SHAY BARADUT","insta":"shay.baradut","stats":"IG 77.9K | TIKTOK 46.6K","thumb":f"{CDN}/c3c8980e-ae2a-4f07-8bb2-2b2cd31a9e1c/1.png","url":f"{BASE}/influencer"},
]

# ── In-memory cache ────────────────────────────────────────────────────────────
_cache       = None   # {"data": {CAT: [model,...]}, "fetched_at": "..."}
_fetch_state = {"running": False, "done": 0, "total": 0}
_fetch_lock  = threading.Lock()

# ── Scraping helpers ───────────────────────────────────────────────────────────
def slug_to_name(slug):
    parts = slug.split("-")
    if parts and parts[-1].isdigit(): parts = parts[:-1]
    return " ".join(p.upper() for p in parts)

def extract_page(html, slug):
    """Pull name, stats, instagram, photos from raw HTML."""
    # Name from <title>
    name = slug_to_name(slug)
    m = re.search(r'<title>([^<|—\-]+?)(?:\s*[|—\-])', html, re.I)
    if m:
        t = m.group(1).strip().upper()
        if t and t not in {"IL MODELS","IL MODEL","HOME","MODELS"}:
            name = t

    # Stats — extract all available fields with multiple pattern attempts
    found = {}

    # Height
    for pat in [r'[Hh]eight[\s:]*([0-9.,]+\s*(?:cm)?)', r'"height"\s*:\s*"([^"]+)"']:
        m = re.search(pat, html)
        if m: found["Height"] = m.group(1).strip().rstrip(".,"); break

    # Bust / Waist / Hips — try individual, then combined B/W/H
    for pat in [r'[Bb]ust[\s:]*(\d+)', r'"bust"\s*:\s*"?(\d+)"?']:
        m = re.search(pat, html)
        if m: found["Bust"] = m.group(1); break
    for pat in [r'[Ww]aist[\s:]*(\d+)', r'"waist"\s*:\s*"?(\d+)"?']:
        m = re.search(pat, html)
        if m: found["Waist"] = m.group(1); break
    for pat in [r'[Hh]ips[\s:]*(\d+)', r'"hips"\s*:\s*"?(\d+)"?']:
        m = re.search(pat, html)
        if m: found["Hips"] = m.group(1); break
    # Combined B/W/H fallback
    if not all(k in found for k in ("Bust","Waist","Hips")):
        m = re.search(r'B[/\s]?W[/\s]?H[\s:]*(\d+)[/\s]+(\d+)[/\s]+(\d+)', html, re.I)
        if m:
            found.setdefault("Bust",  m.group(1))
            found.setdefault("Waist", m.group(2))
            found.setdefault("Hips",  m.group(3))

    # Other fields — require colon separator to avoid false matches (e.g. "Brazil" → "Bra: zil")
    extra_fields = [
        ("Bra",           [r'[Bb]ra\s*:\s*([A-Za-z0-9/]+)', r'"bra"\s*:\s*"([^"]+)"']),
        ("Shirt",         [r'[Ss]hirt\s*:\s*([A-Za-z0-9]+)', r'"shirt"\s*:\s*"([^"]+)"']),
        ("Pants",         [r'[Pp]ants\s*:\s*(\d+)', r'"pants"\s*:\s*"?(\d+)"?']),
        ("Shoe",          [r'[Ss]hoe[s]?\s*:\s*(\d+[.,]?\d*)', r'[Ss]hoes?\s*:\s*(\d+[.,]?\d*)']),
        ("Eye Color",     [r'[Ee]ye\s*[Cc]olor\s*:\s*(\w+)', r'"eyeColor"\s*:\s*"([^"]+)"']),
        ("Hair Color",    [r'[Hh]air\s*[Cc]olor\s*:\s*(\w+)', r'"hairColor"\s*:\s*"([^"]+)"']),
        ("Tattoos",       [r'[Tt]attoos?\s*:\s*(\w+)']),
        ("Ear Piercings", [r'[Ee]ar\s*[Pp]iercings?\s*:\s*([0-9A-Za-z+\-]+']),
    ]
    for lbl, patterns in extra_fields:
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                val = m.group(1).strip().rstrip(".,")
                if val and len(val) < 30:  # sanity check
                    found[lbl] = val
                break

    # Build ordered stats string
    order = ["Height","Bust","Waist","Hips","Bra","Shirt","Pants","Shoe","Eye Color","Hair Color","Tattoos","Ear Piercings"]
    parts = [f"{k}  {found[k]}" for k in order if k in found]
    stats = "  |  ".join(parts)

    # Instagram
    insta = ""
    skip = {"ilmodels_","ilmodels","p","reel","stories","explore","accounts","reels"}
    for pat in [
        r'href=["\']https?://(?:www\.)?instagram\.com/([a-zA-Z0-9_.]{2,40})[/"\']',
        r'instagram\.com/([a-zA-Z0-9_.]{2,40})[/?"\s<]',
    ]:
        im = re.search(pat, html)
        if im and im[1].lower() not in skip:
            insta = "@" + im[1]; break

    # Photos
    seen, photos = set(), []
    for m in re.finditer(r'https://images\.squarespace-cdn\.com/content/v1/[a-z0-9]+/([^"\'<>\s)]+)', html):
        url = m[0].split("?")[0]
        if LOGO_ID in url or url in seen: continue
        seen.add(url); photos.append(url)

    return {"name": name, "stats": stats, "insta": insta, "photos": photos}

def fetch_model(cat, slug):
    try:
        r = req.get(f"{BASE}/{slug}/", headers=UA, timeout=12)
        if r.ok:
            data = extract_page(r.text, slug)
            photos = [p for p in data["photos"] if "favicon" not in p]
            return cat, slug, {**data, "photos": photos,
                               "thumb": photos[0] if photos else "",
                               "url": f"{BASE}/{slug}/"}
    except Exception as e:
        print(f"  [{slug}] {e}")
    return cat, slug, {"name": slug_to_name(slug), "stats": "", "insta": "", "photos": [], "thumb": "", "url": f"{BASE}/{slug}/"}

def discover_slugs(cat, path):
    try:
        r = req.get(f"{BASE}{path}", headers=UA, timeout=12)
        if not r.ok: return cat, []
        links = re.findall(r'href="/([a-z][a-z0-9-]+)/"', r.text)
        slugs = [l for l in dict.fromkeys(links) if l not in SKIP_SLUGS and "." not in l and len(l) > 2]
        return cat, slugs
    except: return cat, []

def run_fetch():
    global _cache, _fetch_state
    with _fetch_lock:
        if _fetch_state["running"]: return
        _fetch_state.update({"running": True, "done": 0, "total": 0})

    try:
        print("🔍 Discovering models...")
        cat_slugs = {}
        with ThreadPoolExecutor(max_workers=5) as ex:
            for cat, slugs in [f.result() for f in [ex.submit(discover_slugs, c, p) for c, p in CATEGORIES.items()]]:
                cat_slugs[cat] = slugs

        tasks = [(c, s) for c, ss in cat_slugs.items() for s in ss]
        _fetch_state["total"] = len(tasks)
        print(f"📡 Fetching {len(tasks)} models...")

        raw = {c: {} for c in cat_slugs}
        with ThreadPoolExecutor(max_workers=12) as ex:
            for future in as_completed([ex.submit(fetch_model, c, s) for c, s in tasks]):
                cat, slug, data = future.result()
                raw[cat][slug] = data
                _fetch_state["done"] += 1

        # Build ordered output
        out = {}
        for cat, slugs in cat_slugs.items():
            out[cat] = [raw[cat][s] for s in slugs if s in raw[cat]]

        # Add influencers
        out["INFLUENCERS"] = [{**inf, "slug": None} for inf in INFLUENCERS]

        _cache = {"data": out, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        total  = sum(len(v) for k, v in out.items() if k != "INFLUENCERS")
        print(f"✅ Done — {total} models")
    except Exception as e:
        print(f"❌ Fetch error: {e}")
    finally:
        _fetch_state["running"] = False

# ── PDF generation ─────────────────────────────────────────────────────────────
HEADERS_PDF = {**UA, "Referer": "https://www.ilmodel.com/"}

def fetch_img(url):
    try:
        r = req.get(url, headers=HEADERS_PDF, timeout=10, stream=True)
        if r.ok:
            img = PILImage.open(io.BytesIO(r.content)).convert("RGB")
            out = io.BytesIO(); img.save(out, "JPEG", quality=85); out.seek(0)
            return out
    except: pass
    return None

def build_pdf(models, title=""):
    W, H  = A4          # 595 x 842 pts
    M     = 10 * mm

    BG    = HexColor("#0A0A0A")
    GOLD  = HexColor("#C9A96E")
    GOLD2 = HexColor("#E8D5A3")
    WHITE = HexColor("#FFFFFF")
    SILVER= HexColor("#AAAAAA")
    DARK  = HexColor("#0F0F0F")
    DARK2 = HexColor("#161616")

    HDR_H  = 22 * mm   # header strip
    INFO_H = 80 * mm   # info strip at bottom
    PHOTO_H = H - HDR_H - INFO_H   # photo fills the middle

    buf = io.BytesIO()
    c   = rl.Canvas(buf, pagesize=A4)
    c.setTitle("IL Models Newsletter")

    def draw_page(model):
        # ── Full background ──
        c.setFillColor(BG)
        c.rect(0, 0, W, H, fill=1, stroke=0)

        # ── HEADER ──
        # Gold top bar (3mm)
        c.setFillColor(GOLD)
        c.rect(0, H - 3*mm, W, 3*mm, fill=1, stroke=0)
        # Header background
        c.setFillColor(DARK)
        c.rect(0, H - HDR_H, W, HDR_H - 3*mm, fill=1, stroke=0)
        # Gold bottom line of header
        c.setFillColor(GOLD)
        c.rect(0, H - HDR_H, W, 0.6*mm, fill=1, stroke=0)

        # Logo — "IL · MODELS"
        logo_y = H - HDR_H + 6*mm
        c.setFont("Helvetica-Bold", 17)
        c.setFillColor(WHITE)
        c.drawString(M, logo_y, "IL")
        c.setFillColor(GOLD)
        c.setFont("Helvetica-Bold", 17)
        c.drawString(M + 19, logo_y, "·")
        c.setFillColor(WHITE)
        c.drawString(M + 28, logo_y, "MODELS")

        # Custom title on the right
        hdr_right = title.upper() if title else time.strftime("Newsletter  ·  %B %Y").upper()
        c.setFont("Helvetica", 8)
        c.setFillColor(SILVER)
        c.drawRightString(W - M, logo_y, hdr_right)

        # ── PHOTO ──
        py = INFO_H
        img = fetch_img(model.get("photo_url") or model.get("thumb", ""))
        if img:
            c.drawImage(ImageReader(img), 0, py, width=W, height=PHOTO_H,
                        preserveAspectRatio=True, anchor="n", mask="auto")
        else:
            c.setFillColor(HexColor("#1A1A1A"))
            c.rect(0, py, W, PHOTO_H, fill=1, stroke=0)
            c.setFillColor(SILVER); c.setFont("Helvetica", 14)
            c.drawCentredString(W/2, py + PHOTO_H/2, "No photo")

        # Gradient overlay at photo bottom (dark fade into info strip)
        steps = 18
        for i in range(steps):
            alpha = i / steps
            grey = int(10 + alpha * 5)
            c.setFillColor(HexColor(f"#{grey:02x}{grey:02x}{grey:02x}"))
            c.setFillAlpha(alpha * 0.7)
            band_h = 18 * mm / steps
            c.rect(0, py + i * band_h, W, band_h + 0.5, fill=1, stroke=0)
        c.setFillAlpha(1.0)

        # Clickable photo → model page
        url = model.get("url", "")
        if url:
            c.linkURL(url, (0, py, W, py + PHOTO_H))

        # ── INFO STRIP ──
        c.setFillColor(DARK2)
        c.rect(0, 0, W, INFO_H, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.rect(0, INFO_H - 0.5*mm, W, 0.5*mm, fill=1, stroke=0)

        # Name
        name = model.get("name", "")
        c.setFont("Helvetica-Bold", 22)
        c.setFillColor(WHITE)
        c.drawString(M, INFO_H - 13*mm, name[:32])

        # Stats — split into rows of 4 items each
        raw = model.get("stats", "")
        stat_items = [s.strip() for s in raw.split("|") if s.strip()]
        PER_ROW = 4
        rows = [stat_items[i:i+PER_ROW] for i in range(0, len(stat_items), PER_ROW)]

        c.setFont("Helvetica", 8)
        c.setFillColor(SILVER)
        stat_y = INFO_H - 21*mm
        for row in rows[:4]:
            line = "   |   ".join(row)
            c.drawString(M, stat_y, line)
            stat_y -= 5*mm

        # Instagram button
        insta = model.get("insta", "")
        if insta:
            handle = insta.lstrip("@")
            btn_w  = 70*mm
            btn_h  = 10*mm
            btn_x  = M
            btn_y  = 7*mm

            # Instagram pink/purple background
            c.setFillColor(HexColor("#C13584"))
            c.roundRect(btn_x, btn_y, btn_w, btn_h, 2.5*mm, fill=1, stroke=0)

            # Camera icon (simple rounded square outline)
            ix = btn_x + 3.8*mm
            iy = btn_y + 2.3*mm
            isz = 5.4*mm
            c.setStrokeColor(WHITE)
            c.setLineWidth(0.7)
            c.roundRect(ix, iy, isz, isz, 1*mm, fill=0, stroke=1)
            c.setLineWidth(0.55)
            c.circle(ix + isz/2, iy + isz/2, 1.5*mm, fill=0, stroke=1)
            c.setFillColor(WHITE)
            c.circle(ix + isz - 1.2*mm, iy + isz - 1.2*mm, 0.45*mm, fill=1, stroke=0)

            # Label
            c.setFont("Helvetica-Bold", 9)
            c.setFillColor(WHITE)
            c.drawString(btn_x + 12*mm, btn_y + 3.3*mm, f"Instagram   @{handle}")

            # Link
            c.linkURL(f"https://instagram.com/{handle}",
                      (btn_x, btn_y, btn_x + btn_w, btn_y + btn_h))

        # Page URL hint bottom-right
        c.setFont("Helvetica", 7)
        c.setFillColor(HexColor("#444"))
        c.drawRightString(W - M, 3.5*mm, "ilmodel.com")

    for i, model in enumerate(models):
        draw_page(model)
        if i < len(models) - 1:
            c.showPage()

    c.save(); buf.seek(0); return buf

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/models")
def api_models():
    if _cache:
        return jsonify(_cache)
    threading.Thread(target=run_fetch, daemon=True).start()
    return jsonify({"error": "loading"}), 503

@app.route("/api/status")
def api_status():
    return jsonify({
        "running":     _fetch_state["running"],
        "done":        _fetch_state["done"],
        "total":       _fetch_state["total"],
        "has_data":    _cache is not None,
        "fetched_at":  _cache.get("fetched_at") if _cache else None,
    })

@app.route("/api/refresh")
def api_refresh():
    if not _fetch_state["running"]:
        threading.Thread(target=run_fetch, daemon=True).start()
    return jsonify({"status": "started"})

@app.route("/api/model-photos/<slug>")
def api_model_photos(slug):
    """Return all photos for a single model (fetched live)."""
    try:
        r = req.get(f"{BASE}/{slug}/", headers=UA, timeout=12)
        if r.ok:
            data   = extract_page(r.text, slug)
            photos = [p for p in data["photos"] if "favicon" not in p]
            return jsonify({"photos": photos})
    except Exception as e:
        print(f"  model-photos [{slug}]: {e}")
    return jsonify({"photos": []})

@app.route("/api/generate", methods=["POST"])
def api_generate():
    data   = request.get_json(force=True) or {}
    models = data.get("models", [])
    title  = data.get("title", "")
    if not models:
        return jsonify({"error": "No models"}), 400
    try:
        pdf  = build_pdf(models, title=title)
        resp = make_response(pdf.read())
        resp.headers["Content-Type"]        = "application/pdf"
        resp.headers["Content-Disposition"] = f'attachment; filename="il-models-{time.strftime("%Y%m%d")}.pdf"'
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Start ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"🚀 Starting on port {PORT}")
    threading.Thread(target=run_fetch, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False)
