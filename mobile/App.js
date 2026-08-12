import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { StatusBar } from "expo-status-bar";

import LoginScreen from "./screens/LoginScreen";
import HomeScreen from "./screens/HomeScreen";
import EmergencyScreen from "./screens/EmergencyScreen";
import RemindersScreen from "./screens/RemindersScreen";
import SeniorModeScreen from "./screens/SeniorModeScreen";

const Stack = createNativeStackNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <StatusBar style="dark" />
      <Stack.Navigator screenOptions={{ headerStyle: { backgroundColor: "#1F4E79" }, headerTintColor: "white" }}>
        <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
        <Stack.Screen name="SeniorMode" component={SeniorModeScreen} options={{ title: "Senior Mode" }} />
        <Stack.Screen name="Home" component={HomeScreen} options={{ title: "My Health Record" }} />
        <Stack.Screen name="Emergency" component={EmergencyScreen} options={{ title: "Emergency Card" }} />
        <Stack.Screen name="Reminders" component={RemindersScreen} options={{ title: "Reminders" }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
