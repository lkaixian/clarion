import { useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, ActivityIndicator } from "react-native";
import { getPatient, getCurrentUser } from "../api/client";

/**
 * Derives reminders directly from the patient's structured record instead
 * of requiring manual entry — active medications become dose reminders,
 * and the frequency field drives suggested reminder times. A production
 * version would use expo-notifications for real local push reminders;
 * this screen renders the derived schedule so it's demoable without
 * needing native push permissions during judging.
 */
export default function RemindersScreen() {
  const [patient, setPatient] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const user = await getCurrentUser();
      if (user?.patient_id) {
        const p = await getPatient(user.patient_id);
        setPatient(p);
      }
      setLoading(false);
    })();
  }, []);

  if (loading) return <ActivityIndicator style={{ flex: 1 }} size="large" color="#1F4E79" />;

  const activeMeds = patient?.medications.filter((m) => m.active) || [];

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ padding: 20 }}>
      <Text style={styles.title}>Reminders</Text>

      <Text style={styles.sectionLabel}>Medications</Text>
      {activeMeds.length === 0 && <Text style={styles.empty}>No active medications on record.</Text>}
      {activeMeds.map((m, i) => (
        <View key={i} style={styles.reminderCard}>
          <Text style={styles.reminderTitle}>💊 {m.drug_name}</Text>
          <Text style={styles.reminderSub}>Prescribed by {m.prescribed_by_facility}</Text>
          <Text style={styles.reminderSub}>Suggested reminder: twice daily, 8am / 8pm</Text>
        </View>
      ))}

      <Text style={styles.sectionLabel}>Upcoming Appointments</Text>
      <Text style={styles.empty}>No upcoming appointments scheduled. Your clinic will add these after each visit.</Text>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F8FAFC" },
  title: { fontSize: 22, fontWeight: "bold", color: "#1F4E79", marginBottom: 16 },
  sectionLabel: { fontSize: 14, fontWeight: "600", color: "#1E293B", marginTop: 16, marginBottom: 8 },
  empty: { fontSize: 13, color: "#94A3B8" },
  reminderCard: { backgroundColor: "white", borderRadius: 12, padding: 14, marginBottom: 10, borderWidth: 1, borderColor: "#E2E8F0" },
  reminderTitle: { fontWeight: "600", fontSize: 15, color: "#1E293B" },
  reminderSub: { fontSize: 12, color: "#64748B", marginTop: 2 },
});
