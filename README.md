# TCM Annotation Platform · 古籍数据标注平台

面向中医古籍（本草文献）数字化的多用户标注系统。覆盖 **图像预处理 → OCR 预标注 → 版面/层累结构标注 → 单字校对 → 语义标注 → 质量审核 → 知识图谱构建** 的完整流程，支持管理员 / 标注员 / 审核员三角色协作。

> 本仓库只包含系统代码，**不包含任何古籍影像、标注数据、数据库文件或密钥**。书籍 PDF、页面图片、OCR 结果和标注记录均由系统在本地运行时生成和存储。

## 功能特性

### 页面标注（Schema v2）

- **书籍管理**：上传 PDF、自动渲染页面、页面预处理（二值化/去噪等）。
- **OCR 预标注**：预留 PaddleOCR-VL-1.6 与 PP-OCRv5 云端接口，管理员手动发起批次、逐页预览确认后才导入初标；未配置 Token 时可全程人工标注。
- **三阶段标注**：区域标注 → 版面与层累结构 → 单字校对；自动保存带版本号，防止旧数据覆盖新数据。
- **自定义实体层**：C1–C10 实体层名称、颜色、说明全部可配置。
- **可视化工作流**：受约束 DAG 编辑器，强制保留区域、版面/层累、单字三个核心节点，可插入 OCR、阶段审核、终审、导出节点；模板发布后形成不可变版本。
- **导出**：v2 JSON、版面 COCO、字符 COCO、兼容 `final.json` 与自定义字形 ZIP。

### 语义标注与知识图谱（Schema v3）

- **文本单元**：维护卷、章、条文、医案、医论文本单元。
- **语义预标注**：OpenAI Chat Completions 兼容接口（自填 Base URL / API Key / 模型名），未配置时人工标注不受影响。
- **标注规范中心**：版本、状态、适用范围与正反例管理。
- **质量中心**：双人盲标、F1 / Kappa 指标、不可覆盖的专家裁决。
- **知识图谱**：从已审核数据构建图谱、查询传承关系，导出 JSON / CSV / GraphML。
- **研究辅助**：基于已审核语料的证据型问答、医案检索与疾病研究。
- **CJK 支持**：Unicode/Unihan 索引批量导入、书内自定义字。

## 技术栈

| 端 | 技术 |
| --- | --- |
| 后端 | Python · FastAPI · SQLAlchemy · SQLite |
| 前端 | React · TypeScript · Vite |
| 外部模型 | PaddleOCR-VL（可选）· 任意 OpenAI 兼容语义模型（可选） |

## 快速开始

### 1. 环境变量

```powershell
copy .env.example .env
```

按需填写：`BENCAO_SECRET_KEY`（务必修改）、可选的 `PADDLEOCR_ACCESS_TOKEN` 等。`.env` 永远不要提交。

### 2. 启动后端

```powershell
pip install -r marker/backend/requirements.txt
python -m uvicorn marker.backend.main:app --host 127.0.0.1 --port 18765
```

或使用脚本（PowerShell）：

```powershell
cd marker
.\run_backend.ps1
```

### 3. 启动前端

```powershell
cd marker/frontend
npm install
npm run dev
```

默认地址：前端 http://127.0.0.1:30080 ，后端 http://127.0.0.1:18765 。

### 4. 登录

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | `admin` | `admin123` |
| 标注员 | `annotator` | `annotator123` |
| 审核员 | `reviewer` | `reviewer123` |

> 默认账号仅用于首次体验，请登录后立即修改。

### 5. 运行测试

```powershell
python -m pytest marker/tests
```

## 目录结构

```
.
├── .env.example              # 环境变量模板
├── ANNOTATION_PLATFORM_V2.md # 平台设计与工作流说明
└── marker/
    ├── backend/              # FastAPI 后端（认证、书籍、工作流、OCR、语义、导出）
    ├── frontend/             # React + Vite 前端
    ├── schemas/              # 导出 JSON Schema（annotation v2 / v3）
    ├── scripts/              # Unihan 导入、验收示例种子脚本
    ├── tests/                # 后端测试
    └── data/                 # 仅含版面行位置模板（运行时自动创建其余数据目录）
```

运行时生成的数据（SQLite 数据库、页面图片、OCR 原始结果、加密密钥、导出包）均落在 `marker/data/` 下，已由 `.gitignore` 排除。

## 数据与安全

- OCR / 语义模型的访问令牌在数据库中使用 Fernet 加密存储，密钥文件位于本地数据目录，不进入仓库。
- 全站测试模式可在系统设置中切换，凭据从 `.env` 读取（参见 `.env.example` 中 `BENCAO_TEST_*` 说明）。
- 本项目默认面向本机（localhost）部署；如需对外暴露，请先修改 `BENCAO_SECRET_KEY`、`BENCAO_CORS_ORIGINS` 与默认账号密码。

## License

暂未附带开源许可证（All rights reserved）。如需引用或二次开发，请先联系仓库所有者。
