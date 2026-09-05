# Almacenamiento de imágenes: Cloudflare R2

## Por qué se cambió de Cloudinary a R2

Cloudinary factura principalmente por **ancho de banda y transformaciones**, no por
espacio ocupado. Para una tienda de postales/productos impresos bajo demanda, ese
modelo escala mal: el plan gratuito se queda corto en cuanto hay tráfico real, y el
siguiente escalón (plan "Plus") cuesta del orden de 89$/mes solo por almacenamiento
e imágenes, con planes superiores por encima de 200$/mes.

Cloudflare R2 es almacenamiento compatible con S3 que **no cobra por tráfico de
salida (egress)** — el coste que realmente disparaba la factura de Cloudinary. Solo
se paga por GB almacenado (~$0.015/GB/mes) y por operaciones de lectura/escritura,
que para el volumen de esta web (obras de arte subidas manualmente, no un carrete
infinito) son céntimos al mes. Además ya usábamos Cloudflare para el DNS del
dominio, así que no añade un proveedor nuevo a gestionar.

Las miniaturas ya no las genera un servicio externo: se generan en el propio
servidor con Pillow al subir la obra (`generar_miniatura()` en `app.py`).

## Qué se necesita para producción de postales

Las imágenes originales que se suben son las mismas que luego se envían a un
proveedor de impresión bajo demanda (Printful, Gelato, Prodigi...) para imprimirlas
sobre el producto físico. Para que quede nítido hace falta ~300 DPI al tamaño físico
del producto:

| Producto          | Resolución mínima aprox. |
|--------------------|---------------------------|
| Postal (15×10cm)  | ~1800×1200 px             |
| Taza              | ~2500×1000 px             |
| Camiseta          | ~4500×5400 px             |

Cualquier foto/ilustración digital moderna (12+ megapíxeles) cubre esto de sobra.
No hay que redimensionar antes de subir: se guarda el original en R2 para impresión
y se genera aparte una miniatura ligera (800px) para verla en la web.

## Configuración

### Bucket R2
- Nombre: `faunamirada`
- Acceso público activado vía **Public Development URL** (`pub-xxxx.r2.dev`).
  - Nota: Cloudflare marca ese dominio como pensado para desarrollo. Si el
    tráfico crece, conviene conectar un dominio propio (p. ej.
    `img.faunamirada.com`) al bucket desde R2 → Settings → Custom Domains.
- API Token con permiso "Object Read & Write" limitado a este bucket
  (Cloudflare dashboard → R2 Object Storage → Manage R2 API Tokens).

### Variables de entorno (`.env` en local, panel de Coolify en producción)

```
R2_ACCOUNT_ID=<id de cuenta de Cloudflare>
R2_ACCESS_KEY_ID=<access key del token R2>
R2_SECRET_ACCESS_KEY=<secret key del token R2>
R2_ENDPOINT_URL=https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
R2_BUCKET_NAME=faunamirada
R2_PUBLIC_URL=https://pub-xxxxxxxx.r2.dev
```

`R2_ENDPOINT_URL` es el endpoint S3 del token (aparece al crearlo, "Default"
jurisdiction). `R2_PUBLIC_URL` es la URL pública del bucket, sin barra final.

### Cómo funciona en el código (`app.py`)

- `s3` es un cliente `boto3` apuntando al endpoint S3 de R2 (`region_name='auto'`,
  `signature_version='s3v4'`).
- `subir_a_r2(datos, key, content_type)` sube unos bytes al bucket y devuelve la
  URL pública (`R2_PUBLIC_URL/<key>`).
- `generar_miniatura(imagen_bytes)` usa Pillow para crear una miniatura JPEG de
  800px de lado máximo — solo para imágenes, los vídeos no necesitan miniatura
  porque las plantillas ya los muestran con `<video>` directamente.
- Cada `Obra` guarda `archivo_key` (y `thumbnail_key` si es imagen) para poder
  borrar ambos objetos del bucket cuando se elimina la obra (`/eliminar/<id>`).

## Migración desde Cloudinary (histórico)

Los campos del modelo `Obra` se renombraron de `cloudinary_url` /
`cloudinary_public_id` a `archivo_url` / `archivo_key` para que reflejen el
proveedor real. No hubo migración de datos porque el cambio se hizo antes de
tener obras reales en producción.
