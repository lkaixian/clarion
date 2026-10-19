import { useState } from "react";
import Layout from "../components/Layout";
import { TabBar } from "./admin/_shared";
import AppointmentsTab from "./admin/AppointmentsTab";
import InventoryTab from "./admin/InventoryTab";
import WardsTab from "./admin/WardsTab";
import RoomsTab from "./admin/RoomsTab";
import SectionsTab from "./admin/SectionsTab";
import WaitingRoomDisplaysTab from "./admin/DisplaysTab";
import StaffRosterTab from "./admin/StaffRosterTab";
import HospitalSettingsTab from "./admin/HospitalSettingsTab";
import AccessControlTab from "./admin/AccessControlTab";
import AnnouncementsTab from "./admin/AnnouncementsTab";
import OnlineBookingTab from "./admin/OnlineBookingTab";
import RespondersTab from "./admin/RespondersTab";

// Facility-scoped admin console — appointments monitoring, medicine
// inventory, ward/bed capacity, and staff roster, all auto-scoped
// server-side to the current admin's own facility (routers/admin.py).
// Access itself is gated one level up by App.jsx's <RequirePage page="admin">
// route guard; nothing here needs to re-check the role.
export default function AdminConsole() {
  const [activeTab, setActiveTab] = useState("appointments");

  return (
    <Layout>
      <div className="mb-6">
        <h1 className="page-title">Admin Console</h1>
        <p className="text-sm text-slate-500">Facility-wide monitoring and management for your hospital.</p>
      </div>

      <TabBar active={activeTab} onChange={setActiveTab} />

      {activeTab === "appointments" && <AppointmentsTab />}
      {activeTab === "inventory" && <InventoryTab />}
      {activeTab === "wards" && <WardsTab />}
      {activeTab === "rooms" && <RoomsTab />}
      {activeTab === "sections" && <SectionsTab />}
      {activeTab === "displays" && <WaitingRoomDisplaysTab />}
      {activeTab === "staff" && <StaffRosterTab />}
      {activeTab === "hospital" && <HospitalSettingsTab />}
      {activeTab === "booking" && <OnlineBookingTab />}
      {activeTab === "responders" && <RespondersTab />}
      {activeTab === "access" && <AccessControlTab />}
      {activeTab === "announcements" && <AnnouncementsTab />}
    </Layout>
  );
}
