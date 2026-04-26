import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/session_state.dart';
import '../models/session_stream_event.dart';
import 'api_client.dart';

class MockRepository extends ChangeNotifier {
  MockRepository({
    SessionApi? api,
    SessionStateModel? initialSession,
    Duration reconnectDelay = const Duration(seconds: 1),
  })  : _api = api ?? ApiClient(),
        _reconnectDelay = reconnectDelay,
        _session = initialSession ?? SessionStateModel.fallback();

  final SessionApi _api;
  final Duration _reconnectDelay;
  SessionStateModel _session;
  StreamSubscription<SessionStreamEvent>? _liveSubscription;
  bool _isLoading = false;
  bool _isStreaming = false;
  bool _isDisposed = false;
  bool _reconnectScheduled = false;
  int _streamGeneration = 0;
  String? _errorMessage;

  SessionStateModel get session => _session;
  bool get isLoading => _isLoading;
  bool get isStreaming => _isStreaming;
  String? get errorMessage => _errorMessage;

  Future<void> load() async {
    final mode = _session.mode == SessionMode.unspecified
        ? SessionMode.focus
        : _session.mode;
    await _replaceSession(
      () => _api.fetchSession(),
      fallbackMode: mode,
    );
  }

  Future<void> changeMode(SessionMode mode) async {
    await _replaceSession(
      () => _api.setSessionMode(mode),
      fallbackMode: mode,
    );
  }

  Future<void> refresh() async {
    final mode = _session.mode == SessionMode.unspecified
        ? SessionMode.focus
        : _session.mode;
    await _replaceSession(
      () => _api.fetchSession(),
      fallbackMode: mode,
    );
  }

  Future<void> reset() async {
    final mode = _session.mode == SessionMode.unspecified
        ? SessionMode.focus
        : _session.mode;
    await _replaceSession(
      () => _api.resetSession(mode),
      fallbackMode: mode,
    );
  }

  Future<void> setSpeakerLock(String speakerId, bool isLocked) async {
    _isLoading = true;
    _errorMessage = null;
    _notifySafely();

    try {
      _session = await _api.setSpeakerLock(speakerId, isLocked);
      await _restartLiveUpdates();
    } catch (_) {
      _errorMessage = 'Unable to update speaker lock. Session state was preserved.';
    } finally {
      _isLoading = false;
      _notifySafely();
    }
  }

  Future<void> _replaceSession(
    Future<SessionStateModel> Function() loader, {
    required SessionMode fallbackMode,
  }) async {
    _isLoading = true;
    _errorMessage = null;
    _notifySafely();

    try {
      _session = await loader();
      await _restartLiveUpdates();
    } catch (_) {
      await _stopLiveUpdates(notifyListenersOnStop: false);
      _session = SessionStateModel.fallback(mode: fallbackMode);
      _errorMessage = 'Gateway unavailable. Showing local fallback scene.';
    } finally {
      _isLoading = false;
      _notifySafely();
    }
  }

  Future<void> _restartLiveUpdates() async {
    await _stopLiveUpdates(notifyListenersOnStop: false);

    await _startLiveUpdates();
  }

  Future<void> _startLiveUpdates() async {
    final generation = _streamGeneration;
    try {
      _liveSubscription = _api.watchSessionEvents().listen(
            _handleStreamEvent,
            onError: (_) => _handleLiveUpdatesDisconnected(generation),
            onDone: () => _handleLiveUpdatesDisconnected(generation),
          );
      _isStreaming = true;
      _reconnectScheduled = false;
      _errorMessage = null;
    } catch (_) {
      _handleLiveUpdatesDisconnected(generation);
    }
  }

  void _handleLiveUpdatesDisconnected(int generation) {
    if (_isDisposed || generation != _streamGeneration) {
      return;
    }

    _liveSubscription = null;
    _isStreaming = false;
    _errorMessage ??= 'Live updates unavailable. Reconnecting...';
    _notifySafely();
    _scheduleReconnect(generation);
  }

  void _scheduleReconnect(int generation) {
    if (_isDisposed || _isLoading || _reconnectScheduled) {
      return;
    }

    _reconnectScheduled = true;
    unawaited(
      Future<void>.delayed(_reconnectDelay).then((_) async {
        if (_isDisposed || generation != _streamGeneration || _isLoading) {
          _reconnectScheduled = false;
          return;
        }

        _reconnectScheduled = false;
        await _startLiveUpdates();
      }),
    );
  }

  Future<void> _stopLiveUpdates({
    bool notifyListenersOnStop = true,
  }) async {
    _streamGeneration += 1;
    _reconnectScheduled = false;
    await _liveSubscription?.cancel();
    _liveSubscription = null;
    if (_isStreaming) {
      _isStreaming = false;
      if (notifyListenersOnStop && !_isDisposed) {
        notifyListeners();
      }
    }
  }

  void _handleStreamEvent(SessionStreamEvent event) {
    switch (event.type) {
      case SessionStreamEventType.unknown:
        return;
      case SessionStreamEventType.sessionSnapshot:
        if (event.session case final nextSession?) {
          _session = nextSession;
        }
      case SessionStreamEventType.speakerUpdate:
        if (event.speakerEvent case final update?) {
          _session = SessionStateModel(
            sessionId: _session.sessionId,
            mode: _session.mode,
            speakers: _session.speakers
                .map(
                  (speaker) => speaker.speakerId == update.speakerId
                      ? speaker.copyWith(
                          active: update.active,
                          isLocked: update.isLocked,
                          lastUpdatedUnixMs: update.observedUnixMs,
                          sourceCaption: update.sourceCaption,
                          translatedCaption: update.translatedCaption,
                          targetLanguageCode: update.targetLanguageCode,
                          laneStatus: update.laneStatus,
                          statusMessage: update.statusMessage,
                        )
                      : speaker,
                )
                .toList(growable: false),
            topSpeakerId: _session.topSpeakerId,
          );
        }
    }

    _notifySafely();
  }

  void _notifySafely() {
    if (!_isDisposed) {
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _isDisposed = true;
    _streamGeneration += 1;
    unawaited(_liveSubscription?.cancel());
    super.dispose();
  }
}
