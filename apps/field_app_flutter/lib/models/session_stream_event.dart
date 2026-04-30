import '../generated/session_contract.dart';
import 'session_state.dart';
import 'speaker.dart';

export '../generated/session_contract.dart' show SessionStreamEventType;

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