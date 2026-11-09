# video-renderer

Declarative video generation pipeline: describe scenes in a JSON spec, get an
MP4 with animated visuals and TTS voiceover. Mistral Voxtral is the default;
Google Gemini TTS, ElevenLabs, and fal.ai endpoints are also supported (see
[TTS providers](#tts-providers)).

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
- **Voice**: provider-specific. Mistral accepts built-in voice slugs
  (`GET /v1/audio/voices`) or a cloned `voice_id`; Google uses voice names
  such as `Kore`; ElevenLabs uses voice IDs; fal uses its endpoint's voice
  name. See [TTS providers](#tts-providers).
- Full contract: `src/schema.json` (JSON Schema).

See `samples/sample-spec.json` for a complete example.

## TTS providers

Narration defaults to Mistral Voxtral. Choose a provider with `voice.provider`,
`meta.tts.provider`, or `TTS_PROVIDER`.

| Provider | Key | Notes |
|---|---|---|
| `mistral` | `MISTRAL_API_KEY` | default; voice slug or cloned `voice_id` |
| `google` | `GOOGLE_API_KEY` | Gemini 3.8 Flash TTS (Interactions API), WAV; voice name (`Kore`); `voice.model` override |
| `elevenlabs` | `ELEVENLABS_API_KEY` | free: 10k credits/month, non-commercial + attribution, MP3; WAV/PCM requires Pro; default voice Sarah |
| `fal` | `FAL_KEY` | fal TTS endpoint in `voice.model` (default `fal-ai/elevenlabs/tts/eleven-v3`) |

Voice precedence: `voice.*` > `meta.tts.*` > env (`MISTRAL_VOICE`,
`GOOGLE_VOICE`, `ELEVENLABS_VOICE_ID`, `FAL_VOICE`) > provider default.
`voice.strict: true` disables defaults/fallbacks and fails instead of
substituting another voice. Cache keys include provider, voice, model, style,
format, and strict. Missing keys or API failures show a warning and render that
scene silently. Put keys in `.env` (gitignored) — never commit them.
Keys: [Mistral](https://console.mistral.ai), [Google AI Studio](https://aistudio.google.com/apikey), [ElevenLabs](https://elevenlabs.io/app/settings/api-keys), [fal](https://fal.ai/dashboard/keys).

```json
{ "voice": { "provider": "google", "slug": "Kore", "strict": true } }
```

### Direct TTS CLI

Synthesize a single clip without rendering a video:

```bash
python src/tts_cli.py --provider google --text "Hello from Gemini." \
  --output temp/gemini.wav --voice Kore --strict
```

`--provider` defaults to `TTS_PROVIDER` (Mistral if unset). `--output`
defaults to `output/tts.<format>`; a missing extension is added, and a
mismatched one is rejected. Use `--format mp3|wav` where supported and
`--list-providers` to print the choices.

## Files

- `src/render.py` — spec → MP4 renderer (MoviePy + Matplotlib)
- `src/tts_cli.py` — one-shot TTS CLI (provider / text / output)
- `src/tts.py` — TTS provider dispatch + Mistral/Google/ElevenLabs/fal adapters
- `src/schema.json` — JSON Schema for the spec
- `src/themes/presets.py` — dark/light color presets
- `demos/` — rendered example videos from `samples/sample-spec.json`

## Notes

- TTS is skipped gracefully (with a warning) when the selected provider's
  key is unset or its API fails.
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
