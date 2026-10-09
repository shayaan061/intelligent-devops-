// Builds IDF_final.docx and IDF_final.txt from content.js.
// Usage: node build.js <out_dir>
const fs = require("fs");
const path = require("path");
const {
  AlignmentType, BorderStyle, Document, ImageRun, LevelFormat, Packer, Paragraph,
  ShadingType, Table, TableCell, TableRow, TextRun, WidthType, Footer, PageNumber,
} = require("docx");
const blocks = require("./content");

const out = process.argv[2] || ".";
const FONT = "Times New Roman";
const CONTENT_W = 9026; // A4 with 1" margins, in DXA
const sp = (after = 120, before = 0) => ({ spacing: { after, before, line: 276 } });

function runs(lead, text, size = 24) {
  const r = [];
  if (lead) r.push(new TextRun({ text: lead + " ", bold: true, font: FONT, size }));
  if (text) r.push(new TextRun({ text, font: FONT, size }));
  return r;
}

function inventorsTable(rows) {
  const head = ["S No", "Name (Full)", "Department/ School", "Designation", "Mobile No.", "Email", "Official Address"];
  const widths = [620, 1300, 1400, 1250, 1100, 1856, 1500]; // sums to 9026
  const border = { style: BorderStyle.SINGLE, size: 4, color: "808080" };
  const borders = { top: border, bottom: border, left: border, right: border };
  const cell = (text, i, header) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA }, borders,
    margins: { top: 60, bottom: 60, left: 80, right: 80 },
    shading: header ? { type: ShadingType.CLEAR, fill: "E7E6E6", color: "auto" } : undefined,
    children: [new Paragraph({ children: [new TextRun({ text, bold: header, font: FONT, size: 18 })] })],
  });
  return new Table({
    width: { size: CONTENT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: head.map((h, i) => cell(h, i, true)) }),
      ...rows.map((r) => new TableRow({ children: r.map((v, i) => cell(v, i, false)) }))],
  });
}

const children = [];
const txt = [];
const wrap = (s, indent = "") => {
  // plain text, wrapped at 92 columns for readability
  const words = s.split(" "); const lines = []; let line = indent;
  for (const w of words) {
    if ((line + w).length > 92 && line.trim()) { lines.push(line.trimEnd()); line = indent; }
    line += w + " ";
  }
  if (line.trim()) lines.push(line.trimEnd());
  return lines.join("\n");
};

for (const b of blocks) {
  switch (b.t) {
    case "center":
      children.push(new Paragraph({ alignment: AlignmentType.CENTER, ...sp(80), children: [new TextRun({ text: b.text, bold: b.bold, font: FONT, size: b.size })] }));
      txt.push(b.text);
      break;
    case "title":
      children.push(new Paragraph({ alignment: AlignmentType.CENTER, ...sp(240, 360), children: [new TextRun({ text: b.text, bold: true, font: FONT, size: 30 })] }));
      txt.push("", b.text.toUpperCase(), "");
      break;
    case "h1":
      children.push(new Paragraph({ ...sp(120, 280), keepNext: true, children: [new TextRun({ text: b.text, bold: true, font: FONT, size: 26 })] }));
      txt.push("", b.text, "-".repeat(Math.min(b.text.length, 92)));
      break;
    case "h2":
      children.push(new Paragraph({ ...sp(80, 200), keepNext: true, children: [new TextRun({ text: b.text, bold: true, font: FONT, size: 24 })] }));
      txt.push("", b.text);
      break;
    case "p":
      children.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, ...sp(), children: [new TextRun({ text: b.text, bold: b.bold, font: FONT, size: 24 })] }));
      txt.push(wrap(b.text), "");
      break;
    case "bullets":
      for (const it of b.items) {
        const lead = typeof it === "string" ? null : it.lead, text = typeof it === "string" ? it : it.text;
        children.push(new Paragraph({ numbering: { reference: "bullets", level: 0 }, alignment: AlignmentType.JUSTIFIED, ...sp(80), children: runs(lead, text) }));
        txt.push(wrap(`- ${lead ? lead + " " : ""}${text}`, "  ").replace(/^ {2}/, ""));
      }
      txt.push("");
      break;
    case "items":
      for (const it of b.items) {
        children.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, indent: { left: 360 }, ...sp(120), children: runs(it.lead, it.text) }));
        txt.push(wrap(`${it.lead} ${it.text}`), "");
      }
      break;
    case "inventors":
      children.push(inventorsTable(b.rows));
      for (const r of b.rows) {
        txt.push(`${r[0]}. ${r[1]}`, `   Department/School: ${r[2]}`, `   Designation: ${r[3]}`, `   Mobile No.: ${r[4]}`, `   Email: ${r[5]}`, `   Official Address: ${r[6]}`, "");
      }
      break;
    case "img": {
      const data = fs.readFileSync(path.join(__dirname, b.file));
      const wPx = 600, hPx = Math.round((wPx * b.h) / b.w); // docx-js sizes images in px (96 dpi); 600 px = the A4 text width
      children.push(new Paragraph({ alignment: AlignmentType.CENTER, ...sp(80, 200), keepNext: true,
        children: [new ImageRun({ type: "png", data, transformation: { width: wPx, height: hPx },
          altText: { title: b.caption, description: b.caption, name: b.file } })] }));
      children.push(new Paragraph({ alignment: AlignmentType.CENTER, ...sp(240), children: [new TextRun({ text: b.caption, bold: true, font: FONT, size: 22 })] }));
      txt.push(`[${b.caption} — see the figure image]`, "");
      break;
    }
    case "claims":
      for (const c of b.items) {
        children.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, ...sp(c.length > 1 ? 60 : 160), keepNext: c.length > 1, children: [new TextRun({ text: c[0], font: FONT, size: 24 })] }));
        txt.push(wrap(c[0]));
        c.slice(1).forEach((line, i) => {
          children.push(new Paragraph({ alignment: AlignmentType.JUSTIFIED, indent: { left: 720 }, ...sp(i === c.length - 2 ? 160 : 60), children: [new TextRun({ text: line, font: FONT, size: 24 })] }));
          txt.push(wrap(line, "    "));
        });
        txt.push("");
      }
      break;
    case "signatures":
      children.push(new Paragraph({ ...sp(200, 280), children: [new TextRun({ text: "Signature of Inventor(s):", bold: true, font: FONT, size: 24 })] }));
      txt.push("", "Signature of Inventor(s):", "");
      for (const n of b.names) {
        for (const [k, v] of [["Signature:", "______________________________"], ["Name:", n], ["Date:", "____________________"]]) {
          children.push(new Paragraph({ ...sp(60), children: [new TextRun({ text: `${k} `, bold: true, font: FONT, size: 24 }), new TextRun({ text: v, font: FONT, size: 24 })] }));
          txt.push(`${k} ${v}`);
        }
        children.push(new Paragraph({ ...sp(160), children: [] }));
        txt.push("");
      }
      break;
    default:
      throw new Error("unknown block " + b.t);
  }
}

const doc = new Document({
  creator: "Muhammad Shayaan Ali, Shruti Tyagi, Riddhima Sharma, Ashish Kumar",
  title: "Invention Disclosure Form: Intelligent DevOps Monitoring & Incident Response System",
  styles: { default: { document: { run: { font: FONT, size: 24 } } } },
  numbering: { config: [{ reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
    style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text: "Page ", font: FONT, size: 18 }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 18 }),
      new TextRun({ text: " of ", font: FONT, size: 18 }), new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 18 })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(path.join(out, "IDF_final.docx"), buf);
  fs.writeFileSync(path.join(out, "IDF_final.txt"), txt.join("\n").replace(/\n{3,}/g, "\n\n").trim() + "\n");
  console.log("written to", out);
});
