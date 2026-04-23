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

# -----------------------------
# HEALTH
# -----------------------------
@app.route("/")
def home():
    return "Backend is running"

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# -----------------------------
# WORKER (SAFE + FAST)
# -----------------------------
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

        # -----------------------------
        # ELA
        # -----------------------------
        jobs[job_id]["step"] = "running ELA"

        temp = path + "_c.jpg"
        image.save(temp, "JPEG", quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # -----------------------------
        # LIGHT ANALYSIS (no heavy CV freeze)
        # -----------------------------
        jobs[job_id]["step"] = "analyzing"

        gray = cv2.imread(path, 0)
        if gray is None:
            raise Exception("Image read failed")

        noise = float(np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))))
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        # scaled confidence (more intuitive)
        confidence = int(min(100, (score*0.6 + noise*0.2 + sharp*0.1)))

        risk = "High" if confidence > 70 else "Moderate" if confidence > 40 else "Low"

        # -----------------------------
        # RESPONSE
        # -----------------------------
        jobs[job_id] = {
            "status": "done",
            "result": {
                "score": score,
                "confidence": confidence,
                "risk_level": risk,
                "ela_result": "Likely manipulated" if confidence > 70 else
                              "Possibly manipulated" if confidence > 40 else
                              "Likely original",

                "score_explanation":
                    "Measures compression consistency (ELA). Low = uniform, high = irregular.",

                "confidence_explanation":
                    "Represents strength of detected anomalies across multiple signals.",

                "legal_conclusion":
                    "Indicators suggest possible manipulation." if confidence > 40 else
                    "No strong evidence of manipulation detected.",

                "interpretation": [
                    "Score reflects compression variation.",
                    "Confidence reflects strength of forensic signals.",
                    "Low confidence = weak evidence, not proof of authenticity.",
                    "Normal compression or resizing can affect results."
                ],

                "ela_image": f"{BASE_URL}/files/{ela_file}"
            }
        }

    except Exception as e:
        print("🔥 ERROR:", traceback.format_exc())
        jobs[job_id] = {"status": "error", "error": str(e)}


# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        file = request.files.get("image")
        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        job_id = str(uuid.uuid4())
        path = os.path.join(UPLOAD_FOLDER, f"{job_id}.jpg")
        file.save(path)

        # size limit
        if os.path.getsize(path) > 5 * 1024 * 1024:
            return jsonify({"error": "File too large"}), 400

        jobs[job_id] = {"status": "processing", "step": "starting"}

        threading.Thread(target=process_job, args=(job_id, path)).start()

        return jsonify({"job_id": job_id})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id, {"error": "invalid job"}))


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
