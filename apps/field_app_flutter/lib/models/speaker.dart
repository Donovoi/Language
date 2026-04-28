// Contract-lock manifest: CI compares these keys against `proto/session.proto`.
const String kSpeakerIdJsonKey = 'speaker_id';
const String kSpeakerDisplayNameJsonKey = 'display_name';
const String kSpeakerLanguageCodeJsonKey = 'language_code';
const String kSpeakerPriorityJsonKey = 'priority';
const String kSpeakerActiveJsonKey = 'active';
const String kSpeakerIsLockedJsonKey = 'is_locked';
const String kSpeakerFrontFacingJsonKey = 'front_facing';
const String kSpeakerPersistenceBonusJsonKey = 'persistence_bonus';
const String kSpeakerLastUpdatedUnixMsJsonKey = 'last_updated_unix_ms';
const String kSpeakerSourceCaptionJsonKey = 'source_caption';
const String kSpeakerTranslatedCaptionJsonKey = 'translated_caption';
const String kSpeakerTargetLanguageCodeJsonKey = 'target_language_code';
const String kSpeakerLaneStatusJsonKey = 'lane_status';
const String kSpeakerStatusMessageJsonKey = 'status_message';

const List<String> kSpeakerContractFields = <String>[
  kSpeakerIdJsonKey,
  kSpeakerDisplayNameJsonKey,
  kSpeakerLanguageCodeJsonKey,
  kSpeakerPriorityJsonKey,
  kSpeakerActiveJsonKey,
  kSpeakerIsLockedJsonKey,
  kSpeakerFrontFacingJsonKey,
  kSpeakerPersistenceBonusJsonKey,
  kSpeakerLastUpdatedUnixMsJsonKey,
  kSpeakerSourceCaptionJsonKey,
  kSpeakerTranslatedCaptionJsonKey,
  kSpeakerTargetLanguageCodeJsonKey,
  kSpeakerLaneStatusJsonKey,
  kSpeakerStatusMessageJsonKey,
];

enum TranslationLaneStatus {
  unspecified('LANE_STATUS_UNSPECIFIED', 'UNSPECIFIED', 'Pending'),
  idle('LANE_STATUS_IDLE', 'IDLE', 'Idle'),
  listening('LANE_STATUS_LISTENING', 'LISTENING', 'Listening'),
  translating('LANE_STATUS_TRANSLATING', 'TRANSLATING', 'Translating'),
  ready('LANE_STATUS_READY', 'READY', 'Ready'),
  error('LANE_STATUS_ERROR', 'ERROR', 'Error');

  const TranslationLaneStatus(this.protoName, this.apiValue, this.label);

  final String protoName;
  final String apiValue;
  final String label;
}

extension TranslationLaneStatusPresentation on TranslationLaneStatus {

  static TranslationLaneStatus fromApiValue(String? value) {
    return TranslationLaneStatus.values.firstWhere(
      (status) => status.apiValue == value,
      orElse: () => TranslationLaneStatus.unspecified,
    );
  }
}

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
