# PRODU · Pedidos desde SQLite

El dashboard consulta pedidos registrados en la aplicación Windows PRODU Control. Excel ya no es la fuente de datos. La nueva base y la publicación inicial empiezan vacías.

La aplicación está en [`desktop`](desktop/README.md): registro de ticket, cliente y operador; fechas automáticas; historial; estatus En proceso, En resguardo, Terminado y Entregado a cliente; búsqueda; análisis; respaldos y subida manual a GitHub.

`data/produccion.json` es una publicación de consulta, no la base de datos. El botón **Subir a dashboard** de la aplicación actualiza ese archivo en `main`. El dashboard consulta la copia de GitHub cada 30 segundos mientras está visible y permite actualizar manualmente. Conserva una copia local para consultar si falla la conexión e indica la fecha de esa copia. Las observaciones y credenciales permanecen en Windows.

Pendientes significa todos los no entregados. Los gráficos muestran los cuatro estatus y la carga por operador. Tony usa los mismos conteos. Los operadores pueden agruparse sin distinguir mayúsculas y acentos.

El dashboard continúa como sitio estático/PWA. Cloudflare Pages debe estar conectado a este repositorio y a la rama `main` para desplegar los cambios de código. Si el proyecto usa otro repositorio, sube los archivos de este dashboard o corrige la conexión en Cloudflare. El JSON se consulta directamente en PRODUDASH1; el despliegue de código y la subida de pedidos son operaciones distintas.

Validación: `node test-orders-model.js`. Para vista local, ejecuta `py -m http.server 8765 --bind 127.0.0.1` y abre http://127.0.0.1:8765. En localhost se usa el JSON de esta carpeta; en el sitio publicado se consulta GitHub.
