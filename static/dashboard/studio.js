(function () {
    var bootstrapEl = document.getElementById("studio-bootstrap");
    var diagnosticsEl = document.getElementById("studio-diagnostics");
    var targetsEl = document.getElementById("studio-targets");
    if (!bootstrapEl || !diagnosticsEl || !targetsEl) {
        return;
    }

    function escapeHtml(value) {
        return String(value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function renderCapabilityList(capabilities, className) {
        if (!Array.isArray(capabilities) || capabilities.length === 0) {
            return "";
        }

        return '<div class="' + className + '">' + capabilities.map(function (capability) {
            return '<span class="studio-chip">' + escapeHtml(capability.replace(/_/g, " ")) + "</span>";
        }).join("") + "</div>";
    }

    function renderTarget(target) {
        var capabilities = Array.isArray(target.capabilities) ? target.capabilities : [];
        var partialCapabilities = Array.isArray(target.partial_capabilities) ? target.partial_capabilities : [];
        var stateLabel = partialCapabilities.length > 0 ? "Partial support" : "Ready";

        return [
            '<article class="studio-target-card" data-kind="' + escapeHtml(target.kind || "unknown") + '">',
            '  <div class="studio-target-card__header">',
            '    <strong>' + escapeHtml(target.label || target.id || "Unnamed target") + '</strong>',
            '    <span class="studio-chip">' + escapeHtml(stateLabel) + '</span>',
            "  </div>",
            target.description ? '  <p class="studio-copy">' + escapeHtml(target.description) + '</p>' : "",
            renderCapabilityList(capabilities, "studio-target-card__capabilities"),
            partialCapabilities.length > 0 ? '  <p class="studio-copy">Partial: ' + escapeHtml(partialCapabilities.join(", ").replace(/_/g, " ")) + '</p>' : "",
            "</article>",
        ].join("");
    }

    var payload = {};
    try {
        payload = JSON.parse(bootstrapEl.textContent || "{}");
    } catch (error) {
        diagnosticsEl.textContent = "Failed to parse Studio bootstrap payload.";
        diagnosticsEl.dataset.state = "error";
        return;
    }

    var targets = Array.isArray(payload.targets)
        ? payload.targets
        : Array.isArray(payload.entries)
            ? payload.entries
            : [];
    diagnosticsEl.dataset.state = targets.length > 0 ? "ready" : "empty";
    if (targets.length > 0) {
        targetsEl.innerHTML = targets.map(renderTarget).join("");
        var partialCount = targets.filter(function (target) {
            return Array.isArray(target.partial_capabilities) && target.partial_capabilities.length > 0;
        }).length;
        diagnosticsEl.textContent = partialCount > 0
            ? partialCount + " Studio targets have partial capability support."
            : "Studio bootstrap payload loaded.";
    } else {
        targetsEl.textContent = targetsEl.dataset.emptyMessage || "No Studio targets available.";
    }

    if (!targets.length && !diagnosticsEl.textContent.trim()) {
        diagnosticsEl.textContent = diagnosticsEl.dataset.emptyMessage || "No diagnostics yet.";
    }
})();
