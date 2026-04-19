import 'package:flutter/material.dart';

import '../../models/speaker.dart';
import 'priority_badge.dart';

class SpeakerLane extends StatelessWidget {
  const SpeakerLane({
    super.key,
    required this.speaker,
    required this.isTopSpeaker,
  });

  final Speaker speaker;
  final bool isTopSpeaker;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;
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
                    if (speaker.isLocked)
                      const Padding(
                        padding: EdgeInsets.only(left: 8),
                        child: Icon(Icons.lock, size: 18),
                      ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  '${speaker.languageCode} • ${speaker.active ? 'Active' : 'Idle'}',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 4),
                Text(
                  isTopSpeaker ? 'Primary translation target' : 'Queued for translation mix',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                      ),
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
}
