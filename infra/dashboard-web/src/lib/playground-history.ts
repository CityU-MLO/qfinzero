export type PlaygroundThreadStatus = "regular" | "archived";

export interface PlaygroundThread {
  id: string;
  title: string;
  status: PlaygroundThreadStatus;
  createdAt: string;
  updatedAt: string;
}

export interface StoredThreadMessage {
  id?: string;
  role?: string;
  content?: unknown;
  createdAt?: string;
  [key: string]: unknown;
}

export interface StoredThreadRepositoryItem {
  parentId: string | null;
  message: StoredThreadMessage;
  runConfig?: Record<string, unknown>;
}

export interface StoredThreadRepository {
  headId?: string | null;
  messages: StoredThreadRepositoryItem[];
}

const THREADS_KEY = "playground_threads_v1";
const THREAD_MESSAGES_PREFIX = "playground_thread_messages_v1:";
const DEFAULT_THREAD_TITLE = "New Chat";

function getStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

function parseJson<T>(raw: string | null, fallback: T): T {
  if (!raw) return fallback;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function compactText(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

function extractTextFromContent(content: unknown): string {
  if (typeof content === "string") return compactText(content);
  if (!Array.isArray(content)) return "";

  const chunks = content
    .filter((part): part is { type?: string; text?: string } => !!part && typeof part === "object")
    .map((part) => (part.type === "text" && typeof part.text === "string" ? part.text : ""))
    .filter(Boolean);

  return compactText(chunks.join(" "));
}

export function loadThreads(): PlaygroundThread[] {
  const storage = getStorage();
  if (!storage) return [];
  const threads = parseJson<PlaygroundThread[]>(storage.getItem(THREADS_KEY), []);
  return threads.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function saveThreads(threads: PlaygroundThread[]) {
  const storage = getStorage();
  if (!storage) return;
  storage.setItem(THREADS_KEY, JSON.stringify(threads));
}

export function upsertThread(thread: PlaygroundThread) {
  const threads = loadThreads();
  const next = threads.filter((t) => t.id !== thread.id);
  next.push(thread);
  saveThreads(next);
}

export function removeThread(threadId: string) {
  const storage = getStorage();
  if (!storage) return;
  saveThreads(loadThreads().filter((t) => t.id !== threadId));
  storage.removeItem(`${THREAD_MESSAGES_PREFIX}${threadId}`);
}

export function loadThreadMessages(threadId: string): StoredThreadMessage[] {
  const storage = getStorage();
  if (!storage) return [];
  return parseJson<StoredThreadMessage[]>(
    storage.getItem(`${THREAD_MESSAGES_PREFIX}${threadId}`),
    []
  );
}

export function saveThreadMessages(threadId: string, messages: StoredThreadMessage[]) {
  const storage = getStorage();
  if (!storage) return;
  storage.setItem(`${THREAD_MESSAGES_PREFIX}${threadId}`, JSON.stringify(messages));
}

export function appendThreadMessage(threadId: string, message: StoredThreadMessage) {
  const messages = loadThreadMessages(threadId);
  messages.push(message);
  saveThreadMessages(threadId, messages);
}

export function deriveThreadTitleFromMessage(message: StoredThreadMessage): string {
  if (message.role !== "user") return DEFAULT_THREAD_TITLE;
  const text = extractTextFromContent(message.content);
  if (!text) return DEFAULT_THREAD_TITLE;
  return text.length > 48 ? `${text.slice(0, 48)}…` : text;
}

export function ensureThread(threadId: string): PlaygroundThread {
  const now = new Date().toISOString();
  const existing = loadThreads().find((t) => t.id === threadId);
  if (existing) return existing;

  const thread: PlaygroundThread = {
    id: threadId,
    title: DEFAULT_THREAD_TITLE,
    status: "regular",
    createdAt: now,
    updatedAt: now,
  };
  upsertThread(thread);
  return thread;
}

export function touchThread(threadId: string, nextTitle?: string) {
  const base = ensureThread(threadId);
  const thread: PlaygroundThread = {
    ...base,
    title: nextTitle ?? base.title,
    updatedAt: new Date().toISOString(),
  };
  upsertThread(thread);
}

export function setThreadStatus(threadId: string, status: PlaygroundThreadStatus) {
  const base = ensureThread(threadId);
  const thread: PlaygroundThread = {
    ...base,
    status,
    updatedAt: new Date().toISOString(),
  };
  upsertThread(thread);
}

export function renameThread(threadId: string, title: string) {
  const compact = title.trim();
  touchThread(threadId, compact || PLAYGROUND_HISTORY_DEFAULT_TITLE);
}

export function maybeAutoTitleThread(threadId: string, message: StoredThreadMessage) {
  const existing = ensureThread(threadId);
  if (existing.title !== DEFAULT_THREAD_TITLE) return;
  const candidate = deriveThreadTitleFromMessage(message);
  if (candidate === DEFAULT_THREAD_TITLE) return;
  touchThread(threadId, candidate);
}

export const PLAYGROUND_HISTORY_DEFAULT_TITLE = DEFAULT_THREAD_TITLE;

export function loadThreadRepository(threadId: string): StoredThreadRepository {
  const messages = loadThreadMessages(threadId);
  return {
    headId: messages[messages.length - 1]?.id ?? null,
    messages: messages.map((message, index) => ({
      parentId: index > 0 ? messages[index - 1]?.id ?? null : null,
      message,
    })),
  };
}

export function saveThreadRepository(threadId: string, repository: StoredThreadRepository) {
  saveThreadMessages(
    threadId,
    repository.messages.map((item) => item.message)
  );
}

export function upsertThreadRepositoryItem(threadId: string, item: StoredThreadRepositoryItem) {
  const repository = loadThreadRepository(threadId);
  const nextMessages = repository.messages.filter((entry) => entry.message.id !== item.message.id);
  nextMessages.push(item);
  saveThreadRepository(threadId, {
    headId: item.message.id ?? repository.headId ?? null,
    messages: nextMessages,
  });
}
