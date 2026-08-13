import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import PatientList from "./pages/PatientList";
import PatientDetail from "./pages/PatientDetail";
import { getCurrentUser } from "./api/client";

function Protected({ children }) {
  return getCurrentUser() ? children : <Navigate to="/" />;
}

// A patient account can't call GET /patients (staff-only on the backend) —
// this guards direct navigation / a stale bookmark to that URL, on top of
// Login.jsx and Layout.jsx already sending a patient straight to their own
// record instead. Without this, a patient hitting /patients directly would
// still see a raw 403 from PatientList's data fetch.
function StaffOnly({ children }) {
  const user = getCurrentUser();
  if (user?.role === "patient") {
    return user.patient_id ? <Navigate to={`/patients/${user.patient_id}`} /> : <Navigate to="/" />;
  }
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/patients" element={<Protected><StaffOnly><PatientList /></StaffOnly></Protected>} />
        <Route path="/patients/:id" element={<Protected><PatientDetail /></Protected>} />
      </Routes>
    </BrowserRouter>
  );
}
