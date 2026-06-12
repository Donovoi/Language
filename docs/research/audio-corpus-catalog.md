# External Audio Corpus Catalog

This catalog keeps public crowd, meeting, multilingual, and separation datasets on an auditable path.
The machine-readable source of truth is `fixtures/audio_eval/external_corpora/catalog.json`; validate
it with:

```bash
make audio-corpus-catalog-check
```

Windows:

```powershell
python scripts/check_audio_corpus_catalog.py
```

## First Benchmarks To Build

| Priority | Corpus | Use first for | License/terms posture |
| --- | --- | --- | --- |
| P0 | NOTSOFAR-1 Recorded Meetings | Real distant meeting diarization and ASR stress | CC BY 4.0 data via official repo/HF subsets |
| P0 | AMI Meeting Corpus | Canonical meeting diarization, close/distant mic comparison | Public release under CC BY 4.0 for released signals/annotations |
| P0 | LibriCSS | Continuous overlap and future separation/TSE benchmarks | Open benchmark derived from LibriSpeech; keep attribution review |
| P0 | LibriMix | Controlled two-/three-speaker separation fixtures | Open generated dataset; full generation is huge |
| P0 | FSD50K/Freesound | Crowd ambience, applause, chatter-like noise | Per-clip Creative Commons; filter to CC0/CC BY and track attribution |
| P0 | MUSAN | Baseline speech/noise/music augmentation | CC BY 4.0 |

The next fixture should be a tiny NOTSOFAR or AMI subset that runs through the existing rolling PCM
Sortformer path and emits the same DER-like, overlap latency, label-churn, and causality fields. The
first noise fixture is `scripts/prepare_crowd_noise_fixture.py`: it mixes a CC-reviewed
FSD50K/Freesound crowd preview underneath the same spoken fixture without changing speaker truth.

## Useful But Terms-Sensitive

| Corpus | Why keep it | Why wait |
| --- | --- | --- |
| VoxConverse | Wild multi-speaker diarization with public-video conditions, overlap, crowd/music/background variation | YouTube-derived public-figure speech; keep benchmark-only until review |
| AliMeeting/M2MeT | Mandarin multi-party meetings and a bridge to DiariST-style Chinese-to-English evaluation | Official access/split rules need review before automated downloads |
| Ego4D AVD | Egocentric social/crowd audio-visual diarization pressure | Custom license acceptance and video/privacy posture make it too heavy for first audio-only gates |

## Multilingual Speech Sources

Common Voice and FLEURS are not crowd recordings, but they are the right permissive sources for
language-ID, multilingual ASR, and early translation routing fixtures. Use them to add non-English
speech segments, then mix those segments with meeting/crowd noise rather than pretending they are
real overlapping room captures.

The first FLEURS-backed gate is `scripts/benchmark_translation_fixture.py`. It uses four tiny
runtime-downloaded clips from `google/fleurs` and records English reference text for oracle
language/translation scoring before real ASR/LID/MT adapters are trusted.

## Detractor Loop

The strongest objection is that "free online crowd recordings" can be legally and scientifically
messy: many have unclear consent, unstable URLs, missing speaker labels, or licenses that allow
listening but not redistribution or training. The cheapest falsifying benchmark is to take one
candidate clip, prove its license and attribution, hash it, mix it into the rolling PCM fixture, and
show whether diarization/ASR degrades. If license or attribution cannot be proven, reject the clip and
use FSD50K, MUSAN, AMI, NOTSOFAR, LibriCSS, or Common Voice instead.

## Primary Sources

- AMI Meeting Corpus: https://groups.inf.ed.ac.uk/ami/corpus/
- NOTSOFAR-1 Challenge: https://github.com/microsoft/NOTSOFAR1-Challenge
- VoxConverse: https://github.com/joonson/voxconverse
- LibriCSS paper page: https://www.microsoft.com/en-us/research/publication/continuous-speech-separation-dataset-and-analysis/
- LibriMix repo: https://github.com/JorisCos/LibriMix
- FSD50K/Freesound datasets: https://labs.freesound.org/datasets/
- MUSAN/OpenSLR: https://openslr.org/17/
- Common Voice datasets: https://commonvoice.mozilla.org/en/datasets
- FLEURS dataset card: https://huggingface.co/datasets/google/fleurs
- AliMeeting baseline/download pointers: https://github.com/yufan-aslp/AliMeeting
