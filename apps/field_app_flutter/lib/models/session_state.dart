import 'speaker.dart';

enum SessionMode { focus, crowd, locked }

extension SessionModeLabel on SessionMode {
  String get apiValue => switch (this) {
        SessionMode.focus => 'FOCUS',
        SessionMode.crowd => 'CROWD',
        SessionMode.locked => 'LOCKED',
      };

  String get label => switch (this) {
        SessionMode.focus => 'Focus',
        SessionMode.crowd => 'Crowd',
        SessionMode.locked => 'Locked',
      };

  static SessionMode fromApi(String value) {
    return switch (value) {
      'CROWD' => SessionMode.crowd,
      'LOCKED' => SessionMode.locked,
      _ => SessionMode.focus,
    };
  }
}

class SessionStateModel {
  const SessionStateModel({
    required this.sessionId,
    required this.mode,
    required this.topSpeakerId,
    required this.speakerCount,
    required this.speakers,
  });

  final String sessionId;
  final SessionMode mode;
  final String? topSpeakerId;
  final int speakerCount;
  final List<Speaker> speakers;

  factory SessionStateModel.fromJson(Map<String, dynamic> json) {
    return SessionStateModel(
      sessionId: json['session_id'] as String,
      mode: SessionModeLabel.fromApi(json['mode'] as String),
      topSpeakerId: json['top_speaker_id'] as String?,
      speakerCount: (json['speaker_count'] as num).toInt(),
      speakers: (json['speakers'] as List<dynamic>)
          .map((dynamic item) => Speaker.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  static SessionStateModel empty() {
    return const SessionStateModel(
      sessionId: 'local-preview',
      mode: SessionMode.focus,
      topSpeakerId: null,
      speakerCount: 0,
      speakers: <Speaker>[],
    );
  }
}
