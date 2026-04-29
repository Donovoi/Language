from __future__ import annotations

from dataclasses import dataclass
import json
from json import JSONDecodeError
from urllib import error, request
from urllib.parse import urljoin

from app.config import TranslationSettings, get_translation_settings
from app.models import LaneStatus, SpeakerState


class TranslationAdapterError(RuntimeError):
    """Raised when the configured translation adapter cannot translate a caption."""


@dataclass(frozen=True, slots=True)
class TranslationRequest:
    text: str
    source_language_code: str
    target_language_code: str


class _LibreTranslateAdapter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout_ms: int,
    ) -> None:
        self._translate_url = urljoin(f"{base_url.rstrip('/')}/", "translate")
        self._api_key = api_key
        self._timeout_seconds = timeout_ms / 1000

    def translate(self, translation_request: TranslationRequest) -> str:
        payload: dict[str, object] = {
            "q": translation_request.text,
            "source": translation_request.source_language_code,
            "target": translation_request.target_language_code,
            "format": "text",
        }
        if self._api_key is not None:
            payload["api_key"] = self._api_key

        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self._translate_url,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self._timeout_seconds) as response:
                raw_response = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            reason = detail or str(exc.reason) or f"HTTP {exc.code}"
            raise TranslationAdapterError(reason) from exc
        except error.URLError as exc:
            reason = exc.reason if isinstance(exc.reason, str) else str(exc.reason)
            raise TranslationAdapterError(reason or "request failed") from exc
        except TimeoutError as exc:
            raise TranslationAdapterError("request timed out") from exc

        try:
            payload = json.loads(raw_response)
        except JSONDecodeError as exc:
            raise TranslationAdapterError("provider returned invalid JSON") from exc

        if isinstance(payload, list) and payload:
            payload = payload[0]

        if not isinstance(payload, dict):
            raise TranslationAdapterError("provider response was not a JSON object")

        translated_text = payload.get("translatedText") or payload.get("translated_text")
        if isinstance(translated_text, list):
            translated_text = translated_text[0] if translated_text else None
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise TranslationAdapterError("provider response did not include translatedText")

        return translated_text.strip()


class CaptionTranslator:
    def __init__(self, settings: TranslationSettings | None = None) -> None:
        self._settings = settings or get_translation_settings()
        self._adapter = self._build_adapter(self._settings)

    @property
    def enabled(self) -> bool:
        return self._adapter is not None

    def translate_ready_speakers(self, speakers: list[SpeakerState]) -> list[SpeakerState]:
        if not self.enabled or not speakers:
            return speakers

        return [self._translate_ready_speaker(speaker) for speaker in speakers]

    def _build_adapter(self, settings: TranslationSettings) -> _LibreTranslateAdapter | None:
        if not settings.enabled or settings.base_url is None:
            return None
        return _LibreTranslateAdapter(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout_ms=settings.timeout_ms,
        )

    def _translate_ready_speaker(self, speaker: SpeakerState) -> SpeakerState:
        if speaker.lane_status != LaneStatus.READY:
            return speaker

        existing_translation = (speaker.translated_caption or "").strip()
        if existing_translation:
            return speaker

        source_caption = (speaker.source_caption or "").strip()
        if not source_caption:
            return speaker

        requested_target_language = _normalize_language_tag(
            speaker.target_language_code or self._settings.default_target_language_code
        )
        source_language = _provider_language_code(speaker.language_code)
        provider_target_language = _provider_language_code(requested_target_language)

        if source_language == provider_target_language:
            return speaker.model_copy(
                update={
                    "translated_caption": source_caption,
                    "target_language_code": requested_target_language,
                }
            )

        adapter = self._adapter
        if adapter is None:
            return speaker

        try:
            translated_caption = adapter.translate(
                TranslationRequest(
                    text=source_caption,
                    source_language_code=source_language,
                    target_language_code=provider_target_language,
                )
            )
        except TranslationAdapterError as exc:
            return speaker.model_copy(
                update={
                    "translated_caption": None,
                    "target_language_code": requested_target_language,
                    "lane_status": LaneStatus.ERROR,
                    "status_message": f"Translation provider error: {exc}",
                }
            )

        return speaker.model_copy(
            update={
                "translated_caption": translated_caption,
                "target_language_code": requested_target_language,
            }
        )


def _normalize_language_tag(language_tag: str) -> str:
    return language_tag.strip().replace("_", "-").lower()


def _provider_language_code(language_tag: str) -> str:
    normalized = _normalize_language_tag(language_tag)
    primary_language, _, _ = normalized.partition("-")
    return primary_language or normalized