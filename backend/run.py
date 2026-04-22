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

# 🔥 CHANGE THIS TO YOUR ACTUAL RENDER URL
BASE_URL = "https://pixelproof-backend-v2.onrender.com"


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

    metadata = {}

    # -----------------------------
    # EXIF METADATA
    # -----------------------------
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
        metadata["exif_error"] = str(e)

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
        mean_diff = np.mean(ela_array)
        max_diff = np.max(ela_array)

# Normalize score (0–100)
score = int((mean_diff / (max_diff + 1e-5)) * 100)

    except Exception as e:
        return jsonify({"error": f"ELA processing failed: {str(e)}"}), 500

    # -----------------------------
    # Findings logic
    # -----------------------------
    findings = []

    findings = []

if score > 60:
    findings.append("Strong signs of manipulation (high compression inconsistency)")
    result = "Likely manipulated"

elif score > 30:
    findings.append("Moderate inconsistencies detected")
    result = "Possibly manipulated"

else:
    findings.append("Low compression differences detected")
    result = "No strong evidence of manipulation"

    # -----------------------------
    # Response
    # -----------------------------
    return jsonify({
        "score": score,
        "ela_result": result,
        "metadata": metadata,
        "findings": findings,
        "ela_image": f"{BASE_URL}/files/{ela_filename}"
    })


# -----------------------------
# Generate PDF report
# -----------------------------
@app.route("/api/report", methods=["POST"])
def generate_report():
    data = request.json

    filename = "report.pdf"
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()

    content = []

    content.append(Paragraph("PixelProof Forensic Report", styles["Title"]))
    content.append(Spacer(1, 12))

    content.append(Paragraph(f"Score: {data['score']}", styles["Normal"]))
    content.append(Paragraph(f"Conclusion: {data['ela_result']}", styles["Normal"]))
    content.append(Spacer(1, 10))

    content.append(Paragraph("Findings:", styles["Heading2"]))
    for f in data["findings"]:
        content.append(Paragraph(f"- {f}", styles["Normal"]))

    content.append(Spacer(1, 10))
    content.append(Paragraph("Metadata Summary:", styles["Heading2"]))

    # limit metadata to avoid huge PDF
    metadata_items = list(data.get("metadata", {}).items())[:15]

    for k, v in metadata_items:
        content.append(Paragraph(f"{k}: {v}", styles["Normal"]))

    doc.build(content)

    return jsonify({
        "report": f"{BASE_URL}/files/{filename}"
    })


# -----------------------------
# Run locally (not used on Render)
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
