#!/usr/bin/env node

const fs = require('fs');
const path = require('path');
const pptxgen = require('pptxgenjs');

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token.startsWith('--')) {
      const key = token.slice(2);
      const next = argv[i + 1];
      if (next && !next.startsWith('--')) {
        args[key] = next;
        i += 1;
      } else {
        args[key] = true;
      }
      continue;
    }
    if (token.startsWith('-') && token.length > 1) {
      const key = token.slice(1);
      const next = argv[i + 1];
      if (next && !next.startsWith('-')) {
        args[key] = next;
        i += 1;
      } else {
        args[key] = true;
      }
    }
  }
  return args;
}

function hexToColor(hex) {
  return String(hex || '#000000').replace('#', '').toLowerCase();
}

function addTextBlock(slide, text, opts) {
  const config = {
    x: 0.5,
    y: 0.5,
    w: 12,
    h: 1,
    color: 'ffffff',
    fontFace: 'Arial',
    fontSize: 22,
    bold: false,
    ...opts,
  };
  slide.addText(text, config);
}

function addBulletList(slide, heading, items, theme) {
  if (heading) {
    addTextBlock(slide, heading, {
      x: 0.9,
      y: 0.6,
      w: 8,
      h: 0.8,
      color: hexToColor(theme.accent || '#58a6ff'),
      fontSize: 24,
      bold: true,
    });
  }

  const textConfig = {
    x: 1.2,
    y: 1.6,
    w: 10.2,
    h: 4.8,
    color: hexToColor(theme.fg || '#f0f6fc'),
    fontFace: 'Arial',
    fontSize: 20,
    bullet: { indent: 0.2 },
  };
  slide.addText(items.map((item) => ({ text: `• ${item}` })).join('\n'), textConfig);
}

function addChartSlide(pptx, slide, scene, theme) {
  const accent = hexToColor(theme.accent || '#58a6ff');
  const bg = hexToColor(theme.bg || '#0d1117');
  const fg = hexToColor(theme.fg || '#f0f6fc');
  const labels = Array.isArray(scene.labels) ? scene.labels : [];
  const values = Array.isArray(scene.values) ? scene.values : [];
  if (!labels.length || !values.length) {
    return;
  }

  const chartTypeName = (scene.chart_type || 'bar').toLowerCase();
  const mapping = { bar: 'bar', line: 'line', pie: 'pie' };
  const chartType = mapping[chartTypeName] || 'bar';

  if (scene.pptx_chart === 'png') {
    return;
  }

  if (scene.heading) {
    addTextBlock(slide, scene.heading, {
      x: 0.9,
      y: 0.55,
      w: 10,
      h: 0.6,
      color: accent,
      fontSize: 24,
      bold: true,
    });
  }

  const chartData = [{
    name: scene.heading || 'Series',
    labels,
    values,
    fill: accent,
    line: { color: accent },
  }];

  const chartOpts = {
    x: 1.2,
    y: 1.4,
    w: 10.8,
    h: 4.8,
    chartColors: [accent],
    showLegend: true,
    legendPos: 'b',
    dataLabelFormat: '0',
    chartArea: { fill: { color: bg } },
    plotArea: { fill: { color: bg } },
    categoryAxis: {
      line: { color: fg },
      textColor: fg,
      majorGridLines: { line: { color: fg, pt: 0.5 } },
    },
    valueAxis: {
      line: { color: fg },
      textColor: fg,
      majorGridLines: { line: { color: fg, pt: 0.5 } },
    },
    legend: { textColor: fg, fontFace: 'Arial', fontSize: 12 },
  };

  try {
    slide.addChart(pptx.ChartType[chartType], chartData, chartOpts);
  } catch (error) {
    console.warn(`[warn] native pptx chart fallback for ${chartType}: ${error.message}`);
    slide.addText('Chart data unavailable in this export format.', {
      x: 1.5,
      y: 2.2,
      w: 8,
      h: 1.5,
      color: fg,
      fontSize: 18,
    });
  }
}

function exportTimeline(spec, outputPath) {
  const theme = spec.theme || {};
  const pptx = new pptxgen();
  pptx.layout = 'LAYOUT_WIDE';
  pptx.author = 'video-renderer';
  pptx.company = 'QMUL';
  pptx.subject = 'Render export';
  pptx.title = spec.meta && spec.meta.title ? spec.meta.title : 'Video export';
  pptx.defineLayout({ name: 'WIDE', width: 13.333, height: 7.5 });

  for (const scene of spec.timeline || []) {
    const slide = pptx.addSlide();
    slide.background = { color: hexToColor(theme.bg || '#0d1117') };

    if (scene.type === 'title') {
      addTextBlock(slide, scene.text || '', {
        x: 1,
        y: 2.4,
        w: 11.3,
        h: 1.3,
        color: hexToColor(theme.fg || '#f0f6fc'),
        fontSize: 30,
        bold: true,
        align: 'center',
      });
      if (scene.subtitle) {
        addTextBlock(slide, scene.subtitle, {
          x: 2.5,
          y: 4.0,
          w: 8,
          h: 0.7,
          color: hexToColor(theme.accent || '#58a6ff'),
          fontSize: 18,
          align: 'center',
        });
      }
    } else if (scene.type === 'bullets') {
      addBulletList(slide, scene.heading, scene.items || [], theme);
    } else if (scene.type === 'chart') {
      addChartSlide(pptx, slide, scene, theme);
    } else if (scene.type === 'image') {
      if (scene.src) {
        slide.addImage({ path: scene.src, x: 0, y: 0, w: 13.333, h: 7.5 });
      }
      if (scene.caption) {
        addTextBlock(slide, scene.caption, {
          x: 1,
          y: 6.4,
          w: 11.3,
          h: 0.5,
          color: hexToColor(theme.fg || '#f0f6fc'),
          fontSize: 16,
          align: 'center',
        });
      }
    } else if (scene.type === 'outro') {
      addTextBlock(slide, scene.text || '', {
        x: 1,
        y: 2.8,
        w: 11.3,
        h: 1.5,
        color: hexToColor(theme.accent || '#58a6ff'),
        fontSize: 28,
        bold: true,
        align: 'center',
      });
    }
  }

  return pptx.writeFile({ fileName: outputPath });
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const specPath = args.spec || args.s;
  const outputPath = args.output || args.o || 'output/export.pptx';

  if (!specPath) {
    console.error('Usage: node scripts/export_pptx.js --spec <spec.json> --output <out.pptx>');
    process.exit(1);
  }

  const spec = JSON.parse(fs.readFileSync(specPath, 'utf8'));
  const absOutput = path.resolve(outputPath);
  fs.mkdirSync(path.dirname(absOutput), { recursive: true });

  exportTimeline(spec, absOutput)
    .then(() => {
      console.log(`[done] ${absOutput}`);
    })
    .catch((error) => {
      console.error(`[warn] pptx export failed: ${error.message}`);
      process.exit(1);
    });
}

main();
