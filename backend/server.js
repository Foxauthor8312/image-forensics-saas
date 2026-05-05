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


// ---------- SIMPLE CLASSIFICATION ----------
function classifyImage(exif, elaScore) {
  if (exif && elaScore < 10) {
    return { type: "Likely Original", confidence: 0.9 };
  }

  if (exif && elaScore > 25) {
    return { type: "Recompressed", confidence: 0.8 };
  }

  if (!exif && elaScore > 25) {
    return { type: "Edited", confidence: 0.85 };
  }

  return { type: "Recompressed", confidence: 0.7 };
}


// ---------- ELA (WORKING + ALWAYS RETURNS OVERLAY) ----------
async function runELA(buffer) {
  try {
    const normalized = await sharp(buffer)
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
      const value = Math.abs(orig.data[i] - comp.data[i]) * 10; // amplify
diff[i] = Math.min(255, value);
    }

    const elaImage = await sharp(diff, {
      raw: {
        width: orig.info.width,
        height: orig.info.height,
        channels: orig.info.channels
      }
    })
      .jpeg({ quality: 60 }) // small + stable
      .toBuffer();

    return {
      score: Number((total / orig.data.length).toFixed(2)),
      overlay: `data:image/jpeg;base64,${elaImage.toString('base64')}`
    };

  } catch (err) {
    console.log("ELA ERROR:", err.message);
    return null;
  }
}


// ---------- ROUTES ----------
app.get('/', (req, res) => {
  res.send('Backend OK');
});

app.post('/analyze', upload.single('image'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    const rawExif = await exifr.parse(req.file.buffer);

    const ela = await runELA(req.file.buffer);

const exif = rawExif
  ? {
      make: rawExif.Make || "Unknown",
      model: rawExif.Model || "Unknown",
      date: rawExif.DateTimeOriginal || rawExif.CreateDate || "Unknown",

      iso: rawExif.ISO || null,
      lens: rawExif.LensModel || null,

      exposureTime: rawExif.ExposureTime || null,
      fNumber: rawExif.FNumber || null,
      focalLength: rawExif.FocalLength || null,

      gps: rawExif.latitude && rawExif.longitude
        ? {
            lat: rawExif.latitude,
            lon: rawExif.longitude
          }
        : null
    }
  : null;
    const classification = classifyImage(
      exif,
      ela ? ela.score : 0
    );

    res.json({
      success: true,
      exif,
      ela, // 🔥 THIS includes overlay
      classification
    });

  } catch (err) {
    console.log("ERROR:", err.message);
    res.status(500).json({ error: "Server error" });
  }
});


// ---------- START ----------
app.listen(PORT, () => {
  console.log("Running on port " + PORT);
});
