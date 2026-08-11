from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "apps" / "dashboard"


def test_dashboard_exposes_filter_tab_replay_and_live_region_state() -> None:
    markup = (DASHBOARD / "index.html").read_text(encoding="utf-8")

    assert markup.count('class="filter-button') == 3
    assert markup.count('aria-pressed="false"') >= 3
    assert 'aria-controls="overview-view"' in markup
    assert 'aria-controls="replay-view"' in markup
    assert 'id="replay-tab"' in markup and 'tabindex="-1"' in markup
    assert 'aria-label="任务摘要" aria-live="polite" aria-atomic="true"' in markup
    assert 'id="attention-banner" class="attention-banner" role="status"' in markup
    assert 'id="replay-play" class="play-button" type="button" aria-pressed="false"' in markup
    assert 'id="replay-position" aria-live="polite"' in markup


def test_dashboard_script_keeps_keyboard_and_dynamic_state_in_sync() -> None:
    script = (DASHBOARD / "app.js").read_text(encoding="utf-8")

    for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"):
        assert key in script
    assert 'tab.setAttribute("aria-selected", String(selected))' in script
    assert "tab.tabIndex = selected ? 0 : -1" in script
    assert 'item.setAttribute("aria-pressed", String(selected))' in script
    assert "replayRange.setAttribute" in script
    assert '"aria-valuetext"' in script
    assert 'scrollIntoView({ block: "nearest", inline: "nearest" })' in script


def test_dashboard_supports_reduced_motion_and_forced_colors() -> None:
    styles = (DASHBOARD / "styles.css").read_text(encoding="utf-8")

    assert "@media (prefers-reduced-motion: reduce)" in styles
    assert "animation-duration: 0.01ms !important" in styles
    assert "animation-iteration-count: 1 !important" in styles
    assert "@media (forced-colors: active)" in styles
