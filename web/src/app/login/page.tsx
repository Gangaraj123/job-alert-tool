import { LoginForm } from "@/components/LoginForm";

export const metadata = { title: "Sign in · Job Alerts" };

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const { next, error } = await searchParams;
  return <LoginForm next={next} error={error} />;
}
