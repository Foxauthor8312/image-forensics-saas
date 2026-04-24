from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance
from PIL.ExifTags import TAGS, GPSTAGS

# PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000")
jobs = {}

# -----------------------------
# GPS
# -----------------------------
def extract_gps(path):
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return None

        gps_data = {}

        for tag, value in exif.items():
            tag_name = TAGS.get(tag)
            if tag_name == "GPSInfo":
                for key in value:
                    gps_tag = GPSTAGS.get(key)
                    gps_data[gps_tag] = value[key]

        if "GPSLatitude" in gps_data and "GPSLongitude" in gps_data:

            def convert(coord):
                d = coord[0][0]/coord[0][1]
                m = coord[1][0]/coord[1][1]
                s = coord[2][0]/coord[2][1]
                return d + (m/60) + (s/3600)

            lat = convert(gps_data["GPSLatitude"])
            lon = convert(gps_data["GPSLongitude"])

            if gps_data.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps_data.get("GPSLongitudeRef") == "W":
                lon = -lon

            return {"lat": lat, "lon": lon}

    except:
        return None

# -----------------------------
# METADATA
# -----------------------------
def extract_metadata(path):
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return {"available": False}

        data = {}
        for tag, value in exif.items():
            name = TAGS.get(tag, tag)
            if name in ["Make","Model","DateTime","Software","LensModel"]:
                data[name] = str(value)

        data["ImageWidth"] = img.width
        data["ImageHeight"] = img.height
        data["available"] = True

        return data
    except:
        return {"available": False}

# -----------------------------
# PDF
# -----------------------------
def generate_pdf(job_id, result):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")

        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("PixelProof Report", styles["Title"]))
        content.append(Spacer(1,10))

        table = Table([
            ["Score", str(result["score"])],
            ["Confidence", f"{result['confidence']}%"],
            ["Result", result["simple_explanation"]["result"]]
        ])

        content.append(table)
        content.append(Spacer(1,10))

        content.append(Paragraph(result["simple_explanation"]["meaning"], styles["Normal"]))

        for r in result["simple_explanation"]["reasons"]:
            content.append(Paragraph(f"• {r}", styles["Normal"]))

        ela_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_ela.jpg")
        if os.path.exists(ela_path):
            content.append(RLImage(ela_path, width=5*inch, height=3*inch))

        heat_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_heatmap.jpg")
        if os.path.exists(heat_path):
            content.append(RLImage(heat_path, width=5*inch, height=3*inch))

        doc.build(content)

        return f"{BASE_URL}/files/{job_id}_report.pdf"

    except Exception as e:
        print("PDF ERROR:", e)
        return None

# -----------------------------
# PROCESS
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status":"processing","step":"loading"}

        image = Image.open(path).convert("RGB")
        image.thumbnail((800,800))
        image.save(path)

        # ELA
        temp = path+"_c.jpg"
        image.save(temp,"JPEG",quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # CV
        gray = cv2.imread(path,0)
        if gray is None:
            raise Exception("OpenCV failed")

        noise = np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0)))
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

        noise_n = min(100, noise*1.5)
        sharp_n = min(100, sharp/10)

        confidence = int(min(100, score*0.4 + noise_n*0.3 + sharp_n*0.3))

        # Heatmap
        regions = []
        heatmap_file = None

        img = cv2.imread(path)
        img_small = cv2.resize(img,(600,600))

        gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray,(5,5),0)
        diff = cv2.absdiff(gray, blur)

        norm = cv2.normalize(diff,None,0,255,cv2.NORM_MINMAX)

        heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(img_small,0.6,heat,0.4,0)

        heatmap_file = f"{job_id}_heatmap.jpg"
        cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)

        _, thresh = cv2.threshold(norm,180,255,cv2.THRESH_BINARY)
        contours,_ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours[:5]:
            x,y,w,h = cv2.boundingRect(cnt)
            if w*h < 500: continue
            regions.append({
                "x":int(x),"y":int(y),"w":int(w),"h":int(h),
                "reason":"Area differs from surrounding image"
            })

        gps = extract_gps(path)
        metadata = extract_metadata(path)

        simple = {
            "result": "Likely edited" if confidence>70 else "Possibly edited" if confidence>40 else "Likely original",
            "meaning": "Based on compression, noise, and detail consistency.",
            "reasons": [
                "Compression differences" if score>40 else "Compression consistent",
                "Noise irregularity" if noise_n>40 else "Noise consistent",
                "Sharpness inconsistency" if sharp_n>40 else "Sharpness consistent"
            ]
        }

        result = {
            "score":score,
            "confidence":confidence,
            "ela_image":f"{BASE_URL}/files/{ela_file}",
            "heatmap":f"{BASE_URL}/files/{heatmap_file}",
            "regions":regions,
            "simple_explanation":simple,
            "gps":gps,
            "metadata":metadata
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
    if not file:
        return jsonify({"error":"No file"}),400

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

@app.route("/health")
def health():
    return jsonify({"status":"ok"})
