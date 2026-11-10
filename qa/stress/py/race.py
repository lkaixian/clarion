"""Live-URL burst tool. N identical requests released together by an asyncio barrier.

  python race.py --url https://host --token JWT --method POST --path /payments/webhook/mock \
      --json '{"x":1}' -n 20 --expect-single-success

Library: `burst(method, url, n, **httpx_kwargs)` -> list[httpx.Response | Exception].
"""
import argparse
import asyncio
import collections
import json
import sys

import httpx

try:
    import h2  # noqa: F401
    _H2 = True
except ImportError:  # http/1.1 still works, bursts are just a little less tight
    _H2 = False


async def burst(method, url, n, *, verify=False, timeout=30, per_request=None, **kw):
    """Fire n requests at once. per_request(i) -> extra kwargs (e.g. a distinct header/body) for request i."""
    async with httpx.AsyncClient(http2=_H2, verify=verify, timeout=timeout,
                                 limits=httpx.Limits(max_connections=max(n, 1))) as c:
        go = asyncio.Event()

        async def one(i):
            await go.wait()
            try:
                return await c.request(method, url, **{**kw, **(per_request(i) if per_request else {})})
            except Exception as exc:  # noqa: BLE001
                return exc

        tasks = [asyncio.create_task(one(i)) for i in range(n)]
        await asyncio.sleep(0.2)  # let every task park on the gate
        go.set()
        return await asyncio.gather(*tasks)


def run(method, url, n, **kw):
    return asyncio.run(burst(method, url, n, **kw))


def histogram(results):
    return collections.Counter(r.status_code if isinstance(r, httpx.Response) else type(r).__name__ for r in results)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="base URL, e.g. https://clarion.example")
    ap.add_argument("--token", default="", help="Bearer access token")
    ap.add_argument("--method", default="POST")
    ap.add_argument("--path", required=True)
    ap.add_argument("--json", default=None, help="JSON body")
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--expect-single-success", action="store_true", help="exit 1 unless exactly one 2xx")
    a = ap.parse_args(argv)
    headers = {"Authorization": f"Bearer {a.token}"} if a.token else {}
    kw = {"headers": headers}
    if a.json:
        kw["json"] = json.loads(a.json)
    res = run(a.method, a.url.rstrip("/") + a.path, a.n, **kw)
    h = histogram(res)
    print("status histogram:", dict(sorted(h.items(), key=lambda kv: str(kv[0]))))
    if a.expect_single_success:
        ok = sum(v for k, v in h.items() if isinstance(k, int) and 200 <= k < 300)
        print(f"2xx = {ok} -> {'PASS' if ok == 1 else 'FAIL'}")
        return 0 if ok == 1 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
