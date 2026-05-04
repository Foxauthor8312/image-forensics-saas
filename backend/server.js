const express = require('express');
const multer = require('multer');
const exifr = require('exifr');
const sharp = require('sharp');

const app = express();
const PORT = process.env.PORT || 10000;

// =========================
// MIDDLEWARE
// =========================
app.use(express.json());

app.use((req, res, next) => {
  console.log(`[REQ] ${req.method} ${req.url}`);
  next();
});

const upload = multer({ storage: multer.memoryStorage() });

// =========================
// VERSION
// =========================
app.get('/version', (req, res) => {
  res.json({
    version: "v1.2.0",
    status: "forensics-ready",
    time: new Date().toISOString()
  });
});

// =========================
// HEALTH
// =========================
app.get('/', (req, res) => {
  res.send("PixelProof backend v1.2.0");
});

// =========================
// EXIF CLEANER
// =========================
function cleanExif(exif) {
  if (!exif) return null;

  return {
    camera: {
      make: exif.Make || null,
      model: exif.Model || null
    },
    capture: {
      date: exif.DateTimeOriginal || null,
      modified: exif.ModifyDate || null
    },
    image: {
      width: exif.ExifImageWidth || null,
      height: exif.ExifImageHeight || null
    },
    gps: exif.latitude && exif.longitude
      ? {
          lat: exif.latitude,
          lon: exif.longitude
        }
      : null
  };
}

// =========================
// EXIF EXTRACTION
// =========================
async function extractExif(buffer) {
  try {
    return await exifr.parse(buffer);
  } catch (err) {
    console.log("EXIF error:", err.message);
    return null;
  }
}

// =========================
// CONFIDENCE SCORE
// =========================
function calculateConfidence(exif) {
  if (!exif) return 0.3;

  let score = 0.5;
  if (exif.Make) score += 0.1;
  if (exif.Model) score += 0.1;
  if (exif.DateTimeOriginal) score += 0.1;
  if (exif.latitude && exif.longitude) score += 0.1;

  return Math.min(score, 0.9);
}

// =========================
// ELA PROCESSING
// =========================
async function runELA(buffer) {
  try {
    // Normalize to JPEG
    const normalized = await sharp(buffer).jpeg().toBuffer();

    const recompressed = await sharp(normalized)
      .jpeg({ quality: 60 })
      .toBuffer();

    const originalRaw = await sharp(normalized)
      .raw()
      .toBuffer({ resolveWithObject: true });

    const recompressedRaw = await sharp(recompressed)
      .raw()
      .toBuffer({ resolveWithObject: true });

    const { data: origData, info } = originalRaw;
    const { data: compData } = recompressedRaw;

    const diff = Buffer.alloc(origData.length);
    let totalDiff = 0;

    for (let i = 0; i < origData.length; i++) {
      const value = Math.abs(origData[i] - compData[i]) * 10;
      diff[i] = value;
      totalDiff += value;
    }

    const elaImage = await sharp(diff, {
      raw: {
        width: info.width,
        height: info.height,
        channels: info.channels
      }
    }).png().toBuffer();

    const avgDiff = totalDiff / origData.length;

    const overlay = await sharp(normalized)
  .composite([
    {
      input: elaImage,
      blend: 'overlay',
      opacity: 0.6
    }
  ])
  .png()
  .toBuffer();

return {
  heatmap: `data:image/png;base64,${elaImage.toString('base64')}`,
  overlay: `data:image/png;base64,${overlay.toString('base64')}`,
  score: Number(avgDiff.toFixed(2))
};

  } catch (err) {
    console.error("ELA error:", err);
    return null;
  }
}

// =========================
// ELA NORMALIZATION
// =========================
function normalizeELAScore(score) {
  const min = 0;
  const max = 25;
  const normalized = (score - min) / (max - min);
  return Math.max(0, Math.min(1, normalized));
}

// =========================
// TAMPERING EVALUATION
// =========================
function evaluateTampering({ elaScore, exif }) {
  const reasons = [];

  const elaNorm = normalizeELAScore(elaScore);
  let likelihood = elaNorm * 0.7;

  if (!exif) {
    likelihood += 0.2;
    reasons.push("Missing EXIF metadata");
  }

  if (exif && !exif.DateTimeOriginal) {
    likelihood += 0.1;
    reasons.push("No original capture timestamp");
  }

  likelihood = Math.max(0, Math.min(1, likelihood));

  let label = "Likely Original";
  if (likelihood > 0.75) label = "Highly Suspicious";
  else if (likelihood > 0.5) label = "Moderate Anomalies";
  else if (likelihood > 0.3) label = "Minor Inconsistencies";

  if (elaNorm > 0.6) reasons.push("Elevated ELA response");
  else if (elaNorm > 0.3) reasons.push("Moderate compression inconsistencies");

  return {
    likelihood: Number(likelihood.toFixed(2)),
    label,
    reasons
  };
}

// =========================
// ANALYZE ROUTE
// =========================
app.post('/analyze', upload.single('image'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    // File size protection
    if (req.file.size > 10 * 1024 * 1024) {
      return res.status(400).json({
        error: "Image too large",
        maxSizeMB: 10
      });
    }

    console.log("File:", req.file.mimetype, req.file.size);

    const rawExif = await extractExif(req.file.buffer);
    const cleanedExif = cleanExif(rawExif);

    const exifResult = cleanedExif
      ? { present: true, data: cleanedExif }
      : { present: false, message: "No metadata (common for mobile uploads)" };

    const confidence = calculateConfidence(rawExif);

    // ELA
    const elaData = await runELA(req.file.buffer);

    let elaResult;
    if (!elaData) {
      elaResult = { status: "failed" };
    } else {
    elaResult = {
  status: "complete",
  score: elaData.score,
  level: getELALevel(elaData.score),
  heatmap: elaData.heatmap,
  overlay: elaData.overlay
};
    }

    // Tampering
    let tampering = {
      likelihood: 0,
      label: "Unknown",
      reasons: []
    };

    if (elaData) {
      tampering = evaluateTampering({
        elaScore: elaData.score,
        exif: rawExif
      });
    }

    res.json({
      success: true,
      timestamp: new Date().toISOString(),
      confidence,
      exif: exifResult,
      ela: elaResult,
      tampering
    });

  } catch (err) {
    console.error("Processing error:", err);
    res.status(500).json({ error: "Processing failed" });
  }
});

// =========================
// START SERVER
// =========================
app.listen(PORT, () => {
  console.log("=== SERVER STARTED ===");
  console.log(`Running on port ${PORT}`);
});
