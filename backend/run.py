from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import uuid

from PIL import Image, ImageChops, ImageEnhance
from PIL.ExifTags import TAGS, GPSTAGS

app = Flask(__name__)

# -----------------------------
# 🔥 CORS (Vercel → Render fix)
# -----------------------------
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    supports_credentials=True
)

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

    except Exception as e:
        print("METADATA ERROR:", e)
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

        gps_data = {GPSTAGS.get(k): v for k, v in gps_info.items()}

        def convert(value):
            try:
                d = value[0][0] / value[0][1]
                m = value[1][0] / value[1][1]
                s = value[2][0] / value[2][1]
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

    except Exception as e:
        print("GPS ERROR:", e)
        return None

# -----------------------------
# ANALYSIS (PIL-based)
# -----------------------------
def analyze_image(path, job_id):

    image = Image.open(path).convert("RGB")

    # --- ELA ---
    temp = path + "_temp.jpg"
    image.save(temp, "JPEG", quality=90)

    diff = ImageChops.difference(image, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)

    # --- scoring ---
    ela_gray = ela.convert("L")
    pixels = list(ela_gray.getdata())
    mean_val = sum(pixels) / len(pixels)

    score = int((mean_val / 255) * 100)
    confidence = score

    if confidence > 60:
        result = "Likely edited"
    elif confidence > 30:
        result = "Possibly edited"
    else:
        result = "Likely original"

    # --- heatmap (visual enhancement) ---
    heat = ela.convert("RGB")
    heat = ImageEnhance.Color(heat).enhance(3)
    heat = ImageEnhance.Contrast(heat).enhance(2)

    heatmap_file = f"{job_id}_heatmap.jpg"
    heatmap_path = os.path.join(UPLOAD_FOLDER, heatmap_file)

    heat.save(heatmap_path)
    print("✅ Heatmap saved:", heatmap_path)

    return score, confidence, result, heatmap_file

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    print("🔥 ANALYZE HIT")

    file = request.files.get("image")
    print("FILE:", file)

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
        print("ERROR:", e)
        return jsonify({"status": "error", "error": str(e)})

# -----------------------------
# FILE SERVING
# -----------------------------
@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -----------------------------
# HEALTH CHECK
# -----------------------------
@app.route("/health")
def health():
    return {"status": "ok"}
