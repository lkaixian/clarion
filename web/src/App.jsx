import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Login from "./pages/Login";
import ForgotPassword from "./pages/ForgotPassword";
import PatientList from "./pages/PatientList";
import PatientDetail from "./pages/PatientDetail";
import Profile from "./pages/Profile";
import AdminConsole from "./pages/AdminConsole";
import Reception from "./pages/Reception";
import Pharmacy from "./pages/Pharmacy";
import Ancillary from "./pages/Ancillary";
import Dental from "./pages/Dental";
import Billing from "./pages/Billing";
import Reporting from "./pages/Reporting";
import Dashboard from "./pages/Dashboard";
import WaitingRoomDisplay from "./pages/WaitingRoomDisplay";
import ChangePassword from "./pages/ChangePassword";
import Security from "./pages/Security";
import { getCurrentUser } from "./api/client";
import { landingPathFor } from "./lib/access";

function Protected({ children }) {
  return getCurrentUser() ? children : <Navigate to="/login" />;
}

// One generic page guard, driven by the per-facility `allowed_pages` matrix
// the backend now returns on the user object (pages:
// "patients" | "reception" | "pharmacy" | "admin"). The backend also 403s any
// API call into an area the role can't reach, so without this guard a stale
// client would render the page and then show nothing but failed fetches —
// this bounces the user somewhere they can actually use instead.
//
// - A patient account is sent to its own landing path (its record). It must
//   still be able to reach /patients/:id directly, so that route is NOT
//   wrapped in RequirePage — see the route table below.
// - An admin implicitly has every page (its allowed_pages already lists all
//   four, but the explicit role check keeps this correct even against an
//   older cached user object).
function RequirePage({ page, children }) {
  const user = getCurrentUser();
  if (!user) return <Navigate to="/login" />;
  if (user.role === "patient") return <Navigate to={landingPathFor(user)} />;
  const pages = user.allowed_pages || [];
  if (user.role === "admin" || pages.includes(page)) return children;
  return <Navigate to={landingPathFor(user)} />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/login" replace />} />
        <Route path="/login" element={<Login />} />
        <Route path="/change-password" element={<Protected><ChangePassword /></Protected>} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/security" element={<Protected><Security /></Protected>} />
        {/* Public big-screen waiting-room board — no auth, deliberately
            OUTSIDE <Protected>: a lobby TV has no logged-in user. The page
            itself calls the unauthenticated /display/{token} endpoint. */}
        <Route path="/display/:token" element={<WaitingRoomDisplay />} />
        <Route path="/patients" element={<Protected><RequirePage page="patients"><PatientList /></RequirePage></Protected>} />
        {/* Not wrapped in RequirePage: a patient must be able to open their
            own record here. Staff without "patients" access who land here
            will just get a 403 from PatientDetail's fetch — acceptable, and
            they have no link to it anyway. */}
        <Route path="/patients/:id" element={<Protected><PatientDetail /></Protected>} />
        {/* Any authenticated staff member — a signature isn't a console
            "page", so it's guarded by <Protected> only, no RequirePage. */}
        <Route path="/profile" element={<Protected><Profile /></Protected>} />
        <Route path="/admin" element={<Protected><RequirePage page="admin"><AdminConsole /></RequirePage></Protected>} />
        <Route path="/reception" element={<Protected><RequirePage page="reception"><Reception /></RequirePage></Protected>} />
        <Route path="/pharmacy" element={<Protected><RequirePage page="pharmacy"><Pharmacy /></RequirePage></Protected>} />
        <Route path="/ancillary" element={<Protected><RequirePage page="ancillary"><Ancillary /></RequirePage></Protected>} />
        <Route path="/dental" element={<Protected><RequirePage page="dental"><Dental /></RequirePage></Protected>} />
        <Route path="/billing" element={<Protected><RequirePage page="billing"><Billing /></RequirePage></Protected>} />
        <Route path="/reporting" element={<Protected><RequirePage page="reporting"><Reporting /></RequirePage></Protected>} />
        <Route path="/dashboard" element={<Protected><RequirePage page="dashboard"><Dashboard /></RequirePage></Protected>} />
      </Routes>
    </BrowserRouter>
  );
}
