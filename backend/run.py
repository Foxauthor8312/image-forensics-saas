from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, traceback

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"
jobs = {}

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -----------------------------
# PDF
# -----------------------------
def generate_pdf(job_id, result):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")
        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("PixelProof Forensic Report", styles["Title"]))
        content.append(Spacer(1,10))

        content.append(Paragraph(f"Score: {result['score']}", styles["Normal"]))
        content.append(Paragraph(f"Confidence: {result['confidence']}%", styles["Normal"]))
        content.append(Paragraph(result["legal_conclusion"], styles["Normal"]))
        content.append(Spacer(1,10))

        content.append(Paragraph("Findings:", styles["Heading2"]))
        for e in result["explanation"]:
            content.append(Paragraph(f"- {e}", styles["Normal"]))

        content.append(Spacer(1,10))

        try:
            content.append(RLImage(os.path.join(UPLOAD_FOLDER, f"{job_id}_ela.jpg"), width=400, height=250))
        except:
            pass

        try:
            content.append(RLImage(os.path.join(UPLOAD_FOLDER, f"{job_id}_heatmap.jpg"), width=400, height=250))
        except:
            pass

        doc.build(content)

        return f"{BASE_URL}/files/{job_id}_report.pdf"

    except Exception as e:
        print("PDF error:", e)
        return None


# -----------------------------
# WORKER
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status": "processing", "step": "loading image"}

        image = Image.open(path).convert("RGB")
        image.thumbnail((800,800))
        image.save(path)

        # ELA
        jobs[job_id]["step"] = "running ELA"
        temp = path+"_c.jpg"
        image.save(temp,"JPEG",quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # CV
        jobs[job_id]["step"] = "analyzing"
        gray = cv2.imread(path,0)
        noise = np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0)))
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

        noise_n = min(100, noise*1.5)
        sharp_n = min(100, sharp/10)

        confidence = int(min(100, score*0.5 + noise_n*0.25 + sharp_n*0.25))

        # HEATMAP
        jobs[job_id]["step"] = "detecting tamper regions"
        heatmap_file = None

        try:
            img = cv2.imread(path)
            img = cv2.resize(img,(600,600))
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))
            norm = cv2.normalize(diff,None,0,255,cv2.NORM_MINMAX)
            heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(img,0.6,heat,0.4,0)

            heatmap_file = f"{job_id}_heatmap.jpg"
            cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)
        except:
            pass

        # EXPLANATION
        explanation = [
            f"Compression {'inconsistent' if score>40 else 'uniform'}",
            f"Noise {'irregular' if noise_n>40 else 'consistent'}",
            f"Sharpness {'variable' if sharp_n>40 else 'consistent'}"
        ]

        legal = "Possible manipulation detected." if confidence>40 else "No strong manipulation evidence."

        result_data = {
            "score": score,
            "confidence": confidence,
            "ela_result": "Likely manipulated" if confidence>70 else "Likely original",
            "score_explanation": "ELA compression analysis",
            "confidence_explanation": "Combined anomaly strength",
            "legal_conclusion": legal,
            "explanation": explanation
        }

        report_url = generate_pdf(job_id, result_data)

        jobs[job_id] = {
            "status":"done",
            "result":{
                **result_data,
                "ela_image": f"{BASE_URL}/files/{ela_file}",
                "heatmap": f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
                "report": report_url
            }
        }

    except Exception as e:
        jobs[job_id] = {"status":"error","error":str(e)}


@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    if not file:
        return jsonify({"error":"No file uploaded"}),400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id+".jpg")
    file.save(path)

    jobs[job_id] = {"status":"processing"}
    threading.Thread(target=process_job,args=(job_id,path)).start()

    return jsonify({"job_id":job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id,{"status":"error"}))


if __name__=="__main__":
    app.run(host="0.0.0.0",port=3000)
