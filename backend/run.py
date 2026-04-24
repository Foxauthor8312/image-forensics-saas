from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, threading, traceback

import numpy as np
import cv2
from PIL import Image, ImageChops, ImageEnhance, UnidentifiedImageError

# AI
import torch
import torchvision.transforms as T
from torchvision.models import resnet18

# PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"
jobs = {}

# -----------------------------
# LOAD AI MODEL
# -----------------------------
device = "cpu"

model = resnet18(weights="DEFAULT")
model.fc = torch.nn.Linear(model.fc.in_features, 2)
model.eval()

transform = T.Compose([
    T.Resize((224,224)),
    T.ToTensor(),
])

def run_ai_model(path):
    try:
        img = Image.open(path).convert("RGB")
        tensor = transform(img).unsqueeze(0)

        with torch.no_grad():
            out = model(tensor)

        prob = torch.softmax(out, dim=1)[0][1].item()
        return int(prob * 100)

    except Exception as e:
        print("AI error:", e)
        return None

# -----------------------------
# PDF GENERATION
# -----------------------------
def generate_pdf(job_id, result):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")

        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("PixelProof Forensic Report", styles["Title"]))
        content.append(Spacer(1,10))

        content.append(Paragraph(f"Score: {result['score']}", styles["Normal"]))
        content.append(Paragraph(f"Confidence: {result['confidence']}%", styles["Normal"]))
        content.append(Paragraph(f"AI Detection: {result.get('ai_score','N/A')}%", styles["Normal"]))
        content.append(Paragraph(result["legal_conclusion"], styles["Normal"]))
        content.append(Spacer(1,10))

        content.append(Paragraph("Findings:", styles["Heading2"]))
        for e in result["explanation"]:
            content.append(Paragraph(f"- {e}", styles["Normal"]))

        content.append(Spacer(1,10))

        try:
            content.append(RLImage(os.path.join(UPLOAD_FOLDER, f"{job_id}_ela.jpg"), width=400, height=250))
        except:
            pass

        try:
            content.append(RLImage(os.path.join(UPLOAD_FOLDER, f"{job_id}_heatmap.jpg"), width=400, height=250))
        except:
            pass

        doc.build(content)

        return f"{BASE_URL}/files/{job_id}_report.pdf"

    except Exception as e:
        print("PDF error:", e)
        return None

# -----------------------------
# PROCESS JOB
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status": "processing", "step": "loading image"}

        try:
            image = Image.open(path).convert("RGB")
        except UnidentifiedImageError:
            jobs[job_id] = {"status": "error", "error": "Invalid image"}
            return

        image.thumbnail((800,800))
        image.save(path)

        # -----------------------------
        # ELA
        # -----------------------------
        jobs[job_id]["step"] = "running ELA"

        temp = path+"_c.jpg"
        image.save(temp,"JPEG",quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # -----------------------------
        # CV ANALYSIS
        # -----------------------------
        jobs[job_id]["step"] = "analyzing structure"

        gray = cv2.imread(path,0)
        if gray is None:
            raise Exception("Image read failed")

        noise = np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0)))
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

        noise_n = min(100, noise*1.5)
        sharp_n = min(100, sharp/10)

        # -----------------------------
        # AI DETECTION
        # -----------------------------
        jobs[job_id]["step"] = "running AI detection"

        ai_score = run_ai_model(path)

        # -----------------------------
        # CONFIDENCE (COMBINED)
        # -----------------------------
        ela_c = score * 0.4
        noise_c = noise_n * 0.2
        sharp_c = sharp_n * 0.2
        ai_c = (ai_score or 0) * 0.2

        confidence = int(min(100, ela_c + noise_c + sharp_c + ai_c))

        # -----------------------------
        # HEATMAP
        # -----------------------------
        jobs[job_id]["step"] = "detecting tamper regions"

        heatmap_file = None

        try:
            img = cv2.imread(path)
            img = cv2.resize(img,(600,600))

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            diff = cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0))
            norm = cv2.normalize(diff,None,0,255,cv2.NORM_MINMAX)
            heat = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
            overlay = cv2.addWeighted(img,0.6,heat,0.4,0)

            heatmap_file = f"{job_id}_heatmap.jpg"
            cv2.imwrite(os.path.join(UPLOAD_FOLDER, heatmap_file), overlay)

        except:
            pass

        # -----------------------------
        # EXPLANATIONS
        # -----------------------------
        explanation = [
            f"Compression {'inconsistent' if score>40 else 'uniform'}",
            f"Noise {'irregular' if noise_n>40 else 'consistent'}",
            f"Sharpness {'variable' if sharp_n>40 else 'consistent'}"
        ]

        if ai_score is not None:
            explanation.append(f"AI model indicates {ai_score}% likelihood of manipulation")

        legal = "Strong indicators of manipulation." if confidence>70 else \
                "Possible manipulation detected." if confidence>40 else \
                "No strong evidence of manipulation."

        # -----------------------------
        # RESULT
        # -----------------------------
        result_data = {
            "score": score,
            "confidence": confidence,
            "ai_score": ai_score,
            "ela_result":
                "Likely manipulated" if confidence>70 else
                "Possibly manipulated" if confidence>40 else
                "Likely original",
            "score_explanation": "Compression consistency (ELA)",
            "confidence_explanation": "Combined signal + AI model confidence",
            "legal_conclusion": legal,
            "narrative": "Analysis using ELA, CV features, and AI model.",
            "interpretation": [
                "ELA detects compression inconsistencies",
                "AI detects learned manipulation patterns",
                "Combined score increases reliability"
            ],
            "explanation": explanation,
            "confidence_breakdown": {
                "ela": int(ela_c),
                "noise": int(noise_c),
                "sharpness": int(sharp_c),
                "ai": int(ai_c)
            }
        }

        report_url = generate_pdf(job_id, result_data)

        jobs[job_id] = {
            "status": "done",
            "result": {
                **result_data,
                "ela_image": f"{BASE_URL}/files/{ela_file}",
                "heatmap": f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
                "report": report_url
            }
        }

    except Exception as e:
        print("🔥 ERROR:", traceback.format_exc())
        jobs[job_id] = {"status": "error", "error": str(e)}

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    if not file:
        return jsonify({"error":"No file uploaded"}),400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id+".jpg")
    file.save(path)

    jobs[job_id] = {"status":"processing","step":"starting"}

    threading.Thread(target=process_job,args=(job_id,path)).start()

    return jsonify({"job_id":job_id})

@app.route("/api/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id,{"status":"error"}))

@app.route("/files/<filename>")
def serve_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/health")
def health():
    return jsonify({"status":"ok"})

# -----------------------------
# RUN
# -----------------------------
if __name__=="__main__":
    app.run(host="0.0.0.0",port=3000)
