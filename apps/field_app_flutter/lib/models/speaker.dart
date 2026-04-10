class Speaker {
  const Speaker({
    required this.speakerId,
    required this.displayName,
    required this.languageCode,
    required this.priority,
    required this.active,
    required this.isLocked,
    required this.lastUpdatedUnixMs,
  });

  final String speakerId;
  final String displayName;
  final String languageCode;
  final double priority;
  final bool active;
  final bool isLocked;
  final int lastUpdatedUnixMs;

  factory Speaker.fromJson(Map<String, dynamic> json) {
    return Speaker(
      speakerId: json['speaker_id'] as String,
      displayName: json['display_name'] as String,
      languageCode: json['language_code'] as String,
      priority: (json['priority'] as num).toDouble(),
      active: json['active'] as bool,
      isLocked: json['is_locked'] as bool? ?? false,
      lastUpdatedUnixMs: (json['last_updated_unix_ms'] as num).toInt(),
    );
  }
}
