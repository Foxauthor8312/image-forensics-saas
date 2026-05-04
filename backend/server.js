const express = require('express');
const multer = require('multer');
const cors = require('cors');
const exifr = require('exifr');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(cors());
app.use(express.json());

const upload = multer({ storage: multer.memoryStorage() });

// =========================
// HELPERS
// =========================

function calculateTampering(exif) {
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

// =========================
// ROUTES
// =========================

app.get('/', function(req, res) {
  res.send('Backend OK');
});

app.post('/analyze', upload.single('image'), async function(req, res) {
  try {
if (!req.file) {
  return res.status(400).json({ error: "No file uploaded" });
}

if (req.file.size > 5 * 1024 * 1024) {
  return res.status(400).json({ error: "File too large (5MB max)" });
}
    
    console.log("UPLOAD OK");

    const rawExif = await exifr.parse(req.file.buffer);

    console.log("EXIF PARSED");

    let exif = null;

    if (rawExif) {
      exif = {
        make: rawExif.Make || rawExif.make || "Unknown",
        model: rawExif.Model || rawExif.model || "Unknown",
        date: rawExif.DateTimeOriginal || rawExif.CreateDate || "Unknown",
        iso: rawExif.ISO || null,
        lens: rawExif.LensModel || null,
        gps: rawExif.latitude && rawExif.longitude
          ? { lat: rawExif.latitude, lon: rawExif.longitude }
          : null
      };
    }

    const tampering = calculateTampering(exif);
    const confidence = calculateConfidence(exif, tampering);

    res.json({
      success: true,
      size: req.file.size,
      exif: exif,
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

app.listen(PORT, function() {
  console.log("Running on port " + PORT);
});
