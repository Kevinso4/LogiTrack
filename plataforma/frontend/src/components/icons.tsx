// Iconografía lineal al estilo SF Symbols (trazo 1.75, esquinas redondeadas).
type P = { className?: string };
const base = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  viewBox: "0 0 24 24",
};

export const IconResumen = ({ className = "size-5" }: P) => (
  <svg {...base} className={className}><rect x="3" y="3" width="7.5" height="9" rx="2" /><rect x="13.5" y="3" width="7.5" height="5" rx="2" /><rect x="13.5" y="11" width="7.5" height="10" rx="2" /><rect x="3" y="15" width="7.5" height="6" rx="2" /></svg>
);
export const IconCamion = ({ className = "size-5" }: P) => (
  <svg {...base} className={className}><path d="M2.5 6.5a1.5 1.5 0 0 1 1.5-1.5h9a1.5 1.5 0 0 1 1.5 1.5V16h-12z" /><path d="M14.5 9h3.6a1.5 1.5 0 0 1 1.2.6l2 2.7a1.5 1.5 0 0 1 .3.9V16h-7.1" /><circle cx="7" cy="17.5" r="1.9" /><circle cx="17.5" cy="17.5" r="1.9" /></svg>
);
export const IconCaja = ({ className = "size-5" }: P) => (
  <svg {...base} className={className}><path d="M12 2.8 20.5 7v10L12 21.2 3.5 17V7z" /><path d="M3.5 7 12 11.2 20.5 7M12 11.2v10M7.8 4.9l8.5 4.3" /></svg>
);
export const IconMapa = ({ className = "size-5" }: P) => (
  <svg {...base} className={className}><path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z" /><circle cx="12" cy="10" r="2.4" /></svg>
);
export const IconLlave = ({ className = "size-5" }: P) => (
  <svg {...base} className={className}><path d="M14.7 6.3a4.5 4.5 0 0 0 5.6 5.6l-8.9 8.9a2.1 2.1 0 0 1-3-3l8.9-8.9" /><path d="M14.7 6.3 17 4l3 3-2.3 2.3" /></svg>
);
export const IconBuscar = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.3-4.3" /></svg>
);
export const IconMas = ({ className = "size-4" }: P) => (
  <svg {...base} className={className} strokeWidth={2}><path d="M12 5v14M5 12h14" /></svg>
);
export const IconCerrar = ({ className = "size-4" }: P) => (
  <svg {...base} className={className} strokeWidth={2}><path d="M6 6l12 12M18 6 6 18" /></svg>
);
export const IconSalir = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><path d="M15 17l5-5-5-5M20 12H9M12 20H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7" /></svg>
);
export const IconAlerta = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><path d="M10.3 3.9 2.4 17.6A2 2 0 0 0 4.1 20.6h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4.5M12 17h.01" /></svg>
);
export const IconCheck = ({ className = "size-4" }: P) => (
  <svg {...base} className={className} strokeWidth={2.2}><path d="m5 12.5 4.5 4.5L19 7.5" /></svg>
);
export const IconChevron = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><path d="m9 6 6 6-6 6" /></svg>
);
export const IconRayo = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><path d="M13 2.5 4.5 13.5H12l-1 8 8.5-11H12z" /></svg>
);
export const IconCopo = ({ className = "size-3.5" }: P) => (
  <svg {...base} className={className}><path d="M12 2v20M4.2 6.5l15.6 11M4.2 17.5l15.6-11M9 3.5l3 2.5 3-2.5M9 20.5l3-2.5 3 2.5" /></svg>
);
export const IconPeligro = ({ className = "size-3.5" }: P) => (
  <svg {...base} className={className}><path d="M12 3 21 12l-9 9-9-9z" /><path d="M12 8.5v4M12 15.5h.01" /></svg>
);
export const IconServidor = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><rect x="3.5" y="4" width="17" height="6.5" rx="2" /><rect x="3.5" y="13.5" width="17" height="6.5" rx="2" /><path d="M7.5 7.3h.01M7.5 16.8h.01" /></svg>
);
export const IconGota = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><path d="M12 3s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11z" /></svg>
);
export const IconTermometro = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z" /></svg>
);
export const IconVelocidad = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><path d="M4.5 18a8.5 8.5 0 1 1 15 0" /><path d="m12 14 4-5" /></svg>
);
export const IconLocalizar = ({ className = "size-4" }: P) => (
  <svg {...base} className={className}><circle cx="12" cy="12" r="7.5" /><circle cx="12" cy="12" r="2.2" /><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22" /></svg>
);
