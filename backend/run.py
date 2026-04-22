from PIL import Image, ImageChops, ImageEnhance
import exifread
import numpy as np

from flask import send_from_directory
from flask import Flask, request, jsonify
from flask_cors import CORS
import os

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route("/")
def home():
    return "Backend is running"

@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")

    if not file:
        return jsonify({"error": "No file"}), 400

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    # --- EXIF METADATA ---
    with open(filepath, 'rb') as f:
        tags = exifread.process_file(f)

    metadata = {}
    for i, (k, v) in enumerate(tags.items()):
        if i >= 10:
            break
        metadata[k] = str(v)

    # --- ELA (Error Level Analysis) ---
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

    # --- SCORE ---
    ela_array = np.array(ela_image)
    score = int(np.mean(ela_array))

    findings = []
    if score > 20:
        findings.append("High compression differences detected")
    else:
        findings.append("No strong manipulation signals")

    return jsonify({
        "score": score,
        "ela_result": "Potential manipulation" if score > 20 else "Likely original",
        "metadata": metadata,
        "findings": findings,
        "ela_image": f"/files/{ela_filename}"
    })
@app.route('/files/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)
if __name__ == "__main__":
    app.run()
