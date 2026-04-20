import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/models/speaker.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('SessionStateModel.effectiveTopSpeakerId', () {
    test('uses the declared top speaker when it is present', () {
      const session = SessionStateModel(
        sessionId: 'session-123',
        mode: SessionMode.focus,
        speakers: <Speaker>[
          Speaker(
            speakerId: 'speaker-a',
            displayName: 'Alice',
            languageCode: 'en',
            priority: 0.9,
            active: true,
            isLocked: false,
            frontFacing: true,
            persistenceBonus: 0.2,
            lastUpdatedUnixMs: 1,
          ),
          Speaker(
            speakerId: 'speaker-b',
            displayName: 'Bruno',
            languageCode: 'pt-BR',
            priority: 0.8,
            active: true,
            isLocked: false,
            frontFacing: false,
            persistenceBonus: 0.1,
            lastUpdatedUnixMs: 2,
          ),
        ],
        topSpeakerId: 'speaker-b',
      );

      expect(session.effectiveTopSpeakerId, 'speaker-b');
    });

    test('falls back to the first speaker when top speaker is missing', () {
      const session = SessionStateModel(
        sessionId: 'session-123',
        mode: SessionMode.focus,
        speakers: <Speaker>[
          Speaker(
            speakerId: 'speaker-a',
            displayName: 'Alice',
            languageCode: 'en',
            priority: 0.9,
            active: true,
            isLocked: false,
            frontFacing: true,
            persistenceBonus: 0.2,
            lastUpdatedUnixMs: 1,
          ),
          Speaker(
            speakerId: 'speaker-b',
            displayName: 'Bruno',
            languageCode: 'pt-BR',
            priority: 0.8,
            active: true,
            isLocked: false,
            frontFacing: false,
            persistenceBonus: 0.1,
            lastUpdatedUnixMs: 2,
          ),
        ],
        topSpeakerId: 'speaker-missing',
      );

      expect(session.effectiveTopSpeakerId, 'speaker-a');
    });
  });

  test('Speaker.fromJson applies defaults for optional fields', () {
    final speaker = Speaker.fromJson(<String, dynamic>{
      'speaker_id': 'speaker-a',
      'display_name': 'Alice',
      'language_code': 'en',
      'priority': 0.9,
      'active': true,
    });

    expect(speaker.isLocked, isFalse);
    expect(speaker.frontFacing, isFalse);
    expect(speaker.persistenceBonus, 0);
    expect(speaker.lastUpdatedUnixMs, 0);
  });
}
