import 'speaker.dart';

enum SessionMode { unspecified, focus, crowd, locked }

extension SessionModePresentation on SessionMode {
  String get apiValue {
    switch (this) {
      case SessionMode.unspecified:
        return 'UNSPECIFIED';
      case SessionMode.focus:
        return 'FOCUS';
      case SessionMode.crowd:
        return 'CROWD';
      case SessionMode.locked:
        return 'LOCKED';
    }
  }

  String get label {
    switch (this) {
      case SessionMode.unspecified:
        return 'Unspecified';
      case SessionMode.focus:
        return 'Focus';
      case SessionMode.crowd:
        return 'Crowd';
      case SessionMode.locked:
        return 'Locked';
    }
  }

  static SessionMode fromApiValue(String value) {
    return SessionMode.values.firstWhere(
      (mode) => mode.apiValue == value,
      orElse: () => SessionMode.unspecified,
    );
  }
}

class SessionStateModel {
  const SessionStateModel({
    required this.sessionId,
    required this.mode,
    required this.speakers,
    required this.topSpeakerId,
  });

  final String sessionId;
  final SessionMode mode;
  final List<Speaker> speakers;
  final String? topSpeakerId;

  factory SessionStateModel.fromJson(Map<String, dynamic> json) {
    return SessionStateModel(
      sessionId: json['session_id'] as String,
      mode: SessionModePresentation.fromApiValue(json['mode'] as String),
      speakers: (json['speakers'] as List<dynamic>)
          .map((item) => Speaker.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
      topSpeakerId: json['top_speaker_id'] as String?,
    );
  }

  factory SessionStateModel.fallback({SessionMode mode = SessionMode.focus}) {
    final speakers = switch (mode) {
      SessionMode.focus => const <Speaker>[
          Speaker(
            speakerId: 'speaker-alice',
            displayName: 'Alice',
            languageCode: 'en',
            priority: 0.95,
            active: true,
            isLocked: false,
            frontFacing: true,
            persistenceBonus: 0.25,
            lastUpdatedUnixMs: 1710000000000,
          ),
          Speaker(
            speakerId: 'speaker-bruno',
            displayName: 'Bruno',
            languageCode: 'pt-BR',
            priority: 0.76,
            active: true,
            isLocked: false,
            frontFacing: false,
            persistenceBonus: 0.12,
            lastUpdatedUnixMs: 1710000000200,
          ),
          Speaker(
            speakerId: 'speaker-devi',
            displayName: 'Devi',
            languageCode: 'hi',
            priority: 0.71,
            active: true,
            isLocked: false,
            frontFacing: true,
            persistenceBonus: 0.08,
            lastUpdatedUnixMs: 1710000000600,
          ),
        ],
      SessionMode.crowd => const <Speaker>[
          Speaker(
            speakerId: 'speaker-alice',
            displayName: 'Alice',
            languageCode: 'en',
            priority: 0.82,
            active: true,
            isLocked: false,
            frontFacing: true,
            persistenceBonus: 0.18,
            lastUpdatedUnixMs: 1710000000000,
          ),
          Speaker(
            speakerId: 'speaker-bruno',
            displayName: 'Bruno',
            languageCode: 'pt-BR',
            priority: 0.74,
            active: true,
            isLocked: false,
            frontFacing: false,
            persistenceBonus: 0.12,
            lastUpdatedUnixMs: 1710000000200,
          ),
          Speaker(
            speakerId: 'speaker-carmen',
            displayName: 'Carmen',
            languageCode: 'es',
            priority: 0.69,
            active: true,
            isLocked: false,
            frontFacing: false,
            persistenceBonus: 0.05,
            lastUpdatedUnixMs: 1710000000400,
          ),
        ],
      SessionMode.locked => const <Speaker>[
          Speaker(
            speakerId: 'speaker-bruno',
            displayName: 'Bruno',
            languageCode: 'pt-BR',
            priority: 0.70,
            active: true,
            isLocked: true,
            frontFacing: true,
            persistenceBonus: 0.12,
            lastUpdatedUnixMs: 1710000000200,
          ),
          Speaker(
            speakerId: 'speaker-alice',
            displayName: 'Alice',
            languageCode: 'en',
            priority: 0.80,
            active: true,
            isLocked: false,
            frontFacing: true,
            persistenceBonus: 0.18,
            lastUpdatedUnixMs: 1710000000000,
          ),
          Speaker(
            speakerId: 'speaker-devi',
            displayName: 'Devi',
            languageCode: 'hi',
            priority: 0.71,
            active: true,
            isLocked: false,
            frontFacing: true,
            persistenceBonus: 0.08,
            lastUpdatedUnixMs: 1710000000600,
          ),
        ],
      SessionMode.unspecified => const <Speaker>[],
    };

    return SessionStateModel(
      sessionId: 'demo-session',
      mode: mode,
      speakers: speakers,
      topSpeakerId: speakers.isEmpty ? null : speakers.first.speakerId,
    );
  }
}
