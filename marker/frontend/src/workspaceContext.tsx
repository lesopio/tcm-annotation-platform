import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, Book, Role } from "./api";

export const STORAGE_KEYS = { token: "bencao_token", display: "bencao_display_settings", workspace: "bencao_workspace_ctx" } as const;

type WorkspaceState = { bookId: number; pageId: number; assignmentId: number; tabs: Record<string, string> };
type WorkspaceContextValue = WorkspaceState & {
  setBookId: (id: number) => void;
  setPageId: (id: number) => void;
  setAssignmentId: (id: number) => void;
  rememberTab: (workspace: string, tab: string) => void;
};
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);
const emptyState: WorkspaceState = { bookId: 0, pageId: 0, assignmentId: 0, tabs: {} };

function readStoredState(): WorkspaceState {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.workspace);
    if (!raw) return emptyState;
    const parsed = JSON.parse(raw) as Partial<WorkspaceState>;
    return {
      bookId: Number(parsed.bookId) || 0,
      pageId: Number(parsed.pageId) || 0,
      assignmentId: Number(parsed.assignmentId) || 0,
      tabs: parsed.tabs && typeof parsed.tabs === "object" ? parsed.tabs : {},
    };
  } catch {
    return emptyState;
  }
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<WorkspaceState>(readStoredState);
  useEffect(() => { try { localStorage.setItem(STORAGE_KEYS.workspace, JSON.stringify(state)); } catch { /* 存储不可用时静默降级为会话内状态 */ } }, [state]);
  const value = useMemo<WorkspaceContextValue>(() => ({
    ...state,
    setBookId: (bookId) => setState(prev => ({ ...prev, bookId, pageId: 0 })),
    setPageId: (pageId) => setState(prev => ({ ...prev, pageId })),
    setAssignmentId: (assignmentId) => setState(prev => ({ ...prev, assignmentId })),
    rememberTab: (workspace, tab) => setState(prev => prev.tabs[workspace] === tab ? prev : ({ ...prev, tabs: { ...prev.tabs, [workspace]: tab } })),
  }), [state]);
  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("useWorkspace 必须在 WorkspaceProvider 内使用");
  return value;
}

export type WorkspaceTab = { key: string; label: string; roles: Role[] };

/** 读取并校验工作区 tab：未知或无权限的 tab 回退到该角色默认值，并回写地址栏。 */
export function useWorkspaceTab(workspace: string, role: Role, tabs: WorkspaceTab[], fallbackKey: string): { tab: string; setTab: (key: string) => void } {
  const { tabs: remembered, rememberTab } = useWorkspace();
  const [searchParams, setSearchParams] = useSearchParams();
  const allowed = tabs.filter(item => item.roles.includes(role));
  const fallback = allowed.some(item => item.key === fallbackKey) ? fallbackKey : allowed[0]?.key ?? "";
  const requested = searchParams.get("tab") || remembered[workspace] || "";
  const tab = allowed.some(item => item.key === requested) ? requested : fallback;
  useEffect(() => {
    if (tab && searchParams.get("tab") !== tab) {
      const next = new URLSearchParams(searchParams);
      next.set("tab", tab);
      setSearchParams(next, { replace: true });
    }
  });
  useEffect(() => { if (tab) rememberTab(workspace, tab); }, [tab, workspace, rememberTab]);
  const setTab = useCallback((key: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", key);
    setSearchParams(next);
  }, [searchParams, setSearchParams]);
  return { tab, setTab };
}

/** 工作区共享的书籍选择：校验已存 bookId 是否仍存在，失效时回退到首个可访问书籍。 */
export function useWorkspaceBook(token: string): { books: Book[]; bookId: number; selectBook: (id: number) => void } {
  const { bookId, setBookId } = useWorkspace();
  const [books, setBooks] = useState<Book[]>([]);
  useEffect(() => { let alive = true; api.books(token).then(rows => { if (alive) setBooks(rows); }).catch(() => { if (alive) setBooks([]); }); return () => { alive = false; }; }, [token]);
  useEffect(() => { if (books.length && !books.some(item => item.id === bookId)) setBookId(books[0].id); }, [books, bookId, setBookId]);
  return { books, bookId, selectBook: setBookId };
}
