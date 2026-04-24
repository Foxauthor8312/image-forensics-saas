from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, traceback

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance, UnidentifiedImageError

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

def process_job(job_id, path):
    try:
        jobs[job_id] = {"status": "processing", "step": "loading image"}

        try:
            image = Image.open(path).convert("RGB")
        except UnidentifiedImageError:
            jobs[job_id] = {"status": "error", "error": "Invalid image"}
            return

        image.thumbnail((800, 800))
        image.save(path)

        # ELA
        jobs[job_id]["step"] = "running ELA"
        temp = path + "_c.jpg"
        image.save(temp, "JPEG", quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # CV
        jobs[job_id]["step"] = "analyzing"
        gray = cv2.imread(path, 0)
        if gray is None:
            raise Exception("Image read failed")

        noise = np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0)))
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

        noise_n = min(100, noise*1.5)
        sharp_n = min(100, sharp/10)

        ela_c = score * 0.5
        noise_c = noise_n * 0.25
        sharp_c = sharp_n * 0.25

        confidence = int(min(100, ela_c + noise_c + sharp_c))

        risk = "High" if confidence > 70 else "Moderate" if confidence > 40 else "Low"

        # explanations
        score_explanation = "Measures compression consistency (ELA)."
        confidence_explanation = "Strength of detected forensic signals."

        explanation = [
            f"Compression {'inconsistent' if score>40 else 'moderate' if score>10 else 'uniform'}",
            f"Noise {'irregular' if noise_n>40 else 'consistent'}",
            f"Sharpness {'variable' if sharp_n>40 else 'consistent'}"
        ]

        interpretation = [
            "Score reflects compression variation.",
            "Confidence reflects anomaly strength.",
            "Low confidence = weak evidence, not proof of authenticity."
        ]

        narrative = "Analysis based on compression, noise, and sharpness consistency."

        legal = "Possible manipulation detected." if confidence>40 else "No strong manipulation evidence."

        jobs[job_id] = {
            "status": "done",
            "result": {
                "score": score,
                "confidence": confidence,
                "risk_level": risk,
                "ela_result":
                    "Likely manipulated" if confidence>70 else
                    "Possibly manipulated" if confidence>40 else
                    "Likely original",
                "score_explanation": score_explanation,
                "confidence_explanation": confidence_explanation,
                "legal_conclusion": legal,
                "narrative": narrative,
                "explanation": explanation,
                "interpretation": interpretation,
                "ela_image": f"{BASE_URL}/files/{ela_file}",
                "confidence_breakdown": {
                    "ela": int(ela_c),
                    "noise": int(noise_c),
                    "sharpness": int(sharp_c)
                }
            }
        }

    except Exception as e:
        jobs[job_id] = {"status": "error", "error": str(e)}


@app.route("/api/analyze", methods=["POST"])
def analyze():
    if "image" not in request.files:
        return jsonify({"error":"No file uploaded"}),400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error":"No file selected"}),400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id+".jpg")
    file.save(path)

    jobs[job_id] = {"status":"processing","step":"starting"}
    threading.Thread(target=process_job,args=(job_id,path)).start()

    return jsonify({"job_id":job_id})


@app.route("/api/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id,{"status":"error","error":"invalid job"}))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
