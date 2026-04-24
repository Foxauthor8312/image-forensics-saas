from flask import Flask, request, jsonify
from flask_cors import CORS
import os, uuid

from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

jobs = {}

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
# GPS
# -----------------------------
def extract_gps(path):
    try:
        img = Image.open(path)
        exif = img._getexif()

        if not exif:
            return None

        gps_data = {}

        for tag, val in exif.items():
            if TAGS.get(tag) == "GPSInfo":
                for k in val:
                    gps_data[GPSTAGS.get(k)] = val[k]

        if "GPSLatitude" in gps_data and "GPSLongitude" in gps_data:

            def convert(c):
                return c[0][0]/c[0][1] + c[1][0]/c[1][1]/60 + c[2][0]/c[2][1]/3600

            lat = convert(gps_data["GPSLatitude"])
            lon = convert(gps_data["GPSLongitude"])

            if gps_data.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps_data.get("GPSLongitudeRef") == "W":
                lon = -lon

            return {"lat": lat, "lon": lon}

    except Exception as e:
        print("GPS ERROR:", e)

    return None

# -----------------------------
# ANALYZE (SYNC)
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    if not file:
        return jsonify({"error":"No file"}),400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id+".jpg")
    file.save(path)

    try:
        img = Image.open(path)
        width, height = img.size

        metadata = extract_metadata(path)
        gps = extract_gps(path)

        result = {
            "score": 50,
            "confidence": 50,
            "message": f"Image processed: {width}x{height}",
            "metadata": metadata,
            "gps": gps
        }

        # return result immediately (NO THREAD)
        return jsonify({
            "status": "done",
            "result": result
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        })

# -----------------------------
@app.route("/health")
def health():
    return {"status":"ok"}
