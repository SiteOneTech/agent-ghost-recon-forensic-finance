// "Only the latest request may apply its result": call next() before each request and check isLatest(token) after
// every await; an older response that lands late is dropped instead of overwriting newer state.
export function latestGuard() {
  let current = 0;
  return {
    next: () => { current += 1; return current; },
    isLatest: (token) => token === current,
  };
}
