const express = require('express');
const multer = require('multer');
const cors = require('cors');
const exifr = require('exifr');
const sharp = require('sharp');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(cors());
app.use(express.json());

const upload = multer({ storage: multer.memoryStorage() });

// =========================
// HELPERS
// =========================

function calculateTampering(exif, ela) {
  let score = 0.3;
  const reasons = [];

  if (!exif) {
    score += 0.4;
    reasons.push("No metadata present");
  } else {
    if (!exif.make || !exif.model) {
      score += 0.2;
      reasons.push("Missing camera information");
    }

    if (!exif.date || exif.date === "Unknown") {
      score += 0.2;
      reasons.push("Missing capture date");
    }

    if (exif.gps) {
      reasons.push("Original capture likely (GPS present)");
    } else {
      reasons.push("No location data (common for edited/shared images)");
    }
  }

  if (ela && typeof ela.score === "number") {
    if (ela.score > 25) {
      score += 0.3;
      reasons.push("High compression inconsistency detected");
    }
  }

  score = Math.min(score, 1);

  let label = "Likely Original";
  if (score > 0.75) label = "Highly Suspicious";
  else if (score > 0.5) label = "Moderate Anomalies";
  else if (score > 0.3) label = "Minor Inconsistencies";

  return {
    likelihood: Number(score.toFixed(2)),
    label,
    reasons
  };
}

function calculateConfidence(exif, tampering, ela) {
  let score = 0.5;

  if (exif) {
    score += 0.2;
    if (exif.make && exif.model) score += 0.1;
    if (exif.date && exif.date !== "Unknown") score += 0.1;
    if (exif.gps) score += 0.05;
  }

  if (tampering && tampering.likelihood) {
    score -= tampering.likelihood * 0.5;
  }

  if (ela && typeof ela.score === "number") {
    if (ela.score > 30) score -= 0.4;
    else if (ela.score > 20) score -= 0.3;
    else if (ela.score > 10) score -= 0.15;
  }

  return Math.max(0, Math.min(1, Number(score.toFixed(2))));
}

function classifyImage(exif, ela, tampering) {
  const elaScore = ela && ela.score ? ela.score : 0;

  if (exif && elaScore > 25 && tampering.likelihood < 0.6) {
    return {
      type: "Recompressed",
      reason: "High compression artifacts with intact metadata",
      confidence: 0.8
    };
  }

  if ((!exif && elaScore > 20) || tampering.likelihood > 0.7) {
    return {
      type: "Edited",
      reason: "Missing metadata or strong anomaly signals",
      confidence: 0.85
    };
  }

  if (exif && elaScore < 10) {
    return {
      type: "Likely Original",
      reason: "Low compression artifacts with intact metadata",
      confidence: 0.9
    };
  }

  return {
    type: "Possibly Modified",
    reason: "Moderate compression differences detected",
    confidence: 0.6
  };
}

async function runELA(buffer) {
  try {
    const normalized = await sharp(buffer)
      .rotate()
      .resize({ width: 800, withoutEnlargement: true })
      .jpeg()
      .toBuffer();

    const recompressed = await sharp(normalized)
      .jpeg({ quality: 60 })
      .toBuffer();

    const orig = await sharp(normalized)
      .raw()
      .toBuffer({ resolveWithObject: true });

    const comp = await sharp(recompressed)
      .raw()
      .toBuffer({ resolveWithObject: true });

    const diff = Buffer.alloc(orig.data.length);
    let total = 0;

    for (let i = 0; i < orig.data.length; i++) {
      const value = Math.min(255, Math.abs(orig.data[i] - comp.data[i]) * 10);
      diff[i] = value;
      total += value;
    }

    const elaImage = await sharp(diff, {
      raw: {
        width: orig.info.width,
        height: orig.info.height,
        channels: orig.info.channels
      }
    }).png().toBuffer();

    const overlay = await sharp(normalized)
      .composite([{ input: elaImage, blend: 'overlay', opacity: 0.6 }])
      .png()
      .toBuffer();

    return {
      score: Number((total / orig.data.length).toFixed(2)),
      overlay: `data:image/png;base64,${overlay.toString('base64')}`
    };

  } catch (err) {
    console.log("ELA ERROR:", err.message);
    return null;
  }
}

// =========================
// ROUTES
// =========================

app.get('/', (req, res) => {
  res.send('Backend OK');
});

app.post('/analyze', upload.single('image'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    const exifRaw = await exifr.parse(req.file.buffer);

    let buffer = req.file.buffer;

    if (req.file.size > 8 * 1024 * 1024) {
      buffer = await sharp(req.file.buffer)
        .resize({ width: 1600, withoutEnlargement: true })
        .jpeg({ quality: 80 })
        .toBuffer();
    }

    const ela = await runELA(buffer);

    let exif = null;
    if (exifRaw) {
      exif = {
        make: exifRaw.Make || "Unknown",
        model: exifRaw.Model || "Unknown",
        date: exifRaw.DateTimeOriginal || exifRaw.CreateDate || "Unknown",
        iso: exifRaw.ISO || null,
        gps: exifRaw.latitude && exifRaw.longitude
          ? { lat: exifRaw.latitude, lon: exifRaw.longitude }
          : null
      };
    }

    const tampering = calculateTampering(exif, ela);
    const confidence = calculateConfidence(exif, tampering, ela);
    const classification = classifyImage(exif, ela, tampering);

    res.json({
      success: true,
      size: req.file.size,
      exif,
      ela,
      tampering,
      confidence,
      classification
    });

  } catch (err) {
    console.log("ERROR:", err.message);
    res.status(500).json({ error: "Server error" });
  }
});

app.listen(PORT, () => {
  console.log(`Running on port ${PORT}`);
});
