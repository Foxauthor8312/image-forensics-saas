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
} catch (e) {
console.log("EXIF error:", e.message);
return null;
}
}

app.get('/', function(req, res) {
res.send('Backend OK');
});

app.post('/analyze', upload.single('image'), async function(req, res) {
try {
if (!req.file) {
return res.status(400).json({ error: "No file uploaded" });
}

```
console.log("BUFFER SIZE:", req.file.buffer ? req.file.buffer.length : 0);

const rawExif = await extractExif(req.file.buffer);

console.log("RAW EXIF:", rawExif);

let exif = null;

if (rawExif) {
  exif = {
    make: rawExif.Make || rawExif.make || null,
    model: rawExif.Model || rawExif.model || null,
    date: rawExif.DateTimeOriginal || rawExif.CreateDate || null,
    hasGPS: rawExif.latitude && rawExif.longitude ? true : false
  };
}

res.json({
  success: true,
  size: req.file.size,
  exif: exif ? exif : { present: false }
});
```

} catch (err) {
console.log("SERVER ERROR:", err.message);
res.status(500).json({ error: "Server error" });
}
});

app.listen(PORT, function() {
console.log("Running on port " + PORT);
});
