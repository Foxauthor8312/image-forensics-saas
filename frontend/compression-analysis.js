export async function analyzeCompression(file) {

    const arrayBuffer = await file.arrayBuffer();
    const data = new Uint8Array(arrayBuffer);

    const result = {
        quantizationTables: []
    };

    let offset = 0;

    while (offset < data.length) {

        // JPEG markers begin with 0xFF
        if (data[offset] === 0xFF) {

            const marker = data[offset + 1];

            // DQT = Define Quantization Table
            if (marker === 0xDB) {

                const segmentLength =
                    (data[offset + 2] << 8) |
                    data[offset + 3];

                let qOffset = offset + 4;
                const end = offset + 2 + segmentLength;

                while (qOffset < end) {

                    const tableInfo = data[qOffset];
                    const tableId = tableInfo & 0x0F;

                    qOffset++;

                    const values = [];

                    for (let i = 0; i < 64; i++) {
                        values.push(data[qOffset]);
                        qOffset++;
                    }

                    result.quantizationTables.push({
                        tableId,
                        values
                    });
                }
            }
        }

        offset++;
    }

    console.log("Compression Analysis:", result);

    return result;
}
