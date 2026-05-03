const express = require('express');
const multer = require('multer');
const exifr = require('exifr');

const app = express();

// =========================
// CONFIG
// =========================
const PORT = process.env.PORT || 10000;

// =========================
// MIDDLEWARE
// =========================
app.use(express.json());

// Request logger (VERY useful)
app.use((req, res, next) => {
  console.log(`[REQ] ${req.method} ${req.url}`);
  next();
});

// Multer setup (memory storage)
const upload = multer({ storage: multer.memoryStorage() });

// =========================
// VERSION CHECK (DEPLOY TEST)
// =========================
app.get('/version', (req, res) => {
  res.json({
    version: "v1.0.5",
    status: "stable",
    time: new Date().toISOString()
  });
});

// =========================
// EXIF EXTRACTION FUNCTION
// =========================
async function extractExif(buffer) {
  try {
    const data = await exifr.parse(buffer);
    return data;
  } catch (err) {
    console.log("EXIF error:", err.message);
    return null;
  }
}

// =========================
// MAIN IMAGE ANALYSIS ROUTE
// =========================
app.post('/analyze', upload.single('image'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "No file uploaded" });
    }

    console.log("File received:", req.file.mimetype, req.file.size);

    // EXIF
    const exif = await extractExif(req.file.buffer);

    let exifResult;
    if (!exif) {
  exifResult = {
    present: false,
    message: "No metadata (likely stripped by device or app)"
  };
} else {
  exifResult = {
    present: true,
    tags: exif
  };
}

    // =========================
    // ELA PLACEHOLDER
    // =========================
    // Replace this with your actual ELA logic
    const elaResult = {
      status: "processed",
      note: "ELA placeholder (replace with real implementation)"
    };

    // =========================
    // RESPONSE
    // =========================
    res.json({
      success: true,
      exif: exifResult,
      ela: elaResult
    });

  } catch (err) {
    console.error("Processing error:", err);
    res.status(500).json({ error: "Server error processing image" });
  }
});

// =========================
// HEALTH CHECK (OPTIONAL)
// =========================
app.get('/', (req, res) => {
  res.send("Backend is running");
});

// =========================
// START SERVER
// =========================
app.listen(PORT, () => {
  console.log("=== SERVER STARTED ===");
  console.log(`Server running on port ${PORT}`);
});
