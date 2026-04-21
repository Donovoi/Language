import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/models/speaker.dart';
import 'package:field_app_flutter/services/mock_repository.dart';
import 'package:flutter_test/flutter_test.dart';

import '../test_support/fake_session_api.dart';

void main() {
  test('load seeds focus mode when the session starts unspecified', () async {
    final api = FakeSessionApi(
      fetchMockSceneHandler: (mode) async => SessionStateModel.fallback(
        mode: mode,
      ),
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

    expect(api.fetchMockSceneModes, <SessionMode>[SessionMode.focus]);
    expect(repository.session.mode, SessionMode.focus);
    expect(repository.errorMessage, isNull);
    expect(repository.isLoading, isFalse);
  });

  test('changeMode falls back to the requested mode when the gateway fails',
      () async {
    final api = FakeSessionApi(
      fetchMockSceneHandler: (_) async => throw Exception('offline'),
    );
    final repository = MockRepository(
      api: api,
      initialSession: SessionStateModel.fallback(mode: SessionMode.focus),
    );

    await repository.changeMode(SessionMode.locked);

    expect(api.fetchMockSceneModes, <SessionMode>[SessionMode.locked]);
    expect(repository.session.mode, SessionMode.locked);
    expect(
      repository.errorMessage,
      'Gateway unavailable. Showing local fallback scene.',
    );
    expect(repository.isLoading, isFalse);
  });

  test('refresh reuses the current mode for the fetch request', () async {
    final api = FakeSessionApi(
      fetchSessionHandler: (mode) async => SessionStateModel.fallback(
        mode: mode ?? SessionMode.focus,
      ),
    );
    final repository = MockRepository(
      api: api,
      initialSession: SessionStateModel.fallback(mode: SessionMode.crowd),
    );

    await repository.refresh();

    expect(api.fetchSessionModes, <SessionMode?>[SessionMode.crowd]);
    expect(repository.session.mode, SessionMode.crowd);
    expect(repository.errorMessage, isNull);
  });
}
