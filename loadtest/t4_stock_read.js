// T4 Cache: 재고 조회 반복. 캐시 On/Off 를 바꿔 두 번 실행하고 p95 를 비교한다.
//   curl -X POST -H "X-Admin-Token: $T" -H 'content-type: application/json' \
//        -d '{"enabled":false}' http://<backend>/api/ops/cache   (백엔드 a/b 각각)
//   k6 run -e BASE=http://<ALB-DNS> loadtest/t4_stock_read.js
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const BASE = __ENV.BASE || 'http://localhost:8000';
const fromCache = new Counter('source_cache');
const fromDb = new Counter('source_db');

export const options = {
  vus: 20,
  duration: '30s',
};

export default function () {
  const res = http.get(`${BASE}/api/events/1`, { tags: { name: 'stock' } });
  check(res, { 'status 200': (r) => r.status === 200 });
  if (res.status === 200) {
    if (res.json('source') === 'cache') fromCache.add(1);
    else fromDb.add(1);
  }
}
