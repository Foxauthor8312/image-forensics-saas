from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading
import numpy as np
import cv2

from PIL import Image, ImageChops, ImageEnhance
import exifread

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

jobs = {}

# -----------------------------
# HOME
# -----------------------------
@app.route("/")
def home():
    return "Backend is running"


@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# -----------------------------
# WORKER FUNCTION
# -----------------------------
def process_job(job_id, path):
    try:
        metadata = {}

        # -----------------------------
        # EXIF (safe + trimmed)
        # -----------------------------
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f)
            for tag in tags:
                val = str(tags[tag])
                if len(val) < 200:
                    metadata[tag] = val
        except:
            pass

        # -----------------------------
        # LOAD + RESIZE (CRITICAL FIX)
        # -----------------------------
        image = Image.open(path).convert("RGB")
        image.thumbnail((800, 800))
        image.save(path)

        # -----------------------------
        # ELA
        # -----------------------------
        temp = path + "_compressed.jpg"
        image.save(temp, "JPEG", quality=90)

        compressed = Image.open(temp)
        diff = ImageChops.difference(image, compressed)

        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela_path = os.path.join(UPLOAD_FOLDER, ela_file)
        ela.save(ela_path)

        arr = np.array(ela)
        score = int((np.mean(arr) / (np.max(arr) + 1e-5)) * 100)

        # -----------------------------
        # FAST CV (noise + sharpness)
        # -----------------------------
        img_cv = cv2.imread(path, 0)

        if img_cv is not None:
            noise = float(np.mean(cv2.absdiff(img_cv, cv2.GaussianBlur(img_cv,(5,5),0))))
            sharp = float(cv2.Laplacian(img_cv, cv2.CV_64F).var())
        else:
            noise = 0
            sharp = 0

        noise_n = min(100, noise / 2)
        sharp_n = min(100, sharp / 50)

        # -----------------------------
        # CONFIDENCE BREAKDOWN
        # -----------------------------
        ela_contrib = score * 0.4
        noise_contrib = noise_n * 0.3
        sharp_contrib = sharp_n * 0.3
        meta_bonus = 10 if len(metadata) == 0 else 0

        confidence = int(min(100, ela_contrib + noise_contrib + sharp_contrib + meta_bonus))

        # -----------------------------
        # HEATMAP (SAFE + FAST)
        # -----------------------------
        heatmap_file = None
        regions = []

        try:
            img = cv2.imread(path)
            if img is not None:
                img = cv2.resize(img, (600, 600))

                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                diff = cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))

                norm = cv2.normalize(diff, None, 0,255,cv2.NORM_MINMAX)
                heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
                overlay = cv2.addWeighted(img,0.6,heat,0.4,0)

                _, thresh = cv2.threshold(norm,50,255,cv2.THRESH_BINARY)
                contours,_ = cv2.findContours(thresh,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)

                for c in contours:
                    if cv2.contourArea(c) > 500:
                        x,y,w,h = cv2.boundingRect(c)
                        regions.append([int(x),int(y),int(w),int(h)])
                        cv2.rectangle(overlay,(x,y),(x+w,y+h),(0,255,0),2)

                heatmap_file = f"{job_id}_heatmap.jpg"
                cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)

        except:
            pass

        # -----------------------------
        # EXPLANATION
        # -----------------------------
        explanation = []

        if score < 10:
            explanation.append("Very low compression differences detected.")
        elif score < 40:
            explanation.append("Moderate compression differences detected.")
        else:
            explanation.append("High compression inconsistencies detected.")

        if noise_n > 40:
            explanation.append("Noise inconsistencies detected.")

        if sharp_n > 40:
            explanation.append("Sharpness irregularities detected.")

        if len(metadata) == 0:
            explanation.append("Metadata missing or stripped.")

        if not explanation:
            explanation.append("No strong anomalies detected.")

        # -----------------------------
        # RESULT
        # -----------------------------
        if confidence > 70:
            result = "Likely manipulated"
        elif confidence > 40:
            result = "Possibly manipulated"
        else:
            result = "Likely original"

        jobs[job_id] = {
            "status": "done",
            "result": {
                "score": score,
                "confidence": confidence,
                "ela_result": result,
                "metadata": metadata,
                "ela_image": f"{BASE_URL}/files/{ela_file}",
                "heatmap": f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
                "regions": regions,
                "explanation": explanation,
                "confidence_breakdown": {
                    "ela": int(ela_contrib),
                    "noise": int(noise_contrib),
                    "sharpness": int(sharp_contrib),
                    "metadata_bonus": meta_bonus
                }
            }
        }

    except Exception as e:
        jobs[job_id] = {"status": "error", "error": str(e)}


# -----------------------------
# START JOB
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")

    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, f"{job_id}.jpg")

    file.save(path)

    jobs[job_id] = {"status": "processing"}

    threading.Thread(target=process_job, args=(job_id, path)).start()

    return jsonify({"job_id": job_id})


# -----------------------------
# CHECK STATUS
# -----------------------------
@app.route("/api/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Invalid job ID"}), 404
    return jsonify(job)


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
