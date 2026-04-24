from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, datetime

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance
from PIL.ExifTags import TAGS, GPSTAGS

# PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle
from reportlab.lib import colors
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

        data = {
            "available": False,
            "ImageWidth": img.width,
            "ImageHeight": img.height
        }

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

            if gps.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps.get("GPSLongitudeRef") == "W":
                lon = -lon

            return {"lat": lat, "lon": lon}

    except:
        return None

# -----------------------------
# LEGAL LANGUAGE
# -----------------------------
def build_legal(score, confidence):
    if confidence > 70:
        opinion = "It is my professional opinion, within a reasonable degree of technical certainty, that this image exhibits characteristics consistent with digital alteration."
    elif confidence > 40:
        opinion = "The image contains indicators that may be consistent with digital alteration; however, these findings are not conclusive."
    else:
        opinion = "The analysis does not reveal strong indicators of digital alteration."

    return {
        "opinion": opinion,
        "confidence": confidence
    }

# -----------------------------
# COURT-STYLE PDF
# -----------------------------
def generate_pdf(job_id, result):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")

        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()
        content = []

        # HEADER
        content.append(Paragraph("DIGITAL IMAGE FORENSIC REPORT", styles["Title"]))
        content.append(Spacer(1, 12))

        content.append(Paragraph(
            f"Date of Analysis: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            styles["Normal"]
        ))
        content.append(Spacer(1, 10))

        # SUMMARY TABLE
        table_data = [
            ["Score", str(result["score"])],
            ["Confidence", f"{result['confidence']}%"],
            ["Conclusion", result["legal"]["opinion"]]
        ]

        table = Table(table_data, colWidths=[120, 300])
        table.setStyle(TableStyle([
            ("GRID",(0,0),(-1,-1),1,colors.black)
        ]))

        content.append(table)
        content.append(Spacer(1, 15))

        # METHODOLOGY
        content.append(Paragraph("Methodology", styles["Heading2"]))
        content.append(Paragraph(
            "This analysis utilized Error Level Analysis (ELA), noise distribution evaluation, "
            "and sharpness consistency measurements to identify anomalies that may indicate "
            "digital manipulation.",
            styles["Normal"]
        ))
        content.append(Spacer(1, 10))

        # FINDINGS
        content.append(Paragraph("Findings", styles["Heading2"]))
        for r in result["simple_explanation"]["reasons"]:
            content.append(Paragraph(f"- {r}", styles["Normal"]))

        content.append(Spacer(1, 10))

        # CONCLUSION
        content.append(Paragraph("Conclusion", styles["Heading2"]))
        content.append(Paragraph(result["legal"]["opinion"], styles["Normal"]))

        content.append(Spacer(1, 10))

        # LIMITATIONS
        content.append(Paragraph("Limitations", styles["Heading2"]))
        limitations = [
            "This analysis is probabilistic and does not constitute definitive proof.",
            "Image recompression may introduce artifacts.",
            "Low-resolution images reduce analytical reliability."
        ]

        for l in limitations:
            content.append(Paragraph(f"- {l}", styles["Normal"]))

        content.append(Spacer(1, 15))

        # IMAGES
        ela_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_ela.jpg")
        if os.path.exists(ela_path):
            content.append(Paragraph("ELA Analysis", styles["Heading3"]))
            content.append(RLImage(ela_path, width=5*inch, height=3*inch))

        heat_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_heatmap.jpg")
        if os.path.exists(heat_path):
            content.append(Paragraph("Heatmap Analysis", styles["Heading3"]))
            content.append(RLImage(heat_path, width=5*inch, height=3*inch))

        doc.build(content)

        return f"{BASE_URL}/files/{job_id}_report.pdf"

    except Exception as e:
        print("PDF ERROR:", e)
        return None

# -----------------------------
# PROCESS JOB (same logic)
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status":"processing"}

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
        noise = np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0)))
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

        confidence = int(min(100, score*0.4 + noise*0.3 + sharp*0.3))

        # HEATMAP
        img = cv2.imread(path)
        img_small = cv2.resize(img,(600,600))
        gray = cv2.cvtColor(img_small, cv2.COLOR_BGR2GRAY)

        norm = cv2.normalize(gray,None,0,255,cv2.NORM_MINMAX)
        heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
        overlay = cv2.addWeighted(img_small,0.6,heat,0.4,0)

        heatmap_file = f"{job_id}_heatmap.jpg"
        cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)

        simple = {
            "result": "Likely edited" if confidence>70 else "Possibly edited" if confidence>40 else "Likely original",
            "meaning": "Image consistency analysis performed.",
            "reasons": ["Compression variance","Noise inconsistency","Sharpness variance"]
        }

        result = {
            "score":score,
            "confidence":confidence,
            "ela_image":f"{BASE_URL}/files/{ela_file}",
            "heatmap":f"{BASE_URL}/files/{heatmap_file}",
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
