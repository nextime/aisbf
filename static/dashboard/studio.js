(function () {
    var bootstrapEl = document.getElementById("studio-bootstrap");
    var diagnosticsEl = document.getElementById("studio-diagnostics");
    if (!bootstrapEl || !diagnosticsEl) {
        return;
    }

    var payload = {};
    try {
        payload = JSON.parse(bootstrapEl.textContent || "{}");
    } catch (error) {
        diagnosticsEl.textContent = "Failed to parse Studio bootstrap payload.";
        diagnosticsEl.dataset.state = "error";
        return;
    }

    var targets = Array.isArray(payload.targets) ? payload.targets.length : 0;
    diagnosticsEl.dataset.state = targets > 0 ? "ready" : "empty";
    if (targets > 0) {
        diagnosticsEl.textContent = "Studio bootstrap payload loaded.";
    }
})();
