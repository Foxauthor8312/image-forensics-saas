const express = require('express');
const multer = require('multer');
const exifr = require('exifr');
const sharp = require('sharp');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(cors({ origin: "*" }));
app.use(express.json());

app.use((req, res, next) => {
console.log("[REQ] " + req.method + " " + req.url);
next();
});

const upload = multer({ storage: multer.memoryStorage() });

app.get('/', (req, res) => {
res.send("Backend running");
});

async function extractExif(buffer) {
try {
return await exifr.parse(buffer);
} catch {
return null;
}
}

async function runELA(buffer) {
try {
const resized = await sharp(buffer)
.resize({ width: 800, withoutEnlargement: true })
.jpeg()
.toBuffer();

```
const recompressed = await sharp(resized)
  .jpeg({ quality: 60 })
  .toBuffer();

const orig = await sharp(resized).raw().toBuffer({ resolveWithObject: true });
const comp = await sharp(recompressed).raw().toBuffer({ resolveWithObject: true });

if (!orig.data || !comp.data) return null;

let total = 0;
for (let i = 0; i < orig.data.length; i++) {
  total += Math.abs(orig.data[i] - comp.data[i]);
}

const score = total / orig.data.length;

return { score: Number(score.toFixed(2)) };
```

} catch {
return null;
}
}

app.post('/analyze', upload.single('image'), async (req, res) => {
try {

```
if (!req.file) {
  return res.status(400).json({ error: "No file uploaded" });
}

const rawExif = await extractExif(req.file.buffer);
const ela = await runELA(req.file.buffer);

let likelihood = 0.3;
if (!rawExif) likelihood += 0.2;
if (ela && ela.score > 10) likelihood += 0.3;

res.json({
  success: true,
  ela: ela || { status: "skipped" },
  tampering: {
    likelihood: likelihood,
    label: likelihood > 0.6 ? "Suspicious" : "Likely Original"
  }
});
```

} catch (err) {
console.log("ERROR:", err);
res.status(500).json({ error: "Server crash" });
}
});

app.listen(PORT, () => {
console.log("Server running on port " + PORT);
});
