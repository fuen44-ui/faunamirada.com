# Pendiente

## Para dejar en producción lo ya hecho
- [ ] Commit + push de todo lo desarrollado en esta sesión: migración a R2,
      login admin, ajustes, productos/calculadora de márgenes, ofertas,
      carrito + checkout con Stripe, protección de imágenes, calendario y
      pegatinas añadidos al catálogo.
- [ ] Desplegar en Coolify y comprobar que arranca bien (puede volver a pasar
      lo de la BD con esquema viejo si hay datos reales — mirar `docs/`
      antes de tocar la BD de producción).
- [ ] Cambiar la contraseña de admin por defecto (`faunamirada2026`) desde
      `/admin/ajustes` en cuanto se despliegue.

## Gelato (proveedor de impresión elegido para probar)
- [ ] Crear cuenta gratuita en dashboard.gelato.com.
- [ ] Sacar la API key (sandbox).
- [ ] Sacar el `productUid` real de: Calendario, Postal, Pack de pegatinas
      (navegando su catálogo) y rellenarlos en `/admin/productos` → campo
      "ID/variant del proveedor".
- [ ] Completar en `proveedores.py` la implementación real de
      `ProveedorGelato.crear_pedido()` y `.consultar_precio()` (ahora mismo
      lanzan `NotImplementedError` a propósito, ver `docs/TIENDA.md`).

## Precios y catálogo
- [ ] Rellenar precio de coste real, IVA y transporte de cada producto en
      `/admin/productos` (ahora están a 0 salvo la taza de prueba). El
      margen y la ganancia total se calculan solos en cuanto se rellenen.
- [ ] Sustituir las imágenes de marcador de posición (`placehold.co`) de
      Calendario y Pegatinas por fotos reales del producto.
- [ ] Crear las ofertas/combos reales en `/admin/ofertas` una vez los
      precios de coste estén ajustados (para que el precio del combo tenga
      margen de verdad).

## Pagos
- [ ] Crear cuenta de Stripe (si no existe ya) y poner sus claves reales en
      `/admin/ajustes`.
- [ ] Configurar el webhook `https://faunamirada.com/webhook/stripe` en el
      dashboard de Stripe (evento `checkout.session.completed`) y copiar el
      "Signing secret" a Ajustes.
- [ ] Probar una compra real de principio a fin en producción.

## DNS / infraestructura (menor)
- [ ] Añadir CNAME `www` → `faunamirada.com` en Cloudflare si se quiere que
      "www.faunamirada.com" funcione también.
- [ ] Borrar los TXT `_railway-verify` en Cloudflare (ya no se usa Railway).
- [ ] Cuando el tráfico de imágenes crezca, conectar un dominio propio
      (p. ej. `img.faunamirada.com`) al bucket R2 en vez del `pub-xxxx.r2.dev`
      de desarrollo (ver `docs/ALMACENAMIENTO.md`).

## Posible trabajo futuro (no urgente)
- [ ] Roles diferenciados admin/gestor (ahora mismo hay una sola contraseña
      compartida sin distinción de permisos).
- [ ] Automatizar la comprobación de precio del proveedor (ahora es manual,
      un botón por producto) con una tarea programada periódica.
