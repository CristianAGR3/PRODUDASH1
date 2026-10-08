# PRODU Control 1.0

Aplicación portable de Windows de 64 bits para administrar pedidos de producción con SQLite. El ejecutable incluye Python: no necesitas instalar Python, Excel ni un servidor MySQL.

## Primer uso

1. Extrae completamente el ZIP en una carpeta donde puedas guardar archivos, por ejemplo Documentos/PRODU Control. No ejecutes el programa dentro del ZIP.
2. Abre `PRODU_Control.exe`. El archivo `pedidos.db` entregado está vacío. Si no existe, el programa crea una base vacía junto al ejecutable.
3. Pulsa **Nuevo pedido** e introduce ticket, cliente y operador. La fecha/hora se guarda automáticamente y se muestra en horario de Ciudad de México.
4. Selecciona un pedido y pulsa **Editar / estatus**, o haz doble clic. Los estatus disponibles son En proceso, En resguardo, Terminado y Entregado a cliente. Puedes corregir datos y regresar un pedido a un estatus anterior; el historial conserva el cambio.
5. Usa el buscador y los filtros de operador, estatus y fecha de registro. Escribe las fechas como AAAA-MM-DD. Los conteos y la pestaña Análisis usan la vista filtrada.

**Pendientes de entrega = todos los pedidos que todavía no están Entregados a cliente**, incluidos los terminados. El ranking muestra pendientes, total y cada estatus por operador o cliente. Entregas por día cuenta los pedidos actualmente entregados en su fecha de entrega. Al reabrir un pedido, deja de contar como entregado; la entrega anterior queda en el historial.

Los tickets son únicos, conservan ceros iniciales y pueden contener letras. No se importan los pedidos antiguos de Excel. Las observaciones son opcionales y permanecen en la base local. No se incluye un botón para borrar pedidos.

## Conectar el dashboard

El repositorio de destino es `CristianAGR3/PRODUDASH1`, rama `main`. El dashboard se abre en https://produdash.pages.dev/.

1. En Configuración, pulsa **Crear token** e inicia sesión tú mismo en GitHub.
2. Crea un **fine-grained personal access token** (token específico), elige a CristianAGR3 como propietario del recurso y selecciona solamente PRODUDASH1. En permisos de repositorio, asigna **Contents: Read and write**. Metadata queda como permiso de lectura obligatorio. Define la caducidad que corresponda.
3. Copia el token y pégalo en el campo del programa. No lo compartas por chat ni lo incluyas en archivos del repositorio.
4. Opcionalmente activa Recordar token. Windows lo cifra para tu cuenta mediante DPAPI y lo guarda en `%LOCALAPPDATA%/PRODU Control/settings.json`. Sin esa opción, tendrás que introducirlo otra vez al abrir el programa.
5. Guarda la configuración y pulsa **Subir a dashboard**. Revisa el total que se publicará y confirma.

La subida publica una copia completa en `data/produccion.json`; los filtros no limitan la información publicada. El programa funciona sin Internet; solo la subida necesita conexión. El dashboard actualizado consulta el JSON de GitHub cada 30 segundos mientras está visible. La caché/CDN de GitHub y el despliegue de Cloudflare pueden añadir demora. El mensaje de subida completada confirma la recepción por GitHub, no el despliegue de Cloudflare.

**El repositorio es público.** Tickets, clientes, operadores, estatus y fechas estarán visibles en Internet. El token, las observaciones y el archivo SQLite no se publican. El dashboard es de consulta; los cambios se realizan en el programa de Windows.

Si el dashboard pertenece a otra base, existe una versión más nueva o el JSON cambió fuera del programa, se bloquea la sustitución para evitar perder información. Después de revisar cuál base es la correcta, puedes marcar **Permitir sustituir datos de otra base en la próxima subida**; se desmarca tras una subida exitosa. Cada copia del paquete comienza vacía; usa una sola base de producción como fuente de publicación. Copiar o respaldar la base conserva su identificador.

Si GitHub rechaza la subida, revisa el token, su vencimiento, el repositorio elegido, el permiso Contents y las reglas de la rama. Los pedidos locales permanecen guardados. Cuando caduque el token, reemplázalo en Configuración.

## Respaldos y reportes

- En Configuración, **Crear respaldo .db** guarda pedidos e historial en un archivo nuevo. La copia es consistente incluso si la base usa archivos temporales WAL.
- **Abrir otra base .db** permite trabajar con una base existente o un respaldo compatible. El programa recuerda esa ruta; la base original permanece en su carpeta.
- **Exportar CSV** exporta la vista actual, incluidas las observaciones, con formato compatible con Excel. Esto es un reporte y no una dependencia de Excel.
- Si copias manualmente la base, cierra todas las instancias del programa primero. Conserva el archivo `.db`: contiene tus pedidos. El programa puede crear archivos auxiliares `.db-wal` y `.db-shm` mientras está abierto.

Atajos: Ctrl+N nuevo pedido, Ctrl+F buscar, F5 actualizar la vista, Ctrl+Enter guardar en el formulario y Esc cancelar el formulario.

## Código y validación

El código Python está en esta carpeta. Para modificarlo, instala Python de 64 bits, ejecuta `py -m pip install -r requirements.txt` y después `py app.py`. `build.ps1` genera el ejecutable en `dist`. El paquete utiliza tkinter/ttkbootstrap, SQLite, Pillow y tzdata.

Pruebas: `py -m unittest discover -s . -p test_app.py -v`. El ejecutable admite `--self-test` y termina con código 0 cuando su prueba de guardado/entrega funciona. Todas las pruebas usan bases temporales; no añaden pedidos al archivo entregado.

Los errores técnicos se registran localmente en `%LOCALAPPDATA%/PRODU Control/errores.log`.

Documentación de referencia: [SQLite en Python](https://docs.python.org/3/library/sqlite3.html), [API de contenido de GitHub](https://docs.github.com/en/rest/repos/contents), [tokens de GitHub](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) y [PyInstaller](https://pyinstaller.org/en/stable/usage.html).
