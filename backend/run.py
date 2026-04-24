from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance

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
# PDF GENERATOR (FIXED)
# -----------------------------
def generate_pdf(job_id, result):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")

        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("PixelProof Forensic Report", styles["Title"]))
        content.append(Spacer(1, 12))

        # Summary table
        table_data = [
            ["Score", str(result.get("score", "N/A"))],
            ["Confidence", f"{result.get('confidence', 'N/A')}%"],
            ["Result", result.get("simple_explanation", {}).get("result", "N/A")]
        ]

        table = Table(table_data, colWidths=[150, 250])
        table.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 1, colors.black)
        ]))

        content.append(table)
        content.append(Spacer(1, 12))

        # Simple explanation
        simple = result.get("simple_explanation", {})
        content.append(Paragraph("Simple Explanation", styles["Heading2"]))
        content.append(Spacer(1, 6))

        content.append(Paragraph(simple.get("meaning", ""), styles["Normal"]))
        content.append(Spacer(1, 6))

        for r in simple.get("reasons", []):
            content.append(Paragraph(f"• {r}", styles["Normal"]))

        content.append(Spacer(1, 12))

        # Images
        ela_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_ela.jpg")
        if os.path.exists(ela_path):
            content.append(Paragraph("ELA", styles["Heading3"]))
            content.append(RLImage(ela_path, width=5*inch, height=3*inch))

        heatmap_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_heatmap.jpg")
        if os.path.exists(heatmap_path):
            content.append(Paragraph("Heatmap", styles["Heading3"]))
            content.append(RLImage(heatmap_path, width=5*inch, height=3*inch))

        content.append(Spacer(1, 20))
        content.append(Paragraph(
            "This report is based on automated analysis and is not definitive proof.",
            styles["Italic"]
        ))

        doc.build(content)

        return f"{BASE_URL}/files/{job_id}_report.pdf"

    except Exception as e:
        print("PDF ERROR:", e)
        return None


# -----------------------------
# PROCESS JOB
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

        noise_n = min(100, noise*1.5)
        sharp_n = min(100, sharp/10)

        confidence = int(min(100, score*0.4 + noise_n*0.3 + sharp_n*0.3))

        # -----------------------------
        # HEATMAP + REGIONS
        # -----------------------------
        regions = []
        heatmap_file = None

        try:
            img = cv2.imread(path)
            if img is None:
                raise Exception("Image read failed")

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
                if w*h < 500:
                    continue

                regions.append({
                    "x":int(x),
                    "y":int(y),
                    "w":int(w),
                    "h":int(h),
                    "reason":"Region differs from surrounding image."
                })

        except Exception as e:
            print("HEATMAP ERROR:", e)

        # -----------------------------
        # SIMPLE EXPLANATION
        # -----------------------------
        simple_explanation = {
            "result": "Likely edited" if confidence>70 else "Possibly edited" if confidence>40 else "Likely original",
            "meaning": "Based on compression, noise, and sharpness consistency.",
            "reasons": [
                "Compression differences" if score>40 else "Compression consistent",
                "Noise irregularity" if noise_n>40 else "Noise consistent",
                "Sharpness inconsistency" if sharp_n>40 else "Sharpness consistent"
            ]
        }

        # -----------------------------
        # RESULT
        # -----------------------------
        result_data = {
            "score":score,
            "confidence":confidence,
            "ela_image":f"{BASE_URL}/files/{ela_file}",
            "heatmap":f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
            "regions":regions,
            "simple_explanation":simple_explanation
        }

        report_url = generate_pdf(job_id, result_data)

        jobs[job_id] = {
            "status":"done",
            "result":{
                **result_data,
                "report":report_url
            }
        }

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
