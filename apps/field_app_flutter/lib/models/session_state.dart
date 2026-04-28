import 'speaker.dart';

// Contract-lock manifest: CI compares these keys against `proto/session.proto`.
const String kSessionStateSessionIdJsonKey = 'session_id';
const String kSessionStateModeJsonKey = 'mode';
const String kSessionStateSpeakersJsonKey = 'speakers';
const String kSessionStateTopSpeakerIdJsonKey = 'top_speaker_id';

const List<String> kSessionStateContractFields = <String>[
  kSessionStateSessionIdJsonKey,
  kSessionStateModeJsonKey,
  kSessionStateSpeakersJsonKey,
  kSessionStateTopSpeakerIdJsonKey,
];

enum SessionMode {
  unspecified('SESSION_MODE_UNSPECIFIED', 'UNSPECIFIED', 'Unspecified'),
  focus('SESSION_MODE_FOCUS', 'FOCUS', 'Focus'),
  crowd('SESSION_MODE_CROWD', 'CROWD', 'Crowd'),
  locked('SESSION_MODE_LOCKED', 'LOCKED', 'Locked');

  const SessionMode(this.protoName, this.apiValue, this.label);

  final String protoName;
  final String apiValue;
  final String label;
}

extension SessionModePresentation on SessionMode {

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

  String? get effectiveTopSpeakerId {
    if (topSpeakerId != null &&
        speakers.any((speaker) => speaker.speakerId == topSpeakerId)) {
      return topSpeakerId;
    }
    return speakers.isEmpty ? null : speakers.first.speakerId;
  }

  factory SessionStateModel.fromJson(Map<String, dynamic> json) {
    return SessionStateModel(
      sessionId: json[kSessionStateSessionIdJsonKey] as String,
      mode: SessionModePresentation.fromApiValue(
        json[kSessionStateModeJsonKey] as String,
      ),
      speakers: (json[kSessionStateSpeakersJsonKey] as List<dynamic>)
          .map((item) => Speaker.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
      topSpeakerId: json[kSessionStateTopSpeakerIdJsonKey] as String?,
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
            sourceCaption: 'Let\'s keep the next question short.',
            translatedCaption: 'Let\'s keep the next question short.',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.ready,
            statusMessage: 'Primary lane locked in.',
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
            sourceCaption: 'Posso compartilhar a proxima pergunta agora?',
            translatedCaption: 'Can I share the next question now?',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.ready,
            statusMessage: 'Translation live.',
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
            sourceCaption: 'Main sirf do minute loongi.',
            translatedCaption: 'I\'ll only take two minutes.',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.translating,
            statusMessage: 'Refreshing translation...',
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
            sourceCaption: 'Let\'s keep the next question short.',
            translatedCaption: 'Let\'s keep the next question short.',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.ready,
            statusMessage: 'Translation live.',
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
            sourceCaption: 'Posso compartilhar a proxima pergunta agora?',
            translatedCaption: 'Can I share the next question now?',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.ready,
            statusMessage: 'Translation live.',
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
            sourceCaption: 'Necesito un momento para revisar la cifra.',
            translatedCaption: 'I need a moment to verify the number.',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.ready,
            statusMessage: 'Translation live.',
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
            sourceCaption: 'Posso compartilhar a proxima pergunta agora?',
            translatedCaption: 'Can I share the next question now?',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.ready,
            statusMessage: 'Pinned by operator.',
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
            sourceCaption: 'Let\'s keep the next question short.',
            translatedCaption: 'Let\'s keep the next question short.',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.ready,
            statusMessage: 'Secondary lane ready.',
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
            sourceCaption: 'Main sirf do minute loongi.',
            translatedCaption: 'I\'ll only take two minutes.',
            targetLanguageCode: 'en',
            laneStatus: TranslationLaneStatus.translating,
            statusMessage: 'Refreshing translation...',
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
