import '../models/session_state.dart';
import 'api_client.dart';

class MockRepository {
  MockRepository({ApiClient? apiClient}) : _apiClient = apiClient ?? ApiClient();

  final ApiClient _apiClient;

  Future<SessionStateModel> fetchInitialSession() async {
    try {
      final payload = await _apiClient.getJson('/v1/session');
      return SessionStateModel.fromJson(payload);
    } catch (_) {
      return _sessionForMode(SessionMode.focus);
    }
  }

  Future<SessionStateModel> loadMode(SessionMode mode) async {
    try {
      final payload = await _apiClient.getJson(
        '/v1/mock/scene',
        queryParameters: <String, String>{'mode': mode.apiValue},
      );
      return SessionStateModel.fromJson(payload['session'] as Map<String, dynamic>);
    } catch (_) {
      return _sessionForMode(mode);
    }
  }

  SessionStateModel _sessionForMode(SessionMode mode) {
    final Map<SessionMode, Map<String, dynamic>> payloads = <SessionMode, Map<String, dynamic>>{
      SessionMode.focus: <String, dynamic>{
        'session_id': 'local-preview',
        'mode': 'FOCUS',
        'top_speaker_id': 'speaker-01',
        'speaker_count': 4,
        'speakers': <Map<String, dynamic>>[
          _speaker('speaker-01', 'Alex', 'en-us', 1.27, true, false, 1712745001000),
          _speaker('speaker-02', 'Mina', 'ko-kr', 0.98, true, false, 1712745001200),
          _speaker('speaker-03', 'Luis', 'es-es', 0.23, false, false, 1712744999000),
          _speaker('speaker-04', 'Nora', 'fr-fr', 0.16, false, false, 1712744997000),
        ],
      },
      SessionMode.crowd: <String, dynamic>{
        'session_id': 'local-preview',
        'mode': 'CROWD',
        'top_speaker_id': 'speaker-02',
        'speaker_count': 5,
        'speakers': <Map<String, dynamic>>[
          _speaker('speaker-02', 'Mina', 'ko-kr', 0.88, true, false, 1712745001200),
          _speaker('speaker-01', 'Alex', 'en-us', 0.82, true, false, 1712745001000),
          _speaker('speaker-03', 'Luis', 'es-es', 0.79, true, false, 1712745001400),
          _speaker('speaker-05', 'Jae', 'ja-jp', 0.72, true, false, 1712745001600),
          _speaker('speaker-04', 'Nora', 'fr-fr', 0.54, false, false, 1712744997000),
        ],
      },
      SessionMode.locked: <String, dynamic>{
        'session_id': 'local-preview',
        'mode': 'LOCKED',
        'top_speaker_id': 'speaker-02',
        'speaker_count': 4,
        'speakers': <Map<String, dynamic>>[
          _speaker('speaker-02', 'Mina', 'ko-kr', 1.63, true, true, 1712745001200),
          _speaker('speaker-01', 'Alex', 'en-us', 0.94, true, false, 1712745001000),
          _speaker('speaker-03', 'Luis', 'es-es', 0.39, false, false, 1712744999000),
          _speaker('speaker-04', 'Nora', 'fr-fr', 0.34, false, false, 1712744997000),
        ],
      },
    };

    return SessionStateModel.fromJson(payloads[mode]!);
  }

  static Map<String, dynamic> _speaker(
    String speakerId,
    String displayName,
    String languageCode,
    double priority,
    bool active,
    bool isLocked,
    int lastUpdatedUnixMs,
  ) {
    return <String, dynamic>{
      'speaker_id': speakerId,
      'display_name': displayName,
      'language_code': languageCode,
      'priority': priority,
      'active': active,
      'is_locked': isLocked,
      'last_updated_unix_ms': lastUpdatedUnixMs,
    };
  }
}
