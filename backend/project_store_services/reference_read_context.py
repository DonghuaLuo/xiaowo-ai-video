"""Lazy, operation-local inputs shared by a batch of canvas reference views."""

from contextlib import ExitStack
from typing import Any


class ReferenceReadContext:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self._card_results: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._stack: ExitStack | None = None
        self._active = False
        self._connection = None
        self._episodes: dict[str, bool] = {}
        self._assets = None
        self._asset_index = None
        self._model_selection = None

    def __enter__(self):
        if self._stack is not None:
            raise RuntimeError("ReferenceReadContext is limited to one read operation")
        self._stack = ExitStack()
        self._active = True
        return self

    def __exit__(self, *exc):
        self._active = False
        try:
            return self._stack.__exit__(*exc)
        finally:
            self._connection = None

    def card_results(self, episode_id: str, node_id: str) -> list[dict[str, Any]]:
        from .canvas_store_database import _canvas_document_row, _canvas_snapshot_connection
        from .canvas_store_queries import _read_card_results_in_conn

        if not self._active:
            raise RuntimeError("Card results require an active ReferenceReadContext")
        key = (episode_id, node_id)
        if key not in self._card_results:
            if self._connection is None:
                self._connection = self._stack.enter_context(_canvas_snapshot_connection(self.project_id))
            if episode_id not in self._episodes:
                self._episodes[episode_id] = _canvas_document_row(self._connection, episode_id) is not None
            self._card_results[key] = (
                _read_card_results_in_conn(self._connection, episode_id, node_id)
                if self._episodes[episode_id] else []
            )
        # Consumers select/copy records; this batch-owned snapshot is never written back.
        return self._card_results[key]

    @property
    def assets(self) -> dict[str, Any]:
        from .assets import list_assets
        # The context belongs to one operation. Python 3.10 cached_property has
        # a descriptor-wide lock: concurrent operations can invert its order
        # with the JSON write lock held by an asset/association mutation.
        if self._assets is None:
            self._assets = list_assets(
                "project", self.project_id, hydrate=False, lifecycle_status="active",
                persist_normalization=False,
            )
        return self._assets

    @property
    def asset_index(self) -> dict[tuple[str, str], dict[str, Any]]:
        if self._asset_index is None:
            self._asset_index = {
                (kind, str(asset["id"])): asset
                for kind, rows in self.assets.items() if isinstance(rows, list)
                for asset in rows if isinstance(asset, dict) and asset.get("id")
            }
        return self._asset_index

    @property
    def model_selection(self) -> tuple[dict[str, Any], dict[str, Any]]:
        from .model_provider_config import _project_model_selection
        if self._model_selection is None:
            self._model_selection = _project_model_selection(self.project_id)
        return self._model_selection
