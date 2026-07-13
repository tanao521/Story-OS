(() => {
  let logs = [];
  const escape = (value) => window.escapeHtml ? window.escapeHtml(value) : String(value);
  const previousLog = window.logMessage;
  window.logMessage = (message, type = "info") => {
    logs.push({ message, type });
    logs = logs.slice(-300);
    previousLog?.(message, type);
    if (type === "error") {
      const target = document.getElementById("error-center-list");
      if (target) target.innerHTML = "<article class=\"error-entry\"><strong>运行错误</strong><p>检查步骤、文件和服务后重试。</p><code>" + escape(message) + "</code></article>";
    }
  };
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-clear-logs]")) document.getElementById("log-output").innerHTML = "";
    if (event.target.closest("[data-copy-logs]")) navigator.clipboard?.writeText(logs.map((item) => item.message).join("\n"));
    if (event.target.closest("[data-clear-errors]")) document.getElementById("error-center-list").textContent = "暂无前端运行错误。";
  });
})();
