import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';
import '../theme/app_theme.dart';

/// FIX for "UI looks cluttered — long lists need a top-5-plus-expand or
/// scrollable treatment": several [SectionCard] bodies on the Home screen
/// (conditions, medications, allergies, encounters, documents) used to
/// render every item unconditionally, which meant a patient with a long
/// history pushed the whole screen down indefinitely and buried the
/// sections below it. This shows only the first [collapsedCount] items by
/// default with a "Show N more" affordance that reveals the rest in place
/// (no navigation, no new screen) — kept as a shared widget (alongside
/// [SectionCard]) rather than a one-off per section, since the same
/// truncate-then-expand shape is used identically across every long list
/// on Home.
class ExpandableItemList extends StatefulWidget {
  const ExpandableItemList({
    super.key,
    required this.items,
    this.collapsedCount = 5,
  });

  final List<Widget> items;
  final int collapsedCount;

  @override
  State<ExpandableItemList> createState() => _ExpandableItemListState();
}

class _ExpandableItemListState extends State<ExpandableItemList> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final overflowCount = widget.items.length - widget.collapsedCount;
    final hasOverflow = overflowCount > 0;
    final visible = (_expanded || !hasOverflow)
        ? widget.items
        : widget.items.take(widget.collapsedCount).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ...visible,
        if (hasOverflow)
          InkWell(
            borderRadius: BorderRadius.circular(6),
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.only(top: 4, bottom: 2),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    _expanded
                        ? l10n.showLessAction
                        : l10n.showMoreAction(overflowCount),
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: context.palette.primary,
                    ),
                  ),
                  Icon(
                    _expanded
                        ? Icons.keyboard_arrow_up
                        : Icons.keyboard_arrow_down,
                    size: 18,
                    color: context.palette.primary,
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
