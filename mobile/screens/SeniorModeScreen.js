import { View, Text, StyleSheet, TouchableOpacity } from "react-native";

/**
 * Simplified, large-text, minimal-navigation entry point for senior
 * citizens or low digital-literacy users. In a real deployment this would
 * be reachable via a single home-screen shortcut, and would let a family
 * member/guardian log in on the senior's behalf to manage their record.
 */
export default function SeniorModeScreen({ navigation }) {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>MediBridge{"\n"}Senior Mode</Text>

      <TouchableOpacity style={styles.bigButton} onPress={() => navigation.navigate("Login")}>
        <Text style={styles.bigButtonText}>📋{"\n"}View My Health Info</Text>
      </TouchableOpacity>

      <TouchableOpacity style={[styles.bigButton, styles.emergencyBig]} onPress={() => navigation.navigate("Login")}>
        <Text style={styles.bigButtonText}>🚨{"\n"}Emergency Card</Text>
      </TouchableOpacity>

      <Text style={styles.helpText}>
        No smartphone? Ask hospital staff to print your Emergency Card —
        it works without an app, login, or internet connection.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#F8FAFC", padding: 24, justifyContent: "center" },
  title: { fontSize: 28, fontWeight: "bold", color: "#1F4E79", textAlign: "center", marginBottom: 40, lineHeight: 36 },
  bigButton: { backgroundColor: "#DCE6F1", borderRadius: 20, padding: 28, alignItems: "center", marginBottom: 20 },
  emergencyBig: { backgroundColor: "#FEE2E2" },
  bigButtonText: { fontSize: 22, fontWeight: "700", color: "#1E293B", textAlign: "center", lineHeight: 30 },
  helpText: { fontSize: 15, color: "#64748B", textAlign: "center", marginTop: 20, lineHeight: 22 },
});
