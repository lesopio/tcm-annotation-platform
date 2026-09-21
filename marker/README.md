# 标注系统子目录说明

本目录包含标注平台全部前后端代码。

## 本机启动

后端（PowerShell）：

```powershell
cd marker
.\run_backend.ps1
```

前端（PowerShell）：

```powershell
cd marker
.\run_frontend.ps1
```

默认地址：

- 前端：http://127.0.0.1:30080
- 后端：http://127.0.0.1:18765

## 默认账号

- 管理员：`admin / admin123`
- 标注员：`annotator / annotator123`
- 审核员：`reviewer / reviewer123`

> 首次启动后请立即在系统内修改默认密码。

## 当前流程

1. 管理员上传 PDF，填写任务标题和提示。
2. 管理员配置 C1-C10 实体层名称、颜色、说明。
3. 管理员按页码范围把页面分配给标注员。
4. 管理员启动识别队列（默认 `BENCAO_RECOGNIZER=mock`，预留 PaddleOCR-VL + PP-OCRv5 接口）。
5. 标注员完成版面、行/列、单字校对、实体标注并提交。
6. 审核员审核页面，可修正后通过或打回。
7. 管理员或审核员导出最终版 ZIP。

## 模型接口

当前默认 `BENCAO_RECOGNIZER=mock`，用于本机跑通流程。接入真实飞桨模型时实现 `backend/ocr_service.py` 中的 `paddle_vl_v5` 分支即可，前端和业务 API 不需要重写。
