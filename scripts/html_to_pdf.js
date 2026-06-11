#!/usr/bin/env node
'use strict';

const puppeteer = require('puppeteer-core');
const fs = require('fs');
const path = require('path');

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const CSS = `
  @page { size: A4; margin: 1.05cm 1.05cm 1.35cm 1.05cm; }
  * { box-sizing: border-box; }
  html { background: #F3F6F9; }
  body {
    margin: 0;
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif;
    font-size: 12px;
    line-height: 1.65;
    color: #1F2937;
    background: #F3F6F9;
  }
  .report-shell {
    background: #FFFFFF;
    min-height: 100vh;
    padding: 14px 16px 18px 16px;
    border: 1px solid #E2E8F0;
  }
  .report-cover, .executive-summary, .summary-card, .summary-narrative, .report-note,
  .chart-panel, .risk-card, .risk-card-row, .avoid-page-break,
  table, thead, tbody, tr, svg, blockquote {
    page-break-inside: avoid;
    break-inside: avoid;
  }
  .risk-card-panel {
    page-break-inside: auto;
    break-inside: auto;
  }
  .chart-heading {
    page-break-after: avoid;
    break-after: avoid;
  }
  p:has(> strong:only-child) {
    page-break-after: avoid;
    break-after: avoid;
  }
  h1 {
    font-size: 22px;
    line-height: 1.3;
    color: #0F172A;
    border-bottom: 2px solid #0F766E;
    padding-bottom: 7px;
    margin: 16px 0 10px 0;
    font-weight: 800;
  }
  h2 {
    font-size: 16px;
    line-height: 1.35;
    color: #0F172A;
    margin: 22px 0 10px 0;
    padding: 7px 10px;
    border-left: 4px solid #0F766E;
    background: #F8FAFC;
    border-radius: 0 6px 6px 0;
    page-break-after: avoid;
    break-after: avoid;
  }
  h3 {
    font-size: 13px;
    line-height: 1.45;
    color: #334155;
    margin: 15px 0 8px 0;
    font-weight: 750;
    page-break-after: avoid;
    break-after: avoid;
  }
  table {
    width: 100% !important;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 10.5px;
    line-height: 1.45;
    margin: 9px 0 12px 0;
    overflow-wrap: anywhere;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    overflow: hidden;
  }
  thead { display: table-header-group; }
  tfoot { display: table-footer-group; }
  th {
    background: #EEF2F7;
    color: #0F172A;
    border-bottom: 1px solid #CBD5E1;
    padding: 7px 8px;
    text-align: center;
    font-weight: 750;
  }
  td {
    padding: 7px 8px;
    border-bottom: 1px solid #E5E7EB;
    vertical-align: top;
  }
  tbody tr:nth-child(even) { background-color: rgba(248, 250, 252, 0.7); }
  tr:last-child td { border-bottom: 0; }
  svg { max-width: 100%; height: auto; display: block; }
  ul, ol { padding-left: 20px; margin: 6px 0 8px 0; }
  li { margin: 2px 0; }
  strong { color: #111827; font-weight: 800; }
  code { background: #F1F5F9; border: 1px solid #E2E8F0; border-radius: 4px; padding: 0 4px; color: #0F172A; }
  blockquote { border-left: 3px solid #94A3B8; padding: 8px 12px; color: #475569; background: #F8FAFC; margin: 8px 0; }
  p { margin: 6px 0; }
  hr { border: none; border-top: 1px solid #E2E8F0; margin: 14px 0; }
  @media print {
    html, body { background: #FFFFFF; }
    .report-shell { border: 0; padding: 0; }
  }
`;

async function main() {
  const [mdPath, pdfPath] = process.argv.slice(2);
  if (!mdPath || !pdfPath) {
    console.error('Usage: node html_to_pdf.js <input.md> <output.pdf>');
    process.exit(1);
  }

  const mdContent = fs.readFileSync(mdPath, 'utf-8');

  // Use Python markdown via subprocess for consistent rendering
  const { execSync } = require('child_process');
  const htmlBody = execSync(
    `python3 -c "import markdown,sys; print(markdown.markdown(sys.stdin.read(), extensions=['tables','fenced_code']))"`,
    { input: mdContent, encoding: 'utf-8' }
  );

  const htmlDoc = `<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><style>${CSS}</style></head>
<body><main class="report-shell">${htmlBody}</main></body>
</html>`;

  const tmpHtml = '/tmp/report_pdf_temp.html';
  fs.writeFileSync(tmpHtml, htmlDoc, 'utf-8');

  const browser = await puppeteer.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const page = await browser.newPage();
  await page.goto(`file://${tmpHtml}`, { waitUntil: 'networkidle0' });
  await page.pdf({
    path: pdfPath,
    format: 'A4',
    margin: { top: '1.05cm', bottom: '1.35cm', left: '1.05cm', right: '1.05cm' },
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: '<div style="width:100%;font-size:8px;color:#94A3B8;padding:0 1.05cm;display:flex;justify-content:space-between;font-family:-apple-system, PingFang SC, Microsoft YaHei, sans-serif;"><span>纸袋月度库存AI分析报告</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>',
    printBackground: true,
  });

  await browser.close();
  fs.unlinkSync(tmpHtml);
  console.log(`PDF generated: ${pdfPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
