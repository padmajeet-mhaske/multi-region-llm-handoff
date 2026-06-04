"""Configure Toxiproxy to simulate WAN latency between regions."""
import requests
import time


TOXIPROXY_HOST = "localhost"
TOXIPROXY_API_PORT = 8474
BASE_URL = f"http://{TOXIPROXY_HOST}:{TOXIPROXY_API_PORT}"

WAN_LATENCY_MS = 120
PACKET_LOSS_PERCENT = 0.1


def create_proxy(name: str, listen: str, upstream: str) -> bool:
    resp = requests.post(f"{BASE_URL}/proxies", json={
        "name": name,
        "listen": listen,
        "upstream": upstream,
        "enabled": True,
    })
    return resp.status_code in (200, 201, 409)


def add_latency_toxic(proxy_name: str, latency_ms: int, jitter_ms: int = 10) -> bool:
    resp = requests.post(f"{BASE_URL}/proxies/{proxy_name}/toxics", json={
        "name": f"{proxy_name}_latency",
        "type": "latency",
        "stream": "downstream",
        "toxicity": 1.0,
        "attributes": {"latency": latency_ms, "jitter": jitter_ms},
    })
    return resp.status_code in (200, 201)


def add_packet_loss_toxic(proxy_name: str, loss_percent: float) -> bool:
    resp = requests.post(f"{BASE_URL}/proxies/{proxy_name}/toxics", json={
        "name": f"{proxy_name}_loss",
        "type": "bandwidth",
        "stream": "downstream",
        "toxicity": loss_percent / 100.0,
        "attributes": {"rate": 0},
    })
    return resp.status_code in (200, 201)


def setup_wan_simulation():
    print("Setting up Toxiproxy WAN simulation...")

    # Proxy for Redis-A cross-region access (A -> B path)
    create_proxy("redis-a-wan", "0.0.0.0:16379", "redis-region-a:6379")
    add_latency_toxic("redis-a-wan", WAN_LATENCY_MS)

    # Proxy for Redis-B cross-region access (B -> A path)
    create_proxy("redis-b-wan", "0.0.0.0:16380", "redis-region-b:6379")
    add_latency_toxic("redis-b-wan", WAN_LATENCY_MS)

    print(f"WAN simulation active: {WAN_LATENCY_MS}ms latency, ~{PACKET_LOSS_PERCENT}% loss")


def teardown_wan_simulation():
    for proxy in ["redis-a-wan", "redis-b-wan"]:
        requests.delete(f"{BASE_URL}/proxies/{proxy}")
    print("Toxiproxy proxies removed.")


if __name__ == "__main__":
    retries = 5
    for i in range(retries):
        try:
            setup_wan_simulation()
            break
        except requests.exceptions.ConnectionError:
            print(f"Toxiproxy not ready, retrying ({i+1}/{retries})...")
            time.sleep(3)
