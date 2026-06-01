"""
Tests that the dashboard HTML template and Python wiring are consistent.

Prevents regressions like:
- A tab button referencing a tab ID that doesn't exist in the template
- A section builder that is defined but never called
- A template placeholder that is never replaced
"""
import re
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.dashboard_server import HTML_TEMPLATE, _build_dashboard_html, _build_monitor_section


def _extract_tab_btn_ids(template: str) -> set:
    """Return the set of IDs referenced in tab button onclick=showTab('X') calls."""
    return set(re.findall(r"onclick=\"showTab\('([^']+)'\)\"", template))


def _extract_tab_content_ids(template: str) -> set:
    """Return the set of IDs from <div id="tab-X"> content divs."""
    return set(re.findall(r'id="tab-([^"]+)"', template))


def _extract_template_placeholders(template: str) -> set:
    """Return all {placeholder} names in the template."""
    return set(re.findall(r'\{(\w+_section|\w+)\}', template))


def test_all_tab_buttons_have_matching_content_div():
    """Every showTab('X') call must have a matching <div id="tab-X"> in the template."""
    btn_ids = _extract_tab_btn_ids(HTML_TEMPLATE)
    content_ids = _extract_tab_content_ids(HTML_TEMPLATE)
    missing = btn_ids - content_ids
    assert not missing, (
        f"Tab button(s) reference non-existent content divs: {missing}\n"
        f"Add <div id=\"tab-{'|'.join(missing)}\"> to HTML_TEMPLATE."
    )


def test_all_tab_content_divs_have_matching_button():
    """Every <div id="tab-X"> must have a corresponding showTab('X') button."""
    btn_ids = _extract_tab_btn_ids(HTML_TEMPLATE)
    content_ids = _extract_tab_content_ids(HTML_TEMPLATE)
    orphaned = content_ids - btn_ids
    assert not orphaned, (
        f"Tab content div(s) have no button: {orphaned}\n"
        f"Add a tab button calling showTab('{next(iter(orphaned))}') to HTML_TEMPLATE."
    )


def test_monitor_tab_present():
    """The monitor tab must exist both as a button and as a content div."""
    btn_ids = _extract_tab_btn_ids(HTML_TEMPLATE)
    content_ids = _extract_tab_content_ids(HTML_TEMPLATE)
    assert "monitor" in btn_ids, "btn-monitor tab button missing from HTML_TEMPLATE"
    assert "monitor" in content_ids, "tab-monitor content div missing from HTML_TEMPLATE"


def test_monitor_section_placeholder_in_template():
    """The {monitor_section} placeholder must appear in HTML_TEMPLATE."""
    assert "{monitor_section}" in HTML_TEMPLATE, (
        "{monitor_section} placeholder missing from HTML_TEMPLATE — "
        "_build_monitor_section() output will never be injected."
    )


def test_build_dashboard_html_replaces_monitor_section():
    """_build_dashboard_html() must not leave {monitor_section} unreplaced in output."""
    # Minimal call with empty data — just checks that the placeholder is substituted
    html = _build_dashboard_html(agents=[], backlog_items=[], open_opportunities=[],
                                 learning_data={}, trades=[], positions_status={},
                                 llm_stats={}, pnl_snapshots=[])
    assert "{monitor_section}" not in html, (
        "{monitor_section} placeholder was not replaced in the rendered HTML. "
        "Add .replace('{monitor_section}', monitor_section) to _build_dashboard_html()."
    )


def test_build_monitor_section_returns_html_string():
    """`_build_monitor_section` must return a non-empty HTML string for empty agent list."""
    html = _build_monitor_section(agents=[])
    assert isinstance(html, str) and len(html) > 0, (
        "_build_monitor_section() returned empty/non-string for empty agents list"
    )


def test_build_monitor_section_renders_issues():
    """Issues in SwarmMonitor metadata must appear in the rendered monitor section."""
    agents = [{
        "agent_name": "SwarmMonitor",
        "status": "ACTIVE",
        "last_pulse": "2026-01-01T00:00:00Z",
        "metadata": {
            "all_ok": False,
            "check_count": 5,
            "last_checked": "2026-01-01T00:00:00Z",
            "check_interval_min": 5,
            "issues": [
                {
                    "type": "AGENT_ERROR",
                    "severity": "HIGH",
                    "agent": "ProjectLead",
                    "message": "Agent crashed with RuntimeError",
                    "detected_at": "00:01:00 UTC",
                    "detail": "Traceback: RuntimeError: test error",
                }
            ],
        },
    }]
    html = _build_monitor_section(agents)
    assert "ProjectLead" in html, "Agent name not rendered in monitor section"
    assert "Agent crashed" in html, "Issue message not rendered in monitor section"
    assert "HIGH" in html, "Severity not rendered in monitor section"
