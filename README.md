# video-renderer

Declarative video generation pipeline: describe scenes in a JSON spec, get an
MP4 with animated visuals and Mistral TTS (Voxtral) voiceover.

## How it works

1. You provide a **spec** (JSON) — a timeline of scenes with text, charts,
   images, and optional narration.
2. The renderer synthesizes narration per scene via the Mistral TTS API,
   probes each clip's duration, and sizes each scene to its audio
   (audio-driven timeline). Explicit `duration` overrides when you want a
   scene to linger.
3. MoviePy composites the scenes with animations and encodes the final MP4.

## Running locally

```bash
git clone https://github.com/iamjonjackson/video-renderer.git
cd video-renderer
python3 -m venv .venv && source .venv/bin/activate
pip install moviepy matplotlib imageio-ffmpeg pillow

cp .env.example .env     # then edit .env and add your MISTRAL_API_KEY
set -a; source .env; set +a   # load env vars (or use dotenv in your shell)

# Final videos go to ./output, intermediate render files to ./temp
python3 src/render.py samples/sample-spec.json -o output/demo.mp4
```

Notes:
- `.env` is gitignored; `.env.example` documents the variables.
- `output/` (final videos) and `temp/` (TTS/image caches, intermediate
  artifacts) are gitignored except their `.gitkeep` placeholders.
- Without `MISTRAL_API_KEY`, scenes render silently and AI image blocks are
  skipped with a warning — the pipeline never hard-fails on missing AI.
- System ffmpeg is used if installed; otherwise `imageio-ffmpeg` bundles one.

### GitHub Actions

A `Render test` workflow runs on PRs: renders `samples/sample-spec.json`
using the `MISTRAL_API_KEY` repo secret and uploads the MP4 as an artifact.

## Spec format (summary)

```json
{
  "meta":  { "fps": 30 },
  "theme": { "preset": "dark", "accent": "#58a6ff" },
  "voice": { "slug": "gb_jane_neutral" },
  "timeline": [
    { "type": "title",  "text": "Quarterly Review", "narration": "..." },
    { "type": "bullets", "heading": "Key Wins", "items": ["...", "..."] },
    { "type": "chart",  "chart_type": "bar", "labels": ["Jul","Aug","Sep"],
                        "values": [410, 455, 512], "narration": "..." },
    { "type": "image",  "src": "assets/slide.png", "anim": "kenburns" },
    { "type": "outro",  "text": "Thank you" }
  ]
}
```

- **Scene types**: `title`, `bullets`, `chart` (bar/line/pie), `image`, `outro`
- **Animations**: `fade`, `slide-up`, `zoom-in`, `kenburns` (images)
- **PPTX export**: every render also emits a `.pptx` alongside the MP4 —
  one slide per scene, built from the same artifacts (narration WAVs
  embedded on their slides, chart PNGs, generated images). Open in
  PowerPoint, tweak, and export to video from there for a near-identical
  result.
- **AI-generated images** (optional, any scene): add an `image` block —

```json
"image": {
  "prompt": "minimal isometric illustration of a rocket launch, deep blue palette",
  "placement": "background"   // "background" (faded, behind text) or
                               // "left" / "right" (spotlight panel beside text)
  "opacity": 0.25,             // background mode: image fade level
  "model": "mistral-medium-latest" // optional agent model override
}
```

For `background` placement the renderer measures WCAG contrast of the text
area against the composited backdrop and raises the scrim opacity until
AA (≥ 4.5:1) is met. If the target can't be reached even at maximum scrim,
the render continues with a warning (best-effort) — it never aborts.
`left`/`right` placements keep text on the solid theme background (contrast
by construction) with the image in a bordered panel.
- **Timing**: omit `duration` and provide `narration` for audio-driven scenes;
  `padding` (default 1.0s) adds a guaranteed tail buffer after narration.
- **Voice**: built-in voice slugs (list via `GET /v1/audio/voices`) or a
  cloned `voice_id` from a 2–3s audio sample.
- Full contract: `src/schema.json` (JSON Schema).

See `samples/sample-spec.json` for a complete example.

### Whole-video colour schemes

Pick one colour for the entire video:

```json
"theme": { "color_scheme": "purple" }
```

Options: **red, orange, yellow, green, blue, purple, pink, white, grey**.
Each scheme coordinates the slide background, content boxes, headings,
body text, caption panels, image borders, chart fills and labels, and
any generated branding. White uses a light canvas; the other schemes use
subtly tinted dark backgrounds with lighter accents. Charts retain direct
category/value labels rather than relying on colour alone. The same
resolved colours are used in the editable PPTX export.

The built-in solid colour pairs are tested against WCAG contrast thresholds:
[text at least 4.5:1](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html),
[meaningful chart fills at least 3:1 against the background](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html),
and pie percentages at least 4.5:1 against their slice. Schemed image
backgrounds put text on a solid panel; captions also use opaque panels.
These checks cover the curated colours at full scene visibility, rather
than arbitrary photos, logo opacity, transitions, or custom overrides.

`color_scheme` takes precedence over `preset`. Existing `dark` and `light`
presets still work when it is omitted. Explicit hex overrides such as `bg`,
`fg`, `accent`, `surface`, and `secondary` take precedence over a scheme;
custom overrides need their own contrast checks. Supplied PNGs and photos
retain their original colours.

See [the nine colour schemes](docs/evidence/branding/color-schemes.png).

### Branding overlay

Add an optional top-level `branding` block to place a logo over the video:

```json
"branding": {
  "logo": "assets/logo.png",
  "position": "bottom-right",
  "margin": 0.03,
  "max_height": 0.1,
  "opacity": 0.85,
  "scenes": "all"
}
```

Logo paths are relative to the spec file (absolute paths also work). PNG
transparency is preserved and multiplied by `opacity` (0–1). `position`
accepts `top-left`, `top-right`, `bottom-left`, or `bottom-right`.
`margin` is a fraction of each frame dimension, greater than 0 and less
than 0.5; the default 0.03 gives 58px horizontally and 32px vertically at
1920×1080, with a minimum inset of 1px. `max_height` is a fraction of frame
height (default 0.1, or 108px); logos retain their aspect ratio, never
upscale, and shrink further if needed to fit within the margins.

Use `"scenes": ["title", "outro"]` to brand only those scene types, or `[]`
to disable it. Omitted options use the defaults shown above. The logo stays
fixed above scene animations throughout each selected scene. Omit `branding`
to keep the existing rendering unchanged. This overlay applies to the MP4;
the editable PPTX export is unchanged.

#### Generate a brand from the spec

Instead of supplying a PNG, use `generated` to build a transparent symbol
and wordmark locally. The result is deterministic and needs no API key:

```json
"branding": {
  "generated": {
    "name": "Video Render",
    "style": "orbit"
  },
  "position": "bottom-right",
  "margin": 0.04,
  "max_height": 0.12,
  "opacity": 1,
  "scenes": "all"
}
```

Choose `orbit` (orbital rings and a satellite), `spark` (layered starburst),
or `petal` (four petals with a transparent centre). The default is `orbit`.
`name` is required (up to 32 characters); `tagline` is optional (up to 48).
Both must fit on a single line. Longer wordmarks scale down to fit the frame.

Generated branding automatically inherits `theme.color_scheme`. Without a
scheme it defaults to blue. For a logo-only override, `generated.palette`
accepts the same nine colour names; normally leave it out so the whole
video stays coordinated. Exact logo overrides are optional via
`generated.colors`, using `primary`, `secondary`, and `text` as `#RRGGBB`.

Supply exactly one of `logo` or `generated`. All placement, opacity, scale,
and scene-filter options work with either source.

Try `python3 src/render.py samples/branding-spec.json -o output/branding.mp4`.
See [all styles and palettes](docs/evidence/branding/brand-options.png).

## Files

- `src/render.py` — spec → MP4 renderer (MoviePy + Matplotlib)
- `src/tts.py` — Mistral Voxtral TTS REST client (`/v1/audio/speech`)
- `src/schema.json` — JSON Schema for the spec
- `src/themes/presets.py` — whole-video colour schemes and dark/light presets
- `demos/` — rendered example videos from `samples/sample-spec.json`

## Notes

- TTS is skipped gracefully (with a warning) when `MISTRAL_API_KEY` is unset.
- Never commit API keys; pass via environment only.

### Getting a Mistral API key

Students: request a key from your hackathon organiser.

- Free API access is not currently available from Mistral but the Pro (Education) option is very affordable if you wanted to sign up at [console.mistral.ai](https://console.mistral.ai)
- If you have a paid account, you can create a key under **API Keys**, copy it into your `.env`:
   `MISTRAL_API_KEY=...`
- Rate limits and model availability depend on your tier — see the
   **Limits** page in the console for your current allowances

## Contributing

Work happens on a branch in your fork **first**; the PR comes last.

1. **Fork** the repo, clone your fork, and create a branch: `git checkout -b your-feature`
2. **Pick an open issue** — issues are not exclusive; multiple teams may work the same one
3. **Build and test** — render the sample: `python3 src/render.py samples/sample-spec.json -o output/demo.mp4` (add your own `MISTRAL_API_KEY` in your fork under Settings → Secrets → Actions to run CI)
4. **Commit with co-author trailers** so teammates get credit: `Co-authored-by: Name <name@example.com>` (See `.github/PULL_REQUEST_TEMPLATE.md` for instructions)
5. **Push your branch and open a PR** (`gh pr create`, or the web UI's Contribute button), referencing the issue (`Closes #N`) and attaching screenshot/video evidence as per the PR template

> CI runs on PRs but without access to repo secrets — test locally or in your fork with your own `MISTRAL_API_KEY` if your change touches TTS or image generation.
