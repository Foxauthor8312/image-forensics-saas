document
  .getElementById("downloadPdfBtn")
  .addEventListener("click", generatePdfReport);

async function generatePdfReport(){

  const { jsPDF } = window.jspdf;

  const report =
    document.getElementById("pdfReport");

  const canvas = await html2canvas(report, {
    scale: 2,
    useCORS: true
  });

  const imgData =
    canvas.toDataURL("image/jpeg", 1.0);

  const pdf = new jsPDF(
    "p",
    "mm",
    "a4"
  );

  const pageWidth = 210;
  const margin = 10;

  const usableWidth =
    pageWidth - (margin * 2);

  const imgHeight =
    canvas.height * usableWidth / canvas.width;

  pdf.addImage(
    imgData,
    "JPEG",
    margin,
    margin,
    usableWidth,
    imgHeight
  );

  pdf.save("PixelProof_Report.pdf");
}
