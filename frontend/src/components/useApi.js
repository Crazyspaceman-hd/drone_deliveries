import { useEffect, useState } from 'react';

/** Minimal fetch hook: returns { data, error, loading }. */
export function useApi(fetcher, deps = []) {
  const [data,    setData]    = useState(null);
  const [error,   setError]   = useState(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let canceled = false;
    setLoading(true);
    setError(null);
    fetcher()
      .then((d) => { if (!canceled) setData(d); })
      .catch((e) => { if (!canceled) setError(e.message || String(e)); })
      .finally(() => { if (!canceled) setLoading(false); });
    return () => { canceled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error, loading };
}
