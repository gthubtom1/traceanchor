# Changelog

## 0.1.1 — HTTP budget precision correction

Use the high-resolution performance counter for HTTP elapsed-time charging. The original strictly-positive charging assertion is retained and strengthened with real loopback I/O under an explicitly frozen coarse monotonic clock. Two post-release CI runs exposed this issue after the first successful qualification. No frozen scope, budgets or acceptance conditions were weakened. The 0.1.0 tag and artifacts remain immutable.

## 0.1.0 — first finite-capability release

Independent stdlib-only core, SQLite ownership, full source snapshots, explicit task modes and observation gaps, bounded Windows Job execution, host-driven finite reconstruction, five separate comparisons, current-verdict invalidation, linked development subtasks, three-tier storage governance, CLI/MCP and project-local host configuration.

This is not a claim of general desktop/APK/browser automation or superiority over the research sources. See support and qualification records for actual platform and host validation. Release is gated on the frozen acceptance contract and public audit.
