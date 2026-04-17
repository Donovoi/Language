import 'package:flutter/foundation.dart';

import '../models/session_state.dart';
import 'api_client.dart';

class MockRepository extends ChangeNotifier {
  MockRepository({
    SessionApi? api,
    SessionStateModel? initialSession,
  })  : _api = api ?? ApiClient(),
        _session = initialSession ?? SessionStateModel.fallback();

  final SessionApi _api;
  SessionStateModel _session;
  bool _isLoading = false;
  String? _errorMessage;

  SessionStateModel get session => _session;
  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;

  Future<void> load() async {
    await _replaceSession(() => _api.fetchMockScene(_session.mode == SessionMode.unspecified ? SessionMode.focus : _session.mode));
  }

  Future<void> changeMode(SessionMode mode) async {
    await _replaceSession(() => _api.fetchMockScene(mode));
  }

  Future<void> refresh() async {
    await _replaceSession(() => _api.fetchSession(mode: _session.mode));
  }

  Future<void> _replaceSession(Future<SessionStateModel> Function() loader) async {
    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _session = await loader();
    } catch (_) {
      _session = SessionStateModel.fallback(mode: _session.mode == SessionMode.unspecified ? SessionMode.focus : _session.mode);
      _errorMessage = 'Gateway unavailable. Showing local fallback scene.';
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }
}
