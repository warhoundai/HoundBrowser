"""Public-only pinned-DNS egress proxy used by Chromium, including CONNECT tunnels."""
import asyncio
import ipaddress
from urllib.parse import urlsplit

class PublicNetworkError(ValueError):
    pass

def public_url(value: str) -> str:
    try:
        u = urlsplit(value)
        port = u.port
    except (ValueError, TypeError):
        raise PublicNetworkError('Invalid URL')
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password:
        raise PublicNetworkError('Use a public HTTP(S) URL without credentials')
    if port not in (None, 80, 443):
        raise PublicNetworkError('Only standard public web ports are supported')
    host = u.hostname.lower().rstrip('.')
    if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
        raise PublicNetworkError('Private network addresses are unavailable')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise PublicNetworkError('Private network addresses are unavailable')
    return value

def origin(value: str) -> str:
    public_url(value)
    u = urlsplit(value)
    host = u.hostname.lower().rstrip('.')
    host = '[' + host + ']' if ':' in host else host.encode('idna').decode()
    port = u.port or (443 if u.scheme == 'https' else 80)
    return f'{u.scheme}://{host}' + (f':{port}' if port != (443 if u.scheme == 'https' else 80) else '')

async def resolve_public(host: str, port: int):
    if port not in (80, 443):
        raise PublicNetworkError('Port is unavailable')
    public_url(f'http://[{host}]/' if ':' in host else f'http://{host}/')
    rows = await asyncio.get_running_loop().getaddrinfo(host, port, type=__import__('socket').SOCK_STREAM)
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise PublicNetworkError('DNS resolved to a private or unavailable address')
    return addresses

async def relay(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()

class PublicProxy:
    def __init__(self, resolver=resolve_public, connector=asyncio.open_connection):
        self.resolver = resolver
        self.connector = connector
        self.server = None
        self.writers = set()

    async def start(self):
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0, limit=65536)
        return f'http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}'

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in tuple(self.writers):
            writer.close()

    async def handle(self, reader, writer):
        remote = None
        self.writers.add(writer)
        try:
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
            line = header.split(b'\r\n', 1)[0].decode('ascii')
            method, target, version = line.split(' ', 2)
            if method == 'CONNECT':
                parsed = urlsplit('https://' + target)
                host, port = parsed.hostname, parsed.port or 443
            else:
                public_url(target)
                parsed = urlsplit(target)
                host, port = parsed.hostname, parsed.port or 80
                if method not in ('GET', 'HEAD') or parsed.scheme != 'http':
                    raise PublicNetworkError('Method unavailable')
            addresses = await self.resolver(host, port)
            # Connect to the validated numeric address, not the hostname: no DNS re-resolution race.
            remote_reader, remote = await asyncio.wait_for(self.connector(addresses[0], port), 10)
            self.writers.add(remote)
            if method == 'CONNECT':
                writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                await writer.drain()
            else:
                path = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
                lines = [f'{method} {path} {version}'.encode('ascii')]
                for field in header.split(b'\r\n')[1:]:
                    key = field.split(b':', 1)[0].lower()
                    if field and key not in (b'proxy-authorization', b'proxy-connection', b'connection', b'host', b'content-length', b'transfer-encoding'):
                        lines.append(field)
                lines.extend([f'Host: {host}'.encode('idna'), b'Connection: close', b'', b''])
                remote.write(b'\r\n'.join(lines))
                await remote.drain()
            await asyncio.wait_for(asyncio.gather(relay(reader, remote), relay(remote_reader, writer)), 930)
        except Exception:
            if not writer.is_closing():
                try:
                    writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                    await writer.drain()
                except Exception:
                    pass
        finally:
            for item in (writer, remote):
                if item:
                    self.writers.discard(item)
                    item.close()
