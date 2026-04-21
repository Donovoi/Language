import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/services/api_client.dart';

class FakeSessionApi implements SessionApi {
  FakeSessionApi({
    this.fetchSessionHandler,
    this.fetchMockSceneHandler,
  });

  final Future<SessionStateModel> Function(SessionMode? mode)?
      fetchSessionHandler;
  final Future<SessionStateModel> Function(SessionMode mode)?
      fetchMockSceneHandler;

  final List<SessionMode?> fetchSessionModes = <SessionMode?>[];
  final List<SessionMode> fetchMockSceneModes = <SessionMode>[];

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
  Future<SessionStateModel> fetchMockScene(SessionMode mode) {
    fetchMockSceneModes.add(mode);
    final handler = fetchMockSceneHandler;
    if (handler == null) {
      throw UnimplementedError('fetchMockSceneHandler was not provided.');
    }
    return handler(mode);
  }
}
