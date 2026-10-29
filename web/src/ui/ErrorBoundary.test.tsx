// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter, Outlet, Route, Routes } from "react-router";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ErrorBoundary, SectionBoundary } from "./ErrorBoundary";

afterEach(cleanup);
beforeEach(() => {
  // React и граница пишут пойманное исключение в консоль — в выводе тестов оно лишнее
  vi.spyOn(console, "error").mockImplementation(() => {});
});

function Broken(): never {
  throw new Error("сбой отрисовки");
}

function Layout() {
  return (
    <>
      <nav aria-label="Разделы">
        <Link to="/good">Исправный раздел</Link>
      </nav>
      <SectionBoundary>
        <Outlet />
      </SectionBoundary>
    </>
  );
}

// R-032: исключение в разделе — сообщение на его месте, меню работает; переход в другой
// раздел показывает его
test("сбой раздела не снимает меню, переход в другой раздел его показывает", () => {
  render(
    <MemoryRouter initialEntries={["/bad"]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/bad" element={<Broken />} />
          <Route path="/good" element={<p>Раздел работает</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
  expect(screen.getByRole("alert").textContent).toContain("Раздел не открылся");
  expect(screen.getByRole("button", { name: "Перезагрузить" })).toBeTruthy();
  fireEvent.click(screen.getByRole("link", { name: "Исправный раздел" }));
  expect(screen.getByText("Раздел работает")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

// граница 3D: свой запасной вид, «Попробовать снова» отрисовывает содержимое заново
test("«Попробовать снова» отрисовывает содержимое заново", () => {
  let fail = true;
  function Scene() {
    if (fail) throw new Error("нет WebGL");
    return <p>Сцена</p>;
  }
  render(
    <ErrorBoundary fallback={(retry) => <button type="button" onClick={() => { fail = false; retry(); }}>Попробовать снова</button>}>
      <Scene />
    </ErrorBoundary>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Попробовать снова" }));
  expect(screen.getByText("Сцена")).toBeTruthy();
});
