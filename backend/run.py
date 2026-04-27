# run.py (LOCKED)

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os, json, io
import numpy as np
import cv2
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

UP, HM = "uploads", "heatmaps"
os.makedirs(UP, exist_ok=True)
os.makedirs(HM, exist_ok=True)

def _score(m): return float(np.mean(m))/255*100

def analyze_image(path):
    img = cv2.imread(path)
    if img is None:
        raise ValueError("Invalid image")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    ela = cv2.absdiff(img, cv2.imdecode(cv2.imencode(".jpg", img)[1], 1))
    ela = cv2.cvtColor(ela, cv2.COLOR_BGR2GRAY)

    noise = cv2.absdiff(gray, cv2.GaussianBlur(gray,(3,3),0))
    edges = cv2.Canny(gray,100,200)
    comp  = np.abs(cv2.Laplacian(gray, cv2.CV_64F)).astype(np.uint8)

    ops = {"ELA": ela, "Noise": noise, "Edges": edges, "Compression": comp}
    signals = {k: round(_score(v)) for k,v in ops.items()}
    signals["Metadata"] = 20

    vals = list(signals.values())
    score = round(np.mean(vals))
    confidence = int(max(0, min(100, round(100 - np.std(vals)))))

    combo = sum([v.astype(np.float32) for v in ops.values()])
    combo = cv2.normalize(combo, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    heat  = cv2.applyColorMap(combo, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(img, 0.6, heat, 0.4, 0)

    name = f"{datetime.utcnow().timestamp()}.jpg"
    cv2.imwrite(os.path.join(HM, name), overlay)

    return {
        "analysis": "Analysis Complete",
        "score": score,
        "confidence": confidence,
        "simple_explanation": "Signal-based analysis complete.",
        "technical_explanation": "ELA, noise, edges, and compression evaluated.",
        "legal_explanation": "Not a definitive forensic conclusion.",
        "confidence_note": "Confidence reflects agreement between signals.",
        "signals": signals,
        "heatmap": f"/api/heatmap/{name}"
    }

@app.route("/")
def home():
    return "Backend OK"

@app.route("/api/heatmap/<fname>")
def heatmap(fname):
    return send_file(os.path.join(HM, fname), mimetype="image/jpeg")

@app.route("/api/analyze", methods=["POST"])
def analyze():
    if "image" not in request.files:
        return jsonify({"error":"No image"}), 400

    img = request.files["image"]
    path = os.path.join(UP, f"{datetime.utcnow().timestamp()}_{img.filename}")
    img.save(path)

    try:
        metadata = json.loads(request.form.get("metadata","{}"))
    except:
        metadata = {}

    try:
        gps = json.loads(request.form.get("gps","null"))
    except:
        gps = None

    result = analyze_image(path)
    result["metadata"] = {"all": metadata}
    result["gps"] = gps

    return jsonify({"result": result})

@app.route("/api/pdf", methods=["POST"])
def pdf():
    data = request.json or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("PixelProof Report", styles["Title"]))
    story.append(Spacer(1,10))
    story.append(Paragraph(f"Score: {data.get('score',0)}%", styles["Normal"]))
    story.append(Paragraph(f"Confidence: {data.get('confidence',0)}%", styles["Normal"]))
    story.append(Spacer(1,10))

    for k,v in (data.get("signals") or {}).items():
        story.append(Paragraph(f"{k}: {v}%", styles["Normal"]))

    # embed heatmap if reachable
    heatmap_url = data.get("heatmap")
    if heatmap_url:
        try:
            import requests
            r = requests.get(heatmap_url, timeout=5)
            if r.ok:
                img = RLImage(io.BytesIO(r.content), width=300, height=200)
                story.append(Spacer(1,10))
                story.append(img)
        except:
            pass

    doc.build(story)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="report.pdf", mimetype="application/pdf")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
