import 'package:flutter/material.dart';

import '../../models/session_state.dart';
import '../../services/mock_repository.dart';
import 'speaker_lane.dart';

class SessionScreen extends StatefulWidget {
  const SessionScreen({
    super.key,
    required this.repository,
    this.autoLoad = true,
  });

  final MockRepository repository;
  final bool autoLoad;

  @override
  State<SessionScreen> createState() => _SessionScreenState();
}

class _SessionScreenState extends State<SessionScreen> {
  @override
  void initState() {
    super.initState();
    if (widget.autoLoad) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        widget.repository.load();
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.repository,
      builder: (context, _) {
        final session = widget.repository.session;
        final topSpeakerId = session.effectiveTopSpeakerId;
        return Scaffold(
          appBar: AppBar(
            title: const Text('Language Field Console'),
            actions: <Widget>[
              IconButton(
                onPressed: widget.repository.isLoading ? null : widget.repository.reset,
                icon: const Icon(Icons.restart_alt),
                tooltip: 'Reset session',
              ),
              IconButton(
                onPressed:
                    widget.repository.isLoading ? null : widget.repository.refresh,
                icon: const Icon(Icons.refresh),
                tooltip: 'Refresh session',
              ),
            ],
          ),
          body: SafeArea(
            child: Padding(
              padding: const EdgeInsets.all(20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    'Session ${session.sessionId}',
                    style: Theme.of(context).textTheme.labelLarge,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    '${session.mode.label} mode',
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 12,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: widget.repository.isStreaming
                          ? Theme.of(context)
                              .colorScheme
                              .primary
                              .withAlpha(24)
                          : Theme.of(context)
                              .colorScheme
                              .outlineVariant
                              .withAlpha(32),
                      borderRadius: BorderRadius.circular(999),
                    ),
                    child: Text(
                      widget.repository.isStreaming
                          ? 'Live updates connected'
                          : 'Live updates offline',
                      style: Theme.of(context).textTheme.labelLarge?.copyWith(
                            color: widget.repository.isStreaming
                                ? Theme.of(context).colorScheme.primary
                                : Theme.of(context).colorScheme.onSurfaceVariant,
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 8,
                    children: SessionMode.values
                        .where((mode) => mode != SessionMode.unspecified)
                        .map(
                          (mode) => ChoiceChip(
                            label: Text(mode.label),
                            selected: session.mode == mode,
                            onSelected: widget.repository.isLoading
                                ? null
                                : (_) {
                                    widget.repository.changeMode(mode);
                                  },
                          ),
                        )
                        .toList(growable: false),
                  ),
                  if (widget.repository.errorMessage case final message?) ...<Widget>[
                    const SizedBox(height: 12),
                    Text(
                      message,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            color: Theme.of(context).colorScheme.error,
                          ),
                    ),
                  ],
                  const SizedBox(height: 20),
                  Row(
                    children: <Widget>[
                      Text(
                        'Speaker lanes',
                        style: Theme.of(context).textTheme.titleLarge?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                      const SizedBox(width: 12),
                      if (widget.repository.isLoading)
                        const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        ),
                    ],
                  ),
                  const SizedBox(height: 12),
                  Expanded(
                    child: session.speakers.isEmpty
                        ? Center(
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: <Widget>[
                                Icon(
                                  Icons.hearing_disabled_outlined,
                                  size: 36,
                                  color: Theme.of(context)
                                      .colorScheme
                                      .onSurfaceVariant,
                                ),
                                const SizedBox(height: 12),
                                Text(
                                  'No speaker lanes available yet.',
                                  style: Theme.of(context)
                                      .textTheme
                                      .titleMedium
                                      ?.copyWith(fontWeight: FontWeight.w700),
                                  textAlign: TextAlign.center,
                                ),
                                const SizedBox(height: 6),
                                Text(
                                  'Refresh the session or switch modes to load a scene.',
                                  style: Theme.of(context)
                                      .textTheme
                                      .bodyMedium
                                      ?.copyWith(
                                        color: Theme.of(context)
                                            .colorScheme
                                            .onSurfaceVariant,
                                      ),
                                  textAlign: TextAlign.center,
                                ),
                              ],
                            ),
                          )
                        : ListView.separated(
                            itemBuilder: (context, index) {
                              final speaker = session.speakers[index];
                              return SpeakerLane(
                                speaker: speaker,
                                isTopSpeaker: speaker.speakerId == topSpeakerId,
                                onToggleLock: widget.repository.isLoading
                                    ? null
                                    : () {
                                        widget.repository.setSpeakerLock(
                                          speaker.speakerId,
                                          !speaker.isLocked,
                                        );
                                      },
                              );
                            },
                            separatorBuilder: (_, __) =>
                                const SizedBox(height: 12),
                            itemCount: session.speakers.length,
                          ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
