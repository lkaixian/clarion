/// Reads the NRIC number and name out of raw OCR text from the FRONT of a MyKad.
/// Pure function, no I/O. OCR output is noisy, so the caller shows the result for
/// the user to confirm; nothing here is trusted by the server.
class MyKadFields {
  const MyKadFields({this.nric, this.name});
  final String? nric; // formatted 900101-01-1234
  final String? name; // upper case as printed
  bool get isEmpty => nric == null && name == null;
}

final _icPattern = RegExp(r'(?<!\d)(\d{6})[\s\-]?(\d{2})[\s\-]?(\d{4})(?!\d)');

// Printed on the card or around the name; never part of a name.
const _stopWords = {
  'KAD PENGENALAN', 'MALAYSIA', 'IDENTITY CARD', 'MYKAD', 'WARGANEGARA', 'ISLAM',
  'LELAKI', 'PEREMPUAN', 'BUKAN ISLAM', 'BUDDHA', 'HINDU', 'KRISTIAN',
  'JALAN', 'LORONG', 'TAMAN', 'KAMPUNG', 'BANDAR', 'LOT', 'NO', 'BLOK', 'JOHOR',
  'SELANGOR', 'PERAK', 'KEDAH', 'PAHANG', 'SABAH', 'SARAWAK', 'KELANTAN', 'MELAKA',
  'PERLIS', 'TERENGGANU', 'PENANG', 'PULAU PINANG', 'NEGERI SEMBILAN', 'KUALA LUMPUR',
  'LABUAN', 'PUTRAJAYA',
};

/// A real name line: 2 to 6 words, letters only, every word short enough to be a name.
/// Hologram and guilloche text comes out of OCR as long run-together "words"
/// (WMACAYSAKERA, AYSAKEHRIAAS), which is what this rejects.
bool _looksLikeNameLine(String line) {
  final t = line.trim();
  if (t.length < 3) return false;
  if (RegExp(r'\d').hasMatch(t)) return false;
  if (!RegExp(r"^[A-Z][A-Z\s'./@\-]+$").hasMatch(t)) return false;
  final up = t.toUpperCase();
  for (final w in _stopWords) {
    if (up == w || up.startsWith('$w ')) return false;
  }
  final words = up.split(' ').where((w) => w.isNotEmpty).toList();
  if (words.length < 2 || words.length > 6) return false;
  if (words.any((w) => w.length > 11)) return false;
  return true;
}

MyKadFields parseMyKadText(String raw) {
  final lines = raw
      .split(RegExp(r'[\r\n]+'))
      .map((l) => l.replaceAll(RegExp(r'\s+'), ' ').trim())
      .where((l) => l.isNotEmpty)
      .toList();

  String? nric;
  var icLine = -1;
  for (var i = 0; i < lines.length && nric == null; i++) {
    final m = _icPattern.firstMatch(lines[i]);
    if (m != null) {
      nric = '${m.group(1)}-${m.group(2)}-${m.group(3)}';
      icLine = i;
    }
  }

  String? pick(Iterable<int> indexes) {
    final parts = <String>[];
    for (final i in indexes) {
      if (i < 0 || i >= lines.length) break;
      if (_looksLikeNameLine(lines[i])) {
        parts.add(lines[i].toUpperCase());
        if (parts.length == 3) break;
      } else if (parts.isNotEmpty) {
        break; // the name block ended
      }
    }
    return parts.isEmpty ? null : parts.join(' ');
  }

  String? name;
  if (icLine >= 0) {
    // The name is printed below the number; some OCR passes return it above.
    name = pick(Iterable<int>.generate(lines.length - icLine - 1, (k) => icLine + 1 + k)) ??
        pick(Iterable<int>.generate(icLine, (k) => icLine - 1 - k).toList().reversed);
  } else {
    name = pick(Iterable<int>.generate(lines.length, (k) => k));
  }
  return MyKadFields(nric: nric, name: name);
}
