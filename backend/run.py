from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, traceback, time, requests

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance, UnidentifiedImageError
import exifread

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"
jobs = {}

# -----------------------------
# GLOBAL ERROR HANDLER (IMPORTANT)
# -----------------------------
@app.errorhandler(Exception)
def handle_exception(e):
    print("🔥 GLOBAL ERROR:", traceback.format_exc())
    return jsonify({"error": str(e)}), 500


# -----------------------------
# HEALTH + WAKE
# -----------------------------
@app.route("/")
def home():
    return "Backend is running"

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# -----------------------------
# SELF-WARM (prevents cold start failures)
# -----------------------------
def warm_self():
    try:
        time.sleep(2)
        requests.get(BASE_URL + "/health", timeout=5)
        print("🔥 Warmed backend")
    except:
        print("⚠️ Warm failed")

threading.Thread(target=warm_self).start()


@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# -----------------------------
# GPS
# -----------------------------
def get_gps_coords(tags):
    try:
        def convert(v):
            d = float(v.values[0].num) / float(v.values[0].den)
            m = float(v.values[1].num) / float(v.values[1].den)
            s = float(v.values[2].num) / float(v.values[2].den)
            return d + m/60 + s/3600

        lat = convert(tags["GPS GPSLatitude"])
        if tags["GPS GPSLatitudeRef"].values != "N":
            lat = -lat

        lon = convert(tags["GPS GPSLongitude"])
        if tags["GPS GPSLongitudeRef"].values != "E":
            lon = -lon

        return [lat, lon]
    except:
        return None


# -----------------------------
# SAFE WORKER
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status": "processing", "step": "loading image"}

        # Load image safely
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
        # QUICK CV (lightweight)
        # -----------------------------
        jobs[job_id]["step"] = "analyzing"

        img_cv = cv2.imread(path, 0)
        if img_cv is None:
            raise Exception("Image read failed")

        noise = float(np.mean(cv2.absdiff(img_cv, cv2.GaussianBlur(img_cv,(5,5),0))))
        sharp = float(cv2.Laplacian(img_cv, cv2.CV_64F).var())

        confidence = int(min(100, (score*0.5 + noise*0.2 + sharp*0.1)))

        risk = "High" if confidence > 70 else "Moderate" if confidence > 40 else "Low"

        # -----------------------------
        # RESULT
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
                "score_explanation": "Compression consistency (ELA).",
                "confidence_explanation": "Strength of detected anomalies.",
                "legal_conclusion": "Forensic indicators detected." if confidence > 40 else
                                    "No strong manipulation evidence.",
                "interpretation": [
                    "Score measures compression variation.",
                    "Confidence reflects anomaly strength.",
                    "Low confidence = weak evidence, not proof of authenticity."
                ],
                "ela_image": f"{BASE_URL}/files/{ela_file}"
            }
        }

    except Exception as e:
        print("🔥 JOB ERROR:", traceback.format_exc())
        jobs[job_id] = {"status": "error", "error": str(e)}


# -----------------------------
# TIMEOUT WRAPPER
# -----------------------------
def run_with_timeout(job_id, path, timeout=20):
    thread = threading.Thread(target=process_job, args=(job_id, path))
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        jobs[job_id] = {"status": "error", "error": "Processing timeout"}


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

        jobs[job_id] = {"status": "processing"}

        threading.Thread(target=run_with_timeout, args=(job_id, path)).start()

        return jsonify({"job_id": job_id})

    except Exception as e:
        print("🔥 ANALYZE ERROR:", traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/api/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id, {"error": "invalid job"}))


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
