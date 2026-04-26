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
    final targetLanguage = speaker.targetLanguageCode ?? speaker.languageCode;
    final languageSummary = targetLanguage == speaker.languageCode
        ? '${speaker.languageCode} • ${speaker.active ? 'Active' : 'Idle'}'
        : '${speaker.languageCode} → $targetLanguage • ${speaker.active ? 'Active' : 'Idle'}';
    final statusColor = _statusColor(context, speaker.laneStatus);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colorScheme.surface,
        borderRadius: BorderRadius.circular(16),
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
}
