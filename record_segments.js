'use strict';
const puppeteer = require('puppeteer');
const { execSync } = require('child_process');
const path = require('path');
const fs = require('fs');

const HTML_PATH = 'file:///' + path.resolve(__dirname, 'index.html').replace(/\\/g, '/');
const OUT_DIR   = path.resolve(__dirname, 'recording_output');

// Each segment: seek to (elapsed, phaseIndex, focusLocked), resume, stop when phaseIndex >= stopPhase
const SEGMENTS = [
  { id: 'seg1_initial_growth',  seekElapsed:     0, seekPhase: 0, locked: false, stopPhase: 1, maxMs: 15000 },
  { id: 'seg2_2018_to_2019',    seekElapsed: 12500, seekPhase: 1, locked: false, stopPhase: 3, maxMs:  3500 },
  { id: 'seg3_2019_to_2021',    seekElapsed: 14300, seekPhase: 3, locked: false, stopPhase: 4, maxMs:  5000 },
  { id: 'seg4_2021_to_2022',    seekElapsed: 17900, seekPhase: 4, locked: true,  stopPhase: 5, maxMs:  4000 },
  { id: 'seg5_2022_to_firing',  seekElapsed: 20300, seekPhase: 5, locked: true,  stopPhase: 6, maxMs: 12000 },
  { id: 'seg6_kortnie_arrival', seekElapsed: 28700, seekPhase: 8, locked: true,  stopPhase: 9, maxMs:  6000 },
];

// phaseNav select value → screenshot filename
const PHASE_SHOTS = [
  { id: 'phase1_ellner_director',    navIdx: '0' },
  { id: 'phase2_daniel_fired',       navIdx: '1' },
  { id: 'phase3_dayton_joins',       navIdx: '2' },
  { id: 'phase4_hanewinkel_joins',   navIdx: '3' },
  { id: 'phase5_five_depart',        navIdx: '4' },
  { id: 'phase6_meadows_terminated', navIdx: '5' },
  { id: 'phase7_sronce_joins',       navIdx: '6' },
];

async function waitForCondition(page, condFn, maxMs) {
  const deadline = Date.now() + maxMs;
  while (Date.now() < deadline) {
    if (await page.evaluate(condFn)) return true;
    await new Promise(r => setTimeout(r, 80));
  }
  return false;
}

async function newPage(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 720 });
  await page.goto(HTML_PATH, { waitUntil: 'networkidle0', timeout: 30000 });
  await page.waitForFunction(() => !!window.__anim, { timeout: 10000 });
  // Hide controls and toolbar for clean video
  await page.addStyleTag({ content: '.controls { display: none !important; } body { margin: 0; overflow: hidden; }' });
  await new Promise(r => setTimeout(r, 400));
  return page;
}

async function recordSegment(browser, seg) {
  console.log(`\nRecording ${seg.id} …`);
  const page = await newPage(browser);

  const webmPath = path.join(OUT_DIR, 'videos', `${seg.id}.webm`);
  const mp4Path  = path.join(OUT_DIR, 'videos', `${seg.id}.mp4`);

  // Seek to segment start position
  await page.evaluate(({ elapsed, phase, locked }) => {
    window.__anim.seekTo(elapsed, phase, locked);
  }, { elapsed: seg.seekElapsed, phase: seg.seekPhase, locked: seg.locked });

  await new Promise(r => setTimeout(r, 300));

  // Start recording
  const recorder = await page.screencast({ path: webmPath });

  // Resume animation
  await page.evaluate(() => window.__anim.resume());

  // Wait for stop condition
  const stopPhase = seg.stopPhase;
  const reached = await waitForCondition(
    page,
    () => window.__anim.phaseIndex >= stopPhase || window.__anim.ended,
    seg.maxMs
  );

  if (!reached) console.warn(`  WARNING: timed out waiting for phase ${stopPhase}`);

  await new Promise(r => setTimeout(r, 400)); // capture final frame
  await recorder.stop();
  await page.close();

  // Convert WebM → MP4 H.264 (Drive-compatible)
  execSync(
    `ffmpeg -y -i "${webmPath}" -c:v libx264 -preset medium -crf 22 -pix_fmt yuv420p -movflags +faststart "${mp4Path}"`,
    { stdio: 'inherit' }
  );
  console.log(`  Saved: ${mp4Path}`);
  return mp4Path;
}

async function screenshotPhase(browser, shot) {
  console.log(`\nScreenshotting ${shot.id} …`);
  const page = await newPage(browser);

  // Trigger phase nav
  await page.evaluate(idx => {
    const el = document.getElementById('phaseNav');
    el.value = idx;
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, shot.navIdx);

  await new Promise(r => setTimeout(r, 900)); // let overlay settle

  const imgPath = path.join(OUT_DIR, 'screenshots', `${shot.id}.png`);
  await page.screenshot({ path: imgPath, type: 'png', fullPage: false });
  await page.close();

  console.log(`  Saved: ${imgPath}`);
  return imgPath;
}

(async () => {
  fs.mkdirSync(path.join(OUT_DIR, 'videos'),       { recursive: true });
  fs.mkdirSync(path.join(OUT_DIR, 'screenshots'),  { recursive: true });

  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
  });

  const videos = [];
  for (const seg of SEGMENTS) {
    const mp4 = await recordSegment(browser, seg);
    videos.push({ id: seg.id, path: mp4 });
  }

  const screenshots = [];
  for (const shot of PHASE_SHOTS) {
    const img = await screenshotPhase(browser, shot);
    screenshots.push({ id: shot.id, path: img });
  }

  await browser.close();

  const manifest = { videos, screenshots };
  fs.writeFileSync(path.join(OUT_DIR, 'manifest.json'), JSON.stringify(manifest, null, 2));
  console.log('\nAll done. Run:  python build_slides.py');
})();
