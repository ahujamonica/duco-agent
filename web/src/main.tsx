import { StrictMode, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import "./index.css";
import { AuthProvider, useAuth } from "./lib/auth";
import { I18nProvider } from "./lib/i18n";
import { ToastProvider } from "./components/ui";
import { Shell } from "./components/Shell";
import Landing from "./pages/Landing";
import AuthPage from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import FamilyPage from "./pages/Family";
import PoliciesPage from "./pages/Policies";
import PolicyDetail from "./pages/PolicyDetail";
import DocumentsPage from "./pages/Documents";
import DocumentDetail from "./pages/DocumentDetail";
import NewCase from "./pages/NewCase";
import CaseRun from "./pages/CaseRun";
import CaseResults from "./pages/CaseResults";
import CaseFinancial from "./pages/CaseFinancial";
import CaseLetters from "./pages/CaseLetters";
import CaseReview from "./pages/CaseReview";
import CaseHistory from "./pages/CaseHistory";
import Settings from "./pages/Settings";

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, [pathname]);
  return null;
}

function Protected() {
  const { user, ready } = useAuth();
  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-brand border-t-transparent" />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <Shell />;
}

function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-canvas px-6 text-center">
      <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-brand">404</p>
      <h1 className="mt-2 text-3xl font-bold text-navy">That page does not exist.</h1>
      <a href="/app" className="mt-5 rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white">
        Back to the workspace
      </a>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      <Route element={<Protected />}>
        <Route path="/app" element={<Dashboard />} />
        <Route path="/app/family" element={<FamilyPage />} />
        <Route path="/app/policies" element={<PoliciesPage />} />
        <Route path="/app/policies/:policyId" element={<PolicyDetail />} />
        <Route path="/app/documents" element={<DocumentsPage />} />
        <Route path="/app/documents/:documentId" element={<DocumentDetail />} />
        <Route path="/app/cases" element={<CaseHistory />} />
        <Route path="/app/cases/new" element={<NewCase />} />
        <Route path="/app/cases/:caseId" element={<CaseResults />} />
        <Route path="/app/cases/:caseId/run" element={<CaseRun />} />
        <Route path="/app/cases/:caseId/review" element={<CaseReview />} />
        <Route path="/app/cases/:caseId/financial" element={<CaseFinancial />} />
        <Route path="/app/cases/:caseId/letters" element={<CaseLetters />} />
        <Route path="/app/settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <I18nProvider>
        <AuthProvider>
          <ToastProvider>
            <ScrollToTop />
            <App />
          </ToastProvider>
        </AuthProvider>
      </I18nProvider>
    </BrowserRouter>
  </StrictMode>
);
