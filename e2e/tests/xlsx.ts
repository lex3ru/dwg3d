import { crc32 } from 'node:zlib'

// A workbook of one sheet, enough for the import forms: rows of text and numbers.

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

function zip(files: [string, string][]): Buffer {
  const parts: Buffer[] = [], directory: Buffer[] = []
  let offset = 0
  for (const [name, text] of files) {
    const data = Buffer.from(text, 'utf8'), file = Buffer.from(name, 'utf8')
    const head = Buffer.alloc(30)
    head.writeUInt32LE(0x04034b50, 0); head.writeUInt16LE(20, 4); head.writeUInt16LE(0x0800, 6)      // stored, names in UTF-8
    head.writeUInt32LE(crc32(data), 14); head.writeUInt32LE(data.length, 18); head.writeUInt32LE(data.length, 22)
    head.writeUInt16LE(file.length, 26)
    const entry = Buffer.alloc(46)
    entry.writeUInt32LE(0x02014b50, 0); entry.writeUInt16LE(20, 4); entry.writeUInt16LE(20, 6); entry.writeUInt16LE(0x0800, 8)
    entry.writeUInt32LE(crc32(data), 16); entry.writeUInt32LE(data.length, 20); entry.writeUInt32LE(data.length, 24)
    entry.writeUInt16LE(file.length, 28); entry.writeUInt32LE(offset, 42)
    parts.push(head, file, data); directory.push(entry, file)
    offset += 30 + file.length + data.length
  }
  const size = directory.reduce((n, b) => n + b.length, 0), end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(files.length, 8); end.writeUInt16LE(files.length, 10)
  end.writeUInt32LE(size, 12); end.writeUInt32LE(offset, 16)
  return Buffer.concat([...parts, ...directory, end])
}

export function xlsx(rows: (string | number)[][]): Buffer {
  const cell = (v: string | number) => typeof v === 'number' ? `<c><v>${v}</v></c>` : `<c t="inlineStr"><is><t>${esc(v)}</t></is></c>`
  const ns = 'http://schemas.openxmlformats.org'
  return zip([
    ['[Content_Types].xml', `<?xml version="1.0" encoding="UTF-8"?><Types xmlns="${ns}/package/2006/content-types">` +
      '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>' +
      '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
      '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'],
    ['_rels/.rels', `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${ns}/package/2006/relationships">` +
      `<Relationship Id="rId1" Type="${ns}/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
    ['xl/workbook.xml', `<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="${ns}/spreadsheetml/2006/main" xmlns:r="${ns}/officeDocument/2006/relationships">` +
      '<sheets><sheet name="Лист1" sheetId="1" r:id="rId1"/></sheets></workbook>'],
    ['xl/_rels/workbook.xml.rels', `<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="${ns}/package/2006/relationships">` +
      `<Relationship Id="rId1" Type="${ns}/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>`],
    ['xl/worksheets/sheet1.xml', `<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="${ns}/spreadsheetml/2006/main"><sheetData>` +
      rows.map(r => `<row>${r.map(cell).join('')}</row>`).join('') + '</sheetData></worksheet>'],
  ])
}
