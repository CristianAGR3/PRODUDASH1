"""Manual publication to GitHub; credentials stay on the Windows PC."""
import base64
import ctypes
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULTS = {"repository": "CristianAGR3/PRODUDASH1", "branch": "main",
            "dashboard_url": "https://produdash.pages.dev/", "token_encrypted": "", "db_path": ""}
SETTINGS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.cwd()))) / "PRODU Control"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


class Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(text, decrypt=False):
    if os.name != "nt":
        raise ValueError("Guardar credenciales requiere Windows.")
    raw = base64.b64decode(text) if decrypt else text.encode("utf-8")
    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dest = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    func.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                     ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    func.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not func(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise ValueError("Windows no pudo guardar/abrir la credencial. Introduce el token otra vez.")
    try:
        result = ctypes.string_at(dest.data, dest.size)
        return result.decode("utf-8") if decrypt else base64.b64encode(result).decode("ascii")
    finally:
        kernel.LocalFree(dest.data)


def load_settings():
    if SETTINGS_FILE.exists():
        return {**DEFAULTS, **json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))}
    return dict(DEFAULTS)


def save_settings(settings):
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)


class SyncError(Exception):
    pass


class Publisher:
    def __init__(self, repository, branch, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("El repositorio debe tener el formato propietario/repositorio.")
        if not branch.strip():
            raise ValueError("La rama es obligatoria.")
        if not token.strip():
            raise ValueError("Configura un token de GitHub con permiso Contents: Read and write.")
        self.repository, self.branch, self.token = repository, branch, token.strip()
        self.url = f"https://api.github.com/repos/{repository}/contents/data/produccion.json"

    def request(self, url, data=None):
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8") if data is not None else None,
                                     method="PUT" if data is not None else "GET",
                                     headers={"Authorization": f"Bearer {self.token}",
                                              "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28",
                                              "Content-Type": "application/json", "User-Agent": "PRODU-Control/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=35) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            explanations = {401: "El token es inválido o expiró.",
                            403: "GitHub rechazó el acceso. Revisa Contents: Read and write, restricciones de rama o límite de API.",
                            404: "No se encontró el repositorio, archivo o rama. Revisa la configuración y el acceso del token.",
                            409: "El dashboard cambió durante la subida. Actualiza e inténtalo otra vez.",
                            422: "GitHub no aceptó la actualización. Revisa la rama y sus reglas."}
            raise SyncError(explanations.get(exc.code, f"GitHub respondió con error {exc.code}.")) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SyncError("No se pudo conectar con GitHub. Tus pedidos siguen guardados; reintenta cuando tengas Internet.") from None

    def publish(self, snapshot, last_sha="", allow_replace=False):
        remote = self.request(self.url + "?ref=" + urllib.parse.quote(self.branch, safe=""))
        sha = remote["sha"]
        if remote.get("encoding") != "base64" or not remote.get("content"):
            raise SyncError("El archivo remoto supera el tamaño compatible con esta versión o no es un JSON válido.")
        try:
            current = json.loads(base64.b64decode(remote["content"]))
        except (ValueError, UnicodeDecodeError):
            raise SyncError("El archivo publicado no contiene un JSON válido.") from None
        meta = current.get("meta", {})
        local_id = snapshot["meta"]["databaseId"]
        if meta.get("databaseId") and meta["databaseId"] != local_id and not allow_replace:
            raise SyncError("El dashboard pertenece a otra base de datos. Si esta base debe sustituirla, marca la opción de sustitución en Configuración.")
        if meta.get("databaseId") == local_id and int(meta.get("revision", -1)) > snapshot["meta"]["revision"] and not allow_replace:
            raise SyncError("El dashboard tiene una versión más reciente de esta base. Abre la base actual antes de subir.")
        if last_sha and sha != last_sha and not allow_replace:
            raise SyncError("El archivo del dashboard cambió fuera de este programa. Revisa la base y usa la opción de sustitución solo si corresponde.")
        if not meta.get("databaseId") and current.get("orders") and not allow_replace:
            raise SyncError("Hay datos anteriores en el dashboard. Para sustituirlos, activa la opción de sustitución en Configuración.")
        payload = {"message": f"Actualizar pedidos desde SQLite · revisión {snapshot['meta']['revision']}",
                   "content": base64.b64encode(json.dumps(snapshot, ensure_ascii=False, indent=2).encode("utf-8")).decode("ascii"),
                   "sha": sha, "branch": self.branch}
        response = self.request(self.url, payload)
        return response["content"]["sha"]
