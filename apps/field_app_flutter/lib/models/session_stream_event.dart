import '../generated/session_contract.dart';
import 'session_state.dart';

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
    this.inputLevelDbfs,
    this.outputLevelDbfs,
    this.overlappingSpeakerIds,
    this.detectedLanguageCode,
    this.languageConfidence,
    this.voiceCloneId,
    this.voiceCloneStatus,
    this.translatedAudioStreamId,
    this.originalVoiceSuppressionDb,
    this.playbackLatencyMs,
    this.sourceSuppressionMode,
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
  final double? inputLevelDbfs;
  final double? outputLevelDbfs;
  final List<String>? overlappingSpeakerIds;
  final String? detectedLanguageCode;
  final double? languageConfidence;
  final String? voiceCloneId;
  final String? voiceCloneStatus;
  final String? translatedAudioStreamId;
  final double? originalVoiceSuppressionDb;
  final int? playbackLatencyMs;
  final SourceSuppressionMode? sourceSuppressionMode;

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
      inputLevelDbfs:
          (json[kSpeakerEventInputLevelDbfsJsonKey] as num?)?.toDouble(),
      outputLevelDbfs:
          (json[kSpeakerEventOutputLevelDbfsJsonKey] as num?)?.toDouble(),
      overlappingSpeakerIds:
          json.containsKey(kSpeakerEventOverlappingSpeakerIdsJsonKey)
              ? (json[kSpeakerEventOverlappingSpeakerIdsJsonKey]
                      as List<dynamic>?)
                  ?.whereType<String>()
                  .toList(growable: false)
              : null,
      detectedLanguageCode:
          json[kSpeakerEventDetectedLanguageCodeJsonKey] as String?,
      languageConfidence:
          (json[kSpeakerEventLanguageConfidenceJsonKey] as num?)?.toDouble(),
      voiceCloneId: json[kSpeakerEventVoiceCloneIdJsonKey] as String?,
      voiceCloneStatus:
          json[kSpeakerEventVoiceCloneStatusJsonKey] as String?,
      translatedAudioStreamId:
          json[kSpeakerEventTranslatedAudioStreamIdJsonKey] as String?,
      originalVoiceSuppressionDb:
          (json[kSpeakerEventOriginalVoiceSuppressionDbJsonKey] as num?)
              ?.toDouble(),
      playbackLatencyMs:
          (json[kSpeakerEventPlaybackLatencyMsJsonKey] as num?)?.toInt(),
      sourceSuppressionMode: json.containsKey(
        kSpeakerEventSourceSuppressionModeJsonKey,
      )
          ? SourceSuppressionModePresentation.fromApiValue(
              json[kSpeakerEventSourceSuppressionModeJsonKey] as String?,
            )
          : null,
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
