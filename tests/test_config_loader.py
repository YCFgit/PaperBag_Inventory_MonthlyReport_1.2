from pathlib import Path

from src.models.schemas import AppConfig, ScopeConfig
from src.utils.config import load_app_config
from src.utils.config import load_cards
from src.utils.config import validate_loaded_app_config


def test_load_cards_merges_presets_into_card_config(tmp_path: Path) -> None:
    cards_yaml = tmp_path / "cards.yaml"
    cards_yaml.write_text(
        """
presets:
  period_month:
    request_body:
      view: GRID
    filters:
      - fieldName: 查询期间
        operator: BETWEEN
        values: ["{{report_month_start}}", "{{report_month_end}}"]
    dynamic_params:
      - name: startDate
        value: "{{report_month_start}}"

cards:
  - card_id: "demo"
    name: "示例"
    role: "demo_role"
    section: "demo_section"
    preset_refs:
      - period_month
    filters:
      - fieldName: 自定义
        operator: EQ
        values: ["x"]
""",
        encoding="utf-8",
    )

    cards = load_cards(cards_yaml)

    assert cards[0].preset_refs == ["period_month"]
    assert cards[0].request_body["view"] == "GRID"
    assert len(cards[0].filters) == 2
    assert cards[0].filters[0]["fieldName"] == "查询期间"
    assert cards[0].dynamic_params[0]["name"] == "startDate"


def test_project_cards_config_uses_ai_monthly_regional_ratio_card() -> None:
    cards_yaml = Path(__file__).resolve().parents[1] / "config" / "cards.yaml"

    cards = load_cards(cards_yaml)
    regional_inventory_card = next(card for card in cards if card.role == "regional_inventory_ratio")

    assert regional_inventory_card.card_id == "xe5da9d423db44bbe96028ad"
    assert regional_inventory_card.name == "大区库销比_不含团购_配合AI月报使用"


def test_project_cards_config_is_trimmed_to_supported_ten_cards() -> None:
    cards_yaml = Path(__file__).resolve().parents[1] / "config" / "cards.yaml"

    cards = load_cards(cards_yaml)

    assert {card.card_id for card in cards} == {
        "xe5da9d423db44bbe96028ad",
        "l6e08fdcc7fef45ccaa31d1b",
        "a597c4441b7414c93a7c502d",
        "qd0651b4b8bc944e88a6d1f0",
        "j21833508e589464c922d381",
        "l1d70dacd48c3422d9f7f67c",
        "d01d19a06c98445008a49a3f",
        "nb692ce19d26a49569de3ca8",
        "u114a0c72ae524037a53c8d1",
        "b0432cceaa1944241be3f0dc",
    }


def test_project_cards_config_marks_local_excel_only_cards() -> None:
    cards_yaml = Path(__file__).resolve().parents[1] / "config" / "cards.yaml"

    cards = load_cards(cards_yaml)
    forecast_card = next(card for card in cards if card.card_id == "u114a0c72ae524037a53c8d1")
    stocktake_difference_card = next(card for card in cards if card.card_id == "b0432cceaa1944241be3f0dc")

    assert forecast_card.enabled is False
    assert stocktake_difference_card.local_only is True


def test_project_stocktake_monthly_card_uses_ge_le_date_filters() -> None:
    cards_yaml = Path(__file__).resolve().parents[1] / "config" / "cards.yaml"

    cards = load_cards(cards_yaml)
    stocktake_monthly_card = next(card for card in cards if card.card_id == "qd0651b4b8bc944e88a6d1f0")

    assert len(stocktake_monthly_card.filters) == 2
    assert stocktake_monthly_card.filters[0]["name"] == "盘点日"
    assert stocktake_monthly_card.filters[0]["filterType"] == "GE"
    assert stocktake_monthly_card.filters[0]["filterValue"] == ["2024-03-01"]
    assert stocktake_monthly_card.filters[1]["filterType"] == "LE"
    assert stocktake_monthly_card.filters[1]["filterValue"] == ["{{report_month_end}}"]


def test_project_consumption_ratio_monthly_card_uses_grid_view() -> None:
    cards_yaml = Path(__file__).resolve().parents[1] / "config" / "cards.yaml"

    cards = load_cards(cards_yaml)
    consumption_ratio_card = next(card for card in cards if card.card_id == "j21833508e589464c922d381")

    assert consumption_ratio_card.request_body["view"] == "GRID"


def test_project_inventory_trend_card_uses_previous_month_start_filter() -> None:
    cards_yaml = Path(__file__).resolve().parents[1] / "config" / "cards.yaml"

    cards = load_cards(cards_yaml)
    inventory_trend_card = next(card for card in cards if card.card_id == "d01d19a06c98445008a49a3f")

    assert inventory_trend_card.filters[0]["filterValue"] == ["{{previous_month_start}}", "{{report_month_end}}"]


def test_project_overall_consumption_summary_card_has_no_extra_category_filter() -> None:
    cards_yaml = Path(__file__).resolve().parents[1] / "config" / "cards.yaml"

    cards = load_cards(cards_yaml)
    overall_consumption_card = next(card for card in cards if card.card_id == "l1d70dacd48c3422d9f7f67c")

    assert overall_consumption_card.filters == []


def test_load_cards_reads_local_only_flag(tmp_path: Path) -> None:
    cards_yaml = tmp_path / "cards.yaml"
    cards_yaml.write_text(
        """
cards:
  - card_id: "demo"
    name: "示例"
    role: "demo_role"
    section: "demo_section"
    local_only: true
""",
        encoding="utf-8",
    )

    cards = load_cards(cards_yaml)

    assert cards[0].local_only is True


def test_validate_loaded_app_config_reports_missing_required_runtime_values(tmp_path: Path) -> None:
    app_config = AppConfig(
        project_root=tmp_path,
        runtime_root=tmp_path,
        project_name="Test Project",
        project_slug="test_project",
        timezone="Asia/Shanghai",
        guanyuan_base_url="https://example.com",
        auth_token_path="/auth",
        data_card_path_template="/card/{card_id}",
        guanyuan_client_id="",
        guanyuan_client_secret="",
        guanyuan_user_id="",
        llm_base_url="",
        llm_api_key="",
        llm_model="",
        enable_llm=True,
        scope_config=ScopeConfig(),
    )

    errors = validate_loaded_app_config(app_config)

    assert "GUANYUAN_CLIENT_ID is required." in errors
    assert "LLM_BASE_URL is required when LLM is enabled." in errors


def test_validate_loaded_app_config_allows_llm_disabled(tmp_path: Path) -> None:
    app_config = AppConfig(
        project_root=tmp_path,
        runtime_root=tmp_path,
        project_name="Test Project",
        project_slug="test_project",
        timezone="Asia/Shanghai",
        guanyuan_base_url="https://example.com",
        auth_token_path="/auth",
        data_card_path_template="/card/{card_id}",
        guanyuan_client_id="id",
        guanyuan_client_secret="secret",
        guanyuan_user_id="user",
        enable_llm=False,
        scope_config=ScopeConfig(),
    )

    errors = validate_loaded_app_config(app_config)

    assert errors == []


def test_load_app_config_reads_project_metadata(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "app.yaml").write_text(
        """
project:
  name: "Renamed Project"
  slug: "renamed_project"
timezone: Asia/Shanghai
guanyuan:
  base_url: "https://example.com"
  auth_token_path: "/auth"
  data_card_path_template: "/card/{card_id}"
storage:
  raw_data_dir: "data/raw"
  processed_data_dir: "data/processed"
  report_dir: "data/reports"
report:
  template_path: "config/report_template.md.j2"
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("PAPER_BAG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("TZ", raising=False)

    app_config = load_app_config(tmp_path)

    assert app_config.project_name == "Renamed Project"
    assert app_config.project_slug == "renamed_project"


def test_load_app_config_derives_project_slug_from_directory_name(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "PaperBag_Inventory_MonthlyReport_1.2"
    config_dir = project_root / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "app.yaml").write_text(
        """
timezone: Asia/Shanghai
guanyuan:
  base_url: "https://example.com"
  auth_token_path: "/auth"
  data_card_path_template: "/card/{card_id}"
storage:
  raw_data_dir: "data/raw"
  processed_data_dir: "data/processed"
  report_dir: "data/reports"
report:
  template_path: "config/report_template.md.j2"
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("PAPER_BAG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("TZ", raising=False)

    app_config = load_app_config(project_root)

    assert app_config.project_name == "Paper Bag Inventory Monthly Report 1.2"
    assert app_config.project_slug == "paper_bag_inventory_monthly_report_1_2"


def test_project_app_config_defaults_to_second_day_schedule_and_conversation_file_only(monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("DINGTALK_DELIVERY_MODE", "conversation_file_only")

    app_config = load_app_config(project_root)

    assert app_config.monthly_cron == "0 9 2 * *"
    assert app_config.dingtalk_delivery_mode == "conversation_file_only"


def test_load_app_config_reads_dingtalk_enterprise_credentials(tmp_path: Path, monkeypatch) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "app.yaml").write_text(
        """
timezone: Asia/Shanghai
guanyuan:
  base_url: "https://example.com"
  auth_token_path: "/auth"
  data_card_path_template: "/card/{card_id}"
storage:
  raw_data_dir: "data/raw"
  processed_data_dir: "data/processed"
  report_dir: "data/reports"
report:
  template_path: "config/report_template.md.j2"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DINGTALK_APP_KEY", "app-key")
    monkeypatch.setenv("DINGTALK_APP_SECRET", "app-secret")
    monkeypatch.setenv("DINGTALK_AGENT_ID", "4668444612")
    monkeypatch.setenv("DINGTALK_CORP_ID", "dingcorp")
    monkeypatch.setenv("DINGTALK_OPEN_CONVERSATION_ID", "oc_test")

    app_config = load_app_config(tmp_path)

    assert app_config.dingtalk_app_key == "app-key"
    assert app_config.dingtalk_app_secret == "app-secret"
    assert app_config.dingtalk_agent_id == "4668444612"
    assert app_config.dingtalk_corp_id == "dingcorp"
    assert app_config.dingtalk_open_conversation_id == "oc_test"
