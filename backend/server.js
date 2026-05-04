const express = require('express');
const multer = require('multer');
const cors = require('cors');
const exifr = require('exifr');   // 👈 import

const app = express();
const PORT = process.env.PORT || 10000;

// =========================
// MIDDLEWARE
// =========================
app.use(cors());
app.use(express.json());

const upload = multer({ storage: multer.memoryStorage() });

// =========================
// 👇 PUT HELPER FUNCTION HERE
// =========================
async function extractExif(buffer) {
  try {
    return await exifr.parse(buffer);
  } catch {
    return null;
  }
}

// =========================
// ROUTES
// =========================
app.get('/', (req, res) => {
  res.send('OK');
});

app.post('/analyze', upload.single('image'), async (req, res) => {
  try {

    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    const rawExif = await extractExif(req.file.buffer);
    console.log("BUFFER SIZE:", req.file.buffer?.length);
    console.log("RAW EXIF FULL:", rawExif);

    const exif = rawExif
      ? {
          make: rawExif.Make || null,
          model: rawExif.Model || null,
          date: rawExif.DateTimeOriginal || null,
          hasGPS: !!(rawExif.latitude && rawExif.longitude)
        }
      : null;

    res.json({
      success: true,
      size: req.file.size,
      exif: exif || { present: false }
    });

  } catch (err) {
    console.log("ERROR:", err);
    res.status(500).json({ error: "Processing failed" });
  }
});

// =========================
// START SERVER
// =========================
app.listen(PORT, () => {
  console.log('Running on port ' + PORT);
});
