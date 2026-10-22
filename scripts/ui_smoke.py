"""[SCRIPTS / qa] Drive the app in a real (headless) browser and screenshot every screen.

    pip install playwright      # once; uses your installed Chromium/Chrome
    python scripts/ui_smoke.py [out_dir]       # default: docs/screenshots

Starts the app in-process with the scripted backend (no model needed), then: chats with an
agent, runs a council vote, edits an agent's face (and checks it really animates), answers an
approval prompt, creates and runs a task, restores a backup, runs the setup check, and shows
the one-click setup card a new user sees. Fails on any JavaScript error.
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


def start(backend: str):
    tmp = Path(tempfile.mkdtemp())
    cfg = Config(backend=backend, workspace=tmp / "ws", log_dir=tmp / "logs", agents_dir=tmp / "agents")
    cfg.workspace.mkdir()
    srv, app = create_server(cfg, port=0, state=tmp)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, app, cfg, f"http://127.0.0.1:{app.port}/?token={app.token}"


def main(out: Path) -> int:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    srv, app, cfg, url = start("scripted")
    app.scheduler.start()
    errors: list[str] = []
    chromium = "/opt/pw-browsers/chromium"
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chromium if os.path.exists(chromium) else None)
        page = browser.new_page(viewport={"width": 1360, "height": 860})
        page.on("pageerror", lambda e: errors.append(f"{e} @ {(e.stack or '').splitlines()[1:3]}"))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("dialog", lambda d: d.accept())
        page.goto(url)
        page.wait_for_selector("#chat-agent option", state="attached")

        # --- chat
        page.select_option("#chat-agent", "green")
        page.fill("#chat-input", "demo")
        page.press("#chat-input", "Enter")
        page.wait_for_selector(".msg.agent >> text=Demo complete", timeout=20000)
        page.screenshot(path=str(out / "1_chat.png"))

        # --- council
        page.click("[data-tab=council]")
        page.fill("#c-question", "Should a beginner learn Rust or Go first?")
        page.click("[data-proto=vote]")
        page.fill("#c-options", "Rust, Go")
        page.click("#c-run")
        page.wait_for_selector("#c-final:not(.hidden)", timeout=20000)
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / "2_council.png"), full_page=True)

        # --- agents: edit a face, check it animates
        page.click("[data-tab=agents]")
        page.locator(".acard", has_text="Orange").first.click()
        page.select_option("#f-eyes", "@")
        page.click("#a-expr >> text=talking")
        page.wait_for_timeout(300)
        frames = set()
        for _ in range(6):
            frames.add(page.inner_text("#a-preview"))
            page.wait_for_timeout(250)
        if len(frames) < 2:
            errors.append("ASCII face did not animate")
        if any(ord(c) > 126 for f in frames for c in f if c != "\n"):
            errors.append("face is not plain ASCII")
        page.click("#a-form button[type=submit]")
        page.wait_for_timeout(300)
        page.screenshot(path=str(out / "3_agents.png"))

        # --- approval prompt (as if an agent asked to run a command)
        result: dict = {}
        t = threading.Thread(target=lambda: result.setdefault(
            "allowed", app.broker.approver("orange")("run_shell", {"command": "pytest -q"}, "execute tool")))
        t.start()
        page.wait_for_selector("#modal:not(.hidden)", timeout=5000)
        page.screenshot(path=str(out / "4_approval.png"))
        page.click("#m-no")
        t.join(5)
        if result.get("allowed") is not False:
            errors.append("Deny button did not deny")

        # --- tasks: create one, run it, open the result
        page.click("[data-tab=tasks]")
        page.fill("#tk-name", "Morning briefing")
        page.fill("#tk-prompt", "demo")
        page.select_option("#tk-sched", "daily")
        page.fill("#tk-time", "07:30")
        page.click("#tk-save-run")
        page.wait_for_selector("#run-list >> text=Morning briefing", timeout=20000)
        if "daily at 07:30" not in page.inner_text("#task-list"):
            errors.append("task schedule not shown")
        page.screenshot(path=str(out / "5_tasks.png"))
        page.click("#run-list >> text=Open")
        page.wait_for_selector("#viewer:not(.hidden)")
        if "Demo complete" not in page.inner_text("#v-text"):
            errors.append("task result viewer empty")
        page.click("#v-close")

        # --- settings: undo a change, run the setup check
        from hybrid_agent.security.backup import snapshot
        victim = cfg.workspace / "notes.txt"
        victim.write_text("original", encoding="utf-8")
        snapshot(cfg.workspace, victim, "edit")
        victim.write_text("changed by agent", encoding="utf-8")
        page.click("[data-tab=settings]")
        page.wait_for_selector("#s-backups >> text=Restore")
        page.click("#s-backups >> text=Restore")
        page.wait_for_timeout(500)
        if victim.read_text(encoding="utf-8") != "original":
            errors.append("Restore button did not restore the file")
        page.click("#s-doctor")
        page.wait_for_selector("#s-table tr >> nth=1")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(3500)                  # let the toast fade
        page.screenshot(path=str(out / "6_settings.png"))

        # --- phone width
        page.set_viewport_size({"width": 390, "height": 844})
        page.click("[data-tab=chat]")
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        page.screenshot(path=str(out / "7_phone.png"))

        # --- what a brand-new user sees: the one-click setup card (local model, nothing installed yet)
        srv2, app2, _, url2 = start("local")
        if app2.runtime.status()["installed"]:
            print("note: a model engine is installed here, so the setup card may not show")
        page.set_viewport_size({"width": 1360, "height": 560})
        page.goto(url2)
        page.wait_for_selector("#setup:not(.hidden)", timeout=10000)
        if "Set up now" not in page.inner_text("#setup"):
            errors.append("setup card has no Set up button")
        page.screenshot(path=str(out / "0_setup.png"))
        srv2.shutdown()
        srv2.server_close()
        browser.close()
    srv.shutdown()
    srv.server_close()
    if overflow:
        errors.append("horizontal scroll at phone width")
    print("screenshots:", out)
    print("errors:", errors or "none")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "screenshots"))
