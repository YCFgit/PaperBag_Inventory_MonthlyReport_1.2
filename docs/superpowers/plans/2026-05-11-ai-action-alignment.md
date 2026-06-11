# AI Action Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI action list map directly to earlier issue points with concise, executable actions.

**Architecture:** Keep the existing report data model and markdown tables. Strengthen the monthly report template instructions and follow-up document wording so generated actions must connect problem evidence, solution direction, concrete action, and review metric.

**Tech Stack:** Python, Jinja markdown templates, pytest.

---

### Task 1: Lock The Template Contract

**Files:**
- Modify: `tests/test_report_service.py`
- Modify: `config/report_template.md.j2`

- [ ] Add template assertions for the action-list contract: problem alignment, solution direction, no divergent suggestions, and concise executable wording.
- [ ] Run `pytest tests/test_report_service.py::test_project_report_template_uses_ai_monthly_regional_ratio_source_name -q` and confirm it fails before implementation.
- [ ] Update `config/report_template.md.j2` near section six with a short "生成要求" block.
- [ ] Re-run the same test and confirm it passes.

### Task 2: Align Follow-Up Wording

**Files:**
- Modify: `tests/test_report_service.py`
- Modify: `src/services/report_service.py`

- [ ] Add follow-up document assertions for the same issue-solution-action-review chain.
- [ ] Run the targeted follow-up test and confirm it fails before implementation.
- [ ] Update the follow-up document header/rules with concise execution requirements.
- [ ] Run targeted tests, then the full report service test file.
