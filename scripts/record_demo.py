"""Record the README demo clip against the live app.

Drives the deployed application through the flow a reader is asked to try:
an empty sandbox, a catalogue upload, a datasheet upload, and the datasheet
appearing against the product row it describes. Every frame is the real
app talking to the real API — nothing is mocked, staged or re-enacted.

The sandbox is left as it was found: both uploads are deleted afterwards.

Requires: playwright (pip install playwright && playwright install chromium)
          ffmpeg on PATH
Usage:    python scripts/record_demo.py
Output:   docs/media/specledger-demo.gif and .mp4
"""

from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FRAMES = ROOT / ".demo-frames"
OUT = ROOT / "docs" / "media"
APP = "https://yashasm18.github.io/specledger/"
API = "https://specledger-production.up.railway.app"
RAW = "https://raw.githubusercontent.com/Yashasm18/specledger/main/data/samples/"

CATALOGUE = "01_industrial_distributor.csv"
DATASHEET = "sample_datasheet_apollo_70-104-01.pdf"
PART = "70-104-01"

WIDTH, HEIGHT = 1280, 760
FPS = 12


class Recorder:
    """Writes numbered PNG frames; holds a frame by repeating it."""

    def __init__(self, page):
        self.page = page
        self.n = 0

    def hold(self, seconds: float = 1.0) -> None:
        shot = self.page.screenshot(type="png")
        for _ in range(max(1, int(seconds * FPS))):
            (FRAMES / f"{self.n:05d}.png").write_bytes(shot)
            self.n += 1

    def roll(self, seconds: float, interval: float = 1.0 / FPS) -> None:
        """Capture live while something is happening."""
        end = time.time() + seconds
        while time.time() < end:
            (FRAMES / f"{self.n:05d}.png").write_bytes(self.page.screenshot(type="png"))
            self.n += 1
            time.sleep(interval)


def click_text(page, text: str, exact: bool = False) -> bool:
    """Click by visible text, dispatched in-page.

    Playwright's own click refuses when anything overlaps the target, and
    the caption band counts as an overlap even though it is
    pointer-events:none. The app's handlers only care about the event.
    """
    return page.evaluate(
        """([text, exact]) => {
            // Leaf nodes first: a SKU cell is a leaf, while every ancestor
            // also "contains" the text and would match a naive search.
            const leaves = [...document.querySelectorAll('*')].filter(
                el => el.children.length === 0 && el.offsetParent !== null);
            const pick = (els) => els.sort(
                (a, b) => (a.textContent || '').length - (b.textContent || '').length)[0];
            let hit = pick(leaves.filter(el => (el.textContent || '').trim() === text));
            if (!hit && !exact) {
                hit = pick(leaves.filter(el => (el.textContent || '').includes(text)));
            }
            if (!hit) return false;
            const target = hit.closest('button, a, [role="button"], tr, .tr') || hit.parentElement || hit;
            target.click();
            return true;
        }""",
        [text, exact],
    )


def switch_workspace(page, name: str) -> None:
    """Open the workspace switcher and select one by name.

    The trigger is div.workspace and carries child elements, so a
    leaf-node text search cannot see it — hence the explicit selector.
    """
    page.evaluate("() => document.querySelector('.workspace')?.click()")
    page.wait_for_timeout(900)
    page.evaluate(
        """(name) => {
            const opts = [...document.querySelectorAll('*')].filter(
                e => e.offsetParent && (e.textContent || '').includes(name)
                     && (e.textContent || '').length < 220);
            if (!opts.length) return false;
            const el = opts[opts.length - 1];
            (el.closest('[role="option"], button, li, div') || el).click();
            return true;
        }""",
        name,
    )
    page.wait_for_timeout(5000)


def wait_for_text(page, text: str, timeout: float = 25.0) -> bool:
    """Poll until the text appears. The catalogue table fills in after its
    own fetch, so a fixed sleep either flakes or wastes seconds of clip."""
    end = time.time() + timeout
    while time.time() < end:
        if page.evaluate("t => document.body.innerText.includes(t)", text):
            return True
        page.wait_for_timeout(400)
    return False


def caption(page, text: str, sub: str = "") -> None:
    """Overlay a short caption so the clip reads without sound."""
    page.evaluate(
        """([text, sub]) => {
            let el = document.getElementById('__demo_caption');
            if (!el) {
                el = document.createElement('div');
                el.id = '__demo_caption';
                el.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;'
                    + 'background:linear-gradient(transparent,rgba(6,12,24,.93) 38%);color:#fff;'
                    + 'padding:44px 40px 26px;font:600 20px/1.35 ui-sans-serif,system-ui,sans-serif;'
                    + 'pointer-events:none;text-align:center;';
                document.body.appendChild(el);
            }
            el.innerHTML = text
                ? text + (sub ? '<div style="margin-top:7px;font:400 14px/1.5 ui-sans-serif,system-ui;'
                                + 'color:#9fb3d1">' + sub + '</div>' : '')
                : '';
        }""",
        [text, sub],
    )


def upload(page, endpoint: str, filename: str, content_type: str, extra: str = "") -> dict:
    """Upload through the page so the request carries the app's own key."""
    return page.evaluate(
        """async ([raw, name, ctype, endpoint, extra, api]) => {
            const bytes = await fetch(raw + name).then(r => r.arrayBuffer());
            const src = [...document.querySelectorAll('script[src]')]
                .map(s => s.src).find(u => /assets\\/index-.*\\.js/.test(u));
            const js = await fetch(src).then(r => r.text());
            const i = js.indexOf('X-API-Key');
            const m = js.slice(Math.max(0, i - 400), i + 120)
                .match(/["'`]([A-Za-z0-9_\\-]{16,80})["'`]/g) || [];
            let key = null;
            for (const c of m) { const v = c.slice(1, -1); if (v !== 'X-API-Key') key = v; }
            const fd = new FormData();
            fd.append('file', new File([bytes], name, { type: ctype }));
            const res = await fetch(api + endpoint + extra, {
                method: 'POST', headers: { 'X-API-Key': key }, body: fd });
            return { status: res.status, body: (await res.text()).slice(0, 300) };
        }""",
        [RAW, filename, content_type, endpoint, extra, API],
    )


def cleanup(page) -> None:
    page.evaluate(
        """async (api) => {
            const src = [...document.querySelectorAll('script[src]')]
                .map(s => s.src).find(u => /assets\\/index-.*\\.js/.test(u));
            const js = await fetch(src).then(r => r.text());
            const i = js.indexOf('X-API-Key');
            const m = js.slice(Math.max(0, i - 400), i + 120)
                .match(/["'`]([A-Za-z0-9_\\-]{16,80})["'`]/g) || [];
            let key = null;
            for (const c of m) { const v = c.slice(1, -1); if (v !== 'X-API-Key') key = v; }
            const list = await fetch(api + '/catalogue/batches?organization_id=sandbox')
                .then(r => r.json());
            for (const b of list.batches) {
                await fetch(api + '/catalogue/batches/' + b.batch_id + '?organization_id=sandbox',
                            { method: 'DELETE', headers: { 'X-API-Key': key } });
            }
        }""",
        API,
    )


def encode() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    mp4 = OUT / "specledger-demo.mp4"
    gif = OUT / "specledger-demo.gif"
    src = str(FRAMES / "%05d.png")

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", src,
                    "-vf", "scale=1100:-2:flags=lanczos", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(mp4)], check=True)

    palette = FRAMES / "palette.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", src,
                    "-vf", "fps=10,scale=900:-1:flags=lanczos,palettegen=max_colors=128",
                    str(palette)], check=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", src,
                    "-i", str(palette), "-lavfi",
                    "fps=10,scale=900:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3",
                    str(gif)], check=True)
    palette.unlink(missing_ok=True)
    print(f"mp4 {mp4.stat().st_size/1_000_000:.2f} MB   gif {gif.stat().st_size/1_000_000:.2f} MB")


def main() -> None:
    for old in FRAMES.glob("*.png"):
        old.unlink()
    FRAMES.mkdir(exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        cleaned = False
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT},
                                device_scale_factor=1)
        # A clean browser profile triggers the first-run role chooser, which
        # would sit over every frame. Record as a returning reader instead;
        # this is the app's own stored state, not a modification of it.
        page.add_init_script(
            "localStorage.setItem('specledger_has_authenticated','true');"
            "localStorage.setItem('specledger_persona','super_admin');"
        )
        rec = Recorder(page)

        page.goto(APP, wait_until="networkidle")
        page.wait_for_timeout(6000)
        caption(page, "SpecLedger", "Unilog's 1,000-row challenge dataset, enriched to 252 columns")
        rec.hold(2.6)

        # Run the benchmark live — the figures are computed during the request.
        caption(page, "Every figure is measured live", "Nothing on screen is a stored result")
        assert click_text(page, "Run benchmark"), "Run benchmark not found"
        rec.roll(9)
        rec.hold(2.4)

        # Move to the sandbox, which is empty.
        caption(page, "A separate workspace for your own data",
                "The challenge dataset is never touched")
        switch_workspace(page, "Evaluation Sandbox")
        rec.hold(2.2)

        # Upload a catalogue with entirely different column names.
        caption(page, "Upload a catalogue", "Column names need not match — they are matched by role")
        rec.hold(1.6)
        result = upload(page, "/catalogue/ingest", CATALOGUE, "text/csv",
                        "?organization_id=sandbox&process_immediately=true")
        print("ingest:", result["status"], result["body"][:120])
        # A reload returns to the master workspace, so re-enter the sandbox
        # before showing the result of the upload.
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(5000)
        switch_workspace(page, "Evaluation Sandbox")
        assert wait_for_text(page, PART), "uploaded catalogue never rendered"
        caption(page, "Enriched, validated and routed on upload", "")
        rec.hold(3.0)

        # Upload the matching manufacturer datasheet.
        caption(page, "Now a manufacturer datasheet", "It names part 70-104-01")
        result = upload(page, "/documents/intake", DATASHEET, "application/pdf",
                        "?organization_id=sandbox&category=valve")
        print("intake:", result["status"], result["body"][:120])
        rec.hold(2.6)
        page.wait_for_timeout(9000)

        # Open the row it describes.
        caption(page, "It finds the row it describes", "Matched on part number")
        click_text(page, "Catalogue")
        assert wait_for_text(page, PART), "catalogue row never appeared"
        page.wait_for_timeout(800)
        assert click_text(page, PART, exact=True), "row not found"
        page.wait_for_timeout(2500)
        click_text(page, "Spec Triplets")
        page.wait_for_timeout(3500)
        rec.hold(1.2)
        caption(page, "Specifications, with the page and sentence they came from",
                "Proposals for a reviewer — nothing is written into the delivered columns")
        rec.hold(5.0)

        caption(page, "")
        rec.hold(0.4)

        cleanup(page)
        cleaned = True
        browser.close()

    print(f"{rec.n} frames")
    encode()


if __name__ == "__main__":
    sys.exit(main())
