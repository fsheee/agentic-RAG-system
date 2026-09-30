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

  async function handleSend(event: React.FormEvent) {
    event.preventDefault();
    const question = input.trim();
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
          className="rounded-md border border-zinc-300 px-3 py-1 text-sm hover:bg-zinc-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
        >
          New chat
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto py-4">
        {chat.messages.length === 0 && (
          <p className="pt-8 text-center text-zinc-500 dark:text-zinc-400">
            Ask a question about the hospital knowledge base.
            {!loading && !user && " Sign in to keep conversation history."}
          </p>
        )}

        {chat.messages.map((message, index) => (
          <div
            key={index}
            className={message.role === "user" ? "flex justify-end" : "flex justify-start"}
          >
            <div
              className={
                message.role === "user"
                  ? "max-w-[85%] rounded-2xl bg-zinc-900 px-4 py-2.5 text-zinc-50 dark:bg-zinc-100 dark:text-zinc-900"
                  : "max-w-[85%] rounded-2xl bg-zinc-100 px-4 py-2.5 dark:bg-zinc-800"
              }
            >
              <p className="whitespace-pre-wrap">{message.content}</p>

              {message.sources && message.sources.length > 0 && (
                <div className="mt-2 border-t border-zinc-300 pt-2 text-xs dark:border-zinc-600">
                  <span className="font-medium">Sources:</span>{" "}
                  {message.sources.map((source, i) => (
                    <span key={i} className="mr-2">
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
            <div className="rounded-2xl bg-zinc-100 px-4 py-2.5 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
              Thinking…
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

      <form onSubmit={handleSend} className="flex gap-2 border-t border-zinc-200 py-4 dark:border-zinc-800">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder={loading ? "Restoring session…" : "Ask a question…"}
          disabled={loading}
          className="flex-1 rounded-md border border-zinc-300 bg-white px-3 py-2 outline-none focus:border-zinc-500 disabled:opacity-60 dark:border-zinc-700 dark:bg-zinc-900"
        />
        <button
          type="submit"
          disabled={sending || loading || input.trim().length === 0}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm text-zinc-50 hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          Send
        </button>
      </form>
    </div>
  );
}
