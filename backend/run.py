from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from PIL import Image, ImageChops, ImageEnhance
import exifread
import numpy as np
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"


@app.route("/")
def home():
    return "Backend is running"


@app.route('/files/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")

    if not file:
        return jsonify({"error": "No file uploaded"}), 400

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    metadata = {}

    try:
        with open(filepath, 'rb') as f:
            tags = exifread.process_file(f)

        for tag in tags:
            metadata[tag] = str(tags[tag])

    except Exception as e:
        metadata["error"] = str(e)

    try:
        image = Image.open(filepath)
        metadata["Format"] = image.format
        metadata["Size"] = image.size
    except:
        pass

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

        mean_diff = np.mean(ela_array)
        max_diff = np.max(ela_array)

        score = int((mean_diff / (max_diff + 1e-5)) * 100)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    confidence = min(100, score + (10 if len(metadata) == 0 else 0))

    if confidence > 70:
        result = "Likely manipulated"
    elif confidence > 40:
        result = "Possibly manipulated"
    else:
        result = "No strong evidence of manipulation"

    return jsonify({
        "score": score,
        "confidence": confidence,
        "ela_result": result,
        "metadata": metadata,
        "findings": [result],
        "ela_image": f"{BASE_URL}/files/{ela_filename}"
    })


@app.route("/api/report", methods=["POST"])
def generate_report():
    data = request.json

    file_path = os.path.join(UPLOAD_FOLDER, "report.pdf")

    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()

    content = []

    content.append(Paragraph("PixelProof Report", styles["Title"]))
    content.append(Spacer(1, 10))
    content.append(Paragraph(f"Score: {data['score']}", styles["Normal"]))
    content.append(Paragraph(f"Confidence: {data['confidence']}%", styles["Normal"]))
    content.append(Paragraph(f"Result: {data['ela_result']}", styles["Normal"]))

    doc.build(content)

    return jsonify({
        "report": f"{BASE_URL}/files/report.pdf"
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
