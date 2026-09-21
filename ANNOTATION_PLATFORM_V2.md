# 多用户古籍数据标注平台 v2

> 语义标注与知识图谱能力已升级到导出 Schema v3；原有页面标注 v2 接口和导出继续保留。

## 本地配置

1. 复制 `.env.example` 为 `.env`。
2. 修改 `BENCAO_SECRET_KEY`。
3. 如需云端预标注，填写 `PADDLEOCR_ACCESS_TOKEN`。未配置 Token 时，手工标注不受影响。

后端：

```powershell
python -m uvicorn marker.backend.main:app --host 127.0.0.1 --port 18765
```

前端：

```powershell
Set-Location marker/frontend
npm run dev
```

## 工作流

- 管理员：上传 PDF、维护区域/版面/层累标签、创建用户、按页分配、发起 PaddleOCR-VL-1.6 批次、导出审核通过数据。
- 标注员：区域标注 → 版面与层累 → 单字校对；自动保存使用版本号防止旧数据覆盖。
- 审核员：复核三阶段内容，可修改、通过或填写意见打回。

管理员可在“可视化工作流”中维护受约束 DAG。系统强制保留区域、版面/层累、单字三个核心节点及其数据依赖，同时允许插入 OCR、阶段审核、终审和导出节点。模板发布后形成不可变版本；书籍需要由管理员逐书检查并升级。

流程按整书推进：每个节点内部生成页级任务，全部页面完成后开放后继节点。OCR 节点不会自动调用云端服务，仍需管理员明确填写页码范围并启动。

新版前端路由：

- `/dashboard`：角色总览。
- `/books`、`/workflows`、`/labels`、`/assignments`、`/users`：管理员工作区。
- `/tasks`、`/reviews`、`/archive`：标注与审核任务。
- `/work/{assignmentId}`：沉浸式标注工作台。

主导出为 v2 JSON，Schema 位于 `marker/schemas/annotation-v2.schema.json`；压缩包同时包含版面 COCO、可选字符 COCO、兼容 `final.json` 和自定义字形文件。

## 语义标注与知识图谱 v3

- `/semantic`：维护卷、章、条文、医案和医论文本单元；同时标注实体、关系和结构化医案。
- `/task-center`：统一查看批量 OCR、OCR 预览、语义预标注、图谱构建和导出任务。
- `/ocr-preview`：管理员手动识别单页，检查版面框与文本，确认后才导入初标。
- `/guidelines`：维护标注规范的版本、状态、适用范围和正反例。
- `/quality`：建立双人盲标、查看 F1/Kappa 指标并形成不可覆盖的专家裁决。
- `/knowledge-graph`：从已审核数据构建图谱，查询传承关系并导出 JSON、CSV 或 GraphML。
- `/research`：使用已审核语料进行证据型问答、医案检索和疾病研究辅助。

系统设置中的“语义预标注模型”采用 OpenAI Chat Completions 兼容接口，配置 Base URL、API Key、模型名和超时即可。未配置模型时，人工标注、质量审核、图谱和研究应用仍可使用。

语义导出接口为 `GET /api/books/{book_id}/semantic-export`，Schema 位于 `marker/schemas/annotation-v3.schema.json`。导出包含本体、层级文本、实体、关系、医案、裁决、规范和知识图谱，并保留来源证据。

可使用以下命令创建一套明确标记为“非真实史料”的验收示例：

```powershell
python -m marker.scripts.seed_semantic_acceptance_sample
```

## CJK 字库

系统可直接新增书内自定义字。批量建立 Unicode/Unihan 索引时，先从 Unicode 官方站点手工取得固定版本 `Unihan.zip`，再执行：

```powershell
python marker/scripts/import_unihan.py C:/path/to/Unihan.zip
```

脚本不会联网下载数据。系统字体只作为显示回退，不会复制进仓库。
