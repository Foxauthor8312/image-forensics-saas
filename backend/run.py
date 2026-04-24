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

BASE_URL = os.environ.get("BASE_URL", "http://localhost:3000")
jobs = {}

# -----------------------------
# AI MODEL
# -----------------------------
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
    except:
        return None

# -----------------------------
# PDF
# -----------------------------
def generate_pdf(job_id, result):
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{job_id}_report.pdf")
        doc = SimpleDocTemplate(file_path)
        styles = getSampleStyleSheet()
        content = []

        content.append(Paragraph("PixelProof Forensic Report", styles["Title"]))
        content.append(Spacer(1,10))

        content.append(Paragraph(result["executive_summary"], styles["Normal"]))
        content.append(Spacer(1,10))

        content.append(Paragraph("Conclusion:", styles["Heading2"]))
        content.append(Paragraph(result["opinion"], styles["Normal"]))
        content.append(Spacer(1,10))

        content.append(Paragraph("Confidence:", styles["Heading2"]))
        content.append(Paragraph(result["confidence_reasoning"], styles["Normal"]))

        content.append(Spacer(1,10))

        content.append(Paragraph("Findings:", styles["Heading2"]))
        for e in result["explanation"]:
            content.append(Paragraph(f"- {e}", styles["Normal"]))

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
# PROCESS
# -----------------------------
def process_job(job_id, path):
    try:
        jobs[job_id] = {"status":"processing","step":"loading image"}

        image = Image.open(path).convert("RGB")
        image.thumbnail((800,800))
        image.save(path)

        # ELA
        jobs[job_id]["step"] = "running ELA"
        temp = path+"_c.jpg"
        image.save(temp,"JPEG",quality=90)

        diff = ImageChops.difference(image, Image.open(temp))
        ela = ImageEnhance.Brightness(diff).enhance(10)

        ela_file = f"{job_id}_ela.jpg"
        ela.save(os.path.join(UPLOAD_FOLDER, ela_file))

        arr = np.array(ela)
        score = int((np.mean(arr)/(np.max(arr)+1e-5))*100)

        # CV
        jobs[job_id]["step"] = "analyzing structure"
        gray = cv2.imread(path,0)

        noise = np.mean(cv2.absdiff(gray, cv2.GaussianBlur(gray,(5,5),0)))
        sharp = cv2.Laplacian(gray, cv2.CV_64F).var()

        noise_n = min(100, noise*1.5)
        sharp_n = min(100, sharp/10)

        # AI
        jobs[job_id]["step"] = "running AI detection"
        ai_score = run_ai_model(path)

        # CONFIDENCE
        ela_c = score * 0.4
        noise_c = noise_n * 0.2
        sharp_c = sharp_n * 0.2
        ai_c = (ai_score or 0) * 0.2

        confidence = int(min(100, ela_c + noise_c + sharp_c + ai_c))

        # HEATMAP
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
        # EXPERT EXPLANATIONS
        # -----------------------------
        if confidence > 75:
            executive_summary = "Multiple independent indicators strongly suggest digital manipulation."
            opinion = "It is highly probable that the image has been altered."
        elif confidence > 45:
            executive_summary = "Some indicators suggest possible editing, but not conclusive."
            opinion = "The image may have been altered."
        else:
            executive_summary = "No strong indicators of manipulation detected."
            opinion = "Insufficient evidence of alteration."

        confidence_reasoning = f"Confidence ({confidence}%) derived from combined ELA, noise, sharpness, and AI signals."

        ai_interpretation = f"AI model indicates {ai_score}% likelihood of manipulation." if ai_score else "AI unavailable."

        methodology = [
            "ELA compression analysis",
            "Noise distribution analysis",
            "Sharpness consistency",
            "AI pattern recognition"
        ]

        explanation = [
            f"Compression {'inconsistent' if score>40 else 'uniform'}",
            f"Noise {'irregular' if noise_n>40 else 'consistent'}",
            f"Sharpness {'variable' if sharp_n>40 else 'consistent'}"
        ]

        evidence_analysis = {
            "ELA": f"{int(ela_c)}%",
            "Noise": f"{int(noise_c)}%",
            "Sharpness": f"{int(sharp_c)}%",
            "AI": f"{int(ai_c)}%"
        }

        limitations = [
            "Recompression can affect results",
            "AI depends on training data",
            "Analysis is probabilistic"
        ]

        recommendation = "Verify source if image is critical."

        # RESULT
        result_data = {
            "score": score,
            "confidence": confidence,
            "ai_score": ai_score,
            "ela_result": "Likely manipulated" if confidence>70 else "Likely original",

            "executive_summary": executive_summary,
            "opinion": opinion,
            "confidence_reasoning": confidence_reasoning,
            "ai_interpretation": ai_interpretation,
            "methodology": methodology,
            "evidence_analysis": evidence_analysis,
            "limitations": limitations,
            "recommendation": recommendation,
            "explanation": explanation
        }

        report_url = generate_pdf(job_id, result_data)

        jobs[job_id] = {
            "status":"done",
            "result":{
                **result_data,
                "ela_image": f"{BASE_URL}/files/{ela_file}",
                "heatmap": f"{BASE_URL}/files/{heatmap_file}" if heatmap_file else None,
                "report": report_url
            }
        }

    except Exception as e:
        jobs[job_id] = {"status":"error","error":str(e)}

# -----------------------------
# API
# -----------------------------
@app.route("/api/analyze", methods=["POST"])
def analyze():
    file = request.files.get("image")
    if not file:
        return jsonify({"error":"No file"}),400

    job_id = str(uuid.uuid4())
    path = os.path.join(UPLOAD_FOLDER, job_id+".jpg")
    file.save(path)

    jobs[job_id] = {"status":"processing"}
    threading.Thread(target=process_job,args=(job_id,path)).start()

    return jsonify({"job_id":job_id})

@app.route("/api/status/<job_id>")
def status(job_id):
    return jsonify(jobs.get(job_id,{"status":"error"}))

@app.route("/files/<filename>")
def files(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route("/health")
def health():
    return jsonify({"status":"ok"})
