import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, isValidSession } from "@/lib/auth";

/**
 * Gates every page behind the shared password.
 *
 * Runs before any route renders, so no data reaches the browser for an
 * unauthenticated visitor -- a page-level check would still ship the
 * server-rendered payload first.
 */
export async function proxy(request: NextRequest) {
  const secret = process.env.AUTH_SECRET;
  const password = process.env.APP_PASSWORD;

  // Unconfigured means open: a local dev run without these set should not
  // lock the developer out of their own app.
  if (!secret || !password) return NextResponse.next();

  const { pathname } = request.nextUrl;
  if (pathname === "/login") return NextResponse.next();

  const token = request.cookies.get(SESSION_COOKIE)?.value;
  if (await isValidSession(token, secret)) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  // Return the visitor where they were headed once they sign in.
  url.searchParams.set("next", pathname);
  return NextResponse.redirect(url);
}

export const config = {
  // Static assets and the Next internals are excluded: they carry no data
  // and gating them would break the login page's own styling.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|ico)$).*)"],
};
