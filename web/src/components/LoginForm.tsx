"use client";

import * as React from "react";
import { Lock } from "lucide-react";
import { signIn } from "@/app/login/actions";
import { Button, Card, Input } from "@/components/ui/primitives";

export function LoginForm({
  next,
  error,
}: {
  next?: string;
  error?: string;
}) {
  const [pending, setPending] = React.useState(false);

  return (
    <div className="grid min-h-dvh place-items-center px-4">
      <Card className="w-full max-w-sm p-6">
        <div className="mb-5">
          <span className="mb-3 grid size-9 place-items-center rounded-lg bg-accent-soft text-accent">
            <Lock size={17} />
          </span>
          <h1 className="font-display text-xl font-bold">Job Alerts</h1>
          <p className="mt-1 text-sm text-muted">
            Enter the shared password to continue.
          </p>
        </div>

        <form
          action={async (formData) => {
            setPending(true);
            try {
              await signIn(formData);
            } finally {
              setPending(false);
            }
          }}
          className="space-y-3"
        >
          <input type="hidden" name="next" value={next ?? "/"} />
          <Input
            type="password"
            name="password"
            autoFocus
            required
            autoComplete="current-password"
            placeholder="Password"
            aria-label="Password"
            aria-invalid={error ? true : undefined}
          />
          {error ? (
            <p role="alert" className="text-xs text-danger">
              That password didn&rsquo;t match. Try again.
            </p>
          ) : null}
          <Button
            type="submit"
            variant="primary"
            disabled={pending}
            className="w-full"
          >
            {pending ? "Checking…" : "Sign in"}
          </Button>
        </form>

        <p className="mt-4 text-xs text-faint">
          This browser stays signed in for 90 days.
        </p>
      </Card>
    </div>
  );
}
