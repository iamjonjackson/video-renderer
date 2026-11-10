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
- **Bullet timing priority**: per-bullet audio syncing is preferred and takes
  priority whenever `narration_per_bullet` is available. Both the standard
  `samples/sample-spec.json` and `samples/bullet-sync-spec.json` use this mode.
  Stagger is the fallback for silent scenes, single-clip narration, or missing
  audio. A single narration file has no individual bullet start times, so it
  cannot provide exact syncing on its own.
- **Fallback stagger**: single-narration and silent bullet scenes reveal items
  one at a time using `stagger` (default `0.4` seconds). Each item fades in
  over 0.15 seconds without moving, then remains visible until the scene ends.
  For three items with `stagger: 0.4`, starts are 0, 0.4 and 0.8 seconds;
  frames at 0.2, 0.6 and 1.0 seconds show one, two and three items.
  `stagger: 0` starts every bullet together. Negative intervals are rejected.
  This works with both full-width text and left/right spotlight panels.

  ```json
  {
    "type": "bullets",
    "heading": "Key wins",
    "items": ["Revenue increased", "Churn decreased", "New clients joined"],
    "stagger": 0.4,
    "narration": "Revenue increased, churn decreased and new clients joined."
  }
  ```

  Omit `narration` for the same visual pacing without audio. Duration rules
  are unchanged: silent scenes use the existing stagger-based calculation,
  and narrated scenes fit the audio plus padding. Choose a long enough
  `duration` or a smaller `stagger` if the final reveal would fall after the
  scene ends; the renderer does not extend the scene to fit these reveals.
  The standard sample includes a `stagger` value on Key Wins as a fallback;
  it is ignored while that scene's per-bullet narration is available.
- **Narration-timed bullets**: use `narration_per_bullet` with one entry for
  each item. Each bullet starts a short 0.15s fade when its own narration
  clip starts, then stays visible. Offsets use cumulative decoded audio
  durations, including when WAV or MP3 files come from the cache. `stagger`
  does not control these reveals. Left alignment and the default 1.0s tail
  padding are retained; an explicit `duration` can extend the scene.

  ```json
  {
    "type": "bullets",
    "heading": "Key wins",
    "items": ["Revenue increased", "Churn decreased", "New clients joined"],
    "narration_per_bullet": [
      "Revenue increased this quarter.",
      "Churn decreased compared with the previous quarter.",
      "Two new clients joined the platform."
    ]
  }
  ```

  If the audio clips last 2, 3, and 4 seconds, the bullets appear at scene
  offsets 0, 2, and 5 seconds, and the scene lasts at least 10 seconds with
  default padding. The render log prints the absolute bullet start times
  in the final video. `narration_per_bullet` takes precedence over plain
  `narration`, as before. A mismatched number of entries reports an error
  before TTS requests are made.

  Single-`narration` and silent scenes use the fixed stagger described above.
  If the API key is missing, the warning and silent rendering behaviour
  still apply, and bullets fall back to stagger timing. The timed reveals
  are a video feature; PPTX slides still contain the complete bullet list
  with the combined narration track.

  Render the full five-slide quarterly review using a configured TTS key or
  cache. Both **Key Wins** and **Looking Ahead** use three timed bullets;
  the title, chart, image panel and outro are included too:

  ```bash
  python3 src/render.py samples/bullet-sync-spec.json -o output/full-bullet-sync-demo.mp4
  ```

  The existing renderer writes both `output/full-bullet-sync-demo.mp4` and
  `output/full-bullet-sync-demo.pptx`; no separate export script is needed.
  The MP4 contains the timed reveals. The PPTX contains all five slides,
  with the complete bullet lists and their combined narration embedded.
  Editing either file does not update the JSON spec or the other output.

  Play the MP4 and compare each reveal with the narration and logged start
  times. Pause just before and after a start time for screenshot evidence.
  An empty cache needs eight TTS requests and optional image generation;
  unchanged cached assets are reused on later runs.

  Run the automated checks without API calls:

  ```bash
  python3 -m unittest discover -s tests -p 'test_bullet_sync.py' -v
  ```

  Tests use unequal WAV/MP3 clip lengths, check visible bullet rows at
  offsets ±0.2s, compare the last audible sample with the video end, and
  cover normal/long-video rendering, caching, missing keys, alignment,
  single bullets, explicit durations, fixed stagger intervals, zero stagger,
  invalid intervals and both spotlight layouts.
- **Voice**: built-in voice slugs (list via `GET /v1/audio/voices`) or a
  cloned `voice_id` from a 2–3s audio sample.
- Full contract: `src/schema.json` (JSON Schema).

See `samples/sample-spec.json` for a complete example.

## Files

- `src/render.py` — spec → MP4 renderer (MoviePy + Matplotlib)
- `src/tts.py` — Mistral Voxtral TTS REST client (`/v1/audio/speech`)
- `src/schema.json` — JSON Schema for the spec
- `src/themes/presets.py` — dark/light color presets
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
