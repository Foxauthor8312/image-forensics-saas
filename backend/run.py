from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance
from PIL.ExifTags import TAGS, GPSTAGS

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

# -----------------------------
# METADATA
# -----------------------------
def extract_metadata(path):
    try:
        img = Image.open(path)
        exif = img._getexif()

        data = {
            "available": False,
            "ImageWidth": img.width,
            "ImageHeight": img.height,
            "all": {}
        }

        if exif:
            for tag, value in exif.items():
                name = TAGS.get(tag, str(tag))
                data["all"][name] = str(value)

            data["available"] = True

        return data

    except:
        return {"available": False}

# -----------------------------
# GPS
# -----------------------------
def extract_gps(path):
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return None

        gps_info = None
        for tag, val in exif.items():
            if TAGS.get(tag) == "GPSInfo":
                gps_info = val
                break

        if not gps_info:
            return None

        gps_data = {}
        for k, v in gps_info.items():
            gps_data[GPSTAGS.get(k)] = v

        def convert(value):
            try:
                if isinstance(value[0], tuple):
                    d = value[0][0] / value[0][1]
                    m = value[1][0] / value[1][1]
                    s = value[2][0] / value[2][1]
                else:
                    d, m, s = value
                return d + (m / 60.0) + (s / 3600.0)
            except:
                return None

        lat = convert(gps_data.get("GPSLatitude"))
        lon = convert(gps_data.get("GPSLongitude"))

        if lat is None or lon is None:
            return None

        if gps_data.get("GPSLatitudeRef") == "S":
            lat = -lat
        if gps_data.get("GPSLongitudeRef") == "W":
            lon = -lon

        return {"lat": lat, "lon": lon}

    except:
        return None

# -----------------------------
# ANALYSIS + HEATMAP
# -----------------------------
def analyze_image(path, job_id):

    image = Image.open(path).convert("RGB")

    # --- ELA ---
    temp = path + "_temp.jpg"
    image.save(temp, "JPEG", quality=90)

    diff = ImageChops.difference(image, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)
    ela_np = np.array(ela)
    ela_gray = cv2.cvtColor(ela_np, cv2.COLOR_BGR2GRAY)

    # --- OpenCV ---
    img = cv2.imread(path)
    if img is None:
        return 0, 0, "Error", None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    noise = cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))
    edges = cv2.Canny(gray, 100, 200)

    ela_n = cv2.normalize(ela_gray,None,0,255,cv2.NORM_MINMAX)
    noise_n = cv2.normalize(noise,None,0,255,cv2.NORM_MINMAX)
    edge_n = cv2.normalize(edges,None,0,255,cv2.NORM_MINMAX)

    combined = (0.5*ela_n + 0.3*noise_n + 0.2*edge_n).astype(np.uint8)
    combined = cv2.GaussianBlur(combined,(5,5),0)
    combined = cv2.equalizeHist(combined)

    # --- Heatmap ---
    heat = cv2.applyColorMap(combined, cv2.COLORMAP_JET)
    overlay = cv2.addWeighted(img, 0.6, heat, 0.4, 0)

    heatmap_file = f"{job_id}_heatmap.jpg"
    heatmap_path = os.path.join(UPLOAD_FOLDER, heatmap_file)

    cv2.imwrite(heatmap_path, overlay)

    # --- scoring ---
    score = int(np.mean(ela_gray)/255*100)
    confidence = int(np.mean(combined)/255*100)

    if confidence > 70:
        result = "Likely edited"
    elif confidence > 40:
        result = "Possibly edited"
    else:
        result = "Likely original"

    return score, confidence, result, heatmap_file

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "No file"}), 400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id + ".jpg")
    file.save(path)

    try:
        img = Image.open(path)
        width, height = img.size

        score, confidence, result_text, heatmap_file = analyze_image(path, job_id)

        metadata = extract_metadata(path)
        gps = extract_gps(path)

        return jsonify({
            "status": "done",
            "result": {
                "message": f"Image processed: {width}x{height}",
                "score": score,
                "confidence": confidence,
                "analysis": result_text,
                "metadata": metadata,
                "gps": gps,
                "heatmap": f"{BASE_URL}/files/{heatmap_file}"
            }
        })

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/health")
def health():
    return {"status": "ok"}
