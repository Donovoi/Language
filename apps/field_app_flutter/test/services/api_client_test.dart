import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:field_app_flutter/models/session_state.dart';
import 'package:field_app_flutter/services/api_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('cancelling an idle SSE stream closes it without another event', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => server.close(force: true));
    final requests = server.listen((request) async {
      request.response.bufferOutput = false;
      request.response.headers.contentType = ContentType(
        'text',
        'event-stream',
      );
      request.response.write('data: {}\n\n');
      await request.response.flush();
      // Deliberately keep the connection open and send no further data.
    });
    addTearDown(requests.cancel);
    final firstEvent = Completer<void>();
    final client = ApiClient(baseUrl: 'http://127.0.0.1:${server.port}');
    final events = client.watchSessionEvents().listen((_) {
      if (!firstEvent.isCompleted) firstEvent.complete();
    });
    await firstEvent.future.timeout(const Duration(seconds: 5));
    // Let the generator resume after yielding and start waiting for more bytes.
    await Future<void>.delayed(Duration.zero);
    await events.cancel().timeout(const Duration(seconds: 1));
  });

  test('ApiClient sends bearer token when configured', () async {
    final received = <({String method, String path, String? authorization})>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      received.add((
        method: request.method,
        path: request.uri.path,
        authorization: request.headers.value(HttpHeaders.authorizationHeader),
      ));
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

    expect(received, <({String method, String path, String? authorization})>[
      (
        method: 'POST',
        path: '/v1/mock/live-ingest',
        authorization: 'Bearer dev-token',
      ),
    ]);
  });

  test('ApiClient omits bearer token when auth is unset', () async {
    final received = <({String method, String path, String? authorization})>[];
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final subscription = server.listen((request) async {
      received.add((
        method: request.method,
        path: request.uri.path,
        authorization: request.headers.value(HttpHeaders.authorizationHeader),
      ));
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

    expect(received, <({String method, String path, String? authorization})>[
      (method: 'DELETE', path: '/v1/mock/live-ingest', authorization: null),
    ]);
  });
}
