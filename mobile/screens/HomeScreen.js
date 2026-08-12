import { useEffect, useState } from "react";
import { View, Text, ScrollView, StyleSheet, TouchableOpacity, ActivityIndicator } from "react-native";
import { getPatient, getSummary, getCurrentUser, logout } from "../api/client";

function Card({ title, children }) {
  return (
    <View style={styles.card}>
      <Text style={styles.cardTitle}>{title}</Text>
      {children}
    </View>
  );
}

export default function HomeScreen({ navigation }) {
  const [patient, setPatient] = useState(null);
  const [brief, setBrief] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const user = await getCurrentUser();
      if (!user?.patient_id) return setLoading(false);
      const [p, s] = await Promise.all([
        getPatient(user.patient_id),
        getSummary(user.patient_id).catch(() => ({ handover_brief: "" })),
      ]);
      setPatient(p);
      setBrief(s.handover_brief);
      setLoading(false);
    })();
  }, []);

  if (loading) return <ActivityIndicator style={{ flex: 1 }} size="large" color="#1F4E79" />;
  if (!patient) return <Text style={{ padding: 24 }}>No linked patient record found.</Text>;

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 16 }}>
      <View style={styles.header}>
        <View>
          <Text style={styles.name}>{patient.full_name}</Text>
          <Text style={styles.sub}>Blood type {patient.blood_type || "—"}</Text>
        </View>
        <TouchableOpacity onPress={async () => { await logout(); navigation.replace("Login"); }}>
          <Text style={styles.signOut}>Sign out</Text>
        </TouchableOpacity>
      </View>

      <TouchableOpacity
        style={styles.emergencyButton}
        onPress={() => navigation.navigate("Emergency", { patientId: patient.id })}
      >
        <Text style={styles.emergencyButtonText}>🚨 View / Issue Emergency QR Card</Text>
      </TouchableOpacity>

      {brief ? (
        <Card title="Your Health Summary">
          <Text style={styles.bodyText}>{brief}</Text>
        </Card>
      ) : null}

      <Card title="Active Conditions">
        {patient.conditions.map((c, i) => <Text key={i} style={styles.bodyText}>• {c.name}</Text>)}
      </Card>

      <Card title="Current Medications">
        {patient.medications.filter(m => m.active).map((m, i) => (
          <Text key={i} style={styles.bodyText}>• {m.drug_name} ({m.prescribed_by_facility})</Text>
        ))}
      </Card>

      <Card title="Allergies">
        {patient.allergies.map((a, i) => <Text key={i} style={styles.bodyText}>• {a.substance} ({a.severity})</Text>)}
      </Card>

      <TouchableOpacity style={styles.secondaryButton} onPress={() => navigation.navigate("Reminders")}>
        <Text style={styles.secondaryButtonText}>💊 Medication & Appointment Reminders</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F8FAFC" },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 16 },
  name: { fontSize: 22, fontWeight: "bold", color: "#1E293B" },
  sub: { fontSize: 13, color: "#64748B" },
  signOut: { color: "#94A3B8", fontSize: 13 },
  emergencyButton: { backgroundColor: "#B91C1C", borderRadius: 14, padding: 16, alignItems: "center", marginBottom: 16 },
  emergencyButtonText: { color: "white", fontWeight: "700", fontSize: 15 },
  card: { backgroundColor: "white", borderRadius: 14, padding: 16, marginBottom: 12, borderWidth: 1, borderColor: "#E2E8F0" },
  cardTitle: { fontWeight: "700", color: "#1F4E79", marginBottom: 8, fontSize: 14 },
  bodyText: { fontSize: 14, color: "#334155", marginBottom: 2, lineHeight: 20 },
  secondaryButton: { backgroundColor: "#DCE6F1", borderRadius: 14, padding: 16, alignItems: "center", marginTop: 4 },
  secondaryButtonText: { color: "#1F4E79", fontWeight: "600", fontSize: 14 },
});
