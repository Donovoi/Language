import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/models/session_stream_event.dart';
import 'package:field_app_flutter/services/api_client.dart';

class FakeSessionApi implements SessionApi {
  FakeSessionApi({
    this.fetchSessionHandler,
    this.setSessionModeHandler,
    this.resetSessionHandler,
    this.setSpeakerLockHandler,
    this.fetchMockSceneHandler,
    this.startMockLiveIngestHandler,
    this.stopMockLiveIngestHandler,
    this.watchSessionEventsHandler,
  });

  final Future<SessionStateModel> Function(SessionMode? mode)? fetchSessionHandler;
  final Future<SessionStateModel> Function(SessionMode mode)?
      setSessionModeHandler;
  final Future<SessionStateModel> Function(SessionMode mode)?
      resetSessionHandler;
  final Future<SessionStateModel> Function(String speakerId, bool isLocked)?
      setSpeakerLockHandler;
  final Future<SessionStateModel> Function(SessionMode mode)?
      fetchMockSceneHandler;
  final Future<void> Function(SessionMode mode, int intervalMs)?
      startMockLiveIngestHandler;
  final Future<void> Function()? stopMockLiveIngestHandler;
  final Stream<SessionStreamEvent> Function(SessionMode? mode)?
      watchSessionEventsHandler;

  final List<SessionMode?> fetchSessionModes = <SessionMode?>[];
  final List<SessionMode> setSessionModeModes = <SessionMode>[];
  final List<SessionMode> resetSessionModes = <SessionMode>[];
  final List<({String speakerId, bool isLocked})> setSpeakerLockRequests =
      <({String speakerId, bool isLocked})>[];
  final List<SessionMode> fetchMockSceneModes = <SessionMode>[];
  final List<({SessionMode mode, int intervalMs})> startMockLiveIngestRequests =
      <({SessionMode mode, int intervalMs})>[];
  int stopMockLiveIngestCallCount = 0;
  final List<SessionMode?> watchSessionEventsModes = <SessionMode?>[];

  @override
  Future<SessionStateModel> fetchSession({SessionMode? mode}) {
    fetchSessionModes.add(mode);
    final handler = fetchSessionHandler;
    if (handler == null) {
      throw UnimplementedError('fetchSessionHandler was not provided.');
    }
    return handler(mode);
  }

  @override
  Future<SessionStateModel> setSessionMode(SessionMode mode) {
    setSessionModeModes.add(mode);
    final handler = setSessionModeHandler;
    if (handler == null) {
      throw UnimplementedError('setSessionModeHandler was not provided.');
    }
    return handler(mode);
  }

  @override
  Future<SessionStateModel> resetSession(SessionMode mode) {
    resetSessionModes.add(mode);
    final handler = resetSessionHandler;
    if (handler == null) {
      throw UnimplementedError('resetSessionHandler was not provided.');
    }
    return handler(mode);
  }

  @override
  Future<SessionStateModel> setSpeakerLock(String speakerId, bool isLocked) {
    setSpeakerLockRequests.add((speakerId: speakerId, isLocked: isLocked));
    final handler = setSpeakerLockHandler;
    if (handler == null) {
      throw UnimplementedError('setSpeakerLockHandler was not provided.');
    }
    return handler(speakerId, isLocked);
  }

  @override
  Future<SessionStateModel> fetchMockScene(SessionMode mode) {
    fetchMockSceneModes.add(mode);
    final handler = fetchMockSceneHandler;
    if (handler == null) {
      throw UnimplementedError('fetchMockSceneHandler was not provided.');
    }
    return handler(mode);
  }

  @override
  Future<void> startMockLiveIngest({
    required SessionMode mode,
    int intervalMs = 350,
  }) {
    startMockLiveIngestRequests.add((mode: mode, intervalMs: intervalMs));
    final handler = startMockLiveIngestHandler;
    if (handler == null) {
      throw UnimplementedError('startMockLiveIngestHandler was not provided.');
    }
    return handler(mode, intervalMs);
  }

  @override
  Future<void> stopMockLiveIngest() {
    stopMockLiveIngestCallCount += 1;
    final handler = stopMockLiveIngestHandler;
    if (handler == null) {
      throw UnimplementedError('stopMockLiveIngestHandler was not provided.');
    }
    return handler();
  }

  @override
  Stream<SessionStreamEvent> watchSessionEvents({SessionMode? mode}) {
    watchSessionEventsModes.add(mode);
    final handler = watchSessionEventsHandler;
    if (handler == null) {
      throw UnimplementedError('watchSessionEventsHandler was not provided.');
    }
    return handler(mode);
  }
}
