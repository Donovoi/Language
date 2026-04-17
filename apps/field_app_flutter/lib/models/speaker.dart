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
    };
  }
}
