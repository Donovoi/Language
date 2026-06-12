# Online Diarization And Separation

- Decision id: RDR-0001
- Date: 2026-06-08
- Owner/agent: Codex research gate
- Subsystem: overlapping-speaker diarization and speech separation
- Implementation surface: gateway diarization adapter, future audio separation module, `proto/session.proto` speaker metadata

## Product Constraint

The app needs stable speaker identities during live overlapping speech, plus enough overlap metadata
to drive translation, same-voice output, and source suppression. Separation is valuable only if it
improves downstream ASR/translation without adding unacceptable latency or artifacts.

## Options Considered

| Option | Evidence status | Runtime fit | Main concern |
| --- | --- | --- | --- |
| NVIDIA Streaming Sortformer 4spk v2.1 | Interspeech 2025 plus NVIDIA model card/docs | Best first online diarization benchmark | GPU/vendor stack, 4-speaker ceiling, needs local benchmark |
| pyannote.audio 3.1/community pipeline | Interspeech 2023 toolkit baseline plus HF model card | Best open baseline and offline/dev comparator | Gated model access and not truly streaming-first |
| EEND-VC plus TS-VAD refinement | CHiME-8/DASR research pattern | Strong benchmark path for complex meetings | More complex than a first adapter |
| VoiceFilter-Lite / 3S-TSE target extraction | Peer-reviewed/preprint target extraction work | Better realtime fit than always-on blind separation | Needs speaker enrollment or array assumptions |
| WeSep / enrollment-conditioned TSE | Interspeech 2024 toolkit plus runnable demo | Best next audio-only target-speaker extraction adapter | Needs longer enrollment clips and local model/license validation |
| Always-on neural separation | ICLR/Clarity 2025 plus LibriCSS/LibriMix benchmarks | High-upside overlap aid and quality ceiling | Can hurt ASR and add latency if used blindly |

## Recommendation

Start with a two-lane diarization plan:

1. Spike NVIDIA Streaming Sortformer 4spk v2.1 as the online diarization candidate.
2. Keep pyannote as a dev/offline baseline for regression comparison.
3. Benchmark target-speaker extraction and separation only on overlapped or locked/priority-speaker windows.
4. Bypass separation for non-overlap speech to preserve latency and avoid artifacts.

Do not make separation mandatory in the first live prototype. Use it as an overlap-triggered
experiment until it proves it improves ASR or speaker tracking enough to justify its delay.
Diarization answers "who spoke when"; it does not produce clean per-speaker audio.

## Evidence

| Ref | Source | Status | Key result | Link |
| --- | --- | --- | --- | --- |
| R1 | Streaming Sortformer | Interspeech 2025 | Uses speaker cache and arrival-time ordering for online diarization. | https://www.isca-archive.org/interspeech_2025/medennikov25_interspeech.pdf |
| R2 | NVIDIA NeMo docs | Official docs | Supports offline and online Sortformer; online uses small overlapping chunks and AOSC. | https://docs.nvidia.com/nemo/speech/nightly/asr/speaker_diarization/models.html |
| R3 | NVIDIA NeMo Curator | Official docs | Streaming Sortformer stage targets online workloads and a 4-speaker model. | https://docs.nvidia.com/nemo/curator/latest/curate-audio/process-data/quality-filtering/speaker-separation |
| R4 | NVIDIA Streaming Sortformer model card | Official model card | Low-latency config reports 1.04s input-buffer latency and 4 output speakers. | https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1 |
| R5 | pyannote.audio 2.1 | Interspeech 2023 | Open toolkit pipeline with segmentation, embeddings, clustering, and reproducible recipe. | https://www.isca-archive.org/interspeech_2023/bredin23_interspeech.html |
| R6 | pyannote Community-1 | Official model card | Useful current baseline with public benchmark reporting. | https://huggingface.co/pyannote-community/speaker-diarization-community-1 |
| R7 | CHiME-8 DASR | Challenge paper/preprint | Benchmarks joint distant ASR and diarization across diverse multi-speaker settings. | https://arxiv.org/abs/2407.16447 |
| R8 | CHiME-7/8 review | Review/preprint | Best systems still rely on diarization refinement; neural SSE remains unreliable in complex setups. | https://arxiv.org/abs/2507.18161 |
| R9 | VoiceFilter-Lite | Interspeech 2020/preprint | Streaming targeted voice separation for on-device ASR. | https://arxiv.org/abs/2009.04323 |
| R10 | 3S-TSE | arXiv/preprint | Efficient target-speaker extraction for real-time and low-resource use. | https://arxiv.org/abs/2312.10979 |
| R11 | TIGER | ICLR 2025 | Efficient speech separation with lower parameters/MACs than TF-GridNet on EchoSet. | https://proceedings.iclr.cc/paper_files/paper/2025/hash/af790b7ae573771689438bbcfc5933fe-Abstract-Conference.html |
| R12 | TF-MLPNet | Clarity 2025 | Tiny real-time speech separation on low-power hardware. | https://www.isca-archive.org/clarity_2025/itani25_clarity.html |
| R13 | LibriCSS | Dataset paper/preprint | Continuous partially overlapped speech dataset with ASR-oriented evaluation. | https://arxiv.org/abs/2001.11482 |
| R14 | LibriMix | Dataset paper/preprint | Two- and three-speaker mixtures with noisy and sparse-overlap variants. | https://arxiv.org/abs/2005.11262 |
| R15 | WeSep | Interspeech 2024 plus public toolkit/demo | Practical audio-enrollment API shape: mixture plus enrollment audio to extracted speech. | https://arxiv.org/abs/2409.15799 |
| R16 | ClearerVoice-Studio | Apache-2.0 public toolkit | Strong packaged speech processing stack, but current TSE path is audio-visual or training-oriented. | https://github.com/modelscope/ClearerVoice-Studio |
| R17 | LLaSE-G1 | 2025 public code/model | General speech-enhancement model covering TSE, but with a heavier WavLM/X-Codec stack and instability warning. | https://github.com/Kevin-naticl/LLaSE-G1 |
| R18 | Positive/negative enrollment TSE | NeurIPS 2025 public implementation | Interesting wrong-speaker-cue research direction, but weights/license posture make it research-only for now. | https://github.com/xu-shitong/TSE-through-Positive-Negative-Enroll |

## Metrics And Benchmark

- Primary metric: DER and JER with no skipped overlap
- Secondary metrics: missed-overlap rate, speaker-count error, label-swap rate, WER after separation, target-speaker leakage, voice-clone embedding drift, real-time factor, input-buffer latency
- Dataset or fixture: AMI, AliMeeting, DIHARD3, VoxConverse, NOTSOFAR-1, LibriCSS, LibriMix sparse overlap, and a local two-speaker room fixture
- Disposable command: use `scripts/benchmark_diarization_fixture.py` under the audio-eval container
- Corpus catalog: `fixtures/audio_eval/external_corpora/catalog.json` ranks NOTSOFAR-1, AMI,
  LibriCSS, LibriMix, VoxConverse, and AliMeeting with license/terms posture before download
- Optional baseline adapter: `scripts/run_pyannote_diarization_fixture.py` writes JSONL predictions
  for the same scorer when pyannote dependencies and model access are available
- Optional online-candidate adapter: `scripts/run_sortformer_real_speech_fixture.py` and
  `scripts/run_sortformer_chunked_real_speech_fixture.py` write the same JSONL/report shape through
  the dedicated Sortformer profile
- Stateful online adapter: `scripts/run_sortformer_online_real_speech_fixture.py` uses
  `forward_streaming_step` with model-card low-latency settings and reports input-buffer latency
- Rolling PCM adapter: `scripts/run_sortformer_rolling_real_speech_fixture.py` feeds raw fixture PCM
  in arrival order, extracts features per available input buffer, reuses stateful Sortformer
  stepping, and reports whether future samples entered the model path
- Oracle target-speaker extraction upper bound: `scripts/benchmark_target_speaker_extraction_fixture.py`
  / `make audio-eval-oracle-tse-check` writes per-speaker extracted clips from fixture stems and
  scores target SNR, interferer reduction, level preservation, duration preservation, and hashes
- Mixture-passthrough lower bound: `scripts/benchmark_target_speaker_extraction_fixture.py passthrough-check`
  / `make audio-eval-mixture-passthrough-tse-check` writes the same artifact shape from mixed audio
  and must fail SNR/interferer-reduction gates
- Downstream translation upper bound: `scripts/run_whisper_tse_translation_fixture.py` /
  `make audio-eval-whisper-oracle-tse-translation-check` runs Whisper on rolling oracle-TSE slices
  to compare against the rolling mixed-audio failure before integrating a real separator
- Downstream translation lower bound: `make audio-eval-whisper-mixture-passthrough-tse-translation-check`
  runs Whisper on rolling mixture-passthrough TSE slices and must warn in the same contract
- First real separator spike: `scripts/run_speechbrain_sepformer_tse_fixture.py` /
  `make audio-eval-speechbrain-sepformer-check` runs SpeechBrain SepFormer WHAMR as a blind
  separator, writes the same TSE JSONL, and compares it with the mixture-passthrough lower bound
- External separator downstream bridge: `scripts/run_whisper_tse_translation_fixture.py --tse-mode external`
  / `make audio-eval-whisper-speechbrain-sepformer-translation-check` feeds real separator artifacts
  into the same rolling Whisper quality gates
- Enrolled TSE contract: `scripts/benchmark_enrolled_tse_fixture.py` /
  `make audio-eval-enrolled-oracle-tse-check` adds enrollment-audio paths, hashes, target speaker IDs,
  and same-speaker cue metadata to the TSE JSONL shape
- Mismatched enrollment falsifier: `make audio-eval-enrolled-mismatch-tse-check` pairs each target
  with another speaker's enrollment and must fail target-audio quality gates while passing enrollment
  file/hash validation
- Enrolled downstream bridge: `make audio-eval-whisper-enrolled-oracle-tse-translation-check` feeds
  enrolled oracle artifacts through the same rolling Whisper translation gates
- First real enrolled TSE adapter: `scripts/run_wesep_enrolled_tse_fixture.py` /
  `make audio-eval-wesep-check` runs WeSep with mixture audio plus same-speaker enrollment clips,
  validates enrollment metadata, and compares extracted clips with mixture passthrough
- Enrolled real-model downstream bridge: `make audio-eval-whisper-wesep-translation-check` feeds
  WeSep artifacts through the same rolling Whisper translation gates
- Pass condition: stable speaker IDs across speaker re-entry, less than 500 ms decision latency for first prototype, and no WER regression when separation is enabled

Current measured result on June 9, 2026: oracle TSE on the FLEURS multilingual overlap fixture produced
four extracted clips, covered four overlapped target segments, preserved level/duration exactly, and hit
the capped 120 dB target SNR/interferer-reduction upper bound. Whisper on rolling oracle-TSE slices then
passed with primary-language accuracy 1.0, mean final translation token F1 0.438026, zero language flips,
and max final latency 8847.547 ms. Mixture-passthrough TSE produced the same artifact shape but failed
as expected with min target SNR -6.154 dB, min interferer reduction 0.0 dB, max level error 7.09 dB,
Whisper primary-language accuracy 0.5, mean final translation token F1 0.05, and three language flips.
The earlier rolling mixed-audio Whisper check produced primary-language accuracy 0.5, mean final
translation token F1 0.029643, and three language flips, so real TSE is justified only if it moves
downstream translation toward the oracle-TSE result without unacceptable latency.
Current real-model spike: SpeechBrain SepFormer WHAMR is the first practical disposable Docker
candidate because it is Apache-2.0 with a direct Python API, but it is blind two-speaker separation,
not enrollment-based target-speaker extraction. Its report preserves `speaker_id` through
benchmark-time oracle stream mapping and must beat the mixture-passthrough lower bound before it is
considered for live playback.
Measured on June 10, 2026, SepFormer produced four extracted clips and preserved duration, but failed
the real-model bar: min target SNR -12.311 dB, mean target SNR -8.654 dB, min interferer reduction
-11.925 dB, mean interferer reduction -8.611 dB, and max absolute level error 12.007 dB. It did not
beat the mixture-passthrough mean target SNR of -0.043 dB. Downstream Whisper on the SepFormer clips
also warned with primary-language accuracy 0.25, mean translation token F1 0.088346, one language
flip, and max final latency 9031.32 ms. Keep it as a comparator, not a playback integration path.
Next target-conditioned step: keep the enrolled oracle/mismatch contract as the gate, keep the WeSep
adapter only while it beats mixture passthrough with reference-free runtime postprocess, then add
longer non-same-window enrollment and compare against another enrollment-conditioned candidate before
claiming broad robustness.
ClearerVoice remains a useful packaged comparator only if video/face conditioning enters the product,
and LLaSE-G1/positive-negative enrollment are side research tracks until their runtime and licensing
risks are cleared.
Measured on June 10, 2026, the enrolled oracle path passed with four enrollment files, four hashes,
four extracted clips, min target SNR 120.0 dB, min interferer reduction 120.0 dB, and max level error
0.0 dB. The mismatched-enrollment negative control validated all four enrollment files/hashes and all
four wrong-speaker expectations while failing target-audio quality gates as intended: min target SNR
-4.098 dB, min interferer reduction -6.718 dB, and max level error 8.82 dB.
Measured on June 12, 2026, the WeSep enrolled TSE run produced four extracted clips, four enrollment
files, four enrollment hashes, exact duration preservation, and zero enrollment mismatches. The runner
now applies runtime-available mixture-correlation polarity correction and enrollment-RMS level
normalization while declaring no reference-stem use. That makes WeSep a real-model release-candidate
pass for the current fixture: min target SNR 0.186 dB, mean target SNR 9.766 dB, min interferer
reduction 4.865 dB, mean interferer reduction 9.809 dB, and max absolute level error 0.609 dB.
Downstream Whisper on the WeSep clips still passes the oracle-windowed diagnostic bridge with
primary-language accuracy 1.0, mean translation token F1 0.176282, two language flips, max
first-partial latency 4497.101 ms, and max final latency 9375.379 ms. The current release proof is the
causal Sortformer-driven bridge: DER-like 0.13699, first-speech and overlap latency 3200 ms,
`causality_ok=true`, primary-language accuracy 1.0, mean translation token F1 0.206838, and max final
latency 8725.643 ms. Keep the oracle ceiling gates visible and add longer non-same-window enrollment
plus direct TSE on causal diarization windows before calling this robust enough for arbitrary live
rooms.

## Integration Plan

- Contract fields: `overlapping_speaker_ids`, `input_level_dbfs`, `detected_language_confidence`, `translated_audio_stream_id`
- Gateway/Rust/Flutter files: gateway adapter first, then Rust audio state helpers if low-latency policy logic appears
- Fallback behavior: pyannote/offline baseline for dev; no separation when overlap confidence is low
- Rollback trigger: separation increases WER or diarization label churn on local fixtures

## Detractor Concerns

- Strongest objection: Streaming Sortformer may look excellent in demos but still be brittle for more than four active speakers, non-English speech, non-NVIDIA hardware, and noisy consumer microphones; a diarizer also does not produce clean speaker audio.
- Cheapest falsifying benchmark: run two local overlapping speakers with speaker re-entry and check label stability plus ASR WER with and without separation.
- Fallback path: no separation, pyannote baseline, and UI-visible "overlap uncertain" diagnostics.
- Decision reversal condition: an open streaming diarization model beats Sortformer on local DER/JER/latency without gated access or GPU-heavy deployment.
