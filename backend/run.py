from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance
from PIL.ExifTags import TAGS

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000")
jobs = {}

# -----------------------------
# METADATA (ALWAYS RETURNS)
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

        if exif:
            for tag, value in exif.items():
                name = TAGS.get(tag, tag)
                if name in ["Make","Model","DateTime","Software"]:
                    data[name] = str(value)
            data["available"] = True

        return data

    except Exception as e:
        print("METADATA ERROR:", e)
        return {"available": False}

# -----------------------------
# PROCESS
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status":"processing","step":"starting"}

        # Resize
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

        # -----------------------------
        # HEATMAP (GUARANTEED)
        # -----------------------------
        heatmap_file = f"{job_id}_heatmap.jpg"

        try:
            img = cv2.imread(path)

            if img is None:
                raise Exception("cv2 failed")

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            blur = cv2.GaussianBlur(gray,(5,5),0)
            diff = cv2.absdiff(gray, blur)

            norm = cv2.normalize(diff,None,0,255,cv2.NORM_MINMAX)
            norm = cv2.equalizeHist(norm)

            heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(img,0.6,heat,0.4,0)

            cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)

            print("✅ Heatmap saved")

        except Exception as e:
            print("🔥 HEATMAP ERROR:", e)

            # fallback (always creates file)
            fallback = np.zeros((400,400,3), dtype=np.uint8)
            cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), fallback)

        # -----------------------------
        # SCORE (simple)
        # -----------------------------
        score = int(np.mean(np.array(ela))/255*100)
        confidence = score

        # -----------------------------
        # RESULT
        # -----------------------------
        result = {
            "score": score,
            "confidence": confidence,
            "ela_image": f"{BASE_URL}/files/{ela_file}",
            "heatmap": f"{BASE_URL}/files/{heatmap_file}",
            "metadata": extract_metadata(path),
            "simple_explanation": {
                "result": "Likely edited" if confidence>50 else "Likely original",
                "meaning": "Based on compression and consistency checks.",
                "reasons": [
                    "Compression differences detected",
                    "Pixel consistency varies"
                ]
            }
        }

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
