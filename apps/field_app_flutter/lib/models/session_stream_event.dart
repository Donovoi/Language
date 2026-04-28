import 'session_state.dart';
import 'speaker.dart';

// Contract-lock manifest: CI compares these keys against `proto/session.proto`.
const String kSpeakerEventSpeakerIdJsonKey = 'speaker_id';
const String kSpeakerEventPriorityDeltaJsonKey = 'priority_delta';
const String kSpeakerEventActiveJsonKey = 'active';
const String kSpeakerEventIsLockedJsonKey = 'is_locked';
const String kSpeakerEventObservedUnixMsJsonKey = 'observed_unix_ms';
const String kSpeakerEventSourceCaptionJsonKey = 'source_caption';
const String kSpeakerEventTranslatedCaptionJsonKey = 'translated_caption';
const String kSpeakerEventTargetLanguageCodeJsonKey = 'target_language_code';
const String kSpeakerEventLaneStatusJsonKey = 'lane_status';
const String kSpeakerEventStatusMessageJsonKey = 'status_message';

const List<String> kSpeakerEventContractFields = <String>[
  kSpeakerEventSpeakerIdJsonKey,
  kSpeakerEventPriorityDeltaJsonKey,
  kSpeakerEventActiveJsonKey,
  kSpeakerEventIsLockedJsonKey,
  kSpeakerEventObservedUnixMsJsonKey,
  kSpeakerEventSourceCaptionJsonKey,
  kSpeakerEventTranslatedCaptionJsonKey,
  kSpeakerEventTargetLanguageCodeJsonKey,
  kSpeakerEventLaneStatusJsonKey,
  kSpeakerEventStatusMessageJsonKey,
];

const String kSessionStreamEventEventJsonKey = 'event';
const String kSessionStreamEventSessionJsonKey = 'session';
const String kSessionStreamEventSpeakerEventJsonKey = 'speaker_event';

const List<String> kSessionStreamEventContractFields = <String>[
  kSessionStreamEventEventJsonKey,
  kSessionStreamEventSessionJsonKey,
  kSessionStreamEventSpeakerEventJsonKey,
];

enum SessionStreamEventType {
  unknown('STREAM_EVENT_TYPE_UNSPECIFIED', 'unknown'),
  sessionSnapshot('STREAM_EVENT_TYPE_SESSION_SNAPSHOT', 'session.snapshot'),
  speakerUpdate('STREAM_EVENT_TYPE_SPEAKER_UPDATE', 'speaker.update');

  const SessionStreamEventType(this.protoName, this.apiValue);

  final String protoName;
  final String apiValue;
}

extension SessionStreamEventTypePresentation on SessionStreamEventType {

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
      speakerId: json[kSpeakerEventSpeakerIdJsonKey] as String,
      priorityDelta: (json[kSpeakerEventPriorityDeltaJsonKey] as num).toDouble(),
      active: json[kSpeakerEventActiveJsonKey] as bool,
      isLocked: json[kSpeakerEventIsLockedJsonKey] as bool? ?? false,
      observedUnixMs:
          (json[kSpeakerEventObservedUnixMsJsonKey] as num?)?.toInt() ?? 0,
      sourceCaption: json[kSpeakerEventSourceCaptionJsonKey] as String?,
      translatedCaption: json[kSpeakerEventTranslatedCaptionJsonKey] as String?,
      targetLanguageCode: json[kSpeakerEventTargetLanguageCodeJsonKey] as String?,
      laneStatus: TranslationLaneStatusPresentation.fromApiValue(
        json[kSpeakerEventLaneStatusJsonKey] as String?,
      ),
      statusMessage: json[kSpeakerEventStatusMessageJsonKey] as String?,
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
    final sessionJson = json[kSessionStreamEventSessionJsonKey];
    final speakerEventJson = json[kSessionStreamEventSpeakerEventJsonKey];

    return SessionStreamEvent(
      type: SessionStreamEventTypePresentation.fromApiValue(
        json[kSessionStreamEventEventJsonKey] as String?,
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