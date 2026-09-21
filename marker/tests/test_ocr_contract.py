import json

from marker.backend import ocr_service
from marker.backend.ocr_service import call_paddleocr_vl_api, normalize_paddleocr_vl_response


def test_pruned_result_contract_preserves_regions_and_defers_character_boxes():
    raw = {
        "jobId": "contract-example",
        "pages": [{
            "prunedResult": {
                "parsingResList": [
                    {"label": "text", "bbox": [10, 20, 110, 420], "content": "本草"},
                    {"label": "seal", "bbox": [120, 300, 200, 380], "content": ""},
                ]
            }
        }],
    }
    result = normalize_paddleocr_vl_response(raw)
    assert [item["region_type"] for item in result["regions"]] == ["text", "seal"]
    assert result["lines"][0]["ocr_text"] == "本草"
    assert result["lines"][0]["needs_char_split"] is True
    assert result["chars"] == []


def test_unknown_contract_never_fabricates_boxes():
    result = normalize_paddleocr_vl_response({"unexpected": True})
    assert result["regions"] == []
    assert result["chars"] == []
    assert result["warnings"]


def test_async_job_api_uploads_file_and_polls_result(tmp_path, monkeypatch):
    image_path = tmp_path / "test.png"
    image_path.write_bytes(b"fake-image")
    calls: list[tuple[str, str]] = []

    class Response:
        def __init__(self, payload=None, text="", status_code=200):
            self._payload = payload
            self.text = text
            self.status_code = status_code

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def fake_post(url, *, headers, data, files, timeout):
        calls.append(("POST", url))
        assert headers["Authorization"] == "bearer test-token"
        assert data["model"] == "PaddleOCR-VL-1.6"
        assert "file" in files
        return Response({"code": 0, "msg": "Success", "data": {"jobId": "job-1"}})

    def fake_get(url, *, timeout, headers=None):
        calls.append(("GET", url))
        if url.endswith("/job-1"):
            return Response({"code": 0, "data": {"state": "done", "resultUrl": {"jsonUrl": "https://result.test/data.jsonl"}}})
        payload = {"result": {"layoutParsingResults": [{"prunedResult": {"parsingResList": []}}]}}
        return Response(text=json.dumps(payload))

    monkeypatch.setattr(ocr_service.requests, "post", fake_post)
    monkeypatch.setattr(ocr_service.requests, "get", fake_get)
    result = call_paddleocr_vl_api(image_path, config={"access_token": "test-token", "base_url": "https://jobs.test/api/v2/ocr/jobs", "model": "PaddleOCR-VL-1.6", "provider": "paddleocr"})

    assert result["jobId"] == "job-1"
    assert len(result["layoutParsingResults"]) == 1
    assert calls == [("POST", "https://jobs.test/api/v2/ocr/jobs"), ("GET", "https://jobs.test/api/v2/ocr/jobs/job-1"), ("GET", "https://result.test/data.jsonl")]
