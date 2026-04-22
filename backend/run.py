from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import numpy as np
import cv2

from PIL import Image, ImageChops, ImageEnhance
import exifread

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"


# -----------------------------
# SAFE ANALYSIS FUNCTIONS
# -----------------------------

def analyze_noise(image_path):
    try:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0

        blur = cv2.GaussianBlur(img, (5, 5), 0)
        noise = cv2.absdiff(img, blur)

        return float(np.mean(noise))
    except:
        return 0


def analyze_sharpness(image_path):
    try:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0

        laplacian = cv2.Laplacian(img, cv2.CV_64F)
        return float(laplacian.var())
    except:
        return 0


# -----------------------------
# ROUTES
# -----------------------------

@app.route("/")
def home():
    return "Backend is running"


@app.route("/files/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# -----------------------------
# ANALYZE
# -----------------------------

@app.route("/api/analyze", methods=["POST"])
def analyze():
    try:
        file = request.files.get("image")

        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        # Safe filename
        filename = "upload.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        metadata = {}

        # -----------------------------
        # EXIF
        # -----------------------------
        try:
            with open(filepath, 'rb') as f:
                tags = exifread.process_file(f)

            for tag in tags:
                metadata[tag] = str(tags[tag])
        except:
            pass

        # -----------------------------
        # PIL metadata
        # -----------------------------
        try:
            image = Image.open(filepath)
            image = image.convert("RGB")

            metadata["Format"] = image.format
            metadata["Size"] = image.size
        except:
            pass

        # -----------------------------
        # ELA
        # -----------------------------
        try:
            original = Image.open(filepath).convert("RGB")

            temp_path = filepath + "_compressed.jpg"
            original.save(temp_path, "JPEG", quality=90)

            compressed = Image.open(temp_path)
            diff = ImageChops.difference(original, compressed)

            enhancer = ImageEnhance.Brightness(diff)
            ela_image = enhancer.enhance(10)

            ela_filename = "ela.jpg"
            ela_path = os.path.join(UPLOAD_FOLDER, ela_filename)
            ela_image.save(ela_path)

            ela_array = np.array(ela_image)

            mean_diff = np.mean(ela_array)
            max_diff = np.max(ela_array)

            score = int((mean_diff / (max_diff + 1e-5)) * 100)

        except Exception as e:
            return jsonify({"error": f"ELA failed: {str(e)}"}), 500

        # -----------------------------
        # ADVANCED ANALYSIS
        # -----------------------------
        noise_score = analyze_noise(filepath)
        sharpness_score = analyze_sharpness(filepath)

        noise_norm = min(100, noise_score / 2)
        sharpness_norm = min(100, sharpness_score / 50)

        # -----------------------------
        # CONFIDENCE
        # -----------------------------
        confidence = (
            score * 0.4 +
            noise_norm * 0.3 +
            sharpness_norm * 0.3
        )

        if len(metadata) == 0:
            confidence += 10

        confidence = int(max(0, min(100, confidence)))

        # -----------------------------
        # FINDINGS
        # -----------------------------
        findings = []

        if score > 50:
            findings.append("Compression inconsistencies detected")

        if noise_norm > 40:
            findings.append("Noise pattern inconsistency detected")

        if sharpness_norm > 40:
            findings.append("Sharpness irregularities detected")

        if len(metadata) == 0:
            findings.append("Metadata missing or stripped")

        if not findings:
            findings.append("No strong forensic anomalies detected")

        # -----------------------------
        # RESULT
        # -----------------------------
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
            "findings": findings,
            "ela_image": f"{BASE_URL}/files/{ela_filename}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------
# PDF REPORT
# -----------------------------

@app.route("/api/report", methods=["POST"])
def generate_report():
    try:
        data = request.json

        file_path = os.path.join(UPLOAD_FOLDER, "report.pdf")

        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()

        content = []

        content.append(Paragraph("PixelProof Report", styles["Title"]))
        content.append(Spacer(1, 10))
        content.append(Paragraph(f"Score: {data.get('score')}", styles["Normal"]))
        content.append(Paragraph(f"Confidence: {data.get('confidence')}%", styles["Normal"]))
        content.append(Paragraph(f"Result: {data.get('ela_result')}", styles["Normal"]))

        doc.build(content)

        return jsonify({
            "report": f"{BASE_URL}/files/report.pdf"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
