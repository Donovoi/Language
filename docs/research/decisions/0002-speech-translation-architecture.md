# Speech Translation Architecture

- Decision id: RDR-0002
- Date: 2026-06-08
- Owner/agent: Codex research gate
- Subsystem: language ID, ASR, into-English translation, and direct S2ST comparison
- Implementation surface: gateway translation/audio provider adapters, future streaming ASR adapter, `detected_language` fields

## Product Constraint

The product needs early language detection, partial English output, debuggable failures, and a path to
same-speaker English audio. Direct speech-to-speech systems are exciting, but the current app also
needs intermediate speaker, volume, source text, and suppression metadata.

## Options Considered

| Option | Evidence status | Runtime fit | Main concern |
| --- | --- | --- | --- |
| Cascaded/hybrid ASR -> MT/S2TT -> voice-conditioned TTS | Mature pattern with strong baselines | Best first production path | Error propagation and added orchestration latency |
| MMS LID + Whisper-Streaming style ASR + NLLB/provider MT | Papers/model cards plus runnable components | Best concrete first benchmark stack | Whisper is adapted to streaming rather than native streaming |
| SeamlessM4T-style unified model | Nature 2025 | Best benchmark for multilingual speech/text coverage | Non-commercial research constraints and limited same-voice control |
| SeamlessStreaming | arXiv plus model card | Best direct/streaming shadow benchmark | Speech-output quality and app-level controllability still need proof |
| DiariST-style streaming ST with diarization | ICASSP 2024 | Best research pattern for streaming ST plus speakers | Narrower dataset scope and not a drop-in runtime |
| Direct S2ST LLM/vocoder systems | 2025 preprints | High upside | Harder to debug and control speaker clone/suppression metadata |

## Recommendation

Build the first real implementation as a cascaded/hybrid runtime:

1. streaming capture and diarization
2. explicit language ID, with ASR language prediction as a second signal
3. streaming ASR source text
4. into-English MT/S2TT at a text boundary
5. text-level translation confidence and partials
6. same-voice English TTS/voice conversion
7. playback mixer and suppression metadata

For the first benchmark stack, test MMS LID, Whisper-Streaming style ASR, and NLLB/provider MT against
SeamlessStreaming/SeamlessM4T as the shadow direct path. Keep direct S2ST as a research track until
it can expose enough control for speaker identity, volume matching, and source suppression.

## Evidence

| Ref | Source | Status | Key result | Link |
| --- | --- | --- | --- | --- |
| R1 | SEAMLESSM4T | Nature 2025 | Unified ASR/S2TT/S2ST/T2ST/T2TT across many languages and strong robustness claims. | https://www.nature.com/articles/s41586-024-08359-z |
| R2 | Whisper | ICML 2023/PMLR | Multilingual weakly supervised ASR baseline trained on 680,000 hours. | https://proceedings.mlr.press/v202/radford23a.html |
| R3 | Whisper-Streaming | IJCNLP-AACL 2023 demo/preprint | Adapts Whisper-like models for streaming with local agreement and reported 3.3s latency. | https://arxiv.org/abs/2307.14743 |
| R4 | MMS | arXiv preprint/model family | Speech technology scaled to 1,000+ languages; useful LID benchmark family. | https://arxiv.org/abs/2305.13516 |
| R5 | NLLB/FLORES-200 | arXiv/preprint plus benchmark | Strong multilingual MT and FLORES-200 evaluation basis. | https://arxiv.org/abs/2207.04672 |
| R6 | SeamlessStreaming | arXiv preprint/model family | Simultaneous speech-to-speech/text translation in a streaming fashion. | https://arxiv.org/abs/2312.05187 |
| R7 | DiariST | ICASSP 2024 | Streaming speech translation with speaker diarization and overlap-aware evaluation. | https://www.microsoft.com/en-us/research/uploads/prod/2024/05/ICASSP2024_Translation_and_Diarization.pdf |
| R8 | CHiME-8 DASR | Challenge paper/preprint | Evaluates joint distant ASR and diarization in diverse multi-speaker scenarios. | https://arxiv.org/abs/2407.16447 |
| R9 | FLEURS | arXiv benchmark | Speech benchmark useful for multilingual ASR and language ID evaluation. | https://arxiv.org/abs/2205.12446 |
| R10 | CoVoST 2 | arXiv benchmark | Massively multilingual speech-to-text translation benchmark. | https://arxiv.org/abs/2007.10310 |
| R11 | SLM-S2ST | 2025 arXiv preprint | Direct speech-to-speech translation using text/audio token generation and streaming vocoder. | https://www.microsoft.com/en-us/research/publication/slm-s2st-a-multimodal-language-model-for-direct-speech-to-speech-translation/ |

## Metrics And Benchmark

- Primary metric: time to first English partial and final translation quality
- Secondary metrics: language ID accuracy, WER/CER, BLEU/chrF/COMET, speaker-attributed BLEU, partial rollback rate
- Dataset or fixture: FLEURS, CoVoST2, DiariST-AliMeeting, and local mixed-language room clips
- Disposable command: `scripts/benchmark_translation_fixture.py` / `make audio-eval-translation-check`
- First measured baseline: `scripts/run_whisper_translation_fixture.py` / `make audio-eval-whisper-translation-check`
- First mixed-audio falsifier: `scripts/run_whisper_rolling_translation_fixture.py` / `make audio-eval-whisper-rolling-translation-check`
- First TSE upper bound: `scripts/run_whisper_tse_translation_fixture.py` / `make audio-eval-whisper-oracle-tse-translation-check`
- TSE lower bound: `scripts/run_whisper_tse_translation_fixture.py --tse-mode passthrough` / `make audio-eval-whisper-mixture-passthrough-tse-translation-check`
- External TSE/separator bridge: `scripts/run_whisper_tse_translation_fixture.py --tse-mode external --tse-predictions ...`
  / `make audio-eval-whisper-speechbrain-sepformer-translation-check`
- Enrolled oracle TSE bridge: `scripts/benchmark_enrolled_tse_fixture.py oracle-check` plus
  `make audio-eval-whisper-enrolled-oracle-tse-translation-check`
- Real enrolled TSE bridge: `scripts/run_wesep_enrolled_tse_fixture.py` plus
  `make audio-eval-whisper-wesep-translation-check`
- Pass condition: stable 1s/2s/4s language ID windows, partial English within a live-turn budget, and clean fallback when language ID flips

Current measured result on June 9, 2026: Whisper tiny on clean oracle FLEURS source clips reached
primary-language accuracy 1.0 and mean translation token F1 0.422401. The rolling mixed-audio
falsifier warned: four final segments were produced, primary-language accuracy fell to 0.5, mean
final translation token F1 fell to 0.029643, and three speaker language flips were recorded. That
supports keeping separation/target-speaker extraction ahead of spoken translated playback.
The rolling oracle-TSE upper bound restored primary-language accuracy to 1.0, mean final translation
token F1 to 0.438026, and language flips to zero, with max final latency 8847.547 ms on CPU.
The rolling mixture-passthrough-TSE lower bound kept primary-language accuracy at 0.5, mean final
translation token F1 at 0.05, and language flips at three, proving copied mixed audio is not enough.
The first external separator bridge, SpeechBrain SepFormer WHAMR, warned on June 10, 2026:
primary-language accuracy 0.25, mean final translation token F1 0.088346, one language flip, and max
final latency 9031.32 ms. This keeps the cascade architecture intact but falsifies blind SepFormer as
the next playback-ready separation layer for the current multilingual overlap fixture.
The enrolled oracle bridge adds speaker-cue metadata before the next real adapter. Measured on
June 10, 2026, it passed with primary-language accuracy 1.0, mean final translation token F1 0.422401,
zero language flips, max first-partial latency 4576.792 ms, and max final latency 8756.592 ms. The
paired mismatched-enrollment TSE check fails target-audio gates, proving the app contract can
distinguish correct and wrong speaker cues before WeSep or another enrollment-conditioned model is
trusted.
The real enrolled WeSep bridge now passes both the oracle-windowed diagnostic post-TSE translation
bridge and the causal Sortformer-driven release bridge for the current fixture.
Measured on June 12, 2026, WeSep beat mixture passthrough after runtime-available
mixture-correlation polarity correction and enrollment-RMS level normalization, with no reference
stems used by the postprocess. Downstream Whisper produced all four final speaker translations with
primary-language accuracy 1.0, mean final translation token F1 0.176282, two language flips, max
first-partial latency 4497.101 ms, and max final latency 9375.379 ms on the oracle-windowed
diagnostic. The causal release report instead consumes rolling Sortformer diarization, records
DER-like 0.13699, `causality_ok=true`, primary-language accuracy 1.0, mean final translation token F1
0.206838, three language flips, max first-partial latency 4455.676 ms, and max final latency 8725.643
ms. Longer-enrollment, stronger TSE candidates, and direct TSE on causal diarization windows remain
active research work.

## Integration Plan

- Contract fields: `detected_language`, `detected_language_confidence`, `translated_caption`, `playback_latency_ms`
- Gateway/Rust/Flutter files: gateway adapter and SSE event path first; Flutter already displays metadata
- Fallback behavior: text-only translated caption when audio synthesis is not ready
- Rollback trigger: direct S2ST cannot expose partials, language confidence, or speaker-conditioned audio controls

## Detractor Concerns

- Strongest objection: A cascade can accumulate ASR mistakes and may be slower than a polished direct S2ST model; Whisper-style streaming is adapted rather than native.
- Cheapest falsifying benchmark: run the same short multilingual overlap clips through one cascaded baseline and one direct/hybrid baseline, measuring time to first English audio plus translation quality.
- Fallback path: keep text captions and neutral TTS even when voice clone or direct S2ST fails.
- Decision reversal condition: a direct S2ST candidate beats cascade latency/quality while exposing speaker identity, volume, and safety controls through the app contract.
