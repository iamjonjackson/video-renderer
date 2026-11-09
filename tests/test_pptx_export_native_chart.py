import json
import subprocess
import zipfile
from pathlib import Path


def test_chart_scene_uses_native_pptx_chart(tmp_path):
    spec = {
        "meta": {"title": "Demo"},
        "theme": {"bg": "#0d1117", "fg": "#f0f6fc", "accent": "#58a6ff"},
        "timeline": [
            {
                "type": "chart",
                "chart_type": "bar",
                "heading": "Monthly Revenue",
                "labels": ["Jul", "Aug", "Sep"],
                "values": [410, 455, 512],
            }
        ],
    }
    spec_path = tmp_path / "chart-spec.json"
    output = tmp_path / "chart-demo.pptx"
    spec_path.write_text(json.dumps(spec))

    subprocess.run(
        ["node", "scripts/export_pptx.js", "--spec", str(spec_path), "--output", str(output)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )

    with zipfile.ZipFile(output) as zf:
        names = zf.namelist()
        assert any(name.startswith('ppt/charts/') for name in names), "Expected a chart XML part in the PPTX package"
        assert any(name.endswith('chart1.xml') for name in names), "Expected native PowerPoint chart XML contents"
