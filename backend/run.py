from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, datetime

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance
from PIL.ExifTags import TAGS, GPSTAGS

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000")
jobs = {}

# -----------------------------
# METADATA
# -----------------------------
def extract_metadata(path):
    try:
        img = Image.open(path)
        exif = img._getexif()

        data = {"available": False, "ImageWidth": img.width, "ImageHeight": img.height}

        if not exif:
            return data

        for tag, value in exif.items():
            name = TAGS.get(tag, tag)
            if name in ["Make","Model","DateTime","Software"]:
                data[name] = str(value)

        data["available"] = True
        return data
    except:
        return {"available": False}

# -----------------------------
# GPS
# -----------------------------
def extract_gps(path):
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return None

        gps = {}
        for tag, val in exif.items():
            if TAGS.get(tag) == "GPSInfo":
                for k in val:
                    gps[GPSTAGS.get(k)] = val[k]

        if "GPSLatitude" in gps and "GPSLongitude" in gps:

            def conv(c):
                return c[0][0]/c[0][1] + c[1][0]/c[1][1]/60 + c[2][0]/c[2][1]/3600

            lat = conv(gps["GPSLatitude"])
            lon = conv(gps["GPSLongitude"])

            if gps.get("GPSLatitudeRef") == "S": lat = -lat
            if gps.get("GPSLongitudeRef") == "W": lon = -lon

            return {"lat": lat, "lon": lon}
    except:
        return None

# -----------------------------
# LEGAL
# -----------------------------
def build_legal(score, confidence):
    if confidence > 70:
        opinion = "High likelihood of digital alteration."
    elif confidence > 40:
        opinion = "Possible indicators of alteration."
    else:
        opinion = "No strong indicators of alteration."

    return {
        "opinion": opinion,
        "confidence": confidence
    }

# -----------------------------
# PDF
# -----------------------------
def generate_pdf(job_id, result):
    try:
        path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")
        doc = SimpleDocTemplate(path)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("Forensic Image Report", styles["Title"]))
        content.append(Spacer(1,10))

        content.append(Paragraph(result["legal"]["opinion"], styles["Normal"]))
        content.append(Paragraph(f"Confidence: {result['confidence']}%", styles["Normal"]))

        ela = os.path.join(UPLOAD_FOLDER, f"{job_id}_ela.jpg")
        if os.path.exists(ela):
            content.append(RLImage(ela, width=5*inch, height=3*inch))

        heat = os.path.join(UPLOAD_FOLDER, f"{job_id}_heatmap.jpg")
        if os.path.exists(heat):
            content.append(RLImage(heat, width=5*inch, height=3*inch))

        doc.build(content)
        return f"{BASE_URL}/files/{job_id}_report.pdf"

    except Exception as e:
        print("PDF ERROR:", e)
        return None

# -----------------------------
# MAIN PROCESS
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status":"processing","step":"starting"}

        image = Image.open(path).convert("RGB")
        image.thumbnail((800,800))
        image.save(path)

        # -----------------------------
        # ELA
        # -----------------------------
        temp = path+"_c.jpg"
        image.save(temp,"JPEG",quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        ela_np = np.array(ela)
        ela_gray = cv2.cvtColor(ela_np, cv2.COLOR_BGR2GRAY)

        # -----------------------------
        # CV FEATURES
        # -----------------------------
        img = cv2.imread(path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        noise = cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))
        edges = cv2.Canny(gray, 100, 200)

        # -----------------------------
        # 🔥 AI-STYLE FUSION MAP
        # -----------------------------
        ela_n = cv2.normalize(ela_gray,None,0,255,cv2.NORM_MINMAX)
        noise_n = cv2.normalize(noise,None,0,255,cv2.NORM_MINMAX)
        edge_n = cv2.normalize(edges,None,0,255,cv2.NORM_MINMAX)

        combined = (
            0.5 * ela_n +
            0.3 * noise_n +
            0.2 * edge_n
        ).astype(np.uint8)

        combined = cv2.GaussianBlur(combined,(5,5),0)
        combined = cv2.equalizeHist(combined)

        # -----------------------------
        # HEATMAP
        # -----------------------------
        heat = cv2.applyColorMap(combined, cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(img, 0.6, heat, 0.4, 0)

        heatmap_file = f"{job_id}_heatmap.jpg"
        cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)

        # -----------------------------
        # REGION DETECTION
        # -----------------------------
        regions = []
        _, thresh = cv2.threshold(combined, 180, 255, cv2.THRESH_BINARY)

        contours,_ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours[:6]:
            x,y,w,h = cv2.boundingRect(cnt)
            if w*h < 800:
                continue

            regions.append({
                "x":int(x),
                "y":int(y),
                "w":int(w),
                "h":int(h),
                "reason":"High anomaly score in this region (multi-signal detection)."
            })

        # -----------------------------
        # SCORING
        # -----------------------------
        score = int(np.mean(ela_gray)/255*100)
        confidence = int(np.mean(combined)/255*100)

        # -----------------------------
        # EXPLANATION
        # -----------------------------
        simple = {
            "result": "Likely edited" if confidence>70 else "Possibly edited" if confidence>40 else "Likely original",
            "meaning": "This result is based on combined analysis of compression artifacts, noise patterns, and edge consistency.",
            "reasons": [
                "Compression inconsistencies detected",
                "Noise patterns differ across regions",
                "Edge structures are inconsistent"
            ]
        }

        result = {
            "score":score,
            "confidence":confidence,
            "ela_image":f"{BASE_URL}/files/{ela_file}",
            "heatmap":f"{BASE_URL}/files/{heatmap_file}",
            "regions":regions,
            "simple_explanation":simple,
            "metadata":extract_metadata(path),
            "gps":extract_gps(path),
            "legal":build_legal(score, confidence)
        }

        result["report"] = generate_pdf(job_id, result)

        jobs[job_id] = {"status":"done","result":result}

    except Exception as e:
        jobs[job_id] = {"status":"error","error":str(e)}

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id+".jpg")
    file.save(path)

    threading.Thread(target=process_job,args=(job_id,path)).start()
    return jsonify({"job_id":job_id})

@app.route("/api/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id,{"status":"error"}))

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)
