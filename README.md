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
- The legacy CLI skips failed/missing TTS or optional Mistral AI images with
  warnings. Studio's explicitly requested narration is strict: failure is an
  error, never a successful silent narrated export.
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
  navigation preserves the current project. Create offers explicit Local and
  Hosted modes. In Local mode a small 0.8B-parameter AI runs on the browser CPU to write
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
- Choose **Video + PowerPoint**, **Video only** or **PowerPoint only**. Video only skips PowerPoint preparation and export entirely. The latter reuses the
  CLI's `--pptx-only` path: no MP4 generation or encoding. Download links are
  offered only for successful output types.
- Export **silent MP4 and PPTX** by default, or explicitly consent to narrated
  export using the server-configured identity (see below). Silent export removes
  narration only from its render copy. Render subprocesses receive no provider
  credentials; approved audio is prepared separately. Studio uses explicit timing.
- Up to 12 scenes, 16 elements per canvas, 60 seconds total, 1–15 seconds per
  scene. Resolutions: 1280×720, 1920×1080, 1080×1920, 720×1280, 1080×1080,
  2560×1440, 3840×2160, 2160×3840 and 2160×2160. 4K uses more time/memory and
  remains subject to the render deadline. Canvas preview fits the available space;
  aspect ratio changes its shape, but higher resolution at the same aspect ratio
  does not make the on-screen preview larger.
  Canvas coordinates are normalised. Legacy MP4/PPTX layouts fit without distortion;
  freeform scenes use the full selected aspect ratio. Existing 1080p CLI defaults
  remain unchanged. Rendering uses
  24/30 fps. Legacy filesystem image scenes/agent image blocks and unsupported
  fields are rejected; embedded PNG/JPEG canvas images are supported. Use the
  CLI for legacy images. The upstream sample's agent image block is not directly
  importable into Studio.
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

### Hosted generation and strict narration

Configure server environment variables before starting Studio: `FRAME_GOOGLE_MODEL`
with `GOOGLE_API_KEY` (or `GEMINI_API_KEY`), and/or `FRAME_MISTRAL_MODEL` with
`MISTRAL_API_KEY`. No hosted text model is selected implicitly. Readiness means
configuration is present, not that the account/model has been tested. See
`.env.example`; keys never go to the browser.

Hosted Create uses Google or Mistral structured JSON for grounded planning and
composition. Review source fidelity and approve replacement explicitly. Consent
covers sending the brief to the selected provider and applicable charges/data terms.
Optional stages are one Google concept image (`FRAME_GOOGLE_IMAGE_MODEL`), advisory
vision critique of up to three rendered frames, and one repair after critique.
Images require Google mode and no supplied asset; critique requires a model/account
with vision support. No automatic provider fallback or unbounded retries.

A job permits 2–5 calls (two core stages plus selected options), at most 16,384
output tokens per structured call, bounded input (title 1–100 characters,
description 20–3000, up to six 180-character points) and a four-minute coordinator
deadline. These are request bounds, **not a monetary cap or cost guarantee**.
Cancellation rejects late results and stops local processing; submitted remote calls
may still run and be charged. Safe client errors do not expose provider bodies or
credentials. In-memory caches retain eight structured stages and two completed
candidates; Studio shutdown clears them. Nothing is applied automatically.

Narrated export requires separate consent and exact server settings
`FRAME_TTS_PROVIDER` (`google`, `mistral` or `elevenlabs`), `FRAME_TTS_MODEL` and
`FRAME_TTS_VOICE`, plus the corresponding key. Preparation makes up to 12 separate
requests, one per narrated scene, with no retry or provider/model/voice fallback.
Every scene needs a transcript (authored narration or derived visible text).
Audio is decoded and measured before the credential-free renderer receives a
controlled manifest. An explicit duration shorter than the audio fails; missing
or corrupt required audio also fails. Captions are whole-scene transcript SRT cues,
not word-aligned captions. Review pronunciation and timing. Cancellation does not
make a paid request refundable; a new paid attempt requires consent again.

### Browser-local AI storyboard drafting

On first use, open **Create** and select **Download and enable local AI**.
The setup panel shows progress and cancellation. Studio downloads only fixed,
checksum-pinned model/runtime assets after consent, verifies them, and activates
all assets together. No separate shell setup is required. Installed assets are
verified offline on server startup and reused. Cancelled/failed setups keep partial
files out of use; retry is explicit. Setup needs internet and about 543 MB installed disk
space, plus staging space and browser memory. Prompts are never part of download
requests. Assets remain ignored by Git. `python scripts/setup_browser_ai.py` is an
optional CLI for the same provisioning mechanism.

Uses [Qwen3.5-0.8B](https://huggingface.co/Qwen/Qwen3.5-0.8B)
(Apache-2.0; see `studio/QWEN-LICENSE`), Q4_K_M weights pinned to Unsloth revision
`6ab461498e2023f6e3c1baea90a8f0fe38ab64d0`, and
[wllama 3.13.0](https://github.com/ngxson/wllama) (MIT). wllama runs single-threaded
WebAssembly CPU inference in a worker; JSON-schema grammar constrains the output.
The model, WASM and JavaScript load only from Studio's same-origin static server.
The brief is not sent to a hosted AI service. Generated JSON goes to the local
Python `/api/validate` endpoint before review; that endpoint makes no AI calls.

In **Create**, fill a title, description and optional key points, then select
**Generate storyboard JSON**. Initial loading transfers about 533 MB from the
local server into browser storage. Loading progress and **Cancel generation**
are available; editing the brief or leaving Create cancels pending work. Your
project is unchanged until you review the JSON and confirm replacement.

A current browser with WebAssembly, worker and browser-storage support is needed.
Runtime memory exceeds model size; low-memory devices may fail, and weaker CPUs
can be slow. This is not a guarantee of support on every machine. The generator writes directly to editable composition JSON with stable element IDs,
source-preserving text, safe normalised layout and aspect-aware typography. Supporting
sentences and takeaways are chosen from the brief rather than invented. This is a
source-grounded assembly mode, not unrestricted creative writing: use short source
sentences (up to 180 characters), review selected sentence relevance and text fit.
Generated canvases have 3–8 scenes. Every required point remains visible. Optional
entrance motion uses the same versioned contract as the editor and video renderer.

### Element animation

Select an element and open its options to set **Fade**, **Slide** or **Scale**,
start time and duration. Slide direction is editable. **Play scene** previews the
scene; its slider deterministically scrubs time; **Resting layout** restores the
editable base pose. Reduced-motion preferences disable playback but permit frame
inspection. Changing scenes or editing cancels playback. Motion is saved in JSON as
`motion_version: 1` and element `animation` metadata; legacy projects remain static.

Start/duration are scene-local seconds, duration 0.1–3 seconds, and entrances must
finish within the scene. Effects are finite, not generated scripts. Video renders
the authored motion; PowerPoint exports editable static resting layouts and notes
explicitly explaining that video animation is not reproduced. Entrance and exit effects apply to text, charts and shapes. Exit tracks must
start after entrance tracks finish. Scene style offers Crossfade and Slide Left
transitions into the following scene, with preview. Video keeps the total timeline
duration unchanged: a transition occupies the beginning of the next scene.
Undo/redo retains up to 12 project snapshots (also bounded to 8 MiB). **Advanced
tracks** edits validated JSON for beats, groups and selected-element pose/path/chunk/
chart-stagger fields; it is not a graphical multitrack sequencer. Paths, group
transforms, semantic text chunks and per-value bar staggering share deterministic
preview/video timing. PPTX stays static and editable; native PowerPoint animation
and loop effects are not implemented. Unsupported timing/effects are rejected.

**Regenerate shot** uses the hosted pipeline from current shot text and its first
chart, constraining both planning and composition to a single replacement for
explicit review. Other scenes are preserved; project changes invalidate the candidate.
It does not preserve all selected shot styling/assets or guarantee continuity.
Undo restores the prior project.

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
  "version": 1,
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

- **Validation**: `src/document.py` is shared by CLI and Studio. Unversioned
  documents migrate to `version: 1`; other versions fail. Studio's scene/time/
  resolution limits do not cap legacy CLI timelines, dimensions or frame rates.
  Shared composition/motion/asset validation rejects malformed inputs before
  rendering; legacy filesystem paths remain a CLI-only feature.
- **Scene types**: `title`, `bullets`, `chart` (bar/line/pie), `image`, `outro`,
  `composition` (native text, chart, shape, icon, embedded image and path elements)
- **Animations**: `fade`, `slide-up`, `zoom-in`, `kenburns` (images)
- **PPTX export**: every render also emits a `.pptx` alongside the MP4 —
  one slide per scene, built from the same artifacts (narration WAVs
  embedded on their slides, chart PNGs, generated images). Open in
  PowerPoint and tweak the deck. Frame composition motion is not reproduced;
  PowerPoint's video output is not a guaranteed match.
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

## Notes

- TTS is skipped gracefully (with a warning) when the selected provider's
  key is unset or the provider fails (quota, network, rejected voice).
- Never commit API keys; pass via environment only.

## Narration providers

The defaults, fallbacks and key guidance below describe the **legacy CLI**, not
Studio's strict `FRAME_TTS_*` path. Provider model names, free tiers, licences,
retirement dates and prices are inherited guidance, not freshly verified public
facts. Confirm current availability and terms with the linked providers before
use; configured readiness is not live capability or cost evidence.

| `TTS_PROVIDER` | Key env var | Output | Default voice / model |
| --- | --- | --- | --- |
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
this change are regenerated once.) Legacy CLI AI image generation uses Mistral;
Studio's optional hosted image stage uses an explicitly configured Google model.

### Getting a Google (Gemini API) key

- Create a key at [Google AI Studio](https://aistudio.google.com/apikey)
  and set `GOOGLE_API_KEY=...`. No credit card is needed for the free tier.
- Gemini TTS models are available on the Gemini API free tier within
  per-project rate limits (requests per minute/day). Check the current
  allowances on the [rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
  page and [pricing](https://ai.google.dev/gemini-api/docs/pricing) page; on
  the free tier, Google may use prompts to improve its products. Image
  generation has separate availability/pricing; verify the selected model's terms.
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

### Representative local-AI briefs

`samples/canvas-ai-briefs.json` contains detailed explainers, a qualified product
pitch, a completed/planned project update, verified numeric data, sparse input and
an adversarial override example. Paste each title/description/key-point set into
Create and select its audience/aspect/motion options. Review source coverage,
sentence relevance, duplication, readability, timing and factual qualifiers before
applying; schema-valid JSON alone is not a quality pass.

Generation infers compact editorial/style choices, not repetitive coordinate JSON.
A validated layout assembler preserves source text and builds canvas geometry and
motion. This remains a constrained source-selection workflow, not free-form design.
Charts, diagrams, shapes and numeric data editing are editor capabilities; these
briefs do not imply that AI automatically creates charts or a full visual design.
Sparse input can still repeat content. Detected override/invented-data instructions
are rejected; this is a narrow guard, not a general semantic-injection guarantee.

The default uses Qwen3.5-0.8B Q4_K_M with thinking disabled and a bounded 4K
context. No vision projector or vision assets are downloaded. Upgrades reuse
checksum-verified runtime files; runtime repairs reuse verified model weights.
Activation replaces the installation atomically and retires old model files only
after the new installation verifies. No silent downgrade or cloud fallback.

Model selection compared SmolLM2-360M, Qwen2.5-0.5B, Qwen3-0.6B, Qwen3.5-0.8B
and LiquidAI LFM2.5-350M. Qwen3.5 scored 6/7 on a bounded source-selection test in
both native CPU and browser WASM runs; Qwen2.5 scored 4/7 native and 2/7 browser.
Q3_K_M saved about 62 MB but scored 5/7 native, so Q4_K_M remains the supported
path. These are small task-specific observations on one Mac, not universal model
quality or device performance guarantees.

### Visual AI composition

Create accepts optional verified chart rows (`label: value`, 2–8 rows). AI can select
column, horizontal, line, area, pie or doughnut designs using only those supplied
values. A brief asking for a graph/chart with verified data requires one chart on
an eligible body scene; charts are not duplicated across every slide. Numbers in
prose are not inferred into data. Negative data cannot select pie/doughnut.

The model also chooses text, accent, rounded-card or arrow treatments and solid,
gradient or grid backgrounds from reviewed layout primitives. It does not generate
arbitrary drawing code. All visuals are editable, use the same motion contract and
are validated before applying. Review visual appropriateness and readability.

### Design and coordinated motion

Frame uses original bounded design primitives inspired by public animation
patterns: exact-time seeking (HyperFrames) and staggered transform-based reveals
(Motion). It does not embed either product's agent, copy paid assets, execute
model-authored scripts or introduce another renderer.

AI can choose editorial, spotlight or split layouts; violet, teal or amber palettes;
reviewed icons; background treatments; and coordinated reveal/rise/focus presets.
Portrait generation avoids split layouts. Charts retain supplied values. Review
text fit and visual relevance—the small model is not a general design agent.

The Icon tool adds editable check, arrow, star, info, target or heart elements.
Geometry is shared between SVG preview, Pillow video frames and editable native
PowerPoint paths. Scene animation presets coordinate entrances/exits without
changing resting positions. Select an element to customise its motion afterwards.
Supplied bitmap images, word/character/chunk text reveals and chart growth are
supported. Hosted concept images are explicit opt-in, never an implicit local-mode
service. Bar staggering sequences supplied values; this is not arbitrary multi-series
chart authoring.

### Word and chart reveals

Text can reveal word by word while reserving its complete final layout; seeking
backwards does not rewrite its content. Wipe entrances reveal text, charts, shapes
or icons from left to right without replacing their resting geometry. A chart wipe
reveals the entire graphic (including labels), not interpolated invented values.
Both effects are entrance-only; existing fade/slide/scale exits remain available.

Use **Text + chart reveals** to apply coordinated words/wipes to a scene. The
**Timing** panel lists entrance/exit tracks with time bars; selecting a track opens
its timing controls. Preview and video use the same eased progress and threshold
rules. Editing restores the complete resting pose. PowerPoint remains static and
editable. Browser/Pillow font wrapping may differ, so inspect actual exports.

### Full storyboard preview

**Play project** runs every scene automatically on one master clock, with element
entrances/exits and scene transitions. Pause/resume, Restart, 0.5×/1×/2× speed and
the project scrubber inspect the whole sequence without changing the editing scene.
**Back to editing** removes the preview; edits invalidate it. Reduced motion blocks
autoplay but permits seeking. Background motion is an approximate browser treatment,
not pixel-identical to Pillow's video background implementation; inspect export.
The selection/application stages of AI visuals share one allowed-design contract,
including later scenes after the one permitted chart has already been inserted.

### Content-specific animation

**Draw chart / fill slices** draws a line/area through successive data points with
point-marker arrivals, grows bars from zero, or reveals pie/doughnut wedges through
their supplied shares. Percentages appear when each slice finishes; no values are
invented or rewritten. **Character-by-character reveal** retains the final text
layout and reveals Unicode codepoints, including whitespace, at deterministic times.
It is not grapheme-cluster-aware; complex combined scripts need export inspection.
The story preset now uses characters for text and chart-draw for charts. Both are
entrance-only. Editing/resting mode restores complete content; PPTX stays static.

### Art direction, fonts and supplied images

Create offers three coherent directions: **Studio** (blue ink / sans),
**Editorial** (warm paper / serif), and **Technical** (dark green / mono).
The local model chooses source sentences and hero, poster, split or framed layouts;
host code owns geometry, palette and numeric data. Prompts include scene role,
audience, prior layout and factual constraints. Browser font measurements reject
text that cannot fit at the minimum size rather than silently clipping it.

Add a PNG/JPEG in Create to support opening/body compositions, or use **Image** in
the editor. Assets are embedded in project JSON, not fetched from URLs. Cover crops
centrally; Contain preserves the entire image. Edit fit/description in element
options. Images stay separate movable pictures in PowerPoint, not editable pixels.
Supplied-image editing invokes no image-generation model or stock-photo service;
hosted concept generation is a separate opt-in stage.

Uploads are resampled locally to ≤1600 pixels and must fit 256 KiB encoded raster
bytes per asset. Server validation permits ≤2048 pixels/side, ≤4 million pixels,
2 MiB aggregate image bytes and 3 MiB request/JSON size. SVG, remote paths, animated,
corrupt and MIME-mismatched files are rejected. Storage quota failures advise JSON
export without replacing the last saved copy.

Font choices are offline DejaVu Sans, Serif and Sans Mono, regular/bold, served from
the existing matplotlib installation. Licence: `studio/DEJAVU-LICENSE`. Pillow and
browser use those same families. PowerPoint references the matching font names;
recipients need them installed or their presentation app may substitute fonts.
Complex script shaping and browser/Pillow wrapping are not pixel-identical.

### Variety and motion character

Art directions now include **Minimal, Signal, Botanical, Noir and Cobalt** alongside
Studio, Editorial and Technical. Caption and heading-band layouts extend the layout
kit. Tutorial, comparison and case-study goals provide additional editorial intents;
they preserve the supplied source order rather than inventing new steps/results.
These are original compositions informed by public design-system/editorial patterns,
not downloaded OpenDesign plugins, copied brand assets or an external agent runtime.

The original offline vector library now has 18 symbols, including book, code, shield,
users, cloud, lightbulb, calendar, chart, mail, globe, layers and play. Local generation
selects a relevant symbol or none; both video and editable PPTX use the same primitive
geometry in `studio/vector-library.json` for the new symbols. No SVG import, external
icon CDN or diffusion-image model is required. Icons illustrate concepts, not photos.

Choose Calm, Balanced, Energetic or Cinematic in Create or scene motion presets.
Styles coordinate duration, stagger, element-specific effects, easing and transform
intensity. Individual tracks expose four easing curves and intensity 0–2. Intensity
changes only slide travel/scale amplitude; it does not change text content, chart
values or resting geometry. Reveal timing still follows easing. Short scenes clamp
tracks to preserve non-overlapping entrance/exit timing. Reduced motion still blocks
autoplay. These are bounded deterministic curves, not a spring-physics simulation.

Local generation remains vector/supplied-image-led, without a diffusion download.
Hosted mode can request one concept raster with explicit privacy/cost consent.
Generated concept imagery is not factual photographic evidence.

### Directed sequences (not only animated slides)

Local generation now has a second constrained directing pass **after composition**.
It sees the actual visual targets and chooses a build, spotlight, visual-first or
text-first shot. The compiler creates a timed focal beat, supporting reveal and
reading hold. A visual-first shot is offered only when a chart/image/symbol exists.
This separates editorial layout from temporal storytelling instead of asking the
small model for unrestricted HTML or executable animation code.

Portable `keyframes` on elements describe ordered `{time,x,y,scale,opacity}` poses.
`x/y` are canvas-normalised offsets from resting geometry, not absolute positions.
Tracks contain 2–8 strictly increasing finite times inside the scene, offset bounds
−1…1, scale .5…1.5 and opacity 0…1. Cosine interpolation is deterministic under seek;
offsets add to entrance/exit transforms and opacity/scale multiply. Static PPTX
remains the complete resting composition. Timing lists directed poses and lets you
remove them. Applying a scene preset replaces directed poses as well as entrances.

The HyperFrames examples gallery informed the separation of compositions and timed
blocks (kinetic type, callouts, chart stories), but only its public text catalogue
was inspected—not full video playback. Frame does not reproduce its HTML/GSAP/3D
capabilities. Local generation, hosted candidates and validated imported JSON use
the same portable render contract. The local compiler now infers only consumed
editorial/layout/symbol/design and shot choices; palette/background/effect tokens
are host-owned rather than redundant model decisions.

### Rendered quality and evaluation

Mechanical checks use actual Pillow text wrapping and sample composed element/group
poses at 24 Hz plus authored cues. They report clipping, essential-content overlap
and known-background contrast errors; reading holds and contrast over images,
patterns or partial backgrounds need review. Source IDs and protected-fact checks
are narrow guards, not proof that every paraphrase entails its source. These checks
cannot replace full-film human watching or narrated listening.

For offline corpus evidence, inspect the command first:

```bash
python3 scripts/evaluate_generation.py --help
.venv/bin/python scripts/evaluate_generation.py --output /tmp/frame-eval
# Optional: add --spec /path/to/candidate.json (repeatable)
```

Choose a new/empty output directory outside this repository. Outputs are silent
full-film `film.mp4`, editable PPTX, scene PNGs, evidence JSON and `report.json`.
The harness uses 6 fps at the smallest supported matching aspect ratio, not
production-quality exports. Imported specs lack original-brief fidelity checks.
It does not read `.env` or call providers. Implementation is present but verification
is partial: live providers were not called and full human watch/listen review is
not complete. See [generation design](docs/generation-design.md) for the contract
and remaining release gates.
