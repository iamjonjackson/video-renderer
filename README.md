# video-renderer

Declarative video generation pipeline: describe scenes in a JSON spec, get an
MP4 with animated visuals, Mistral TTS (Voxtral) voiceover, and optional
background music.

## How it works

1. You provide a **spec** (JSON) — a timeline of scenes with text, charts,
   images, and optional narration.
2. The renderer synthesizes narration per scene via the Mistral TTS API,
   probes each clip's duration, and sizes each scene to its audio
   (audio-driven timeline). Explicit `duration` overrides when you want a
   scene to linger.
3. MoviePy composites the scenes with animations and encodes the final MP4.

## Quick start

```bash
pip install moviepy matplotlib imageio-ffmpeg

export MISTRAL_API_KEY=...   # optional; scenes without narration render silent

python3 src/render.py samples/sample-spec.json -o output/demo.mp4
```

## Spec format (summary)

```json
{
  "meta":  { "fps": 30 },
  "theme": { "preset": "dark", "accent": "#58a6ff" },
  "voice": { "slug": "en_jane_neutral" },
  "music": { "src": "assets/music.mp3", "volume": 0.2 },
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
- **Timing**: omit `duration` and provide `narration` for audio-driven scenes;
  `padding` (default 0.5s) adds breathing room after narration.
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
- TTS pricing: ~$0.016 per 1k characters (Voxtral, `voxtral-mini-tts-2603`).
