"""Custom DNS resolver to bypass ISP DNS blocking."""
import socket
import logging
from typing import Optional
import dns.resolver

logger = logging.getLogger(__name__)

# Cache resolved IPs to avoid repeated DNS queries
_dns_cache: dict[str, list[str]] = {}


def resolve_with_google_dns(hostname: str, use_cache: bool = True) -> Optional[str]:
    """Resolve hostname using Google DNS (8.8.8.8) to bypass ISP blocking.

    Args:
        hostname: The hostname to resolve
        use_cache: Whether to use cached results

    Returns:
        The first resolved IP address, or None if resolution fails
    """
    if use_cache and hostname in _dns_cache:
        return _dns_cache[hostname][0]

    try:
        # Create a resolver that uses Google DNS
        resolver = dns.resolver.Resolver()
        resolver.nameservers = ['8.8.8.8', '8.8.4.4']
        resolver.timeout = 5.0
        resolver.lifetime = 5.0

        # Query A records (IPv4)
        answers = resolver.resolve(hostname, 'A')
        ips = [str(rdata) for rdata in answers]

        if ips:
            _dns_cache[hostname] = ips
            logger.info(f"Resolved {hostname} to {ips[0]} via Google DNS")
            return ips[0]

        logger.warning(f"No A records found for {hostname}")
        return None

    except Exception as e:
        logger.error(f"Failed to resolve {hostname} via Google DNS: {e}")
        return None


def get_host_ip_mapping() -> dict[str, str]:
    """Get mapping of Polymarket hostnames to their IPs via Google DNS."""
    hosts = [
        'gamma-api.polymarket.com',
        'clob.polymarket.com',
        'data-api.polymarket.com',
    ]

    mapping = {}
    for host in hosts:
        ip = resolve_with_google_dns(host)
        if ip:
            mapping[host] = ip

    return mapping
