#!/usr/bin/env python3
"""Da de alta o actualiza un agente del portal RE/MAX Life en users.json.

La contraseña se pide de forma interactiva (no queda en el historial del shell)
y se guarda HASHEADA con bcrypt — nunca en texto plano.

Uso:
    python add_user.py            # interactivo (recomendado)
    python add_user.py --list     # lista los agentes existentes
    python add_user.py --remove   # elimina un agente

Tras crear/editar agentes, vuelve a desplegar el backend:
    railway up
"""
import json
import os
import sys
import getpass

import bcrypt

USERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
MIN_LEN = 8


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
        print(f"  - {username}  ({info.get('name', username)})")


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
    data["agents"][username] = {"name": name, "hash": h}
    save(data)
    print(f"{'Actualizado' if existed else 'Creado'}: {username} ({name})")
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
