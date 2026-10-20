#!/usr/bin/env python3
"""PRD 7.2 T1~T4 HTTP 검증 스크립트.

사용법 (ALB 주소 하나 또는 백엔드 여러 대를 라운드로빈):
    python scripts/verify_e2e.py --base http://<ALB-DNS> --admin-token $ADMIN_TOKEN
    python scripts/verify_e2e.py --base http://10.0.10.11:8000 --base http://10.0.10.12:8000 ...

의존성: httpx (backend/requirements-dev.txt 에 포함)
"""
import argparse
import statistics
import sys
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from itertools import cycle

import httpx


def pctl(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    k = max(0, min(len(values) - 1, round(p / 100 * (len(values) - 1))))
    return values[k]


class Runner:
    def __init__(self, bases, admin_token, event_id, workers):
        self.bases = bases
        self._rr = cycle(bases)
        self.admin = {"X-Admin-Token": admin_token}
        self.event_id = event_id
        self.workers = workers
        self.client = httpx.Client(timeout=15.0, limits=httpx.Limits(max_connections=workers * 2))
        self.failed = False

    def base(self):
        return next(self._rr)

    def check(self, name, ok, detail=""):
        mark = "PASS" if ok else "FAIL"
        if not ok:
            self.failed = True
        print(f"  [{mark}] {name} {detail}")

    def reset(self, qty):
        r = self.client.post(
            f"{self.bases[0]}/api/ops/reset-event",
            json={"event_id": self.event_id, "total_qty": qty},
            headers=self.admin,
        )
        r.raise_for_status()
        for b in self.bases[1:]:  # 인스턴스 로컬 카운터도 비운다
            self.client.post(f"{b}/api/ops/counters/reset", headers=self.admin)

    def stats(self):
        r = self.client.get(
            f"{self.bases[0]}/api/ops/stats", params={"event_id": self.event_id}, headers=self.admin
        )
        r.raise_for_status()
        return r.json()

    def issue(self, user_id):
        url = f"{self.base()}/api/events/{self.event_id}/issue"
        try:
            r = self.client.post(url, json={"userId": user_id})
            return r.status_code, r.headers.get("X-Served-By", "?")
        except httpx.HTTPError as exc:
            return f"ERR:{type(exc).__name__}", "?"

    def burst(self, user_ids):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            results = list(ex.map(self.issue, user_ids))
        elapsed = time.perf_counter() - started
        codes = Counter(c for c, _ in results)
        servers = Counter(s for _, s in results)
        return codes, servers, elapsed

    # ---- 시나리오 ----
    def t1_smoke(self):
        print("\nT1 Smoke: 재고 조회 1회 + 발급 1건")
        self.reset(100)
        b = self.base()
        r = self.client.get(f"{b}/api/events/{self.event_id}")
        self.check("GET /api/events/{id} 200", r.status_code == 200, r.text)
        user = f"smoke-{uuid.uuid4().hex[:8]}"
        r = self.client.post(f"{b}/api/events/{self.event_id}/issue", json={"userId": user})
        self.check("POST issue 201", r.status_code == 201, r.text)
        r = self.client.get(f"{b}/api/users/{user}/coupons")
        self.check("GET user coupons count=1", r.json().get("count") == 1)
        self.check("DB 신규 1건", self.stats()["db"]["issued_count"] == 1)

    def t2_duplicate(self, n=100):
        print(f"\nT2 Duplicate: 동일 userId 동시 {n}회")
        self.reset(100)
        codes, servers, elapsed = self.burst(["dup-user-0001"] * n)
        print(f"  응답 코드={dict(codes)} 분산={dict(servers)} {elapsed:.2f}s")
        db = self.stats()["db"]
        self.check("201 == 1", codes.get(201, 0) == 1)
        self.check(f"409 == {n - 1}", codes.get(409, 0) == n - 1)
        self.check("DB 1건", db["issued_count"] == 1, f"(db={db})")

    def t3_soldout(self, stock=100, users=500):
        print(f"\nT3 Sold-out: 재고 {stock}, 서로 다른 userId {users}명")
        self.reset(stock)
        ids = [f"user-{i:05d}" for i in range(users)]
        codes, servers, elapsed = self.burst(ids)
        print(f"  응답 코드={dict(codes)} 분산={dict(servers)} {elapsed:.2f}s")
        db = self.stats()["db"]
        self.check(f"201 == {stock}", codes.get(201, 0) == stock)
        self.check(f"410 == {users - stock}", codes.get(410, 0) == users - stock)
        self.check(f"DB {stock}건 / 재고 0", db["issued_count"] == stock and db["remaining_qty"] == 0,
                   f"(db={db})")
        other = {k: v for k, v in codes.items() if k not in (201, 410)}
        self.check("예상 밖 응답 0건", not other, f"{other}")

    def t4_cache(self, n=300):
        print(f"\nT4 Cache: 재고 조회 {n}회, 캐시 On/Off 비교")
        out = {}
        for enabled in (True, False):
            for b in self.bases:
                self.client.post(f"{b}/api/ops/cache", json={"enabled": enabled}, headers=self.admin)
            self.reset(100)
            lat, sources = [], Counter()
            for _ in range(n):
                t = time.perf_counter()
                r = self.client.get(f"{self.base()}/api/events/{self.event_id}")
                lat.append((time.perf_counter() - t) * 1000)
                sources[r.json().get("source")] += 1
            out[enabled] = (statistics.mean(lat), pctl(lat, 95), dict(sources))
            label = "ON " if enabled else "OFF"
            print(f"  캐시 {label}: avg={out[enabled][0]:.2f}ms p95={out[enabled][1]:.2f}ms "
                  f"source={out[enabled][2]}")
        for b in self.bases:  # 원상 복구
            self.client.post(f"{b}/api/ops/cache", json={"enabled": True}, headers=self.admin)
        self.check("캐시 ON 일 때 cache hit 발생", out[True][2].get("cache", 0) > 0)
        self.check("캐시 OFF 일 때 전부 db", out[False][2].get("cache", 0) == 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", action="append", required=True, help="ALB 또는 백엔드 주소 (반복 가능)")
    ap.add_argument("--admin-token", required=True)
    ap.add_argument("--event-id", type=int, default=1)
    ap.add_argument("--workers", type=int, default=50)
    ap.add_argument("--only", default="t1,t2,t3,t4")
    args = ap.parse_args()

    r = Runner([b.rstrip("/") for b in args.base], args.admin_token, args.event_id, args.workers)
    only = set(args.only.split(","))
    if "t1" in only:
        r.t1_smoke()
    if "t2" in only:
        r.t2_duplicate()
    if "t3" in only:
        r.t3_soldout()
    if "t4" in only:
        r.t4_cache()
    print("\n결과:", "ALL PASS" if not r.failed else "FAILED")
    sys.exit(1 if r.failed else 0)


if __name__ == "__main__":
    main()
