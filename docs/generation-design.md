# Frame generation and motion-quality design

Status: implemented in current working source; verification is partial. No live
provider calls or full human watch/listen review establish release quality yet.
Audience: maintainers changing generation, document or rendering contracts.
Decision authority: repository owner. This document is not permission to transmit
private briefs, inspect credentials, download models or make paid requests.

## Outcome and architecture

Produce an editable, source-grounded film with purposeful composition, reveals,
reading holds and continuity—not raster slides or executable model-authored code.

```text
brief + source IDs + verified data + approved asset
  -> grounded narrative / shot plan
  -> typed composition / timeline document
  -> shared validation + mechanical render checks
  -> optional concept image / rendered critique / one repair
  -> staged candidate -> human review / explicit apply
  -> optional strict audio preparation -> credential-free MP4 / static PPTX
```

One server-owned coordinator owns hosted jobs. Local browser generation is a
separate explicit mode; neither mode silently switches providers. Provider/model
configuration and consent are capability-specific. ElevenLabs supports narration,
not storyboard planning or images. Existing MoviePy/Pillow and native PPTX export
remain the production paths; browser preview is approximate.

## Implemented document and editor contract

- `src/document.py:validate_spec` is shared by CLI loading and Studio. Unversioned
  documents migrate non-destructively to top-level `version: 1`; other versions
  fail. Studio retains 12 scenes, 60 seconds, 1–15 seconds per scene, 16 elements,
  supported resolutions and 24/30 fps. Legacy CLI retains longer timelines,
  positive frame rates/dimensions and legacy image settings; Studio's envelope
  is not imposed on CLI. Composition, asset and motion checks are shared.
- Canvas elements support text, chart, shape, icon, embedded raster and path.
  Rich motion adds polyline tracing, group transforms, semantic text chunks and
  per-value bar staggering. Groups and elements have bounded pose tracks;
  scene-local offsets add to entrances, scale/opacity multiply, and cosine pose
  interpolation remains deterministic under seeking. Compatible repeated IDs
  across adjacent hosted shots can compile a position handoff; this is not a
  general object-morphing engine.
- **Advanced tracks** exposes validated JSON for beats, groups and selected-element
  keyframes, membership, path points/stroke, chunks and chart stagger. It is not a
  graphical sequencer. Undo/redo keeps up to 12 snapshots, also capped at 8 MiB.
- **Regenerate shot** uses current visible text and the first chart as a fresh
  hosted brief. A dedicated single-shot request constrains both planning and
  composition to one replacement for review. Other scenes are
  preserved; stale project state invalidates application. Selected-shot assets,
  all styles, full original source context and cross-shot continuity are not
  guaranteed. Undo restores the prior project.
- The local Qwen compiler infers consumed sentence/layout/symbol/design and shot
  choices. Palette/background/effect decisions overwritten by host compilation
  were removed. It remains constrained source selection, not unrestricted design.
- PPTX is static resting content with editable native objects and separate images.
  It does not reproduce video motion. Fonts, complex-script shaping and browser/
  Pillow wrapping can differ; inspect actual exports.

## Implemented hosted generation contract

`src/generation.py` coordinates Google and Mistral structured-output adapters in
`src/generation_provider.py`. Server configuration is `FRAME_GOOGLE_MODEL` with
`GOOGLE_API_KEY` (or `GEMINI_API_KEY`), and/or `FRAME_MISTRAL_MODEL` with
`MISTRAL_API_KEY`. No text model is implicitly chosen. Readiness discloses configured
identity, not keys, and does not prove account/model capability or pricing.

Input is bounded: title 1–100 characters, description 20–3000, at most six
180-character points, validated chart rows and embedded asset metadata. Source IDs
trace claims; charts must retain supplied values. Hosted paraphrases are allowed,
but source membership and protected-fact checks do not prove semantic entailment.
Human factual review remains necessary; numbers in prose are not inferred datasets.

A job requires disclosure/charge consent and allows 2–5 calls: planning and
composition, optionally one Google concept image, one advisory vision critique and
one repair after critique. Structured calls request at most 16,384 output tokens;
the coordinator checks a four-minute deadline. These bounds are **not a monetary
cap or cost guarantee**. Provider rates, input tokens and submitted remote work
still determine charges. There is no automatic fallback or unbounded retry loop.

Optional images require Google mode, `FRAME_GOOGLE_IMAGE_MODEL`, explicit consent
and no supplied asset. The server owns the opening asset slot, decodes/limits the
returned raster and labels it concept imagery, not factual evidence. Models cannot
provide URLs, executable HTML/JS or filesystem paths. Critique sends up to three
approved rendered contact frames and requires a vision-capable model/account;
one authorised repair is revalidated and remains advisory, never automatic approval.

Safe client failures omit provider bodies/credentials. Cancellation rejects late
results and stops local processing; it cannot cancel/refund an already submitted
remote request. Candidates never overwrite the project automatically. Brief edits
invalidate client candidates. In-memory caches retain eight structured stages and
two complete candidates; identity includes request/source/asset content, provider,
model and prompt/schema versions (complete candidates also include image identity).
Coordinator close clears caches and cancels work. There is no persistent cloud cache
or automatic publication.

## Implemented strict narration handoff

Studio defaults to silent export. Narrated export requires separate consent plus
exact server `FRAME_TTS_PROVIDER`, `FRAME_TTS_MODEL` and `FRAME_TTS_VOICE` settings
and the selected provider key. Supported providers are Google, Mistral and
ElevenLabs. `src/narration.py` makes up to 12 separate requests, one per narrated
scene, with no retries or alternate provider/model/voice. It does not read `.env`.
The legacy CLI's documented fallback/silence behaviour remains separate.

Every Studio scene needs authored narration or a transcript derived from visible
text. Preparation decodes audio, measures duration, validates captions and publishes
only a complete server-owned manifest. An explicit scene duration shorter than its
audio fails rather than trimming speech; otherwise explicit timing is preserved.
Without explicit timing the preparation helper uses audio duration plus padding.
Missing/corrupt required audio fails, never successful silent narrated output.
Credential-free rendering consumes controlled local audio paths for MP4/PPTX.

SRT cues contain the whole scene transcript over its audio interval: **not word-
aligned captions**. Review pronunciation, transcript and timing. Cancellation stops
local preparation and discards incomplete artifacts, but an in-flight paid request
may still be charged. A cancelled request is not a free attempt; any new paid
attempt needs consent again.

## Mechanical quality and remaining human gates

`src/quality.py` uses actual Pillow text layout/wrapping and composed group/element
poses sampled at 24 Hz plus authored pose, entrance/exit and chunk boundaries.
Errors include clipping, unbreakable text, essential-content overlap and insufficient
contrast on known backgrounds. Reading holds and contrast over image/pattern/partial
backgrounds are warnings. Samples can miss between-sample failures and do not prove
factual fulfilment, meaningful movement, pacing or aesthetic quality.

Acceptance requires reviewing protected names/numbers/qualifiers/status, required
source coverage and unchanged datasets; watching complete films for legibility,
reading holds, purposeful movement and continuity; checking static PPTX content;
and listening completely to narrated cases with caption/transcript correction.
Neither schema validity nor a model critique is a numerical taste or release gate.

## Offline evaluation and progress

Inspect usage before rendering:

```bash
python3 scripts/evaluate_generation.py --help
.venv/bin/python scripts/evaluate_generation.py --output /tmp/frame-eval
# Add --spec /path/to/candidate.json repeatedly for imported candidates.
```

`--output` must name a new/empty directory outside the repository. The harness reads
`samples/canvas-ai-briefs.json` and `samples/generation-evaluation.json`, makes no
provider calls and does not read `.env`. Each case emits a silent full-film
`film.mp4`, editable PPTX, scene PNGs and evidence JSON; `report.json` records
mechanical checks and rejection probes. Copies preserve scene durations/transitions
but use 6 fps at the smallest supported matching aspect ratio. This is offline
fixture evidence, not production export quality or a local/hosted model comparison.
Imported specs require their original brief/source bundle for factual evaluation.

Contract hygiene, hosted adapters/coordinator, richer editor tracks, optional
image/critique/repair, strict narration and mechanical/corpus tooling are implemented.
This documentation update inspected source and ran only CLI `--help`; it did not run
tests, render the corpus, access credentials or call providers. Existing rendered
corpus outputs, where supplied, still require full human viewing and are not live
provider evidence. Live provider comparisons and full human watch/listen acceptance
remain unverified. Do not advertise comprehensive film-quality fulfilment yet.

## Reference and scope limits

Public HyperFrames catalogue: <https://hyperframes.heygen.com/examples>
(public text only, not full playback). OpenDesign: <https://open-design.ai/plugins/>
(inspiration, no imported plugins/brand assets). Frame uses original bounded
primitives, not those products' HTML/GSAP/3D or agent runtime capabilities.

Provider references: <https://ai.google.dev/gemini-api/docs/structured-output> and
<https://docs.mistral.ai/inference/conversations/structured-output/custom>.
Adapter code is the implemented API contract. Public model identities, availability,
free tiers, licences and prices in inherited README guidance were not freshly
verified; consult provider documentation/account terms before selecting identities
or authorising live evaluation. No new current-model claims are inferred here.

Latest hardening disables dotenv loading in credential-free MoviePy children,
including strict audio decoding, so importing the renderer cannot restore keys from
a repository `.env`. A disposable sentinel test inspects actual ffmpeg launches.
