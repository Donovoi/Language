import 'dart:async';

import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../../services/microphone_check.dart';

class MicrophoneCheckScreen extends StatefulWidget {
  const MicrophoneCheckScreen({
    super.key,
    this.microphone = const MicrophoneCheck(),
  });
  final MicrophoneCheck microphone;

  @override
  State<MicrophoneCheckScreen> createState() => _MicrophoneCheckScreenState();
}

class _MicrophoneCheckScreenState extends State<MicrophoneCheckScreen>
    with WidgetsBindingObserver {
  MicrophoneClip? _clip;
  bool _permitted = false;
  bool _busy = false;
  int _generation = 0;
  String _status = 'Enable the microphone to begin.';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _refreshPermission();
  }

  Future<void> _refreshPermission() async {
    try {
      final permitted = await widget.microphone.permissionStatus();
      if (mounted) setState(() => _permitted = permitted);
    } catch (_) {
      if (mounted)
        setState(() => _status = 'Microphone checks are available on Android.');
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _refreshPermission();
    } else {
      unawaited(_clear());
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _generation++;
    _clip?.discard();
    unawaited(widget.microphone.clear().catchError((Object _) {}));
    super.dispose();
  }

  Future<void> _enable() async {
    try {
      final permitted = await widget.microphone.requestPermission();
      if (!mounted) return;
      setState(() {
        _permitted = permitted;
        _status = permitted ? 'Ready. Tap Record and speak near the phone.' : 'Microphone permission was denied. Enable it in Android app settings to record.';
      });
    } catch (error) {
      if (mounted) setState(() => _status = _message(error));
    }
  }

  Future<void> _record() async {
    final generation = ++_generation;
    _clip?.discard();
    setState(() {
      _clip = null;
      _busy = true;
      _status = 'Recording for 3 seconds…';
    });
    try {
      final clip = await widget.microphone.capture();
      if (!mounted || generation != _generation) {
        clip.discard();
        return;
      }
      setState(() {
        _clip = clip;
        _status = clip.hasSignal
            ? 'Clip ready. Play it to check what the microphone heard.'
            : 'No usable signal. Check microphone privacy settings and try again.';
      });
    } catch (error) {
      if (mounted && generation == _generation) {
        setState(() => _status = _message(error));
        await _refreshPermission();
      }
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  Future<void> _play() async {
    final generation = ++_generation;
    setState(() {
      _busy = true;
      _status = 'Playing clip…';
    });
    try {
      await widget.microphone.play();
      if (mounted && generation == _generation) {
        setState(
          () => _status =
              'Playback finished. Listen for clear, undistorted sound.',
        );
      }
    } catch (error) {
      if (mounted && generation == _generation) {
        _clip?.discard();
        setState(() {
          _clip = null;
          _status = _message(error);
        });
        await widget.microphone.clear().catchError((Object _) {});
      }
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  Future<void> _clear() async {
    final generation = ++_generation;
    _clip?.discard();
    if (mounted)
      setState(() {
        _clip = null;
        _busy = true;
        _status = 'Discarding clip…';
      });
    try {
      await widget.microphone.clear();
      if (mounted && generation == _generation)
        setState(() => _status = 'Clip discarded.');
    } catch (error) {
      if (mounted && generation == _generation)
        setState(() => _status = _message(error));
    } finally {
      if (mounted && generation == _generation) setState(() => _busy = false);
    }
  }

  String _message(Object error) => error is PlatformException
      ? error.message ?? 'Audio check unavailable. Try again.'
      : 'Audio check unavailable. Try again.';

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Microphone check')),
    body: SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          const Icon(Icons.mic_outlined, size: 56),
          const SizedBox(height: 20),
          const Text('Record a short clip, then listen back.'),
          const SizedBox(height: 8),
          const Text(
            'Audio stays in memory on this phone. Leaving this screen or '
            'switching apps discards it. This check does not translate speech.',
          ),
          const SizedBox(height: 24),
          Text(
            _status,
            key: const Key('microphone-status'),
            semanticsLabel: _status,
          ),
          if (_clip case final clip?) ...[
            const SizedBox(height: 16),
            Text(
              '${clip.seconds.toStringAsFixed(1)} seconds · ${clip.inputName}',
            ),
            Text(
              'Average ${clip.rmsDbfs.toStringAsFixed(1)} dBFS · '
              'Peak ${clip.peakDbfs.toStringAsFixed(1)} dBFS',
            ),
            if (clip.clippedFraction > 0.01)
              const Text(
                'The input is clipping. Move farther from the sound source.',
              ),
          ],
          const SizedBox(height: 24),
          FilledButton.icon(
            onPressed: _busy ? null : (_permitted ? _record : _enable),
            icon: const Icon(Icons.mic),
            label: Text(_permitted ? 'Record 3 seconds' : 'Enable microphone'),
          ),
          const SizedBox(height: 8),
          OutlinedButton.icon(
            onPressed: _busy || _clip?.hasSignal != true ? null : _play,
            icon: const Icon(Icons.play_arrow),
            label: const Text('Play clip'),
          ),
          const SizedBox(height: 8),
          TextButton(
            onPressed: _busy || _clip != null ? _clear : null,
            child: Text(_busy ? 'Stop and discard' : 'Discard clip'),
          ),
        ],
      ),
    ),
  );
}
