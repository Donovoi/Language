import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../models/session_state.dart';
import '../models/session_stream_event.dart';

abstract class SessionApi {
  Future<SessionStateModel> fetchSession({SessionMode? mode});
  Future<SessionStateModel> setSessionMode(SessionMode mode);
  Future<SessionStateModel> resetSession(SessionMode mode);
  Future<SessionStateModel> setSpeakerLock(String speakerId, bool isLocked);
  Future<SessionStateModel> fetchMockScene(SessionMode mode);
  Stream<SessionStreamEvent> watchSessionEvents({SessionMode? mode});
}

class ApiClient implements SessionApi {
  ApiClient({String? baseUrl}) : _baseUrl = baseUrl ?? _defaultBaseUrl();

  final String _baseUrl;

  @override
  Future<SessionStateModel> fetchSession({SessionMode? mode}) async {
    final query = <String, String>{};
    if (mode != null) {
      query['mode'] = mode.apiValue;
    }
    final response = await _readJson(
      Uri.parse(
        '$_baseUrl/v1/session',
      ).replace(queryParameters: query.isEmpty ? null : query),
    );
    return SessionStateModel.fromJson(response);
  }

  @override
  Future<SessionStateModel> setSessionMode(SessionMode mode) async {
    final response = await _readJson(
      Uri.parse('$_baseUrl/v1/session/mode').replace(
        queryParameters: <String, String>{'mode': mode.apiValue},
      ),
      method: 'PUT',
    );
    return SessionStateModel.fromJson(response);
  }

  @override
  Future<SessionStateModel> resetSession(SessionMode mode) async {
    final response = await _readJson(
      Uri.parse('$_baseUrl/v1/session/reset').replace(
        queryParameters: <String, String>{'mode': mode.apiValue},
      ),
      method: 'POST',
    );
    return SessionStateModel.fromJson(response['session'] as Map<String, dynamic>);
  }

  @override
  Future<SessionStateModel> setSpeakerLock(String speakerId, bool isLocked) async {
    final encodedSpeakerId = Uri.encodeComponent(speakerId);
    final response = await _readJson(
      Uri.parse('$_baseUrl/v1/speakers/$encodedSpeakerId/lock'),
      method: isLocked ? 'PUT' : 'DELETE',
    );
    return SessionStateModel.fromJson(response);
  }

  @override
  Future<SessionStateModel> fetchMockScene(SessionMode mode) async {
    final response = await _readJson(
      Uri.parse('$_baseUrl/v1/mock/scene').replace(
        queryParameters: <String, String>{'mode': mode.apiValue},
      ),
    );
    return SessionStateModel.fromJson(response['session'] as Map<String, dynamic>);
  }

  @override
  Stream<SessionStreamEvent> watchSessionEvents({SessionMode? mode}) async* {
    final query = <String, String>{};
    if (mode != null) {
      query['mode'] = mode.apiValue;
    }

    final client = HttpClient();
    final uri = Uri.parse('$_baseUrl/v1/events/stream').replace(
      queryParameters: query.isEmpty ? null : query,
    );

    try {
      final request = await client.getUrl(uri);
      request.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
      final response = await request.close();
      final statusCode = response.statusCode;
      if (statusCode < 200 || statusCode >= 300) {
        throw HttpException('Request failed with status $statusCode', uri: uri);
      }

      final buffer = StringBuffer();
      await for (final line in response
          .transform(utf8.decoder)
          .transform(const LineSplitter())) {
        if (line.isEmpty) {
          if (buffer.isNotEmpty) {
            yield SessionStreamEvent.fromJson(
              jsonDecode(buffer.toString()) as Map<String, dynamic>,
            );
            buffer.clear();
          }
          continue;
        }

        if (line.startsWith('data:')) {
          if (buffer.isNotEmpty) {
            buffer.write('\n');
          }
          buffer.write(line.substring(5).trimLeft());
        }
      }

      if (buffer.isNotEmpty) {
        yield SessionStreamEvent.fromJson(
          jsonDecode(buffer.toString()) as Map<String, dynamic>,
        );
      }
    } finally {
      client.close(force: true);
    }
  }

  Future<Map<String, dynamic>> _readJson(
    Uri uri, {
    String method = 'GET',
  }) async {
    final client = HttpClient();
    try {
      final request = await client.openUrl(method, uri);
      final response = await request.close();
      final payload = await response.transform(utf8.decoder).join();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException('Request failed with status ${response.statusCode}', uri: uri);
      }
      return jsonDecode(payload) as Map<String, dynamic>;
    } finally {
      client.close(force: true);
    }
  }

  static String _defaultBaseUrl() {
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://127.0.0.1:8000';
  }
}
