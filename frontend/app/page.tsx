"use client";

import { useEffect, useRef, useState } from "react";
import { ask, type Source } from "@/lib/api";
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

const SUGGESTIONS = [
  { label: "Visiting hours", question: "What are the hospital visiting hours?" },
  { label: "Leave policy", question: "What is the annual leave policy for employees?" },
  { label: "Facilities", question: "Which departments and facilities does the hospital have?" },
  { label: "Emergency rules", question: "What is the procedure during a medical emergency?" },
];

export default function ChatPage() {
  const { user, token, loading } = useAuth();
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
                Sign in to keep your conversation history.
              </p>
            )}

            <div className="mt-8 grid w-full max-w-2xl gap-3 sm:grid-cols-2">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion.label}
                  onClick={() => send(suggestion.question)}
                  disabled={sending}
                  className="group rounded-2xl border border-zinc-200 bg-white p-4 text-left transition hover:-translate-y-0.5 hover:border-indigo-300 hover:shadow-md disabled:opacity-60 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-indigo-700"
                >
                  <span className="block text-sm font-medium group-hover:text-indigo-600 dark:group-hover:text-indigo-400">
                    {suggestion.label}
                  </span>
                  <span className="mt-1 block text-sm text-zinc-500 dark:text-zinc-400">
                    {suggestion.question}
                  </span>
                </button>
              ))}
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
