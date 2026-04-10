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
    final Color borderColor = isTopSpeaker
        ? Theme.of(context).colorScheme.primary
        : Theme.of(context).colorScheme.outlineVariant;

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: borderColor, width: isTopSpeaker ? 2 : 1),
        ),
        padding: const EdgeInsets.all(16),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
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
                      if (isTopSpeaker)
                        Text(
                          'TOP',
                          style: Theme.of(context).textTheme.labelMedium?.copyWith(
                                color: Theme.of(context).colorScheme.primary,
                                fontWeight: FontWeight.w700,
                              ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: <Widget>[
                      _MetaChip(label: speaker.languageCode.toUpperCase()),
                      _MetaChip(label: speaker.active ? 'ACTIVE' : 'IDLE'),
                      if (speaker.isLocked) const _MetaChip(label: 'LOCKED'),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(width: 12),
            PriorityBadge(priority: speaker.priority, highlighted: isTopSpeaker),
          ],
        ),
      ),
    );
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHigh,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.labelMedium,
      ),
    );
  }
}
