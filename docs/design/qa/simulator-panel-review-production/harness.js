(function () {
  "use strict";
  const names = [
    "ready-current", "ready-cached", "partial", "stale-mixed", "source-missing", "not-run",
    "failed", "usage-null", "warnings-multiple", "agreements-conflicts", "explicit-run-404",
  ];
  const picker = document.getElementById("fixture-picker");
  async function load(name) {
    const response = await fetch(`../../fixtures/model_persona_panel_review/${name}.json`);
    const fixture = await response.json();
    if (name === "explicit-run-404") {
      window.StoryOSSimulatorPanelReview.renderState("explicit_not_found", "指定的面板执行不存在；未回退到自动选择。 ");
      return;
    }
    window.StoryOSSimulatorPanelReview.renderReview(fixture);
  }
  function startHarness() {
    // Production initialization runs first on DOMContentLoaded and defaults
    // ordinary URLs to traditional mode. The isolated harness then restores
    // its own mount without altering the production URL contract.
    document.getElementById("simulator-panel-review")?.classList.remove("hidden");
    names.forEach((name) => { const option = document.createElement("option"); option.value = name; option.textContent = name; picker.append(option); });
    picker.addEventListener("change", () => load(picker.value));
    load(names[0]);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startHarness, { once: true });
  else startHarness();
})();
