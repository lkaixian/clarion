import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../l10n/generated/app_localizations.dart';
import '../providers/auth_provider.dart';
import '../providers/queue_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/common.dart';
import '../widgets/profile_switcher.dart';
import 'care_screen.dart';
import 'home_screen.dart';
import 'profile_screen.dart';
import 'queue_status_screen.dart';
import 'scan_hub_screen.dart';

const _kHome = 0, _kCare = 1, _kScan = 2, _kQueue = 3, _kProfile = 4;

/// The signed-in app for every account: five tabs with the Scan hub raised
/// in the centre. Tabs are built on first visit and then kept alive.
class MainShell extends StatefulWidget {
  const MainShell({super.key});

  @override
  State<MainShell> createState() => _MainShellState();
}

class _MainShellState extends State<MainShell> {
  int _index = _kHome;
  final _visited = <int>{_kHome};

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      refreshPatientData(context);
      _showLinkRemovedNotice();
    });
  }

  /// A fresh shell is built whenever the active profile changes (see app.dart),
  /// so this runs right after "no longer act for this profile" falls back.
  void _showLinkRemovedNotice() {
    final auth = context.read<AuthProvider>();
    if (!auth.actingLinkRemoved) return;
    auth.actingLinkRemoved = false;
    clearCachedPatientData(context);
    context.snack(AppLocalizations.of(context).familyLinkRemoved);
  }

  void _go(int i) => setState(() {
        _index = i;
        _visited.add(i);
      });

  void _onCheckedIn() {
    _go(_kQueue);
    final patientId = context.read<AuthProvider>().user?.patientId;
    if (patientId != null) context.read<QueueProvider>().refresh(patientId);
  }

  Widget _tab(int i) {
    if (!_visited.contains(i)) return const SizedBox.shrink();
    switch (i) {
      case _kHome:
        return const HomeScreen();
      case _kCare:
        return const CareScreen();
      case _kScan:
        return ScanHubScreen(active: _index == _kScan, onCheckedIn: _onCheckedIn);
      case _kQueue:
        return QueueStatusScreen(active: _index == _kQueue, onScan: () => _go(_kScan));
      default:
        return const ProfileScreen();
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final items = <_NavSpec>[
      _NavSpec(_kHome, Icons.home_outlined, Icons.home, l10n.navHome),
      _NavSpec(_kCare, Icons.favorite_border, Icons.favorite, l10n.navCare),
      _NavSpec(_kScan, Icons.qr_code_scanner, Icons.qr_code_scanner, l10n.navScan),
      _NavSpec(_kQueue, Icons.confirmation_number_outlined, Icons.confirmation_number, l10n.navQueue),
      _NavSpec(_kProfile, Icons.person_outline, Icons.person, l10n.navProfile),
    ];

    return PopScope(
      canPop: _index == _kHome,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _go(_kHome);
      },
      child: Scaffold(
        body: IndexedStack(index: _index, children: [for (var i = 0; i < 5; i++) _tab(i)]),
        bottomNavigationBar: _ShellNavBar(items: items, selected: _index, onSelect: _go),
      ),
    );
  }
}

class _NavSpec {
  const _NavSpec(this.index, this.icon, this.selectedIcon, this.label);
  final int index;
  final IconData icon;
  final IconData selectedIcon;
  final String label;
}

/// Bottom bar in the app's Material 3 style (surface, chipBg indicator pill).
/// The centre item is a 56dp filled circle that rises above the bar.
class _ShellNavBar extends StatelessWidget {
  const _ShellNavBar({required this.items, required this.selected, required this.onSelect});

  final List<_NavSpec> items;
  final int selected;
  final ValueChanged<int> onSelect;

  static const _barHeight = 64.0;
  static const _raise = 20.0;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    // Fixed-height bar: keep large system text from overflowing the labels.
    final media = MediaQuery.of(context);
    return MediaQuery(
      data: media.copyWith(textScaler: media.textScaler.clamp(maxScaleFactor: 1.3)),
      child: Material(
        color: p.surface,
        child: SafeArea(
          top: false,
          child: SizedBox(
            height: _barHeight + _raise,
            child: Stack(
              children: [
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  height: _barHeight,
                  child: DecoratedBox(
                    decoration: BoxDecoration(border: Border(top: BorderSide(color: p.border))),
                  ),
                ),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    for (final item in items)
                      Expanded(
                        child: item.index == _kScan
                            ? _ScanItem(item: item, selected: selected == item.index, onTap: () => onSelect(item.index))
                            : _NavItem(item: item, selected: selected == item.index, onTap: () => onSelect(item.index)),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.item, required this.selected, required this.onTap});
  final _NavSpec item;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final color = selected ? p.primary : p.textMuted;
    return Semantics(
      button: true,
      selected: selected,
      label: item.label,
      excludeSemantics: true,
      onTap: onTap,
      child: InkWell(
        key: Key('nav-${item.index}'),
        onTap: onTap,
        child: SizedBox(
          height: _ShellNavBar._barHeight,
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                width: 56,
                height: 28,
                decoration: BoxDecoration(
                  color: selected ? p.chipBg : Colors.transparent,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(selected ? item.selectedIcon : item.icon, size: 22, color: color),
              ),
              const SizedBox(height: 2),
              Text(
                item.label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 12, fontWeight: selected ? FontWeight.w700 : FontWeight.w500, color: color),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ScanItem extends StatelessWidget {
  const _ScanItem({required this.item, required this.selected, required this.onTap});
  final _NavSpec item;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Semantics(
      button: true,
      selected: selected,
      label: item.label,
      excludeSemantics: true,
      onTap: onTap,
      child: InkWell(
        key: Key('nav-${item.index}'),
        onTap: onTap,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.end,
          children: [
            Container(
              width: 56,
              height: 56,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: p.primary,
                shape: BoxShape.circle,
                // Ring in the surface colour separates the circle from the bar edge.
                border: Border.all(color: p.surface, width: 3),
              ),
              child: Icon(Icons.qr_code_scanner, size: 28, color: context.onFill),
            ),
            const SizedBox(height: 2),
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                item.label,
                maxLines: 1,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: selected ? p.primary : p.textMuted,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
