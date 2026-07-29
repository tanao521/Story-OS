# Phase 0D5-C-RC1 — Real-Browser Evidence Closure

状态：**PARTIALLY PASSED — FIX REQUIRED**

本 RC 只验证 0D5-C，不进入 0D5-D。真实 Codex Chromium 浏览器已用于隔离 fixture；Candidate Approval、Commit、Chapter Completion 和 Provider 均未触碰。

## 当前证据

- Browser engine: Codex In-app Browser (Chromium-backed; exact version not exposed)
- Execution: background/headless browser session
- Fixture server: `http://127.0.0.1:7862/`
- Temporary root: `%TEMP%/rc2_browser_ws_pq6i5qyh` (fixture process)
- Browser process: yes
- JavaScript execution: yes
- Real DOM interaction: yes
- Real network requests: yes
- History/popstate: yes
- Console capture: yes

Verified in the real browser:

- simulator shell is visible and default scope is rendered;
- missing branch remains `BRANCH_SETUP` and does not silently select the active branch;
- Browse changes URL/view without selecting;
- Create creates an open inactive branch and keeps the active pointer unchanged;
- Select uses one explicit mutation and synchronizes URL/read model;
- Archive requires a replacement and moves the active pointer;
- Restore reopens an inactive branch without selecting it;
- Browse A/B and back/forward restore URL scope with zero observed console errors in a fresh tab;
- Traditional/static regression remains green.

## Remaining gate

The supplied fixture lacks an authoritative ready Canon/source/vector state capable of completing three durable Turn confirmations. Consequently the Turn 1 → Turn 2 → Turn 3, response-loss recovery, and full mutation-count matrix cannot be honestly marked verified. Keep 0D5-C unsealed and do not enter 0D5-D.
