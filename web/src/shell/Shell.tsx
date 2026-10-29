import { useState } from "react";
import { Outlet } from "react-router";
import { JobNotices } from "@/lib/jobs";
import { SectionBoundary } from "@/ui/ErrorBoundary";
import { CardPanel } from "./CardPanel";
import { ShellProvider } from "./context";
import { Sidebar } from "./Sidebar";
import { TabBar } from "./TabBar";
import { Topbar } from "./Topbar";

function readCollapsed() {
  try {
    return localStorage.getItem("menu-collapsed") === "1";
  } catch {
    return false;
  }
}

// Каркас (6.3): слева меню, сверху строка, в центре раздел, справа карточка;
// на телефоне — вкладки внизу.
export function Shell() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const toggle = () => {
    setCollapsed((c) => {
      try {
        localStorage.setItem("menu-collapsed", c ? "0" : "1");
      } catch {
        /* не запомнится — не беда */
      }
      return !c;
    });
  };
  return (
    <ShellProvider>
      <div className="flex h-dvh">
        <Sidebar collapsed={collapsed} onToggle={toggle} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <div className="flex min-h-0 flex-1">
            <main className="min-w-0 flex-1 overflow-y-auto">
              <SectionBoundary>
                <Outlet />
              </SectionBoundary>
            </main>
            <CardPanel />
          </div>
          <TabBar />
        </div>
      </div>
      <JobNotices />
    </ShellProvider>
  );
}

export function PageBody({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 px-8 pt-6 pb-10 max-md:px-4 max-md:pt-4">{children}</div>;
}
