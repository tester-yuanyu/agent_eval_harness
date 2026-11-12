"""Langfuse 5.x unstable Dashboard 边界；模板与指标语义由调用方负责。

仅包装传入 client，保留节流/重试策略；SDK 类型在实际调用时加载。
分页失败、重复或变化中的集合直接报错，交付流程可恢复后再验证。
"""

from __future__ import annotations


class DashboardAPI:
    def __init__(self, client):
        self.client = client

    @staticmethod
    def definition(value):
        from langfuse.api.unstable.dashboards.types.dashboard_definition import (
            DashboardDefinition,
        )

        return DashboardDefinition.model_validate(value)

    @staticmethod
    def _list(endpoint):
        rows, seen = [], set()
        page, total = 1, None
        while True:
            response = endpoint.list(
                page=page, limit=100, request_options={"max_retries": 0}
            )
            meta = getattr(response, "meta", None)
            data = getattr(response, "data", None)
            if meta is None or not isinstance(data, list):
                raise ValueError("incompatible dashboard list response")
            count, pages = (
                getattr(meta, "total_items", None),
                getattr(meta, "total_pages", None),
            )
            if (
                type(count) is not int
                or count < 0
                or type(pages) is not int
                or pages != (count + 99) // 100
                or meta.page != page
                or meta.limit != 100
            ):
                raise ValueError("incompatible dashboard pagination")
            if total is not None and count != total:
                raise ValueError("dashboard collection changed during pagination")
            total = count
            for row in data:
                identifier = getattr(row, "id", None)
                if (
                    not isinstance(identifier, str)
                    or not identifier
                    or identifier in seen
                ):
                    raise ValueError("missing or duplicate dashboard item")
                seen.add(identifier)
                rows.append(row)
            expected = min(100, max(0, total - (page - 1) * 100))
            if len(data) != expected:
                raise ValueError("incomplete dashboard page")
            if page >= pages:
                return rows
            page += 1

    def list_dashboards(self):
        return self._list(self.client.unstable.dashboards)

    def list_widgets(self):
        return self._list(self.client.unstable.dashboard_widgets)

    def get_dashboard(self, identifier):
        return self.client.unstable.dashboards.get(identifier)

    def create_dashboard(self, **kwargs):
        return self.client.unstable.dashboards.create(**kwargs)

    def update_dashboard(self, identifier, **kwargs):
        return self.client.unstable.dashboards.update(identifier, **kwargs)

    def get_widget(self, identifier):
        return self.client.unstable.dashboard_widgets.get(identifier)

    def create_widget(self, **kwargs):
        return self.client.unstable.dashboard_widgets.create(**kwargs)

    def update_widget(self, identifier, **kwargs):
        return self.client.unstable.dashboard_widgets.update(identifier, **kwargs)
