from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import uuid

import numpy as np
from PIL import Image, ImageChops, ImageEnhance
from PIL.ExifTags import TAGS, GPSTAGS

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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

    except Exception as e:
        print("GPS ERROR:", e)
        return None

def analyze_image(path):
    image = Image.open(path).convert("RGB")

    temp = path + "_temp.jpg"
    image.save(temp, "JPEG", quality=90)

    diff = ImageChops.difference(image, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)

    arr = np.array(ela)
    score = int(np.mean(arr) / 255 * 100)

    if score > 60:
        result = "Likely edited"
    elif score > 30:
        result = "Possibly edited"
    else:
        result = "Likely original"

    return score, result

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

        score, result_text = analyze_image(path)
        metadata = extract_metadata(path)
        gps = extract_gps(path)

        return jsonify({
            "status": "done",
            "result": {
                "message": f"Image processed: {width}x{height}",
                "score": score,
                "confidence": score,
                "analysis": result_text,
                "metadata": metadata,
                "gps": gps
            }
        })

    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})

@app.route("/health")
def health():
    return {"status": "ok"}
