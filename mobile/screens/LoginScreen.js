import { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { login } from "../api/client";

export default function LoginScreen({ navigation }) {
  const [email, setEmail] = useState("patient@medibridge.demo");
  const [password, setPassword] = useState("patient123");
  const [loading, setLoading] = useState(false);

  async function handleLogin() {
    setLoading(true);
    try {
      await login(email, password);
      navigation.replace("Home");
    } catch (e) {
      Alert.alert("Login failed", "Check your credentials or that the backend is reachable.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>MediBridge</Text>
      <Text style={styles.subtitle}>Your health record, wherever you go</Text>

      <TextInput
        style={styles.input} value={email} onChangeText={setEmail}
        autoCapitalize="none" placeholder="Email"
      />
      <TextInput
        style={styles.input} value={password} onChangeText={setPassword}
        secureTextEntry placeholder="Password"
      />

      <TouchableOpacity style={styles.button} onPress={handleLogin} disabled={loading}>
        <Text style={styles.buttonText}>{loading ? "Signing in..." : "Sign In"}</Text>
      </TouchableOpacity>

      <TouchableOpacity onPress={() => navigation.navigate("SeniorMode")}>
        <Text style={styles.seniorLink}>Senior Citizen Mode →</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: "center", padding: 24, backgroundColor: "#F8FAFC" },
  title: { fontSize: 32, fontWeight: "bold", color: "#1F4E79", textAlign: "center" },
  subtitle: { fontSize: 14, color: "#64748B", textAlign: "center", marginBottom: 32 },
  input: { borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 12, padding: 14, marginBottom: 12, backgroundColor: "white" },
  button: { backgroundColor: "#1F4E79", borderRadius: 12, padding: 16, alignItems: "center", marginTop: 8 },
  buttonText: { color: "white", fontWeight: "600", fontSize: 16 },
  seniorLink: { textAlign: "center", color: "#2E75B6", marginTop: 20, fontSize: 15 },
});
