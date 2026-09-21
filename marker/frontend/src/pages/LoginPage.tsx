import { FormEvent, useState } from "react";
import { BookOpen, KeyRound, LogIn, UserRound } from "lucide-react";

export default function LoginPage({ onLogin }: { onLogin: (username: string, password: string) => Promise<void> }) {
  const [loading,setLoading]=useState(false), [error,setError]=useState("");
  async function submit(event:FormEvent<HTMLFormElement>){event.preventDefault();const form=new FormData(event.currentTarget);setLoading(true);setError("");try{await onLogin(String(form.get("username")),String(form.get("password")));}catch(err){setError(err instanceof Error?err.message:String(err));}finally{setLoading(false);}}
  return <main className="login-page"><div className="login-orb login-orb-a"/><div className="login-orb login-orb-b"/><form className="login-panel" onSubmit={submit}>
    <div className="login-emblem"><BookOpen size={31}/></div><h1>古籍多用户数据标注平台</h1><p>区域标注 · 版面与层累 · 单字校对</p>
    <label className="input-with-icon"><UserRound size={18}/><input name="username" autoComplete="username" placeholder="账号" required/></label>
    <label className="input-with-icon"><KeyRound size={18}/><input name="password" type="password" autoComplete="current-password" placeholder="密码" required/></label>
    <button className="primary-button login-button" disabled={loading}><LogIn size={18}/>{loading?"正在登录":"登 录"}</button>
    {error&&<div className="alert error">{error}</div>}<small className="login-footnote">本地部署 · 数据留存在当前工作站</small>
  </form></main>;
}
