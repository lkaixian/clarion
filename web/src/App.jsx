import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import PatientList from "./pages/PatientList";
import PatientDetail from "./pages/PatientDetail";
import AdminConsole from "./pages/AdminConsole";
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

// /admin (routers/admin.py) is `role === "admin"`-only on the backend —
// mirrors StaffOnly above exactly, just for a narrower role. Without this, a
// clinician/records_officer/patient hitting /admin directly (stale bookmark,
// typed URL, a nav link that somehow rendered anyway) would see a raw 403
// from AdminConsole's data fetches instead of landing somewhere useful, the
// same UX gap StaffOnly closes for /patients.
function AdminOnly({ children }) {
  const user = getCurrentUser();
  if (user?.role === "admin") return children;
  if (user?.role === "patient") {
    return user.patient_id ? <Navigate to={`/patients/${user.patient_id}`} /> : <Navigate to="/" />;
  }
  return <Navigate to="/patients" />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/patients" element={<Protected><StaffOnly><PatientList /></StaffOnly></Protected>} />
        <Route path="/patients/:id" element={<Protected><PatientDetail /></Protected>} />
        <Route path="/admin" element={<Protected><AdminOnly><AdminConsole /></AdminOnly></Protected>} />
      </Routes>
    </BrowserRouter>
  );
}
