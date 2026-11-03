import { Navigate, Route, Routes, useLocation } from "react-router";
import { MeProvider, useMeQuery } from "@/lib/auth";
import { useLiveUpdates } from "@/lib/live";
import { CatalogPage } from "@/catalog/CatalogPage";
import { PurposesPage } from "@/catalog/PurposesPage";
import { EditorPage } from "@/editor/Editor";
import { CountPage } from "@/inventory/CountPage";
import { CountsPage } from "@/inventory/CountsPage";
import { DocumentPage } from "@/inventory/DocumentPage";
import { DocumentsPage } from "@/inventory/DocumentsPage";
import { HelpPage } from "@/help/Help";
import { HomePage } from "@/home/HomePage";
import { PropertyPage } from "@/inventory/PropertyPage";
import { QrPage } from "@/inventory/QrPage";
import { ScanPage } from "@/inventory/ScanPage";
import { WarehousePage } from "@/inventory/WarehousePage";
import { Buildings } from "@/pages/Buildings";
import { Journal } from "@/pages/Journal";
import { PlanIndex } from "@/pages/PlanIndex";
import { ForcedPassword, Login, nextAfterLogin } from "@/pages/Login";
import { Placeholder } from "@/pages/Placeholder";
import { SearchPage } from "@/pages/SearchPage";
import { SettingsPage } from "@/pages/Settings";
import { Users } from "@/pages/Users";
import { GuestShell } from "@/share/GuestShell";
import { ShareLinksPage } from "@/share/ShareLinksPage";
import { SharePage } from "@/share/SharePage";
import { ProjectPage } from "@/projects/ProjectPage";
import { ProjectsPage } from "@/projects/ProjectsPage";
import { ReportsPage } from "@/reports/ReportsPage";
import { homeFor, MENU } from "@/shell/menu";
import { CamerasPage } from "@/surveillance/CamerasPage";
import { Shell } from "@/shell/Shell";
import { Loading } from "@/ui/misc";

const READY: Record<string, React.ReactNode> = {
  "/": <HomePage />,
  "/cameras": <CamerasPage />,
  "/reports": <ReportsPage />,
  "/users": <Users />,
  "/journal": <Journal />,
  "/settings": <SettingsPage />,
  "/buildings": <Buildings />,
  "/plan": <PlanIndex />,
  "/catalog": <CatalogPage />,
  "/purposes": <PurposesPage />,
  "/property": <PropertyPage />,
  "/warehouse": <WarehousePage />,
  "/documents": <DocumentsPage />,
  "/projects": <ProjectsPage />,
  "/inventory": <CountsPage />,
  "/links": <ShareLinksPage />,
};

export function App() {
  const me = useMeQuery();
  const location = useLocation();
  useLiveUpdates(!!me.data && !me.data.must_change_password && me.data.role !== "guest");
  // ссылка на просмотр открывается и без входа (5.7.2)
  if (location.pathname.startsWith("/share/"))
    return (
      <Routes>
        <Route path="/share/:token" element={<SharePage />} />
      </Routes>
    );

  if (me.isLoading) return <Loading />;
  if (me.isError) {
    return <div className="p-8 text-center text-sm text-bad">Сервер не отвечает. Обновите страницу через минуту.</div>;
  }
  if (!me.data) {
    if (location.pathname === "/login") return <Login />;
    const next = location.pathname + location.search;
    return <Navigate to={`/login${next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`} replace />;
  }
  if (me.data.must_change_password) return <ForcedPassword me={me.data} />;

  const role = me.data.role;
  if (role === "guest")
    return (
      <MeProvider me={me.data}>
        <Routes>
          <Route element={<GuestShell />}>
            <Route path="/plan/:buildingId/:floorId?" element={<EditorPage />} />
            <Route path="*" element={<Navigate to={`/plan/${me.data.buildings[0]?.id ?? ""}`} replace />} />
          </Route>
        </Routes>
      </MeProvider>
    );
  return (
    <MeProvider me={me.data}>
      <Routes>
        <Route path="/login" element={<Navigate to={nextAfterLogin(location.search) ?? homeFor(role)} replace />} />
        <Route element={<Shell />}>
          {MENU.filter((m) => m.roles.includes(role)).map((m) => (
            <Route key={m.path} path={m.path === "/" ? undefined : m.path} index={m.path === "/"} element={READY[m.path] ?? <Placeholder />} />
          ))}
          <Route path="/plan/:buildingId/:floorId?" element={<EditorPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/scan" element={<ScanPage />} />
          <Route path="/help" element={<HelpPage />} />
          {role === "admin" && <Route path="/documents/:docId" element={<DocumentPage />} />}
          {role === "admin" && <Route path="/projects/:projectId" element={<ProjectPage />} />}
          {role === "admin" && <Route path="/inventory/:countId" element={<CountPage />} />}
          <Route path="/q/:code" element={<QrPage />} />
          <Route path="*" element={<Navigate to={homeFor(role)} replace />} />
        </Route>
      </Routes>
    </MeProvider>
  );
}
