from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os, json, io, cv2, numpy as np
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph

app = Flask(__name__)
CORS(app)

UP, HM = "uploads", "heatmaps"
os.makedirs(UP, exist_ok=True)
os.makedirs(HM, exist_ok=True)

# ---------- CORE IMAGE ANALYSIS ----------
def analyze(path):
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    ops = {
        "ELA": cv2.absdiff(img, cv2.imdecode(cv2.imencode(".jpg", img)[1],1)),
        "Noise": cv2.absdiff(gray, cv2.GaussianBlur(gray,(3,3),0)),
        "Edges": cv2.Canny(gray,100,200),
        "Compression": np.abs(cv2.Laplacian(gray, cv2.CV_64F))
    }

    score = lambda m: float(np.mean(m))/255*100
    signals = {k: round(score(v)) for k,v in ops.items()}
    signals["Metadata"] = 20

    s_vals = list(signals.values())
    total = round(np.mean(s_vals))
    conf = round(100 - np.std(s_vals))

    combo = sum([v.astype(np.float32) for v in ops.values()])
    combo = cv2.normalize(combo,None,0,255,cv2.NORM_MINMAX).astype(np.uint8)

    heat = cv2.applyColorMap(combo, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(img,0.6,heat,0.4,0)

    name = f"{datetime.utcnow().timestamp()}.jpg"
    cv2.imwrite(os.path.join(HM,name), overlay)

    return {
        "analysis":"Analysis Complete",
        "score":total,
        "confidence":conf,
        "simple_explanation":"Signal analysis completed.",
        "technical_explanation":"ELA, noise, edges, compression used.",
        "legal_explanation":"Not a definitive forensic conclusion.",
        "confidence_note":"Signal agreement level.",
        "signals":signals,
        "heatmap":f"/api/heatmap/{name}"
    }

# ---------- ROUTES ----------
@app.route("/")
def home(): return "Backend OK"

@app.route("/api/heatmap/<f>")
def heatmap(f): return send_file(os.path.join(HM,f), mimetype="image/jpeg")

@app.route("/api/analyze", methods=["POST"])
def run():
    img = request.files["image"]
    path = os.path.join(UP, f"{datetime.utcnow().timestamp()}_{img.filename}")
    img.save(path)

    meta = json.loads(request.form.get("metadata","{}"))
    gps = json.loads(request.form.get("gps","null"))

    res = analyze(path)
    res["metadata"] = {"all": meta}
    res["gps"] = gps

    return jsonify({"result": res})

@app.route("/api/pdf", methods=["POST"])
def pdf():
    d = request.json
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf)

    story = [
        Paragraph("PixelProof Report", None),
        Paragraph(f"Score: {d['score']}%", None),
        Paragraph(f"Confidence: {d['confidence']}%", None)
    ]

    doc.build(story)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="report.pdf")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
