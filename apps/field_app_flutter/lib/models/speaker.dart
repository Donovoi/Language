import '../generated/session_contract.dart';

export '../generated/session_contract.dart' show TranslationLaneStatus;
export '../generated/session_contract.dart' show SourceSuppressionMode;

class Speaker {
  const Speaker({
    required this.speakerId,
    required this.displayName,
    required this.languageCode,
    required this.priority,
    required this.active,
    required this.isLocked,
    required this.frontFacing,
    required this.persistenceBonus,
    required this.lastUpdatedUnixMs,
    this.sourceCaption,
    this.translatedCaption,
    this.targetLanguageCode,
    this.laneStatus = TranslationLaneStatus.unspecified,
    this.statusMessage,
    this.inputLevelDbfs,
    this.outputLevelDbfs,
    this.overlappingSpeakerIds = const <String>[],
    this.detectedLanguageCode,
    this.languageConfidence,
    this.voiceCloneId,
    this.voiceCloneStatus,
    this.translatedAudioStreamId,
    this.originalVoiceSuppressionDb,
    this.playbackLatencyMs,
    this.sourceSuppressionMode = SourceSuppressionMode.unspecified,
  });

  final String speakerId;
  final String displayName;
  final String languageCode;
  final double priority;
  final bool active;
  final bool isLocked;
  final bool frontFacing;
  final double persistenceBonus;
  final int lastUpdatedUnixMs;
  final String? sourceCaption;
  final String? translatedCaption;
  final String? targetLanguageCode;
  final TranslationLaneStatus laneStatus;
  final String? statusMessage;
  final double? inputLevelDbfs;
  final double? outputLevelDbfs;
  final List<String> overlappingSpeakerIds;
  final String? detectedLanguageCode;
  final double? languageConfidence;
  final String? voiceCloneId;
  final String? voiceCloneStatus;
  final String? translatedAudioStreamId;
  final double? originalVoiceSuppressionDb;
  final int? playbackLatencyMs;
  final SourceSuppressionMode sourceSuppressionMode;

  Speaker copyWith({
    String? speakerId,
    String? displayName,
    String? languageCode,
    double? priority,
    bool? active,
    bool? isLocked,
    bool? frontFacing,
    double? persistenceBonus,
    int? lastUpdatedUnixMs,
    String? sourceCaption,
    String? translatedCaption,
    String? targetLanguageCode,
    TranslationLaneStatus? laneStatus,
    String? statusMessage,
    double? inputLevelDbfs,
    double? outputLevelDbfs,
    List<String>? overlappingSpeakerIds,
    String? detectedLanguageCode,
    double? languageConfidence,
    String? voiceCloneId,
    String? voiceCloneStatus,
    String? translatedAudioStreamId,
    double? originalVoiceSuppressionDb,
    int? playbackLatencyMs,
    SourceSuppressionMode? sourceSuppressionMode,
  }) {
    return Speaker(
      speakerId: speakerId ?? this.speakerId,
      displayName: displayName ?? this.displayName,
      languageCode: languageCode ?? this.languageCode,
      priority: priority ?? this.priority,
      active: active ?? this.active,
      isLocked: isLocked ?? this.isLocked,
      frontFacing: frontFacing ?? this.frontFacing,
      persistenceBonus: persistenceBonus ?? this.persistenceBonus,
      lastUpdatedUnixMs: lastUpdatedUnixMs ?? this.lastUpdatedUnixMs,
      sourceCaption: sourceCaption ?? this.sourceCaption,
      translatedCaption: translatedCaption ?? this.translatedCaption,
      targetLanguageCode: targetLanguageCode ?? this.targetLanguageCode,
      laneStatus: laneStatus ?? this.laneStatus,
      statusMessage: statusMessage ?? this.statusMessage,
      inputLevelDbfs: inputLevelDbfs ?? this.inputLevelDbfs,
      outputLevelDbfs: outputLevelDbfs ?? this.outputLevelDbfs,
      overlappingSpeakerIds:
          overlappingSpeakerIds ?? this.overlappingSpeakerIds,
      detectedLanguageCode: detectedLanguageCode ?? this.detectedLanguageCode,
      languageConfidence: languageConfidence ?? this.languageConfidence,
      voiceCloneId: voiceCloneId ?? this.voiceCloneId,
      voiceCloneStatus: voiceCloneStatus ?? this.voiceCloneStatus,
      translatedAudioStreamId:
          translatedAudioStreamId ?? this.translatedAudioStreamId,
      originalVoiceSuppressionDb:
          originalVoiceSuppressionDb ?? this.originalVoiceSuppressionDb,
      playbackLatencyMs: playbackLatencyMs ?? this.playbackLatencyMs,
      sourceSuppressionMode:
          sourceSuppressionMode ?? this.sourceSuppressionMode,
    );
  }

  factory Speaker.fromJson(Map<String, dynamic> json) {
    return Speaker(
      speakerId: json[kSpeakerIdJsonKey] as String,
      displayName: json[kSpeakerDisplayNameJsonKey] as String,
      languageCode: json[kSpeakerLanguageCodeJsonKey] as String,
      priority: (json[kSpeakerPriorityJsonKey] as num).toDouble(),
      active: json[kSpeakerActiveJsonKey] as bool,
      isLocked: json[kSpeakerIsLockedJsonKey] as bool? ?? false,
      frontFacing: json[kSpeakerFrontFacingJsonKey] as bool? ?? false,
      persistenceBonus:
          (json[kSpeakerPersistenceBonusJsonKey] as num?)?.toDouble() ?? 0,
      lastUpdatedUnixMs:
          (json[kSpeakerLastUpdatedUnixMsJsonKey] as num?)?.toInt() ?? 0,
      sourceCaption: json[kSpeakerSourceCaptionJsonKey] as String?,
      translatedCaption: json[kSpeakerTranslatedCaptionJsonKey] as String?,
      targetLanguageCode: json[kSpeakerTargetLanguageCodeJsonKey] as String?,
      laneStatus: TranslationLaneStatusPresentation.fromApiValue(
        json[kSpeakerLaneStatusJsonKey] as String?,
      ),
      statusMessage: json[kSpeakerStatusMessageJsonKey] as String?,
      inputLevelDbfs:
          (json[kSpeakerInputLevelDbfsJsonKey] as num?)?.toDouble(),
      outputLevelDbfs:
          (json[kSpeakerOutputLevelDbfsJsonKey] as num?)?.toDouble(),
      overlappingSpeakerIds:
          (json[kSpeakerOverlappingSpeakerIdsJsonKey] as List<dynamic>?)
                  ?.whereType<String>()
                  .toList(growable: false) ??
              const <String>[],
      detectedLanguageCode:
          json[kSpeakerDetectedLanguageCodeJsonKey] as String?,
      languageConfidence:
          (json[kSpeakerLanguageConfidenceJsonKey] as num?)?.toDouble(),
      voiceCloneId: json[kSpeakerVoiceCloneIdJsonKey] as String?,
      voiceCloneStatus: json[kSpeakerVoiceCloneStatusJsonKey] as String?,
      translatedAudioStreamId:
          json[kSpeakerTranslatedAudioStreamIdJsonKey] as String?,
      originalVoiceSuppressionDb:
          (json[kSpeakerOriginalVoiceSuppressionDbJsonKey] as num?)
              ?.toDouble(),
      playbackLatencyMs:
          (json[kSpeakerPlaybackLatencyMsJsonKey] as num?)?.toInt(),
      sourceSuppressionMode: SourceSuppressionModePresentation.fromApiValue(
        json[kSpeakerSourceSuppressionModeJsonKey] as String?,
      ),
    );
  }

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      kSpeakerIdJsonKey: speakerId,
      kSpeakerDisplayNameJsonKey: displayName,
      kSpeakerLanguageCodeJsonKey: languageCode,
      kSpeakerPriorityJsonKey: priority,
      kSpeakerActiveJsonKey: active,
      kSpeakerIsLockedJsonKey: isLocked,
      kSpeakerFrontFacingJsonKey: frontFacing,
      kSpeakerPersistenceBonusJsonKey: persistenceBonus,
      kSpeakerLastUpdatedUnixMsJsonKey: lastUpdatedUnixMs,
      kSpeakerSourceCaptionJsonKey: sourceCaption,
      kSpeakerTranslatedCaptionJsonKey: translatedCaption,
      kSpeakerTargetLanguageCodeJsonKey: targetLanguageCode,
      kSpeakerLaneStatusJsonKey: laneStatus.apiValue,
      kSpeakerStatusMessageJsonKey: statusMessage,
      kSpeakerInputLevelDbfsJsonKey: inputLevelDbfs,
      kSpeakerOutputLevelDbfsJsonKey: outputLevelDbfs,
      kSpeakerOverlappingSpeakerIdsJsonKey: overlappingSpeakerIds,
      kSpeakerDetectedLanguageCodeJsonKey: detectedLanguageCode,
      kSpeakerLanguageConfidenceJsonKey: languageConfidence,
      kSpeakerVoiceCloneIdJsonKey: voiceCloneId,
      kSpeakerVoiceCloneStatusJsonKey: voiceCloneStatus,
      kSpeakerTranslatedAudioStreamIdJsonKey: translatedAudioStreamId,
      kSpeakerOriginalVoiceSuppressionDbJsonKey: originalVoiceSuppressionDb,
      kSpeakerPlaybackLatencyMsJsonKey: playbackLatencyMs,
      kSpeakerSourceSuppressionModeJsonKey: sourceSuppressionMode.apiValue,
    };
  }
}
