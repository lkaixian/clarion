import { useState } from "react";
import { View, Text, StyleSheet, TouchableOpacity, Image, ScrollView, ActivityIndicator } from "react-native";
import { issueEmergencyCard } from "../api/client";

const SCOPE_OPTIONS = [
  { key: "allergies", label: "Allergies" },
  { key: "medications", label: "Current Medications" },
  { key: "conditions", label: "Chronic Conditions" },
  { key: "blood_type", label: "Blood Type" },
];

export default function EmergencyScreen({ route, navigation }) {
  const { patientId } = route.params;
  const [selected, setSelected] = useState(SCOPE_OPTIONS.map((o) => o.key));
  const [card, setCard] = useState(null);
  const [loading, setLoading] = useState(false);

  function toggle(key) {
    setSelected((s) => (s.includes(key) ? s.filter((k) => k !== key) : [...s, key]));
  }

  async function issue() {
    setLoading(true);
    const data = await issueEmergencyCard(patientId, selected);
    setCard(data);
    setLoading(false);
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 20 }}>
      <Text style={styles.title}>Emergency Access Card</Text>
      <Text style={styles.desc}>
        Choose what a first responder can see in an emergency. Nothing else on your
        record is ever exposed by this QR code — each scan is logged and you can
        revoke access at any time.
      </Text>

      <Text style={styles.sectionLabel}>Fields to share in an emergency:</Text>
      {SCOPE_OPTIONS.map((opt) => (
        <TouchableOpacity key={opt.key} style={styles.checkboxRow} onPress={() => toggle(opt.key)}>
          <View style={[styles.checkbox, selected.includes(opt.key) && styles.checkboxChecked]} />
          <Text style={styles.checkboxLabel}>{opt.label}</Text>
        </TouchableOpacity>
      ))}

      <TouchableOpacity style={styles.issueButton} onPress={issue} disabled={loading}>
        <Text style={styles.issueButtonText}>{loading ? "Issuing..." : "Generate QR / Card"}</Text>
      </TouchableOpacity>

      {loading && <ActivityIndicator style={{ marginTop: 16 }} color="#1F4E79" />}

      {card && (
        <View style={styles.cardResult}>
          <Image source={{ uri: card.qr_code_base64 }} style={styles.qrImage} />
          <Text style={styles.refText}>Reference: {card.card_reference}</Text>
          <Text style={styles.printNote}>
            Print this card for offline / senior-citizen use. It should also show
            your blood type and top allergy in large text as a fallback.
          </Text>
        </View>
      )}

      <TouchableOpacity onPress={() => navigation.goBack()} style={{ marginTop: 20 }}>
        <Text style={{ color: "#64748B", textAlign: "center" }}>← Back</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F8FAFC" },
  title: { fontSize: 22, fontWeight: "bold", color: "#B91C1C", marginBottom: 8 },
  desc: { fontSize: 13, color: "#64748B", marginBottom: 20, lineHeight: 19 },
  sectionLabel: { fontSize: 14, fontWeight: "600", color: "#1E293B", marginBottom: 8 },
  checkboxRow: { flexDirection: "row", alignItems: "center", marginBottom: 10 },
  checkbox: { width: 20, height: 20, borderRadius: 6, borderWidth: 2, borderColor: "#CBD5E1", marginRight: 10 },
  checkboxChecked: { backgroundColor: "#1F4E79", borderColor: "#1F4E79" },
  checkboxLabel: { fontSize: 14, color: "#334155" },
  issueButton: { backgroundColor: "#B91C1C", borderRadius: 14, padding: 16, alignItems: "center", marginTop: 16 },
  issueButtonText: { color: "white", fontWeight: "700", fontSize: 15 },
  cardResult: { alignItems: "center", marginTop: 24, backgroundColor: "white", padding: 20, borderRadius: 16, borderWidth: 1, borderColor: "#E2E8F0" },
  qrImage: { width: 180, height: 180, marginBottom: 12 },
  refText: { fontFamily: "monospace", fontSize: 13, color: "#334155", marginBottom: 8 },
  printNote: { fontSize: 12, color: "#94A3B8", textAlign: "center" },
});
