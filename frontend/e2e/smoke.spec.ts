import { expect, test } from "@playwright/test";

const TERMINAL = ["COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"];

test("submit with poison chunk -> terminal job with masks and gap marker", async ({
  page,
}) => {
  await page.goto("/");

  // Three healthy chunks are pre-selected; add the always-failing one via
  // the labeled toggle (two-way synced with the catalog row).
  const poisonToggle = page.getByLabel("include a chunk that always fails");
  await poisonToggle.check();
  await expect(page.getByLabel("select audio-file-8.wav")).toBeChecked();

  await page.getByRole("button", { name: /submit job/i }).click();
  await expect(page).toHaveURL(/\/jobs\/[0-9a-f-]{36}/);

  // Fan-out, retries on the poison chunk, stitch, and deid all happen within
  // the demo budget; polling stops once the status chip goes terminal.
  const status = page.getByTestId("job-status").locator("[data-status]");
  await expect
    .poll(async () => status.getAttribute("data-status"), { timeout: 75_000 })
    .toMatch(new RegExp(TERMINAL.join("|")));

  await expect(status).toHaveAttribute("data-status", "COMPLETED_WITH_ERRORS");

  // De-identified transcript: real mask chips plus the stitch gap marker for
  // the failed chunk.
  const transcript = page.getByTestId("transcript");
  await expect(transcript.locator("[data-mask]").first()).toBeVisible();
  await expect(transcript.locator("[data-gap]")).toHaveCount(1);

  // The failed chunk shows exhausted retries in the ledger.
  const strip = page.getByTestId("chunk-strip");
  await expect(strip.locator('[data-status="FAILED"]')).toHaveCount(1);
});

test("system panel reports live counters within the vendor cap", async ({ page }) => {
  await page.goto("/system");

  // The high-water mark card renders "hwm / capacity" and must respect the cap.
  const hwm = page.getByTestId("hwm");
  await expect(hwm).toBeVisible();
  const [mark, capacity] = (await hwm.innerText()).split("/").map(Number);
  expect(capacity).toBeGreaterThan(0);
  expect(mark).toBeLessThanOrEqual(capacity);
});
