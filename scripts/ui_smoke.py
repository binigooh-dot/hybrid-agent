"""[SCRIPTS / qa] Drive the GUI in a real (headless) browser and screenshot every screen.

    pip install playwright      # once; uses your installed Chromium/Chrome
    python scripts/ui_smoke.py [out_dir]

Starts the GUI in-process with the scripted backend (no model needed), then:
runs a council vote, chats, opens the persona editor (and checks the ASCII
face really animates), triggers an approval prompt, filters tools, restores a
backup from the Safety tab, runs the setup doctor. Fails on any JavaScript error.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hybrid_agent.core.config import Config
from hybrid_agent.gui.server import create_server


def main(out: Path) -> int:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(backend="scripted", workspace=tmp / "ws", log_dir=tmp / "logs", persona_dir=tmp / "personas")
    cfg.workspace.mkdir()
    srv, app = create_server(cfg, port=0, state=tmp)
    app.scheduler.start()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{app.port}/?token={app.token}"
    errors: list[str] = []
    chromium = "/opt/pw-browsers/chromium"
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium if os.path.exists(chromium) else None)
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        page.on("pageerror", lambda e: errors.append(f"{e} @ {(e.stack or '').splitlines()[1:3]}"))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(url)
        page.wait_for_selector(".pick")

        # --- council
        page.fill("#c-question", "Should a beginner learn Rust or Go first?")
        page.click("[data-proto=vote]")
        page.fill("#c-options", "Rust, Go")
        page.click("#c-run")
        page.wait_for_selector("#c-final:not(.hidden)", timeout=20000)
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / "1_council.png"), full_page=True)

        # --- chat with a persona
        page.click("[data-tab=chat]")
        page.select_option("#chat-persona", "nova")
        page.fill("#chat-input", "demo")
        page.press("#chat-input", "Enter")
        page.wait_for_selector(".msg.agent >> text=Demo complete", timeout=20000)
        page.screenshot(path=str(out / "2_chat.png"), full_page=True)

        # --- persona editor
        page.click("[data-tab=personas]")
        page.locator(".pcard", has_text="The Skeptic").first.click()
        page.click("#p-expr >> text=speaking")
        page.wait_for_timeout(300)
        frames = set()
        for _ in range(6):                       # the talking face must cycle frames
            frames.add(page.inner_text("#p-preview"))
            page.wait_for_timeout(240)
        if len(frames) < 2:
            errors.append("ASCII face did not animate")
        page.screenshot(path=str(out / "3_personas.png"), full_page=True)

        # --- approval prompt (as if an agent asked to run a command)
        result = {}
        t = threading.Thread(target=lambda: result.setdefault(
            "allowed", app.broker.approver("vex")("run_shell", {"command": "pytest -q"}, "execute tool")))
        t.start()
        page.wait_for_selector("#modal:not(.hidden)", timeout=5000)
        page.screenshot(path=str(out / "4_approval.png"))
        page.click("#m-no")
        t.join(5)
        if result.get("allowed") is not False:
            errors.append("Deny button did not deny")

        # --- tools + safety
        page.click("[data-tab=tools]")
        page.fill("#t-search", "csv")
        page.screenshot(path=str(out / "5_tools.png"), full_page=True)
        from hybrid_agent.security.backup import snapshot
        victim = cfg.workspace / "notes.txt"
        victim.write_text("original", encoding="utf-8")
        snapshot(cfg.workspace, victim, "edit")
        victim.write_text("changed by agent", encoding="utf-8")
        page.on("dialog", lambda d: d.accept())
        page.click("[data-tab=safety]")
        page.wait_for_selector("#s-backups >> text=Restore")
        page.screenshot(path=str(out / "6_safety.png"), full_page=True)
        page.click("#s-backups >> text=Restore")
        page.wait_for_timeout(500)
        if victim.read_text(encoding="utf-8") != "original":
            errors.append("Restore button did not restore the file")
        page.click("#s-doctor")
        page.wait_for_selector("#s-table tr >> nth=1")
        page.screenshot(path=str(out / "7_checks.png"), full_page=True)

        # --- tasks: create one, run it, open the result
        page.click("[data-tab=tasks]")
        page.fill("#tk-name", "Demo briefing")
        page.fill("#tk-prompt", "demo")
        page.select_option("#tk-sched", "daily")
        page.fill("#tk-time", "07:30")
        page.click("#tk-save-run")
        page.wait_for_selector("#run-list >> text=Demo briefing", timeout=20000)
        if "daily at 07:30" not in page.inner_text("#task-list"):
            errors.append("task schedule not shown")
        page.screenshot(path=str(out / "9_tasks.png"), full_page=True)
        page.click("#run-list >> text=Open")
        page.wait_for_selector("#viewer:not(.hidden)")
        if "Demo complete" not in page.inner_text("#v-text"):
            errors.append("task result viewer empty")
        page.click("#v-close")

        # --- control panel (engine status, models, settings, storage)
        page.click("[data-tab=control]")
        page.wait_for_selector("#storage dt")
        page.screenshot(path=str(out / "10_control.png"), full_page=True)

        # --- phone width
        page.set_viewport_size({"width": 390, "height": 844})
        page.click("[data-tab=council]")
        page.screenshot(path=str(out / "8_phone.png"), full_page=True)
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        browser.close()
    srv.shutdown()
    srv.server_close()
    if overflow:
        errors.append("horizontal scroll at phone width")
    print("screenshots:", out)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "logs" / "ui_smoke"))
