import { NextRequest, NextResponse } from "next/server";

const COOKIE_NAME = process.env.AUTH_COOKIE_NAME || "kol_session";
const CONFIGURED_BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH || "";

function routePath(basePath: string, pathname: string) {
  if (pathname === "/") return basePath || "/";
  return `${basePath}${pathname}`;
}

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const basePath = request.nextUrl.basePath || CONFIGURED_BASE_PATH;
  const appPath = basePath && (pathname === basePath || pathname.startsWith(`${basePath}/`))
    ? pathname.slice(basePath.length) || "/"
    : pathname;
  const authenticated = Boolean(request.cookies.get(COOKIE_NAME)?.value);

  if (appPath === "/login") {
    return authenticated
      ? NextResponse.redirect(new URL(routePath(basePath, "/"), request.url))
      : NextResponse.next();
  }

  if (!authenticated) {
    const loginUrl = new URL(routePath(basePath, "/login"), request.url);
    loginUrl.searchParams.set("next", `${appPath}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/", "/((?!_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
