# video-renderer

Declarative video generation pipeline: describe scenes in a JSON spec, get an
MP4 with animated visuals and Mistral TTS (Voxtral) voiceover.

## How it works

1. You provide a **spec** (JSON) — a timeline of scenes with text, charts,
   images, and optional narration.
2. The renderer synthesizes narration per scene via the selected TTS API,
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
- Narration defaults to Mistral. Missing credentials or provider failures
  leave silent scenes with a warning. AI images still use `MISTRAL_API_KEY`,
  independently of the narration provider.
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
- **Voice**: Mistral voice slugs or a cloned `voice_id`; alternative providers
  have their own voice settings described below.
- Full contract: `src/schema.json` (JSON Schema).

See `samples/sample-spec.json` for a complete example.

## Files

- `src/render.py` — spec → MP4 renderer (MoviePy + Matplotlib)
- `src/tts.py` — narration dispatch, audio validation, and Mistral REST client
- `src/tts_google.py` — Gemini TTS adapter
- `src/tts_elevenlabs.py` — ElevenLabs TTS adapter
- `src/schema.json` — JSON Schema for the spec
- `src/themes/presets.py` — dark/light color presets
- `demos/` — rendered example videos from `samples/sample-spec.json`

## Notes

- TTS is skipped gracefully (with a warning) when the selected provider's
  key is missing or its request fails.
- Never commit API keys; pass via environment only.

### Getting a Mistral API key

Students: request a key from your hackathon organiser.

- Free API access is not currently available from Mistral but the Pro (Education) option is very affordable if you wanted to sign up at [console.mistral.ai](https://console.mistral.ai)
- If you have a paid account, you can create a key under **API Keys**, copy it into your `.env`:
   `MISTRAL_API_KEY=...`
- Rate limits and model availability depend on your tier — see the
   **Limits** page in the console for your current allowances

### Choosing a narration provider

Set `TTS_PROVIDER` to `mistral` (the default), `google`, or `elevenlabs`.
Credentials are read from environment variables, like the existing Mistral
key. The renderer does not load `.env` automatically; after editing it, use
`set -a; source .env; set +a` as shown above.

```bash
TTS_PROVIDER=google python3 src/render.py samples/sample-spec.json -o output/google.mp4
TTS_PROVIDER=elevenlabs python3 src/render.py samples/sample-spec.json -o output/elevenlabs.mp4
```

Existing `voice.slug`, `voice.voice_id`, `voice.model`, and `voice.format`
continue to configure Mistral. Alternative settings live under `voice.google`
and `voice.elevenlabs`, so switching providers also works with existing specs
that contain Mistral-specific voice names. These blocks are optional:

```json
"voice": {
  "slug": "gb_jane_neutral",
  "google": {
    "slug": "Kore",
    "model": "gemini-2.5-flash-preview-tts",
    "style": "Read aloud in a neutral, warm narration voice"
  },
  "elevenlabs": {
    "model": "eleven_multilingual_v2",
    "format": "mp3"
  }
}
```

Google uses `GOOGLE_API_KEY`, created in [Google AI Studio](https://aistudio.google.com/apikey).
The default Gemini 2.5 Flash Preview TTS model is listed as free of charge on
the [Gemini pricing page](https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash-preview-tts),
subject to [per-project rate limits](https://ai.google.dev/gemini-api/docs/rate-limits).
A free-tier project does not require upgrading to paid billing; availability
and quotas depend on the project and region. Check its current limits in AI
Studio. This is the Gemini Developer API, not Google Cloud Text-to-Speech.
The adapter defaults to the `Kore` voice, accepts a style prompt, and wraps
24 kHz, 16-bit mono PCM in a proper WAV header. Google output is WAV only.
Models returning a complete WAV are also supported. See Google's
[TTS guide](https://ai.google.dev/gemini-api/docs/generate-content/speech-generation)
for voices and supported models. This adapter covers narration only, not
Google image generation or any image pricing.

ElevenLabs uses `ELEVENLABS_API_KEY`, created in the dashboard's
[API keys settings](https://elevenlabs.io/app/settings/api-keys).
The [free plan](https://elevenlabs.io/pricing) includes 10,000 credits per
month, roughly 10 minutes depending on the model and text. It has API access,
but **no commercial license**. When publishing free-plan narration,
ElevenLabs currently requires `elevenlabs.io` or `11.ai` in the title; see its
[publishing and attribution rules](https://elevenlabs.io/docs/help-center/legal/can-i-publish-the-content-i-generate-on-the-platform).
The adapter lists the account's built-in (`premade`) voices and selects one
by name, rather than choosing a paid library voice. Enable **Voices: Read**
as well as **Text to Speech** on the key when using automatic selection.
The lookup is reused for the rest of the process. An explicit
`voice.elevenlabs.voice_id` or `ELEVENLABS_VOICE_ID` skips this lookup;
the spec setting takes priority. The selected ID is included in the audio
cache key. See the [voices API](https://elevenlabs.io/docs/api-reference/voices/search).
If the account has no built-in voices, select another voice that the account
can use through the API. Library voices may require a paid plan even when
they are available in the website's free voice library.
MP3 output is saved directly. Optional WAV output wraps the free-tier
24 kHz PCM response, avoiding the paid-only 44.1 kHz PCM option. See the
[speech API format options](https://elevenlabs.io/docs/api-reference/text-to-speech/convert).

Narration caches now include the provider, voice, model, style, output
format, and text. Switching providers or voice settings creates fresh audio;
unchanged settings reuse it without speech generation calls. Automatic
ElevenLabs voice selection makes one metadata lookup per process; an explicit
voice ID skips that lookup. Old text-only cache files
are not reused because their voice and provider cannot be verified, so the
first render after this update synthesizes narration again. Failed requests
and invalid audio are not saved as usable cache files. A failed provider
leaves a silent scene; it does not silently switch to another provider.
Image generation continues to use Mistral and its existing cache.

### Testing narration

Run the quota-free tests:

```bash
python3 -m unittest discover -s tests -v
```

To make one short live request after loading the appropriate key:

```bash
TTS_PROVIDER=google python3 scripts/check_tts.py
TTS_PROVIDER=elevenlabs python3 scripts/check_tts.py
# optional explicit voice instead of automatic account selection
TTS_PROVIDER=elevenlabs ELEVENLABS_VOICE_ID=your_voice_id python3 scripts/check_tts.py
```

Each command uses a short sentence, validates the audio with MoviePy, and
writes a provider-named file under `output/`. Listen to the audio to check
the actual narration, then attach screenshot/video evidence to the PR.
The automated tests mock API responses; they do not verify account access,
live quotas, or the spoken content returned by a real provider.

## Contributing

Work happens on a branch in your fork **first**; the PR comes last.

1. **Fork** the repo, clone your fork, and create a branch: `git checkout -b your-feature`
2. **Pick an open issue** — issues are not exclusive; multiple teams may work the same one
3. **Build and test** — render the sample: `python3 src/render.py samples/sample-spec.json -o output/demo.mp4` (add your own `MISTRAL_API_KEY` in your fork under Settings → Secrets → Actions to run CI)
4. **Commit with co-author trailers** so teammates get credit: `Co-authored-by: Name <name@example.com>` (See `.github/PULL_REQUEST_TEMPLATE.md` for instructions)
5. **Push your branch and open a PR** (`gh pr create`, or the web UI's Contribute button), referencing the issue (`Closes #N`) and attaching screenshot/video evidence as per the PR template

> CI runs on PRs but without access to repo secrets — test locally or in your fork with your own `MISTRAL_API_KEY` if your change touches TTS or image generation.
