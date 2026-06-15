from __future__ import annotations

from pathlib import Path

from src.main import _extract_executive_summary, _extract_report_title, _load_existing_report, _resolve_existing_report_path


def test_resolve_existing_report_path_skips_followup_files(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports" / "2026-05"
    report_dir.mkdir(parents=True)
    (report_dir / "demo_issue_followup_2026-05_aaaa.md").write_text("# followup\n", encoding="utf-8")
    report_path = report_dir / "demo_2026-05_bbbb.md"
    report_path.write_text("# 正式月报\n摘要\n", encoding="utf-8")

    resolved = _resolve_existing_report_path(tmp_path / "reports", "2026-05", None)

    assert resolved == report_path


def test_resolve_existing_report_path_prefers_fixed_monthly_report_name(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports" / "2026-05"
    report_dir.mkdir(parents=True)
    legacy_path = report_dir / "demo_2026-05_bbbb.md"
    legacy_path.write_text("# 旧报告\n", encoding="utf-8")
    preferred_path = report_dir / "202605-月度纸袋分析报告.md"
    preferred_path.write_text("# 固定报告\n", encoding="utf-8")

    resolved = _resolve_existing_report_path(tmp_path / "reports", "2026-05", None)

    assert resolved == preferred_path


def test_load_existing_report_reads_title_and_summary(tmp_path: Path) -> None:
    report_path = tmp_path / "demo.md"
    report_path.write_text("# 2026年5月纸袋月报\n\n这是摘要。\n\n正文。\n", encoding="utf-8")

    report = _load_existing_report(report_path, "2026-05")

    assert report.title == "2026年5月纸袋月报"
    assert report.executive_summary == "这是摘要。"
    assert report.output_path == report_path


def test_extract_report_title_and_summary_fall_back_when_markdown_is_sparse() -> None:
    markdown = "\n\n# \n\n"

    assert _extract_report_title(markdown, "2026-05") == "202605-月度纸袋分析报告"
    assert _extract_executive_summary(markdown) == "本月报告已生成。"
