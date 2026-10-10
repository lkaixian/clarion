import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Small titled card used throughout the Home screen — equivalent to the
/// `<Card>` helper component in the reference React Native app.
class SectionCard extends StatelessWidget {
  const SectionCard({super.key, required this.title, required this.child});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: context.palette.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: context.palette.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(fontWeight: FontWeight.bold, color: context.palette.primary, fontSize: 14),
          ),
          const SizedBox(height: 8),
          child,
        ],
      ),
    );
  }
}
