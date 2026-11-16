"""Platform-level suggestion rules."""

from __future__ import annotations

from wattman.suggest.rules import Suggestion, Window, register


@register("pcie_aspm_performance")
def pcie_aspm_performance(window: Window) -> list[Suggestion]:
    settings = window.settings()
    policy = settings.get("pcie.aspm.policy")
    if policy is None:
        return []
    # The active option appears in [brackets], e.g. "default performance [powersave] powersupersave"
    if "[powersave" in policy or "[powersupersave" in policy:
        return []
    if "[performance]" in policy or "[default]" in policy:
        return [Suggestion(
            rule="pcie_aspm_performance",
            severity="info",
            message=(
                f"PCIe ASPM policy is `{policy}`. Switching to `powersave` typically saves "
                "1–3 W on idle systems with NVMe/discrete GPU. Set via "
                "`echo powersave | sudo tee /sys/module/pcie_aspm/parameters/policy`."
            ),
            evidence={"current_policy": policy},
        )]
    return []


@register("ab_validated")
def ab_validated(window: Window) -> list[Suggestion]:
    """Promote A/B results into a confirmed-saving message. ab.process_pending
    runs first (see suggest.rules.evaluate_and_persist)."""
    rows = window.conn.execute(
        "SELECT sc.knob, sc.old_value, sc.new_value, ab.delta_watts, ab.n_before, ab.n_after, sc.ts "
        "FROM setting_change sc JOIN ab_result ab ON sc.id = ab.setting_change_id "
        "WHERE ab.computed_at >= ? "
        "ORDER BY sc.ts DESC LIMIT 5",
        (window.now_ts - 86400,),
    ).fetchall()
    out: list[Suggestion] = []
    for knob, old, new, delta, n_b, n_a, _ts in rows:
        if min(n_b, n_a) < 60:
            continue
        if abs(delta) < 2.0:
            continue
        direction = "saved" if delta < 0 else "added"
        out.append(Suggestion(
            rule="ab_validated",
            severity="info",
            message=(
                f"Changing `{knob}` from `{old}` to `{new}` {direction} "
                f"{abs(delta):.1f} W on average ({n_b}/{n_a} samples)."
            ),
            evidence={"knob": knob, "old": old, "new": new, "delta_w": delta,
                      "n_before": n_b, "n_after": n_a},
        ))
    return out
