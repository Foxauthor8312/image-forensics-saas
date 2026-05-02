const express = require("express");
const cors = require("cors");
const multer = require("multer");
const exifr = require("exifr");
const sharp = require("sharp");

const app = express();
const upload = multer({ storage: multer.memoryStorage() });

app.use(cors({
  origin: "*"
}));

// ROOT TEST
app.get("/", (req, res) => {
  res.send("PixelProof backend running");
});

// 🧠 REAL ELA ANALYSIS
app.post("/api/analyze", upload.single("image"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No image uploaded" });
    }

    const original = req.file.buffer;

    // STEP 1: recompress
    const recompressed = await sharp(original)
      .jpeg({ quality: 70 })
      .toBuffer();

    // STEP 2: raw pixel data
    const origRaw = await sharp(original).raw().toBuffer({ resolveWithObject: true });
    const recomRaw = await sharp(recompressed).raw().toBuffer({ resolveWithObject: true });

    const oData = origRaw.data;
    const rData = recomRaw.data;

    let diffSum = 0;

    // STEP 3: pixel difference
    for (let i = 0; i < oData.length; i++) {
      diffSum += Math.abs(oData[i] - rData[i]);
    }

    const avgDiff = diffSum / oData.length;

    // STEP 4: normalize score
    const elaScore = Math.min(100, Math.round(avgDiff * 2));

    // 🧠 METADATA
   let metadata = {};

try {
  const exifData = await exifr.parse(original, {
  gps: true,
  exif: true,
  tiff: true,
  ifd0: true
});

  metadata = {
    camera: exifData?.Make || "Unknown",
    model: exifData?.Model || "Unknown",
    software: exifData?.Software || "Unknown",
    date: exifData?.DateTimeOriginal || null,
    gps: (exifData?.latitude && exifData?.longitude)
      ? {
          lat: exifData.latitude,
          lon: exifData.longitude
        }
      : null
  };

} catch (e) {
  console.log("EXIF parse failed:", e.message);
}

    // 🧠 SIGNALS
    const signals = {
      ela: elaScore,
      noise: Math.max(20, Math.min(80, elaScore - 10)),
      metadata: metadata.gps ? 20 : 5
    };

    const score = Math.round(
      signals.ela * 0.5 +
      signals.noise * 0.25 +
      signals.metadata * 0.25
    );

    // 🧠 EXPLANATION
    let analysis = "";

    if (elaScore > 70) {
      analysis = "High compression inconsistencies detected across the image.";
    } else if (elaScore > 40) {
      analysis = "Moderate compression variation observed.";
    } else {
      analysis = "Compression appears consistent across the image.";
    }

    const conclusion =
      score > 70
        ? "Strong evidence of alteration"
        : score > 40
        ? "Possible modification detected"
        : "Likely authentic image";

    const response = {
      score,
      signals,
      metadata,
      heatmap: null,
      analysis,
      conclusion
    };

    res.json({ result: response });

  } catch (err) {
    console.error("ELA ERROR:", err);
    res.status(500).json({ error: "ELA analysis failed" });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log("Server running on", PORT));
