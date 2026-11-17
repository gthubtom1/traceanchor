"""Bounded loopback HTTP observation, not a crawler or credential/session manager."""
import http.client
import ipaddress
import time
from urllib.parse import urlsplit

from .core import TraceError, digest


def observe(url, *, timeout=5, max_bytes=1048576, cancel=None):
    if not isinstance(url, str) or len(url) > 4096 or not 0 < timeout <= 10 or not 1 <= max_bytes <= 4 * 1024 * 1024:
        raise TraceError('invalid-input', 'HTTP probe has invalid bounded parameters')
    parts = urlsplit(url)
    if parts.scheme != 'http' or parts.username or parts.password or parts.fragment or parts.query:
        raise TraceError('unsupported-http', 'Only credential-free loopback HTTP paths without query/fragment are supported; secrets stay outside evidence')
    try:
        address = ipaddress.ip_address(parts.hostname or '')
    except ValueError as exc:
        raise TraceError('unsupported-http', 'Use a literal loopback IP, not DNS-resolved hostnames') from exc
    if not address.is_loopback:
        raise TraceError('effect-boundary', 'This release samples only explicit loopback test endpoints')
    if cancel is not None and cancel.is_set():
        raise TraceError('cancelled', 'HTTP observation cancelled before connection')
    started = time.monotonic()
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    try:
        connection.request('GET', parts.path or '/', headers={'Accept': '*/*', 'User-Agent': 'TraceAnchor/0.1.0', 'Connection': 'close'})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise TraceError('redirect-refused', 'Redirect was not followed outside the frozen observation path', {'http_status': response.status})
        chunks, total = [], 0
        while total <= max_bytes:
            if cancel is not None and cancel.is_set():
                raise TraceError('cancelled', 'HTTP observation cancelled')
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TraceError('timeout', 'HTTP observation exceeded its total deadline')
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            block = response.read1(min(65536, max_bytes + 1 - total))
            if not block:
                break
            total += len(block)
            chunks.append(block)
        body = b''.join(chunks)
        truncated = len(body) > max_bytes
        body = body[:max_bytes]
        # Do not retain Set-Cookie, auth headers or ambient session identity.
        headers = {k.lower(): v for k, v in response.getheaders() if k.lower() in {'content-type', 'content-length'}}
        return {'status': 'partial' if truncated else 'observed', 'http_status': response.status, 'headers': headers, 'body': body, 'body_sha256': digest(body), 'digest_scope': 'prefix' if truncated else 'complete-response-body', 'truncated': truncated, 'elapsed_seconds': time.monotonic() - started, 'coverage': {'method': 'GET', 'path': parts.path or '/', 'samples': 1}, 'limitations': ['One local response is not a complete service state machine or an authentication proof']}
    except TraceError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise TraceError('observation-unavailable', 'Local HTTP service could not be observed; missing service remains blocked', {'error_type': type(exc).__name__, 'reason': str(exc)}) from exc
    finally:
        connection.close()
