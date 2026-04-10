import 'package:flutter/material.dart';

import '../../models/session_state.dart';
import '../../services/mock_repository.dart';
import 'speaker_lane.dart';

class SessionScreen extends StatefulWidget {
  const SessionScreen({super.key, MockRepository? repository}) : _repository = repository;

  final MockRepository? _repository;

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  late final SessionScreenController _controller;

  @override
  void initState() {
    super.initState();
    _controller = SessionScreenController(widget._repository ?? MockRepository());
    _controller.loadInitialSession();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Language Field Console'),
        actions: <Widget>[
          IconButton(
            tooltip: 'Refresh session',
            onPressed: _controller.loadInitialSession,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: AnimatedBuilder(
        animation: _controller,
        builder: (BuildContext context, Widget? child) {
          final session = _controller.session;

          return Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text(
                  'Session mode',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 8,
                  children: SessionMode.values
                      .map(
                        (SessionMode mode) => ChoiceChip(
                          label: Text(mode.label),
                          selected: session.mode == mode,
                          onSelected: _controller.loading
                              ? null
                              : (bool selected) {
                                  if (selected) {
                                    _controller.selectMode(mode);
                                  }
                                },
                        ),
                      )
                      .toList(growable: false),
                ),
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Row(
                      children: <Widget>[
                        Expanded(
                          child: _SummaryColumn(
                            label: 'Current mode',
                            value: session.mode.label,
                          ),
                        ),
                        Expanded(
                          child: _SummaryColumn(
                            label: 'Speakers',
                            value: session.speakerCount.toString(),
                          ),
                        ),
                        Expanded(
                          child: _SummaryColumn(
                            label: 'Top speaker',
                            value: session.topSpeakerId ?? 'None',
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                if (_controller.errorMessage != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      _controller.errorMessage!,
                      style: TextStyle(color: Theme.of(context).colorScheme.error),
                    ),
                  ),
                Expanded(
                  child: _controller.loading && session.speakers.isEmpty
                      ? const Center(child: CircularProgressIndicator())
                      : ListView.builder(
                          itemCount: session.speakers.length,
                          itemBuilder: (BuildContext context, int index) {
                            final speaker = session.speakers[index];
                            return SpeakerLane(
                              speaker: speaker,
                              isTopSpeaker: speaker.speakerId == session.topSpeakerId,
                            );
                          },
                        ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

class SessionScreenController extends ChangeNotifier {
  SessionScreenController(this._repository);

  final MockRepository _repository;

  SessionStateModel _session = SessionStateModel.empty();
  bool _loading = false;
  String? _errorMessage;

  SessionStateModel get session => _session;
  bool get loading => _loading;
  String? get errorMessage => _errorMessage;

  Future<void> loadInitialSession() async {
    await _load(_repository.fetchInitialSession);
  }

  Future<void> selectMode(SessionMode mode) async {
    await _load(() => _repository.loadMode(mode));
  }

  Future<void> _load(Future<SessionStateModel> Function() loader) async {
    _loading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      _session = await loader();
    } catch (error) {
      _errorMessage = 'Unable to load session data.';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }
}

class _SummaryColumn extends StatelessWidget {
  const _SummaryColumn({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(label, style: Theme.of(context).textTheme.labelMedium),
        const SizedBox(height: 4),
        Text(
          value,
          style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
        ),
      ],
    );
  }
}
