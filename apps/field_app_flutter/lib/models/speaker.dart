enum TranslationLaneStatus {
  unspecified,
  idle,
  listening,
  translating,
  ready,
  error,
}

extension TranslationLaneStatusPresentation on TranslationLaneStatus {
  String get apiValue {
    switch (this) {
      case TranslationLaneStatus.unspecified:
        return 'UNSPECIFIED';
      case TranslationLaneStatus.idle:
        return 'IDLE';
      case TranslationLaneStatus.listening:
        return 'LISTENING';
      case TranslationLaneStatus.translating:
        return 'TRANSLATING';
      case TranslationLaneStatus.ready:
        return 'READY';
      case TranslationLaneStatus.error:
        return 'ERROR';
    }
  }

  String get label {
    switch (this) {
      case TranslationLaneStatus.unspecified:
        return 'Pending';
      case TranslationLaneStatus.idle:
        return 'Idle';
      case TranslationLaneStatus.listening:
        return 'Listening';
      case TranslationLaneStatus.translating:
        return 'Translating';
      case TranslationLaneStatus.ready:
        return 'Ready';
      case TranslationLaneStatus.error:
        return 'Error';
    }
  }

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
      speakerId: json['speaker_id'] as String,
      displayName: json['display_name'] as String,
      languageCode: json['language_code'] as String,
      priority: (json['priority'] as num).toDouble(),
      active: json['active'] as bool,
      isLocked: json['is_locked'] as bool? ?? false,
      frontFacing: json['front_facing'] as bool? ?? false,
      persistenceBonus: (json['persistence_bonus'] as num?)?.toDouble() ?? 0,
      lastUpdatedUnixMs: (json['last_updated_unix_ms'] as num?)?.toInt() ?? 0,
      sourceCaption: json['source_caption'] as String?,
      translatedCaption: json['translated_caption'] as String?,
      targetLanguageCode: json['target_language_code'] as String?,
      laneStatus: TranslationLaneStatusPresentation.fromApiValue(
        json['lane_status'] as String?,
      ),
      statusMessage: json['status_message'] as String?,
    );
  }

  Map<String, dynamic> toJson() {
    return <String, dynamic>{
      'speaker_id': speakerId,
      'display_name': displayName,
      'language_code': languageCode,
      'priority': priority,
      'active': active,
      'is_locked': isLocked,
      'front_facing': frontFacing,
      'persistence_bonus': persistenceBonus,
      'last_updated_unix_ms': lastUpdatedUnixMs,
      'source_caption': sourceCaption,
      'translated_caption': translatedCaption,
      'target_language_code': targetLanguageCode,
      'lane_status': laneStatus.apiValue,
      'status_message': statusMessage,
    };
  }
}
