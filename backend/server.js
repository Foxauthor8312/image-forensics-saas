const express = require("express");
const cors = require("cors");
const multer = require("multer");
const sharp = require("sharp");
const fs = require("fs");
const path = require("path");

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json({ limit: "5mb" }));

// ensure heatmaps dir exists
const HEATMAP_DIR = path.join(__dirname, "heatmaps");
if (!fs.existsSync(HEATMAP_DIR)) fs.mkdirSync(HEATMAP_DIR);

// serve heatmaps
app.use("/heatmaps", express.static(HEATMAP_DIR));

// multer (in-memory to avoid disk I/O issues)
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 5 * 1024 * 1024 } // 5MB
});

// health
app.get("/", (req, res) => {
  res.send("PixelProof backend is running");
});

// ---- helpers ----

// Compute simple ELA diff and return a heatmap buffer + score (0–100)
async function computeELA(buffer) {
  // Normalize to JPEG
  const base = await sharp(buffer)
    .rotate()
    .resize({ width: 800, withoutEnlargement: true })
    .jpeg({ quality: 90 })
    .toBuffer();

  // Recompress
  const recompressed = await sharp(base)
    .jpeg({ quality: 70 })
    .toBuffer();

  // Get raw pixels
  const a = await sharp(base).raw().toBuffer({ resolveWithObject: true });
  const b = await sharp(recompressed).raw().toBuffer({ resolveWithObject: true });

  const { data: da, info } = a;
  const { data: db } = b;

  const w = info.width;
  const h = info.height;
  const channels = info.channels; // likely 3

  // Diff image (grayscale intensity of difference)
  const diff = Buffer.alloc(w * h);

  let sum = 0;
  let maxv = 0;

  for (let i = 0, j = 0; i < da.length; i += channels, j++) {
    // average channel diff
    const d =
      Math.abs(da[i] - db[i]) +
      Math.abs(da[i + 1] - db[i + 1]) +
      Math.abs(da[i + 2] - db[i + 2]);

    const v = Math.min(255, Math.round(d / 3) * 3); // amplify a bit
    diff[j] = v;

    sum += v;
    if (v > maxv) maxv = v;
  }

  // Normalize to 0–255 for visibility
  const scale = maxv ? 255 / maxv : 1;
  for (let i = 0; i < diff.length; i++) {
    diff[i] = Math.min(255, Math.round(diff[i] * scale));
  }

  // Build a heatmap (pseudo color: red intensity)
  const heatRGB = Buffer.alloc(w * h * 3);
  for (let i = 0, j = 0; i < diff.length; i++, j += 3) {
    const v = diff[i];
    heatRGB[j] = v;        // R
    heatRGB[j + 1] = 0;    // G
    heatRGB[j + 2] = 0;    // B
  }

  const heatPng = await sharp(heatRGB, {
    raw: { width: w, height: h, channels: 3 }
  })
    .png()
    .toBuffer();

  // ELA score: mean intensity mapped to 0–100
  const mean = sum / diff.length;
  const elaScore = Math.max(0, Math.min(100, Math.round((mean / 255) * 100)));

  return { heatPng, elaScore, width: w, height: h };
}

// Simple “noise” proxy: variance of luminance
async function computeNoiseScore(buffer) {
  const { data, info } = await sharp(buffer)
    .resize({ width: 800, withoutEnlargement: true })
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });

  let mean = 0;
  for (let i = 0; i < data.length; i++) mean += data[i];
  mean /= data.length;

  let variance = 0;
  for (let i = 0; i < data.length; i++) {
    const d = data[i] - mean;
    variance += d * d;
  }
  variance /= data.length;

  // map variance to 0–100 (empirical scaling)
  const noise = Math.max(0, Math.min(100, Math.round(variance / 50)));
  return noise;
}

// Metadata flags (very simple heuristic)
function metadataScore(meta) {
  if (!meta) return 10;
  let score = 0;

  if (meta.Software && /photoshop|gimp|editor/i.test(meta.Software)) score += 40;
  if (!meta.Make || !meta.Model) score += 15;
  if (!meta.DateTimeOriginal) score += 10;

  return Math.max(0, Math.min(100, score));
}

// Combine signals into overall score
function combineScore({ ela, noise, metadata }) {
  const w = { ela: 0.5, noise: 0.25, metadata: 0.25 };
  const total = ela * w.ela + noise * w.noise + metadata * w.metadata;
  return Math.round(total);
}

function verdict(score) {
  if (score > 70) return "Likely Altered";
  if (score > 40) return "Possibly Modified";
  return "Likely Authentic";
}

// ---- route ----

app.post("/api/analyze", upload.single("image"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No image uploaded" });
    }

    const buffer = req.file.buffer;

    // parse optional metadata/gps from client
    let clientMeta = {};
    let clientGPS = null;
    try {
      clientMeta = JSON.parse(req.body.metadata || "{}");
      clientGPS = JSON.parse(req.body.gps || "null");
    } catch {}

    // --- analysis ---
    const { heatPng, elaScore } = await computeELA(buffer);
    const noise = await computeNoiseScore(buffer);
    const metaScore = metadataScore(clientMeta);

    const score = combineScore({
      ela: elaScore,
      noise,
      metadata: metaScore
    });

    const id = Date.now().toString(36);
    const heatPath = `/heatmaps/${id}.png`;
    fs.writeFileSync(path.join(HEATMAP_DIR, `${id}.png`), heatPng);

    const result = {
      analysis: verdict(score),
      score,
      confidence: Math.max(60, Math.min(95, 60 + Math.round((elaScore + noise) / 4))),

      signals: {
        ela: elaScore,
        noise,
        lighting: Math.max(0, Math.min(100, Math.round((elaScore + noise) / 2))), // placeholder
        edges: Math.max(0, Math.min(100, Math.round(noise * 0.8))),               // placeholder
        metadata: metaScore
      },

      technical_explanation:
        "ELA highlights recompression differences. Elevated regions can indicate localized edits. Noise variance reflects sensor consistency; mismatches can suggest compositing.",

      legal_explanation:
        "Results are indicative and should be corroborated with certified forensic methods for evidentiary use.",

      metadata: clientMeta || {},
      gps: clientGPS || null,
      heatmap: heatPath
    };

    res.json({ result });

  } catch (err) {
    console.error("ANALYZE ERROR:", err);
    res.status(500).json({ error: "Analysis failed" });
  }
});

app.listen(PORT, () => {
  console.log("Server running on port", PORT);
});
