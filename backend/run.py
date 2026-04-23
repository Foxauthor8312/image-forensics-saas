from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, traceback

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance, UnidentifiedImageError

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"
jobs = {}

# -----------------------------
# GLOBAL ERROR HANDLER
# -----------------------------
@app.errorhandler(Exception)
def handle_exception(e):
    print("🔥 GLOBAL ERROR:", traceback.format_exc())
    return jsonify({"error": str(e)}), 500

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
# WORKER
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status": "processing", "step": "loading image"}

        # Load image
        try:
            image = Image.open(path).convert("RGB")
        except UnidentifiedImageError:
            jobs[job_id] = {"status": "error", "error": "Invalid image file"}
            return

        image.thumbnail((800, 800))
        image.save(path)

        # -----------------------------
        # ELA
        # -----------------------------
        jobs[job_id]["step"] = "running ELA"

        temp = path + "_compressed.jpg"
        image.save(temp, "JPEG", quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # -----------------------------
        # LIGHT CV ANALYSIS
        # -----------------------------
        jobs[job_id]["step"] = "analyzing structure"

        gray = cv2.imread(path, 0)
        if gray is None:
            raise Exception("Image read failed")

        noise = float(np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))))
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())

        noise_n = min(100, noise * 1.5)
        sharp_n = min(100, sharp / 10)

        # -----------------------------
        # CONFIDENCE (IMPROVED)
        # -----------------------------
        ela_c = score * 0.5
        noise_c = noise_n * 0.25
        sharp_c = sharp_n * 0.25
        meta_c = 10  # assume missing metadata bonus

        confidence = int(min(100, ela_c + noise_c + sharp_c + meta_c))

        # -----------------------------
        # INTERPRETATION LOGIC
        # -----------------------------
        risk = "High" if confidence > 70 else "Moderate" if confidence > 40 else "Low"

        if score < 10:
            score_explanation = "Low compression variation (uniform encoding)."
        elif score < 40:
            score_explanation = "Moderate compression variation detected."
        else:
            score_explanation = "High compression inconsistencies detected."

        if confidence < 30:
            confidence_explanation = "Low confidence: weak forensic signals."
        elif confidence < 70:
            confidence_explanation = "Moderate confidence: some anomalies present."
        else:
            confidence_explanation = "High confidence: strong evidence of manipulation."

        explanation = [
            f"Compression {'inconsistent' if score > 40 else 'moderately varied' if score > 10 else 'uniform'}.",
            f"Noise {'irregular' if noise_n > 40 else 'consistent'}.",
            f"Sharpness {'variable' if sharp_n > 40 else 'consistent'}."
        ]

        narrative = (
            "Image analyzed using compression consistency (ELA), noise distribution, and sharpness variation."
        )

        legal_conclusion = (
            "Strong indicators consistent with manipulation." if confidence > 70 else
            "Possible indicators of editing, not conclusive." if confidence > 40 else
            "No strong evidence of manipulation detected."
        )

        interpretation = [
            "Score reflects compression consistency (ELA).",
            "Confidence represents strength of forensic signals.",
            "Low confidence does not guarantee authenticity.",
            "Standard image processing can affect results."
        ]

        justification = f"Confidence ({confidence}%) derived from combined compression, noise, and sharpness signals."

        result = (
            "Likely manipulated" if confidence > 70 else
            "Possibly manipulated" if confidence > 40 else
            "Likely original"
        )

        # -----------------------------
        # FINAL RESULT
        # -----------------------------
        jobs[job_id] = {
            "status": "done",
            "result": {
                "score": score,
                "confidence": confidence,
                "risk_level": risk,
                "ela_result": result,
                "score_explanation": score_explanation,
                "confidence_explanation": confidence_explanation,
                "legal_conclusion": legal_conclusion,
                "narrative": narrative,
                "explanation": explanation,
                "justification": justification,
                "interpretation": interpretation,
                "ela_image": f"{BASE_URL}/files/{ela_file}",
                "confidence_breakdown": {
                    "ela": int(ela_c),
                    "noise": int(noise_c),
                    "sharpness": int(sharp_c),
                    "metadata_bonus": meta_c
                }
            }
        }

    except Exception as e:
        print("🔥 JOB ERROR:", traceback.format_exc())
        jobs[job_id] = {"status": "error", "error": str(e)}

# -----------------------------
# TIMEOUT WRAPPER
# -----------------------------
def run_with_timeout(job_id, path, timeout=25):
    thread = threading.Thread(target=process_job, args=(job_id, path))
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        jobs[job_id] = {"status": "error", "error": "Processing timed out"}

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
            return jsonify({"error": "Image too large (max 5MB)"}), 400

        jobs[job_id] = {"status": "processing", "step": "starting"}

        threading.Thread(target=run_with_timeout, args=(job_id, path)).start()

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
