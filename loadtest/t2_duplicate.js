// T2 Duplicate: 동일 userId 동시 100회 → 201 1건 / 409 99건
// 사전 초기화: POST /api/ops/reset-event (README 참고)
//   k6 run -e BASE=http://<ALB-DNS> loadtest/t2_duplicate.js
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

const BASE = __ENV.BASE || 'http://localhost:8000';
const s201 = new Counter('status_201');
const s409 = new Counter('status_409');
const sOther = new Counter('status_other');

export const options = {
  scenarios: {
    dup: { executor: 'shared-iterations', vus: 100, iterations: 100, maxDuration: '30s' },
  },
  thresholds: {
    status_201: ['count==1'],
    status_409: ['count==99'],
    status_other: ['count==0'],
  },
};

export default function () {
  const res = http.post(
    `${BASE}/api/events/1/issue`,
    JSON.stringify({ userId: 'dup-user-0001' }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'issue' } },
  );
  if (res.status === 201) s201.add(1);
  else if (res.status === 409) s409.add(1);
  else sOther.add(1);
  check(res, { '201 or 409': (r) => r.status === 201 || r.status === 409 });
}
