# Dashboard web PRODU

Archivos del dashboard estático/PWA. El dashboard consulta directamente la API de GitHub para evitar la caché atrasada del enlace raw. Se actualiza cada 75 segundos; el botón «Actualizar datos» consulta de inmediato. La página pública y el JSON se actualizan de forma independiente. Los detalles de pedido muestran modalidad (CLIENTE RECOGE/ENVÍO) y ubicación (PISO/TARIMA) cuando se publica una instantánea nueva. La interfaz usa motivos geométricos japoneses sutiles y acentos lilas; el tema oscuro combina negro y lila.

`data/produccion.json` se distribuye vacío como plantilla (`schemaVersion` 4); no contiene los pedidos de producción. Para publicar el código web, actualiza estos archivos en el repositorio conectado a Cloudflare Pages y despliega los cambios.
