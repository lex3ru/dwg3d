import { expect, test } from "@playwright/test";
import { loginAdmin } from "./helpers";

// 8.2: план этажа открывается за 2 с, 3D-вид — за 3 с. Нужно здание E2E_PERF_BUILDING
// (например, «Поликлиника»: python -m app sample polyclinic); без него тест пропускается.
const building = process.env.E2E_PERF_BUILDING;

test("8.2: план этажа за 2 с, 3D за 3 с", async ({ page }) => {
  test.skip(!building, "нет E2E_PERF_BUILDING");
  await loginAdmin(page);
  const info = await (await page.request.get(`/api/buildings/${building}`)).json();
  for (const floor of info.floors) {
    const t0 = Date.now();
    await page.goto(`/plan/${building}/${floor.id}`);
    await expect(page.getByRole("img", { name: "План этажа" }).locator("text").first()).toBeVisible();
    const plan = Date.now() - t0;
    const t1 = Date.now();
    await page.goto(`/plan/${building}/${floor.id}?view=3d`);
    await page.waitForFunction(() => {
      const c = document.querySelector("canvas");
      return !!c && c.width > 0;
    });
    await page.waitForTimeout(50);
    const view3d = Date.now() - t1;
    console.log(`${floor.name}: план ${plan} мс, 3D ${view3d} мс`);
    expect(plan).toBeLessThan(2000);
    expect(view3d).toBeLessThan(3000);
  }
});
