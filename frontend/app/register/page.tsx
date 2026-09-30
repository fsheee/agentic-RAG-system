"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { signUp } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signUp(name, email, password);
      router.push("/");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Registration failed. Try again."
      );
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 items-center justify-center px-4 py-10">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-4 rounded-xl border border-zinc-200 p-6 dark:border-zinc-800"
      >
        <h1 className="text-lg font-semibold">Create an account</h1>

        <p className="text-sm text-zinc-500">
          New accounts are created as <strong>patient</strong> accounts.
        </p>

        {error && (
          <p className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            {error}
          </p>
        )}

        <label className="block text-sm">
          Name
          <input
            type="text"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="mt-1 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>

        <label className="block text-sm">
          Email
          <input
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="mt-1 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>

        <label className="block text-sm">
          Password
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-1 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
          <span className="mt-1 block text-xs text-zinc-500">At least 8 characters.</span>
        </label>

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-zinc-900 px-4 py-2 text-sm text-zinc-50 hover:bg-zinc-700 disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {submitting ? "Creating…" : "Register"}
        </button>

        <p className="text-sm text-zinc-500">
          Already registered?{" "}
          <Link href="/login" className="underline">
            Sign in
          </Link>
        </p>
      </form>
    </div>
  );
}
