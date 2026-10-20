// T3 Sold-out: 재고 100, 서로 다른 userId 500명 → 201 100건 / 410 400건
//   k6 run -e BASE=http://<ALB-DNS> loadtest/t3_soldout.js
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import exec from 'k6/execution';

const BASE = __ENV.BASE || 'http://localhost:8000';
const USERS = parseInt(__ENV.USERS || '500', 10);
const STOCK = parseInt(__ENV.STOCK || '100', 10);
const s201 = new Counter('status_201');
const s410 = new Counter('status_410');
const sOther = new Counter('status_other');

export const options = {
  scenarios: {
    rush: { executor: 'shared-iterations', vus: 100, iterations: USERS, maxDuration: '60s' },
  },
  thresholds: {
    status_201: [`count==${STOCK}`],
    status_410: [`count==${USERS - STOCK}`],
    status_other: ['count==0'],
    'http_req_duration{name:issue}': ['p(95)<2000'],
  },
};

export default function () {
  // iterationInTest 는 0..USERS-1 로 겹치지 않는다 → 사용자 고유 보장
  const userId = `user-${String(exec.scenario.iterationInTest).padStart(5, '0')}`;
  const res = http.post(
    `${BASE}/api/events/1/issue`,
    JSON.stringify({ userId }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'issue' } },
  );
  if (res.status === 201) s201.add(1);
  else if (res.status === 410) s410.add(1);
  else sOther.add(1);
  check(res, { '201 or 410': (r) => r.status === 201 || r.status === 410 });
}
