# Same-Voice English Output

- Decision id: RDR-0003
- Date: 2026-06-08
- Owner/agent: Codex research gate
- Subsystem: zero-shot voice cloning, voice conversion, and same-speaker English TTS
- Implementation surface: gateway voice/TTS adapter, `voice_clone_status`, `translated_audio_stream_id`, playback mixer

## Product Constraint

The app needs English audio that sounds like the source speaker, starts quickly, matches volume, and
does not persist voice references unsafely. A neutral fallback voice must exist because voice cloning
will fail or be inappropriate in some settings.

## Options Considered

| Option | Evidence status | Runtime fit | Main concern |
| --- | --- | --- | --- |
| Provider/adapter-first same-voice TTS | Operational decision | Best path to early app behavior | Depends on provider safety, cost, and API terms |
| VoxCPM2 | Official repo/model card plus VoxCPM technical report lineage | Strongest current local practical candidate | VoxCPM2 quality/runtime claims need local proof |
| CosyVoice 2 / Fun-CosyVoice | arXiv technical report plus Apache-2.0 model card | Strong streaming/local comparison | Work-in-progress/preprint lineage, deployment review needed |
| OpenVoice V2 | arXiv preprint plus MIT model card | Lightweight cross-lingual cloning baseline | Voice similarity may not be final-product quality |
| Azure Personal Voice | Official provider docs | Safety-first provider clone path | Speaker profile is not ephemeral |
| DiffGAN-ZSTTS | Scientific Reports 2025 | Peer-reviewed zero-shot TTS evidence | May not be the most practical streaming implementation |
| VALL-E X / Cross-lingual F5-TTS | arXiv preprints | Useful innovation watchlist | Research-only until runtime, safety, and license are proved |

## Recommendation

Use a provider-agnostic TTS/voice adapter first, with two explicit modes:

1. `same_voice_candidate`: generated with ephemeral reference audio and visible readiness status
2. `fallback_voice`: neutral English voice when reference quality, consent, latency, or safety fails

For local research, benchmark VoxCPM2, CosyVoice 2/Fun-CosyVoice, and OpenVoice V2 before choosing a
default local model. Treat F5-TTS, VALL-E X, Seed-VC, and similar cross-lingual systems as innovation
watchlist items until they pass the same benchmark, license, and safety gate.

## Evidence

| Ref | Source | Status | Key result | Link |
| --- | --- | --- | --- | --- |
| R1 | VoxCPM2 | Official repo/model card | 2B model, 30 languages, controllable cloning, Apache-2.0, and reported streaming RTF claims. | https://github.com/OpenBMB/VoxCPM |
| R2 | VoxCPM | arXiv technical report | Tokenizer-free TTS, context-aware generation, true-to-life cloning, Apache-2.0 public access. | https://arxiv.org/abs/2509.24650 |
| R3 | CosyVoice 2 | arXiv technical report | Unified streaming/non-streaming speech synthesis with chunk-aware flow matching. | https://arxiv.org/abs/2412.10117 |
| R4 | FunAudioLLM CosyVoice2-0.5B | Official model card | Apache-2.0 model card tied to CosyVoice papers. | https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B |
| R5 | OpenVoice V2 | Official model card | MIT model card with native multilingual support and commercial use claim. | https://huggingface.co/myshell-ai/OpenVoiceV2 |
| R6 | OpenVoice | arXiv preprint | Short-reference multilingual voice cloning with style controls. | https://arxiv.org/abs/2312.01479 |
| R7 | Azure Personal Voice | Official provider docs | Requires verbal consent statement and 5-90s clean voice sample for speaker profile ID. | https://learn.microsoft.com/en-us/azure/ai-services/speech-service/personal-voice-create-voice |
| R8 | DiffGAN-ZSTTS | Scientific Reports 2025 | Peer-reviewed zero-shot speaker-adaptive TTS over Chinese/English datasets. | https://pubmed.ncbi.nlm.nih.gov/39979408/ |
| R9 | VALL-E X | arXiv preprint | Cross-lingual synthesis from one source-language utterance. | https://arxiv.org/abs/2303.03926 |
| R10 | Cross-Lingual F5-TTS | arXiv/preprint listing | Cross-lingual cloning without prompt transcripts. | https://huggingface.co/papers/2509.14579 |

## Metrics And Benchmark

- Primary metric: time to first playable same-voice English audio
- Secondary metrics: speaker similarity, MOS or DNSMOS/UTMOS, WER of synthesized English, real-time factor, reference length, reference deletion proof
- Dataset or fixture: Seed-TTS-Eval-style English WER/speaker-similarity fixture, consented local speaker references, multilingual source prompts, and fixed English target prompts
- Disposable command: add a future `scripts/benchmark_voice_clone_fixture.py`
- Pass condition: bounded latency, no unsafe reference persistence, acceptable speaker similarity, and a clean fallback voice path

## Integration Plan

- Contract fields: `voice_clone_status`, `translated_audio_stream_id`, `output_level_dbfs`, `playback_latency_ms`
- Gateway/Rust/Flutter files: provider adapter in gateway; Flutter already renders readiness states
- Fallback behavior: neutral TTS with visible status when same-voice synthesis is not ready
- Rollback trigger: provider/model stores references unsafely, exceeds latency budget, or produces unintelligible English

## Detractor Concerns

- Strongest objection: Voice-clone demos often optimize for impressiveness, not consent, bounded full-loop latency, cross-language robustness, licensing, or repeatable human speaker similarity.
- Cheapest falsifying benchmark: three consented speakers, 5s/15s/60s references, ten English outputs each, scored for time-to-first-audio, WER, ASV similarity, and blinded speaker similarity.
- Fallback path: neutral English voice at matched volume with `voice_clone_status=fallback`.
- Decision reversal condition: a local model proves better latency, similarity, safety, and license terms than the provider path on the same fixture.
