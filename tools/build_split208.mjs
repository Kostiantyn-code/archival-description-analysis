// XLSX authoring stage. Requires @oai/artifact-tool in the Node environment.
// Usage: node build_split208.mjs /absolute/path/to/prepared-data [--preview]
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const directory = path.resolve(process.argv[2]);
const rows = JSON.parse(await fs.readFile(path.join(directory, 'split208_matrix.json'), 'utf8'));
const workbook = Workbook.create();
const sheet = workbook.worksheets.add('MNO Split');
sheet.showGridLines = false;
sheet.getRange(`A1:L${rows.length}`).values = rows;
sheet.getRange(`A1:L${rows.length}`).format.font = { name: 'Arial', size: 10, color: '#172F43' };
sheet.getRange(`A1:E${rows.length}`).setNumberFormat('@');
sheet.getRange(`G5:L${rows.length}`).setNumberFormat('@');
sheet.getRange(`F5:F${rows.length}`).setNumberFormat('0');
sheet.getRange(`A5:L${rows.length}`).format.rowHeight = 36;
sheet.getRange(`A5:L${rows.length}`).format.verticalAlignment = 'top';
sheet.getRange(`B5:C${rows.length}`).format.wrapText = true;
sheet.getRange(`E5:E${rows.length}`).format.wrapText = true;
sheet.getRange('A1:A3').format.font.bold = true;
sheet.getRange('A4:L4').format = { fill: '#26465F', font: { name: 'Arial', size: 10, color: '#FFFFFF', bold: true }, wrapText: true, rowHeight: 32 };
const widths = [43, 77, 20, 4, 92, 12, 20, 24, 34, 20, 18, 15];
for (let i = 0; i < widths.length; i++) sheet.getRange(`${String.fromCharCode(65 + i)}1:${String.fromCharCode(65 + i)}${rows.length}`).format.columnWidth = widths[i];
sheet.freezePanes.freezeRows(4);
sheet.freezePanes.freezeColumns(1);
// The parser uses an empty D4 to indicate that folio counts are unavailable.
sheet.getRange('D4').values = [[null]];
workbook.recalculate();
const sample = await workbook.inspect({kind: 'table', range: 'MNO Split!A1:C8', include: 'values,formulas', tableMaxRows: 8, tableMaxCols: 3, maxChars: 2000});
console.log(sample.ndjson);
const errors = await workbook.inspect({kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#SPILL!|#CALC!', options: {useRegex: true, maxResults: 10}, maxChars: 1000});
console.log(errors.ndjson);
if (process.argv.includes('--preview')) {
  const image = await workbook.render({sheetName: 'MNO Split', range: 'A4:C10', scale: 1.4, format: 'png'});
  await fs.writeFile(path.join(directory, 'split208_preview.png'), new Uint8Array(await image.arrayBuffer()));
}
const output = path.join(directory, 'HR-DAST-208_MNO-Split_input.xlsx');
await (await SpreadsheetFile.exportXlsx(workbook)).save(output);
const content = await fs.readFile(output);
const manifestPath = path.join(directory, 'split208_conversion_manifest.json');
const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
manifest.output_file = path.basename(output);
manifest.output_sha256 = crypto.createHash('sha256').update(content).digest('hex');
manifest.export_engine = '@oai/artifact-tool';
manifest.output_rows_including_metadata = rows.length;
await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
console.log(output);
