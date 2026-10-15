import http from 'k6/http';
import { sleep } from 'k6';

// Steady background traffic so incidents have something to show up in.
export const options = { vus: 10, duration: '72h' };

export default function () {
  http.get('http://app:8000/api/orders');
  sleep(0.1);
}
