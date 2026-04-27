import os
import io
import json
import base64
from datetime import datetime

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

import numpy as np
import cv2
from PIL import Image

# PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import letter

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

UPLOAD_FOLDER = "uploads"
HEATMAP_FOLDER = "heatmaps"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(HEATMAP_FOLDER, exist_ok=True)


# -------------------------------
# IMAGE UTILS
# -------------------------------
def load_image_cv(path):
    img = cv2.imread(path)
    if img is None:
        raise ValueError("Invalid image")
    return img


def compute_ela(image, quality=90):
    # convert to JPEG in-memory
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    _, enc = cv2.imencode(".jpg", image, encode_param)
    compressed = cv2.imdecode(enc, 1)

    ela = cv2.absdiff(image, compressed)
    ela = cv2.cvtColor(ela, cv2.COLOR_BGR2GRAY)
    ela = cv2.normalize(ela, None, 0, 255, cv2.NORM_MINMAX)
    return ela


def compute_noise(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    noise = cv2.absdiff(gray, blur)
    return noise


def compute_edges(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 100, 200)
    return edges


def compute_compression(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return np.uint8(np.absolute(lap))


def score_from_map(m):
    return float(np.mean(m)) / 255 * 100


def create_heatmap(base, maps):
    combined = np.zeros_like(base[:, :, 0], dtype=np.float32)

    for m in maps:
        m = cv2.resize(m, (base.shape[1], base.shape[0]))
        combined += m.astype(np.float32)

    combined /= len(maps)
    combined = cv2.normalize(combined, None, 0, 255, cv2.NORM_MINMAX)
    combined = np.uint8(combined)

    heat = cv2.applyColorMap(combined, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(base, 0.6, heat, 0.4, 0)

    return heat, overlay


# -------------------------------
# ANALYSIS ENGINE
# -------------------------------
def analyze_image(path):
    img = load_image_cv(path)

    ela = compute_ela(img)
    noise = compute_noise(img)
    edges = compute_edges(img)
    comp = compute_compression(img)

    ela_s = score_from_map(ela)
    noise_s = score_from_map(noise)
    edges_s = score_from_map(edges)
    comp_s = score_from_map(comp)

    signals = {
        "ELA": round(ela_s),
        "Noise": round(noise_s),
        "Edges": round(edges_s),
        "Compression": round(comp_s),
        "Metadata": 20  # placeholder
    }

    score = round(np.mean(list(signals.values())))
    confidence = round(100 - np.std(list(signals.values())))

    # heatmap
    heat, overlay = create_heatmap(img, [ela, noise, edges, comp])

    fname = f"{datetime.utcnow().timestamp()}.jpg"
    heat_path = os.path.join(HEATMAP_FOLDER, fname)
    cv2.imwrite(heat_path, overlay)

    heat_url = f"/api/heatmap/{fname}"

    return {
        "analysis": "Analysis Complete",
        "score": score,
        "confidence": confidence,
        "simple_explanation": "Automated signal analysis completed.",
        "technical_explanation": "ELA, noise, edge, and compression signals evaluated.",
        "legal_explanation": "Not a definitive forensic conclusion.",
        "confidence_note": "Confidence reflects signal agreement.",
        "signals": signals,
        "heatmap": heat_url
    }


# -------------------------------
# ROUTES
# -------------------------------
@app.route("/")
def home():
    return "PixelProof backend running"


@app.route("/api/heatmap/<filename>")
def serve_heatmap(filename):
    path = os.path.join(HEATMAP_FOLDER, filename)
    return send_file(path, mimetype="image/jpeg")


@app.route("/api/analyze", methods=["POST"])
def analyze():

    if "image" not in request.files:
        return jsonify({"error": "No image"}), 400

    image = request.files["image"]
    fname = f"{datetime.utcnow().timestamp()}_{image.filename}"
    path = os.path.join(UPLOAD_FOLDER, fname)
    image.save(path)

    metadata_raw = request.form.get("metadata")
    gps_raw = request.form.get("gps")

    try:
        metadata = json.loads(metadata_raw) if metadata_raw else {}
    except:
        metadata = {}

    try:
        gps = json.loads(gps_raw) if gps_raw else None
    except:
        gps = None

    result = analyze_image(path)

    result["metadata"] = {"all": metadata}
    result["gps"] = gps

    return jsonify({"result": result})


# -------------------------------
# PDF EXPORT
# -------------------------------
@app.route("/api/pdf", methods=["POST"])
def generate_pdf():

    data = request.json

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()

    content = []

    content.append(Paragraph("PixelProof Report", styles["Title"]))
    content.append(Spacer(1, 10))

    content.append(Paragraph(f"Score: {data.get('score')}%", styles["Normal"]))
    content.append(Paragraph(f"Confidence: {data.get('confidence')}%", styles["Normal"]))
    content.append(Spacer(1, 10))

    for k, v in data.get("signals", {}).items():
        content.append(Paragraph(f"{k}: {v}%", styles["Normal"]))

    content.append(Spacer(1, 10))

    heatmap_url = data.get("heatmap")
    if heatmap_url:
        try:
            import requests
            r = requests.get(heatmap_url)
            img = RLImage(io.BytesIO(r.content), width=300, height=200)
            content.append(img)
        except:
            pass

    doc.build(content)
    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="report.pdf", mimetype="application/pdf")


# -------------------------------
# START
# -------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
