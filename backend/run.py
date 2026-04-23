from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, traceback, time

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
        jobs[job_id] = {"status": "processing", "step": "reading metadata"}

        metadata = {}
        gps = None

        # EXIF
        try:
            with open(path, "rb") as f:
                tags = exifread.process_file(f)

            for tag in tags:
                val = str(tags[tag])
                if len(val) < 200:
                    metadata[tag] = val

            gps = get_gps_coords(tags)
        except:
            pass

        # LOAD IMAGE
        jobs[job_id]["step"] = "loading image"

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
        # CV ANALYSIS
        # -----------------------------
        jobs[job_id]["step"] = "analyzing structure"

        img_cv = cv2.imread(path, 0)
        if img_cv is None:
            raise Exception("OpenCV failed to read image")

        noise = float(np.mean(cv2.absdiff(img_cv, cv2.GaussianBlur(img_cv,(5,5),0))))
        sharp = float(cv2.Laplacian(img_cv, cv2.CV_64F).var())

        noise_n = min(100, noise * 1.5)
        sharp_n = min(100, sharp / 10)

        # -----------------------------
        # CONFIDENCE
        # -----------------------------
        ela_c = score * 0.5
        noise_c = noise_n * 0.25
        sharp_c = sharp_n * 0.25
        meta_c = 10 if len(metadata) == 0 else 0

        confidence = int(min(100, ela_c + noise_c + sharp_c + meta_c))

        risk = "High" if confidence > 70 else "Moderate" if confidence > 40 else "Low"

        # -----------------------------
        # EXPLANATIONS
        # -----------------------------
        score_explanation = "Compression consistency analysis (ELA)."
        confidence_explanation = "Strength of detected forensic signals."

        explanation = [
            f"Compression {'inconsistencies' if score > 40 else 'variation' if score > 10 else 'uniform'} detected.",
            f"Noise is {'irregular' if noise_n > 40 else 'consistent'}.",
            f"Sharpness is {'variable' if sharp_n > 40 else 'consistent'}.",
            f"Metadata {'missing' if len(metadata)==0 else 'present'}."
        ]

        narrative = "Image analyzed using compression, noise, and structural consistency."

        legal_conclusion = (
            "Strong evidence of manipulation." if confidence > 70 else
            "Possible indicators of editing." if confidence > 40 else
            "No strong evidence of manipulation."
        )

        interpretation = [
            "Score = compression consistency (ELA).",
            "Confidence = strength of forensic signals.",
            "Low confidence = weak evidence, not proof of authenticity.",
            "Normal processing can affect results."
        ]

        justification = f"Confidence ({confidence}%) based on combined signals."

        # -----------------------------
        # HEATMAP
        # -----------------------------
        jobs[job_id]["step"] = "generating heatmap"

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

        result = "Likely manipulated" if confidence > 70 else \
                 "Possibly manipulated" if confidence > 40 else \
                 "Likely original"

        # -----------------------------
        # DONE
        # -----------------------------
        jobs[job_id] = {
            "status": "done",
            "result": {
                "score": score,
                "confidence": confidence,
                "score_explanation": score_explanation,
                "confidence_explanation": confidence_explanation,
                "risk_level": risk,
                "legal_conclusion": legal_conclusion,
                "justification": justification,
                "interpretation": interpretation,
                "ela_result": result,
                "metadata": metadata,
                "ela_image": f"{BASE_URL}/files/{ela_file}",
                "heatmap": f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
                "gps": gps,
                "narrative": narrative,
                "explanation": explanation,
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
        jobs[job_id] = {
            "status": "error",
            "error": "Processing timed out"
        }


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

        # File size limit (5MB)
        if os.path.getsize(path) > 5 * 1024 * 1024:
            return jsonify({"error": "Image too large (max 5MB)"}), 400

        jobs[job_id] = {"status": "processing", "step": "starting"}

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
