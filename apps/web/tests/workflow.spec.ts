import { expect, test, type Page, type Route } from "@playwright/test";

const runId = "run_smoke";
const dumpId = "dump_smoke";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("workflow guard, data table, formula builder and analytics stay usable", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("tablist")).toBeVisible();
  await expect(page.getByRole("tab", { name: /Срез/i })).toBeVisible();

  await page.getByRole("tab", { name: /Данные/i }).click();
  await expect(page.getByText(/Данные текущей выборки/i)).toBeVisible();
  await page.getByRole("textbox", { name: /Автор, работа/i }).fill("Иванов");
  await page.getByRole("button", { name: /Обновить/i }).first().click();
  await expect(page.getByText(/Иванов И. И./i)).toBeVisible();

  await page.getByRole("tab", { name: "Индексы", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Индексы и рейтинги/i, level: 1 })).toBeVisible();
  await page.getByRole("button", { name: /Открыть конструктор/i }).click();
  const dialog = page.getByRole("dialog", { name: /Конструктор собственного показателя/i });
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(box && viewport && box.x >= 0 && box.y >= 0 && box.x + box.width <= viewport.width && box.y + box.height <= viewport.height).toBeTruthy();
  await page.getByLabel(/Закрыть конструктор/i).click();

  await page.getByRole("tab", { name: "Аналитика", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Аналитика", level: 1 })).toBeVisible();
});

test("data sorting stays server-side and does not refresh heavy analytics", async ({ page }) => {
  const calls: string[] = [];
  page.on("request", (request) => {
    const url = request.url();
    if (url.includes("/api/v1/")) calls.push(url);
  });
  await page.goto("/#data");
  await expect(page.getByText(/Данные текущей выборки/i)).toBeVisible();
  calls.length = 0;

  await page.getByRole("button", { name: /Сортировать столбец Публикации/i }).click();
  await expect.poll(() => calls.some((url) => url.includes("/local-data/preview") && url.includes("sort=p") && url.includes("direction=desc"))).toBeTruthy();

  expect(calls.some((url) => url.includes("/analytics/scientometrics"))).toBeFalsy();
  expect(calls.some((url) => url.includes("/analytics/ranking"))).toBeFalsy();
});

async function mockApi(page: Page, calls: string[] = []) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    calls.push(`${path}?${url.searchParams.toString()}`);
    const json = (body: unknown) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/registry") return json({ domain_presets: [], organization_presets: [] });
    if (path === "/catalog") {
      return json({
        metrics: [
          { value: "h", label: "Индекс Хирша", description: "Основной индекс" },
          { value: "p", label: "Публикации" },
          { value: "c", label: "Цитирования" },
        ],
        fraction_modes: [{ value: "strict_authors_count", label: "Долевой учет по всем авторам", default: true }],
        data_sources: [{ value: "openalex_cli", label: "Скачать срез", default: true }],
        storage_profiles: [{ value: "minimal_analytics", label: "Базовый набор", default: true }],
        ui_options: { top_n: [{ value: "0", label: "Все", default: true }, { value: "100", label: "100" }] },
      });
    }
    if (path === "/workbench") {
      return json({ active_context: { active_run_id: runId, active_dump_id: dumpId }, dumps: [], runs: [], workflow: { stages: [] } });
    }
    if (path === "/dumps") return json({ dumps: [{ dump_id: dumpId, status: "ready", works_count: 2, size_bytes: 1024, selected: true }], total: 1 });
    if (path === "/openalex/countries" || path === "/openalex/work-types") return json({ results: [] });
    if (path === "/local-data/summary") {
      return json({
        run_id: runId,
        dump_id: dumpId,
        kinds: [{ kind: "indices", label: "Авторы и индексы" }, { kind: "works", label: "Работы" }],
        tables: { indices: { exists: true, rows: 2 }, works: { exists: true, rows: 2 } },
      });
    }
    if (path === "/local-data/schema") {
      return json({
        kind: "indices",
        label: "Авторы и индексы",
        columns: [
          { field: "author_display_name", label: "Автор", type: "text", sortable: true, filterable: true },
          { field: "h", label: "Индекс Хирша", type: "number", sortable: true, filterable: true },
          { field: "p", label: "Публикации", type: "number", sortable: true, filterable: true },
          { field: "c", label: "Цитирования", type: "number", sortable: true, filterable: true },
          { field: "author_id", label: "ID автора", type: "text", sortable: true, filterable: true },
        ],
      });
    }
    if (path === "/local-data/preview") {
      return json(tablePayload("indices"));
    }
    if (path === "/analytics/ranking") return json(tablePayload("filtered_rating"));
    if (path === "/analytics/custom-metrics") return json({ run_id: runId, models: [] });
    if (path === "/analytics/scientometrics") return json({ schema: "scientometric_analysis", descriptive: [], correlations: [], findings: [], conclusion: "" });
    return json({});
  });
}

function tablePayload(table: string) {
  return {
    table,
    fields: ["author_display_name", "h", "p", "c", "author_id"],
    rows: [
      { author_display_name: "Иванов И. И.", h: 5, p: 10, c: 50, author_id: "A1" },
      { author_display_name: "Петров П. П.", h: 3, p: 8, c: 20, author_id: "A2" },
    ],
    total: 2,
    total_exact: true,
    has_more: false,
    limit: 100,
    offset: 0,
  };
}
