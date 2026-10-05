"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ask, type Role, type Source } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
}

interface ChatState {
  messages: Message[];
  conversationId: number | null;
}

const EMPTY_CHAT: ChatState = { messages: [], conversationId: null };

interface Suggestion {
  label: string;
  question: string;
  // Roles allowed to ask this. Omitted = everyone, including anonymous
  // visitors. Mirrors what the backend will actually answer, so a chip
  // never promises an answer the caller cannot get:
  // - documents: app/access.py (HR handbook is staff tier)
  // - appointments: app/agent/graph.py APPOINTMENT_ROLES
  roles?: readonly Role[];
  // Short label on the chip when the signed-in role is not allowed.
  badge?: string;
  // Message shown if such a caller clicks the chip anyway.
  restricted?: string;
}

const APPOINTMENT_ROLES: readonly Role[] = ["patient", "admin"];
const STAFF_ROLES: readonly Role[] = ["doctor", "employee", "hr", "admin"];

const SUGGESTIONS: Suggestion[] = [
  { label: "Hospital Information", question: "What are the hospital visiting hours?" },
  { label: "Doctors & Services", question: "Which doctors are available for dermatology?" },
  { label: "Consultation Fees", question: "What is the consultation fee for a dermatologist?" },
  {
    label: "Appointments",
    question: "Book an appointment with Dr. Bilal Raza.",
    roles: APPOINTMENT_ROLES,
    badge: "Patients & admins",
    restricted: "Only patients and administrators can book appointments.",
  },
  {
    label: "My Appointments",
    question: "Show my upcoming appointments.",
    roles: APPOINTMENT_ROLES,
    badge: "Patients & admins",
    restricted: "Only patients and administrators can view appointments.",
  },
  {
    label: "Hospital Policies",
    question: "What is the annual leave policy for employees?",
    roles: STAFF_ROLES,
    badge: "Staff only",
    restricted: "Employee policies are available to staff accounts only.",
  },
];

// Anonymous visitors are sent to sign in; a signed-in caller with the
// wrong role gets the chip's own `restricted` message instead.
function blockReason(suggestion: Suggestion, user: { role: Role } | null): string | null {
  if (!suggestion.roles) return null;
  if (user && suggestion.roles.includes(user.role)) return null;
  return user ? suggestion.restricted ?? "Not available for your role." : "Sign in to continue.";
}

export default function ChatPage() {
  const { user, token, loading } = useAuth();
  const router = useRouter();
  const [chats, setChats] = useState<Record<string, ChatState>>({});
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Chat state is keyed by identity, so signing in or out switches to that
  // identity's thread and conversation ids never cross accounts. Derived
  // from state instead of reset in an effect.
  const identity = loading ? "restoring" : user ? `user:${user.id}` : "anonymous";
  const chat = chats[identity] ?? EMPTY_CHAT;

  // Every chip is listed; access is decided per click. An anonymous
  // visitor is sent to sign in, a signed-in caller with the wrong role
  // sees why. The backend enforces the same rules regardless — this only
  // keeps the UI honest.
  function handleSuggestion(suggestion: Suggestion) {
    const blocked = blockReason(suggestion, user);

    if (blocked && !user) {
      router.push("/login");
      return;
    }

    if (blocked) {
      setError(blocked);
      return;
    }

    send(suggestion.question);
  }

  const updateChat = (next: (prev: ChatState) => ChatState) => {
    setChats((prev) => ({
      ...prev,
      [identity]: next(prev[identity] ?? EMPTY_CHAT),
    }));
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.messages, sending]);

  async function send(question: string) {
    if (!question || sending || loading) return;

    setError(null);
    setInput("");
    updateChat((prev) => ({
      ...prev,
      messages: [...prev.messages, { role: "user" as const, content: question }],
    }));
    setSending(true);

    try {
      const response = await ask(question, {
        token,
        conversationId: user ? chat.conversationId : null,
      });

      updateChat((prev) => ({
        ...prev,
        messages: [
          ...prev.messages,
          {
            role: "assistant" as const,
            content: response.answer,
            sources: response.sources,
          },
        ],
        conversationId: response.conversation_id ?? prev.conversationId,
      }));
    } catch (err) {
      // Shown in the UI; nothing internal is exposed beyond this message.
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setSending(false);
    }
  }

  function handleSend(event: React.FormEvent) {
    event.preventDefault();
    send(input.trim());
  }

  function handleNewChat() {
    updateChat(() => EMPTY_CHAT);
    setError(null);
  }

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col px-4">
      <div className="flex items-center justify-between py-3">
        <h1 className="text-sm font-medium text-zinc-500 dark:text-zinc-400">
          {chat.conversationId
            ? `Conversation #${chat.conversationId}`
            : "New conversation"}
        </h1>
        <button
          onClick={handleNewChat}
          className="rounded-full border border-zinc-300 px-3 py-1 text-sm transition hover:border-zinc-400 hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          New chat
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto py-4">
        {chat.messages.length === 0 && (
          <div className="flex min-h-[60vh] flex-col items-center justify-center px-2 text-center">
            <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-lg shadow-indigo-500/30">
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="h-7 w-7"
                aria-hidden="true"
              >
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>

            <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
              Ask your{" "}
              <span className="bg-gradient-to-r from-indigo-500 to-violet-600 bg-clip-text text-transparent">
                hospital knowledge base
              </span>
            </h2>
            <p className="mt-3 max-w-md text-sm leading-6 text-zinc-500 dark:text-zinc-400">
              Grounded answers from hospital policies, HR guidelines and facility
              info — every response cites its sources.
            </p>
            {!loading && !user && (
              <p className="mt-2 text-sm text-zinc-400 dark:text-zinc-500">
                Sign in to keep your conversation history and to ask about
                appointments and staff policies.
              </p>
            )}

            <div className="mt-8 grid w-full max-w-2xl gap-3 sm:grid-cols-2">
              {!loading &&
                SUGGESTIONS.map((suggestion) => {
                  const blocked = blockReason(suggestion, user);
                  const badge = blocked
                    ? (user ? suggestion.badge ?? "Restricted" : "Sign in required")
                    : null;

                  return (
                    <button
                      key={suggestion.label}
                      onClick={() => handleSuggestion(suggestion)}
                      disabled={sending}
                      className="group rounded-2xl border border-zinc-200 bg-white p-4 text-left transition hover:-translate-y-0.5 hover:border-indigo-300 hover:shadow-md disabled:opacity-60 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-indigo-700"
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium group-hover:text-indigo-600 dark:group-hover:text-indigo-400">
                          {suggestion.label}
                        </span>
                        {badge && (
                          <span className="shrink-0 rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 ring-1 ring-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:ring-zinc-700">
                            {badge}
                          </span>
                        )}
                      </span>
                      <span className="mt-1 block text-sm text-zinc-500 dark:text-zinc-400">
                        {suggestion.question}
                      </span>
                    </button>
                  );
                })}
            </div>
          </div>
        )}

        {chat.messages.map((message, index) => (
          <div
            key={index}
            className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
          >
            <div
              className={
                message.role === "user"
                  ? "max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-white"
                  : "max-w-[85%] rounded-2xl rounded-bl-md bg-zinc-100 px-4 py-2.5 dark:bg-zinc-800"
              }
            >
              <p className="whitespace-pre-wrap">{message.content}</p>

              {message.sources && message.sources.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5 border-t border-zinc-300 pt-2.5 dark:border-zinc-600">
                  <span className="mr-1 text-xs font-medium uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                    Sources
                  </span>
                  {message.sources.map((source, i) => (
                    <span
                      key={i}
                      className="rounded-full bg-white/70 px-2 py-0.5 text-xs text-zinc-600 ring-1 ring-zinc-300 dark:bg-zinc-900/70 dark:text-zinc-300 dark:ring-zinc-600"
                    >
                      {source.source}
                      {source.page !== null ? ` p.${source.page}` : ""}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}

        {sending && (
          <div className="flex justify-start">
            <div className="flex items-center gap-1.5 rounded-2xl rounded-bl-md bg-zinc-100 px-4 py-3 dark:bg-zinc-800">
              <span className="h-2 w-2 animate-bounce rounded-full bg-zinc-400 [animation-delay:-0.2s] dark:bg-zinc-500" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-zinc-400 [animation-delay:-0.1s] dark:bg-zinc-500" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-zinc-400 dark:bg-zinc-500" />
            </div>
          </div>
        )}

        {error && (
          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            {error}
          </p>
        )}

        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={handleSend}
        className="border-t border-zinc-200 py-4 dark:border-zinc-800"
      >
        <div className="flex items-center gap-2 rounded-2xl border border-zinc-300 bg-white px-4 py-1.5 shadow-sm transition focus-within:border-indigo-500 focus-within:ring-4 focus-within:ring-indigo-500/10 dark:border-zinc-700 dark:bg-zinc-900 dark:focus-within:border-indigo-500">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder={loading ? "Restoring session…" : "Ask a question…"}
            disabled={loading}
            className="min-w-0 flex-1 bg-transparent py-2 text-base outline-none placeholder:text-zinc-400 disabled:opacity-60 dark:placeholder:text-zinc-500"
          />
          <button
            type="submit"
            aria-label="Send message"
            disabled={sending || loading || input.trim().length === 0}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="h-4 w-4"
              aria-hidden="true"
            >
              <path d="M12 19V5" />
              <path d="m5 12 7-7 7 7" />
            </svg>
          </button>
        </div>
        <p className="mt-2 text-center text-xs text-zinc-400 dark:text-zinc-500">
          Answers are generated from retrieved documents and may need verification.
        </p>
      </form>
    </div>
  );
}
