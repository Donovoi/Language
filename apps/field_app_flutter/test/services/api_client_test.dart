import 'dart:convert';
import 'dart:io';

import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('ApiClient sends bearer token when configured', () async {
    final received = <({String method, String path, String? authorization})>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      received.add(
        (
          method: request.method,
          path: request.uri.path,
          authorization: request.headers.value(HttpHeaders.authorizationHeader),
        ),
      );
      request.response
        ..statusCode = HttpStatus.ok
        ..headers.contentType = ContentType.json
        ..write(jsonEncode(<String, Object?>{}));
      await request.response.close();
    });
    addTearDown(() async {
      await subscription.cancel();
      await server.close(force: true);
    });

    final client = ApiClient(
      baseUrl: 'http://127.0.0.1:${server.port}',
      authToken: ' dev-token ',
    );

    await client.startMockLiveIngest(mode: SessionMode.focus);

    expect(
      received,
      <({String method, String path, String? authorization})>[
        (
          method: 'POST',
          path: '/v1/mock/live-ingest',
          authorization: 'Bearer dev-token',
        ),
      ],
    );
  });

  test('ApiClient omits bearer token when auth is unset', () async {
    final received = <({String method, String path, String? authorization})>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      received.add(
        (
          method: request.method,
          path: request.uri.path,
          authorization: request.headers.value(HttpHeaders.authorizationHeader),
        ),
      );
      request.response
        ..statusCode = HttpStatus.ok
        ..headers.contentType = ContentType.json
        ..write(jsonEncode(<String, Object?>{}));
      await request.response.close();
    });
    addTearDown(() async {
      await subscription.cancel();
      await server.close(force: true);
    });

    final client = ApiClient(baseUrl: 'http://127.0.0.1:${server.port}');

    await client.stopMockLiveIngest();

    expect(
      received,
      <({String method, String path, String? authorization})>[
        (
          method: 'DELETE',
          path: '/v1/mock/live-ingest',
          authorization: null,
        ),
      ],
    );
  });
}
