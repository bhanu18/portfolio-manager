import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { PublicOnlyRoute } from "./components/PublicOnlyRoute";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { ProfilePage } from "./pages/ProfilePage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { GroupDetailPage } from "./pages/GroupDetailPage";
import { ReportsPage } from "./pages/ReportsPage";
import { ValuationPage } from "./pages/ValuationPage";
import { PerformancePage } from "./pages/PerformancePage";
import { NotFoundPage } from "./pages/NotFoundPage";

export default function App() {
  return (
    <Routes>
      {/* Public auth routes (redirect to app if already signed in) */}
      <Route element={<PublicOnlyRoute />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
      </Route>

      {/* Authenticated app routes */}
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          {/* Portfolio — unified split-panel (replaces /assets + /trades) */}
          <Route path="/portfolio" element={<PortfolioPage />} />

          {/* Legacy redirects */}
          <Route path="/assets" element={<Navigate to="/portfolio" replace />} />
          <Route path="/assets/:symbol" element={<Navigate to="/portfolio" replace />} />
          <Route path="/trades" element={<Navigate to="/portfolio" replace />} />

          <Route path="/profile" element={<ProfilePage />} />

          {/* /groups redirects to Profile (groups now live there) */}
          <Route path="/groups" element={<Navigate to="/profile" replace />} />
          <Route path="/groups/:groupId" element={<GroupDetailPage />} />

          {/* Reports (v2) — hub with nested sub-routes */}
          <Route path="/reports" element={<ReportsPage />}>
            <Route path="valuation" element={<ValuationPage />} />
            <Route path="performance" element={<PerformancePage />} />
          </Route>
        </Route>
      </Route>

      {/* Defaults */}
      <Route path="/" element={<Navigate to="/portfolio" replace />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
