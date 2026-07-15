"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { isSecondaryDemoFarm } from "@/lib/farms";

// Active-farm context for the farm-scoped sidebar pages (Operations, Decisions,
// Scouting, Applications, Evidence). Farms come from the real, urgency-ranked
// /farms-overview list; the default active farm is the top-ranked visible one.
// The choice persists in localStorage (read only after mount — SSR-safe).

const STORAGE_KEY = "lumos.activeFarmId";

const FarmContext = createContext({
  farms: [],
  loading: true,
  error: null,
  activeFarm: null,
  setActiveFarmId: () => {},
  refresh: () => {},
});

export function FarmProvider({ children }) {
  const [farms, setFarms] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeFarmId, setActiveFarmIdState] = useState(null);

  const refresh = useCallback(() => {
    return api
      .listFarmsOverview()
      .then((all) => {
        setFarms(all.filter((f) => !isSecondaryDemoFarm(f)));
        setError(null);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    let stored = null;
    try {
      stored = window.localStorage.getItem(STORAGE_KEY);
    } catch {
      /* storage unavailable — fall through to the default */
    }
    if (stored) setActiveFarmIdState(Number(stored));
    refresh();
  }, [refresh]);

  const setActiveFarmId = useCallback((id) => {
    setActiveFarmIdState(id == null ? null : Number(id));
    try {
      if (id == null) window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, String(id));
    } catch {
      /* non-fatal */
    }
  }, []);

  const activeFarm =
    farms.find((f) => f.id === activeFarmId) || (farms.length ? farms[0] : null);

  return (
    <FarmContext.Provider
      value={{ farms, loading, error, activeFarm, setActiveFarmId, refresh }}
    >
      {children}
    </FarmContext.Provider>
  );
}

export function useFarmContext() {
  return useContext(FarmContext);
}
