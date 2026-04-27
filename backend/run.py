from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os, uuid, json, hashlib
import numpy as np

from PIL import Image, ImageChops, ImageEnhance, ImageFilter
from PIL.ExifTags import TAGS, GPSTAGS

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)
CORS(app)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

BASE_URL = "https://pixelproof-backend-v2.onrender.com"

# =========================
# HASH
# =========================
def generate_file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

# =========================
# EXIF EXTRACTION
# =========================
def extract_exif(path):
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return {}, None

        meta, gps_data = {}, {}

        for tag, val in exif.items():
            name = TAGS.get(tag, tag)
            meta[name] = val

            if name == "GPSInfo":
                for t in val:
                    sub = GPSTAGS.get(t, t)
                    gps_data[sub] = val[t]

        def convert(c):
            return c[0][0]/c[0][1] + c[1][0]/c[1][1]/60 + c[2][0]/c[2][1]/3600

        gps = None
        if "GPSLatitude" in gps_data and "GPSLongitude" in gps_data:
            lat = convert(gps_data["GPSLatitude"])
            lon = convert(gps_data["GPSLongitude"])

            if gps_data.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps_data.get("GPSLongitudeRef") == "W":
                lon = -lon

            gps = {"lat": lat, "lon": lon, "source": "EXIF"}

        return meta, gps
    except:
        return {}, None

# =========================
# ANALYSIS
# =========================
def ela_score(img, path):
    temp = path+"_temp.jpg"
    img.save(temp, "JPEG", quality=90)
    diff = ImageChops.difference(img, Image.open(temp))
    ela = ImageEnhance.Brightness(diff).enhance(10)
    return np.mean(np.array(ela.convert("L")))/255*100, ela

def noise_score(img):
    g = np.array(img.convert("L"))
    blur = Image.fromarray(g).filter(ImageFilter.GaussianBlur(3))
    return np.std(np.abs(g-np.array(blur)))/255*100

def edge_score(img):
    return np.mean(np.array(img.filter(ImageFilter.FIND_EDGES).convert("L")))/255*100

def block_score(img):
    g = np.array(img.convert("L"))
    blocks=[np.std(g[y:y+8,x:x+8]) for y in range(0,g.shape[0]-8,8) for x in range(0,g.shape[1]-8,8)]
    return np.std(blocks)/255*100

def metadata_score(meta):
    txt=str(meta).lower()
    if "photoshop" in txt or "adobe" in txt: return 80
    return 30

def combine(s):
    w={"ela":0.3,"noise":0.2,"edge":0.2,"block":0.2,"meta":0.1}
    score=sum(s[k]*w[k] for k in w)
    conf=100-np.std(list(s.values()))
    return int(score), int(max(0,min(100,conf)))

def explain(score):
    if score>70:
        return ("Strong signs of manipulation detected.",
                "Multiple forensic signals show inconsistencies.",
                "The image shows characteristics of alteration.",
                "High confidence.")
    elif score>40:
        return ("Possible editing detected.",
                "Moderate inconsistencies found.",
                "The image may have been altered.",
                "Moderate confidence.")
    else:
        return ("Image appears original.",
                "Signals are consistent.",
                "No manipulation detected.",
                "High confidence.")

# =========================
# PDF
# =========================
def generate_pdf(job_id, d):
    path=os.path.join(UPLOAD_FOLDER,f"{job_id}.pdf")
    doc=SimpleDocTemplate(path)
    styles=getSampleStyleSheet()

    c=[]
    c.append(Paragraph("Forensic Report",styles["Title"]))
    c.append(Spacer(1,12))

    c.append(Paragraph(f"Result: {d['analysis']}",styles["Normal"]))
    c.append(Paragraph(f"Score: {d['score']}%",styles["Normal"]))
    c.append(Paragraph(f"Confidence: {d['confidence']}%",styles["Normal"]))
    c.append(Spacer(1,12))

    orig=os.path.join(UPLOAD_FOLDER,f"{job_id}.jpg")
    heat=os.path.join(UPLOAD_FOLDER,f"{job_id}_heat.jpg")

    if os.path.exists(orig): c.append(RLImage(orig,width=400,height=250))
    if os.path.exists(heat): c.append(RLImage(heat,width=400,height=250))

    c.append(Spacer(1,12))
    c.append(Paragraph(d["technical_explanation"],styles["Normal"]))

    for k,v in d["signals"].items():
        c.append(Paragraph(f"{k}: {v}",styles["Normal"]))

    doc.build(c)
    return f"{BASE_URL}/files/{job_id}.pdf"

# =========================
# ROUTE
# =========================
@app.route("/api/analyze",methods=["POST"])
def analyze():

    file=request.files["image"]
    fmeta=json.loads(request.form.get("metadata","{}"))
    fgps=json.loads(request.form.get("gps","null"))

    job=str(uuid.uuid4())
    path=os.path.join(UPLOAD_FOLDER,job+".jpg")
    file.save(path)

    img=Image.open(path).convert("RGB")

    bmeta,bgps=extract_exif(path)
    meta={**fmeta,**bmeta}
    gps=bgps if bgps else fgps

    ela,ela_img=ela_score(img,path)
    noise=noise_score(img)
    edge=edge_score(img)
    block=block_score(img)
    meta_score=metadata_score(meta)

    final,conf=combine({"ela":ela,"noise":noise,"edge":edge,"block":block,"meta":meta_score})

    s,t,l,c_note=explain(final)

    heatfile=f"{job}_heat.jpg"
    ela_img.save(os.path.join(UPLOAD_FOLDER,heatfile))

    result={
        "analysis":"Likely edited" if final>70 else "Possibly edited" if final>40 else "Likely original",
        "score":final,
        "confidence":conf,
        "simple_explanation":s,
        "technical_explanation":t,
        "legal_explanation":l,
        "confidence_note":c_note,
        "signals":{
            "ELA":int(ela),
            "Noise":int(noise),
            "Edges":int(edge),
            "Compression":int(block),
            "Metadata":int(meta_score)
        },
        "metadata":{"available":bool(meta),"all":meta},
        "gps":gps,
        "heatmap":f"{BASE_URL}/files/{heatfile}",
        "integrity":{"hash":generate_file_hash(path)}
    }

    result["pdf_report"]=generate_pdf(job,result)

    return jsonify({"result":result})

@app.route("/files/<f>")
def files(f):
    return send_from_directory(UPLOAD_FOLDER,f)
