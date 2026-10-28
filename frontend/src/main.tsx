import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { AppShell } from "./components/layout";
import { ErrorState, Loading } from "./components/ui";
import { matchPath, useLocation } from "./lib/router";
import { SessionProvider, useSession } from "./lib/session";
import { ToastProvider } from "./lib/toast";
import { AlertsPage } from "./pages/Alerts";
import { AuditPage } from "./pages/Audit";
import { CaseDetailPage } from "./pages/CaseDetail";
import { DashboardPage } from "./pages/Dashboard";
import { DossierPage } from "./pages/Dossier";
import { GraphPage } from "./pages/Graph";
import { ImportsPage } from "./pages/Imports";
import { InstitutionPage } from "./pages/Institution";
import { InstitutionsPage } from "./pages/Institutions";
import { IntakePage } from "./pages/Intake";
import { MasterCasePage } from "./pages/MasterCase";
import { MatchReviewPage } from "./pages/MatchReview";
import { NotFoundPage } from "./pages/NotFound";
import { OverlapDetailPage } from "./pages/OverlapDetail";
import { OverlapsPage } from "./pages/Overlaps";
import { ReportsPage } from "./pages/Reports";
import { RulesPage } from "./pages/Rules";
import { SearchPage } from "./pages/Search";
import { SignalsPage } from "./pages/Signals";
import { WatchlistPage } from "./pages/Watchlist";

type Route = [string, (p: Record<string, string>) => ReactNode];

const ROUTES: Route[] = [
  ["/", () => <DashboardPage />],
  ["/search", () => <SearchPage />],
  ["/cases/new", () => <IntakePage />],
  ["/cases/:id", (p) => <CaseDetailPage id={p.id} />],
  ["/institutions", () => <InstitutionsPage />],
  ["/institutions/:id/dossier", (p) => <DossierPage id={p.id} />],
  ["/institutions/:id", (p) => <InstitutionPage id={p.id} />],
  ["/overlaps", () => <OverlapsPage />],
  ["/overlaps/:id", (p) => <OverlapDetailPage id={p.id} />],
  ["/master-cases/:id", (p) => <MasterCasePage id={p.id} />],
  ["/match-reviews", () => <MatchReviewPage />],
  ["/watchlist", () => <WatchlistPage />],
  ["/graph", () => <GraphPage />],
  ["/alerts", () => <AlertsPage />],
  ["/reports", () => <ReportsPage />],
  ["/rules", () => <RulesPage />],
  ["/imports", () => <ImportsPage />],
  ["/signals", () => <SignalsPage />],
  ["/audit", () => <AuditPage />],
];

function Router() {
  const { pathname } = useLocation();
  const { ref, me, bootError } = useSession();
  if (bootError && !ref) {
    return (
      <div className="mx-auto max-w-xl p-8">
        <ErrorState error={new Error(`Cannot reach the AgniDrishti API: ${bootError}`)} onRetry={() => window.location.reload()} />
      </div>
    );
  }
  if (!ref || !me) return <Loading label="Loading AgniDrishti…" className="justify-center" />;
  for (const [pattern, render] of ROUTES) {
    const params = matchPath(pattern, pathname);
    if (params) return <div key={pathname}>{render(params)}</div>;
  }
  return <NotFoundPage />;
}

function App() {
  const { pathname } = useLocation();
  // The dossier is a print document: rendered without the application chrome.
  if (/^\/institutions\/[^/]+\/dossier$/.test(pathname)) {
    return <Router />;
  }
  return (
    <AppShell>
      <Router />
    </AppShell>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SessionProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </SessionProvider>
  </StrictMode>,
);
