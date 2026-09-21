import { CSSProperties, useEffect, useRef, useState } from "react";
import { FileQuestion, LoaderCircle, RefreshCw, ShieldAlert, WifiOff } from "lucide-react";

type AuthImageError = "auth" | "missing" | "network" | "server";
const errorMeta: Record<AuthImageError, { icon: typeof ShieldAlert; text: string }> = {
  auth: { icon: ShieldAlert, text: "登录已失效或无权查看该图片，请重新登录后再试" },
  missing: { icon: FileQuestion, text: "图片不存在或已被移除" },
  network: { icon: WifiOff, text: "网络异常，图片加载失败" },
  server: { icon: ShieldAlert, text: "服务暂时不可用，请稍后重试" },
};

export default function AuthenticatedImage({ src, token, alt = "", className, style }: { src: string; token: string; alt?: string; className?: string; style?: CSSProperties }) {
  const [objectUrl, setObjectUrl] = useState("");
  const [error, setError] = useState<AuthImageError | null>(null);
  const [attempt, setAttempt] = useState(0);
  const seq = useRef(0), urlRef = useRef("");
  useEffect(() => {
    const current = ++seq.current, controller = new AbortController();
    setError(null);
    (async () => {
      try {
        const response = await fetch(src, { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal });
        if (current !== seq.current) return;
        if (!response.ok) { setError(response.status === 401 || response.status === 403 ? "auth" : response.status === 404 ? "missing" : response.status >= 500 ? "server" : "server"); return; }
        const url = URL.createObjectURL(await response.blob());
        if (current !== seq.current) { URL.revokeObjectURL(url); return; }
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = url;
        setObjectUrl(url);
      } catch (e) {
        if (current !== seq.current || controller.signal.aborted) return;
        setError("network");
      }
    })();
    return () => { controller.abort(); if (urlRef.current) { URL.revokeObjectURL(urlRef.current); urlRef.current = ""; } setObjectUrl(""); };
  }, [src, token, attempt]);
  if (error) { const Icon = errorMeta[error].icon; return <div className={`auth-image auth-image-error${className ? ` ${className}` : ""}`} style={style} role="img" aria-label={alt}><Icon size={22} /><span>{errorMeta[error].text}</span><button className="secondary-button" onClick={() => setAttempt(attempt + 1)}><RefreshCw size={15} />重试</button></div>; }
  if (!objectUrl) return <div className={`auth-image auth-image-loading${className ? ` ${className}` : ""}`} style={style} role="img" aria-label={alt}><LoaderCircle className="spin" size={22} /><span>正在载入图片</span></div>;
  return <img src={objectUrl} alt={alt} className={className} style={style} />;
}
