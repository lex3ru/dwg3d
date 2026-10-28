// @vitest-environment jsdom
import { beforeEach, expect, test } from "vitest";
import { setStorageUser, userKey } from "./userStorage";

beforeEach(() => localStorage.clear());

// R-018 п. 4: данные прежней версии лежат без пользователя — их не теряют, а отдают первому
// вошедшему (как и было до привязки), и больше они никому не достаются
test("данные прежней версии достаются первому вошедшему", () => {
  localStorage.setItem("count-queue:c1", '[{"kind":"unmark","unit_id":"x","seq":1}]');
  setStorageUser("u1");
  expect(localStorage.getItem(userKey("count-queue:c1"))).toBe('[{"kind":"unmark","unit_id":"x","seq":1}]');
  expect(localStorage.getItem("count-queue:c1")).toBeNull();
  setStorageUser("u2");
  expect(localStorage.getItem(userKey("count-queue:c1"))).toBeNull();
});
