"""六步连续标注的工作流步骤校验。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from marker.backend.main import WorkflowSaveIn
from marker.backend.workflow_engine import NODE_TYPES, default_graph


def test_current_step_accepts_six_steps():
    payload = WorkflowSaveIn(expected_version=1, current_step=6)
    assert payload.current_step == 6


def test_current_step_rejects_out_of_range():
    with pytest.raises(ValidationError):
        WorkflowSaveIn(expected_version=1, current_step=0)
    with pytest.raises(ValidationError):
        WorkflowSaveIn(expected_version=1, current_step=7)


def test_semantic_node_types_exist_for_continuous_flow():
    for node_type in ("region", "layout", "character", "text_normalize", "entity", "relation", "medical_case"):
        assert node_type in NODE_TYPES
    graph = default_graph()
    types = [node["type"] for node in graph["nodes"]]
    for node_type in ("region", "layout", "character", "text_normalize", "entity", "relation", "medical_case"):
        assert node_type in types
