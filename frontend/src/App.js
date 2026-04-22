const upload = async () => {
  if (!file) {
    alert("Please select a file first");
    return;
  }

  const formData = new FormData();
  formData.append("image", file);

  try {
    const res = await axios.post(
      "https://pixelproof-backend.onrender.com/api/analyze",
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      }
    );

    setResult(res.data);
  } catch (err) {
    console.error(err);
    alert("Upload failed");
  }
};