// Single door to the backend. The frontend must never talk to Qdrant,
// Neon, or the LLM provider directly — only to FastAPI.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Role = "patient" | "doctor" | "employee" | "hr" | "admin";

export interface User {
  id: number;
  name: string;
  email: string;
  role: Role;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface Source {
  source: string;
  page: number | null;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
  conversation_id: number | null;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  token?: string | null;
}

// FastAPI errors carry `detail` as a string or as a validation array.
function messageFromDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String(item.msg)
          : JSON.stringify(item)
      )
      .join(" ");
  }
  if (detail) return JSON.stringify(detail);
  return "Request failed.";
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, token } = options;

  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Cannot reach the API. Is the backend running?");
  }

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : null;
    throw new ApiError(response.status, messageFromDetail(detail));
  }

  return payload as T;
}

export function register(name: string, email: string, password: string) {
  return request<User>("/auth/register", {
    method: "POST",
    body: { name, email, password },
  });
}

export function login(email: string, password: string) {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: { email, password },
  });
}

export function me(token: string) {
  return request<User>("/auth/me", { token });
}

export function ask(
  question: string,
  options: { token?: string | null; conversationId?: number | null } = {}
) {
  const { token = null, conversationId = null } = options;
  return request<AskResponse>("/ask", {
    method: "POST",
    token,
    body: {
      question,
      ...(conversationId !== null ? { conversation_id: conversationId } : {}),
    },
  });
}
