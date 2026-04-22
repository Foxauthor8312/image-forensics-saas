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

    # Fake result (for now, just to get live)
    return jsonify({
        "original_image": f"/{filepath}",
        "heatmap_image": f"/{filepath}",
        "score": 42,
        "ela_result": "Demo result",
        "findings": ["Demo analysis"]
    })

if __name__ == "__main__":
    app.run()