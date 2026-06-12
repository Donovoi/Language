# Robin Research Gate

Language should stay innovative, but model and provider choices need evidence before they become
runtime commitments. Use the local Robin checkout as the research engine for each major subsystem:
capture, diarization, separation, language ID, speech translation, same-voice TTS, playback mixing,
and source-voice suppression.

## Rule

Before integrating a new model, provider, DSP module, or benchmark-sensitive runtime dependency:

1. generate a research pack from `research/language_stack_questions.json`
2. run Robin or an equivalent literature agent against the relevant subsystem task
3. verify important claims against primary sources
4. run the detractor loop and record the strongest objection
5. write a decision record from `docs/research/decision-record-template.md`
6. add or update a disposable benchmark/smoke check

Preprints, vendor pages, and blogs can help discover candidates, but the final decision must label
their status and prefer peer-reviewed papers or official benchmark/model documentation.

## Generate A Pack

From the Language repo:

```bash
python3 scripts/prepare_robin_research_pack.py
python3 scripts/prepare_robin_research_pack.py --check
```

On Windows:

```powershell
python scripts\prepare_robin_research_pack.py
python scripts\prepare_robin_research_pack.py --check
```

The default Robin path is the sibling checkout at `../robin`. Override it with
`ROBIN_REPO_PATH` or `--robin-repo`.

## Use Robin

In the Robin repo, prefer the open literature fallback unless Edison is intentionally configured:

```powershell
$env:ROBIN_LITERATURE_BACKEND = "open"
$env:ROBIN_WEB_SEARCH_URL = "http://127.0.0.1:8080/search"
docker compose -f docker-compose.search.yml up -d
```

SearXNG is for lead discovery. Claims that affect implementation should be checked against primary
sources such as journal/conference proceedings, official model cards, official code, or benchmark
papers.

## Decision Criteria

Each decision record should include:

- best option and runner-up
- latency, real-time factor, memory, and target hardware assumptions
- quality metrics appropriate to the subsystem
- safety and privacy constraints, especially for voice references
- known failure modes and detractor concerns
- benchmark fixture and disposable environment command
- contract fields affected in `proto/session.proto`

## Detractor Loop

Every decision must answer:

- What practical assumption would make this fail in a real noisy room?
- Which claims are peer-reviewed, and which are only preprint/vendor/demo claims?
- What latency, hardware, licensing, privacy, or safety issue could make it unusable?
- What is the cheapest benchmark that could disprove the choice?
- What fallback should the app use when the choice fails open?

The output must include the strongest objection, the cheapest falsifying benchmark, the fallback path,
and the condition that would reverse the recommendation.

## Subsystem Metrics

- diarization: DER, JER, overlap recall, speaker-label stability, chunk latency
- separation: SI-SDR improvement, WER after separation, artifacts, real-time factor
- language ID and ASR: language accuracy, WER/CER, partial-result latency
- translation: BLEU, chrF, COMET, speaker-attributed BLEU where applicable
- TTS or voice conversion: MOS, speaker similarity, time to first audio, real-time factor
- playback and suppression: LUFS/dBFS target error, clipping, suppression dB, residual source audibility

## Agent Expectation

Agents should not treat a literature answer as done. A research pass is complete only when it produces
an implementation recommendation, a detractor result, and a benchmarkable next step.
