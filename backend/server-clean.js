const express = require('express');
const multer = require('multer');
const sharp = require('sharp');
const cors = require('cors');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(cors());
app.use(express.json());

const upload = multer({ storage: multer.memoryStorage() });

app.get('/', (req, res) => {
res.send('OK');
});

app.post('/analyze', upload.single('image'), async (req, res) => {
try {

```
if (!req.file) {
  return res.status(400).json({ error: "No file" });
}

const resized = await sharp(req.file.buffer)
  .resize({ width: 500 })
  .jpeg()
  .toBuffer();

const recompressed = await sharp(resized)
  .jpeg({ quality: 60 })
  .toBuffer();

const orig = await sharp(resized).raw().toBuffer({ resolveWithObject: true });
const comp = await sharp(recompressed).raw().toBuffer({ resolveWithObject: true });

let total = 0;

for (let i = 0; i < orig.data.length; i++) {
  total += Math.abs(orig.data[i] - comp.data[i]);
}

const score = total / orig.data.length;

res.json({
  success: true,
  score: score
});
```

} catch (err) {
console.log("ERROR:", err);
res.status(500).json({ error: "Crash" });
}
});

app.listen(PORT, () => {
console.log("Running on port " + PORT);
});
