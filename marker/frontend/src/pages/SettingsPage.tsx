import { FormEvent, useEffect, useState } from "react";
import { AlignJustify, Bot, CheckCircle2, Eye, EyeOff, Feather, FlaskConical, KeyRound, Moon, Rows3, Save, Server, Sparkles, Sun } from "lucide-react";
import { api, OcrSettings, OcrTestResult, PlatformSettings, SemanticSettings } from "../api";
import { DisplaySettings, loadDisplaySettings, saveDisplaySettings } from "../displaySettings";

export default function SettingsPage({token}:{token:string}){
  const [settings,setSettings]=useState<OcrSettings|null>(null);
  const [accessToken,setAccessToken]=useState("");
  const [baseUrl,setBaseUrl]=useState("");
  const [model,setModel]=useState("PaddleOCR-VL-1.6");
  const [showToken,setShowToken]=useState(false);
  const [saving,setSaving]=useState(false);
  const [testing,setTesting]=useState(false);
  const [testResult,setTestResult]=useState<OcrTestResult|null>(null);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [display,setDisplay]=useState<DisplaySettings>(loadDisplaySettings);
  const [semantic,setSemantic]=useState<SemanticSettings|null>(null),[semanticKey,setSemanticKey]=useState(""),[semanticUrl,setSemanticUrl]=useState(""),[semanticModel,setSemanticModel]=useState(""),[semanticTimeout,setSemanticTimeout]=useState(120),[semanticTesting,setSemanticTesting]=useState(false),[semanticMessage,setSemanticMessage]=useState("");
  const [platform,setPlatform]=useState<PlatformSettings|null>(null),[modeSaving,setModeSaving]=useState(false);

  useEffect(()=>{api.ocrSettings(token).then(result=>{setSettings(result);setBaseUrl(result.base_url);setModel(result.model);}).catch(e=>setError(e.message));},[token]);
  useEffect(()=>{api.semanticSettings(token).then(result=>{setSemantic(result);setSemanticUrl(result.base_url);setSemanticModel(result.model);setSemanticTimeout(result.timeout_seconds);}).catch(e=>setError(e.message));},[token]);
  useEffect(()=>{api.platformSettings(token).then(setPlatform).catch(()=>setPlatform(null));},[token]);

  async function toggleTestMode(enabled:boolean){
    if(modeSaving)return;setModeSaving(true);setMessage("");setError("");
    try{const result=await api.savePlatformSettings(token,{test_mode:enabled,test_env_ready:platform?.test_env_ready??false});setPlatform(result);setMessage(enabled?"测试模式已开启：OCR 与语义模型将使用 .env 中的真实测试凭据调用。":"已切换回正式配置：使用下方保存的模型密钥调用。");}
    catch(e){setError(e instanceof Error?e.message:"保存失败");}
    finally{setModeSaving(false);}
  }

  async function submit(event:FormEvent){
    event.preventDefault();setSaving(true);setMessage("");setError("");
    try{
      const result=await api.saveOcrSettings(token,{access_token:accessToken.trim()||undefined,base_url:baseUrl.trim(),model:model.trim()});
      setSettings(result);setAccessToken("");setMessage("OCR 配置已保存，新的识别任务将立即使用此配置。");
    }catch(e){setError(e instanceof Error?e.message:"保存失败");}
    finally{setSaving(false);}
  }

  async function testModel(){
    setTesting(true);setTestResult(null);setMessage("");setError("");
    try{setTestResult(await api.testOcrSettings(token,{access_token:accessToken.trim()||undefined,base_url:baseUrl.trim(),model:model.trim()}));}
    catch(e){setError(e instanceof Error?e.message:"模型测试失败");}
    finally{setTesting(false);}
  }

  function updateDisplay(patch:Partial<DisplaySettings>){const next={...display,...patch};setDisplay(next);saveDisplaySettings(next);}

  async function saveSemantic(event:FormEvent){event.preventDefault();setSaving(true);setError("");try{const result=await api.saveSemanticSettings(token,{api_key:semanticKey.trim()||undefined,base_url:semanticUrl.trim(),model:semanticModel.trim(),timeout_seconds:semanticTimeout});setSemantic(result);setSemanticKey("");setSemanticMessage("语义模型配置已保存。");}catch(e){setError(e instanceof Error?e.message:"保存失败");}finally{setSaving(false);}}
  async function testSemantic(){setSemanticTesting(true);setError("");setSemanticMessage("");try{const result=await api.testSemanticSettings(token,{api_key:semanticKey.trim()||undefined,base_url:semanticUrl.trim(),model:semanticModel.trim(),timeout_seconds:semanticTimeout});setSemanticMessage(`连接正常：${result.model} · ${result.elapsed_ms} ms · ${result.message}`);}catch(e){setError(e instanceof Error?e.message:"测试失败");}finally{setSemanticTesting(false);}}

  return <div className="page-stack settings-page">
    <div className="page-toolbar"><div><span className="eyebrow">SYSTEM SETTINGS</span><h1>系统设置</h1><p>配置云端 OCR 服务。密钥只提交给本机后端，并以加密形式保存。</p></div></div>
    {error&&<div className="alert error">{error}</div>}{message&&<div className="alert settings-success"><CheckCircle2 size={17}/><span>{message}</span></div>}
    <section className="content-card settings-card">
      <div className="card-heading"><div><span className="eyebrow">TEST MODE</span><h2>全站测试模式</h2></div><span className={platform?.test_mode?"config-state configured":"config-state"}><FlaskConical size={16}/>{platform?.test_mode?"已开启":"已关闭"}</span></div>
      <div className="display-setting-group"><div><strong>测试模型开关</strong><small>开启后，OCR 与语义模型改用根目录 .env 中的两套真实测试凭据调用（飞桨 + 通义）；关闭后使用下方正式配置。当前 .env 测试凭据：{platform?.test_env_ready?"已就绪":"未配置或缺失"}。</small></div><div className="display-options"><button className={!platform?.test_mode?"active":""} disabled={modeSaving} onClick={()=>toggleTestMode(false)}><Server size={18}/><span>正式配置</span></button><button className={platform?.test_mode?"active":""} disabled={modeSaving} onClick={()=>toggleTestMode(true)}><FlaskConical size={18}/><span>测试凭据</span></button></div></div>
    </section>
    <section className="content-card settings-card">
      <div className="card-heading"><div><span className="eyebrow">OCR PROVIDER</span><h2>PaddleOCR 云端模型</h2></div><span className={settings?.configured?"config-state configured":"config-state"}><KeyRound size={16}/>{settings?.configured?`已配置 ${settings.token_hint}`:"尚未配置密钥"}</span></div>
      <form className="settings-form" onSubmit={submit}>
        <label><span><KeyRound size={16}/>访问密钥</span><div className="secret-input"><input type={showToken?"text":"password"} value={accessToken} onChange={e=>setAccessToken(e.target.value)} autoComplete="new-password" placeholder={settings?.configured?"留空则保留现有密钥":"请输入 PaddleOCR Access Token"}/><button type="button" className="icon-button" onClick={()=>setShowToken(value=>!value)} aria-label={showToken?"隐藏密钥":"显示密钥"}>{showToken?<EyeOff size={18}/>:<Eye size={18}/>}</button></div><small>保存后不会再次显示完整密钥。</small></label>
        <label><span><Server size={16}/>Job URL</span><input type="url" value={baseUrl} onChange={e=>setBaseUrl(e.target.value)} placeholder="https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"/><small>PaddleOCR 异步任务接口；本地图片会以 multipart/form-data 方式提交。</small></label>
        <label><span><Bot size={16}/>模型名称</span><input value={model} onChange={e=>setModel(e.target.value)} required maxLength={120}/><small>当前项目的响应解析适配 PaddleOCR-VL 系列。</small></label>
        <p className="model-test-note">测试会生成并上传一张不含书籍内容的示例图片，并消耗一次 PaddleOCR API 任务额度。</p>
        {testResult&&<div className="model-test-result"><CheckCircle2 size={19}/><div><strong>模型连接正常</strong><span>{testResult.model} · {testResult.elapsed_ms} ms · {testResult.region_count} 个区域 · {testResult.line_count} 行文本</span>{testResult.warnings.length>0&&<small>{testResult.warnings.join("；")}</small>}</div></div>}
        <div className="settings-actions"><button type="button" className="secondary-button" onClick={testModel} disabled={testing||saving||!model.trim()||(!accessToken.trim()&&!settings?.configured)}><FlaskConical size={17}/>{testing?"正在测试":"测试模型"}</button><button className="primary-button" disabled={saving||testing||!model.trim()}><Save size={17}/>{saving?"正在保存":"保存 OCR 配置"}</button></div>
      </form>
    </section>
    <section className="content-card settings-card">
      <div className="card-heading"><div><span className="eyebrow">SEMANTIC MODEL</span><h2>语义预标注模型</h2></div><span className={semantic?.configured?"config-state configured":"config-state"}><Bot size={16}/>{semantic?.configured?`已配置 ${semantic.key_hint}`:"尚未配置"}</span></div>
      <form className="settings-form" onSubmit={saveSemantic}><label><span><KeyRound size={16}/>API Key</span><input type="password" value={semanticKey} onChange={e=>setSemanticKey(e.target.value)} placeholder={semantic?.configured?"留空则保留现有密钥":"输入兼容接口密钥"}/></label><label><span><Server size={16}/>Base URL</span><input type="url" value={semanticUrl} onChange={e=>setSemanticUrl(e.target.value)} placeholder="https://example.com/v1"/><small>兼容 OpenAI Chat Completions；可直接填写完整 /chat/completions 地址。</small></label><label><span><Bot size={16}/>模型名称</span><input value={semanticModel} onChange={e=>setSemanticModel(e.target.value)} placeholder="模型部署名称"/></label><label><span><FlaskConical size={16}/>超时时间（秒）</span><input type="number" min={10} max={600} value={semanticTimeout} onChange={e=>setSemanticTimeout(Number(e.target.value))}/></label>{semanticMessage&&<div className="model-test-result"><CheckCircle2 size={19}/><div><strong>{semanticMessage}</strong></div></div>}<div className="settings-actions"><button type="button" className="secondary-button" onClick={testSemantic} disabled={semanticTesting||(!semanticKey&&!(semantic?.configured))||!semanticUrl||!semanticModel}><FlaskConical size={17}/>{semanticTesting?"正在测试":"测试语义模型"}</button><button className="primary-button" disabled={saving||!semanticUrl||!semanticModel}><Save size={17}/>保存语义配置</button></div></form>
    </section>
    <section className="content-card settings-card display-settings-card">
      <div className="card-heading"><div><span className="eyebrow">APPEARANCE</span><h2>界面主题与显示</h2></div><Feather size={21}/></div>
      <div className="display-setting-group"><div><strong>界面主题</strong><small>更改工作台的背景与表面配色。</small></div><div className="display-options three"><button className={display.theme==="paper"?"active":""} onClick={()=>updateDisplay({theme:"paper"})}><Feather size={18}/><span>宣纸</span></button><button className={display.theme==="light"?"active":""} onClick={()=>updateDisplay({theme:"light"})}><Sun size={18}/><span>明亮</span></button><button className={display.theme==="dark"?"active":""} onClick={()=>updateDisplay({theme:"dark"})}><Moon size={18}/><span>深色</span></button></div></div>
      <div className="display-setting-group"><div><strong>信息密度</strong><small>控制页面间距、卡片留白和表格行高。</small></div><div className="display-options"><button className={display.density==="comfortable"?"active":""} onClick={()=>updateDisplay({density:"comfortable"})}><Rows3 size={18}/><span>舒适</span></button><button className={display.density==="compact"?"active":""} onClick={()=>updateDisplay({density:"compact"})}><AlignJustify size={18}/><span>紧凑</span></button></div></div>
      <div className="display-setting-group"><div><strong>界面动效</strong><small>减少动效适合长时间标注或低性能设备。</small></div><div className="display-options"><button className={display.motion==="standard"?"active":""} onClick={()=>updateDisplay({motion:"standard"})}><Sparkles size={18}/><span>标准</span></button><button className={display.motion==="reduced"?"active":""} onClick={()=>updateDisplay({motion:"reduced"})}><Feather size={18}/><span>减少</span></button></div></div>
    </section>
  </div>;
}
