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
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

# =========================
# EXIF EXTRACTION (FIXED)
# =========================
def extract_exif(path):
    try:
        image = Image.open(path)
        exif_data = image._getexif()

        if not exif_data:
            return {}, None

        metadata = {}
        gps_data = {}

        for tag, value in exif_data.items():
            tag_name = TAGS.get(tag, tag)
            metadata[tag_name] = value

            if tag_name == "GPSInfo":
                for t in value:
                    sub_tag = GPSTAGS.get(t, t)
                    gps_data[sub_tag] = value[t]

        def convert(coord):
            d = coord[0][0] / coord[0][1]
            m = coord[1][0] / coord[1][1]
            s = coord[2][0] / coord[2][1]
            return d + (m / 60.0) + (s / 3600.0)

        gps = None

        if "GPSLatitude" in gps_data and "GPSLongitude" in gps_data:
            lat = convert(gps_data["GPSLatitude"])
            lon = convert(gps_data["GPSLongitude"])

            if gps_data.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps_data.get("GPSLongitudeRef") == "W":
                lon = -lon

            gps = {"lat": lat, "lon": lon, "source": "EXIF"}

        return metadata, gps

    except:
        return {}, None

# =========================
# ANALYSIS METHODS
# =========================
def ela_score(image, path):
    temp = path + "_temp.jpg"
    image.save(temp, "JPEG", quality=90)
    diff = ImageChops.difference(image, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)
    gray = np.array(ela.convert("L"))
    return np.mean(gray)/255*100, ela

def noise_score(image):
    gray = np.array(image.convert("L"))
    blur = Image.fromarray(gray).filter(ImageFilter.GaussianBlur(3))
    noise = np.abs(gray - np.array(blur))
    return np.std(noise)/255*100

def edge_score(image):
    edges = image.filter(ImageFilter.FIND_EDGES)
    return np.mean(np.array(edges.convert("L")))/255*100

def block_score(image):
    gray = np.array(image.convert("L"))
    blocks=[]
    for y in range(0,gray.shape[0]-8,8):
        for x in range(0,gray.shape[1]-8,8):
            blocks.append(np.std(gray[y:y+8,x:x+8]))
    return np.std(blocks)/255*100

def metadata_score(meta):
    if not meta: return 10
    txt = str(meta).lower()
    if "photoshop" in txt or "adobe" in txt: return 80
    return 30

def combine(scores):
    weights={"ela":0.3,"noise":0.2,"edge":0.2,"block":0.2,"meta":0.1}
    total=sum(scores[k]*weights[k] for k in weights)
    confidence=100-np.std(list(scores.values()))
    return int(total), int(max(0,min(100,confidence)))

# =========================
# EXPLANATION
# =========================
def explain(score):
    if score>70:
        return {
            "simple":"Strong signs of manipulation detected.",
            "technical":"Multiple forensic signals show inconsistencies.",
            "legal":"The image shows characteristics of digital alteration.",
            "confidence_note":"High confidence."
        }
    elif score>40:
        return {
            "simple":"Possible editing detected.",
            "technical":"Moderate inconsistencies detected.",
            "legal":"The image may have been altered.",
            "confidence_note":"Moderate confidence."
        }
    else:
        return {
            "simple":"Image appears original.",
            "technical":"Signals are consistent.",
            "legal":"No manipulation detected.",
            "confidence_note":"High confidence."
        }

# =========================
# PDF
# =========================
def generate_pdf(job_id, data):
    path = os.path.join(UPLOAD_FOLDER, f"{job_id}.pdf")
    doc = SimpleDocTemplate(path)
    styles = getSampleStyleSheet()
    content = []

    original = os.path.join(UPLOAD_FOLDER, f"{job_id}.jpg")
    heatmap = os.path.join(UPLOAD_FOLDER, f"{job_id}_heat.jpg")

    content.append(Paragraph("Forensic Report", styles["Title"]))
    content.append(Spacer(1,12))

    content.append(Paragraph(f"Result: {data['analysis']}", styles["Normal"]))
    content.append(Paragraph(f"Score: {data['score']}%", styles["Normal"]))
    content.append(Paragraph(f"Confidence: {data['confidence']}%", styles["Normal"]))
    content.append(Spacer(1,12))

    if os.path.exists(original):
        content.append(RLImage(original, width=400, height=250))
    if os.path.exists(heatmap):
        content.append(RLImage(heatmap, width=400, height=250))

    content.append(Spacer(1,12))

    content.append(Paragraph(data["technical_explanation"], styles["Normal"]))
    content.append(Spacer(1,12))

    for k,v in data["signals"].items():
        content.append(Paragraph(f"{k}: {v}", styles["Normal"]))

    content.append(Spacer(1,12))
    content.append(Paragraph("Generated by PixelProof", styles["Normal"]))

    doc.build(content)
    return f"{BASE_URL}/files/{job_id}.pdf"

# =========================
# ROUTE
# =========================
@app.route("/api/analyze", methods=["POST"])
def analyze():

    file = request.files["image"]
    frontend_meta = json.loads(request.form.get("metadata","{}"))
    frontend_gps = json.loads(request.form.get("gps","null"))

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id+".jpg")
    file.save(path)

    img = Image.open(path).convert("RGB")

    backend_meta, backend_gps = extract_exif(path)

    metadata = {**frontend_meta, **backend_meta}
    gps = backend_gps if backend_gps else frontend_gps

    ela, ela_img = ela_score(img, path)
    noise = noise_score(img)
    edge = edge_score(img)
    block = block_score(img)
    meta = metadata_score(metadata)

    scores = {
        "ELA": int(ela),
        "Noise": int(noise),
        "Edges": int(edge),
        "Compression": int(block),
        "Metadata": int(meta)
    }

    final, conf = combine({
        "ela": ela,
        "noise": noise,
        "edge": edge,
        "block": block,
        "meta": meta
    })

    exp = explain(final)

    heatfile = f"{job_id}_heat.jpg"
    ela_img.save(os.path.join(UPLOAD_FOLDER, heatfile))

    result = {
        "analysis": "Likely edited" if final>70 else "Possibly edited" if final>40 else "Likely original",
        "score": final,
        "confidence": conf,
        "simple_explanation": exp["simple"],
        "technical_explanation": exp["technical"],
        "legal_explanation": exp["legal"],
        "confidence_note": exp["confidence_note"],
        "signals": scores,
        "metadata": {"available": bool(metadata), "all": metadata},
        "gps": gps,
        "heatmap": f"{BASE_URL}/files/{heatfile}",
        "integrity": {"hash": generate_file_hash(path)}
    }

    result["pdf_report"] = generate_pdf(job_id, result)

    return jsonify({"result": result})

@app.route("/files/<f>")
def files(f):
    return send_from_directory(UPLOAD_FOLDER, f)
