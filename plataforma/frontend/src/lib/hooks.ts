"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, API_URL, getAccessToken } from "./api";
import type { EventoDominio } from "./types";

/** GET periódico al gateway. Pausa el sondeo cuando la pestaña no está visible. */
export function useDatos<T>(ruta: string | null, intervaloMs = 0) {
  const [datos, setDatos] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [cargando, setCargando] = useState(true);
  const rutaRef = useRef(ruta);
  rutaRef.current = ruta;

  const recargar = useCallback(async () => {
    const actual = rutaRef.current;
    if (!actual) return;
    try {
      const r = await api<T>(actual);
      if (rutaRef.current === actual) {
        setDatos(r);
        setError(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error desconocido");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    setCargando(true);
    recargar();
    if (!intervaloMs) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") recargar();
    }, intervaloMs);
    return () => clearInterval(id);
  }, [ruta, intervaloMs, recargar]);

  return { datos, error, cargando, recargar, setDatos };
}

/** Feed en vivo de eventos de dominio (SSE desde el gateway, alimentado por RabbitMQ). */
export function useEventosEnVivo(max = 40, alRecibir?: (e: EventoDominio) => void) {
  const [eventos, setEventos] = useState<EventoDominio[]>([]);
  const [conectado, setConectado] = useState(false);
  const callback = useRef(alRecibir);
  callback.current = alRecibir;

  useEffect(() => {
    let fuente: EventSource | null = null;
    let cancelado = false;
    let reintento: ReturnType<typeof setTimeout>;

    api<EventoDominio[]>("/api/v1/eventos/recientes")
      .then((r) => !cancelado && setEventos(r.slice(0, max)))
      .catch(() => undefined);

    const conectar = () => {
      const token = getAccessToken();
      if (!token || cancelado) return;
      fuente = new EventSource(`${API_URL}/api/v1/eventos/stream?token=${encodeURIComponent(token)}`);
      fuente.onopen = () => setConectado(true);
      fuente.addEventListener("dominio", (m) => {
        const evento: EventoDominio = JSON.parse((m as MessageEvent).data);
        setEventos((prev) => [evento, ...prev.filter((p) => p.event_id !== evento.event_id)].slice(0, max));
        callback.current?.(evento);
      });
      fuente.onerror = () => {
        setConectado(false);
        fuente?.close();
        // El token de acceso pudo expirar: se reconecta con el vigente.
        reintento = setTimeout(conectar, 4000);
      };
    };
    conectar();
    return () => {
      cancelado = true;
      clearTimeout(reintento);
      fuente?.close();
    };
  }, [max]);

  return { eventos, conectado };
}
