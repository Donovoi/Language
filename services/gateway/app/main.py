from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Language Gateway", version="0.1.0")


class SpeakerEvent(BaseModel):
    speaker_id: str
    language_code: str
    priority: float
    active: bool


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/speakers")
def speakers(events: list[SpeakerEvent]) -> dict[str, object]:
    ordered = sorted(events, key=lambda item: item.priority, reverse=True)
    return {
        "count": len(ordered),
        "top_speaker": ordered[0].speaker_id if ordered else None,
        "speakers": [event.model_dump() for event in ordered],
    }
