import { Navigate, Route, Routes, useLocation } from "react-router";
import { MeProvider, useMeQuery } from "@/lib/auth";
import { useLiveUpdates } from "@/lib/live";
import { CatalogPage } from "@/catalog/CatalogPage";
import { PurposesPage } from "@/catalog/PurposesPage";
import { EditorPage } from "@/editor/Editor";
import { DocumentPage } from "@/inventory/DocumentPage";
import { DocumentsPage } from "@/inventory/DocumentsPage";
import { PropertyPage } from "@/inventory/PropertyPage";
import { QrPage } from "@/inventory/QrPage";
import { WarehousePage } from "@/inventory/WarehousePage";
import { Buildings } from "@/pages/Buildings";
import { Journal } from "@/pages/Journal";
import { PlanIndex } from "@/pages/PlanIndex";
import { ForcedPassword, Login } from "@/pages/Login";
import { Placeholder } from "@/pages/Placeholder";
import { SearchPage } from "@/pages/SearchPage";
import { SettingsPage } from "@/pages/Settings";
import { Users } from "@/pages/Users";
import { homeFor, MENU } from "@/shell/menu";
import { Shell } from "@/shell/Shell";
import { Loading } from "@/ui/misc";

const READY: Record<string, React.ReactNode> = {
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
};

export function App() {
  const me = useMeQuery();
  const location = useLocation();
  useLiveUpdates(!!me.data && !me.data.must_change_password);

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
  return (
    <MeProvider me={me.data}>
      <Routes>
        <Route path="/login" element={<Navigate to={homeFor(role)} replace />} />
        <Route element={<Shell />}>
          {MENU.filter((m) => m.roles.includes(role)).map((m) => (
            <Route key={m.path} path={m.path === "/" ? undefined : m.path} index={m.path === "/"} element={READY[m.path] ?? <Placeholder />} />
          ))}
          <Route path="/plan/:buildingId/:floorId?" element={<EditorPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/scan" element={<Placeholder title="QR-сканер" stage={6} about="Камера телефона читает QR-метку на вещи или двери помещения и открывает карточку (6.5.12, 5.4.7)." />} />
          {role === "admin" && <Route path="/documents/:docId" element={<DocumentPage />} />}
          <Route path="/q/:code" element={<QrPage />} />
          <Route path="*" element={<Navigate to={homeFor(role)} replace />} />
        </Route>
      </Routes>
    </MeProvider>
  );
}
