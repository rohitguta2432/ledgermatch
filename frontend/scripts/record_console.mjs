// Frame-step the console replay and capture PNGs, then let ffmpeg make the clip.
// /console?t=<ms> renders the recorded run at that instant, so every frame is a
// deterministic screenshot of the real events file — capture speed is irrelevant.
//
//   node scripts/record_console.mjs [outDir] [baseUrl]
//   ffmpeg -framerate 30 -i outDir/f%04d.png -vf scale=1600:900 -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart clip.mp4

import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const OUT = process.argv[2] ?? "/tmp/ledgermatch-console-frames";
const BASE = process.argv[3] ?? "http://localhost:4321";

const W = 1600;
const H = 900;
const FPS = 30;
const SECONDS = 15;
const TOTAL = FPS * SECONDS;

// Wait for the server (next start / next dev) to answer before opening the page.
for (let i = 0; i < 60; i++) {
  try {
    if ((await fetch(`${BASE}/console`)).ok) break;
  } catch {}
  await new Promise((r) => setTimeout(r, 1000));
}

const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({ viewport: { width: W, height: H }, deviceScaleFactor: 2 });

await rm(OUT, { recursive: true, force: true });
await mkdir(OUT, { recursive: true });

await page.goto(`${BASE}/console?t=0`, { waitUntil: "networkidle" });
await page.waitForFunction(() => typeof window.__setT === "function");

for (let f = 0; f < TOTAL; f++) {
  const t = Math.round((f / FPS) * 1000);
  await page.evaluate((ms) => window.__setT(ms), t);
  await page.screenshot({ path: path.join(OUT, `f${String(f).padStart(4, "0")}.png`) });
  if (f % 90 === 0) console.log(`frame ${f}/${TOTAL}`);
}

await browser.close();
console.log(`${TOTAL} frames -> ${OUT}`);
