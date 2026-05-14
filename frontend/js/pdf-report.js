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
