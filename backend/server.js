const express = require('express');
const multer = require('multer');
const cors = require('cors');
const exifr = require('exifr');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(cors());
app.use(express.json());

const upload = multer({ storage: multer.memoryStorage() });

async function extractExif(buffer) {
try {
return await exifr.parse(buffer);
} catch {
return null;
}
}

app.get('/', (req, res) => {
res.send('Backend OK');
});

app.post('/analyze', upload.single('image'), async (req, res) => {
try {
if (!req.file) {
return res.status(400).json({ error: "No file uploaded" });
}

```
const rawExif = await extractExif(req.file.buffer);

console.log("RAW EXIF:", rawExif);

const exif = rawExif
  ? {
      make: rawExif.Make || rawExif.make || null,
      model: rawExif.Model || rawExif.model || null,
      date: rawExif.DateTimeOriginal || rawExif.CreateDate || null,
      hasGPS: !!(rawExif.latitude && rawExif.longitude)
    }
  : null;

res.json({
  success: true,
  size: req.file.size,
  exif: exif || { present: false }
});
```

} catch (err) {
console.log("ERROR:", err);
res.status(500).json({ error: "Server error" });
}
});

app.listen(PORT, () => {
console.log("Running on port " + PORT);
});
