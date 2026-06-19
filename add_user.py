#!/usr/bin/env python3
"""Da de alta o actualiza un agente del portal RE/MAX Life en users.json.

La contraseña se pide de forma interactiva (no queda en el historial del shell)
y se guarda HASHEADA con bcrypt — nunca en texto plano.

Uso:
    python add_user.py            # interactivo (recomendado)
    python add_user.py --list     # lista los agentes existentes (con su email)
    python add_user.py --remove   # elimina un agente

El alta pide el email (con un default nombre.apellido@remax-life.com.pa). Ese
email es la llave del SSO al módulo de Comisiones (portal Altia).

Tras crear/editar agentes, vuelve a desplegar el backend:
    railway up
"""
import json
import os
import re
import sys
import unicodedata
import getpass

import bcrypt

USERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
MIN_LEN = 8
EMAIL_DOMAIN = "remax-life.com.pa"


def _slug(text):
    """Minúsculas sin acentos ni símbolos (para construir el email)."""
    norm = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", norm.lower())


def derive_email(name):
    """nombre.apellido@remax-life.com.pa a partir del nombre para mostrar.
    Usa el primer y el último token (ignora iniciales del medio, p.ej.
    "Pedro G. Alvarado" -> pedro.alvarado)."""
    tokens = [s for s in (_slug(p) for p in name.split()) if s]
    if not tokens:
        return ""
    local = tokens[0] if len(tokens) == 1 else f"{tokens[0]}.{tokens[-1]}"
    return f"{local}@{EMAIL_DOMAIN}"


def load():
    try:
        with open(USERS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {}
    data.setdefault("agents", {})
    return data


def save(data):
    with open(USERS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def cmd_list():
    data = load()
    agents = data["agents"]
    if not agents:
        print("No hay agentes registrados.")
        return
    print(f"Agentes ({len(agents)}):")
    for username, info in sorted(agents.items()):
        tag = "  [admin]" if info.get("admin") else ""
        email = info.get("email", "⚠ SIN EMAIL")
        print(f"  - {username}  ({info.get('name', username)})  <{email}>{tag}")


def cmd_remove():
    data = load()
    username = input("Usuario a eliminar: ").strip().lower()
    if username in data["agents"]:
        del data["agents"][username]
        save(data)
        print(f"Eliminado: {username}. Total: {len(data['agents'])}. Recuerda: railway up")
    else:
        print(f"No existe el usuario '{username}'.")


def cmd_add():
    data = load()
    username = input("Usuario (login, sin espacios): ").strip().lower()
    if not username or " " in username:
        print("Usuario inválido (sin espacios, no vacío).")
        sys.exit(1)
    name = input("Nombre para mostrar: ").strip() or username
    # El email es la llave que une al agente del Hub con su cuenta de Comisiones
    # (SSO al portal Altia). Se ofrece un default derivado del nombre.
    default_email = derive_email(name)
    prompt = f"Email para SSO/comisiones [{default_email}]: " if default_email else "Email para SSO/comisiones: "
    email = input(prompt).strip().lower() or default_email
    if not email:
        print("El email es obligatorio (lo usa el SSO a Comisiones).")
        sys.exit(1)
    is_admin = input("¿Es administrador? (ve el historial de TODOS) [s/N]: ").strip().lower() in ("s", "si", "sí", "y", "yes")
    pw1 = getpass.getpass("Contraseña: ")
    pw2 = getpass.getpass("Repite la contraseña: ")
    if pw1 != pw2:
        print("Las contraseñas no coinciden.")
        sys.exit(1)
    if len(pw1) < MIN_LEN:
        print(f"La contraseña debe tener al menos {MIN_LEN} caracteres.")
        sys.exit(1)
    h = bcrypt.hashpw(pw1.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    existed = username in data["agents"]
    data["agents"][username] = {"name": name, "email": email, "hash": h, "admin": is_admin}
    save(data)
    print(f"{'Actualizado' if existed else 'Creado'}: {username} ({name}){' [admin]' if is_admin else ''}")
    print(f"Total agentes: {len(data['agents'])}")
    print("No olvides desplegar: railway up")


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("--list", "-l"):
        cmd_list()
    elif arg in ("--remove", "-r"):
        cmd_remove()
    else:
        cmd_add()


if __name__ == "__main__":
    main()
