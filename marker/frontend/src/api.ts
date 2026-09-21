export type Role = "admin" | "annotator" | "reviewer" | "expert" | "data_engineer";

export type User = {
  id: number;
  username: string;
  role: Role;
  display_name: string;
  is_active: boolean;
  is_ai_expert?: boolean;
};

export type Book = {
  id: number;
  title: string;
  task_prompt: string;
  status: string;
  page_count: number;
  created_by: number;
  created_at: string;
  updated_at: string;
};

export type BookPage = {
  id: number;
  book_id: number;
  page_no: number;
  page_id: string;
  width: number;
  height: number;
  dpi: number;
  recognition_status: string;
  image_url: string;
};

export type BookEntity = {
  id: number;
  book_id: number;
  code: string;
  name: string;
  color: string;
  description: string;
  is_active: boolean;
};

export type Assignment = {
  id: number;
  book_id: number;
  page_id: number;
  page_no: number;
  user_id: number;
  username: string;
  status: string;
  current_step: number;
  version: number;
  review_comment: string;
  submitted_at: string | null;
  reviewed_at: string | null;
};

export type Region = {
  id?: number;
  assignment_id?: number;
  region_type: string;
  label_id?: number | null;
  order_no: number;
  bbox: [number, number, number, number];
  confirmed: boolean;
};

export type TextLine = {
  id?: number;
  assignment_id?: number;
  region_id?: number | null;
  layout_label_id?: number | null;
  stratum_label_id?: number | null;
  order_no: number;
  bbox: [number, number, number, number];
  char_size: number;
  confirmed: boolean;
  needs_char_split: boolean;
  ocr_text: string;
};

export type TextChar = {
  id?: number;
  assignment_id?: number;
  line_id?: number | null;
  custom_char_id?: number | null;
  order_no: number;
  bbox: [number, number, number, number];
  raw_text: string;
  corrected_text: string;
  candidates: string[];
  confidence: number;
  status: "unchecked" | "confirmed" | "unclear" | "missing";
};

export type EntityAnnotation = {
  id?: number;
  assignment_id?: number;
  entity_id: number;
  entity_code?: string;
  entity_name?: string;
  color?: string;
  bbox: [number, number, number, number];
  note: string;
};

export type Workflow = {
  book: Book;
  page: BookPage;
  assignment: Assignment;
  entities: BookEntity[];
  labels: LabelDefinition[];
  regions: Region[];
  lines: TextLine[];
  chars: TextChar[];
  entity_annotations: EntityAnnotation[];
};

export type RecognitionLatest = {
  job: { id: number; batch_id: number; page_id: number; model: string; status: string; attempts: number; error: string; created_at: string; updated_at: string };
  result: {
    regions: { region_type: string; order_no: number; bbox: [number, number, number, number] }[];
    lines: { order_no: number; region_order_no: number; bbox: [number, number, number, number]; ocr_text: string; needs_char_split: boolean }[];
    chars: { order_no: number; line_order_no: number; bbox: [number, number, number, number]; raw_text: string }[];
    warnings: string[];
  };
};

export type LabelDefinition = {
  id: number; book_id: number; group: "region" | "layout" | "stratum";
  code: string; name: string; color: string; description: string;
  sort_order: number; is_active: boolean;
};

export type CharacterEntry = {
  id: number | null; book_id: number | null; unicode_codepoint: string; character: string;
  ids: string; radical: string; strokes: number | null; readings: string; aliases: string;
  glyph_url: string; source_page_id: number | null; status: string;
};

export type OcrPageJobInfo = { id: number; batch_id: number; page_id: number; page_no?: number | null; image_sha256: string; model: string; status: string; provider_job_id: string | null; error: string; attempts: number; created_at: string; updated_at: string };
export type RecognitionBatch = {
  id?: number;
  book_id?: number;
  status: string;
  current_page: number;
  total_pages: number;
  error: string;
  created_at?: string;
  updated_at?: string;
  pages?: OcrPageJobInfo[];
  platform_job_id?: number;
};

export type WorkflowGraphNode = { id: string; type: string; label: string; role: Role | "system"; position: { x: number; y: number }; params: Record<string, unknown> };
export type WorkflowGraph = { nodes: WorkflowGraphNode[]; edges: { source: string; target: string }[] };
export type WorkflowVersion = { id: number; template_id: number; version: number; status: "draft" | "published"; graph: WorkflowGraph; published_at: string | null };
export type WorkflowTemplate = { id: number; name: string; description: string; is_builtin: boolean; draft: WorkflowVersion | null; published: WorkflowVersion | null; versions: { id: number; version: number; status: string; published_at: string | null }[] };
export type WorkflowPageTask = { id: number; page_id: number; page_no: number; assignee_id: number | null; status: string; comment: string; version: number };
export type WorkflowNodeRun = { id: number; node_key: string; node_type: string; label: string; role: string; status: string; completed_pages: number; total_pages: number; tasks: WorkflowPageTask[] };
export type BookWorkflowRun = { id: number; book_id: number; workflow_version_id: number; pending_version_id: number | null; status: string; graph: WorkflowGraph; nodes: WorkflowNodeRun[] };
export type DashboardData = { role: Role; stats: Record<string, number>; recent: Assignment[] };
export type OcrSettings = { provider: "paddleocr"; configured: boolean; token_hint: string; base_url: string; model: string };
export type OcrTestResult = { ok: boolean; model: string; elapsed_ms: number; region_count: number; line_count: number; warnings: string[] };
export type SemanticSettings = { configured: boolean; key_hint: string; base_url: string; model: string; timeout_seconds: number };
export type OntologyType = { id: number; book_id: number | null; kind: "entity" | "relation"; code: string; name: string; color: string; description: string; source_types: string[]; target_types: string[]; version: number; is_active: boolean };
export type TextUnit = { id: number; book_id: number; page_id: number | null; parent_id: number | null; stable_id: string; unit_type: string; title: string; order_no: number; source_page: string; original_text: string; normalized_text: string; text_type: string; version: number; status: string; updated_at?: string };
export type SemanticEntity = { id: number; text_unit_id: number; assignment_id: number | null; type_id: number; type_code: string; type_name: string; color: string; canonical_name: string; surface_text: string; start_offset: number; end_offset: number; bbox: number[]; aliases: string[]; attributes: Record<string,unknown>; source: string; confidence: number; uncertain: boolean; status: string; created_by: number };
export type SemanticRelation = { id: number; text_unit_id: number; assignment_id: number | null; type_id: number; type_code: string; type_name: string; source_entity_id: number; target_entity_id: number; evidence_text: string; source: string; confidence: number; uncertain: boolean; status: string; created_by: number };
export type MedicalCase = { id: number; text_unit_id: number; assignment_id: number | null; source: string; doctor: string; disease: string; symptoms: string; diagnosis: string; syndrome: string; treatment: string; formula: string; medicines: string; outcome: string; note: string; status: string; created_by: number };
export type SemanticWorkspace = { unit: TextUnit; ontology: OntologyType[]; entities: SemanticEntity[]; relations: SemanticRelation[]; cases: MedicalCase[] };
export type PlatformJob = { id: number; job_type: string; book_id: number | null; book_title: string; page_id: number | null; created_by: number; creator: string; status: "queued"|"running"|"succeeded"|"failed"|"cancelled"; progress: number; model: string; payload: Record<string,unknown>; result: Record<string,unknown>; error: string; attempts: number; created_at: string; started_at: string|null; completed_at: string|null };
export type Adjudication = { id: number; book_id: number; page_id: number; assignment_a_id: number; assignment_b_id: number; status: string; metrics: Record<string,number>; decision: Record<string,unknown>; comment: string; expert_id: number|null };
export type QualityReport = { entities: number; relations: number; cases: number; uncertain: number; approved: number; duplicate_entities: number; adjudications: number; gold_records: number };
export type KnowledgeGraph = { nodes: {id:number;type:string;name:string;aliases:string[];evidence_count:number}[]; edges: {id:number;type:string;source:number;target:number;evidence:{text_unit_id:number;text:string;relation_id:number}[];evidence_count:number}[] };
export type Guideline = {id:number;title:string;content:string;sort_order:number;is_active:boolean;version:number;status:"draft"|"published"|"retired";scope:string;examples:{kind:string;text:string}[];published_at:string|null;updated_at:string};
export type PlatformSettings = { test_mode: boolean; test_env_ready: boolean };

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:18765";

async function request<T>(path: string, token: string | null, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const data = await response.json();
      message = typeof data.detail === "string" ? data.detail : [data.detail?.message, ...(data.detail?.errors ?? [])].filter(Boolean).join("；") || message;
    } catch {
      // keep status text
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  base: API_BASE,
  login: (username: string, password: string) =>
    request<{ access_token: string; user: User }>("/api/auth/login", null, {
      method: "POST",
      body: JSON.stringify({ username, password })
    }),
  me: (token: string) => request<User>("/api/me", token),
  dashboard: (token: string) => request<DashboardData>("/api/dashboard", token),
  ocrSettings: (token: string) => request<OcrSettings>("/api/settings/ocr", token),
  saveOcrSettings: (token: string, settings: { access_token?: string; base_url: string; model: string }) =>
    request<OcrSettings>("/api/settings/ocr", token, { method: "PUT", body: JSON.stringify(settings) }),
  testOcrSettings: (token: string, settings: { access_token?: string; base_url: string; model: string }) =>
    request<OcrTestResult>("/api/settings/ocr/test", token, { method: "POST", body: JSON.stringify(settings) }),
  platformSettings: (token: string) => request<PlatformSettings>("/api/settings/platform", token),
  savePlatformSettings: (token: string, settings: PlatformSettings) =>
    request<PlatformSettings>("/api/settings/platform", token, { method: "PUT", body: JSON.stringify(settings) }),
  semanticSettings: (token: string) => request<SemanticSettings>("/api/settings/semantic", token),
  saveSemanticSettings: (token: string, settings: {api_key?:string;clear_api_key?:boolean;base_url:string;model:string;timeout_seconds:number}) => request<SemanticSettings>("/api/settings/semantic", token, {method:"PUT",body:JSON.stringify(settings)}),
  testSemanticSettings: (token: string, settings: {api_key?:string;base_url:string;model:string;timeout_seconds:number}) => request<{ok:boolean;model:string;message:string;elapsed_ms:number}>("/api/settings/semantic/test", token, {method:"POST",body:JSON.stringify(settings)}),
  users: (token: string) => request<User[]>("/api/users", token),
  saveUser: (token: string, user: Partial<User> & { password?: string; username: string }) =>
    user.id
      ? request<User>(`/api/users/${user.id}`, token, { method: "PUT", body: JSON.stringify(user) })
      : request<User>("/api/users", token, { method: "POST", body: JSON.stringify(user) }),
  books: (token: string) => request<Book[]>("/api/books", token),
  createBook: (token: string, file: File, title: string, taskPrompt: string) => {
    const body = new FormData();
    body.set("file", file);
    body.set("title", title);
    body.set("task_prompt", taskPrompt);
    return request<Book>("/api/books", token, { method: "POST", body });
  },
  updateBook: (token: string, book: Pick<Book, "id" | "title" | "task_prompt" | "status">) =>
    request<Book>(`/api/books/${book.id}`, token, { method: "PUT", body: JSON.stringify(book) }),
  deleteBook: (token: string, bookId: number) => request<{ ok: boolean; deleted: number }>(`/api/books/${bookId}`, token, { method: "DELETE" }),
  bookPages: (token: string, bookId: number) => request<BookPage[]>(`/api/books/${bookId}/pages`, token),
  ontology: (token:string,bookId:number|null=null)=>request<OntologyType[]>(`/api/ontology${bookId===null?"":`?book_id=${bookId}`}`,token),
  saveOntology: (token:string,items:Partial<OntologyType>[])=>request<OntologyType[]>("/api/ontology",token,{method:"PUT",body:JSON.stringify(items)}),
  textUnits: (token:string,bookId:number,pageId?:number)=>request<TextUnit[]>(`/api/text-units?book_id=${bookId}${pageId?`&page_id=${pageId}`:""}`,token),
  saveTextUnit: (token:string,item:Partial<TextUnit>&{book_id:number;stable_id:string})=>request<TextUnit>("/api/text-units",token,{method:"POST",body:JSON.stringify({...item,expected_version:item.id?item.version:undefined})}),
  semanticWorkspace:(token:string,unitId:number,assignmentId?:number)=>request<SemanticWorkspace>(`/api/semantic/workspace/${unitId}${assignmentId?`?assignment_id=${assignmentId}`:""}`,token),
  saveSemanticEntity:(token:string,item:Partial<SemanticEntity>&{text_unit_id:number;type_id:number;canonical_name:string;start_offset:number;end_offset:number})=>request<SemanticEntity>("/api/semantic/entities",token,{method:"POST",body:JSON.stringify(item)}),
  deleteSemanticEntity:(token:string,id:number)=>request<{ok:boolean}>(`/api/semantic/entities/${id}`,token,{method:"DELETE"}),
  saveSemanticRelation:(token:string,item:Partial<SemanticRelation>&{text_unit_id:number;type_id:number;source_entity_id:number;target_entity_id:number})=>request<SemanticRelation>("/api/semantic/relations",token,{method:"POST",body:JSON.stringify(item)}),
  deleteSemanticRelation:(token:string,id:number)=>request<{ok:boolean}>(`/api/semantic/relations/${id}`,token,{method:"DELETE"}),
  saveMedicalCase:(token:string,item:Partial<MedicalCase>&{text_unit_id:number})=>request<MedicalCase>("/api/semantic/cases",token,{method:"POST",body:JSON.stringify(item)}),
  preannotate:(token:string,unitId:number)=>request<PlatformJob>(`/api/semantic/preannotate/${unitId}`,token,{method:"POST"}),
  applyPreannotation:(token:string,jobId:number)=>request<{ok:boolean;entities:number}>(`/api/semantic/preannotation/${jobId}/apply`,token,{method:"POST"}),
  semanticFeedback:(token:string,data:{entity_id?:number;relation_id?:number;action:"accept"|"reject"|"uncertain"})=>request<{ok:boolean;status:string;uncertain:boolean}>("/api/semantic/feedback",token,{method:"POST",body:JSON.stringify(data)}),
  platformJobs:(token:string)=>request<PlatformJob[]>("/api/platform-jobs",token),
  cancelPlatformJob:(token:string,id:number)=>request<PlatformJob>(`/api/platform-jobs/${id}/cancel`,token,{method:"POST"}),
  retryPlatformJob:(token:string,id:number)=>request<PlatformJob>(`/api/platform-jobs/${id}/retry`,token,{method:"POST"}),
  ocrPreview:(token:string,pageId:number)=>request<PlatformJob>("/api/ocr-preview",token,{method:"POST",body:JSON.stringify({page_id:pageId})}),
  confirmOcrPreview:(token:string,jobId:number,assignmentId:number,mode:"merge"|"version")=>request<{ok:boolean;assignment_id:number}>("/api/ocr-preview/confirm",token,{method:"POST",body:JSON.stringify({job_id:jobId,assignment_id:assignmentId,mode})}),
  doubleAssign:(token:string,data:{page_id:number;annotator_a_id:number;annotator_b_id:number})=>request<{id:number;assignment_a_id:number;assignment_b_id:number;status:string}>("/api/quality/double-assign",token,{method:"POST",body:JSON.stringify(data)}),
  adjudications:(token:string)=>request<Adjudication[]>("/api/quality/adjudications",token),
  adjudicate:(token:string,id:number,decision:Record<string,unknown>,comment:string)=>request<{ok:boolean;status:string}>(`/api/quality/adjudications/${id}`,token,{method:"POST",body:JSON.stringify({decision,comment})}),
  qualityReport:(token:string,bookId?:number)=>request<QualityReport>(`/api/quality/report${bookId?`?book_id=${bookId}`:""}`,token),
  buildGraph:(token:string,bookId:number)=>request<PlatformJob>(`/api/graph/build/${bookId}`,token,{method:"POST"}),
  graph:(token:string,bookId:number,q="")=>request<KnowledgeGraph>(`/api/graph/${bookId}?q=${encodeURIComponent(q)}`,token),
  graphExportUrl:(bookId:number,format:"json"|"csv"|"graphml")=>`${API_BASE}/api/graph/${bookId}/export?format=${format}`,
  researchCases:(token:string,params:Record<string,string|number>)=>request<MedicalCase[]>(`/api/research/cases?${new URLSearchParams(Object.entries(params).map(([k,v])=>[k,String(v)])).toString()}`,token),
  researchAnswer:(token:string,bookId:number,q:string)=>request<{answer:string;evidence:{text_unit_id:number;title:string;source_page:string;text:string}[];disclaimer:string}>(`/api/research/answer?book_id=${bookId}&q=${encodeURIComponent(q)}`,token),
  researchRecommend:(token:string,disease:string)=>request<{query:string;cases:MedicalCase[];summary:string;disclaimer:string}>(`/api/research/recommend?disease=${encodeURIComponent(disease)}`,token),
  reviewSemantic:(token:string,data:{entity_ids?:number[];relation_ids?:number[];case_ids?:number[];text_unit_ids?:number[];action:"approve"|"reject"})=>request<{ok:boolean;status:string;counts:Record<string,number>}>("/api/semantic/review",token,{method:"POST",body:JSON.stringify(data)}),
  guidelines:(token:string)=>request<Guideline[]>("/api/admin/guidelines",token),
  saveGuideline:(token:string,item:Partial<Guideline>&{title:string;content:string})=>item.id?request<Guideline>(`/api/guidelines/${item.id}`,token,{method:"PUT",body:JSON.stringify(item)}):request<Guideline>("/api/guidelines",token,{method:"POST",body:JSON.stringify(item)}),
  semanticExportUrl:(bookId:number)=>`${API_BASE}/api/books/${bookId}/semantic-export`,
  exportSemantic:async(token:string,bookId:number)=>{const response=await fetch(`${API_BASE}/api/books/${bookId}/semantic-export`,{headers:{Authorization:`Bearer ${token}`}});if(!response.ok)throw new Error("语义数据导出失败");const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download=`book_${bookId}_semantic_v3.json`;link.click();URL.revokeObjectURL(url);},
  bookEntities: (token: string, bookId: number) => request<BookEntity[]>(`/api/books/${bookId}/entities`, token),
  bookLabels: (token: string, bookId: number) => request<LabelDefinition[]>(`/api/books/${bookId}/labels`, token),
  saveBookLabels: (token: string, bookId: number, labels: Partial<LabelDefinition>[]) =>
    request<LabelDefinition[]>(`/api/books/${bookId}/labels`, token, { method: "PUT", body: JSON.stringify(labels) }),
  saveBookEntities: (token: string, bookId: number, entities: Partial<BookEntity>[]) =>
    request<BookEntity[]>(`/api/books/${bookId}/entities`, token, { method: "PUT", body: JSON.stringify(entities) }),
  saveAssignments: (token: string, bookId: number, items: { user_id: number; start_page: number; end_page: number }[]) =>
    request<{ assigned: number }>(`/api/books/${bookId}/assignments`, token, { method: "POST", body: JSON.stringify({ items }) }),
  bookAssignments: (token: string, bookId: number) => request<Assignment[]>(`/api/books/${bookId}/assignments`, token),
  startRecognition: (token: string, bookId: number, startPage: number, endPage: number) => request<RecognitionBatch>(`/api/books/${bookId}/recognize/start`, token, { method: "POST", body: JSON.stringify({ start_page: startPage, end_page: endPage }) }),
  preprocessPage: (token: string, pageId: number) => request<{ ok: boolean; recognition_job_id: number; platform_job_id: number }>(`/api/book-pages/${pageId}/preprocess`, token, { method: "POST" }),
  clearPageRecognition: (token: string, pageId: number) => request<{ ok: boolean; regions: number; lines: number; chars: number; raw_files: number; jobs: number }>(`/api/book-pages/${pageId}/recognition`, token, { method: "DELETE" }),
  applyPageRecognition: (token: string, pageId: number) => request<{ ok: boolean; applied: number; replaced: number; lines: number; chars: number }>(`/api/book-pages/${pageId}/apply-recognition`, token, { method: "POST" }),
  platformJobDetail: (token: string, jobId: number) => request<PlatformJob>(`/api/platform-jobs/${jobId}`, token),
  recognitionStatus: (token: string, bookId: number) => request<RecognitionBatch>(`/api/books/${bookId}/recognize/status`, token),
  recognitionJobDetail: (token: string, jobId: number) => request<RecognitionBatch>(`/api/recognition-jobs/${jobId}`, token),
  recognitionLatest: (token: string, pageId: number) => request<RecognitionLatest>(`/api/book-pages/${pageId}/recognition-latest`, token),
  workflowTemplates: (token: string) => request<{ items: WorkflowTemplate[] }>("/api/workflows", token),
  workflowNodeTypes: (token: string) => request<{ types: { type: string; label: string; role: string; category: string; color: string; required?: boolean }[] }>("/api/workflows/node-types", token),
  validateWorkflow: (token: string, graph: WorkflowGraph) => request<{ ok: boolean; errors: string[]; order: string[] }>("/api/workflows/validate", token, { method: "POST", body: JSON.stringify({ graph }) }),
  createWorkflow: (token: string, data: { name: string; description: string; graph: WorkflowGraph }) => request<WorkflowTemplate>("/api/workflows", token, { method: "POST", body: JSON.stringify(data) }),
  saveWorkflowTemplate: (token: string, id: number, data: { name: string; description: string; graph: WorkflowGraph }) => request<WorkflowTemplate>(`/api/workflows/${id}`, token, { method: "PUT", body: JSON.stringify(data) }),
  publishWorkflow: (token: string, id: number) => request<WorkflowTemplate>(`/api/workflows/${id}/publish`, token, { method: "POST" }),
  workflowVersions: (token: string, id: number) => request<WorkflowVersion[]>(`/api/workflows/${id}/versions`, token),
  bookWorkflow: (token: string, bookId: number) => request<BookWorkflowRun>(`/api/books/${bookId}/workflow`, token),
  bindBookWorkflow: (token: string, bookId: number, versionId: number) => request<BookWorkflowRun>(`/api/books/${bookId}/workflow/bind`, token, { method: "POST", body: JSON.stringify({ version_id: versionId }) }),
  checkWorkflowUpgrade: (token: string, bookId: number, versionId: number) => request<{ ok: boolean; errors: string[] }>(`/api/books/${bookId}/workflow/upgrade-check`, token, { method: "POST", body: JSON.stringify({ version_id: versionId }) }),
  upgradeBookWorkflow: (token: string, bookId: number, versionId: number) => request<BookWorkflowRun>(`/api/books/${bookId}/workflow/upgrade`, token, { method: "POST", body: JSON.stringify({ version_id: versionId }) }),
  assignWorkflowNode: (token: string, bookId: number, nodeKey: string, userId: number, startPage: number, endPage: number) => request<WorkflowNodeRun>(`/api/books/${bookId}/workflow/nodes/${nodeKey}/assign`, token, { method: "POST", body: JSON.stringify({ user_id: userId, start_page: startPage, end_page: endPage }) }),
  workflowTaskAction: (token: string, taskId: number, action: "complete" | "approve" | "return", comment = "") => request<{ task: WorkflowNodeRun; run: BookWorkflowRun }>(`/api/workflow-page-tasks/${taskId}/action`, token, { method: "POST", body: JSON.stringify({ action, comment }) }),
  myAssignments: (token: string) => request<Assignment[]>("/api/my/assignments", token),
  reviewAssignments: (token: string) => request<Assignment[]>("/api/review/assignments", token),
  workflow: (token: string, assignmentId: number) => request<Workflow>(`/api/assignments/${assignmentId}/workflow`, token),
  resetAssignmentOcr: (token: string, assignmentId: number, mode: "all" | "columns") => request<Workflow>(`/api/assignments/${assignmentId}/reset-ocr`, token, { method: "POST", body: JSON.stringify({ mode }) }),
  saveWorkflow: (token: string, assignmentId: number, workflow: Pick<Workflow, "regions" | "lines" | "chars" | "entity_annotations"> & { current_step: number; expected_version: number }) =>
    request<Workflow>(`/api/assignments/${assignmentId}/workflow`, token, { method: "PUT", body: JSON.stringify(workflow) }),
  submitAssignment: (token: string, assignmentId: number) => request<Assignment>(`/api/assignments/${assignmentId}/submit`, token, { method: "POST" }),
  reviewAssignment: (token: string, assignmentId: number, action: "approve" | "return", comment: string) =>
    request<Assignment>(`/api/assignments/${assignmentId}/review`, token, { method: "POST", body: JSON.stringify({ action, comment }) }),
  searchCharacters: (token: string, bookId: number, q: string) => request<CharacterEntry[]>(`/api/characters?book_id=${bookId}&q=${encodeURIComponent(q)}`, token),
  createCharacter: (token: string, data: Partial<CharacterEntry> & { book_id: number }) => request<CharacterEntry>("/api/characters", token, { method: "POST", body: JSON.stringify(data) }),
  exportFinal: async (token: string, bookId: number) => {
    const response = await fetch(`${API_BASE}/api/books/${bookId}/final-export`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!response.ok) throw new Error("导出失败");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `book_${bookId}_final.zip`;
    link.click();
    URL.revokeObjectURL(url);
  }
};
