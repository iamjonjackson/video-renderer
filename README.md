# video-renderer

Declarative video generation pipeline: describe scenes in a JSON spec, get an
MP4 with animated visuals and text-to-speech voiceover from Mistral (Voxtral),
Google (Gemini TTS) or ElevenLabs.

## How it works

1. You provide a **spec** (JSON) — a timeline of scenes with text, charts,
   images, and optional narration.
2. The renderer synthesizes narration per scene via the selected TTS provider,
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

cp .env.example .env     # then edit .env and add the key for your TTS provider
set -a; source .env; set +a   # load env vars (or use dotenv in your shell)

# Final videos go to ./output, intermediate render files to ./temp
python3 src/render.py samples/sample-spec.json -o output/demo.mp4
```

Notes:
- `.env` is gitignored; `.env.example` documents the variables.
- `output/` (final videos) and `temp/` (TTS/image caches, intermediate
  artifacts) are gitignored except their `.gitkeep` placeholders.
- Without the selected TTS provider's key, scenes render silently with a
  warning; without `MISTRAL_API_KEY`, AI image blocks are skipped with a
  warning — the pipeline never hard-fails on missing AI.
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
- **Voice**: see [Narration providers](#narration-providers). For Mistral,
  built-in voice slugs (list via `GET /v1/audio/voices`) or a cloned
  `voice_id` from a 2–3s audio sample.
- Full contract: `src/schema.json` (JSON Schema).

See `samples/sample-spec.json` for a complete example.

## Files

- `src/render.py` — spec → MP4 renderer (MoviePy + Matplotlib)
- `src/tts.py` — TTS provider dispatch + Mistral Voxtral client (`/v1/audio/speech`)
- `src/tts_google.py` — Google Gemini TTS client (PCM wrapped into WAV)
- `src/tts_elevenlabs.py` — ElevenLabs TTS client (MP3)
- `src/schema.json` — JSON Schema for the spec
- `src/themes/presets.py` — dark/light color presets
- `demos/` — rendered example videos from `samples/sample-spec.json`

## Notes

- TTS is skipped gracefully (with a warning) when the selected provider's
  API key is unset or the provider request fails.
- Never commit API keys; pass via environment only.

## Narration providers

Narration can come from one of three TTS providers. Pick one with the
`TTS_PROVIDER` environment variable, or per spec with `"voice": {"provider": "..."}`
(the spec setting wins). If neither is set, Mistral is used.

| Provider | `TTS_PROVIDER` | Key env var | Free tier | Output |
|---|---|---|---|---|
| Mistral Voxtral | `mistral` (default) | `MISTRAL_API_KEY` | No | WAV/MP3 |
| Google Gemini TTS | `google` | `GOOGLE_API_KEY` | Yes, within rate limits | WAV |
| ElevenLabs | `elevenlabs` | `ELEVENLABS_API_KEY` | Yes, non-commercial | MP3 |

```bash
# .env
TTS_PROVIDER=google
GOOGLE_API_KEY=...
```

Spec example (voice settings apply only to the provider they name):

```json
"voice": { "provider": "google", "slug": "Charon" }
```

If a spec's `voice` block has no `provider` (as in the samples), its `slug`,
`voice_id` and `model` are treated as Mistral settings and ignored when
`TTS_PROVIDER` selects another provider, which then uses its own default voice.

Narration clips are cached in the work directory under names that include the
provider, voice and model, so switching provider generates new audio instead of
reusing another provider's clips.

### Getting a Google (Gemini) API key

1. Sign in at [Google AI Studio](https://aistudio.google.com/) and choose
   **Get API key** → **Create API key**. No credit card is needed.
2. Add it to your `.env`: `GOOGLE_API_KEY=...`

- Gemini TTS models are free of charge within per-project rate limits; if you
  hit a `429` error, wait a minute and retry. Image generation is **not** on the
  free tier, so AI image blocks still need `MISTRAL_API_KEY`.
- Default model `gemini-2.5-flash-preview-tts`, default voice `Kore`. Preview
  model names change, so override with `GOOGLE_TTS_MODEL` if Google renames it.
- Optional: `GOOGLE_TTS_VOICE` (e.g. `Charon`, `Puck`) and `GOOGLE_TTS_STYLE`
  (the spoken-style prompt, default *"Read aloud in a neutral, warm narration
  voice"*). The spec's `voice.slug` sets the voice per spec.

### Getting an ElevenLabs API key

1. Sign up at [elevenlabs.io](https://elevenlabs.io/) and open **Developers** →
   **API Keys** → **Create API Key**. Give it access to **Text to Speech** and
   **Voices** (read).
2. Add it to your `.env`: `ELEVENLABS_API_KEY=...`

- The free tier gives about **10,000 credits a month (roughly 10 minutes of
  audio)** with API access.
- **Free-tier audio is for non-commercial use only and requires attribution to
  ElevenLabs.** Fine for coursework, hackathons and demos; do not use it for
  monetized output. Credit ElevenLabs (for example "Voice by ElevenLabs") in the
  video or its description, and check the current terms on
  [elevenlabs.io](https://elevenlabs.io/) before publishing.
- With no voice set, the first built-in "premade" voice from `/v1/voices` is
  used. To choose one, copy a voice ID from the Voices page into
  `ELEVENLABS_VOICE_ID`, or set it per spec with `voice.voice_id`.
- Optional: `ELEVENLABS_MODEL` (default `eleven_multilingual_v2`).

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
3. **Build and test** — render the sample: `python3 src/render.py samples/sample-spec.json -o output/demo.mp4` (add your own TTS key, e.g. `MISTRAL_API_KEY`, in your fork under Settings → Secrets → Actions to run CI)
4. **Commit with co-author trailers** so teammates get credit: `Co-authored-by: Name <name@example.com>` (See `.github/PULL_REQUEST_TEMPLATE.md` for instructions)
5. **Push your branch and open a PR** (`gh pr create`, or the web UI's Contribute button), referencing the issue (`Closes #N`) and attaching screenshot/video evidence as per the PR template

> CI runs on PRs but without access to repo secrets — test locally or in your fork with your own TTS provider key if your change touches TTS or image generation.
