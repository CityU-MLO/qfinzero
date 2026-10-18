// Identity headers the hub sets after authenticating a request. API route
// handlers forward them to the services so PMB can scope accounts per user.
const IDENTITY_HEADERS = ["x-qfz-user", "x-qfz-role", "x-qfz-user-id", "x-qfz-session"];

export function identityHeaders(req: Request): Record<string, string> {
  const out: Record<string, string> = {};
  for (const h of IDENTITY_HEADERS) {
    const v = req.headers.get(h);
    if (v) out[h] = v;
  }
  return out;
}
