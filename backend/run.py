# FULL BACKEND — CLEAN + COMPLETE

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os, json, io
import numpy as np
import cv2
from PIL import Image
from datetime import datetime
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD = "uploads"
HEAT = "heatmaps"
os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(HEAT, exist_ok=True)

def score(m): return float(np.mean(m))/255*100

def analyze_image(path):
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # signals
    ela = cv2.absdiff(img, cv2.imdecode(cv2.imencode(".jpg", img)[1],1))
    ela = cv2.cvtColor(ela, cv2.COLOR_BGR2GRAY)

    noise = cv2.absdiff(gray, cv2.GaussianBlur(gray,(3,3),0))
    edges = cv2.Canny(gray,100,200)
    comp = cv2.Laplacian(gray, cv2.CV_64F)

    ela_s, noise_s, edge_s, comp_s = map(score,[ela,noise,edges,np.abs(comp)])

    signals = {
        "ELA":round(ela_s),
        "Noise":round(noise_s),
        "Edges":round(edge_s),
        "Compression":round(comp_s),
        "Metadata":20
    }

    score_avg = round(np.mean(list(signals.values())))
    confidence = round(100-np.std(list(signals.values())))

    # heatmap
    combo = (ela+noise+edges+np.abs(comp)).astype(np.float32)
    combo = cv2.normalize(combo,None,0,255,cv2.NORM_MINMAX).astype(np.uint8)
    heat = cv2.applyColorMap(combo, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(img,0.6,heat,0.4,0)

    fname = f"{datetime.utcnow().timestamp()}.jpg"
    path_h = os.path.join(HEAT,fname)
    cv2.imwrite(path_h, overlay)

    return {
        "analysis":"Analysis Complete",
        "score":score_avg,
        "confidence":confidence,
        "simple_explanation":"Signal-based analysis complete.",
        "technical_explanation":"ELA, noise, edge, compression evaluated.",
        "legal_explanation":"Not a definitive forensic conclusion.",
        "confidence_note":"Agreement between signals.",
        "signals":signals,
        "heatmap":f"/api/heatmap/{fname}"
    }

@app.route("/")
def home():
    return "Backend OK"

@app.route("/api/heatmap/<f>")
def heatmap(f):
    return send_file(os.path.join(HEAT,f), mimetype="image/jpeg")

@app.route("/api/analyze", methods=["POST"])
def analyze():
    img = request.files["image"]
    fname = f"{datetime.utcnow().timestamp()}_{img.filename}"
    path = os.path.join(UPLOAD,fname)
    img.save(path)

    metadata = json.loads(request.form.get("metadata","{}"))
    gps = json.loads(request.form.get("gps","null"))

    result = analyze_image(path)
    result["metadata"]={"all":metadata}
    result["gps"]=gps

    return jsonify({"result":result})

@app.route("/api/pdf", methods=["POST"])
def pdf():
    data=request.json
    buf=io.BytesIO()
    doc=SimpleDocTemplate(buf)
    styles=getSampleStyleSheet()
    story=[]

    story.append(Paragraph("PixelProof Report",styles["Title"]))
    story.append(Spacer(1,10))
    story.append(Paragraph(f"Score: {data['score']}%",styles["Normal"]))
    story.append(Paragraph(f"Confidence: {data['confidence']}%",styles["Normal"]))

    doc.build(story)
    buf.seek(0)
    return send_file(buf,as_attachment=True,download_name="report.pdf",mimetype="application/pdf")

if __name__=="__main__":
    app.run(host="0.0.0.0",port=5000)
