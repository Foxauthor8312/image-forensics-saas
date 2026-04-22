from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from PIL import Image, ImageChops, ImageEnhance
import exifread
import numpy as np

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "BASE_URL = "https://pixelproof-backend-v2.onrender.com""  # 🔥 CHANGE THIS

# -----------------------------
# Home route
# -----------------------------
@app.route("/")
def home():
    return "Backend is running"

# -----------------------------
# Serve generated files
# -----------------------------
@app.route('/files/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# -----------------------------
# Analyze image
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")

    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    # -----------------------------
    # EXIF METADATA
    # -----------------------------
    metadata = {}

    try:
        with open(filepath, 'rb') as f:
            tags = exifread.process_file(f)

        for tag in tags.keys():
            try:
                metadata[tag] = str(tags[tag])
            except:
                metadata[tag] = "Unreadable"

        # GPS extraction
        gps_data = {}
        for tag in tags:
            if "GPS" in tag:
                gps_data[tag] = str(tags[tag])

        if gps_data:
            metadata["GPS"] = gps_data

    except Exception as e:
        metadata["error"] = str(e)

    # -----------------------------
    # PIL METADATA
    # -----------------------------
    try:
        image = Image.open(filepath)

        metadata["Format"] = image.format
        metadata["Mode"] = image.mode
        metadata["Size"] = image.size

        if hasattr(image, "info"):
            for k, v in image.info.items():
                metadata[k] = str(v)

    except Exception as e:
        metadata["pil_error"] = str(e)

    # -----------------------------
    # ELA (Error Level Analysis)
    # -----------------------------
    try:
        original = Image.open(filepath).convert('RGB')

        temp_path = filepath + "_compressed.jpg"
        original.save(temp_path, 'JPEG', quality=90)

        compressed = Image.open(temp_path)
        diff = ImageChops.difference(original, compressed)

        enhancer = ImageEnhance.Brightness(diff)
        ela_image = enhancer.enhance(10)

        ela_filename = os.path.basename(filepath) + "_ela.jpg"
        ela_path = os.path.join(UPLOAD_FOLDER, ela_filename)
        ela_image.save(ela_path)

        ela_array = np.array(ela_image)
        score = int(np.mean(ela_array))

    except Exception as e:
        return jsonify({"error": f"ELA processing failed: {str(e)}"}), 500

    # -----------------------------
    # Findings logic
    # -----------------------------
    findings = []

    if score > 20:
        findings.append("High compression differences detected")
    else:
        findings.append("No strong manipulation signals")

    if len(metadata) == 0:
        findings.append("No metadata found (possibly stripped)")

    # -----------------------------
    # Response
    # -----------------------------
    return jsonify({
        "score": score,
        "ela_result": "Potential manipulation" if score > 20 else "Likely original",
        "metadata": metadata,
        "findings": findings,
        "ela_image": f"{BASE_URL}/files/{ela_filename}"
    })


# -----------------------------
# Run server
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
