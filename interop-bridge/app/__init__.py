"""Interop Bridge — traducción bidireccional con el Fleet del compañero.

Cierra el seam 2 del PROMPT_INTEGRACION: conecta el exchange propio
(`logitrack.events`) con los del compañero (`logitrack.fleet` y
`logitrack.shipment`) sin tocar el código de ningún servicio. Sin base de
datos: traduce y republica eventos. Su única razón de cambio es el dialecto
externo, que vive entero en `app.interop` y `app.traductor`.
"""
