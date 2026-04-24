from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid

from PIL import Image, ImageChops, ImageEnhance
from PIL.ExifTags import TAGS, GPSTAGS

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

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

        gps_data = {GPSTAGS.get(k): v for k, v in gps_info.items()}

        def convert(v):
            try:
                d = v[0][0]/v[0][1]
                m = v[1][0]/v[1][1]
                s = v[2][0]/v[2][1]
                return d + m/60 + s/3600
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
# EXPLANATIONS
# -----------------------------
def explain(score):
    if score > 60:
        return (
            "Strong signs of editing were detected.",
            "Analysis reveals significant irregularities in compression artifacts and pixel structure consistent with digital manipulation."
        )
    elif score > 30:
        return (
            "Some unusual patterns detected.",
            "Moderate anomalies detected which may indicate recompression or editing."
        )
    else:
        return (
            "Image appears original.",
            "No material inconsistencies detected in compression or pixel structure."
        )

# -----------------------------
# ANALYSIS
# -----------------------------
def analyze_image(path, job_id):

    image = Image.open(path).convert("RGB")

    temp = path + "_temp.jpg"
    image.save(temp, "JPEG", quality=90)

    diff = ImageChops.difference(image, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)

    gray = ela.convert("L")
    pixels = list(gray.getdata())
    mean_val = sum(pixels) / len(pixels)

    score = int((mean_val / 255) * 100)
    confidence = score

    result = (
        "Likely edited" if score > 60 else
        "Possibly edited" if score > 30 else
        "Likely original"
    )

    simple, legal = explain(score)

    # heatmap
    heat = ela.convert("RGB")
    heat = ImageEnhance.Color(heat).enhance(3)
    heat = ImageEnhance.Contrast(heat).enhance(2)

    heatmap_file = f"{job_id}_heatmap.jpg"
    heat.save(os.path.join(UPLOAD_FOLDER, heatmap_file))

    return score, confidence, result, simple, legal, heatmap_file

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
        w, h = img.size

        score, confidence, result, simple, legal, heatmap = analyze_image(path, job_id)

        metadata = extract_metadata(path)
        gps = extract_gps(path)

        return jsonify({
            "status": "done",
            "result": {
                "message": f"{w}x{h} processed",
                "analysis": result,
                "score": score,
                "confidence": confidence,
                "simple_explanation": simple,
                "legal_explanation": legal,
                "metadata": metadata,
                "gps": gps,
                "heatmap": f"{BASE_URL}/files/{heatmap}"
            }
        })

    except Exception as e:
        return jsonify({"status":"error","error":str(e)})

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/health")
def health():
    return {"status":"ok"}
