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
console.log("UPLOAD OK");

const rawExif = await exifr.parse(req.file.buffer);

console.log("EXIF PARSED");

res.json({
  success: true,
  size: req.file.size,
  hasExif: rawExif ? true : false
});


} catch (err) {
console.log("ERROR:", err.message);
res.status(500).json({ error: "Server error" });
}
});

