from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup
import asyncio
import io
import base64
import re
from datetime import datetime

app = FastAPI(title="RE/MAX Life - Property PDF Generator")

# Embed RE/MAX Life logo as base64 once at startup
import os as _os
_LOGO_B64 = ""
_LOGO_PATH = _os.path.join(_os.path.dirname(__file__), "remax-life-logo.png")
if _os.path.exists(_LOGO_PATH):
    with open(_LOGO_PATH, "rb") as _f:
        _LOGO_B64 = f"data:image/png;base64,{base64.b64encode(_f.read()).decode()}"
LOGO_IMG_DARK = f'<img src="{_LOGO_B64}" style="height:36px;background:#fff;border-radius:6px;padding:4px 10px;" alt="RE/MAX Life" />' if _LOGO_B64 else '<span style="color:#fff;font-weight:900;font-size:18px;">RE/MAX LIFE</span>'
LOGO_IMG_LIGHT = f'<img src="{_LOGO_B64}" style="height:52px;" alt="RE/MAX Life" />' if _LOGO_B64 else '<span style="font-weight:900;font-size:22px;color:#001F5B;">RE/MAX LIFE</span>'
LOGO_IMG_HEADER_SM = f'<img src="{_LOGO_B64}" style="height:26px;background:#fff;border-radius:4px;padding:3px 8px;" alt="RE/MAX Life" />' if _LOGO_B64 else '<span style="color:#fff;font-weight:900;font-size:13px;">RE/MAX LIFE</span>'

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class PropertyRequest(BaseModel):
    urls: List[str]
    client_name: str
    agent_name: str
    language: str = "es"
    doc_date: Optional[str] = None


class PropertyData(BaseModel):
    name: str
    price: str
    area: str
    bedrooms: int
    bathrooms: int
    parking: int
    description: str
    location: str
    images: List[str] = []
    source_url: str


def clean_text(text: str) -> str:
    return " ".join(text.strip().split()) if text else ""


async def fetch_image_as_base64(client: httpx.AsyncClient, url: str) -> str:
    try:
        r = await client.get(url, timeout=10)
        if r.status_code == 200:
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0]
            return f"data:{ct};base64,{base64.b64encode(r.content).decode()}"
    except Exception:
        pass
    return ""


async def scrape_encuentra24(url: str) -> PropertyData:
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=20) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No se pudo acceder a {url}: {str(e)}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # --- Title ---
        title = ""
        for sel in ["h1.adpage__title", "h1[class*='title']", "h1"]:
            el = soup.select_one(sel)
            if el:
                title = clean_text(el.get_text())
                break

        # --- Price ---
        price = ""
        for sel in [
            "[class*='price']", "[class*='Price']",
            "[data-testid*='price']", ".adpage__price"
        ]:
            el = soup.select_one(sel)
            if el:
                txt = clean_text(el.get_text())
                if "$" in txt or "USD" in txt or any(c.isdigit() for c in txt):
                    price = txt
                    break

        # --- Features (area, beds, baths, parking) ---
        area, bedrooms, bathrooms, parking = "", 0, 0, 0

        # Encuentra24 current structure: div.flex.flex-wrap.gap-x-4 > div.flex.flex-col (label|value pairs)
        feature_wrapper = soup.select_one("div.flex.flex-wrap.gap-x-4")
        if feature_wrapper:
            for item in feature_wrapper.select("div.flex.flex-col"):
                spans = item.find_all("span")
                if len(spans) >= 2:
                    label = clean_text(spans[0].get_text()).lower()
                    value = clean_text(spans[1].get_text())
                    if "recámara" in label or "recamara" in label or "bedroom" in label or "habitacion" in label:
                        try:
                            bedrooms = int(float(value.replace(",", ".")))
                        except Exception:
                            pass
                    elif "baño" in label or "bano" in label or "bathroom" in label:
                        try:
                            bathrooms = int(float(value.replace(",", ".")))
                        except Exception:
                            pass
                    elif "parking" in label or "estacionamiento" in label or "garaje" in label:
                        try:
                            parking = int(float(re.findall(r"\d+", value)[0]))
                        except Exception:
                            pass
                    elif "área" in label or "area" in label or "m²" in label or "metros" in label:
                        nums = re.findall(r"[\d,\.]+", value)
                        if nums:
                            area = f"{nums[0].replace(',', '')} m²"
        else:
            # Fallback: generic keyword scan
            feature_map = {
                "recamara": "bedrooms", "bedroom": "bedrooms", "habitacion": "bedrooms",
                "bano": "bathrooms", "bathroom": "bathrooms",
                "estacionamiento": "parking", "parking": "parking", "garaje": "parking",
                "m2": "area", "m²": "area", "metros": "area",
            }
            feature_els = soup.select(
                "[class*='feature'], [class*='Feature'], [class*='attribute'], "
                "[class*='detail'], [class*='Detail'], [class*='spec'], li"
            )
            for el in feature_els:
                txt = clean_text(el.get_text()).lower()
                for kw, field in feature_map.items():
                    if kw in txt:
                        nums = re.findall(r"[\d,\.]+", txt)
                        if nums:
                            val = nums[0].replace(",", "")
                            if field == "area":
                                area = f"{val} m²"
                            elif field == "bedrooms":
                                try:
                                    bedrooms = int(float(val))
                                except Exception:
                                    pass
                            elif field == "bathrooms":
                                try:
                                    bathrooms = int(float(val))
                                except Exception:
                                    pass
                            elif field == "parking":
                                try:
                                    parking = int(float(val))
                                except Exception:
                                    pass

        # --- Description ---
        description = ""
        # Encuentra24 current structure: p.text-sm.text-gray-700
        for sel in [
            "p.text-sm.text-gray-700",
            "[class*='description']", "[class*='Description']",
            "[class*='detail-text']", ".adpage__description", "article p"
        ]:
            el = soup.select_one(sel)
            if el:
                txt = clean_text(el.get_text())
                if len(txt) > 40:
                    description = txt[:400]
                    break

        # --- Location ---
        location = ""
        # Encuentra24 current structure: span.text-muted-foreground with location text, or p.text-sm.font-medium
        for sel in [
            "p.text-sm.font-medium.text-foreground",
            "span.text-muted-foreground.flex.flex-row.items-center",
            "[class*='location']", "[class*='Location']",
            "[class*='address']", "[class*='breadcrumb']"
        ]:
            el = soup.select_one(sel)
            if el:
                loc = clean_text(el.get_text())
                if loc and 5 < len(loc) < 120 and "Inicio" not in loc:
                    location = loc
                    break
        if not location:
            location = "Panamá"

        # --- Images ---
        image_urls = []
        for sel in [
            "img[class*='gallery']", "img[class*='photo']",
            "img[class*='image']", ".swiper-slide img",
            "[class*='gallery'] img", "img[src*='encuentra24']",
            "img[src*='cloudfront']", "img[src*='s3']"
        ]:
            for img in soup.select(sel):
                src = img.get("src") or img.get("data-src") or img.get("data-lazy-src", "")
                if src and src.startswith("http") and src not in image_urls:
                    image_urls.append(src)

        # Fetch up to 4 images as base64
        async with httpx.AsyncClient(headers=HEADERS, timeout=15) as img_client:
            tasks = [fetch_image_as_base64(img_client, u) for u in image_urls[:4]]
            images_b64 = await asyncio.gather(*tasks)
        images = [i for i in images_b64 if i]

        return PropertyData(
            name=title or "Propiedad en Panamá",
            price=price or "Consultar precio",
            area=area or "—",
            bedrooms=bedrooms,
            bathrooms=bathrooms,
            parking=parking,
            description=description or "Propiedad disponible en Panamá.",
            location=location,
            images=images,
            source_url=url,
        )


def format_date(date_str: str, lang: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        d = datetime.now()
    months_es = ["enero","febrero","marzo","abril","mayo","junio",
                 "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    months_en = ["January","February","March","April","May","June",
                 "July","August","September","October","November","December"]
    if lang == "es":
        return f"{d.day} de {months_es[d.month-1]} de {d.year}"
    return f"{months_en[d.month-1]} {d.day}, {d.year}"


def build_html(properties: List[PropertyData], req: PropertyRequest) -> str:
    lang = req.language == "es"
    date_str = format_date(req.doc_date or datetime.now().strftime("%Y-%m-%d"), req.language)

    def img_tag(src, cls=""):
        if src:
            return f'<img src="{src}" class="{cls}" alt="property photo" />'
        return f'<div class="{cls} placeholder"><span>{"Foto" if lang else "Photo"}</span></div>'

    prop_pages = ""
    for i, p in enumerate(properties):
        imgs = p.images + [""] * 4
        prop_pages += f"""
        <div class="page prop-page">
          <header class="prop-header">
            {LOGO_IMG_HEADER_SM}
            <div class="prop-num">{"Propiedad" if lang else "Property"} {i+1} / {len(properties)}</div>
          </header>

          <div class="gallery">
            <div class="gallery-main">{img_tag(imgs[0], "main-img")}</div>
            <div class="gallery-grid">
              {img_tag(imgs[1], "thumb-img")}
              {img_tag(imgs[2], "thumb-img")}
              {img_tag(imgs[3], "thumb-img")}
            </div>
          </div>

          <div class="prop-body">
            <div class="prop-left">
              <h2 class="prop-title">{p.name}</h2>
              <div class="prop-price">{p.price}</div>
              <div class="prop-location">📍 {p.location}</div>
              <p class="prop-desc">{p.description[:300]}</p>
              <a class="prop-link" href="{p.source_url}">{"Ver en Encuentra24 →" if lang else "View on Encuentra24 →"}</a>
            </div>
            <div class="prop-right">
              <div class="spec-card"><span class="spec-val">{p.area}</span><span class="spec-lbl">{"Área" if lang else "Area"}</span></div>
              <div class="spec-card"><span class="spec-val">{p.bedrooms}</span><span class="spec-lbl">{"Recámaras" if lang else "Bedrooms"}</span></div>
              <div class="spec-card"><span class="spec-val">{p.bathrooms}</span><span class="spec-lbl">{"Baños" if lang else "Bathrooms"}</span></div>
              <div class="spec-card"><span class="spec-val">{p.parking}</span><span class="spec-lbl">{"Estac." if lang else "Parking"}</span></div>
            </div>
          </div>

          <footer class="prop-footer">
            <span>{req.agent_name} · RE/MAX Life</span>
            <span>+507 391-9865/662 · Info@remax-life.com.pa</span>
          </footer>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="{req.language}">
<head>
<meta charset="UTF-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;900&family=Inter:wght@400;500&display=swap');
*{{box-sizing:border-box;margin:0;padding:0;}}
html,body{{margin:0;padding:0;}}
body{{font-family:'Inter',sans-serif;background:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact;}}
.page{{width:210mm;height:297mm;page-break-after:always;page-break-inside:avoid;position:relative;display:flex;flex-direction:column;overflow:hidden;}}
@media print{{html,body{{margin:0;padding:0;}} .page{{margin:0;page-break-after:always;page-break-inside:avoid;}} .no-print{{display:none!important;}}}}

/* ── Cover ── */
.cover{{background:#001F5B;color:#fff;}}
.cover-top{{background:linear-gradient(160deg,#001233 0%,#003DA5 100%);flex:1;display:flex;flex-direction:column;justify-content:flex-end;padding:48px;}}
.cover-logo{{margin-bottom:40px;}}
.cover-tagline{{font-size:15px;color:rgba(255,255,255,0.65);max-width:300px;line-height:1.7;}}
.cover-bottom{{background:#fff;padding:44px 48px;}}
.cover-label{{font-size:11px;font-weight:600;letter-spacing:0.15em;color:#999;text-transform:uppercase;margin-bottom:8px;}}
.cover-title{{font-family:'Montserrat',sans-serif;font-size:40px;font-weight:900;color:#001F5B;line-height:1.1;margin-bottom:20px;}}
.cover-client{{font-size:18px;font-weight:600;color:#003DA5;margin-bottom:4px;}}
.cover-meta{{font-size:13px;color:#888;margin-top:20px;}}
.cover-badge{{display:inline-block;background:#003DA5;color:#fff;padding:10px 22px;border-radius:4px;font-size:13px;font-weight:600;margin-top:16px;}}

/* ── Prop pages ── */
.prop-header{{background:#003DA5;padding:10px 32px;display:flex;align-items:center;justify-content:space-between;}}
.prop-num{{font-size:12px;color:rgba(255,255,255,0.7);font-weight:500;}}

.gallery{{display:flex;gap:4px;padding:18px 28px 0;height:195px;}}
.gallery-main{{flex:2;}}
.gallery-grid{{flex:1;display:flex;flex-direction:column;gap:4px;}}
.main-img,.thumb-img{{width:100%;height:100%;object-fit:cover;border-radius:6px;display:block;}}
.placeholder{{background:#E8EEF5;border-radius:6px;display:flex;align-items:center;justify-content:center;}}
.placeholder span{{font-size:11px;color:#aaa;}}

.prop-body{{display:flex;gap:20px;padding:18px 28px;flex:1;}}
.prop-left{{flex:2;}}
.prop-right{{flex:1;display:grid;grid-template-columns:1fr 1fr;gap:8px;align-content:start;padding-top:4px;}}
.prop-title{{font-family:'Montserrat',sans-serif;font-size:19px;font-weight:900;color:#001F5B;margin-bottom:5px;line-height:1.2;}}
.prop-price{{font-family:'Montserrat',sans-serif;font-size:21px;font-weight:700;color:#003DA5;margin-bottom:4px;}}
.prop-location{{font-size:12px;color:#888;margin-bottom:10px;}}
.prop-desc{{font-size:12.5px;color:#444;line-height:1.7;margin-bottom:10px;}}
.prop-link{{display:none;}}
.spec-card{{background:#F0F4FF;border-radius:8px;padding:10px 8px;text-align:center;}}
.spec-val{{display:block;font-family:'Montserrat',sans-serif;font-size:14px;font-weight:700;color:#001F5B;}}
.spec-lbl{{display:block;font-size:9px;color:#888;margin-top:2px;text-transform:uppercase;letter-spacing:0.06em;}}
.prop-footer{{background:#F7F9FF;border-top:1px solid #E0E8F8;padding:10px 28px;display:flex;justify-content:space-between;font-size:11px;color:#666;}}

/* ── Back cover ── */
.back{{background:#001233;color:#fff;align-items:center;justify-content:center;text-align:center;}}
.back-quote{{font-family:'Montserrat',sans-serif;font-size:30px;font-weight:900;line-height:1.25;max-width:340px;margin:0 auto 16px;}}
.back-cta{{font-size:17px;color:rgba(255,255,255,0.6);margin-bottom:44px;}}
.back-contact{{border:1px solid rgba(255,255,255,0.15);border-radius:10px;padding:24px 48px;}}
.back-contact p{{font-size:17px;font-weight:600;margin-bottom:6px;}}
.back-contact span{{font-size:14px;color:rgba(255,255,255,0.6);}}

/* ── Print btn ── */
.print-btn{{position:fixed;bottom:24px;right:24px;background:#003DA5;color:#fff;border:none;border-radius:8px;padding:13px 26px;font-size:15px;font-weight:600;cursor:pointer;z-index:999;box-shadow:0 4px 20px rgba(0,61,165,0.4);}}
</style>
</head>
<body>

<!-- COVER -->
<div class="page cover">
  <div class="cover-top">
    <div class="cover-logo">{LOGO_IMG_DARK}</div>
    <p class="cover-tagline">{"Oportunidades únicas en los destinos más rentables de Panamá" if lang else "Unique real estate opportunities in Panama's most profitable destinations"}</p>
  </div>
  <div class="cover-bottom">
    <div style="margin-bottom:20px;">{LOGO_IMG_LIGHT}</div>
    <div class="cover-label">{"Selección exclusiva" if lang else "Exclusive selection"}</div>
    <div class="cover-title">{"Propiedades\nseleccionadas" if lang else "Selected\nproperties"}</div>
    <div class="cover-label">{"Preparado para" if lang else "Prepared for"}</div>
    <div class="cover-client">{req.client_name}</div>
    <div class="cover-badge">+507 391-9865/662 · Info@remax-life.com.pa</div>
    <div class="cover-meta">{"Presentado por" if lang else "Presented by"}: {req.agent_name} &nbsp;·&nbsp; {date_str}</div>
  </div>
</div>

{prop_pages}

<!-- BACK COVER -->
<div class="page back">
  <div class="back-quote">Every great move begins with a conversation.</div>
  <div class="back-cta">Let's talk.</div>
  <div class="back-contact">
    <p>+507 391-9865/662</p>
    <span>Info@remax-life.com.pa</span>
  </div>
</div>

<button class="print-btn no-print" onclick="window.print()">⬇ {"Descargar PDF" if lang else "Download PDF"}</button>
</body>
</html>"""


@app.get("/")
def root():
    return {"status": "RE/MAX Life Property Generator API", "version": "1.0"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/scrape")
async def scrape_property(url: str):
    data = await scrape_encuentra24(url)
    return data


@app.post("/generate")
async def generate_pdf(req: PropertyRequest):
    if not req.urls:
        raise HTTPException(status_code=400, detail="Se requiere al menos un URL.")
    if len(req.urls) > 10:
        raise HTTPException(status_code=400, detail="Máximo 10 propiedades por documento.")

    tasks = [scrape_encuentra24(url) for url in req.urls]
    try:
        properties = await asyncio.gather(*tasks)
    except HTTPException as e:
        raise e

    html = build_html(list(properties), req)

    safe_name = req.client_name.replace(" ", "-").replace("/", "-")[:30]
    filename = f"REMAX-Life_{safe_name}_{req.doc_date or 'doc'}.html"

    return StreamingResponse(
        io.BytesIO(html.encode("utf-8")),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
