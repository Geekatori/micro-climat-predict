#!/usr/bin/env python3
"""Relais TCP brut pour tester la stack sous Docker Desktop / WSL2.

Docker Desktop en mode réseau miroir ne peut pas joindre le LAN (192.168.1.x), mais
il joint l'hôte WSL via host.docker.internal. Ce script écoute sur l'hôte WSL et relaie
chaque connexion vers Home Assistant sur le LAN. Le TLS traverse tel quel : le conteneur
voit toujours le nom d'hôte de HA, le certificat reste valide.

Inutile sur Unraid, où les conteneurs joignent le LAN directement.

Usage : python3 scripts/wsl-ha-relay.py <cible_ip:port> [port_ecoute]
        (cible lisible aussi dans HA_LAN_TARGET, port d'écoute 8123 par défaut)
"""
import asyncio
import os
import sys

target = sys.argv[1] if len(sys.argv) > 1 else os.getenv("HA_LAN_TARGET", "")
if not target:
    sys.exit("cible manquante : passer ip:port en argument ou définir HA_LAN_TARGET")
listen_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8123
t_host, t_port = target.rsplit(":", 1)


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def handle(client_r, client_w):
    try:
        remote_r, remote_w = await asyncio.open_connection(t_host, int(t_port))
    except OSError as e:
        print(f"connexion vers {target} impossible : {e}", file=sys.stderr)
        client_w.close()
        return
    await asyncio.gather(pipe(client_r, remote_w), pipe(remote_r, client_w))


async def main():
    server = await asyncio.start_server(handle, "0.0.0.0", listen_port)
    print(f"relais 0.0.0.0:{listen_port} -> {target}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
