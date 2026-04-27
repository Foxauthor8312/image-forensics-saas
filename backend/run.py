from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, json, hashlib
import numpy as np

from PIL import Image, ImageChops, ImageEnhance, ImageFilter
from PIL.ExifTags import TAGS, GPSTAGS

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

# =========================
# HASH
# =========================
def generate_file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

# =========================
# EXIF EXTRACTION
# =========================
def extract_exif(path):
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return {}, None

        meta, gps_data = {}, {}

        for tag, val in exif.items():
            name = TAGS.get(tag, tag)
            meta[name] = val

            if name == "GPSInfo":
                for t in val:
                    gps_data[GPSTAGS.get(t, t)] = val[t]

        def convert(c):
            return c[0][0]/c[0][1] + c[1][0]/c[1][1]/60 + c[2][0]/c[2][1]/3600

        gps = None
        if "GPSLatitude" in gps_data and "GPSLongitude" in gps_data:
            lat = convert(gps_data["GPSLatitude"])
            lon = convert(gps_data["GPSLongitude"])

            if gps_data.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps_data.get("GPSLongitudeRef") == "W":
                lon = -lon

            gps = {"lat": lat, "lon": lon, "source": "EXIF"}

        return meta, gps
    except:
        return {}, None

# =========================
# ANALYSIS
# =========================
def ela_score(img, path):
    temp = path+"_temp.jpg"
    img.save(temp, "JPEG", quality=90)
    diff = ImageChops.difference(img, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)
    return np.mean(np.array(ela.convert("L")))/255*100, ela

def noise_score(img):
    g = np.array(img.convert("L"))
    blur = Image.fromarray(g).filter(ImageFilter.GaussianBlur(3))
    return np.std(np.abs(g-np.array(blur)))/255*100

def edge_score(img):
    return np.mean(np.array(img.filter(ImageFilter.FIND_EDGES).convert("L")))/255*100

def block_score(img):
    g = np.array(img.convert("L"))
    blocks=[np.std(g[y:y+8,x:x+8]) for y in range(0,g.shape[0]-8,8) for x in range(0,g.shape[1]-8,8)]
    return np.std(blocks)/255*100

def metadata_score(meta):
    txt=str(meta).lower()
    if "photoshop" in txt or "adobe" in txt: return 80
    return 30

def combine(s):
    w={"ela":0.3,"noise":0.2,"edge":0.2,"block":0.2,"meta":0.1}
    score=sum(s[k]*w[k] for k in w)
    conf=100-np.std(list(s.values()))
    return int(score), int(max(0,min(100,conf)))

# =========================
# EXPLANATION (FULL STRUCTURE)
# =========================
def explain(score):
    if score > 70:
        return {
            "simple": "Strong signs of manipulation detected.",
            "technical": "Multiple forensic signals indicate inconsistencies in compression, noise, and structure.",
            "legal": "The image demonstrates characteristics consistent with digital alteration.",
            "confidence_note": "High confidence due to strong agreement across detection methods."
        }
    elif score > 40:
        return {
            "simple": "Possible editing detected.",
            "technical": "Moderate inconsistencies detected across several forensic indicators.",
            "legal": "The image may have undergone editing or recompression.",
            "confidence_note": "Moderate confidence; further validation recommended."
        }
    else:
        return {
            "simple": "Image appears original.",
            "technical": "Forensic signals show consistent compression, noise, and structure.",
            "legal": "No indicators of digital manipulation detected.",
            "confidence_note": "High confidence in image integrity."
        }

# =========================
# PDF (FULL VERSION)
# =========================
def generate_pdf(job_id, d):

    path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")
    doc = SimpleDocTemplate(path)
    styles = getSampleStyleSheet()

    c = []

    c.append(Paragraph("Digital Image Forensic Analysis Report", styles["Title"]))
    c.append(Spacer(1,12))

    c.append(Paragraph(f"<b>Result:</b> {d['analysis']}", styles["Normal"]))
    c.append(Paragraph(f"<b>Score:</b> {d['score']}%", styles["Normal"]))
    c.append(Paragraph(f"<b>Confidence:</b> {d['confidence']}%", styles["Normal"]))
    c.append(Spacer(1,12))

    # Images
    orig = os.path.join(UPLOAD_FOLDER, f"{job_id}.jpg")
    heat = os.path.join(UPLOAD_FOLDER, f"{job_id}_heat.jpg")

    if os.path.exists(orig):
        c.append(Paragraph("Original Image", styles["Heading2"]))
        c.append(RLImage(orig, width=400, height=250))
        c.append(Spacer(1,10))

    if os.path.exists(heat):
        c.append(Paragraph("Forensic Heatmap", styles["Heading2"]))
        c.append(RLImage(heat, width=400, height=250))
        c.append(Spacer(1,10))

    # Explanations
    c.append(Paragraph("Summary", styles["Heading2"]))
    c.append(Paragraph(d["simple_explanation"], styles["Normal"]))

    c.append(Paragraph("Technical Analysis", styles["Heading2"]))
    c.append(Paragraph(d["technical_explanation"], styles["Normal"]))

    c.append(Paragraph("Conclusion", styles["Heading2"]))
    c.append(Paragraph(d["legal_explanation"], styles["Normal"]))

    c.append(Paragraph("Confidence Explanation", styles["Heading2"]))
    c.append(Paragraph(d["confidence_note"], styles["Normal"]))

    c.append(Spacer(1,12))

    # Signals
    c.append(Paragraph("Signal Breakdown", styles["Heading2"]))
    for k,v in d["signals"].items():
        c.append(Paragraph(f"{k}: {v}", styles["Normal"]))

    c.append(Spacer(1,12))

    # Metadata
    meta = d["metadata"]["all"]
    c.append(Paragraph("Metadata", styles["Heading2"]))
    for k,v in list(meta.items())[:20]:
        c.append(Paragraph(f"{k}: {v}", styles["Normal"]))

    c.append(Spacer(1,12))

    # GPS
    gps = d["gps"]
    c.append(Paragraph("Location Data", styles["Heading2"]))
    if gps:
        c.append(Paragraph(f"Lat: {gps.get('lat')}", styles["Normal"]))
        c.append(Paragraph(f"Lon: {gps.get('lon')}", styles["Normal"]))
        c.append(Paragraph(f"Source: {gps.get('source')}", styles["Normal"]))
    else:
        c.append(Paragraph("No GPS data", styles["Normal"]))

    c.append(Spacer(1,12))

    # Integrity
    c.append(Paragraph("Forensic Integrity", styles["Heading2"]))
    c.append(Paragraph(f"Hash: {d['integrity']['hash']}", styles["Normal"]))

    c.append(Spacer(1,20))

    c.append(Paragraph("Generated by PixelProof", styles["Normal"]))

    doc.build(c)

    return f"{BASE_URL}/files/{job_id}_report.pdf"

# =========================
# ROUTE
# =========================
@app.route("/api/analyze", methods=["POST"])
def analyze():

    file = request.files["image"]
    fmeta = json.loads(request.form.get("metadata","{}"))
    fgps = json.loads(request.form.get("gps","null"))

    job = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job+".jpg")
    file.save(path)

    img = Image.open(path).convert("RGB")

    bmeta, bgps = extract_exif(path)
    meta = {**fmeta, **bmeta}
    gps = bgps if bgps else fgps

    ela, ela_img = ela_score(img, path)
    noise = noise_score(img)
    edge = edge_score(img)
    block = block_score(img)
    meta_score = metadata_score(meta)

    final, conf = combine({
        "ela": ela,
        "noise": noise,
        "edge": edge,
        "block": block,
        "meta": meta_score
    })

    exp = explain(final)

    heatfile = f"{job}_heat.jpg"
    ela_img.save(os.path.join(UPLOAD_FOLDER, heatfile))

    result = {
        "analysis": "Likely edited" if final>70 else "Possibly edited" if final>40 else "Likely original",
        "score": final,
        "confidence": conf,
        "simple_explanation": exp["simple"],
        "technical_explanation": exp["technical"],
        "legal_explanation": exp["legal"],
        "confidence_note": exp["confidence_note"],
        "signals": {
            "ELA": int(ela),
            "Noise": int(noise),
            "Edges": int(edge),
            "Compression": int(block),
            "Metadata": int(meta_score)
        },
        "metadata": {"available": bool(meta), "all": meta},
        "gps": gps,
        "heatmap": f"{BASE_URL}/files/{heatfile}",
        "integrity": {"hash": generate_file_hash(path)}
    }

    # ✅ THIS LINE WAS MISSING BEFORE — NOW FIXED
    result["pdf_report"] = generate_pdf(job, result)

    return jsonify({"result": result})

@app.route("/files/<f>")
def files(f):
    return send_from_directory(UPLOAD_FOLDER, f)
