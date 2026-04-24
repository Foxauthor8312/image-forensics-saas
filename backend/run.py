from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000")
jobs = {}

# -----------------------------
# PROCESS JOB
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status":"processing","step":"loading image"}

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

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # -----------------------------
        # BASIC SIGNALS
        # -----------------------------
        gray = cv2.imread(path,0)
        noise = np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0)))
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

        noise_n = min(100, noise*1.5)
        sharp_n = min(100, sharp/10)

        confidence = int(min(100, score*0.4 + noise_n*0.3 + sharp_n*0.3))

        # -----------------------------
        # HEATMAP + REGIONS (FIXED)
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
            heatmap_path = os.path.join(UPLOAD_FOLDER, heatmap_file)

            if not cv2.imwrite(heatmap_path, overlay):
                raise Exception("Heatmap save failed")

            # Regions
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
                    "reason":"This region differs from surrounding image patterns."
                })

        except Exception as e:
            print("HEATMAP ERROR:", e)

        # -----------------------------
        # SIMPLE EXPLANATION
        # -----------------------------
        simple_explanation = {
            "result": "Likely edited" if confidence>70 else "Possibly edited" if confidence>40 else "Likely original",
            "risk_level": "High" if confidence>70 else "Moderate" if confidence>40 else "Low",
            "confidence_text": f"{confidence}% confidence",
            "meaning": "Based on compression, texture, and detail consistency.",
            "reasons": [
                "Compression variation detected" if score>40 else "Compression consistent",
                "Noise irregularity detected" if noise_n>40 else "Noise consistent",
                "Sharpness inconsistency detected" if sharp_n>40 else "Sharpness consistent"
            ],
            "next_steps": "Verify source if important."
        }

        # -----------------------------
        # RESULT
        # -----------------------------
        jobs[job_id] = {
            "status":"done",
            "result":{
                "score":score,
                "confidence":confidence,
                "ela_image":f"{BASE_URL}/files/{ela_file}",
                "heatmap":f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
                "regions":regions,
                "simple_explanation":simple_explanation,
                "confidence_breakdown":{
                    "ela":int(score*0.4),
                    "noise":int(noise_n*0.3),
                    "sharpness":int(sharp_n*0.3)
                }
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
