import '../generated/session_contract.dart';

export '../generated/session_contract.dart' show TranslationLaneStatus;

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
    };
  }
}
