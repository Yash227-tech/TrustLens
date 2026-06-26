import { Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { DashboardPage } from "@/pages/DashboardPage";
import { AnalyzePage } from "@/pages/AnalyzePage";
import { CasePage } from "@/pages/CasePage";
import { AuditPage } from "@/pages/AuditPage";

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/analyze" element={<AnalyzePage />} />
        <Route path="/cases" element={<CasePage />} />
        <Route path="/audit" element={<AuditPage />} />
      </Routes>
    </AppShell>
  );
}
