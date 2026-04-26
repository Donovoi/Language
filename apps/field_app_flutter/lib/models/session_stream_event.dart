import 'session_state.dart';
import 'speaker.dart';

enum SessionStreamEventType { unknown, sessionSnapshot, speakerUpdate }

extension SessionStreamEventTypePresentation on SessionStreamEventType {
  String get apiValue {
    switch (this) {
      case SessionStreamEventType.unknown:
        return 'unknown';
      case SessionStreamEventType.sessionSnapshot:
        return 'session.snapshot';
      case SessionStreamEventType.speakerUpdate:
        return 'speaker.update';
    }
  }

  static SessionStreamEventType fromApiValue(String? value) {
    return SessionStreamEventType.values.firstWhere(
      (eventType) => eventType.apiValue == value,
      orElse: () => SessionStreamEventType.unknown,
    );
  }
}

class SpeakerEventModel {
  const SpeakerEventModel({
    required this.speakerId,
    required this.priorityDelta,
    required this.active,
    required this.isLocked,
    required this.observedUnixMs,
    this.sourceCaption,
    this.translatedCaption,
    this.targetLanguageCode,
    this.laneStatus = TranslationLaneStatus.unspecified,
    this.statusMessage,
  });

  final String speakerId;
  final double priorityDelta;
  final bool active;
  final bool isLocked;
  final int observedUnixMs;
  final String? sourceCaption;
  final String? translatedCaption;
  final String? targetLanguageCode;
  final TranslationLaneStatus laneStatus;
  final String? statusMessage;

  factory SpeakerEventModel.fromJson(Map<String, dynamic> json) {
    return SpeakerEventModel(
      speakerId: json['speaker_id'] as String,
      priorityDelta: (json['priority_delta'] as num).toDouble(),
      active: json['active'] as bool,
      isLocked: json['is_locked'] as bool? ?? false,
      observedUnixMs: (json['observed_unix_ms'] as num?)?.toInt() ?? 0,
      sourceCaption: json['source_caption'] as String?,
      translatedCaption: json['translated_caption'] as String?,
      targetLanguageCode: json['target_language_code'] as String?,
      laneStatus: TranslationLaneStatusPresentation.fromApiValue(
        json['lane_status'] as String?,
      ),
      statusMessage: json['status_message'] as String?,
    );
  }
}

class SessionStreamEvent {
  const SessionStreamEvent({
    required this.type,
    this.session,
    this.speakerEvent,
  });

  final SessionStreamEventType type;
  final SessionStateModel? session;
  final SpeakerEventModel? speakerEvent;

  factory SessionStreamEvent.fromJson(Map<String, dynamic> json) {
    final sessionJson = json['session'];
    final speakerEventJson = json['speaker_event'];

    return SessionStreamEvent(
      type: SessionStreamEventTypePresentation.fromApiValue(
        json['event'] as String?,
      ),
      session: sessionJson is Map<String, dynamic>
          ? SessionStateModel.fromJson(sessionJson)
          : null,
      speakerEvent: speakerEventJson is Map<String, dynamic>
          ? SpeakerEventModel.fromJson(speakerEventJson)
          : null,
    );
  }
}