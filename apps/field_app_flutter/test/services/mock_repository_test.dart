import 'dart:async';

import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/models/session_stream_event.dart';
import 'package:field_app_flutter/models/speaker.dart';
import 'package:field_app_flutter/services/mock_repository.dart';
import 'package:flutter_test/flutter_test.dart';

import '../test_support/fake_session_api.dart';

void main() {
  test('load seeds focus mode when the session starts unspecified', () async {
    final controller = StreamController<SessionStreamEvent>();
    addTearDown(controller.close);
    final api = FakeSessionApi(
      fetchSessionHandler: (_) async => SessionStateModel.fallback(
        mode: SessionMode.focus,
      ),
      watchSessionEventsHandler: (_) => controller.stream,
    );
    final repository = MockRepository(
      api: api,
      initialSession: const SessionStateModel(
        sessionId: 'session-123',
        mode: SessionMode.unspecified,
        speakers: <Speaker>[],
        topSpeakerId: null,
      ),
    );

    await repository.load();

    expect(api.fetchSessionModes, <SessionMode?>[null]);
    expect(api.watchSessionEventsModes, <SessionMode?>[null]);
    expect(repository.session.mode, SessionMode.focus);
    expect(repository.isStreaming, isTrue);
    expect(repository.errorMessage, isNull);
    expect(repository.isLoading, isFalse);

    repository.dispose();
  });

  test('reconnects live updates after the stream closes', () async {
    final firstController = StreamController<SessionStreamEvent>();
    final secondController = StreamController<SessionStreamEvent>();
    addTearDown(firstController.close);
    addTearDown(secondController.close);

    var streamCallCount = 0;
    final api = FakeSessionApi(
      fetchSessionHandler: (_) async => SessionStateModel.fallback(
        mode: SessionMode.focus,
      ),
      watchSessionEventsHandler: (_) {
        streamCallCount += 1;
        return streamCallCount == 1
            ? firstController.stream
            : secondController.stream;
      },
    );
    final repository = MockRepository(
      api: api,
      reconnectDelay: Duration.zero,
      initialSession: const SessionStateModel(
        sessionId: 'session-123',
        mode: SessionMode.unspecified,
        speakers: <Speaker>[],
        topSpeakerId: null,
      ),
    );

    await repository.load();
    await firstController.close();
    await Future<void>.delayed(Duration.zero);
    await Future<void>.delayed(Duration.zero);

    expect(api.watchSessionEventsModes, <SessionMode?>[null, null]);
    expect(repository.isStreaming, isTrue);

    repository.dispose();
  });

  test('changeMode falls back to the requested mode when the gateway fails',
      () async {
    final api = FakeSessionApi(
      setSessionModeHandler: (_) async => throw Exception('offline'),
    );
    final repository = MockRepository(
      api: api,
      initialSession: SessionStateModel.fallback(mode: SessionMode.focus),
    );

    await repository.changeMode(SessionMode.locked);

    expect(api.setSessionModeModes, <SessionMode>[SessionMode.locked]);
    expect(repository.session.mode, SessionMode.locked);
    expect(
      repository.errorMessage,
      'Gateway unavailable. Showing local fallback scene.',
    );
    expect(repository.isLoading, isFalse);
  });

  test('refresh reuses the current mode for the fetch request', () async {
    final controller = StreamController<SessionStreamEvent>();
    addTearDown(controller.close);
    final api = FakeSessionApi(
      fetchSessionHandler: (_) async => SessionStateModel.fallback(
        mode: SessionMode.crowd,
      ),
      watchSessionEventsHandler: (_) => controller.stream,
    );
    final repository = MockRepository(
      api: api,
      initialSession: SessionStateModel.fallback(mode: SessionMode.crowd),
    );

    await repository.refresh();

    expect(api.fetchSessionModes, <SessionMode?>[null]);
    expect(repository.session.mode, SessionMode.crowd);
    expect(repository.errorMessage, isNull);

    repository.dispose();
  });

  test('reset asks the gateway to rebuild the current mode', () async {
    final controller = StreamController<SessionStreamEvent>();
    addTearDown(controller.close);
    final api = FakeSessionApi(
      resetSessionHandler: (mode) async => SessionStateModel.fallback(
        mode: mode,
      ),
      watchSessionEventsHandler: (_) => controller.stream,
    );
    final repository = MockRepository(
      api: api,
      initialSession: SessionStateModel.fallback(mode: SessionMode.locked),
    );

    await repository.reset();

    expect(api.resetSessionModes, <SessionMode>[SessionMode.locked]);
    expect(repository.session.mode, SessionMode.locked);
    expect(repository.errorMessage, isNull);

    repository.dispose();
  });

  test('setSpeakerLock preserves the session if the gateway call fails',
      () async {
    final repository = MockRepository(
      api: FakeSessionApi(
        setSpeakerLockHandler: (_, __) async => throw Exception('offline'),
      ),
      initialSession: SessionStateModel.fallback(mode: SessionMode.focus),
    );

    await repository.setSpeakerLock('speaker-alice', true);

    expect(
      repository.errorMessage,
      'Unable to update speaker lock. Session state was preserved.',
    );
    expect(repository.session.effectiveTopSpeakerId, 'speaker-alice');
    expect(repository.session.speakers.first.isLocked, isFalse);
  });

  test('setSpeakerLock calls the gateway and updates the session', () async {
    final controller = StreamController<SessionStreamEvent>();
    addTearDown(controller.close);
    final api = FakeSessionApi(
      setSpeakerLockHandler: (speakerId, isLocked) async {
        final session = SessionStateModel.fallback(mode: SessionMode.focus);
        final speakers = session.speakers
            .map(
              (speaker) => speaker.speakerId == speakerId
                  ? speaker.copyWith(
                      isLocked: isLocked,
                      statusMessage: 'Pinned by operator.',
                    )
                  : speaker,
            )
            .toList(growable: false);
        return SessionStateModel(
          sessionId: session.sessionId,
          mode: session.mode,
          speakers: speakers,
          topSpeakerId: session.topSpeakerId,
        );
      },
      watchSessionEventsHandler: (_) => controller.stream,
    );
    final repository = MockRepository(
      api: api,
      initialSession: SessionStateModel.fallback(mode: SessionMode.focus),
    );

    await repository.setSpeakerLock('speaker-alice', true);

    expect(
      api.setSpeakerLockRequests,
      <({String speakerId, bool isLocked})>[
        (speakerId: 'speaker-alice', isLocked: true),
      ],
    );
    expect(repository.session.speakers.first.isLocked, isTrue);
    expect(repository.session.speakers.first.statusMessage, 'Pinned by operator.');

    repository.dispose();
  });

  test('applies streamed speaker updates after loading a session', () async {
    final controller = StreamController<SessionStreamEvent>();
    addTearDown(controller.close);
    final api = FakeSessionApi(
      fetchSessionHandler: (_) async => SessionStateModel.fallback(
        mode: SessionMode.focus,
      ),
      watchSessionEventsHandler: (_) => controller.stream,
    );
    final repository = MockRepository(
      api: api,
      initialSession: const SessionStateModel(
        sessionId: 'session-123',
        mode: SessionMode.unspecified,
        speakers: <Speaker>[],
        topSpeakerId: null,
      ),
    );

    await repository.load();

    controller.add(
      const SessionStreamEvent(
        type: SessionStreamEventType.speakerUpdate,
        speakerEvent: SpeakerEventModel(
          speakerId: 'speaker-alice',
          priorityDelta: 0.18,
          active: true,
          isLocked: false,
          observedUnixMs: 1710000000100,
          sourceCaption: 'Bonjour a tous.',
          translatedCaption: 'Hello everyone.',
          targetLanguageCode: 'en',
          laneStatus: TranslationLaneStatus.ready,
          statusMessage: 'Fresh live caption.',
        ),
      ),
    );
    await Future<void>.delayed(Duration.zero);

    expect(repository.session.speakers.first.translatedCaption, 'Hello everyone.');
    expect(repository.session.speakers.first.statusMessage, 'Fresh live caption.');
    expect(repository.session.speakers.first.lastUpdatedUnixMs, 1710000000100);

    repository.dispose();
  });
}
