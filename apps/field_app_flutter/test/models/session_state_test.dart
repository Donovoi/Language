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
    expect(speaker.laneStatus, TranslationLaneStatus.unspecified);
    expect(speaker.translatedCaption, isNull);
    expect(speaker.targetLanguageCode, isNull);
    expect(speaker.overlappingSpeakerIds, isEmpty);
    expect(speaker.inputLevelDbfs, isNull);
    expect(speaker.voiceCloneStatus, isNull);
    expect(speaker.translatedAudioStreamId, isNull);
    expect(speaker.sourceSuppressionMode, SourceSuppressionMode.unspecified);
  });

  test('Speaker.fromJson parses translation and realtime audio fields', () {
    final speaker = Speaker.fromJson(<String, dynamic>{
      'speaker_id': 'speaker-a',
      'display_name': 'Alice',
      'language_code': 'en',
      'priority': 0.9,
      'active': true,
      'source_caption': 'Hola',
      'translated_caption': 'Hello',
      'target_language_code': 'en',
      'lane_status': 'READY',
      'status_message': 'Translation live.',
      'input_level_dbfs': -19.5,
      'output_level_dbfs': -19,
      'overlapping_speaker_ids': <String>['speaker-b'],
      'detected_language_code': 'es',
      'language_confidence': 0.94,
      'voice_clone_id': 'voice-a',
      'voice_clone_status': 'READY',
      'translated_audio_stream_id': 'mix-a-en',
      'original_voice_suppression_db': 6,
      'playback_latency_ms': 310,
      'source_suppression_mode': 'OVERLAY_DUCKING',
    });

    expect(speaker.sourceCaption, 'Hola');
    expect(speaker.translatedCaption, 'Hello');
    expect(speaker.targetLanguageCode, 'en');
    expect(speaker.laneStatus, TranslationLaneStatus.ready);
    expect(speaker.statusMessage, 'Translation live.');
    expect(speaker.inputLevelDbfs, -19.5);
    expect(speaker.outputLevelDbfs, -19);
    expect(speaker.overlappingSpeakerIds, <String>['speaker-b']);
    expect(speaker.detectedLanguageCode, 'es');
    expect(speaker.languageConfidence, 0.94);
    expect(speaker.voiceCloneId, 'voice-a');
    expect(speaker.voiceCloneStatus, 'READY');
    expect(speaker.translatedAudioStreamId, 'mix-a-en');
    expect(speaker.originalVoiceSuppressionDb, 6);
    expect(speaker.playbackLatencyMs, 310);
    expect(speaker.sourceSuppressionMode, SourceSuppressionMode.overlayDucking);
  });
}
