import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AuthenticatedImage from "./AuthenticatedImage";

type FetchMock = ReturnType<typeof vi.fn>;

function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(res => { resolve = res; }); return { promise, resolve }; }
function okResponse(body = "png-bytes") { return { ok: true, status: 200, blob: async () => new Blob([body], { type: "image/png" }) } as unknown as Response; }
function statusResponse(status: number) { return { ok: false, status, blob: async () => new Blob() } as unknown as Response; }

describe("AuthenticatedImage", () => {
  let urlCounter = 0;
  const createObjectURL = vi.fn(() => `blob:mock-${++urlCounter}`);
  const revokeObjectURL = vi.fn();
  beforeEach(() => {
    urlCounter = 0;
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
    URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("携带 Bearer Token 请求并在成功后渲染图片", async () => {
    const fetchMock: FetchMock = vi.fn().mockResolvedValue(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthenticatedImage src="/api/book-pages/1/image" token="tok-1" alt="古籍页面" />);
    await waitFor(() => expect(screen.getByRole("img")).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledWith("/api/book-pages/1/image", expect.objectContaining({ headers: { Authorization: "Bearer tok-1" } }));
    expect(screen.getByRole("img").getAttribute("src")).toBe("blob:mock-1");
  });

  it("403 时提示登录失效或无权限并提供重试", async () => {
    const fetchMock: FetchMock = vi.fn().mockResolvedValue(statusResponse(403));
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthenticatedImage src="/img" token="tok" alt="x" />);
    await waitFor(() => expect(screen.getByText(/登录已失效或无权查看/)).toBeTruthy());
    expect(screen.getByRole("button", { name: /重试/ })).toBeTruthy();
  });

  it("404 时提示图片不存在", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(statusResponse(404)));
    render(<AuthenticatedImage src="/img" token="tok" alt="x" />);
    await waitFor(() => expect(screen.getByText(/图片不存在或已被移除/)).toBeTruthy());
  });

  it("网络失败时提示网络异常，点击重试后重新请求并成功", async () => {
    const fetchMock: FetchMock = vi.fn().mockRejectedValueOnce(new TypeError("fetch failed")).mockResolvedValueOnce(okResponse());
    vi.stubGlobal("fetch", fetchMock);
    render(<AuthenticatedImage src="/img" token="tok" alt="x" />);
    await waitFor(() => expect(screen.getByText(/网络异常/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /重试/ }));
    await waitFor(() => expect(screen.getByRole("img")).toBeTruthy());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("快速切换时慢的旧请求不得覆盖新图片，其对象 URL 被释放", async () => {
    const slow = deferred<Response>();
    const fetchMock: FetchMock = vi.fn().mockImplementationOnce(() => slow.promise).mockImplementationOnce(async () => okResponse("page-2"));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<AuthenticatedImage src="/page/1/image" token="tok" alt="x" />);
    view.rerender(<AuthenticatedImage src="/page/2/image" token="tok" alt="x" />);
    await waitFor(() => expect(screen.getByRole("img").getAttribute("src")).toBe("blob:mock-1"));
    slow.resolve(okResponse("page-1"));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("img").getAttribute("src")).toBe("blob:mock-1");
  });

  it("卸载时中止请求并释放对象 URL", async () => {
    const slow = deferred<Response>();
    const fetchMock: FetchMock = vi.fn().mockImplementation(() => slow.promise);
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<AuthenticatedImage src="/page/1/image" token="tok" alt="x" />);
    await waitFor(() => expect(screen.getByText(/正在载入图片/)).toBeTruthy());
    const signal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    slow.resolve(okResponse());
    await waitFor(() => expect(screen.getByRole("img")).toBeTruthy());
    view.unmount();
    expect(signal.aborted).toBe(true);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-1");
  });
});
