from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid

from PIL import Image, ImageChops, ImageEnhance
import exifread

app = Flask(__name__)

# CORS (Vercel → Render)
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

# -----------------------------
# METADATA + GPS (EXIFREAD)
# -----------------------------
def extract_metadata_and_gps(path):
    try:
        with open(path, 'rb') as f:
            tags = exifread.process_file(f, details=False)

        metadata = {
            "available": False,
            "all": {}
        }

        gps = None

        if tags:
            metadata["available"] = True

            for tag in tags:
                metadata["all"][tag] = str(tags[tag])

            # ---- GPS extraction ----
            if "GPS GPSLatitude" in tags and "GPS GPSLongitude" in tags:

                def convert(coord):
                    try:
                        d = float(coord.values[0])
                        m = float(coord.values[1])
                        s = float(coord.values[2])
                        return d + (m / 60.0) + (s / 3600.0)
                    except:
                        return None

                lat = convert(tags["GPS GPSLatitude"])
                lon = convert(tags["GPS GPSLongitude"])

                if lat is not None and lon is not None:
                    if str(tags.get("GPS GPSLatitudeRef", "")).strip() == "S":
                        lat = -lat
                    if str(tags.get("GPS GPSLongitudeRef", "")).strip() == "W":
                        lon = -lon

                    gps = {"lat": lat, "lon": lon}

        return metadata, gps

    except Exception as e:
        print("EXIF ERROR:", e)
        return {"available": False}, None

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

    # ELA
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

    # Heatmap
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

# -----------------------------
# FILE SERVING
# -----------------------------
@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -----------------------------
# HEALTH
# -----------------------------
@app.route("/health")
def health():
    return {"status":"ok"}
