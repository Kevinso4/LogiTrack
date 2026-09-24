"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { IconCerrar } from "./icons";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type Tono = "green" | "accent" | "orange" | "red" | "gray" | "indigo" | "teal";

const TONOS: Record<Tono, string> = {
  green: "text-green bg-green/12",
  accent: "text-accent bg-accent/12",
  orange: "text-orange bg-orange/14",
  red: "text-red bg-red/12",
  gray: "text-label-2 bg-fill",
  indigo: "text-indigo bg-indigo/12",
  teal: "text-teal bg-teal/14",
};
const PUNTOS: Record<Tono, string> = {
  green: "bg-green", accent: "bg-accent", orange: "bg-orange", red: "bg-red", gray: "bg-label-3", indigo: "bg-indigo", teal: "bg-teal",
};

export function Badge({ tono = "gray", children, punto = false }: { tono?: Tono; children: React.ReactNode; punto?: boolean }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12px] font-semibold whitespace-nowrap", TONOS[tono])}>
      {punto && <span className={cx("size-1.5 rounded-full", PUNTOS[tono])} />}
      {children}
    </span>
  );
}

export function Punto({ tono }: { tono: Tono }) {
  return <span className={cx("inline-block size-2 shrink-0 rounded-full", PUNTOS[tono])} />;
}

export function Card({ children, className, padding = true }: { children: React.ReactNode; className?: string; padding?: boolean }) {
  return (
    <div className={cx("rounded-[20px] bg-surface shadow-card ring-1 ring-hairline", padding && "p-5", className)}>{children}</div>
  );
}

export function TituloSeccion({ children, accion }: { children: React.ReactNode; accion?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="font-display text-[17px] font-semibold tracking-tight">{children}</h2>
      {accion}
    </div>
  );
}

export function Encabezado({ titulo, subtitulo, children }: { titulo: string; subtitulo?: string; children?: React.ReactNode }) {
  return (
    <header className="mb-7 flex flex-wrap items-end justify-between gap-4 animate-aparecer">
      <div>
        <h1 className="font-display text-[34px] leading-[1.1] font-bold tracking-[-0.022em]">{titulo}</h1>
        {subtitulo && <p className="mt-1.5 text-[15px] text-label-2">{subtitulo}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </header>
  );
}

type VarianteBoton = "primario" | "secundario" | "peligro" | "plano";

export function Boton({
  variante = "primario",
  className,
  cargando,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variante?: VarianteBoton; cargando?: boolean }) {
  const estilos: Record<VarianteBoton, string> = {
    primario: "bg-accent text-white hover:bg-accent-hover",
    secundario: "bg-fill text-accent hover:bg-fill-strong",
    peligro: "bg-red/12 text-red hover:bg-red/20",
    plano: "text-accent hover:bg-fill",
  };
  return (
    <button
      {...props}
      disabled={props.disabled || cargando}
      className={cx(
        "inline-flex h-9 items-center justify-center gap-1.5 rounded-full px-4 text-[14px] font-medium transition-[background,transform,opacity] duration-200 active:scale-[0.97] disabled:pointer-events-none disabled:opacity-45 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
        estilos[variante],
        className,
      )}
    >
      {cargando && <span className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  );
}

export function Segmentado<T extends string>({
  opciones,
  valor,
  onChange,
}: {
  opciones: { valor: T; texto: string; cuenta?: number }[];
  valor: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-[10px] bg-fill p-[3px]" role="tablist">
      {opciones.map((o) => (
        <button
          key={o.valor}
          role="tab"
          aria-selected={valor === o.valor}
          onClick={() => onChange(o.valor)}
          className={cx(
            "flex h-7 items-center gap-1.5 rounded-[7px] px-3 text-[13px] font-medium transition-all duration-200",
            valor === o.valor ? "bg-surface text-label shadow-[0_1px_3px_rgba(0,0,0,0.12)]" : "text-label-2 hover:text-label",
          )}
        >
          {o.texto}
          {o.cuenta != null && <span className="tabular text-label-3">{o.cuenta}</span>}
        </button>
      ))}
    </div>
  );
}

export function Campo({ etiqueta, children, ayuda }: { etiqueta: string; children: React.ReactNode; ayuda?: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[13px] font-medium text-label-2">{etiqueta}</span>
      {children}
      {ayuda && <span className="mt-1 block text-[12px] text-label-3">{ayuda}</span>}
    </label>
  );
}

const claseInput =
  "h-10 w-full rounded-[10px] bg-fill px-3 text-[15px] text-label outline-none ring-accent/40 transition placeholder:text-label-3 focus:bg-surface focus:ring-4";

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(claseInput, props.className)} />;
}

export function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(claseInput, "appearance-none pr-8 bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%2386868b%22 stroke-width=%222.5%22><path d=%22m6 9 6 6 6-6%22/></svg>')] bg-[length:12px] bg-[right_12px_center] bg-no-repeat", props.className)} />;
}

export function Interruptor({ activo, onChange, etiqueta }: { activo: boolean; onChange: (v: boolean) => void; etiqueta: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={activo}
      onClick={() => onChange(!activo)}
      className="flex w-full items-center justify-between gap-3 py-1.5 text-left text-[15px]"
    >
      <span>{etiqueta}</span>
      <span className={cx("relative h-[31px] w-[51px] shrink-0 rounded-full transition-colors duration-300", activo ? "bg-green" : "bg-fill-strong")}>
        <span
          className={cx(
            "absolute top-[2px] left-[2px] size-[27px] rounded-full bg-white shadow-[0_3px_8px_rgba(0,0,0,0.15),0_1px_1px_rgba(0,0,0,0.16)] transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]",
            activo && "translate-x-[20px]",
          )}
        />
      </span>
    </button>
  );
}

/** Hoja modal (sheet) que sube desde abajo, como en iOS/macOS. */
export function Hoja({
  abierta,
  onCerrar,
  titulo,
  children,
  ancho = "max-w-lg",
}: {
  abierta: boolean;
  onCerrar: () => void;
  titulo: string;
  children: React.ReactNode;
  ancho?: string;
}) {
  useEffect(() => {
    if (!abierta) return;
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && onCerrar();
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  }, [abierta, onCerrar]);
  if (!abierta) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6" role="dialog" aria-modal="true" aria-label={titulo}>
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px] animate-fade" onClick={onCerrar} />
      <div className={cx("relative max-h-[92vh] w-full overflow-y-auto rounded-t-[22px] bg-surface shadow-sheet animate-sheet sm:rounded-[22px]", ancho)}>
        <div className="glass sticky top-0 z-10 flex items-center justify-between border-b border-hairline px-5 py-3.5">
          <h3 className="font-display text-[17px] font-semibold">{titulo}</h3>
          <button onClick={onCerrar} aria-label="Cerrar" className="grid size-7 place-items-center rounded-full bg-fill text-label-2 transition hover:bg-fill-strong">
            <IconCerrar className="size-3.5" />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Vacio({ titulo, texto, icono }: { titulo: string; texto?: string; icono?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {icono && <div className="mb-3 text-label-3">{icono}</div>}
      <p className="text-[15px] font-semibold">{titulo}</p>
      {texto && <p className="mt-1 max-w-sm text-[13px] text-label-2">{texto}</p>}
    </div>
  );
}

export function Esqueleto({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-xl bg-fill", className)} />;
}

export function ErrorCaja({ mensaje }: { mensaje: string }) {
  return <div className="rounded-xl bg-red/10 px-4 py-3 text-[13px] text-red">{mensaje}</div>;
}

// ---------------------------------------------------------------- avisos (toasts)

interface Aviso {
  id: number;
  texto: string;
  tono: "ok" | "error";
}
const ContextoAvisos = createContext<(texto: string, tono?: "ok" | "error") => void>(() => undefined);

export function ProveedorAvisos({ children }: { children: React.ReactNode }) {
  const [avisos, setAvisos] = useState<Aviso[]>([]);
  const avisar = useCallback((texto: string, tono: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setAvisos((a) => [...a, { id, texto, tono }]);
    setTimeout(() => setAvisos((a) => a.filter((x) => x.id !== id)), 4200);
  }, []);
  return (
    <ContextoAvisos.Provider value={avisar}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-4 z-[60] flex flex-col items-center gap-2 px-4" aria-live="polite">
        {avisos.map((a) => (
          <div
            key={a.id}
            className={cx(
              "glass pointer-events-auto flex max-w-md items-center gap-2.5 rounded-full py-2.5 pr-5 pl-3 text-[14px] font-medium shadow-sheet ring-1 ring-hairline animate-sheet",
            )}
          >
            <span className={cx("grid size-5 place-items-center rounded-full text-[11px] text-white", a.tono === "ok" ? "bg-green" : "bg-red")}>
              {a.tono === "ok" ? "✓" : "!"}
            </span>
            {a.texto}
          </div>
        ))}
      </div>
    </ContextoAvisos.Provider>
  );
}

export const useAvisos = () => useContext(ContextoAvisos);

export function Metrica({ etiqueta, valor, detalle, tono, icono }: { etiqueta: string; valor: React.ReactNode; detalle?: React.ReactNode; tono?: Tono; icono?: React.ReactNode }) {
  const colores: Partial<Record<Tono, string>> = { green: "text-green", accent: "text-accent", orange: "text-orange", red: "text-red", indigo: "text-indigo", teal: "text-teal" };
  return (
    <Card className="animate-aparecer">
      <div className="flex items-center gap-2 text-[13px] font-medium text-label-2">
        {icono && <span className={cx(tono && colores[tono])}>{icono}</span>}
        {etiqueta}
      </div>
      <div className="font-display tabular mt-2 text-[32px] leading-none font-semibold tracking-tight">{valor}</div>
      {detalle && <div className="mt-2 text-[13px] text-label-2">{detalle}</div>}
    </Card>
  );
}
