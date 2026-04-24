from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid

from PIL import Image, ImageChops, ImageEnhance
import piexif

app = Flask(__name__)

CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

# -----------------------------
# METADATA + GPS (PIEXIF)
# -----------------------------
def extract_metadata_and_gps(path):
    try:
        img = Image.open(path)
        exif_data = img.info.get("exif")

        metadata = {
            "available": False,
            "all": {}
        }
        gps = None

        if not exif_data:
            return metadata, gps

        exif_dict = piexif.load(exif_data)
        metadata["available"] = True

        for ifd in exif_dict:
            for tag in exif_dict[ifd]:
                try:
                    name = piexif.TAGS[ifd][tag]["name"]
                    value = exif_dict[ifd][tag]
                    metadata["all"][name] = str(value)
                except:
                    pass

        # GPS
        gps_ifd = exif_dict.get("GPS", {})

        if gps_ifd:
            def convert(coord):
                try:
                    d = coord[0][0] / coord[0][1]
                    m = coord[1][0] / coord[1][1]
                    s = coord[2][0] / coord[2][1]
                    return d + (m/60) + (s/3600)
                except:
                    return None

            lat = convert(gps_ifd.get(piexif.GPSIFD.GPSLatitude))
            lon = convert(gps_ifd.get(piexif.GPSIFD.GPSLongitude))

            if lat and lon:
                if gps_ifd.get(piexif.GPSIFD.GPSLatitudeRef) == b'S':
                    lat = -lat
                if gps_ifd.get(piexif.GPSIFD.GPSLongitudeRef) == b'W':
                    lon = -lon

                gps = {"lat": lat, "lon": lon}

        return metadata, gps

    except Exception as e:
        print("PIEXIF ERROR:", e)
        return {"available": False}, None

# -----------------------------
# EXPLANATIONS
# -----------------------------
def explain(score):
    if score > 60:
        return (
            "Strong signs of editing were detected.",
            "Significant irregularities in compression artifacts and pixel structure indicate likely digital manipulation."
        )
    elif score > 30:
        return (
            "Some unusual patterns detected.",
            "Moderate anomalies suggest possible recompression or editing."
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

        metadata, gps = extract_metadata_and_gps(path)

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
        print("ERROR:", e)
        return jsonify({"status":"error","error":str(e)})

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/health")
def health():
    return {"status":"ok"}
