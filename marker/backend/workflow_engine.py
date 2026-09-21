from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


NODE_TYPES: dict[str, dict[str, Any]] = {
    "start": {"label": "开始", "role": "system", "category": "控制", "color": "#475569"},
    "ocr": {"label": "OCR 预标注", "role": "admin", "category": "自动处理", "color": "#a16207"},
    "region": {"label": "区域标注", "role": "annotator", "category": "人工标注", "color": "#9a3412", "required": True},
    "region_review": {"label": "区域审核", "role": "reviewer", "category": "质量审核", "color": "#7c3aed"},
    "layout": {"label": "版面与层累", "role": "annotator", "category": "人工标注", "color": "#0369a1", "required": True},
    "layout_review": {"label": "版面审核", "role": "reviewer", "category": "质量审核", "color": "#6d28d9"},
    "character": {"label": "单字校对", "role": "annotator", "category": "人工标注", "color": "#047857", "required": True},
    "character_review": {"label": "单字审核", "role": "reviewer", "category": "质量审核", "color": "#5b21b6"},
    "text_normalize": {"label": "文本整理", "role": "annotator", "category": "语义标注", "color": "#0f766e"},
    "entity": {"label": "实体标注", "role": "annotator", "category": "语义标注", "color": "#0369a1"},
    "relation": {"label": "关系标注", "role": "annotator", "category": "语义标注", "color": "#4338ca"},
    "medical_case": {"label": "医案标注", "role": "annotator", "category": "语义标注", "color": "#7c3aed"},
    "double_compare": {"label": "双标比较", "role": "reviewer", "category": "质量审核", "color": "#a16207"},
    "expert_adjudication": {"label": "专家裁决", "role": "expert", "category": "质量审核", "color": "#9a3412"},
    "graph_publish": {"label": "图谱发布", "role": "data_engineer", "category": "知识图谱", "color": "#047857"},
    "final_review": {"label": "终审", "role": "reviewer", "category": "质量审核", "color": "#4338ca"},
    "export": {"label": "数据导出", "role": "admin", "category": "自动处理", "color": "#0f766e"},
    "end": {"label": "结束", "role": "system", "category": "控制", "color": "#334155"},
}


def default_graph() -> dict[str, list[dict[str, Any]]]:
    sequence = ["start", "ocr", "region", "region_review", "layout", "layout_review", "character", "character_review", "text_normalize", "entity", "relation", "medical_case", "double_compare", "expert_adjudication", "final_review", "graph_publish", "export", "end"]
    nodes = []
    for index, node_type in enumerate(sequence):
        spec = NODE_TYPES[node_type]
        nodes.append({
            "id": node_type,
            "type": node_type,
            "label": spec["label"],
            "role": spec["role"],
            "position": {"x": 80 + (index % 4) * 230, "y": 80 + (index // 4) * 170},
            "params": {"completion_rate": 100, "allow_return": "review" in node_type},
        })
    return {"nodes": nodes, "edges": [{"source": sequence[i], "target": sequence[i + 1]} for i in range(len(sequence) - 1)]}


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    edges = graph.get("edges") if isinstance(graph, dict) else None
    errors: list[str] = []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return {"ok": False, "errors": ["工作流必须包含 nodes 和 edges 数组"], "order": []}
    ids = [str(node.get("id", "")).strip() for node in nodes if isinstance(node, dict)]
    if len(ids) != len(nodes) or any(not item for item in ids):
        errors.append("每个节点必须有非空且稳定的 id")
    if len(set(ids)) != len(ids):
        errors.append("节点 id 不能重复")
    node_by_id = {str(node.get("id")): node for node in nodes if isinstance(node, dict) and node.get("id")}
    type_counts: dict[str, int] = defaultdict(int)
    for node_id, node in node_by_id.items():
        node_type = str(node.get("type", ""))
        type_counts[node_type] += 1
        if node_type not in NODE_TYPES:
            errors.append(f"节点 {node_id} 使用了未知类型 {node_type}")
        expected_role = NODE_TYPES.get(node_type, {}).get("role")
        if expected_role and node.get("role", expected_role) not in (expected_role, "admin"):
            errors.append(f"节点 {node_id} 的执行角色不合法")
    for required in ("start", "region", "layout", "character", "end"):
        if type_counts[required] != 1:
            errors.append(f"{NODE_TYPES[required]['label']}节点必须且只能存在一个")

    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("连线格式无效")
            continue
        source, target = str(edge.get("source", "")), str(edge.get("target", ""))
        if source not in node_by_id or target not in node_by_id:
            errors.append(f"连线 {source} → {target} 引用了不存在的节点")
            continue
        if source == target:
            errors.append(f"节点 {source} 不能连接自身")
            continue
        outgoing[source].add(target)
        incoming[target].add(source)

    queue = deque(sorted(node_id for node_id in node_by_id if not incoming[node_id]))
    order: list[str] = []
    indegree = {node_id: len(incoming[node_id]) for node_id in node_by_id}
    while queue:
        node_id = queue.popleft()
        order.append(node_id)
        for target in sorted(outgoing[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(order) != len(node_by_id):
        errors.append("工作流存在循环")

    start_ids = [node_id for node_id, node in node_by_id.items() if node.get("type") == "start"]
    end_ids = [node_id for node_id, node in node_by_id.items() if node.get("type") == "end"]
    if start_ids and incoming[start_ids[0]]:
        errors.append("开始节点不能有前置节点")
    if end_ids and outgoing[end_ids[0]]:
        errors.append("结束节点不能有后继节点")

    def reachable(source: str, target: str) -> bool:
        seen, pending = set(), [source]
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            pending.extend(outgoing[current] - seen)
        return False

    if start_ids and end_ids:
        start_id, end_id = start_ids[0], end_ids[0]
        for node_id in node_by_id:
            if not reachable(start_id, node_id) or not reachable(node_id, end_id):
                errors.append(f"节点 {node_id} 不在开始到结束的有效路径上")
    unique_type = {str(node.get("type")): node_id for node_id, node in node_by_id.items() if type_counts[str(node.get("type"))] == 1}
    if all(key in unique_type for key in ("region", "layout", "character")):
        if not reachable(unique_type["region"], unique_type["layout"]):
            errors.append("版面与层累必须位于区域标注之后")
        if not reachable(unique_type["layout"], unique_type["character"]):
            errors.append("单字校对必须位于版面与层累之后")
    for node_id, node in node_by_id.items():
        node_type = node.get("type")
        if node_type == "ocr" and "region" in unique_type and not reachable(node_id, unique_type["region"]):
            errors.append("OCR 预标注只能位于区域标注之前")
        if node_type == "export" and "character" in unique_type and not reachable(unique_type["character"], node_id):
            errors.append("数据导出必须位于单字校对之后")
    return {"ok": not errors, "errors": list(dict.fromkeys(errors)), "order": order}
