<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PixelProof</title>
<style>
body { font-family:sans-serif; background:#111; color:#fff; text-align:center; padding:20px }
img { max-width:100%; margin-top:20px; border:2px solid #444 }
</style>
</head>
<body>

<h2>PixelProof</h2>

<input type="file" id="file">

<h3 id="result"></h3>

<img id="elaImage">

<script>
const API = "https://image-forensics-saas-1.onrender.com";

document.getElementById("file").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const form = new FormData();
  form.append("image", file);

  const res = await fetch(API + "/analyze", {
    method: "POST",
    body: form
  });

  const data = await res.json();

  document.getElementById("result").innerText =
    "Result: " + data.classification.type +
    " (" + data.classification.confidence + ")";

  if (data.ela && data.ela.overlay) {
    document.getElementById("elaImage").src = data.ela.overlay;
  }
};
</script>

</body>
</html>
