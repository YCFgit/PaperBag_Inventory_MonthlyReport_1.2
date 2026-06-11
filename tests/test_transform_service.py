from src.services.transform_service import TransformService


def test_transform_service_extracts_and_normalizes_rows() -> None:
    service = TransformService()
    normalized = service.normalize(
        [
            type(
                "RawCard",
                (),
                {
                    "card": type(
                        "Card",
                        (),
                        {"role": "demo", "card_id": "1", "name": "演示卡片", "section": "demo"},
                    )(),
                    "raw_payload": {
                        "pages": [
                            {
                                "data": {
                                    "rows": [
                                        {"库销比": "2.58", "同比": "-51%"},
                                        {"库销比": "3", "同比": "10%"},
                                    ]
                                }
                            }
                        ]
                    },
                },
            )()
        ]
    )

    assert normalized[0].rows[0]["库销比"] == 2.58
    assert normalized[0].rows[0]["同比"] == -0.51
    assert normalized[0].summary["row_count"] == 2


def test_transform_service_collects_application_errors() -> None:
    service = TransformService()
    normalized = service.normalize(
        [
            type(
                "RawCard",
                (),
                {
                    "card": type(
                        "Card",
                        (),
                        {"role": "demo", "card_id": "1", "name": "演示卡片", "section": "demo"},
                    )(),
                    "raw_payload": {
                        "pages": [
                            {"code": 500, "msg": "系统异常", "data": None},
                        ]
                    },
                },
            )()
        ]
    )

    assert normalized[0].summary["application_errors"][0]["code"] == 500
