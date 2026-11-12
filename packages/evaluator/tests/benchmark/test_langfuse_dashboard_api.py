"""Dashboard API 边界契约；无网络，无凭据。"""

from types import SimpleNamespace

import pytest


def page_response(page, ids, total=101):
    return SimpleNamespace(
        data=[SimpleNamespace(id=str(i), name=f"widget-{i}") for i in ids],
        meta=SimpleNamespace(
            page=page, limit=100, total_items=total, total_pages=(total + 99) // 100
        ),
    )


def test_lists_all_pages_without_losing_existing_widgets():
    from eval_framework.benchmark.langfuse_dashboard_api import DashboardAPI

    calls = []

    def listing(*, page, **kwargs):
        calls.append(page)
        return page_response(page, range(100) if page == 1 else [100])

    api = DashboardAPI(
        SimpleNamespace(
            unstable=SimpleNamespace(dashboard_widgets=SimpleNamespace(list=listing))
        )
    )
    assert api.list_widgets()[-1].id == "100"
    assert calls == [1, 2]


@pytest.mark.parametrize(
    "broken", ["missing_meta", "wrong_page", "duplicate", "missing_item", "error"]
)
def test_bad_or_incomplete_listing_is_never_success(broken):
    from eval_framework.benchmark.langfuse_dashboard_api import DashboardAPI

    def listing(*, page, **kwargs):
        if page == 1:
            return page_response(page, range(100))
        if broken == "error":
            raise RuntimeError("offline service error")
        if broken == "missing_meta":
            return SimpleNamespace(data=[])
        if broken == "wrong_page":
            return page_response(1, [100])
        return page_response(page, [0] if broken == "duplicate" else [])

    api = DashboardAPI(
        SimpleNamespace(
            unstable=SimpleNamespace(dashboards=SimpleNamespace(list=listing))
        )
    )
    with pytest.raises((ValueError, RuntimeError)):
        api.list_dashboards()


def test_definition_rejects_incompatible_schema():
    from eval_framework.benchmark.langfuse_dashboard_api import DashboardAPI

    with pytest.raises(ValueError):
        DashboardAPI.definition({"widgets": [{"type": "widget", "widget_id": "a"}]})
