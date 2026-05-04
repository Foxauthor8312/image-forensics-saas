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

  // ELA influence
 if (ela && ela.score > 25) {
  if (exif) {
    reasons.push("Image shows heavy recompression (possible editing or platform processing)");
  } else {
    score += 0.3;
    reasons.push("High compression inconsistency with no metadata");
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

function calculateConfidence(exif, tampering) {
  let score = 0.5;

  if (exif) {
    score += 0.2;
    if (exif.make && exif.model) score += 0.1;
    if (exif.date && exif.date !== "Unknown") score += 0.1;
    if (exif.gps) score += 0.05;
  }

  if (tampering && tampering.likelihood) {
    score -= tampering.likelihood * 0.4;
  }

  return Math.max(0, Math.min(1, Number(score.toFixed(2))));
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

    const score = total / orig.data.length;

    return {
      score: Number(score.toFixed(2)),
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

    console.log("UPLOAD RECEIVED");

    // 1. Extract EXIF FIRST (preserves metadata)
    const exifRaw = await exifr.parse(req.file.buffer);

    // 2. Prepare working buffer
    let buffer = req.file.buffer;

    // Resize ONLY if very large (performance safe)
    if (req.file.size > 8 * 1024 * 1024) {
      console.log("Resizing large image...");
      try {
        buffer = await sharp(req.file.buffer)
          .resize({ width: 1600, withoutEnlargement: true })
          .jpeg({ quality: 80 })
          .toBuffer();
      } catch (err) {
        console.log("Resize failed:", err.message);
      }
    }

    // 3. Run ELA
    const ela = await runELA(buffer);

    // 4. Build EXIF object
    let exif = null;
    if (exifRaw) {
      exif = {
        make: exifRaw.Make || exifRaw.make || "Unknown",
        model: exifRaw.Model || exifRaw.model || "Unknown",
        date: exifRaw.DateTimeOriginal || exifRaw.CreateDate || "Unknown",
        iso: exifRaw.ISO || null,
        lens: exifRaw.LensModel || null,
        gps: exifRaw.latitude && exifRaw.longitude
          ? { lat: exifRaw.latitude, lon: exifRaw.longitude }
          : null
      };
    }

    // 5. Scoring
    const tampering = calculateTampering(exif, ela);
    const confidence = calculateConfidence(exif, tampering);

    res.json({
      success: true,
      size: req.file.size,
      exif,
      ela,
      tampering,
      confidence
    });

  } catch (err) {
    console.log("ERROR:", err.message);
    res.status(500).json({ error: "Server error" });
  }
});

// =========================
// START SERVER
// =========================

app.listen(PORT, () => {
  console.log(`Running on port ${PORT}`);
});
