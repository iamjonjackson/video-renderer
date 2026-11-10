# video-renderer

Declarative video generation pipeline: describe scenes in a JSON spec, get an
MP4 with animated visuals and a TTS voiceover from Mistral Voxtral (default),
Google Gemini TTS or ElevenLabs.

## How it works

1. You provide a **spec** (JSON) — a timeline of scenes with text, charts,
   images, and optional narration.
2. The renderer synthesizes narration per scene via the selected TTS provider
   (see [Narration providers](#narration-providers)),
   probes each clip's duration, and sizes each scene to its audio
   (audio-driven timeline). Explicit `duration` overrides when you want a
   scene to linger.
3. MoviePy composites the scenes with animations and encodes the final MP4.

## Running locally

```bash
git clone https://github.com/iamjonjackson/video-renderer.git
cd video-renderer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env     # then edit .env and add a provider key (e.g. MISTRAL_API_KEY)
set -a; source .env; set +a   # load env vars (or use dotenv in your shell)

# Final videos go to ./output, intermediate render files to ./temp
python3 src/render.py samples/sample-spec.json -o output/demo.mp4
```

Notes:

- `.env` is gitignored; `.env.example` documents the variables. Put real
  keys only in `.env`, never in the tracked `.env.example`.
- MoviePy loads the nearest `.env` on import (python-dotenv), without
  overriding variables already set. To test the no-key path with keys in
  `.env`, set the variable to empty, e.g. `GOOGLE_API_KEY= TTS_PROVIDER=google ...`.
- `output/` (final videos) and `temp/` (TTS/image caches, intermediate
  artifacts) are gitignored except their `.gitkeep` placeholders.
- Without the selected provider's key (or if the provider errors), scenes
  render silently with a warning; without `MISTRAL_API_KEY`, AI image blocks
  are skipped with a warning — the pipeline never hard-fails on missing AI.
- System ffmpeg is used if installed; otherwise `imageio-ffmpeg` bundles one.

## Frame: local visual Studio

Studio adds a Material-inspired storyboard editor without changing the CLI.
Use Python 3.12 with the dependencies above, then run:

```bash
source .venv/bin/activate
python src/studio.py
```

Open **<http://127.0.0.1:8765>** or **<http://localhost:8765>** on the
computer running Studio. Browser-saved projects are separate for each address.
Use `--port 8766` if that port is occupied. Studio is local-only, not a
production server or a hosted collaboration service.

- **Editor / Create** navigation switches between the canvas and a dedicated
  storyboard-generation page without overlays. Browser Back/Forward work;
  navigation preserves the current project. Create offers explainer,
  product-pitch and project-update prompt examples. A small 360M-parameter AI
  runs on the browser CPU to write
  validated JSON from your title, description (20–3000 characters) and optional
  key points. Review the JSON, then explicitly
  approve replacing the project; edits invalidate stale previews.
- **Canvas-first editing:** add text, native charts and rectangle/ellipse shapes,
  drag to place, use arrow keys to nudge (Shift for larger steps), and select
  an element, then right-click for colour, text size in export pixels, alignment and
  layer controls. Shift+F10 / the context-menu key and the element's options
  button provide keyboard/touch access; no persistent selected-element bar. Double-click/Enter edits text **in place** on the canvas; no popup.
  Resize with the eight corner/edge handles (arrow keys resize a focused handle).
  Backspace/Delete removes a focused element, never text being typed. Text size
  is committed as a validated pixel value, not a percentage slider.
  Click away or Control/Command+Enter commits, Escape restores the original.
  Text drafts are browser-saved; unsupported export glyphs are reported after
  editing. The Chart button opens its data/style editor immediately. Styles include column,
  horizontal bar, line, area, pie and doughnut; these export as native editable
  PowerPoint charts. Shape options include rectangle, ellipse, rounded card,
  triangle and arrow for callouts, process flows and emphasis.
  Chart labels, values and style edit directly on the chart: **Done**
  validates/saves the complete draft; **Escape** cancels. Narration alone uses
  an inline notes panel. Pending
  validation cannot overwrite newer edits or a different scene. No right-hand
  inspector or oversized project header. The editor fits the viewport; scenes
  scroll within the storyboard, while **Scene style** opens background/timing
  controls on demand. Dropdowns follow the interface theme (custom native pickers
  where supported). Imported legacy per-bullet notes are retained as combined
  composition notes, up to 7,205 characters.
- Scene templates: blank, title, quote, data story, comparison and closing.
  Chart template values are examples, not factual claims. Legacy title/bullet/
  chart/outro scenes automatically become editable canvas objects when opened,
  retaining duration and narration. Bullets are individually editable. Animation/reveal timing
  may change; export a JSON backup before converting.
- Select solid, gradient, grid, orbit or wave backgrounds, with still/drift/pulse
  motion. Preview is a user-triggered five-second approximation with Stop and
  reduced-motion handling; video backgrounds animate, while PPTX uses time zero.
- Edit title, bullet, chart and outro scenes; add, delete and reorder them.
  Drag scenes to reorder; Alt+arrows provide keyboard reordering. Backspace/Delete
  removes a focused scene, retaining at least one. The compact + in the storyboard
  header opens a scene-type chooser. Right-click a scene, use its ••• button or
  Shift+F10 for Edit on Canvas / Delete; the last scene cannot be deleted.
  Scene cards show miniature slide previews updated from the current content.
  Arrow keys/Home/End select scenes. Changes are announced and
  errors receive focus; page navigation and inline editing retain keyboard focus.
- Choose scenes in the single storyboard list. The header's appearance button
  switches the interface between light and dark with a circular reveal; the
  preference is saved separately from video styling. Reduced-motion preferences
  and browsers without View Transitions use an immediate switch.
- UI motion uses short, finite transitions for page/scene changes, added scenes
  and elements, menus and generated results, plus hover/press/focus feedback.
  Navigation and scene-selection highlights glide between choices; scene changes
  crossfade the outgoing canvas without flashing the stage background.
  Rapid interactions replace earlier entrances; typing/dragging take priority.
  Reduced-motion preferences disable this movement, including changes while
  animations are running. These UI effects do not change exported videos.
- Change the video background/accent, import/export JSON, and restore the last
  project from this browser's local storage. Export JSON before replacing a
  project or clearing browser storage; imports replace the current project.
- The canvas is an **approximate layout preview**, not a live MoviePy render.
  Long text may clip in the final video; inspect the rendered result. Line/pie
  charts are represented by a labelled data preview, not an exact chart.
- Choose **Video + PowerPoint** or **PowerPoint only**. The latter reuses the
  CLI's `--pptx-only` path: no MP4 generation or encoding. Download links are
  offered only for successful output types.
- Render an actual **silent MP4 and PPTX** with download links. Narration stays
  in authored/exported JSON but is removed from the render copy. Inherited
  provider credentials are excluded; rendering makes no AI calls. Timing uses
  explicit scene durations, unlike narration-driven CLI renders.
- Up to 12 scenes, 16 elements per canvas, 60 seconds total, 1–15 seconds per
  scene. Resolutions: 1280×720, 1920×1080, 1080×1920, 720×1280, 1080×1080,
  2560×1440, 3840×2160, 2160×3840 and 2160×2160. 4K uses more time/memory and
  remains subject to the render deadline. Canvas preview fits the available space;
  aspect ratio changes its shape, but higher resolution at the same aspect ratio
  does not make the on-screen preview larger.
  Canvas coordinates are normalised. Legacy MP4/PPTX layouts fit without distortion;
  freeform scenes use the full selected aspect ratio. Existing 1080p CLI defaults
  remain unchanged. Rendering uses
  24/30 fps. Image scenes/AI image blocks and unsupported fields are rejected;
  use the CLI for those features. The upstream sample includes an AI image
  block, so it is not directly importable into this bounded editor.
- One render at a time, three-minute deadline and ten renders per server
  session. Outputs use private temporary directories, removed on shutdown;
  download them before stopping Studio. Refreshing reconnects to the latest
  job. A failed PPTX export is reported separately from a successful video.

UI typography uses the operating system's sans-serif font (including Apple's
system font on macOS) without redistributing SF Compact. Final video rendering
continues to use the CLI's DejaVu Sans. No web-font CDN or frontend build is
needed. Canvas text/shape/chart objects remain editable in PPTX; typography can
vary with PowerPoint font substitution. Composition export uses DejaVu Sans;
unsupported glyphs are rejected before rendering with their Unicode code points,
rather than silently showing missing-character boxes. Full colour emoji and
complex emoji sequences are not supported. UI icons are SVG, not emoji. FontTools
is used for font coverage (included by Matplotlib's dependency set).
The existing CLI and AI integrations remain available.

### Browser-local AI storyboard drafting

Before first use, download the pinned model and browser runtime:

```bash
python scripts/setup_browser_ai.py
python src/studio.py
```

Setup needs internet access and roughly 400 MB of disk space. It verifies SHA-256
model and SHA-512 package checksums without executing package installation scripts.
Assets stay in `studio/ai-assets/` (ignored by Git); rerun setup after a fresh clone.
Generation then works without internet. No API key, Ollama, GPU or AI server is
required. This is the only generation method; the former hardcoded local templates,
Mistral endpoint and `--enable-generation` option have been removed.

Uses [SmolLM2-360M-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct)
(Apache-2.0; see `studio/SMOLLM2-LICENSE`), Q8_0 weights pinned to Unsloth revision
`391ed11137586e383b1be0fab9acf01d282c2e11`, and
[wllama 3.13.0](https://github.com/ngxson/wllama) (MIT). wllama runs single-threaded
WebAssembly CPU inference in a worker; JSON-schema grammar constrains the output.
The model, WASM and JavaScript load only from Studio's same-origin static server.
The brief is not sent to a hosted AI service. Generated JSON goes to the local
Python `/api/validate` endpoint before review; that endpoint makes no AI calls.

In **Create**, fill a title, description and optional key points, then select
**Generate storyboard JSON**. Initial loading transfers about 386 MB from the
local server into browser storage. Loading progress and **Cancel generation**
are available; editing the brief or leaving Create cancels pending work. Your
project is unchanged until you review the JSON and confirm replacement.

A current browser with WebAssembly, worker and browser-storage support is needed.
Runtime memory exceeds model size; low-memory devices may fail, and weaker CPUs
can be slow. This is not a guarantee of support on every machine. The generator now explains the input roles and silent-video requirements, assigns
source key points to ordered slides, and constrains the opening/body/ending schema.
It creates 4–8 slides within the 60-second limit, rather than allowing a three-slide
placeholder. No-key-point briefs are divided using their source sentences. Slide
headings retain assigned source topics when they fit the heading limit; otherwise
  the model writes a concise heading. The AI writes the visible body text.
This is structure enforcement, not a hardcoded content generator.

The tiny model
is intentionally less capable than larger models: use clear, concise English
briefs, verify facts and rewrite weak drafts. Invalid/truncated output is rejected,
not repaired or replaced by a template. No automatic retry or cloud fallback.

Run the Studio checks:

```bash
python -m unittest discover -s tests -v
for file in studio/*.js studio/*.mjs; do node --check "$file" || exit 1; done
node --test tests/test_browser_ai.mjs
```

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
- **Editable PPTX charts**: chart scenes export as native PowerPoint charts
  (bar, line, pie) themed to the spec, so you can edit the data in
  PowerPoint. Set `"pptx_chart": "image"` on a chart scene to keep the
  matplotlib PNG instead; unsupported or failing charts fall back to the
  PNG with a warning. The video always uses the PNG.
- **PPTX-only mode**: `python3 src/render.py spec.json -o output/deck.pptx --pptx-only`
  skips the video path entirely (no clips, segments, ffmpeg or MP4) and
  writes just the deck, still with narration, AI images and charts. With a
  warm workdir cache it makes no API calls and runs in seconds. This is a
  CLI flag only; a spec-level `"meta": {"render": "pptx"}` option is a
  non-goal, since output format is a per-run choice and the same spec should
  produce either.
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
- **Voice** (Mistral): built-in voice slugs (list via `GET /v1/audio/voices`)
  or a cloned `voice_id` from a 2–3s audio sample. Other providers take their
  voice from `meta.tts` — see [Narration providers](#narration-providers).
- Full contract: `src/schema.json` (JSON Schema).

See `samples/sample-spec.json` for a complete example.

## Files

- `src/render.py` — spec → MP4 renderer (MoviePy + Matplotlib)
- `src/tts.py` — TTS contract + provider dispatch; Mistral Voxtral REST client (`/v1/audio/speech`)
- `src/tts_google.py` — Google Gemini TTS adapter (`generateContent`, PCM/WAV)
- `src/tts_elevenlabs.py` — ElevenLabs adapter (`/v1/text-to-speech/{voice_id}`, MP3)
- `src/schema.json` — JSON Schema for the spec
- `src/themes/presets.py` — dark/light color presets
- `demos/` — rendered example videos from `samples/sample-spec.json`

## Notes

- TTS is skipped gracefully (with a warning) when the selected provider's
  key is unset or the provider fails (quota, network, rejected voice).
- Never commit API keys; pass via environment only.

## Narration providers

| `TTS_PROVIDER` | Key env var | Output | Default voice / model |
|---|---|---|---|
| `mistral` (default) | `MISTRAL_API_KEY` | WAV (or `voice.format`) | `voice.slug`, else `gb_jane_neutral` fallbacks / `voxtral-mini-tts-2603` |
| `google` | `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | WAV | `Kore` / `gemini-3.8-flash-lite-tts` |
| `elevenlabs` | `ELEVENLABS_API_KEY` | MP3 | first usable voice on your account / `eleven_multilingual_v2` |

Selection order: the `TTS_PROVIDER` env var, then the spec's
`"meta": {"tts": {"provider": ...}}`, then `mistral`. With neither set,
behaviour is unchanged. Per-spec settings for a provider:

```json
"meta": { "tts": { "provider": "google", "voice": "Charon",
                   "style": "Read aloud in a neutral, warm narration voice" } }
```

`meta.tts.voice` / `model` / `style` only apply when the effective provider
matches `meta.tts.provider`, and the top-level `voice` block only applies to
Mistral, so overriding with `TTS_PROVIDER` never sends one provider's voice
to another. Env overrides: `GOOGLE_TTS_VOICE`, `GOOGLE_TTS_MODEL`,
`GOOGLE_TTS_STYLE`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`.

Narration clips are cached in the workdir as
`narr_<provider>_<hash>_<n>.<ext>`, where the hash covers the text,
provider, voice, model and style, so switching provider or voice regenerates
audio rather than replaying another provider's clips. (Caches from before
this change are regenerated once.) AI image generation still uses Mistral.

### Getting a Google (Gemini API) key

- Create a key at [Google AI Studio](https://aistudio.google.com/apikey)
  and set `GOOGLE_API_KEY=...`. No credit card is needed for the free tier.
- Gemini TTS models are available on the Gemini API free tier within
  per-project rate limits (requests per minute/day). Check the current
  allowances on the [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
  page and [pricing](https://ai.google.dev/gemini-api/docs/pricing) page; on
  the free tier, Google may use prompts to improve its products. Image
  generation is not on the free tier (and this repo's images use Mistral anyway).
- The default model is `gemini-3.8-flash-lite-tts`; if it is unavailable to
  your key, the adapter tries `gemini-3.8-flash-tts`, then
  `gemini-3.1-flash-tts-preview`, also moving on when a model's free-tier
  quota is exhausted (HTTP 429). Quotas are per model and small (one test
  project hit a 10-request limit on `gemini-3.8-flash-lite-tts`), and each
  narration clip is one request, so a long spec can exceed them; scenes
  past the limit render silently and are synthesized on the next run, since
  finished clips stay cached. Older models such as
  `gemini-2.5-flash-preview-tts` are being retired; pin a model with
  `GOOGLE_TTS_MODEL` or `meta.tts.model` if you need one.
- Voices are Gemini's prebuilt voice names (e.g. `Kore`, `Charon`, `Puck`);
  delivery is steered by the `style` prompt.

### Getting an ElevenLabs key

- Sign up at [elevenlabs.io](https://elevenlabs.io) and create a key under
  [API keys](https://elevenlabs.io/app/settings/api-keys); set
  `ELEVENLABS_API_KEY=...`. If you restrict the key's permissions, allow
  Text to Speech and Voices (read).
- **Free tier: 10,000 credits/month** (about 10 minutes of audio with
  `eleven_multilingual_v2`; Flash/Turbo models use about half the credits per
  character — set `ELEVENLABS_MODEL=eleven_flash_v2_5`).
- **Free tier is non-commercial only and requires attribution**: credit
  ElevenLabs (e.g. "Voice: elevenlabs.io") in the video or its description.
  It is fine for coursework and demos; monetized output needs a paid plan
  (Starter and up include a commercial licence). See
  [ElevenLabs pricing](https://elevenlabs.io/pricing) and terms.
- **Voice availability on free keys**: free-tier keys cannot use Voice
  Library voices through the API, and ElevenLabs' legacy Default voices are
  only on accounts created before March 2026 and are retired on
  31 December 2026 ([details](https://elevenlabs.io/docs/help-center/product/voice-customization/my-voices/what-are-default-voices)).
  The adapter picks the first usable voice from your account's `/v1/voices`
  (preferring a British premade voice); set `ELEVENLABS_VOICE_ID` to pin one.
  If no voice is usable, scenes render silently with a warning.

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
