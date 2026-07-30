"""Tests-only independent Edge/CDP smoke and loaded-asset verifier for RC13-FV1-E1."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from queue import Empty, Queue
from pathlib import Path

import websocket


ROOT = Path(__file__).resolve().parents[1]
ASSETS = {
    "simulator-chapter-progression.js": ROOT / "web/static/simulator-chapter-progression.js",
    "simulator-context-navigator.js": ROOT / "web/static/simulator-context-navigator.js",
}


class Cdp:
    def __init__(self, url: str) -> None:
        self.ws = websocket.create_connection(url, timeout=15)
        self.next_id = 0

    def command(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        ident = self.next_id
        self.ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError(f"CDP {method}: {message['error']}")
                return message.get("result", {})

    def close(self) -> None:
        try:
            self.ws.settimeout(0.2)
            self.ws.sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            self.ws.close()
        except Exception:
            pass


def _json_url(url: str, method: str = "GET") -> dict:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _evaluate(cdp: Cdp, expression: str) -> object:
    result = cdp.command("Runtime.evaluate", {
        "expression": expression,
        "returnByValue": True,
        "awaitPromise": True,
    })
    return result.get("result", {}).get("value")


def _wait_for(cdp: Cdp, expression: str, timeout: float = 15.0) -> object:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            value = _evaluate(cdp, expression)
            if value:
                return value
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"browser condition timed out: {expression}")


def _durable_ledger(info: dict[str, object], operation_id: str, state: dict[str, object]) -> dict[str, object]:
    data = Path(str(info["project"])) / "data"
    operations = data / "chapter_progression" / "operations"
    claim = operations / f"{operation_id}.json"
    phase = operations / f"{operation_id}.phase.json"
    result = operations / f"{operation_id}.result.json"
    plans = data / "narrative_turn" / "plans" / "main" / "main"
    transitions = data / "narrative_turn" / "transitions" / "main" / "main"
    sequence_zero = 0
    for path in transitions.rglob("*.json") if transitions.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if int(payload.get("sequence", -1)) == 0 and payload.get("operation_id") == operation_id:
            sequence_zero += 1
    plan_count = 0
    for path in plans.glob("*.json") if plans.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if int(payload.get("chapter_id", 0) or 0) == 2:
            plan_count += 1
    phase_payload = {}
    if phase.exists():
        try:
            phase_payload = json.loads(phase.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            phase_payload = {}
    return {
        "claim": int(claim.exists()),
        "phase": int(phase.exists() and phase_payload.get("phase") == "completed"),
        "result": int(result.exists()),
        "turn_plan": plan_count,
        "sequence_0_transition": sequence_zero,
        "rebind": int(str(state.get("chapter_id") or "") == "2" and bool(state.get("workspace_visible"))),
    }


def _node_box(cdp: Cdp, selector: str) -> tuple[float, float]:
    root = cdp.command("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
    node = cdp.command("DOM.querySelector", {"nodeId": root, "selector": selector}).get("nodeId")
    if not node:
        raise RuntimeError(f"browser selector not found: {selector}")
    cdp.command("DOM.scrollIntoViewIfNeeded", {"nodeId": node})
    model = cdp.command("DOM.getBoxModel", {"nodeId": node})["model"]["content"]
    return ((model[0] + model[2]) / 2, (model[1] + model[5]) / 2)


def _click(cdp: Cdp, selector: str) -> None:
    x, y = _node_box(cdp, selector)
    cdp.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
    cdp.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})


def _select_next(cdp: Cdp, selector: str) -> None:
    _click(cdp, selector)
    for key, code, vk in (("ArrowDown", "ArrowDown", 40), ("Enter", "Enter", 13)):
        cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk})
        cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": vk})


def _select_prev(cdp: Cdp, selector: str) -> None:
    _click(cdp, selector)
    for key, code, vk in (("ArrowUp", "ArrowUp", 38), ("Enter", "Enter", 13)):
        cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": vk})
        cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": "ArrowUp" if key == "ArrowUp" else "Enter", "windowsVirtualKeyCode": vk})


def _activate_keyboard(cdp: Cdp, selector: str, key: str = " ") -> None:
    root = cdp.command("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
    node = cdp.command("DOM.querySelector", {"nodeId": root, "selector": selector}).get("nodeId")
    if not node:
        raise RuntimeError(f"browser selector not found: {selector}")
    cdp.command("DOM.focus", {"nodeId": node})
    cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": key, "code": "Space", "windowsVirtualKeyCode": 32})
    cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": key, "code": "Space", "windowsVirtualKeyCode": 32})


def _insert_text(cdp: Cdp, selector: str, value: str) -> None:
    root = cdp.command("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
    node = cdp.command("DOM.querySelector", {"nodeId": root, "selector": selector}).get("nodeId")
    if not node:
        raise RuntimeError(f"browser selector not found: {selector}")
    cdp.command("DOM.focus", {"nodeId": node})
    cdp.command("Input.insertText", {"text": value})


def _formal_completion(cdp: Cdp, info: dict[str, object]) -> dict[str, object]:
    """Drive the real successor Turn through the visible compile/review/commit UI."""
    print("formal: waiting READY", flush=True)
    _wait_for(cdp, "(() => { const b=document.querySelector('#simulator-chapter-progression-start'); return !!b && !b.disabled && !b.classList.contains('hidden'); })()")
    print("formal: click start", flush=True)
    _click(cdp, "#simulator-chapter-progression-start")
    _wait_for(cdp, "new URLSearchParams(location.search).get('chapter_id') === '2' && !!document.querySelector('#narrative-turn-workspace:not(.hidden)')")
    print("formal: successor loaded", flush=True)
    _wait_for(cdp, '''!!document.querySelector("input[name='narrative-turn-action']:not([disabled])")''')
    print("formal: select recommended action", flush=True)
    _activate_keyboard(cdp, "input[name='narrative-turn-action']:not([disabled])")
    print("formal: wait feasibility", flush=True)
    try:
        _wait_for(cdp, "!!document.querySelector('#nt-feasibility-panel:not(.hidden)') && !!document.querySelector('#nt-consequence-preview:not(.hidden)')", 30)
    except RuntimeError as exc:
        debug = _evaluate(cdp, "JSON.stringify({url:location.href, checked:[...document.querySelectorAll('input[name=\\\"narrative-turn-action\\\"]')].map(x=>({checked:x.checked,disabled:x.disabled,value:x.value})), feasibility:document.querySelector('#nt-feasibility-panel')?.textContent||'', preview:document.querySelector('#nt-consequence-preview')?.textContent||'', notice:document.querySelector('#nt-status-notice')?.textContent||''})")
        raise RuntimeError(f"{exc}; debug={debug}") from exc
    try:
        _wait_for(cdp, "(() => { const b=document.querySelector('#nt-primary-action'); return !!b && !b.disabled; })()", 30)
    except RuntimeError as exc:
        debug = _evaluate(cdp, "JSON.stringify({url:location.href, primary:document.querySelector('#nt-primary-action')?.disabled, feasibility:document.querySelector('#nt-feasibility-panel')?.textContent||'', preview:document.querySelector('#nt-consequence-preview')?.textContent||'', notice:document.querySelector('#nt-status-notice')?.textContent||''})")
        raise RuntimeError(f"{exc}; debug={debug}") from exc
    _click(cdp, "#nt-primary-action")
    print("formal: confirmed", flush=True)
    _wait_for(cdp, "!!document.querySelector('#nt-confirm-result:not(.hidden)')")
    _click(cdp, "[data-loop-view='candidate']")
    print("formal: wait compile", flush=True)
    try:
        _wait_for(cdp, "(() => { const b=document.querySelector('#simulator-candidate-compile'); return !!b && !b.disabled; })()", 30)
    except RuntimeError as exc:
        debug = _evaluate(cdp, "JSON.stringify({url:location.href, compile:document.querySelector('#simulator-candidate-compile')?.disabled, candidate:document.querySelector('#simulator-candidate-list-panel')?.textContent||'', status:document.querySelector('#simulator-loop-status')?.textContent||''})")
        raise RuntimeError(f"{exc}; debug={debug}") from exc
    _click(cdp, "#simulator-candidate-compile")
    print("formal: wait review", flush=True)
    try:
        _wait_for(cdp, "!!document.querySelector('#simulator-candidate-workspace:not(.hidden)') && !!document.querySelector('[data-candidate-approve]:not([disabled])')", 30)
    except RuntimeError as exc:
        debug = _evaluate(cdp, "JSON.stringify({url:location.href, workspace:document.querySelector('#simulator-candidate-workspace')?.className, approve:document.querySelector('[data-candidate-approve]')?.disabled, list:document.querySelector('#simulator-candidate-list-panel')?.textContent||'', status:document.querySelector('#simulator-loop-status')?.textContent||''})")
        audit = json.loads(Path(str(info["audit"])).read_text(encoding="utf-8")) if Path(str(info["audit"])).exists() else None
        debug = f"{debug}; audit={audit}"
        raise RuntimeError(f"{exc}; debug={debug}") from exc
    _click(cdp, "[data-candidate-approve]:not([disabled])")
    print("formal: wait commit", flush=True)
    _wait_for(cdp, "!!document.querySelector('[data-commit-open]:not(.hidden):not([disabled])')", 20)
    _click(cdp, "[data-commit-open]:not(.hidden):not([disabled])")
    _wait_for(cdp, "!!document.querySelector('[data-commit-confirm]:not([disabled])')")
    ownership_before_commit = _evaluate(cdp, "window.StoryOSChapterProgression?.getState()?.status || ''")
    _click(cdp, "[data-commit-confirm]:not([disabled])")
    print("formal: wait completion", flush=True)
    _wait_for(cdp, "!!document.querySelector('#simulator-chapter-completion:not(.hidden)')", 25)
    time.sleep(1.0)
    audit_path = Path(str(info["audit"]))
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"requests": []}
    return {
        "url": str(_evaluate(cdp, "location.href")),
        "completion_visible": bool(_evaluate(cdp, "!!document.querySelector('#simulator-chapter-completion:not(.hidden)')")),
        "progression_state": _evaluate(cdp, "document.querySelector('#simulator-chapter-progression')?.dataset.progressionState || ''"),
        "ownership_before_commit": ownership_before_commit,
        "completion_text": _evaluate(cdp, "document.querySelector('#simulator-completion-body')?.textContent || ''"),
        "audit": audit,
    }


def run(
    executable: Path,
    readiness_delay: float = 0.0,
    scenario: str = "assets",
    drop_start_response: bool = False,
    start_delay: float = 0.0,
) -> dict:
    profile = Path(tempfile.mkdtemp(prefix="phase0d6c_rc13_fv1_e1_browser_"))
    port = _free_port()
    fixture_port = _free_port()
    fixture = None
    browser = None
    cdp = None
    lifecycle: dict[str, float] = {}
    def mark(stage: str) -> None:
        lifecycle[stage] = time.monotonic()
    try:
        print(f"{scenario}: starting fixture", flush=True)
        mark("fixture_process_started")
        fixture = subprocess.Popen(
            [sys.executable, "-u", "tests/_phase0d6c_fv_browser_fixture_server.py"],
            cwd=ROOT,
            env={
                **os.environ,
                "STORYOS_RC4_READINESS_DELAY": str(readiness_delay),
                "STORYOS_FV_DROP_START_RESPONSE": "1" if drop_start_response else "0",
                "STORYOS_FV_START_DELAY": str(start_delay),
                "STORYOS_FV_PORT": str(fixture_port),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        info = None
        startup_lines: Queue[str] = Queue()
        threading.Thread(
            target=lambda: [startup_lines.put(line) for line in (fixture.stdout or [])],
            daemon=True,
        ).start()
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                line = startup_lines.get(timeout=0.2)
            except Empty:
                continue
            if line.startswith("{"):
                info = json.loads(line)
                break
        if not info:
            detail = "fixture exited before startup JSON" if fixture.poll() is not None else "fixture startup JSON timeout"
            raise RuntimeError(f"{detail}; fixture_port={fixture_port}")
        print(f"{scenario}: fixture ready", flush=True)
        mark("fixture_port_ready")
        browser = subprocess.Popen([
            str(executable), "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={profile}",
            "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        mark("edge_process_started")
        version = None
        for _ in range(300):
            try:
                version = _json_url(f"http://127.0.0.1:{port}/json/version")
                break
            except Exception:
                time.sleep(0.1)
        if not version:
            raise RuntimeError("browser CDP endpoint did not start")
        print(f"{scenario}: browser CDP ready", flush=True)
        mark("cdp_endpoint_ready")
        navigation_url = str(info["url"])
        if scenario in {"cross-project-get", "cross-project-post", "rapid-project"}:
            navigation_url = navigation_url.replace("view=narrative-turn", "view=reader-panel-review")
        elif scenario == "mismatch":
            navigation_url = f"{navigation_url}&project={info['project_b']['project_id']}"
        target = _json_url(
            f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote('about:blank', safe=':/?=&')}",
            method="PUT",
        )
        print(f"{scenario}: target created", flush=True)
        mark("target_page_created")
        cdp = Cdp(target["webSocketDebuggerUrl"])
        cdp.command("Network.enable")
        cdp.command("Network.setCacheDisabled", {"cacheDisabled": True})
        cdp.command("Network.clearBrowserCache")
        cdp.command("Page.enable")
        cdp.command("DOM.enable")
        cdp.command("Runtime.enable")
        mark("navigation_started")
        cdp.command("Page.navigate", {"url": navigation_url})
        cdp.ws.settimeout(1)
        if scenario == "formal-completion":
            result = _formal_completion(cdp, info)
            result["browser"] = version
            result["profile"] = str(profile)
            result["profile_preexisting"] = False
            result["cache_disabled"] = True
            return result
        if scenario in {"response-loss", "normal-exactly-once"}:
            _wait_for(cdp, "(() => { const b=document.querySelector('#simulator-chapter-progression-start'); return !!b && !b.disabled && !b.classList.contains('hidden'); })()")
            _click(cdp, "#simulator-chapter-progression-start")
            retry_state = None
            if scenario == "response-loss":
                _wait_for(cdp, "document.querySelector('#simulator-chapter-progression-start')?.textContent === 'Retry start safely'", 20)
                retry_state = _evaluate(cdp, "window.StoryOSChapterProgression?.getState() || null")
                _click(cdp, "#simulator-chapter-progression-start")
            _wait_for(cdp, "new URLSearchParams(location.search).get('chapter_id') === '2' && !!document.querySelector('#narrative-turn-workspace:not(.hidden)')", 20)
            audit_path = Path(str(info["audit"]))
            audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"requests": []}
            starts = [item for item in audit.get("requests", []) if item.get("path") == "/api/chapter-progression/start-turn"]
            operation_id = str((starts[0].get("body") or {}).get("operation_id") or "") if starts else ""
            state = _evaluate(cdp, "(() => { const q=new URLSearchParams(location.search); const p=window.StoryOSChapterProgression?.getState?.()||{}; return {chapter_id:q.get('chapter_id'), status:p.status||'', workspace_visible:!!document.querySelector('#narrative-turn-workspace:not(.hidden)')}; })()")
            ledger = _durable_ledger(info, operation_id, state) if operation_id else {}
            return {
                "browser": version,
                "profile": str(profile),
                "profile_preexisting": False,
                "cache_disabled": True,
                "retry_state": retry_state,
                "state": state,
                "audit": audit,
                "start_count": len(starts),
                "same_request_body": len(starts) == 2 and starts[0].get("body") == starts[1].get("body"),
                "dropped_first_response": bool(starts) and bool(starts[0].get("dropped")),
                "unique_operation_ids": sorted({str((item.get("body") or {}).get("operation_id") or "") for item in starts}),
                "durable_ledger": ledger,
            }
        if scenario in {"switch-back", "rapid-branch", "rapid-project", "history", "existing-turn"}:
            _wait_for(cdp, "(() => { const b=document.querySelector('#simulator-chapter-progression-start'); return !!b && !b.disabled && !b.classList.contains('hidden'); })()")
            audit_path = Path(str(info["audit"]))
            if scenario == "switch-back":
                _select_next(cdp, "#nt-context-branch")
                _wait_for(cdp, "new URLSearchParams(location.search).get('branch_id') === 'sibling'")
                _select_prev(cdp, "#nt-context-branch")
                time.sleep(max(0.0, readiness_delay) + 0.8)
                state = _evaluate(cdp, "(() => { const q=new URLSearchParams(location.search); const p=window.StoryOSChapterProgression?.getState?.()||{}; return {branch:q.get('branch_id'), status:p.status||'', context:p.context||null, workspace_visible:!!document.querySelector('#narrative-turn-workspace:not(.hidden)'), start_visible:!!document.querySelector('#simulator-chapter-progression-start:not(.hidden)')}; })()")
            elif scenario == "rapid-branch":
                for _ in range(3):
                    _select_next(cdp, "#nt-context-branch")
                time.sleep(max(0.0, readiness_delay) + 0.8)
                state = _evaluate(cdp, "(() => { const q=new URLSearchParams(location.search); const p=window.StoryOSChapterProgression?.getState?.()||{}; return {branch:q.get('branch_id'), status:p.status||'', context:p.context||null, workspace_visible:!!document.querySelector('#narrative-turn-workspace:not(.hidden)'), start_visible:!!document.querySelector('#simulator-chapter-progression-start:not(.hidden)')}; })()")
            elif scenario == "rapid-project":
                _wait_for(cdp, "(() => { const q=document.querySelector('#simulator-context-project'); return !!q && !q.disabled && q.options.length >= 2; })()")
                for _ in range(3):
                    _select_next(cdp, "#simulator-context-project")
                time.sleep(max(0.0, readiness_delay) + 0.8)
                state = _evaluate(cdp, "(() => { const q=new URLSearchParams(location.search); const p=window.StoryOSChapterProgression?.getState?.()||{}; const s=window.StoryOSSimulatorLoop?.getState?.()||{}; return {project:q.get('project'), project_id:q.get('project_id'), status:p.status||'', context:p.context||null, scope:s.scope||null, workspace_visible:!!document.querySelector('#narrative-turn-workspace:not(.hidden)'), start_visible:!!document.querySelector('#simulator-chapter-progression-start:not(.hidden)')}; })()")
            else:
                _click(cdp, "#simulator-chapter-progression-start")
                _wait_for(cdp, "new URLSearchParams(location.search).get('chapter_id') === '2' && !!document.querySelector('#narrative-turn-workspace:not(.hidden)')", 20)
                if scenario == "existing-turn":
                    print("existing-turn: started " + str(_evaluate(cdp, "location.href")), flush=True)
                    _evaluate(cdp, "history.back()")
                    time.sleep(0.8)
                    print("existing-turn: after back " + str(_evaluate(cdp, "location.href")), flush=True)
                    _wait_for(cdp, "new URLSearchParams(location.search).get('chapter_id') === '1'", 15)
                    time.sleep(0.5)
                    state = _evaluate(cdp, "(() => { const p=window.StoryOSChapterProgression?.getState?.()||{}; return {url:location.href, status:p.status||'', context:p.context||null, existing_turn:!!document.querySelector('[data-existing-turn-continue]:not(.hidden)'), workspace_visible:!!document.querySelector('#narrative-turn-workspace:not(.hidden)')}; })()")
                else:
                    _evaluate(cdp, "window.__fv_popstates=0; window.addEventListener('popstate',()=>window.__fv_popstates++)")
                    print("history: started " + str(_evaluate(cdp, "location.href")), flush=True)
                    _evaluate(cdp, "history.back()")
                    time.sleep(0.8)
                    print("history: after back " + str(_evaluate(cdp, "location.href")), flush=True)
                    _wait_for(cdp, "new URLSearchParams(location.search).get('chapter_id') === '1'", 15)
                    back_state = _evaluate(cdp, "(() => { const p=window.StoryOSChapterProgression?.getState?.()||{}; return {url:location.href, status:p.status||'', context:p.context||null, visible:!!document.querySelector('#narrative-turn-workspace:not(.hidden)')}; })()")
                    _evaluate(cdp, "history.forward()")
                    time.sleep(0.8)
                    print("history: after forward " + str(_evaluate(cdp, "location.href")), flush=True)
                    _wait_for(cdp, "new URLSearchParams(location.search).get('chapter_id') === '2'", 15)
                    forward_state = _evaluate(cdp, "(() => { const p=window.StoryOSChapterProgression?.getState?.()||{}; return {url:location.href, status:p.status||'', context:p.context||null, visible:!!document.querySelector('#narrative-turn-workspace:not(.hidden)')}; })()")
                    state = {"back": back_state, "forward": forward_state, "popstate_count": _evaluate(cdp, "window.__fv_popstates || 0")}
            audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"requests": []}
            starts = [item for item in audit.get("requests", []) if item.get("path") == "/api/chapter-progression/start-turn"]
            readiness = [item for item in audit.get("requests", []) if item.get("path") == "/api/chapter-progression/readiness"]
            return {"browser": version, "profile_preexisting": False, "cache_disabled": True, "state": state,
                    "audit": audit, "start_count": len(starts), "readiness_count": len(readiness),
                    "operation_ids": sorted({str((item.get("body") or {}).get("operation_id") or "") for item in starts})}
        if scenario == "traditional-get":
            _wait_for(cdp, "document.readyState !== 'loading'", 20)
            mark("dom_ready")
            _wait_for(cdp, "typeof window.StoryOSChapterProgression === 'object' && typeof window.StoryOSContextNavigator === 'object'", 20)
            mark("core_js_loaded")
            _wait_for(cdp, "window.StoryOSChapterProgression?.getState?.()?.status === 'LOADING_READINESS'", 20)
            mark("model_ready")
            _click(cdp, "[data-storyos-mode='traditional']")
            _wait_for(cdp, "new URLSearchParams(location.search).get('mode') === 'traditional'", 10)
            mark("scenario_ready")
            audit_path = Path(str(info["audit"]))
            deadline = time.time() + max(10.0, readiness_delay + 5.0)
            while time.time() < deadline:
                try:
                    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"requests": []}
                except (OSError, json.JSONDecodeError):
                    audit = {"requests": []}
                readiness = [item for item in audit.get("requests", []) if item.get("path") == "/api/chapter-progression/readiness"]
                if readiness and readiness[-1].get("response_released_monotonic"):
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("traditional GET audit response release timeout")
            state = _evaluate(cdp, """(() => {
              const q=new URLSearchParams(location.search);
              const p=window.StoryOSChapterProgression?.getState?.()||{};
              return {mode:q.get('mode'), status:p.status||'', start_intent:p.startIntent||null,
                visible:!!document.querySelector('#simulator-chapter-progression:not(.hidden)'),
                start_visible:!!(() => { const b=document.querySelector('#simulator-chapter-progression-start'); return b && !b.classList.contains('hidden') && b.offsetParent !== null; })()};
            })()""")
            return {"browser": version, "profile_preexisting": False, "cache_disabled": True, "state": state, "audit": audit, "lifecycle": lifecycle}
        if scenario in {"traditional-post", "cross-project-post", "sibling-post"}:
            print(f"{scenario}: waiting READY", flush=True)
            print(f"{scenario}: prewait " + str(_evaluate(cdp, "JSON.stringify({ready:document.readyState, navigator:typeof window.StoryOSContextNavigator, loop:typeof window.StoryOSSimulatorLoop, progression:typeof window.StoryOSChapterProgression, scripts:[...document.scripts].map(s=>s.src).filter(Boolean).slice(-8)})")), flush=True)
            if scenario == "sibling-post":
                print("sibling-post: initial state " + str(_evaluate(cdp, "JSON.stringify({url:location.search, progression:window.StoryOSChapterProgression?.getState?.()||null, button:document.querySelector('#simulator-chapter-progression-start')?.outerHTML||'', branch:document.querySelector('#nt-context-branch')?.outerHTML||''})")), flush=True)
            _wait_for(cdp, "(() => { const b=document.querySelector('#simulator-chapter-progression-start'); return !!b && !b.disabled && !b.classList.contains('hidden'); })()")
            if scenario == "cross-project-post":
                _wait_for(cdp, "(() => { const q=document.querySelector('#simulator-context-project'); return !!q && !q.disabled && q.options.length >= 2; })()")
            _click(cdp, "#simulator-chapter-progression-start")
            print(f"{scenario}: start clicked", flush=True)
            audit_path = Path(str(info["audit"]))
            deadline = time.time() + 15
            while time.time() < deadline:
                audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"requests": []}
                if any(item.get("path") == "/api/chapter-progression/start-turn" and item.get("durable_effect_monotonic") for item in audit.get("requests", [])):
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError("durable start effect was not recorded before switch")
            if scenario == "traditional-post":
                _click(cdp, "[data-storyos-mode='traditional']")
            elif scenario == "cross-project-post":
                _select_next(cdp, "#simulator-context-project")
            else:
                _select_next(cdp, "#nt-context-branch")
            print(f"{scenario}: context switched", flush=True)
            time.sleep(max(0.0, start_delay) + 0.75)
            state = _evaluate(cdp, """(() => {
              const q=new URLSearchParams(location.search);
              const p=window.StoryOSChapterProgression?.getState?.()||{};
              return {mode:q.get('mode'), project:q.get('project'), project_id:q.get('project_id'),
                branch:q.get('branch_id'), chapter:q.get('chapter_id'), status:p.status||'',
                context:p.context||null, start_intent:p.startIntent||null,
                workspace_visible:!!document.querySelector('#narrative-turn-workspace:not(.hidden)'),
                start_visible:!!document.querySelector('#simulator-chapter-progression-start:not(.hidden)')};
            })()""")
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            starts = [item for item in audit.get("requests", []) if item.get("path") == "/api/chapter-progression/start-turn"]
            print(f"{scenario}: evidence collected", flush=True)
            return {"browser": version, "profile_preexisting": False, "cache_disabled": True,
                    "project_a": info.get("project_a"), "project_b": info.get("project_b"),
                    "state": state, "audit": audit, "start_count": len(starts),
                    "operation_ids": sorted({str((item.get("body") or {}).get("operation_id") or "") for item in starts})}
        if scenario == "mismatch":
            time.sleep(1.0)
            state = _evaluate(cdp, "(() => { const p=new URLSearchParams(location.search); const progression=window.StoryOSChapterProgression?.getState?.()||{}; return {project:p.get('project'), project_id:p.get('project_id'), progression_status:progression.status||'', progression_context:progression.context||null, visible:!!document.querySelector('#simulator-chapter-progression:not(.hidden)'), start_visible:!!document.querySelector('#simulator-chapter-progression-start:not(.hidden)')}; })()")
            audit_path = Path(str(info["audit"]))
            audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"requests": []}
            return {"browser": version, "profile": str(profile), "profile_preexisting": False, "cache_disabled": True, "state": state, "audit": audit, "fail_closed": state.get("progression_status") in {"UNAVAILABLE", "CORRUPT"} and not state.get("visible") and not state.get("start_visible") and not audit.get("requests")}
        if scenario == "cross-project-get":
            print("cross: waiting project dropdown", flush=True)
            _wait_for(cdp, "(() => { const q=document.querySelector('#simulator-context-project'); return !!q && !q.disabled && q.options.length >= 2; })()")
            print("cross: project dropdown ready", flush=True)
            _wait_for(cdp, "(() => { const s=window.StoryOSSimulatorLoop?.getState?.(); const p=new URLSearchParams(location.search).get('project_id'); return !!s && !!s.scope && s.scope.project_id === p; })()")
            print("cross: model ready", flush=True)
            _wait_for(cdp, "['LOADING_READINESS','READY','BLOCKED','RECOVERY_REQUIRED','EXISTING_TURN'].includes(window.StoryOSChapterProgression?.getState?.()?.status || '')", 10)
            print("cross: progression requested", flush=True)
            time.sleep(min(0.05, max(0.0, readiness_delay) / 4.0))
            before = _evaluate(cdp, "(() => { const p=new URLSearchParams(location.search); return {project:p.get('project'), project_id:p.get('project_id'), selected:document.querySelector('#simulator-context-project')?.value||''}; })()")
            _select_next(cdp, "#simulator-context-project")
            time.sleep(max(0.0, readiness_delay) + 1.0)
            after = _evaluate(cdp, """(() => {
              const q = new URLSearchParams(location.search);
              const p = document.querySelector('#simulator-chapter-progression');
              const start = document.querySelector('#simulator-chapter-progression-start');
              return {
                project: q.get('project'),
                project_id: q.get('project_id'),
                selected_project: document.querySelector('#simulator-context-project')?.value || '',
                navigator_project: window.__storyosSimulatorContext?.project_id || '',
                model_project: window.StoryOSChapterProgression?.getState()?.context?.project_id || '',
                model_branch: window.StoryOSSimulatorLoop?.getState()?.branch || null,
                model_scope: window.StoryOSSimulatorLoop?.getState()?.scope || null,
                model_turn: window.StoryOSSimulatorLoop?.getState()?.turn || null,
                model_chapter_progression: window.StoryOSSimulatorLoop?.getState()?.chapter_progression || null,
                progression_context: window.StoryOSChapterProgression?.getState?.()?.context || null,
                progression_status: window.StoryOSChapterProgression?.getState?.()?.status || '',
                progression_state: p?.dataset.progressionState || '',
                start_visible: !!start && !start.classList.contains('hidden'),
                scope: document.querySelector('#simulator-chapter-progression-scope')?.textContent || '',
                status: document.querySelector('#simulator-chapter-progression-status')?.textContent || ''
              };
            })()""")
            audit_path = Path(str(info["audit"]))
            audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else {"requests": []}
            project_b_id = str((info.get("project_b") or {}).get("project_id") or "")
            scope_switched = bool(
                project_b_id
                and after.get("project_id") == project_b_id
                and after.get("model_project") == project_b_id
            )
            return {
                "browser": version,
                "profile": str(profile),
                "profile_preexisting": False,
                "cache_disabled": True,
                "project_a": info.get("project_a"),
                "project_b": info.get("project_b"),
                "before": before,
                "after": after,
                "audit": audit,
                "scope_switched_to_b": scope_switched,
                "stale_a_rendered_in_b": bool(
                    not scope_switched
                    and after.get("selected_project") == project_b_id
                    and after.get("start_visible")
                ),
            }
        if scenario == "sibling-get":
            time.sleep(0.5)
            root = cdp.command("DOM.getDocument", {"depth": 1})["root"]["nodeId"]
            node = cdp.command("DOM.querySelector", {"nodeId": root, "selector": "#nt-context-branch"}).get("nodeId")
            if not node:
                raise RuntimeError("branch dropdown was not rendered")
            cdp.command("DOM.scrollIntoViewIfNeeded", {"nodeId": node})
            model = cdp.command("DOM.getBoxModel", {"nodeId": node})["model"]["content"]
            rect = {"x": (model[0] + model[2]) / 2, "y": (model[1] + model[5]) / 2}
            cdp.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": rect["x"], "y": rect["y"], "button": "left", "clickCount": 1})
            cdp.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": rect["x"], "y": rect["y"], "button": "left", "clickCount": 1})
            cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40})
            cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "ArrowDown", "code": "ArrowDown", "windowsVirtualKeyCode": 40})
            cdp.command("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            cdp.command("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13})
            time.sleep(max(0.0, readiness_delay) + 0.5)
            return {
                "browser": version,
                "profile": str(profile),
                "profile_preexisting": False,
                "cache_disabled": True,
                "scenario": cdp.command("Runtime.evaluate", {"expression": "(() => { const p=document.querySelector('#simulator-chapter-progression'); const s=document.querySelector('#simulator-chapter-progression-scope'); const b=document.querySelector('#simulator-chapter-progression-start'); const q=document.querySelector('#nt-context-branch'); return {url:location.search, branch:q&&q.value, progressionState:p&&p.dataset.progressionState, progressionVisible:!!p&&!p.classList.contains('hidden'), scope:s&&s.textContent, startVisible:!!b&&!b.classList.contains('hidden'), status:document.querySelector('#simulator-chapter-progression-status')?.textContent||''}; })()", "returnByValue": True})["result"].get("value"),
                "audit": json.loads(Path(info["audit"]).read_text(encoding="utf-8")) if Path(info["audit"]).exists() else None,
            }
        if scenario == "assets":
            _wait_for(cdp, "document.readyState === 'complete'")
            tree = cdp.command("Page.getResourceTree").get("frameTree", {})
            resources: list[tuple[str, str]] = []
            def collect(node: dict) -> None:
                frame_id = str((node.get("frame") or {}).get("id") or "")
                for resource in node.get("resources") or []:
                    resources.append((frame_id, str(resource.get("url") or "")))
                for child in node.get("childFrames") or []:
                    collect(child)
            collect(tree)
            evidence: dict[str, dict[str, object]] = {}
            for name, path in ASSETS.items():
                matched = next(((frame_id, url) for frame_id, url in resources if name in url), None)
                browser_bytes = b""
                url = ""
                if matched:
                    frame_id, url = matched
                    content = cdp.command("Page.getResourceContent", {"frameId": frame_id, "url": url})
                    browser_bytes = base64.b64decode(content.get("content", "")) if content.get("base64Encoded") else str(content.get("content") or "").encode()
                disk = path.read_bytes()
                evidence[name] = {
                    "url": url,
                    "disk_sha256": hashlib.sha256(disk).hexdigest(),
                    "browser_sha256": hashlib.sha256(browser_bytes).hexdigest() if browser_bytes else None,
                    "match": bool(browser_bytes) and browser_bytes == disk,
                }
            return {"browser": version, "profile": str(profile), "profile_preexisting": False, "cache_disabled": True, "service_worker_controlled": bool(_evaluate(cdp, "!!navigator.serviceWorker?.controller")), "assets": evidence}
        responses: dict[str, dict] = {}
        bodies: dict[str, bytes] = {}
        finished: set[str] = set()
        until = time.time() + 12
        while time.time() < until and len(bodies) < len(ASSETS):
            try:
                event = json.loads(cdp.ws.recv())
            except Exception:
                continue
            method = event.get("method")
            params = event.get("params", {})
            if method == "Network.responseReceived":
                response = params.get("response", {})
                name = next((name for name in ASSETS if name in response.get("url", "")), None)
                if name:
                    responses[name] = {
                        "url": response.get("url"), "status": response.get("status"),
                        "mimeType": response.get("mimeType"),
                        "fromDiskCache": response.get("fromDiskCache", False),
                        "fromServiceWorker": response.get("fromServiceWorker", False),
                        "requestId": params.get("requestId"),
                    }
            elif method == "Network.loadingFinished":
                request_id = params.get("requestId")
                if request_id:
                    finished.add(request_id)
        for name, item in responses.items():
            request_id = item.get("requestId")
            if request_id not in finished:
                continue
            try:
                body = cdp.command("Network.getResponseBody", {"requestId": request_id})
                raw = base64.b64decode(body["body"]) if body.get("base64Encoded") else body["body"].encode()
                bodies[name] = raw
            except Exception:
                # A response can expire before body retrieval; retain the
                # provenance record and report the hash as unavailable.
                continue
        result = {
            "browser": version,
            "profile": str(profile),
            "profile_preexisting": False,
            "cache_disabled": True,
            "assets": {},
        }
        for name, path in ASSETS.items():
            disk = path.read_bytes()
            item = responses.get(name, {})
            browser_bytes = bodies.get(name, b"")
            item.update({
                "disk_sha256": hashlib.sha256(disk).hexdigest(),
                "browser_sha256": hashlib.sha256(browser_bytes).hexdigest() if browser_bytes else None,
                "match": bool(browser_bytes) and browser_bytes == disk,
            })
            result["assets"][name] = item
        return result
    finally:
        if cdp:
            cdp.close()
        if browser:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(browser.pid), "/T", "/F"], capture_output=True, check=False)
            else:
                browser.terminate()
            try:
                browser.wait(timeout=5)
            except subprocess.TimeoutExpired:
                browser.kill()
        if fixture:
            fixture.terminate()
            try:
                fixture.wait(timeout=5)
            except subprocess.TimeoutExpired:
                fixture.kill()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--readiness-delay", type=float, default=0.0)
    parser.add_argument("--scenario", choices=("assets", "sibling-get", "formal-completion", "response-loss", "normal-exactly-once", "cross-project-get", "mismatch", "traditional-get", "traditional-post", "cross-project-post", "sibling-post", "switch-back", "rapid-branch", "rapid-project", "history", "existing-turn"), default="assets")
    parser.add_argument("--drop-start-response", action="store_true")
    parser.add_argument("--start-delay", type=float, default=0.0)
    args = parser.parse_args()
    print(json.dumps(run(args.executable, args.readiness_delay, args.scenario, args.drop_start_response, args.start_delay), indent=2))
