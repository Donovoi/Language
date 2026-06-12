# Language Research Pack

- Run id: `initial-language-stack-research`
- Generated: `2026-06-07 23:17:19 UTC`
- Robin checkout: `..\robin`
- Robin checkout detected: `true`
- App goal: Realtime multi-speaker speech-to-English translation with same-voice, same-volume playback and source-voice suppression.

## How To Use This Pack

1. Start Robin from the local checkout and use the open literature backend unless Edison is explicitly configured.
2. For each subsystem below, run Robin against the task and queries, then verify high-impact claims against primary sources.
3. Write an implementation decision record using `docs/research/decision-record-template.md`.
4. Add the smallest disposable benchmark or smoke check before wiring the chosen candidate into runtime code.

Suggested Robin setup:

```powershell
cd ..\robin
docker compose -f docker-compose.search.yml up -d
$env:ROBIN_LITERATURE_BACKEND = "open"
$env:ROBIN_WEB_SEARCH_URL = "http://127.0.0.1:8080/search"
```

Use SearXNG for lead discovery only. The decision record must cite primary papers, official model cards, or official benchmark docs.

## Evidence Standard

### Preferred

- peer-reviewed conference or journal papers
- official benchmark papers
- model cards or official implementation docs for runnable candidates

### Allowed With Label

- arXiv preprints
- technical reports
- vendor model cards
- blog posts used only for lead discovery

### Required For Decision

- at least one primary source per candidate
- explicit latency and hardware assumptions
- known failure modes and detractor concerns
- a disposable benchmark or smoke-test plan

## Detractor Loop

Force every attractive candidate through a skeptic pass before it becomes implementation work.

Required skeptic questions:

- What practical assumption would make this recommendation fail in a real noisy room?
- What part of the result is from a peer-reviewed source, and what part is only a preprint, vendor claim, or demo?
- What latency, hardware, licensing, privacy, or safety constraint could make the option unusable?
- What benchmark would disprove the recommendation quickly and cheaply?
- What fallback should the app use when the candidate fails open?

Minimum detractor output:

- one strongest objection
- one cheapest falsifying benchmark
- one fallback path
- one condition that would reverse the decision

## Seed Primary Sources

These are starting points, not final authority. Refresh them before each decision.

- [Robin: A multi-agent system for automating scientific discovery](https://www.nature.com/articles/s41586-026-10652-y) - peer-reviewed Nature article; use as research-workflow precedent
- [Joint speech and text machine translation for up to 100 languages](https://www.nature.com/articles/s41586-024-08359-z) - peer-reviewed Nature article; SEAMLESSM4T speech translation baseline
- [Streaming Sortformer: Speaker Cache-Based Online Speaker Diarization with Arrival-Time Ordering](https://www.isca-archive.org/interspeech_2025/medennikov25_interspeech.pdf) - Interspeech 2025; streaming diarization seed
- [DIARIST: Streaming Speech Translation with Speaker Diarization](https://www.microsoft.com/en-us/research/uploads/prod/2024/05/ICASSP2024_Translation_and_Diarization.pdf) - ICASSP 2024; streaming speech translation plus diarization seed
- [TIGER: Time-frequency Interleaved Gain Extraction and Reconstruction for Efficient Speech Separation](https://proceedings.iclr.cc/paper_files/paper/2025/hash/af790b7ae573771689438bbcfc5933fe-Abstract-Conference.html) - ICLR 2025; efficient speech separation seed
- [TF-MLPNet: Tiny Real-Time Neural Speech Separation](https://www.isca-archive.org/clarity_2025/itani25_clarity.html) - Clarity 2025; tiny real-time separation seed
- [pyannote.audio 2.1 speaker diarization pipeline: principle, benchmark, and recipe](https://www.isca-archive.org/interspeech_2023/bredin23_interspeech.html) - Interspeech 2023; open diarization toolkit baseline
- [Robust Speech Recognition via Large-Scale Weak Supervision](https://proceedings.mlr.press/v202/radford23a.html) - ICML 2023; Whisper multilingual ASR baseline
- [High fidelity zero shot speaker adaptation in text to speech synthesis with denoising diffusion GAN](https://pubmed.ncbi.nlm.nih.gov/39979408/) - Scientific Reports 2025; zero-shot speaker-adaptive TTS seed
- [SLM-S2ST: A multimodal language model for direct speech-to-speech translation](https://www.microsoft.com/en-us/research/publication/slm-s2st-a-multimodal-language-model-for-direct-speech-to-speech-translation/) - 2025 arXiv preprint; label as unreviewed until venue status changes

## Research Questions

### capture-vad-noise-front-end

- Decision: Choose the live capture, VAD, denoising, and level-estimation front end.
- Implementation surface: future capture service plus crates/audio_core loudness metadata
- Robin task: Find the best current real-time microphone capture, VAD, denoising, and loudness-estimation approach for noisy rooms with multiple speakers and overlapping speech.
- Benchmark fixture: synthetic room clips with calibrated speech/noise levels and at least one live microphone smoke test
- Acceptance gate: Candidate must estimate speech presence and input level without blocking the downstream diarization path.
- Detractor focus: Reject candidates that only work on clean close-talk speech or require calibration too fragile for a moving room.

Queries:

- real-time speech enhancement noise suppression voice activity detection noisy multi speaker rooms 2025 peer reviewed
- streaming VAD speech enhancement real-time factor noisy conversational speech benchmark
- speech loudness normalization dBFS LUFS perceived volume matching real-time speech playback

Metrics:

- real-time factor
- frame latency
- false speech/non-speech rate
- PESQ/STOI or DNSMOS
- input and output dBFS/LUFS error

### overlap-diarization-speaker-tracking

- Decision: Choose the online diarization and speaker-tracking path for overlapping speakers.
- Implementation surface: gateway diarization adapter, proto speaker events, Flutter speaker lanes
- Robin task: Compare streaming diarization methods for overlapping speakers, especially online Sortformer, EEND-family systems, pyannote-derived pipelines, and speaker-attributed ASR options.
- Benchmark fixture: AMI or AliMeeting-style overlapping clips plus a local two-person overlap fixture
- Acceptance gate: Candidate must produce stable speaker ids and overlapping_speaker_ids compatible with the current session contract.
- Detractor focus: Challenge any claim that speaker labels stay stable under overlap, speaker re-entry, unknown speaker count, and low-latency chunks.

Queries:

- streaming speaker diarization overlapping speech Sortformer EEND Interspeech 2025
- online speaker diarization overlapping conversational speech DER JER benchmark
- speaker attributed ASR diarization overlapping speech streaming benchmark

Metrics:

- DER
- JER
- speaker-label stability across chunks
- overlap recall
- latency
- maximum simultaneous speakers

### speech-separation-target-extraction

- Decision: Choose blind separation or target-speaker extraction for overlapping speech before ASR/TTS.
- Implementation surface: future Rust/Python audio separation module and gateway audio metadata
- Robin task: Find efficient speech separation or target-speaker extraction models that can run with low latency and preserve ASR-relevant intelligibility in reverberant noisy rooms.
- Benchmark fixture: LibriCSS/LibriMix-style mixtures plus captured two-speaker local mixtures
- Acceptance gate: Candidate must improve downstream ASR or diarization enough to justify added latency.
- Detractor focus: Treat separation as optional until it proves downstream ASR or diarization gains exceed added artifacts and delay.

Queries:

- real-time neural speech separation overlapping speakers low latency ICLR 2025 TIGER TF-GridNet
- target speaker extraction streaming speech separation real-time benchmark 2025
- tiny real-time neural speech separation hearable devices TF-MLPNet 2025

Metrics:

- SI-SDR improvement
- WER after separation
- real-time factor
- chunk size
- GPU/CPU memory
- artifacts under reverberation

### language-id-asr-translation

- Decision: Choose language identification, streaming ASR, and into-English translation architecture.
- Implementation surface: gateway translation/audio provider adapters and proto detected_language fields
- Robin task: Compare multilingual ASR plus translation approaches for source-language detection and low-latency English output, including Whisper-family, SeamlessM4T, and current streaming speech translation systems.
- Benchmark fixture: FLEURS/CoVoST2 plus local mixed-language room clips
- Acceptance gate: Candidate must expose language confidence and translated text early enough for same-turn playback.
- Detractor focus: Punish models that look strong offline but cannot stream partials, recover from wrong language ID, or handle code-switching.

Queries:

- multilingual streaming ASR language identification speech translation into English benchmark 2025
- Whisper multilingual speech recognition language identification limitations noisy speech peer reviewed
- SeamlessM4T speech to text translation robustness background noise speaker variation Nature 2025

Metrics:

- language-id accuracy
- WER/CER
- BLEU/chrF/COMET
- partial-result latency
- robustness under noise and overlap

### cascade-vs-direct-s2st

- Decision: Decide whether the product runtime should be cascaded ASR+MT+TTS, direct speech-to-speech, or a hybrid.
- Implementation surface: gateway orchestration and future audio stream contracts
- Robin task: Evaluate direct speech-to-speech translation versus cascaded ASR, text translation, and voice-conditioned TTS for a realtime same-voice English playback app.
- Benchmark fixture: one cascaded baseline and one direct/hybrid baseline on identical multilingual room clips
- Acceptance gate: Decision record must justify why the chosen architecture best preserves real-time behavior and same-voice output.
- Detractor focus: Assume direct S2ST demos hide debuggability, voice-clone control, and source-suppression integration costs until proven otherwise.

Queries:

- direct speech to speech translation versus cascaded ASR MT TTS latency quality 2025
- streaming speech translation speaker diarization overlapping speech DiariST ICASSP 2024
- multimodal language model direct speech-to-speech translation streaming vocoder 2025

Metrics:

- end-to-end latency
- translation quality
- voice similarity preservation
- controllability
- failure debuggability
- provider availability

### voice-clone-tts-conversion

- Decision: Choose the same-speaker English output strategy.
- Implementation surface: gateway voice-clone/TTS adapter, translated_audio_stream_id, voice_clone_status
- Robin task: Compare zero-shot voice cloning, voice conversion, and speaker-conditioned TTS for fast English output that matches source speaker identity without unsafe persistence.
- Benchmark fixture: short consented speaker references with generated English prompts and blind similarity scoring
- Acceptance gate: Candidate must support ephemeral references, visible readiness states, and fallback voice behavior.
- Detractor focus: Reject voice cloning paths that cannot prove consent-safe reference handling, bounded latency, and acceptable cross-language speaker similarity.

Queries:

- zero shot voice cloning TTS few seconds reference speaker similarity MOS 2025 peer reviewed
- streaming voice conversion target speaker extraction voice cloning low latency 2025
- speaker adaptive text to speech denoising diffusion GAN zero-shot Scientific Reports 2025

Metrics:

- speaker similarity
- MOS or DNSMOS
- time to first audio
- real-time factor
- reference audio length
- cross-language voice transfer quality

### playback-mixing-volume-matching

- Decision: Choose the translated playback mixer and loudness-matching strategy.
- Implementation surface: crates/audio_core, Flutter playback controls, future platform audio output
- Robin task: Find practical low-latency speech mixing, gain staging, loudness matching, and clipping prevention methods for translated speech playback at the source speaker's perceived volume.
- Benchmark fixture: fixed loudness source clips with translated playback rendered at matching levels
- Acceptance gate: Candidate must map to input_level_dbfs and output_level_dbfs without unstable gain jumps.
- Detractor focus: Challenge perceived-volume claims with clipping, distance changes, whisper/shout extremes, and multi-speaker simultaneous playback.

Queries:

- real-time speech loudness matching dBFS LUFS playback mixer low latency
- speech audio gain normalization clipping prevention conversational playback
- perceived loudness matching speech synthesis original speaker volume

Metrics:

- LUFS or dBFS target error
- clipping rate
- time to first playable frame
- mix intelligibility
- operator override behavior

### source-voice-suppression

- Decision: Choose the original-source suppression or cancellation approach.
- Implementation surface: future DSP module, gateway suppression metadata, Flutter diagnostics
- Robin task: Compare source-voice suppression, echo cancellation, target speech suppression, and translated playback masking approaches for real-time use without corrupting translated output.
- Benchmark fixture: same-room capture/playback loop with known source and translated reference tracks
- Acceptance gate: Candidate must report original_voice_suppression_db and fail open when cancellation is unreliable.
- Detractor focus: Assume single-device source-voice cancellation is physically limited; require a masking/fail-open fallback and hardware assumptions.

Queries:

- real-time speech source suppression target speaker cancellation overlapping speech 2025
- acoustic echo cancellation translated speech playback microphone suppression low latency
- speech enhancement target speech removal source separation cancellation benchmark

Metrics:

- suppression dB
- residual source intelligibility
- translated output distortion
- latency
- feedback and echo robustness

### evaluation-deployment-baseline

- Decision: Choose the end-to-end benchmark suite and target hardware profile.
- Implementation surface: docker/dev, scripts, CI, docs/testing
- Robin task: Define a benchmark suite that measures the whole realtime loop from capture to English playback across overlapping speakers, language changes, volume changes, and noisy rooms.
- Benchmark fixture: a versioned local fixture pack plus optional public benchmark subsets
- Acceptance gate: Every provider/model integration must add a disposable smoke check and at least one benchmark fixture.
- Detractor focus: Reject benchmark suites that only measure isolated model quality and ignore end-to-end latency, privacy, source suppression, and degraded-room failure.

Queries:

- benchmark realtime speech translation diarization overlapping speakers latency evaluation
- LibriCSS AMI AliMeeting CHiME FLEURS CoVoST2 speech translation diarization evaluation
- edge deployment speech translation diarization TTS real-time GPU CPU benchmark

Metrics:

- end-to-end latency
- DER/JER
- WER/CER
- BLEU/chrF/COMET
- speaker similarity
- suppression dB
- real-time factor
- memory and power

## Decision Output Checklist

- best option and runner-up
- why this app's constraints favor the selected option
- peer-reviewed or primary-source evidence table
- preprints and vendor claims clearly labeled
- benchmark command, fixture, and disposable environment notes
- rollback or fallback behavior
- contract fields affected in `proto/session.proto`
