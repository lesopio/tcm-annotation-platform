import { Navigate, useLocation } from "react-router-dom";

/** 旧路由兼容重定向：目标地址已有的参数优先，原地址的其余查询参数（bookId/pageId/assignmentId 等）原样合并。 */
export default function LegacyRedirect({ to }: { to: string }) {
  const location = useLocation();
  const [targetPath, targetQuery] = to.split("?");
  const targetParams = new URLSearchParams(targetQuery ?? "");
  for (const [key, value] of new URLSearchParams(location.search).entries()) if (!targetParams.has(key)) targetParams.append(key, value);
  const search = targetParams.toString();
  return <Navigate replace to={`${targetPath}${search ? `?${search}` : ""}`}/>;
}
