import type { Context } from "@netlify/edge-functions";

export default async function auth(request: Request, context: Context) {
  const user = Deno.env.get("BASIC_AUTH_USER") ?? "admin";
  const password = Deno.env.get("BASIC_AUTH_PASSWORD") ?? "";

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

  return context.next();
}
