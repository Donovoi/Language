import 'package:flutter/material.dart';

import '../../models/speaker.dart';
import 'priority_badge.dart';

class SpeakerLane extends StatelessWidget {
  const SpeakerLane({
    super.key,
    required this.speaker,
    required this.isTopSpeaker,
    this.onToggleLock,
  });

  final Speaker speaker;
  final bool isTopSpeaker;
  final VoidCallback? onToggleLock;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    final translatedCaption = speaker.translatedCaption;
    final sourceCaption = speaker.sourceCaption;
    final statusMessage = speaker.statusMessage;
    final sourceLanguage = speaker.detectedLanguageCode ?? speaker.languageCode;
    final targetLanguage = speaker.targetLanguageCode ?? 'en';
    final confidenceLabel = speaker.languageConfidence == null
        ? null
        : '${(speaker.languageConfidence! * 100).round()}%';
    final languageSummary = targetLanguage == sourceLanguage
        ? '$sourceLanguage${confidenceLabel == null ? '' : ' $confidenceLabel'}'
            ' • ${speaker.active ? 'Active' : 'Idle'}'
        : '$sourceLanguage → $targetLanguage'
            '${confidenceLabel == null ? '' : ' $confidenceLabel'}'
            ' • ${speaker.active ? 'Active' : 'Idle'}';
    final statusColor = _statusColor(context, speaker.laneStatus);
    final volumeLabel = _volumeLabel(
      speaker.inputLevelDbfs,
      speaker.outputLevelDbfs,
    );
    final suppressionLabel = _suppressionLabel(
      speaker.sourceSuppressionMode,
      speaker.originalVoiceSuppressionDb,
    );
    final latencyLabel = speaker.playbackLatencyMs == null ||
            speaker.playbackLatencyMs == 0
        ? null
        : '${speaker.playbackLatencyMs} ms';

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colorScheme.surface,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: isTopSpeaker ? colorScheme.primary : colorScheme.outlineVariant,
          width: isTopSpeaker ? 2 : 1,
        ),
      ),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Row(
                  children: <Widget>[
                    Expanded(
                      child: Text(
                        speaker.displayName,
                        style: Theme.of(context).textTheme.titleMedium?.copyWith(
                              fontWeight: FontWeight.w700,
                            ),
                      ),
                    ),
                    IconButton(
                      onPressed: onToggleLock,
                      icon: Icon(
                        speaker.isLocked ? Icons.lock : Icons.lock_open,
                        size: 18,
                      ),
                      tooltip: speaker.isLocked
                          ? 'Unlock speaker ${speaker.displayName}'
                          : 'Lock speaker ${speaker.displayName}',
                      visualDensity: VisualDensity.compact,
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  languageSummary,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 4),
                Text(
                  isTopSpeaker ? 'Primary translation target' : 'Queued for translation mix',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                      ),
                ),
                if (translatedCaption != null && translatedCaption.isNotEmpty) ...<Widget>[
                  const SizedBox(height: 12),
                  Text(
                    translatedCaption,
                    style: Theme.of(context).textTheme.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                ],
                if (sourceCaption != null &&
                    sourceCaption.isNotEmpty &&
                    sourceCaption != translatedCaption) ...<Widget>[
                  const SizedBox(height: 6),
                  Text(
                    'Source: $sourceCaption',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                        ),
                  ),
                ],
                const SizedBox(height: 10),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: statusColor.withAlpha(24),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    speaker.laneStatus.label,
                    style: Theme.of(context).textTheme.labelMedium?.copyWith(
                          color: statusColor,
                          fontWeight: FontWeight.w700,
                        ),
                  ),
                ),
                if (statusMessage != null && statusMessage.isNotEmpty) ...<Widget>[
                  const SizedBox(height: 8),
                  Text(
                    statusMessage,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                        ),
                  ),
                ],
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: <Widget>[
                    if (volumeLabel != null)
                      _MetricChip(
                        icon: Icons.graphic_eq,
                        label: volumeLabel,
                      ),
                    if (speaker.voiceCloneStatus != null)
                      _MetricChip(
                        icon: Icons.record_voice_over,
                        label: 'Voice ${speaker.voiceCloneStatus}',
                      ),
                    if (speaker.translatedAudioStreamId != null)
                      const _MetricChip(
                        icon: Icons.volume_up,
                        label: 'English voice ready',
                      ),
                    if (suppressionLabel != null)
                      _MetricChip(
                        icon: Icons.tune,
                        label: suppressionLabel,
                      ),
                    if (speaker.overlappingSpeakerIds.isNotEmpty)
                      _MetricChip(
                        icon: Icons.groups,
                        label:
                            '${speaker.overlappingSpeakerIds.length + 1} overlapping',
                      ),
                    if (latencyLabel != null)
                      _MetricChip(
                        icon: Icons.speed,
                        label: latencyLabel,
                      ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          PriorityBadge(priority: speaker.priority, isTopSpeaker: isTopSpeaker),
        ],
      ),
    );
  }

  Color _statusColor(BuildContext context, TranslationLaneStatus status) {
    final colorScheme = Theme.of(context).colorScheme;
    switch (status) {
      case TranslationLaneStatus.unspecified:
        return colorScheme.onSurfaceVariant;
      case TranslationLaneStatus.idle:
        return colorScheme.outline;
      case TranslationLaneStatus.listening:
        return colorScheme.secondary;
      case TranslationLaneStatus.translating:
        return colorScheme.tertiary;
      case TranslationLaneStatus.ready:
        return colorScheme.primary;
      case TranslationLaneStatus.error:
        return colorScheme.error;
    }
  }

  String? _volumeLabel(double? inputLevelDbfs, double? outputLevelDbfs) {
    if (inputLevelDbfs == null && outputLevelDbfs == null) {
      return null;
    }
    final input = inputLevelDbfs == null ? '--' : '${inputLevelDbfs.round()}';
    final output =
        outputLevelDbfs == null ? '--' : '${outputLevelDbfs.round()}';
    return '$input dBFS → $output dBFS';
  }

  String? _suppressionLabel(
    SourceSuppressionMode mode,
    double? amountDb,
  ) {
    final amountLabel = amountDb == null || amountDb <= 0
        ? null
        : '${amountDb.round()} dB';
    switch (mode) {
      case SourceSuppressionMode.unspecified:
        return amountLabel == null ? null : 'Overlay target $amountLabel';
      case SourceSuppressionMode.unavailable:
        return 'Suppression unavailable';
      case SourceSuppressionMode.overlayDucking:
        return amountLabel == null
            ? 'Overlay ducking'
            : 'Overlay target $amountLabel';
      case SourceSuppressionMode.headphoneIsolated:
        return amountLabel == null
            ? 'Headphone isolated'
            : 'Headphone isolated $amountLabel';
      case SourceSuppressionMode.trueCancellation:
        return amountLabel == null
            ? 'Cancellation measured'
            : 'Cancellation measured $amountLabel';
    }
  }
}

class _MetricChip extends StatelessWidget {
  const _MetricChip({
    required this.icon,
    required this.label,
  });

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
      decoration: BoxDecoration(
        color: colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(icon, size: 14, color: colorScheme.onSurfaceVariant),
          const SizedBox(width: 5),
          Text(
            label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                  fontWeight: FontWeight.w600,
                ),
          ),
        ],
      ),
    );
  }
}
