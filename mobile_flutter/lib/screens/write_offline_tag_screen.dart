import 'package:flutter/material.dart';
import 'package:nfc_manager/nfc_manager.dart' show NfcAvailability;

import '../l10n/generated/app_localizations.dart';
import '../services/nfc_service.dart';
import '../services/tag_crypto.dart';
import '../theme/app_theme.dart';

/// Staff-only screen: writes a compact offline-fallback text directly onto
/// a physical NFC tag's own NDEF memory (see
/// `backend/app/routers/emergency.py::_build_compact_tag_text`'s
/// docstring for the full rationale). The text itself is produced by the
/// WEB console's "Register NFC Card" flow (`POST /emergency/nfc/register`
/// returns the sealed `tag_blob` alongside the UID grant) -- staff copies it
/// here and taps the SAME physical card to write it. Only a sealed `C1.`
/// record is accepted; plaintext is never written. Deliberately a bare
/// paste-and-write screen, not a patient search + registration flow of
/// its own: registration (choosing the patient/scope, reading the UID)
/// already exists on the web console; this only adds the one thing a
/// desktop browser can't do -- an actual NDEF write, which needs a
/// phone's native NFC.
class WriteOfflineTagScreen extends StatefulWidget {
  const WriteOfflineTagScreen({super.key});

  @override
  State<WriteOfflineTagScreen> createState() => _WriteOfflineTagScreenState();
}

class _WriteOfflineTagScreenState extends State<WriteOfflineTagScreen> {
  final _textController = TextEditingController();
  final _urlController = TextEditingController();
  NfcAvailability? _availability;
  bool _writing = false;
  bool _urlInvalid = false;
  NfcWriteResult? _lastResult;

  @override
  void initState() {
    super.initState();
    _loadAvailability();
  }

  @override
  void dispose() {
    _textController.dispose();
    _urlController.dispose();
    NfcService.cancelSession();
    super.dispose();
  }

  Future<void> _loadAvailability() async {
    final availability = await NfcService.checkAvailability();
    if (!mounted) return;
    setState(() => _availability = availability);
  }

  Future<void> _write() async {
    final text = _textController.text.trim();
    if (text.isEmpty) return;
    // Same check NfcService.writeNdefText enforces; done here too so the
    // error shows without waiting for the tap prompt.
    if (!TagCrypto.isWellFormedBlob(text)) {
      setState(() => _lastResult = NfcWriteResult.notEncrypted);
      return;
    }
    final url = _urlController.text.trim();
    if (url.isNotEmpty && !NfcService.isValidPublicUrl(url)) {
      setState(() => _urlInvalid = true);
      return;
    }
    setState(() {
      _urlInvalid = false;
      _writing = true;
      _lastResult = null;
    });
    final result = await NfcService.writeNdefText(text, publicUrl: url);
    if (!mounted) return;
    setState(() {
      _writing = false;
      _lastResult = result;
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.writeOfflineTagTitle)),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l10n.writeOfflineTagDesc,
              style: TextStyle(fontSize: 13, color: context.palette.textMuted, height: 1.4),
            ),
            const SizedBox(height: 12),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.warning_amber_rounded, size: 18, color: Colors.amber.shade800),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(l10n.nfcBasicTagWarning,
                      style: TextStyle(fontSize: 12, color: context.palette.textMuted, height: 1.4)),
                ),
              ],
            ),
            const SizedBox(height: 20),
            if (!NfcService.isSupportedPlatform)
              Text(l10n.nfcUnsupportedPlatform, style: TextStyle(color: context.palette.textMuted))
            else ...[
              TextField(
                controller: _textController,
                maxLines: 4,
                onChanged: (_) => setState(() {}),
                decoration: InputDecoration(
                  labelText: l10n.writeOfflineTagTextLabel,
                  hintText: 'C1.1.…',
                  border: const OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _urlController,
                keyboardType: TextInputType.url,
                onChanged: (_) => setState(() => _urlInvalid = false),
                autocorrect: false,
                decoration: InputDecoration(
                  labelText: l10n.writeOfflineTagUrlLabel,
                  hintText: 'https://host/e/token',
                  border: const OutlineInputBorder(),
                  errorText: _urlInvalid ? l10n.writeOfflineTagUrlInvalid : null,
                  errorMaxLines: 3,
                ),
              ),
              if (_urlController.text.trim().isEmpty) ...[
                const SizedBox(height: 6),
                Text(l10n.writeOfflineTagNoUrlHint,
                    key: const Key('no-url-hint'),
                    style: TextStyle(fontSize: 12, color: Colors.amber.shade800, height: 1.4)),
              ],
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton.icon(
                  icon: const Icon(Icons.nfc),
                  onPressed: (_writing || _textController.text.trim().isEmpty || _availability != NfcAvailability.enabled)
                      ? null
                      : _write,
                  label: Text(_writing ? l10n.writeOfflineTagWriting : l10n.writeOfflineTagButton),
                ),
              ),
              if (_availability == NfcAvailability.disabled) ...[
                const SizedBox(height: 8),
                Text(l10n.nfcDisabled, style: TextStyle(fontSize: 12, color: context.palette.textMuted)),
              ],
              if (_availability == NfcAvailability.unsupported) ...[
                const SizedBox(height: 8),
                Text(l10n.nfcUnsupportedDevice, style: TextStyle(fontSize: 12, color: context.palette.textMuted)),
              ],
              if (_lastResult != null) ...[
                const SizedBox(height: 20),
                _ResultBanner(result: _lastResult!, l10n: l10n),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

class _ResultBanner extends StatelessWidget {
  const _ResultBanner({required this.result, required this.l10n});

  final NfcWriteResult result;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final success = result == NfcWriteResult.success;
    final message = switch (result) {
      NfcWriteResult.success => l10n.writeOfflineTagSuccess,
      NfcWriteResult.notNdef => l10n.writeOfflineTagNotNdef,
      NfcWriteResult.notWritable => l10n.writeOfflineTagNotWritable,
      NfcWriteResult.tooLarge => l10n.writeOfflineTagTooLarge,
      NfcWriteResult.notEncrypted => l10n.writeOfflineTagNotEncrypted,
      NfcWriteResult.unsupported => l10n.nfcUnsupportedPlatform,
      NfcWriteResult.writeFailed => l10n.writeOfflineTagWriteFailed,
    };
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: success ? context.palette.chipBg : context.palette.emergencyBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: success ? context.palette.primaryLight : context.palette.emergency),
      ),
      child: Row(
        children: [
          Icon(
            success ? Icons.check_circle_outline : Icons.error_outline,
            color: success ? context.palette.primary : context.palette.emergency,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(message, style: TextStyle(color: context.palette.textBody)),
          ),
        ],
      ),
    );
  }
}
