# Login, ofertas, carrito y pagos

## Acceso de administración

Se ha añadido un login simple (una sola contraseña compartida, sin roles
distintos todavía) que protege:
- `/subir` y `/eliminar` (gestión de obras)
- `/admin/ofertas` (crear/activar/eliminar combos)
- `/admin/pedidos` (ver pedidos pagados)
- `/admin/ajustes` (proveedor de impresión y claves de Stripe)
- `/admin/productos` (precios, márgenes y coste por producto)

La contraseña inicial se toma de la variable de entorno `ADMIN_PASSWORD` la
primera vez que arranca la app (si no está definida, usa `faunamirada2026`
por defecto — **cámbiala** desde `/admin/ajustes` en cuanto entres la primera
vez). A partir de ahí se guarda como hash en la base de datos y se cambia
desde esa misma pantalla de ajustes, no por variable de entorno.

Es un login de un solo usuario, pensado para proteger la web ya. Si más
adelante hace falta diferenciar "admin" de "gestor" con permisos distintos,
habría que añadir un modelo `Usuario` con roles (más trabajo, no está hecho
todavía).

## Proveedor de impresión intercambiable

`proveedores.py` define una interfaz común (`ProveedorBase.crear_pedido()`)
con tres implementaciones:
- **Simulado** (por defecto): no imprime nada real, solo registra que el
  pedido "se envió a producción". Sirve para probar todo el flujo de compra
  sin tener aún cuenta en ningún sitio.
- **Printful** y **Gelato**: estructura ya creada, pero `crear_pedido()`
  lanza un error explicando qué falta — el mapeo entre nuestros
  `producto_id` (taza, camiseta...) y los variant_id/product UID reales de
  su catálogo, que solo existen una vez tengas cuenta y hayas sincronizado
  productos allí. Cuando llegue ese momento, hay que completar esas dos
  clases con las llamadas reales a su API.

Cuál proveedor está activo (y sus claves API) se elige desde
**`/admin/ajustes`**, no en código ni en variables de entorno — así se puede
cambiar de proveedor o rotar claves sin tocar el servidor ni redeploy.

## Productos y calculadora de márgenes

El catálogo ya no es una lista fija en el código: es la tabla `Producto`,
sembrada una vez con los 5 productos originales (taza, camiseta, sudadera,
bolsa, postal) y editable desde **`/admin/productos`**.

Cada producto tiene 4 precios independientes:
- **PVP** — lo que paga el cliente, con IVA incluido.
- **Coste proveedor** — lo que te cobra Printful/Gelato por esa unidad.
- **IVA %** — para calcular el PVP sin impuestos.
- **Transporte** — coste de envío que asumes tú (si no lo repercutes aparte).

El margen se calcula así y se actualiza al momento al escribir (JavaScript,
sin recargar la página):

```
PVP sin IVA = PVP / (1 + IVA/100)
Margen (€)  = PVP sin IVA − Coste proveedor − Transporte
Margen (%)  = Margen € / PVP sin IVA × 100
```

### Aviso de cambio de precio del proveedor

Cada producto tiene un botón **"Comprobar precio proveedor"** que llama a
`proveedor.consultar_precio(producto)`. Con el proveedor Simulado no hace
nada (no hay proveedor real detrás). Con Printful/Gelato, de momento avisa
de que falta completar la llamada real a su API — necesita que antes
rellenes el campo **"ID/variant del proveedor"** de cada producto (el
identificador que te da su panel al sincronizar el catálogo) y que se
implemente la consulta HTTP correspondiente en `proveedores.py`.

Cuando esa consulta esté implementada: si el coste del proveedor cambió
respecto al que tienes guardado, el producto se marca con `alerta_precio`
(borde rojo y aviso en `/admin/productos`) hasta que revises y actualices el
precio de coste a mano. No hay comprobación automática periódica todavía —
solo al pulsar el botón; si se quiere automatizar (p. ej. una vez al día),
haría falta una tarea programada (cron en Coolify o similar) que llame a
esa misma ruta.

## Ofertas / combos

`/admin/ofertas` permite crear paquetes tipo "3 postales + 1 taza — 24,90€
portes incluidos": nombre, descripción, precio final fijo, si lleva portes
incluidos, y qué productos (y cuántos) incluye. El precio no se calcula
solo — lo pones tú ya calculado (coste real de cada producto en el
proveedor + envío + margen que quieras ganar).

## Carrito y checkout

Carrito en sesión (no hace falta cuenta de cliente para comprar). Al pagar,
se usa **Stripe Checkout** (clave secreta/publicable/webhook configurables
en `/admin/ajustes`, igual que el proveedor de impresión — cambiar de cuenta
de Stripe tampoco requiere tocar código).

Flujo cuando alguien paga:
1. Stripe redirige a `/checkout/exito` y llama a nuestro webhook
   `/webhook/stripe`.
2. El webhook crea un `Pedido` en la base de datos con lo comprado.
3. Se llama al proveedor de impresión activo (`proveedores.obtener_proveedor`)
   para lanzar el pedido a producción. Si algo falla (p. ej. proveedor
   Printful/Gelato sin terminar de configurar), el pedido queda registrado
   con el error en `estado`, visible en `/admin/pedidos`, en vez de perderse.

### Configurar el webhook de Stripe

En el dashboard de Stripe → Developers → Webhooks → añadir endpoint:
`https://faunamirada.com/webhook/stripe`, evento `checkout.session.completed`.
El "Signing secret" que te da Stripe es el `stripe_webhook_secret` de
`/admin/ajustes`.
