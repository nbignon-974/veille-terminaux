import type { Context } from "@netlify/edge-functions";

const SESSION_COOKIE = "vt_session";
const SESSION_MAX_AGE = 86400 * 7; // 7 jours

async function hmacSign(message: string, secret: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(message));
  return btoa(String.fromCharCode(...new Uint8Array(sig)));
}

async function isValidSession(token: string, secret: string): Promise<boolean> {
  const dot = token.lastIndexOf(".");
  if (dot === -1) return false;
  const payload = token.slice(0, dot);
  const sig = token.slice(dot + 1);
  const expected = await hmacSign(payload, secret);
  if (sig !== expected) return false;
  try {
    const ts = parseInt(atob(payload), 10);
    return !isNaN(ts) && Date.now() - ts < SESSION_MAX_AGE * 1000;
  } catch {
    return false;
  }
}

function getCookie(header: string, name: string): string | null {
  for (const part of header.split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return v.join("=");
  }
  return null;
}

export default async function auth(request: Request, context: Context) {
  const user = Deno.env.get("BASIC_AUTH_USER") ?? "admin";
  const password = Deno.env.get("BASIC_AUTH_PASSWORD") ?? "";
  const secret = Deno.env.get("SESSION_SECRET") ?? "change-me-in-production";

  // Cookie de session valide → passage immédiat sans vérification
  const cookieHeader = request.headers.get("cookie") ?? "";
  const sessionToken = getCookie(cookieHeader, SESSION_COOKIE);
  if (sessionToken && await isValidSession(sessionToken, secret)) {
    return context.next();
  }

  // Vérification Basic Auth
  const authHeader = request.headers.get("Authorization");
  const expected = "Basic " + btoa(`${user}:${password}`);

  if (!authHeader || authHeader !== expected) {
    return new Response("Accès non autorisé", {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="Veille Terminaux"',
        "Content-Type": "text/plain; charset=utf-8",
      },
    });
  }

  // Credentials valides → émet le cookie de session signé
  const payload = btoa(String(Date.now()));
  const sig = await hmacSign(payload, secret);
  const token = `${payload}.${sig}`;

  const response = await context.next();
  const headers = new Headers(response.headers);
  headers.append(
    "Set-Cookie",
    `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=${SESSION_MAX_AGE}`,
  );
  return new Response(response.body, { status: response.status, headers });
}
