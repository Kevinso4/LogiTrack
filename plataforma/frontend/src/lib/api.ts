/**
 * Cliente del API Gateway. Toda la app habla solo con el gateway.
 * - El access token vive en memoria (no en localStorage: fuera del alcance de un XSS persistente).
 * - El refresh token es una cookie HttpOnly que gestiona el gateway; ante un 401 se renueva una vez.
 */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

let accessToken: string | null = null;
let alExpirar: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function getAccessToken() {
  return accessToken;
}
export function onSesionExpirada(fn: () => void) {
  alExpirar = fn;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public codigo: string,
    mensaje: string,
    public requestId?: string,
    public detalles?: { campo: string; mensaje: string }[],
  ) {
    super(mensaje);
  }
}

interface RespuestaSesion {
  access_token: string;
  usuario: import("./types").Usuario;
}

let renovacion: Promise<RespuestaSesion | null> | null = null;

/** Rota el refresh token (cookie HttpOnly). Las llamadas concurrentes comparten una sola petición. */
export function refrescarSesion(): Promise<RespuestaSesion | null> {
  if (!renovacion) {
    renovacion = fetch(`${API_URL}/api/v1/auth/refresh`, { method: "POST", credentials: "include" })
      .then(async (r) => {
        if (!r.ok) return null;
        const datos: RespuestaSesion = await r.json();
        accessToken = datos.access_token;
        return datos;
      })
      .catch(() => null)
      .finally(() => {
        renovacion = null;
      });
  }
  return renovacion;
}

async function renovar(): Promise<boolean> {
  return (await refrescarSesion()) !== null;
}

export async function api<T>(ruta: string, opciones: RequestInit & { json?: unknown } = {}, reintento = true): Promise<T> {
  const { json, headers, ...resto } = opciones;
  const cabeceras: Record<string, string> = { ...(headers as Record<string, string>) };
  if (accessToken) cabeceras.Authorization = `Bearer ${accessToken}`;
  if (json !== undefined) cabeceras["Content-Type"] = "application/json";

  let r: Response;
  try {
    r = await fetch(`${API_URL}${ruta}`, {
      ...resto,
      headers: cabeceras,
      body: json !== undefined ? JSON.stringify(json) : resto.body,
      credentials: "include",
    });
  } catch {
    throw new ApiError(0, "sin_conexion", "No se pudo contactar con el API Gateway. ¿Está corriendo docker compose?");
  }

  if (r.status === 401 && reintento && !ruta.startsWith("/api/v1/auth/")) {
    if (await renovar()) return api<T>(ruta, opciones, false);
    alExpirar?.();
  }
  if (!r.ok) {
    let cuerpo: { error?: string; mensaje?: string; request_id?: string; detalles?: { campo: string; mensaje: string }[] } = {};
    try {
      cuerpo = await r.json();
    } catch {
      /* respuesta sin cuerpo JSON */
    }
    const detalle = cuerpo.detalles?.map((d) => `${d.campo}: ${d.mensaje}`).join(" · ");
    throw new ApiError(
      r.status,
      cuerpo.error ?? "error",
      detalle ? `${cuerpo.mensaje ?? "Error"} — ${detalle}` : cuerpo.mensaje ?? `Error ${r.status}`,
      cuerpo.request_id,
      cuerpo.detalles,
    );
  }
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}
